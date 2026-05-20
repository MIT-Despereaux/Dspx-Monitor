@echo off
setlocal ENABLEDELAYEDEXPANSION

REM ---------------------------------------------------------
REM  Dspx-Monitor Startup Script for Windows
REM  Run this script from the Dspx-Monitor directory
REM  with the conda environment activated
REM ---------------------------------------------------------

if not defined SLACK_REPORT_CHANNEL set SLACK_REPORT_CHANNEL=#despereaux
echo Starting Dspx-Monitor...
echo.

REM ---------------------------------------------------------
REM Start the scheduler in the background
REM ---------------------------------------------------------
echo Starting background scheduler...
for /f "tokens=*" %%A in ('powershell -NoProfile -Command "Start-Process python -ArgumentList 'scheduler.py' -PassThru | Select-Object -ExpandProperty Id"') do set SCHEDULER_PID=%%A
echo Scheduler started (PID: !SCHEDULER_PID!)
echo.

REM ---------------------------------------------------------
REM Start Streamlit (blocks until Ctrl+C)
REM ---------------------------------------------------------
echo Starting Streamlit dashboard...
echo The dashboard will be available at http://localhost:8501
echo Press Ctrl+C to stop all services.
echo SELECT N/n TO THE PROMPT: Terminate batch job (Y/N)?
echo.

cmd /c streamlit run app.py --server.port 8501 --server.headless true

REM ---------------------------------------------------------
REM Cleanup after Streamlit exits
REM ---------------------------------------------------------
echo.
echo Stopping services...
if defined SCHEDULER_PID (
    wmic process where ProcessId=!SCHEDULER_PID! call terminate
) else (
    echo Warning: Could not determine scheduler PID, attempting generic termination
    wmic process where "name='python.exe' and CommandLine like '%%%scheduler.py%%%'" call terminate
)

endlocal
