@echo off
REM Start the Accounts Desk on Windows.  First run asks you to create the admin login.
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
  .venv\Scripts\python -m pip install --quiet --upgrade pip
)
.venv\Scripts\pip install --quiet -r requirements.txt
echo.
echo   Accounts Desk running at  http://localhost:5100
echo   (the team opens the same address using this PC IP)
echo.
.venv\Scripts\python -m accounts.main
pause
