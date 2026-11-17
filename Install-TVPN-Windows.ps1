$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'Install Microsoft App Installer (winget) from Microsoft Store, then retry.' }
    $py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    if (-not (Test-Path $py)) {
        & winget install --id Python.Python.3.13 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
    }
    if (-not (Test-Path $py)) { throw 'Python 3.13 executable was not found after installation.' }
    $gui = Join-Path $env:ProgramFiles 'OpenVPN\bin\openvpn-gui.exe'
    if (-not (Test-Path $gui)) {
        & winget install --id OpenVPNTechnologies.OpenVPN --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw 'OpenVPN installation failed.' }
    }
    $work = Join-Path $env:TEMP ('tvpn-' + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $work | Out-Null
    try {
        Invoke-WebRequest -UseBasicParsing 'https://codeload.github.com/user9x21imi/tvpn/zip/refs/heads/main' -OutFile "$work\source.zip"
        Expand-Archive "$work\source.zip" "$work\source"
        $dest = Join-Path $env:LOCALAPPDATA 'TVPN'
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Copy-Item "$work\source\tvpn-main\*" $dest -Recurse -Force
    } finally { Remove-Item $work -Recurse -Force }
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $setup = Join-Path $dest 'platforms\windows\install.ps1'
    $process = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$setup+'"'),'-User',('"'+$user+'"'))
    if ($process.ExitCode -ne 0) { throw 'Administrator setup failed or was cancelled.' }
    & $py -m venv "$dest\.venv"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create Python environment.' }
    & "$dest\.venv\Scripts\python.exe" -m pip install -r "$dest\requirements-windows.txt"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot install Python dependencies.' }
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'TVPN.lnk'))
    $link.TargetPath = Join-Path $dest 'start-windows.cmd'
    $link.WorkingDirectory = $dest
    $link.Save()
    $commands = Join-Path $env:LOCALAPPDATA 'TVPN\bin'
    New-Item -ItemType Directory -Force -Path $commands | Out-Null
    ('@echo off' + "`r`n" + 'call "'+$dest+'\start-windows.cmd" %*') | Set-Content "$commands\tvpn.cmd" -Encoding ASCII
    $userPath = [Environment]::GetEnvironmentVariable('Path','User')
    if (($userPath -split ';') -notcontains $commands) { [Environment]::SetEnvironmentVariable('Path',($userPath+';'+$commands),'User') }
    Write-Host 'TVPN installed. Sign out and back in once to activate VPN permissions. Then open TVPN from Start or type tvpn in a new terminal.'
    Read-Host 'Press Enter to close'
} catch {
    Write-Host $_ -ForegroundColor Red
    Read-Host 'Installation failed. Press Enter to close'
    exit 1
}
