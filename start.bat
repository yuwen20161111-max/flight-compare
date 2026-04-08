@echo off
chcp 65001 >nul
title 機票比價系統

echo ══════════════════════════════════════
echo         機票比價系統 啟動中...
echo ══════════════════════════════════════
echo.

REM 檢查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 Python！
    echo 請先安裝 Python：https://www.python.org/downloads/
    echo 安裝時記得勾選「Add Python to PATH」
    pause
    exit /b
)

REM 安裝套件
echo [1/2] 檢查並安裝必要套件...
pip install -q -r "%~dp0requirements.txt"

echo [2/2] 啟動伺服器...
echo.
echo ══════════════════════════════════════
echo   請在瀏覽器開啟：http://localhost:5000
echo   按 Ctrl+C 可停止伺服器
echo ══════════════════════════════════════
echo.

python "%~dp0app.py"
pause
