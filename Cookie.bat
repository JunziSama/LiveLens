@echo off
chcp 65001 >nul
title 更新B站Cookie

echo ========================================
echo     B站 Cookie 自动更新工具
echo ========================================
echo.

:: 检查 Python 是否可用
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到 Python，请确认已安装并添加到 PATH。
    pause
    exit /b 1
)

:: 检查依赖包（可选，静默安装）
pip show qrcode >nul 2>&1
if errorlevel 1 (
    echo 正在安装依赖库 qrcode 和 pillow ...
    pip install qrcode pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
)

:: 运行 cookie_updater.py
echo 正在启动二维码登录...
python cookie_updater.py

:: 运行结束后等待用户按键（防止窗口闪退）
echo.
echo 按任意键退出...
pause >nul