@echo off
setlocal ENABLEDELAYEDEXPANSION

REM ---------------------------------------------------------
REM  Dspx-Monitor Startup Script for Windows
REM  Run this script from the Dspx-Monitor directory
REM  with the conda environment activated
REM ---------------------------------------------------------

set SLACK_REPORT_CHANNEL=#despereaux
echo Starting Dspx-Monitor...
echo.

REM ---------------------------------------------------------
REM Start the scheduler in the background
REM ---------------------------------------------------------
echo Starting background scheduler...
start /B python scheduler.py
echo Scheduler started
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
wmic process where "name='python.exe' and CommandLine like '%%%scheduler.py%%%'" call terminate

endlocal
