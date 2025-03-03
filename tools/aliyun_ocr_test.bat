@echo off
cd ..
call .venv\Scripts\activate.bat
cd tools
python aliyun_ocr_test.py
pause