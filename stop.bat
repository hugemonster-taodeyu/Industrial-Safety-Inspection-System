@echo off
cd /d "%~dp0"
echo 正在关闭工程行为安全检测系统...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn app.main:app|vite.js' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000,5173,5174 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
taskkill /F /FI "WINDOWTITLE eq 安全检测-后端*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq 安全检测-前端*" >nul 2>&1
echo 已关闭。
timeout /t 2 >nul
