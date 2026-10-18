@echo off
REM One-click launcher for Windows. Double-click this file or run it from cmd.
cd /d "%~dp0"
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate
echo Installing requirements...
pip install -q streamlit anthropic
echo Starting app... your browser will open at http://localhost:8501
streamlit run app.py
pause
