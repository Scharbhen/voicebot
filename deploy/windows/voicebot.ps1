# Управление ассистентом на сервере:
#   powershell -ExecutionPolicy Bypass -File deploy\windows\voicebot.ps1 status|start|stop|restart|logs
param([ValidateSet("status", "start", "stop", "restart", "logs")][string]$Action = "status")
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Task = "Voicebot"
function Stop-Bot {
  Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*uvicorn*app.main:app*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
switch ($Action) {
  "status" {
    $t = Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
    if (-not $t) { "Не установлено — запустите deploy\windows\install.ps1"; break }
    "Задача: $($t.State)"
    $p = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*uvicorn*app.main:app*" }
    if ($p) { "Процесс: работает (PID $($p.ProcessId -join ', '))" } else { "Процесс: не запущен" }
    Get-Content (Join-Path $Root "data\server.log") -Tail 10 -ErrorAction SilentlyContinue
  }
  "start"   { Start-ScheduledTask -TaskName $Task; "Запущено" }
  "stop"    { Stop-Bot; "Остановлено" }
  "restart" { Stop-Bot; Start-Sleep 2; Start-ScheduledTask -TaskName $Task; "Перезапущено" }
  "logs"    { Get-Content (Join-Path $Root "data\server.log") -Tail 50 -Wait }
}
