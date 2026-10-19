@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先在此文件夹运行 准备环境.ps1。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -B -X utf8 "launch.py" --share --open
if errorlevel 1 pause
endlocal
