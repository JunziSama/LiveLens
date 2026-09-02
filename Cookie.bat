@echo off
setlocal
chcp 65001 >nul
title 更新B站Cookie

set "PROJECT_DIR=%~dp0"
set "VENV_PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
set "CHECK_ONLY=0"
if /I "%~1"=="--check" set "CHECK_ONLY=1"
cd /d "%PROJECT_DIR%"

echo ========================================
echo     B站 Cookie 自动更新工具
echo ========================================
echo.

call "%PROJECT_DIR%Live.bat" --check
if errorlevel 1 (
    echo [错误] LiveLens 运行环境检查失败，Cookie 工具未启动。
    if "%CHECK_ONLY%"=="0" pause
    exit /b 1
)

if "%CHECK_ONLY%"=="1" (
    "%VENV_PYTHON%" "%PROJECT_DIR%cookie_updater.py" --check-config
    if errorlevel 1 (
        echo [错误] Cookie 工具导入检查失败。
        exit /b 1
    )
    echo [完成] Cookie 获取工具环境验证成功。
    exit /b 0
)

echo [启动] 正在打开二维码登录流程...
"%VENV_PYTHON%" "%PROJECT_DIR%cookie_updater.py"
set "UPDATER_EXIT_CODE=%ERRORLEVEL%"

echo.
if "%UPDATER_EXIT_CODE%"=="0" (
    echo [完成] Cookie 获取工具执行成功。
) else if "%UPDATER_EXIT_CODE%"=="2" (
    echo [过期] 二维码已过期，请重新运行 Cookie.bat。
) else if "%UPDATER_EXIT_CODE%"=="3" (
    echo [超时] 扫码登录超时，请重新运行 Cookie.bat。
) else if "%UPDATER_EXIT_CODE%"=="130" (
    echo [取消] 用户取消了 Cookie 获取。
) else (
    echo [失败] Cookie 获取工具退出，代码: %UPDATER_EXIT_CODE%
)
echo 按任意键退出...
pause >nul
exit /b %UPDATER_EXIT_CODE%
