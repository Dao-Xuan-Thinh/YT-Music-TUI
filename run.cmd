@echo off
rem Convenience launcher for Windows (double-click, or `run.cmd` in a terminal).
rem First run: creates .venv with a modern Python. Every run: launches the app.
rem Dependencies are installed by bootstrap.py on the first launch, so there is
rem nothing else to do on a new machine. Needs mpv (or ffmpeg) for audio:
rem   winget install --id shinchiro.mpv -e
setlocal
cd /d "%~dp0"

rem An existing venv wins, either spelling (.venv from here or run.sh, venv by hand).
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
  goto :run
)
if exist "venv\Scripts\python.exe" (
  set "PY=venv\Scripts\python.exe"
  goto :run
)

rem No venv yet: pick the newest Python >= 3.10. yt-dlp needs 3.10+ to stream
rem YouTube reliably, and the py launcher knows about every installed version.
set "BASE="
for %%V in (3.14 3.13 3.12 3.11 3.10) do (
  if not defined BASE (
    py -%%V -c "import sys" >nul 2>&1 && set "BASE=py -%%V"
  )
)
if not defined BASE (
  where python >nul 2>&1 && set "BASE=python"
)
if not defined BASE (
  echo ERROR: no Python found. Install Python 3.10+ from https://python.org
  echo        ^(or: winget install --id Python.Python.3.12 -e^)
  pause
  exit /b 1
)

echo First run: creating .venv with %BASE% ...
%BASE% -m venv .venv || (echo ERROR: could not create .venv & pause & exit /b 1)
set "PY=.venv\Scripts\python.exe"

:run
"%PY%" main.py %*
endlocal
