@echo off
chcp 437
title AutoContents Environment Setup
color 0A

setlocal enabledelayedexpansion

echo Script starting...

:: Get script directory and parent directory
set "SCRIPT_DIR=%~dp0"
set "PARENT_DIR=%SCRIPT_DIR:~0,-1%"
for %%I in ("%PARENT_DIR%") do set "PROJECT_DIR=%%~dpI"

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
    echo [1/6] Chocolatey is already installed, skipping...
) else (
    echo [1/6] Installing Chocolatey...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))"
    if !errorlevel! neq 0 (
        echo Chocolatey installation failed: !errorlevel!
        pause
        exit /b !errorlevel!
    )
    for /f "tokens=*" %%i in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable(\"Path\", \"Machine\") + \";\" + [Environment]::GetEnvironmentVariable(\"Path\", \"User\")"') do set "PATH=%%i"
    set "PATH=%ProgramData%\chocolatey\bin;%PATH%"
)

echo Current directory: %CD%

:: Check Python 3.11
python --version 2>nul | findstr "3.11" >nul
if %errorlevel% equ 0 (
    echo [2/6] Python 3.11 is already installed, skipping...
) else (
    echo [2/6] Installing Python 3.11...
    choco install python311 -y
    if !errorlevel! neq 0 (
        echo Python installation failed: !errorlevel!
        pause
        exit /b !errorlevel!
    )
    for /f "tokens=*" %%i in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable(\"Path\", \"Machine\") + \";\" + [Environment]::GetEnvironmentVariable(\"Path\", \"User\")"') do set "PATH=%%i"
)

:: Check Poppler
echo [3/6] Checking Poppler...
pdfinfo -v 2>nul | findstr "pdfinfo version 24.08.0" >nul
if %errorlevel% equ 0 (
    echo Poppler 24.08.0 is already installed, skipping...
) else (
    echo Installing Poppler...

    set "URL=https://github.com/oschwartz10612/poppler-windows/releases/download/v24.08.0-0/Release-24.08.0-0.zip"
    set "FILENAME=Release-24.08.0-0.zip"
    set "DOWNLOAD_PATH=%USERPROFILE%\Downloads\!FILENAME!"
    set "TEMP_EXTRACT_PATH=%TEMP%\poppler_temp"
    set "FINAL_PATH=C:\Program Files\poppler-24.08.0"
    set "BIN_PATH=!FINAL_PATH!\Library\bin"

    echo Creating temp directory: !TEMP_EXTRACT_PATH!

    if exist "!TEMP_EXTRACT_PATH!" rd /s /q "!TEMP_EXTRACT_PATH!"
    mkdir "!TEMP_EXTRACT_PATH!"
    if !errorlevel! neq 0 (
        echo Failed to create temp directory: !errorlevel!
        pause
        exit /b !errorlevel!
    )

    set "retries=0"
    :download_retry
    echo Downloading !FILENAME! to !DOWNLOAD_PATH! ^(Attempt !retries!/3^)...
    powershell -Command "$wc = New-Object Net.WebClient; $wc.DownloadFile('!URL!', '!DOWNLOAD_PATH!')"
    if !errorlevel! neq 0 (
        set /a "retries+=1"
        if !retries! lss 3 (
            echo Download failed, retrying...
            goto download_retry
        ) else (
            echo Download failed after 3 attempts: !errorlevel!
            pause
            exit /b !errorlevel!
        )
    )

    echo Extracting files...
    powershell -Command "Expand-Archive -Path '!DOWNLOAD_PATH!' -DestinationPath '!TEMP_EXTRACT_PATH!' -Force"
    if !errorlevel! neq 0 (
        echo Extraction failed: !errorlevel!
        pause
        exit /b !errorlevel!
    )

    echo Installing files...
    if exist "!FINAL_PATH!" rd /s /q "!FINAL_PATH!"
    robocopy "!TEMP_EXTRACT_PATH!\poppler-24.08.0" "!FINAL_PATH!" /E /NFL /NDL /NJH /NJS /NC /NS /NP
    if !errorlevel! gtr 7 (
        echo Robocopy failed: !errorlevel!
        pause
        exit /b !errorlevel!
    )

    rd /s /q "!TEMP_EXTRACT_PATH!"

    if not exist "!FINAL_PATH!\Library" (
        echo Installation failed: Library directory not found
        pause
        exit /b 1
    )
    if not exist "!FINAL_PATH!\share" (
        echo Installation failed: share directory not found
        pause
        exit /b 1
    )

    echo Adding to System PATH...
    powershell -Command "[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';!BIN_PATH!', 'Machine')"
    if !errorlevel! neq 0 (
        echo PATH update failed: !errorlevel!
        pause
        exit /b !errorlevel!
    )

    echo Verifying PATH update...
    powershell -Command "$newPath = [Environment]::GetEnvironmentVariable('Path', 'Machine'); if ($newPath -like '*!BIN_PATH!*') { exit 0 } else { exit 1 }"
    if !errorLevel! equ 0 (
        echo Installation completed successfully
        echo System PATH has been updated
    ) else (
        echo Installation completed but PATH update failed
        echo Please add "!BIN_PATH!" to your system PATH manually
    )
)

echo Current directory: %CD%

:: Change to project directory
echo Changing to project directory: !PROJECT_DIR!
cd /d "!PROJECT_DIR!"
if !errorlevel! neq 0 (
    echo Failed to change directory: !errorlevel!
    pause
    exit /b !errorlevel!
)

:: Create virtual environment
echo [4/6] Creating virtual environment...
python -m venv .venv
if !errorlevel! neq 0 (
    echo Virtual environment creation failed: !errorlevel!
    pause
    exit /b !errorlevel!
)

:: Activate virtual environment and set pip source
echo [5/6] Setting pip source...
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
echo [6/6] Installing project dependencies...
pip install -r requirements.txt
if !errorlevel! neq 0 (
    echo Dependencies installation failed: !errorlevel!
    pause
    exit /b !errorlevel!
)

echo.
echo [OK] All installations completed!
pause

endlocal