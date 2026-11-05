# Автообновление из GitHub. Запускается планировщиком раз в минуту (задача «Voicebot-Update»),
# можно и вручную: powershell -ExecutionPolicy Bypass -File deploy\windows\git-update.ps1 -Force
# Есть новый коммит → останавливает бота, ставит код, при необходимости обновляет зависимости,
# запускает и проверяет. Не поднялся → возвращает предыдущий коммит. Лог: data\update.log
param([switch]$Force)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
New-Item -ItemType Directory -Force -Path (Join-Path $Root "data") | Out-Null
$Log = Join-Path $Root "data\update.log"
function Log($t) { $l = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $t"; Write-Host $l; Add-Content -Path $Log -Value $l -Encoding UTF8 }

# прокси из .env (если задан) — для git и pip
$px = Get-Content .env -Encoding UTF8 -ErrorAction SilentlyContinue | Where-Object { $_ -match "^\s*HTTPS_PROXY=" } | Select-Object -Last 1
$Proxy = if ($px) { ($px -split "=", 2)[1].Trim() } else { "" }
if ($Proxy) { $env:HTTPS_PROXY = $Proxy; $env:HTTP_PROXY = $Proxy }

function Git { & git -c safe.directory=* @args; if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') завершился с ошибкой" } }

try { Git fetch --quiet origin } catch { Log "нет связи с GitHub: $_"; exit 1 }
$branch = (& git -c safe.directory=* rev-parse --abbrev-ref HEAD).Trim()
$old = (& git -c safe.directory=* rev-parse HEAD).Trim()
$new = (& git -c safe.directory=* rev-parse "origin/$branch").Trim()
if ($old -eq $new -and -not $Force) { exit 0 }
# коммит, который уже не запустился, повторно не ставим (пока не появится новый или не запущено с -Force)
$BadFile = Join-Path $Root "data\bad_commit"
if (-not $Force -and (Test-Path $BadFile) -and ((Get-Content $BadFile -Raw).Trim() -eq $new)) { exit 0 }

$VPy = Join-Path $Root ".venv\Scripts\python.exe"
$serve = Get-Content (Join-Path $Root "deploy\windows\serve.cmd") -Raw -ErrorAction SilentlyContinue
$Port = if ($serve -match "--port (\d+)") { $Matches[1] } else { "443" }

function Stop-Bot {
  Stop-ScheduledTask -TaskName "Voicebot" -ErrorAction SilentlyContinue
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*uvicorn*app.main:app*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep 2
}
function Install-Deps {
  $a = @("-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", "requirements.txt", "cryptography")
  if ($Proxy) { $a += @("--proxy", $Proxy) }
  & $VPy @a
  return ($LASTEXITCODE -eq 0)
}
function Healthy {
  Start-ScheduledTask -TaskName "Voicebot"
  $check = "import ssl,sys,time,urllib.request`nc=ssl._create_unverified_context()`nfor _ in range(40):`n  try:`n    urllib.request.urlopen('https://127.0.0.1:$Port/api/health',context=c,timeout=3); sys.exit(0)`n  except Exception: time.sleep(1)`nsys.exit(1)"
  & $VPy -c $check
  return ($LASTEXITCODE -eq 0)
}
function Apply($rev) {
  $reqBefore = (Get-FileHash requirements.txt).Hash
  Git reset --quiet --hard $rev
  if ((Get-FileHash requirements.txt).Hash -ne $reqBefore) {
    Log "изменились зависимости — устанавливаю"
    if (-not (Install-Deps)) { Log "pip завершился с ошибкой"; return $false }
  }
  return $true
}

$msg = (& git -c safe.directory=* log -1 --format="%h %s" $new)
Log "обновление $($old.Substring(0,7)) → $msg"
Stop-Bot
$ok = Apply $new
if ($ok) { $ok = Healthy }
if ($ok) { Log "готово, работает"; Remove-Item $BadFile -ErrorAction SilentlyContinue; exit 0 }
Set-Content -Path $BadFile -Value $new -Encoding ASCII

Log "новая версия не запустилась — возвращаю $($old.Substring(0,7))"
Get-Content (Join-Path $Root "data\server.log") -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object { Add-Content -Path $Log -Value "    $_" -Encoding UTF8 }
Stop-Bot
[void](Apply $old)
if (Healthy) { Log "откат выполнен, работает прежняя версия" } else { Log "ВНИМАНИЕ: и прежняя версия не запустилась, см. data\server.log" }
exit 1
