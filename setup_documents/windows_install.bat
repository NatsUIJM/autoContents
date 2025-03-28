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
pdfinfo -v >"%TEMP%\pdfinfo_output.txt" 2>&1
set PDFINFO_EXIT=%errorlevel%

if %PDFINFO_EXIT% equ 9009 (
    echo Poppler not found, proceeding with installation...
) else (
    if exist "%TEMP%\pdfinfo_output.txt" (
        findstr "pdfinfo version 24.08.0" "%TEMP%\pdfinfo_output.txt" >nul
        set FINDSTR_EXIT=%errorlevel%
        if !FINDSTR_EXIT! equ 0 (
            echo Poppler 24.08.0 is already installed, skipping...
            goto poppler_done
        )
    )
)

echo Installing Poppler...
echo Due to GitHub's limited accessibility in mainland China, we have chosen to include the Poppler package directly in the project files for installation and deployment. To access the official repository, please visit https://github.com/oschwartz10612/poppler-windows. We extend our special thanks to the original author for their open-source contribution.
set "FILENAME=Release 24.08.0-0.zip"
set "SOURCE_PATH=%SCRIPT_DIR%!FILENAME!"
set "TEMP_EXTRACT_PATH=%TEMP%\poppler_temp"
set "FINAL_PATH=C:\Program Files\poppler-24.08.0"
set "BIN_PATH=!FINAL_PATH!\Library\bin"

if not exist "!SOURCE_PATH!" (
    echo Error: Installation file not found: !SOURCE_PATH!
    echo Please ensure !FILENAME! is in the same directory as this script
    pause
    exit /b 1
)

echo Creating temporary directory...
if exist "!TEMP_EXTRACT_PATH!" rd /s /q "!TEMP_EXTRACT_PATH!"
mkdir "!TEMP_EXTRACT_PATH!"
if !errorlevel! neq 0 (
    echo Failed to create temp directory: !errorlevel!
    pause
    exit /b !errorlevel!
)

echo Extracting files...
powershell -Command "$ProgressPreference = 'Continue'; Expand-Archive -Path '!SOURCE_PATH!' -DestinationPath '!TEMP_EXTRACT_PATH!' -Force"
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

powershell -Command "$newPath = [Environment]::GetEnvironmentVariable('Path', 'Machine'); if ($newPath -like '*!BIN_PATH!*') { exit 0 } else { exit 1 }"
if !errorLevel! equ 0 (
    echo Installation completed successfully
    echo System PATH has been updated
) else (
    echo Installation completed but PATH update failed
    echo Please add "!BIN_PATH!" to your system PATH manually
)

:poppler_done
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