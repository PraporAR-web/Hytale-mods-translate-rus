@echo off
chcp 65001 >nul
python -c "import customtkinter" 2>nul || pip install -r requirements.txt
python app.py
pause
