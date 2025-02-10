@echo off
chcp 65001

:: 检查Python 3.11是否已安装 
python --version 2>nul | findstr "3.11" >nul
if %errorlevel% equ 0 (
    echo Python 3.11已安装，跳过安装步骤...
) else (
    echo 正在安装Python 3.11...
    choco install python311 -y
)

:: 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo This script requires administrator privileges.
    echo Please run this script as administrator.
    pause
    exit /b 1
)

:: 设置下载链接和文件名
set "URL=https://github.com/oschwartz10612/poppler-windows/releases/download/v24.08.0-0/Release-24.08.0-0.zip"
set "FILENAME=Release-24.08.0-0.zip"
set "DOWNLOAD_PATH=%USERPROFILE%\Downloads\%FILENAME%"
set "TEMP_EXTRACT_PATH=%TEMP%\poppler_temp"
set "FINAL_PATH=C:\Program Files\poppler-24.08.0"
set "BIN_PATH=%FINAL_PATH%\Library\bin"

:: 创建临时目录
if exist "%TEMP_EXTRACT_PATH%" rd /s /q "%TEMP_EXTRACT_PATH%"
mkdir "%TEMP_EXTRACT_PATH%"

:: 下载文件
echo Downloading %FILENAME%...
powershell -Command "(New-Object Net.WebClient).DownloadFile('%URL%', '%DOWNLOAD_PATH%')"

:: 先解压到临时目录
echo Extracting files...
powershell -Command "Expand-Archive -Path '%DOWNLOAD_PATH%' -DestinationPath '%TEMP_EXTRACT_PATH%' -Force"

:: 使用robocopy复制文件到最终目标
echo Installing files...
if exist "%FINAL_PATH%" rd /s /q "%FINAL_PATH%"
robocopy "%TEMP_EXTRACT_PATH%\poppler-24.08.0" "%FINAL_PATH%" /E /NFL /NDL /NJH /NJS /NC /NS /NP

:: 清理临时目录
rd /s /q "%TEMP_EXTRACT_PATH%"

:: 检查文件安装是否成功
if not exist "%FINAL_PATH%\Library" (
    echo Installation failed: Library directory not found.
    pause
    exit /b 1
)
if not exist "%FINAL_PATH%\share" (
    echo Installation failed: share directory not found.
    pause
    exit /b 1
)

:: 添加到系统Path
echo Adding to System PATH...
powershell -Command "[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';%BIN_PATH%', 'Machine')"

:: 检查Path是否添加成功
echo Verifying PATH update...
powershell -Command "$newPath = [Environment]::GetEnvironmentVariable('Path', 'Machine'); if ($newPath -like '*%BIN_PATH%*') { exit 0 } else { exit 1 }"
if %errorLevel% equ 0 (
    echo Installation completed successfully.
    echo System PATH has been updated.
) else (
    echo Installation completed but PATH update failed.
    echo Please add "%BIN_PATH%" to your system PATH manually.
)

pause