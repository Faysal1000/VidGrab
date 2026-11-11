@echo off
rem VidGrab installer for Windows. Double-click once (or run from a terminal).
rem Installs Python + ffmpeg with winget if needed, sets up the helper venv and
rem connects it to Chrome / Brave / Edge. Safe to re-run.
rem Uninstall:  install_windows.bat --uninstall
setlocal
cd /d "%~dp0"

if /i "%~1"=="--uninstall" goto run

echo ==^> Checking system tools
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
  echo     Installing Python with winget...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo     Installing ffmpeg with winget...
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
) else (
  echo     OK ffmpeg
)

:run
if not defined PY set "PY=py -3"
%PY% installer\install.py %*
echo.
pause
