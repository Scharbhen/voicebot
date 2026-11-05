# Установка голосового ассистента на Windows-сервер.
# Запуск (PowerShell от имени администратора, из папки проекта):
#   powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
# Параметры (все необязательные):
#   -Port 443                     порт HTTPS (если занят — возьмётся 8443)
#   -Proxy http://proxy:3128      если сервер ходит в интернет через корпоративный прокси
#   -PfxPath C:\certs\srv.pfx -PfxPassword ...   сертификат из корпоративного ЦС (тогда без предупреждения в браузере)
# Повторный запуск безопасен: обновит зависимости, сертификат и перезапустит службу.
param(
  [int]$Port = 443,
  [string]$Proxy = "",
  [string]$PfxPath = "",
  [string]$PfxPassword = ""
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

function Step($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "ОШИБКА: $t" -ForegroundColor Red; exit 1 }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Fail "запустите PowerShell от имени администратора" }

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) { Fail "нет файла .env в $Root — скопируйте его со своего компьютера" }
New-Item -ItemType Directory -Force -Path (Join-Path $Root "data") | Out-Null

# .env пишем без BOM — иначе первая переменная не прочитается
function Set-EnvVar($name, $value) {
  $lines = @(Get-Content $EnvFile -Encoding UTF8 | Where-Object { $_ -notmatch "^\s*$name=" })
  $lines += "$name=$value"
  [IO.File]::WriteAllText($EnvFile, ($lines -join "`r`n") + "`r`n", (New-Object Text.UTF8Encoding($false)))
}
function Get-EnvVar($name) {
  $l = Get-Content $EnvFile -Encoding UTF8 | Where-Object { $_ -match "^\s*$name=" } | Select-Object -Last 1
  if ($l) { return ($l -split "=", 2)[1].Trim() } else { return "" }
}

# ---------- прокси ----------
if ($Proxy) {
  Step "Прокси: $Proxy"
  $env:HTTPS_PROXY = $Proxy; $env:HTTP_PROXY = $Proxy
  Set-EnvVar "HTTPS_PROXY" $Proxy
  Set-EnvVar "NO_PROXY" "localhost,127.0.0.1"
}

# ---------- доступ к Яндексу ----------
Step "Проверяю доступ к ai.api.cloud.yandex.net:443"
if (-not $Proxy) {
  $ok = (Test-NetConnection ai.api.cloud.yandex.net -Port 443 -WarningAction SilentlyContinue).TcpTestSucceeded
  if ($ok) { Write-Host "доступ есть" -ForegroundColor Green }
  else { Write-Host "Нет прямого доступа. Если в сети прокси — перезапустите с -Proxy http://адрес:порт" -ForegroundColor Yellow }
} else { Write-Host "через прокси — проверю после установки" }

# ---------- Python ----------
Step "Python 3.10+"
function Find-Python {
  foreach ($c in @("py -3.12", "py -3.11", "py -3", "python")) {
    $exe, $arg = $c -split " ", 2
    try {
      $v = & $exe $arg -c "import sys; print(sys.version_info[:2] >= (3,10), sys.executable)" 2>$null
      if ($v -and $v.StartsWith("True")) { return $v.Substring(5).Trim() }
    } catch {}
  }
  foreach ($p in @("$env:ProgramFiles\Python312\python.exe", "$env:ProgramFiles\Python311\python.exe")) {
    if (Test-Path $p) { return $p }
  }
  return $null
}
$Py = Find-Python
if (-not $Py) {
  Write-Host "Python не найден — устанавливаю 3.12"
  $done = $false
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    try { winget install -e --id Python.Python.3.12 --scope machine --silent --accept-package-agreements --accept-source-agreements; $done = $true } catch {}
  }
  if (-not $done -or -not (Find-Python)) {
    $inst = Join-Path $env:TEMP "python-3.12.7-amd64.exe"
    $wa = @{ Uri = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"; OutFile = $inst; UseBasicParsing = $true }
    if ($Proxy) { $wa.Proxy = $Proxy }
    Invoke-WebRequest @wa
    Start-Process $inst -Wait -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0"
  }
  $Py = Find-Python
  if (-not $Py) { Fail "не удалось установить Python. Установите Python 3.12 вручную (python.org) и запустите скрипт снова" }
}
Write-Host "Python: $Py"

# ---------- окружение и зависимости ----------
Step "Зависимости"
$VPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VPy)) { & $Py -m venv (Join-Path $Root ".venv") }
$pipArgs = @("-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", "requirements.txt", "cryptography")
if ($Proxy) { $pipArgs += @("--proxy", $Proxy) }
& $VPy @pipArgs
if ($LASTEXITCODE -ne 0) { Fail "pip не смог скачать пакеты (нет доступа к pypi.org? тогда нужен -Proxy)" }

