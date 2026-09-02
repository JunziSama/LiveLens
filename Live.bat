@echo off
setlocal
chcp 65001 >nul
title LiveLens 监控服务

set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%PROJECT_DIR%.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "DEPENDENCY_STAMP=%VENV_DIR%\requirements.txt"
set "PRIMARY_INDEX=https://pypi.org/simple"
set "FALLBACK_INDEX=https://mirrors.aliyun.com/pypi/simple"
set "PIP_BINARY_OPTION="
if /I "%OS%"=="Windows_NT" set "PIP_BINARY_OPTION=--only-binary=:all:"
set "CHECK_ONLY=0"
set "VENV_CREATED=0"
set "VENV_BACKUP="
if /I "%~1"=="--check" set "CHECK_ONLY=1"
cd /d "%PROJECT_DIR%"

if not exist "%PROJECT_DIR%requirements.txt" (
    echo [错误] 未找到 requirements.txt。
    goto failure
)

call :venv_is_healthy
if not errorlevel 1 goto dependencies

call :find_bootstrap_python
if errorlevel 1 (
    echo [错误] 当前 .venv 不可用，且未找到 Python 3.9 至 3.14。
    echo [提示] 请确认 python -V 或 py -3 -V 可在普通命令提示符中运行。
    goto failure
)

if exist "%VENV_DIR%" call :backup_broken_venv
if errorlevel 1 (
    echo [错误] 无法备份损坏的 .venv，请关闭占用该目录的程序后重试。
    goto failure
)

echo [初始化] 正在创建项目虚拟环境 .venv ...
call :run_bootstrap -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [错误] 创建虚拟环境失败。
    call :rollback_venv
    goto failure
)
set "VENV_CREATED=1"

call :venv_is_healthy
if errorlevel 1 (
    echo [错误] 新建的虚拟环境无法运行。
    call :rollback_venv
    goto failure
)

:dependencies
echo [环境] 当前 Python 运行时:
"%VENV_PYTHON%" -c "import os, platform; print('Python ' + platform.python_version() + ' / ' + (platform.machine() or os.environ.get('PROCESSOR_ARCHITECTURE', 'unknown')))"
if errorlevel 1 (
    echo [错误] 无法读取虚拟环境的 Python 版本和架构。
    if "%VENV_CREATED%"=="1" call :rollback_venv
    goto failure
)
echo [检查] 依赖库...
set "NEED_INSTALL=0"
if not exist "%DEPENDENCY_STAMP%" set "NEED_INSTALL=1"
if exist "%DEPENDENCY_STAMP%" (
    fc /b "%PROJECT_DIR%requirements.txt" "%DEPENDENCY_STAMP%" >nul 2>&1
    if errorlevel 1 set "NEED_INSTALL=1"
)
"%VENV_PYTHON%" -c "import bs4, fake_useragent, yaml, requests, requests_toolbelt, schedule, urllib3, websockets, qrcode, PIL" >nul 2>&1
if errorlevel 1 set "NEED_INSTALL=1"

if "%NEED_INSTALL%"=="1" (
    echo [信息] 正在安装依赖库（PyPI 官方源）...
    "%VENV_PYTHON%" -m pip install %PIP_BINARY_OPTION% -r "%PROJECT_DIR%requirements.txt" -i "%PRIMARY_INDEX%"
    if errorlevel 1 (
        echo [警告] PyPI 官方源安装失败，正在切换到阿里云镜像...
        "%VENV_PYTHON%" -m pip install %PIP_BINARY_OPTION% -r "%PROJECT_DIR%requirements.txt" -i "%FALLBACK_INDEX%"
        if errorlevel 1 (
            echo [错误] 两个软件源均安装失败，LiveLens 未启动。
            if defined PIP_BINARY_OPTION echo [提示] 上方日志会列出缺少当前 Python 版本或架构 wheel 的依赖包。
            if "%VENV_CREATED%"=="1" call :rollback_venv
            goto failure
        )
    )
    copy /y "%PROJECT_DIR%requirements.txt" "%DEPENDENCY_STAMP%" >nul
)

"%VENV_PYTHON%" -c "import bs4, fake_useragent, yaml, requests, requests_toolbelt, schedule, urllib3, websockets, qrcode, PIL" >nul 2>&1
if errorlevel 1 (
    echo [错误] 依赖完整性检查失败，LiveLens 未启动。
    if "%VENV_CREATED%"=="1" call :rollback_venv
    goto failure
)

if defined VENV_BACKUP (
    if exist "%VENV_BACKUP%" rmdir /s /q "%VENV_BACKUP%"
    set "VENV_BACKUP="
)
echo [完成] Python 环境和依赖库检查通过。

if "%CHECK_ONLY%"=="1" (
    echo [完成] 启动环境验证成功。
    exit /b 0
)

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
    goto failure
)
echo 启动完成，按任意键退出...
pause >nul
exit /b 0

:venv_is_healthy
if not exist "%VENV_PYTHON%" exit /b 1
"%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if (3, 9) <= sys.version_info < (3, 15) else 1)" >nul 2>&1
exit /b %ERRORLEVEL%

:find_bootstrap_python
set "BOOTSTRAP_PYTHON="
set "BOOTSTRAP_ARGS="
py -3 -c "import sys; raise SystemExit(0 if (3, 9) <= sys.version_info < (3, 15) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "BOOTSTRAP_PYTHON=py"
    set "BOOTSTRAP_ARGS=-3"
    exit /b 0
)
python -c "import sys; raise SystemExit(0 if (3, 9) <= sys.version_info < (3, 15) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "BOOTSTRAP_PYTHON=python"
    exit /b 0
)
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
    if not defined BOOTSTRAP_PYTHON if exist "%%~fD\python.exe" (
        "%%~fD\python.exe" -c "import sys; raise SystemExit(0 if (3, 9) <= sys.version_info < (3, 15) else 1)" >nul 2>&1
        if not errorlevel 1 set "BOOTSTRAP_PYTHON=%%~fD\python.exe"
    )
)
if not defined BOOTSTRAP_PYTHON exit /b 1
exit /b 0

:run_bootstrap
if /I "%BOOTSTRAP_PYTHON%"=="py" (
    py %BOOTSTRAP_ARGS% %*
) else if /I "%BOOTSTRAP_PYTHON%"=="python" (
    python %*
) else (
    "%BOOTSTRAP_PYTHON%" %*
)
exit /b %ERRORLEVEL%

:choose_backup_path
set "VENV_BACKUP=%PROJECT_DIR%.venv.broken.%RANDOM%%RANDOM%"
if exist "%VENV_BACKUP%" goto choose_backup_path
exit /b 0

:backup_broken_venv
call :choose_backup_path
echo [修复] 检测到损坏的 .venv，正在创建临时备份...
move "%VENV_DIR%" "%VENV_BACKUP%" >nul
exit /b %ERRORLEVEL%

:rollback_venv
if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"
if defined VENV_BACKUP if exist "%VENV_BACKUP%" move "%VENV_BACKUP%" "%VENV_DIR%" >nul
set "VENV_BACKUP="
exit /b 0

:failure
if "%CHECK_ONLY%"=="0" pause
exit /b 1
