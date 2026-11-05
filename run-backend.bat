@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
D:\ANACONDA\envs\terminal-yolo\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
echo 后端已退出。
pause
