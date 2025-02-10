@echo off
chcp 65001

:: 获取bat脚本所在目录并切换到上级目录
set SCRIPT_DIR=%~dp0
cd /d %SCRIPT_DIR%..

:: 创建虚拟环境
echo 正在创建虚拟环境...
python -m venv .venv

:: 激活虚拟环境并设置pip源
echo 正在设置pip源...
call .venv\Scripts\activate.bat
pip config set global.index-url https://mirrors.aliyun.com/pypi/simple

:: 安装依赖
echo 正在安装项目依赖...
pip install -r requirements.txt