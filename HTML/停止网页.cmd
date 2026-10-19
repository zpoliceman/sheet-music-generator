@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -B -X utf8 "launch.py" --stop
pause
endlocal
