@echo off
chcp 65001 >nul
title LiveLens 监控服务

:: 设置项目根目录（自动获取脚本所在目录）
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请确认已安装并添加到 PATH。
    pause
    exit /b 1
)

:: 检查并安装依赖（静默，仅当缺失时）
echo [检查] 依赖库...
pip show schedule >nul 2>&1
if errorlevel 1 (
    echo [信息] 正在安装依赖库（使用清华源）...
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)

:: 处理启动参数
if "%1"=="--daemon" goto daemon
if "%1"=="-d" goto daemon

:: 默认：前台运行，实时显示日志
echo ========================================
echo   LiveLens 监控服务 (前台模式)
echo ========================================
echo 提示: 按 Ctrl+C 可停止服务
echo.
python main.py
pause
exit /b 0

:daemon
:: 后台运行模式（使用 start /B 不显示窗口，日志写入文件）
echo ========================================
echo   LiveLens 监控服务 (后台模式)
echo ========================================
echo 服务已在后台启动，日志将写入 service.log
echo 如需停止，请在任务管理器中结束 python.exe 进程
echo.
start /B python main.py > service.log 2>&1
echo 启动完成，按任意键退出...
pause >nul
exit /b 0