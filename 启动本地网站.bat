@echo off
chcp 65001 >nul
title DSH文献站本地服务器
cd /d %~dp0
echo 正在启动文献站本地服务器（gzip 加速版）...
echo 浏览器打开 http://localhost:8761/  即可访问。关闭本窗口即停止服务器。
python tools\serve.py
pause
