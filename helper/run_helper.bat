@echo off
rem Launched by Chrome/Brave/Edge via native messaging. Runs the helper inside its venv.
"%~dp0.venv\Scripts\python.exe" -E -s "%~dp0helper.py" %*
