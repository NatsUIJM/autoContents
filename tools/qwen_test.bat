@echo off
cd ..
call .venv\Scripts\activate.bat
cd tools
python qwen_test.py
pause