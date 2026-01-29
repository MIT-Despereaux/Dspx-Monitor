@echo off
REM Run the Dspx-Monitor background scheduler
REM This should be run separately from the Streamlit dashboard

cd /d "%~dp0"

REM Activate conda environment if available
where conda >nul 2>nul
if %ERRORLEVEL% == 0 (
    call conda activate dspx_mon 2>nul
)

REM Set the Slack report target (configure as needed)
REM Uncomment and set ONE of these:
set SLACK_REPORT_CHANNEL=#despereaux
REM set SLACK_REPORT_USER=U123456789

echo Starting Dspx-Monitor Scheduler...
echo Press Ctrl+C to stop
echo.

python scheduler.py

pause
