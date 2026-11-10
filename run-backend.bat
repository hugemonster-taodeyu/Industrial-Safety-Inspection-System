@echo off
cd /d "%~dp0backend"
title backend
D:\ANACONDA\envs\terminal-yolo\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
echo Backend stopped.
pause
