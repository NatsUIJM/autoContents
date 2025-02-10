@echo off
chcp 437
title Python Installation
color 0A

setlocal enabledelayedexpansion

echo Script starting...

:: Check admin rights
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [OK] Admin rights confirmed
) else (
    echo [X] Please run as administrator!
    pause
    exit
)

:: Check Python 3.11
python --version 2>nul | findstr "3.11" >nul
if %errorlevel% equ 0 (
    echo Python 3.11 is already installed, skipping...
) else (
    echo Installing Python 3.11...
    choco install python311 -y
    if !errorlevel! neq 0 (
        echo Python installation failed: !errorlevel!
        pause
        exit /b !errorlevel!
    )
    for /f "tokens=*" %%i in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable(\"Path\", \"Machine\") + \";\" + [Environment]::GetEnvironmentVariable(\"Path\", \"User\")"') do set "PATH=%%i"
)

echo [OK] Python installation completed!
pause

endlocal