# Installs a global `yttui` command (Windows).
# Run once per machine after cloning:   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = 'Stop'

$repo = $PSScriptRoot
$bin  = Join-Path $env:USERPROFILE 'bin'
New-Item -ItemType Directory -Force -Path $bin | Out-Null

# Launcher: hand off to run.cmd in the repo, which finds/creates the venv and
# picks a modern Python (deps are installed on first launch by bootstrap.py).
$cmd = @"
@echo off
call "$repo\run.cmd" %*
"@
Set-Content -Path (Join-Path $bin 'yttui.cmd') -Value $cmd -Encoding ASCII
Write-Host "Installed: $bin\yttui.cmd  ->  $repo"

# Add %USERPROFILE%\bin to the user PATH if missing.
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (($userPath -split ';') -notcontains $bin) {
    $newPath = ($userPath.TrimEnd(';') + ';' + $bin).TrimStart(';')
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    Write-Host "Added $bin to your user PATH."
} else {
    Write-Host "$bin is already on your PATH."
}

Write-Host "Open a NEW terminal and run:  yttui"
