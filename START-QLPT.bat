@echo off
chcp 65001 >nul
title QLPT - Khoi dong he thong
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-windows.ps1" %*
echo.
pause
