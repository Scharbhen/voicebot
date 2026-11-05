# Один раз на сервере (PowerShell от имени администратора): включает встроенный в Windows SSH-сервер
# и разрешает вход по ключу с вашего компьютера — после этого обновления ставятся командой ./deploy-win.sh
#   powershell -ExecutionPolicy Bypass -File deploy\windows\enable-ssh.ps1 -PublicKey "ssh-ed25519 AAAA... you@mac"
param([Parameter(Mandatory = $true)][string]$PublicKey)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$cap = Get-WindowsCapability -Online -Name "OpenSSH.Server*" | Select-Object -First 1
if ($cap.State -ne "Installed") {
  Write-Host "Устанавливаю OpenSSH Server (компонент Windows)…"
  Add-WindowsCapability -Online -Name $cap.Name | Out-Null
}
Set-Service sshd -StartupType Automatic
Start-Service sshd
if (-not (Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -DisplayName "OpenSSH Server (sshd)" -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow | Out-Null
}

# ключ для администраторов хранится в общем файле, доступ к нему — только SYSTEM и Администраторы
$keys = "$env:ProgramData\ssh\administrators_authorized_keys"
$existing = if (Test-Path $keys) { Get-Content $keys } else { @() }
if ($existing -notcontains $PublicKey.Trim()) { Add-Content -Path $keys -Value $PublicKey.Trim() -Encoding ASCII }
icacls $keys /inheritance:r /grant "*S-1-5-32-544:F" /grant "SYSTEM:F" | Out-Null

Write-Host ""
Write-Host "SSH включён." -ForegroundColor Green
Write-Host "  Пользователь для входа: $env:USERDOMAIN\$env:USERNAME (должен быть администратором сервера)"
Write-Host "  Проверка с Мака:  ssh $env:USERNAME@$([System.Net.Dns]::GetHostEntry('').HostName) hostname"
