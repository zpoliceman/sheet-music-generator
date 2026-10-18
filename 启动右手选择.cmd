@echo off
chcp 65001 >nul
rem 网页连接恢复与独立启动：新增UTF-8代码页，避免Windows把中文注释片段误作命令。
rem 4/4可选右手与实时谱面试听：新增用户双击入口，使用已验证本机环境。
cd /d "%~dp0"
rem 网页连接恢复与独立启动：保留原前台运行方式，改由独立启动器检查服务就绪后打开网页。
rem ".venv-gpu\Scripts\python.exe" -B -X utf8 "tools\guitar_pattern_preview.py" --open
rem pause
rem 网页连接恢复与独立启动：新增独立后台服务入口；仅在启动失败时保留窗口供用户查看原因。
".venv-gpu\Scripts\python.exe" -B -X utf8 "tools\start_guitar_pattern_preview.py" %*
rem 网页连接恢复与独立启动：新增失败状态保留，用户查看错误后命令仍返回失败。
if errorlevel 1 (
    pause
    exit /b 1
)
