@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-helper.ps1" say stopping
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-helper.ps1" stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-helper.ps1" say starting-backend
start "backend" "%~dp0run-backend.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-helper.ps1" say starting-frontend
start "frontend" "%~dp0run-frontend.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-helper.ps1" say waiting
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-helper.ps1" wait
if errorlevel 1 goto notready
start "" http://127.0.0.1:5173/
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-helper.ps1" say opened
goto end
:notready
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-helper.ps1" say notready
pause
:end
