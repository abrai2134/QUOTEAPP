@echo off
REM Start the quotation app on Windows.  First run creates the database.
cd /d "%~dp0"

if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
  .venv\Scripts\python -m pip install --quiet --upgrade pip
  .venv\Scripts\pip install --quiet -r requirements.txt
)

.venv\Scripts\python -m app.seed
echo.
echo   Quotation app running at  http://localhost:5000
echo   (open the same address from your phone using this PC's IP)
echo.
.venv\Scripts\python -m app.main
pause
