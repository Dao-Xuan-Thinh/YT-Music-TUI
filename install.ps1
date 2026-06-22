# Installs a global `yttui` command (Windows).
# Run once per machine after cloning:   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = 'Stop'

$repo = $PSScriptRoot
$bin  = Join-Path $env:USERPROFILE 'bin'
New-Item -ItemType Directory -Force -Path $bin | Out-Null

# Launcher: cd to the repo, prefer a local .venv, else system python.
$cmd = @"
@echo off
cd /d "$repo"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" main.py %*
) else (
  python main.py %*
)
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
