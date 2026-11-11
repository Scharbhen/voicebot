# Публикация бота наружу через Tuna (tuna.am). Запуск (PowerShell от администратора, в C:\voicebot):
#   powershell -ExecutionPolicy Bypass -File deploy\windows\tunnel.ps1 -ApiKey tak_...
#   необязательно: -Subdomain имя   — постоянный адрес имя.ru.tuna.am (зарезервируйте его в кабинете Tuna)
# Скрипт скачивает клиент Tuna, включает пароль на виджет, регистрирует автозапуск туннеля
# (задача «Voicebot-Tunnel») и печатает ссылку для клиента. Повторный запуск безопасен.
param([string]$ApiKey = "", [string]$Subdomain = "")
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
if (-not (Test-Path $EnvFile)) { Fail "нет .env — сначала deploy\windows\install.ps1" }
function Set-EnvVar($name, $value) {
  $lines = @(Get-Content $EnvFile -Encoding UTF8 | Where-Object { $_ -notmatch "^\s*$name=" })
  $lines += "$name=$value"
  [IO.File]::WriteAllText($EnvFile, ($lines -join "`r`n") + "`r`n", (New-Object Text.UTF8Encoding($false)))
}
function Get-EnvVar($name) {
  $l = Get-Content $EnvFile -Encoding UTF8 | Where-Object { $_ -match "^\s*$name=" } | Select-Object -Last 1
  if ($l) { return ($l -split "=", 2)[1].Trim() } else { return "" }
}

if ($ApiKey) { Set-EnvVar "TUNA_API_KEY" $ApiKey.Trim() }
$ApiKey = Get-EnvVar "TUNA_API_KEY"
if (-not $ApiKey) { Fail "укажите ключ Tuna: -ApiKey tak_..." }
if ($Subdomain) { Set-EnvVar "TUNA_SUBDOMAIN" $Subdomain.Trim() }
$Subdomain = Get-EnvVar "TUNA_SUBDOMAIN"
$Proxy = Get-EnvVar "HTTPS_PROXY"

$serve = Get-Content (Join-Path $Root "deploy\windows\serve.cmd") -Raw -ErrorAction SilentlyContinue
if (-not $serve) { Fail "бот не установлен — сначала deploy\windows\install.ps1" }
$Port = if ($serve -match "--port (\d+)") { $Matches[1] } else { "443" }

# ---------- клиент Tuna ----------
Step "Клиент Tuna"
$ToolDir = Join-Path $Root "data\tuna"
$Tuna = Get-ChildItem $ToolDir -Recurse -Filter "tuna.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $Tuna) {
  New-Item -ItemType Directory -Force -Path $ToolDir | Out-Null
  $zip = Join-Path $ToolDir "tuna.zip"
  $wa = @{ Uri = "https://releases.tuna.am/tuna/latest/tuna_windows_amd64.zip"; OutFile = $zip; UseBasicParsing = $true }
  if ($Proxy) { $wa.Proxy = $Proxy }
  Invoke-WebRequest @wa
  Expand-Archive $zip -DestinationPath $ToolDir -Force
  Remove-Item $zip
  $Tuna = Get-ChildItem $ToolDir -Recurse -Filter "tuna.exe" | Select-Object -First 1
  if (-not $Tuna) { Fail "в архиве Tuna нет tuna.exe" }
}
Write-Host $Tuna.FullName

# ---------- пароль на виджет ----------
Step "Пароль на виджет"
$Access = Get-EnvVar "ACCESS_KEY"
if (-not $Access) {
  $Access = -join ((48..57) + (97..122) | Get-Random -Count 10 | ForEach-Object { [char]$_ })
  Set-EnvVar "ACCESS_KEY" $Access
}
Write-Host "включён"

# ---------- запуск туннеля ----------
Step "Туннель → https://localhost:$Port"
$Log = Join-Path $Root "data\tunnel.log"
$Cmd = Join-Path $Root "data\tunnel.cmd"   # в data\ — не попадает в git, ключ остаётся только на сервере
$lines = @(
  "@echo off",
  "cd /d `"$Root`"",
  "set TUNA_API_KEY=$ApiKey",
  "set TUNA_INSPECT=false",
  "set TUNA_TUI=0",
  "set TUNA_NO_PROMPT=1",
  "set TUNA_LOG_FORMAT=text"
)
if ($Subdomain) { $lines += "set TUNA_SUBDOMAIN=$Subdomain" }
if ($Proxy) { $lines += "set HTTPS_PROXY=$Proxy" }
$lines += "`"$($Tuna.FullName)`" http https://localhost:$Port >> `"$Log`" 2>&1"
$lines -join "`r`n" | Set-Content -Path $Cmd -Encoding ASCII

$Task = "Voicebot-Tunnel"
Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
Get-Process tuna -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
if (Test-Path $Log) { Remove-Item $Log -Force }
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Cmd`"" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $Task -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $Task

# ---------- внешний адрес ----------
Step "Жду внешний адрес"
$Url = $null
for ($i = 0; $i -lt 30 -and -not $Url; $i++) {
  Start-Sleep 1
  $txt = Get-Content $Log -Raw -ErrorAction SilentlyContinue
  if ($txt -match "(https://[a-z0-9.-]+\.tuna\.am)") { $Url = $Matches[1] }
}
if (-not $Url) {
  Write-Host "Туннель не сообщил адрес. Лог:" -ForegroundColor Red
  Get-Content $Log -Tail 30 -ErrorAction SilentlyContinue
  exit 1
}
Set-EnvVar "PUBLIC_BASE_URL" $Url

# бот перечитывает .env только при старте — перезапускаем, чтобы включились пароль и внешний адрес
Step "Перезапускаю бота"
Stop-ScheduledTask -TaskName "Voicebot" -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*uvicorn*app.main:app*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 2
Start-ScheduledTask -TaskName "Voicebot"
$ok = $false
for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
  Start-Sleep 2
  try { $ok = (Invoke-WebRequest "$Url/api/health" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch {}
}

$tok = Get-EnvVar "ADMIN_TOKEN"
Write-Host ""
if ($ok) { Write-Host "ГОТОВО — бот доступен снаружи" -ForegroundColor Green }
else { Write-Host "Туннель поднят, но бот через него пока не ответил — проверьте data\tunnel.log и data\server.log" -ForegroundColor Yellow }
Write-Host "  Ссылка для клиента:  $Url/?key=$Access"
Write-Host "  Страница менеджера:  $Url/admin?token=$tok"
if (-not $Subdomain) { Write-Host "  Адрес временный и сменится при перезапуске. Постоянный: зарезервируйте поддомен в кабинете Tuna и запустите скрипт с -Subdomain имя" -ForegroundColor Yellow }
