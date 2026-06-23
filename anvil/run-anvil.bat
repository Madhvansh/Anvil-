@echo off
REM Anvil one-double-click launcher. Runs the whole product (API + PWA + live cockpit) in one process,
REM always from this folder so data paths stay consistent. Pass extra flags after the file name.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m anvil.cli go-live %*
pause
