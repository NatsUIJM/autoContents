@echo off
chcp 437
title Chocolatey Installation
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

:: Check Chocolatey
where choco >nul 2>nul
if %errorlevel% equ 0 (
    echo Chocolatey is already installed, skipping...
) else (
    echo Installing Chocolatey...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))"
    if !errorlevel! neq 0 (
        echo Chocolatey installation failed: !errorlevel!
        pause
        exit /b !errorlevel!
    )
    for /f "tokens=*" %%i in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable(\"Path\", \"Machine\") + \";\" + [Environment]::GetEnvironmentVariable(\"Path\", \"User\")"') do set "PATH=%%i"
    set "PATH=%ProgramData%\chocolatey\bin;%PATH%"
)

echo [OK] Chocolatey installation completed!
pause

endlocal