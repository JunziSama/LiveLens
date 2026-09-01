@echo off
setlocal
chcp 65001 >nul
title LiveLens 监控服务

:: 始终从脚本所在目录运行。
set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%PROJECT_DIR%.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "DEPENDENCY_STAMP=%VENV_DIR%\requirements.txt"
set "PRIMARY_INDEX=https://pypi.org/simple"
set "FALLBACK_INDEX=https://mirrors.aliyun.com/pypi/simple"
cd /d "%PROJECT_DIR%"

:: 检查系统 Python 及最低版本。
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请确认已安装并添加到 PATH。
    pause
    exit /b 1
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [错误] LiveLens 需要 Python 3.9 或更高版本。
    python --version
    pause
    exit /b 1
)

if not exist "%PROJECT_DIR%requirements.txt" (
    echo [错误] 未找到 requirements.txt。
    pause
    exit /b 1
)

:: 使用项目独立虚拟环境，避免 pip 与 python 指向不同环境。
if not exist "%VENV_PYTHON%" (
    echo [初始化] 正在创建项目虚拟环境 .venv ...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败。
        pause
        exit /b 1
    )
)

"%VENV_PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo [错误] .venv 已损坏，请删除项目目录下的 .venv 后重试。
    pause
    exit /b 1
)

:: requirements.txt 变化或关键依赖缺失时才重新安装。
echo [检查] 依赖库...
set "NEED_INSTALL=0"
if not exist "%DEPENDENCY_STAMP%" set "NEED_INSTALL=1"
if exist "%DEPENDENCY_STAMP%" (
    fc /b "%PROJECT_DIR%requirements.txt" "%DEPENDENCY_STAMP%" >nul 2>&1
    if errorlevel 1 set "NEED_INSTALL=1"
)
"%VENV_PYTHON%" -c "import bs4, fake_useragent, yaml, requests, requests_toolbelt, schedule, urllib3, websockets" >nul 2>&1
if errorlevel 1 set "NEED_INSTALL=1"

if "%NEED_INSTALL%"=="1" (
    echo [信息] 正在安装依赖库（PyPI 官方源）...
    "%VENV_PYTHON%" -m pip install -r "%PROJECT_DIR%requirements.txt" -i "%PRIMARY_INDEX%"
    if errorlevel 1 (
        echo [警告] PyPI 官方源安装失败，正在切换到阿里云镜像...
        "%VENV_PYTHON%" -m pip install -r "%PROJECT_DIR%requirements.txt" -i "%FALLBACK_INDEX%"
        if errorlevel 1 (
            echo [错误] 两个软件源均安装失败，LiveLens 未启动。
            pause
            exit /b 1
        )
    )
    copy /y "%PROJECT_DIR%requirements.txt" "%DEPENDENCY_STAMP%" >nul
)

"%VENV_PYTHON%" -c "import bs4, fake_useragent, yaml, requests, requests_toolbelt, schedule, urllib3, websockets" >nul 2>&1
if errorlevel 1 (
    echo [错误] 依赖完整性检查失败，LiveLens 未启动。
    pause
    exit /b 1
)
echo [完成] Python 环境和依赖库检查通过。

:: 仅验证环境，不启动长期运行服务。
if /I "%~1"=="--check" goto check_only

:: 处理启动参数。
if /I "%~1"=="--daemon" goto daemon
if /I "%~1"=="-d" goto daemon

echo ========================================
echo   LiveLens 监控服务 (前台模式)
echo ========================================
echo 提示: 按 Ctrl+C 可停止服务
echo.
"%VENV_PYTHON%" main.py
set "APP_EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %APP_EXIT_CODE%

:check_only
echo [完成] 启动环境验证成功。
exit /b 0

:daemon
echo ========================================
echo   LiveLens 监控服务 (后台模式)
echo ========================================
echo 服务已在后台启动，日志将写入 service.log
echo 如需停止，请在任务管理器中结束对应的 python.exe 进程
echo.
start "" /B "%VENV_PYTHON%" main.py > service.log 2>&1
if errorlevel 1 (
    echo [错误] 后台进程启动失败。
    pause
    exit /b 1
)
echo 启动完成，按任意键退出...
pause >nul
exit /b 0
