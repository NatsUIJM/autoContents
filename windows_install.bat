@echo off

echo Setting global pip mirror to Aliyun...
pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

echo Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo Failed to create virtual environment.
    exit /b 1
)

echo Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo Failed to activate virtual environment.
    exit /b 1
)

echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    exit /b 1
)

echo Setup complete.