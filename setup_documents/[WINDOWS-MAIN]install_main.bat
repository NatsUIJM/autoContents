@echo off
chcp 65001
title autoContents运行环境自动配置
color 0A

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

echo [1/4] 正在安装Chocolatey...
call install_choco.bat

echo [2/4] 正在安装Python和Poppler...
call install_python_poppler.bat

echo [3/4] 正在配置虚拟环境...
call setup_venv.bat

echo [4/4] 正在配置API密钥...
call config_api_keys.bat

echo.
echo [√] 所有安装已完成！
pause