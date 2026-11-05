# Обновление кода на сервере (вызывается из deploy-win.sh по SSH или вручную):
#   powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1 -Zip C:\voicebot\update.zip
#   powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1 -Rollback     — вернуть предыдущую версию
# .env, data\ (база, сертификат, лог) и .venv не трогаются.
param([string]$Zip = "", [switch]$Rollback)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
function Step($t) { Write-Host "==> $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "ОШИБКА: $t" -ForegroundColor Red; exit 1 }

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$Items = @("app", "static", "kb", "scripts", "requirements.txt", ".env.example", "README.md", "deploy\windows")
$Backups = Join-Path $Root "data\backup"
New-Item -ItemType Directory -Force -Path $Backups | Out-Null
$VPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VPy)) { Fail "не установлено — сначала deploy\windows\install.ps1" }

if ($Rollback) {
  $last = Get-ChildItem $Backups -Filter "code-*.zip" | Sort-Object Name -Descending | Select-Object -First 1
  if (-not $last) { Fail "нет сохранённых версий в data\backup" }
  $Zip = $last.FullName
  Step "Откат на $($last.Name)"
}
if (-not $Zip -or -not (Test-Path $Zip)) { Fail "не найден архив: $Zip" }

# распаковываем во временную папку и проверяем, что это наш проект
$Tmp = Join-Path $env:TEMP ("voicebot-" + [guid]::NewGuid().ToString("N"))
Expand-Archive -Path $Zip -DestinationPath $Tmp -Force
if (-not (Test-Path (Join-Path $Tmp "app\main.py"))) { Remove-Item $Tmp -Recurse -Force; Fail "в архиве нет app\main.py" }

# сохраняем текущую версию (последние 10)
if (-not $Rollback) {
  Step "Сохраняю текущую версию"
  $exist = $Items | Where-Object { $_ -notlike "deploy*" -and (Test-Path (Join-Path $Root $_)) }
  Compress-Archive -Path $exist -DestinationPath (Join-Path $Backups ("code-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".zip")) -Force
  Get-ChildItem $Backups -Filter "code-*.zip" | Sort-Object Name -Descending | Select-Object -Skip 10 | Remove-Item -Force
}

$reqOld = if (Test-Path requirements.txt) { (Get-FileHash requirements.txt).Hash } else { "" }

Step "Останавливаю"
Stop-ScheduledTask -TaskName "Voicebot" -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*uvicorn*app.main:app*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 2

Step "Заменяю код"
$serve = Join-Path $Root "deploy\windows\serve.cmd"
$serveKeep = if (Test-Path $serve) { Get-Content $serve -Raw } else { $null }
foreach ($i in @("app", "static", "kb", "scripts")) {
  if (Test-Path (Join-Path $Tmp $i)) {
    if (Test-Path (Join-Path $Root $i)) { Remove-Item (Join-Path $Root $i) -Recurse -Force }
    Copy-Item (Join-Path $Tmp $i) (Join-Path $Root $i) -Recurse -Force
  }
}
foreach ($f in @("requirements.txt", ".env.example", "README.md")) {
  if (Test-Path (Join-Path $Tmp $f)) { Copy-Item (Join-Path $Tmp $f) (Join-Path $Root $f) -Force }
}
if (Test-Path (Join-Path $Tmp "deploy\windows")) {
  New-Item -ItemType Directory -Force -Path (Join-Path $Root "deploy\windows") | Out-Null
  Get-ChildItem (Join-Path $Tmp "deploy\windows") -File | Where-Object { $_.Name -ne "serve.cmd" } |
    ForEach-Object { Copy-Item $_.FullName (Join-Path $Root "deploy\windows\$($_.Name)") -Force }
}
if ($serveKeep) { Set-Content -Path $serve -Value $serveKeep -Encoding ASCII -NoNewline }
Remove-Item $Tmp -Recurse -Force

if ((Get-FileHash requirements.txt).Hash -ne $reqOld) {
  Step "Изменились зависимости — обновляю"
  $proxy = (Get-Content .env -Encoding UTF8 | Where-Object { $_ -match "^\s*HTTPS_PROXY=" } | Select-Object -Last 1)
  $pipArgs = @("-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", "requirements.txt", "cryptography")
  if ($proxy) { $pipArgs += @("--proxy", ($proxy -split "=", 2)[1].Trim()) }
  & $VPy @pipArgs
  if ($LASTEXITCODE -ne 0) { Fail "pip не смог установить зависимости (откат: update.ps1 -Rollback)" }
}

Step "Запускаю"
Start-ScheduledTask -TaskName "Voicebot"
$port = if ($serveKeep -match "--port (\d+)") { $Matches[1] } else { "443" }
$check = @"
import ssl, sys, time, urllib.request
ctx = ssl._create_unverified_context()
for _ in range(30):
    try:
        print(urllib.request.urlopen('https://127.0.0.1:$port/api/health', context=ctx, timeout=3).read().decode()); sys.exit(0)
    except Exception as e:
        err = e; time.sleep(1)
print('нет ответа:', err); sys.exit(1)
"@
& $VPy -c $check
if ($LASTEXITCODE -ne 0) {
  Write-Host "Сервер не поднялся. Лог:" -ForegroundColor Red
  Get-Content data\server.log -Tail 30 -ErrorAction SilentlyContinue
  Write-Host "Вернуть прошлую версию: deploy\windows\update.ps1 -Rollback" -ForegroundColor Yellow
  exit 1
}
Write-Host "ОБНОВЛЕНО" -ForegroundColor Green
