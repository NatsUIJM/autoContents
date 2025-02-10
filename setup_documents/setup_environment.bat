@echo off
chcp 437
title Environment Setup
color 0A

setlocal enabledelayedexpansion

echo Script starting...

:: Get script directory and parent directory
set "SCRIPT_DIR=%~dp0"
set "PARENT_DIR=%SCRIPT_DIR:~0,-1%"
for %%I in ("%PARENT_DIR%") do set "PROJECT_DIR=%%~dpI"

:: Change to project directory
echo Changing to project directory: !PROJECT_DIR!
cd /d "!PROJECT_DIR!"
if !errorlevel! neq 0 (
    echo Failed to change directory: !errorlevel!
    pause
    exit /b !errorlevel!
)

:: Create virtual environment
echo Creating virtual environment...
python -m venv .venv
if !errorlevel! neq 0 (
    echo Virtual environment creation failed: !errorlevel!
    pause
    exit /b !errorlevel!
)

:: Activate virtual environment and set pip source
echo Setting pip source...
call .venv\Scripts\activate.bat
if !errorlevel! neq 0 (
    echo Virtual environment activation failed: !errorlevel!
    pause
    exit /b !errorlevel!
)

pip config set global.index-url https://mirrors.aliyun.com/pypi/simple
if !errorlevel! neq 0 (
    echo Pip source configuration failed: !errorlevel!
    pause
    exit /b !errorlevel!
)

:: Install dependencies
echo Installing project dependencies...
pip install -r requirements.txt
if !errorlevel! neq 0 (
    echo Dependencies installation failed: !errorlevel!
    pause
    exit /b !errorlevel!
)

echo [OK] Environment setup completed!
pause

endlocal