# ---------- остановить старую версию, выбрать порт ----------
$TaskName = "Voicebot"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
  Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*uvicorn*app.main:app*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep 2
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
  if ($Port -eq 443) { Write-Host "Порт 443 занят — использую 8443" -ForegroundColor Yellow; $Port = 8443 }
  else { Fail "порт $Port занят другой программой — укажите другой: -Port 8443" }
}

# ---------- сертификат ----------
Step "Сертификат HTTPS"
$Fqdn = [System.Net.Dns]::GetHostEntry("").HostName
$Ips = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
  Select-Object -ExpandProperty IPAddress)
$Names = @($Fqdn, $env:COMPUTERNAME) + $Ips | Select-Object -Unique
$Tls = Join-Path $Root "data\tls"
if ($PfxPath) {
  & $VPy deploy\windows\make_cert.py $Tls --pfx $PfxPath --pfx-password $PfxPassword
} elseif (-not (Test-Path (Join-Path $Tls "cert.pem"))) {
  & $VPy deploy\windows\make_cert.py $Tls --names ($Names -join ",")
} else { Write-Host "уже есть — оставляю (удалите data\tls, чтобы выпустить заново)" }
if ($LASTEXITCODE -ne 0) { Fail "не удалось подготовить сертификат" }

# страница менеджера в сети — только по токену
if (-not (Get-EnvVar "ADMIN_TOKEN")) {
  Set-EnvVar "ADMIN_TOKEN" (-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 16 | ForEach-Object { [char]$_ }))
}
$Url = if ($Port -eq 443) { "https://$Fqdn" } else { "https://${Fqdn}:$Port" }
Set-EnvVar "PUBLIC_BASE_URL" $Url

# ---------- скрипт запуска ----------
$Serve = Join-Path $Root "deploy\windows\serve.cmd"
@"
@echo off
cd /d "$Root"
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port $Port --ssl-keyfile data\tls\key.pem --ssl-certfile data\tls\cert.pem --ws-ping-interval 20 >> data\server.log 2>&1
"@ | Set-Content -Path $Serve -Encoding ASCII

# ---------- брандмауэр ----------
Step "Брандмауэр: входящий TCP $Port"
Get-NetFirewallRule -DisplayName "Voicebot HTTPS" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "Voicebot HTTPS" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Any | Out-Null

# ---------- автозапуск ----------
Step "Служба (задача планировщика «$TaskName»: старт при загрузке, перезапуск при сбое)"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Serve`"" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

# автообновление из GitHub, если проект склонирован через git
$AutoUpdate = $false
if ((Test-Path (Join-Path $Root ".git")) -and (Get-Command git -ErrorAction SilentlyContinue)) {
  Step "Автообновление из GitHub (задача «Voicebot-Update», раз в минуту)"
  $gitExe = (Get-Command git).Source
  # задача работает от SYSTEM, а папка принадлежит вам — разрешаем git работать с ней
  & $gitExe config --system --add safe.directory ($Root -replace "\\", "/") 2>$null
  $uAction = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $Root `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Root\deploy\windows\git-update.ps1`""
  $uTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
  $uSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
  Register-ScheduledTask -TaskName "Voicebot-Update" -Action $uAction -Trigger $uTrigger -Principal $principal -Settings $uSettings -Force | Out-Null
  $AutoUpdate = $true
}

# ---------- проверка ----------
Step "Проверка"
$check = @"
import ssl, sys, time, urllib.request, json
ctx = ssl._create_unverified_context()
for _ in range(30):
    try:
        r = urllib.request.urlopen('https://127.0.0.1:$Port/api/health', context=ctx, timeout=3)
        print(r.read().decode()); sys.exit(0)
    except Exception as e:
        err = e; time.sleep(1)
print('нет ответа:', err); sys.exit(1)
"@
& $VPy -c $check
if ($LASTEXITCODE -ne 0) { Write-Host "Сервер не ответил. Последние строки лога:" -ForegroundColor Red; Get-Content data\server.log -Tail 30 -ErrorAction SilentlyContinue; exit 1 }

$tok = Get-EnvVar "ADMIN_TOKEN"
Write-Host ""
Write-Host "ГОТОВО" -ForegroundColor Green
Write-Host "  Виджет:    $Url"
foreach ($ip in $Ips) { if ($Port -eq 443) { Write-Host "             https://$ip" } else { Write-Host "             https://${ip}:$Port" } }
Write-Host "  Менеджер:  $Url/admin?token=$tok"
Write-Host "  Лог:       $Root\data\server.log"
if ($AutoUpdate) { Write-Host "  Обновления: git push → сервер подхватит за минуту. Лог обновлений: $Root\data\update.log" }
Write-Host "  Управление: powershell -ExecutionPolicy Bypass -File deploy\windows\voicebot.ps1 status|restart|stop|logs"
if (-not $PfxPath) { Write-Host "  Сертификат самоподписанный: браузер один раз попросит подтвердить переход («Дополнительно» → «Перейти»)." -ForegroundColor Yellow }
