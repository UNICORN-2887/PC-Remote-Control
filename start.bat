@echo off
chcp 65001 >nul
title PC 远程控制

echo ========================================
echo   🖥️  PC 远程控制 - 启动中...
echo ========================================
echo.

echo [1/2] 启动控制服务器...
start "PC远程控制-服务器" /MIN python -u server.py
timeout /t 3 /nobreak >nul

echo [2/2] 启动内网穿透隧道...
echo.
echo 📱 稍等，获取公网地址...
echo.

npx --yes localtunnel --port 5000

echo.
echo 隧道已断开。按任意键退出...
pause >nul
