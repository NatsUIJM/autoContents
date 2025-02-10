@echo off
chcp 65001

:: 检查Chocolatey是否已安装
where choco >nul 2>nul
if %errorlevel% equ 0 (
    echo Chocolatey 已经安装，跳过安装步骤。
    exit /b 0
)

:: 设置执行策略并安装Chocolatey
echo 正在安装 Chocolatey...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))"