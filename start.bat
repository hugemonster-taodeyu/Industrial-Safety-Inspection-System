@echo off
cd /d "%~dp0"
echo 正在停止已有的后端和页面...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
echo 正在启动后端...
start "安全检测-后端" cmd /k "cd /d "%~dp0backend" && "%~dp0.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
echo 正在启动页面...
start "安全检测-前端" cmd /k "cd /d "%~dp0frontend" && npm run dev"
echo 等待页面就绪...
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(30); while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -Uri http://127.0.0.1:5173/ -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -eq 200){ exit 0 } } catch {} ; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 (
  echo 页面在 30 秒内没有就绪，请查看「安全检测-前端」窗口里的报错。
  pause
  exit /b 1
)
start "" http://127.0.0.1:5173/
echo 已打开 http://127.0.0.1:5173/
