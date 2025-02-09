@echo off
chcp 65001
title autoContents运行环境自动配置
color 0A

:: 设置工作目录为脚本所在目录
cd /d "%~dp0"

:: 检查管理员权限
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [√] 已获得管理员权限，继续执行...
) else (
    echo [×] 请以管理员权限运行此脚本！
    pause
    exit
)

:: 检查requirements.txt是否存在
if not exist "requirements.txt" (
    echo [×] requirements.txt文件不存在！
    echo [×] 请确保requirements.txt文件与本脚本在同一目录下
    pause
    exit
)

:: 设置执行策略并安装Chocolatey
echo [1/6] 正在安装Chocolatey...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))"

:: 检查Python 3.11是否已安装
python --version 2>nul | findstr "3.11" >nul
if %errorlevel% equ 0 (
    echo [2/6] Python 3.11已安装，跳过安装步骤...
) else (
    echo [2/6] 正在安装Python 3.11...
    choco install python311 -y
)

:: 安装Poppler
echo [3/6] 正在安装Poppler...
choco install poppler -y

:: 创建虚拟环境
echo [4/6] 正在创建虚拟环境...
python -m venv .venv

:: 激活虚拟环境并设置pip源
echo [5/6] 正在设置pip源...
call .venv\Scripts\activate.bat
pip config set global.index-url https://mirrors.aliyun.com/pypi/simple

:: 安装依赖
echo [6/6] 正在安装项目依赖...
pip install -r requirements.txt

echo.
echo [√] 所有安装已完成！
pause