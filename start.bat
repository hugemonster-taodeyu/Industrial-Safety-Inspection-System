@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在停止已有的后端和页面...
powershell -NoProfile -File "%~dp0start-helper.ps1" stop
echo 正在启动后端...
start "安全检测-后端" "%~dp0run-backend.bat"
echo 正在启动页面...
start "安全检测-前端" "%~dp0run-frontend.bat"
echo 等待页面就绪...
powershell -NoProfile -File "%~dp0start-helper.ps1" wait
if errorlevel 1 goto notready
start "" http://127.0.0.1:5173/
echo 已打开 http://127.0.0.1:5173/
goto end
:notready
echo 页面在 30 秒内没有就绪，请查看「安全检测-前端」窗口里的报错。
pause
:end
