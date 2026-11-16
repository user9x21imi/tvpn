# One-time service/group setup. Run from an Administrator PowerShell.
param([string]$User = [Security.Principal.WindowsIdentity]::GetCurrent().Name)
$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Open PowerShell as Administrator and run this script once with -User COMPUTER\username.'
}
$gui = Join-Path $env:ProgramFiles 'OpenVPN\bin\openvpn-gui.exe'
if (-not (Test-Path $gui)) { throw 'Install OpenVPN Community with GUI and Interactive Service: https://openvpn.net/community-downloads/' }
$group = 'OpenVPN Administrators'
if (-not (Get-LocalGroup -Name $group -ErrorAction SilentlyContinue)) { throw 'The OpenVPN Administrators group is missing. Repair the official OpenVPN installation.' }
if (-not (Get-LocalGroupMember -Group $group | Where-Object {$_.Name -eq $User})) {
    Add-LocalGroupMember -Group $group -Member $User
}
Set-Service -Name OpenVPNServiceInteractive -StartupType Automatic
Start-Service -Name OpenVPNServiceInteractive
Write-Host 'Setup complete. Sign out and back in once, then run start-windows.cmd as your normal user.'
