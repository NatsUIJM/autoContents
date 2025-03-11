@echo off
cd ..
call .venv\Scripts\activate.bat
cd contents_editor
python merge.py
pause