@echo off
setlocal

:: Step 1 - Optional: Create virtual environment if not exists
if not exist venv (
    python -m venv venv
)

:: Step 2 - Activate virtual environment
call venv\Scripts\activate.bat

:: Step 3 - Upgrade pip
python -m pip install --upgrade pip

:: Step 4 - Install dependencies
pip install -r requirements.txt

:: Step 5 - Run the script
python crm_monitor.py

:: Optional: Keep the console open after exit
pause
