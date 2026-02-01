@echo off
REM Dspx-Monitor Startup Script for Windows
REM Run this script from the Dspx-Monitor directory with conda environment activated

echo Starting Dspx-Monitor...
echo.

REM Start the scheduler in the background
echo Starting background scheduler...
start /B python scheduler.py
echo Scheduler started
echo.

echo Starting Streamlit dashboard...
echo The dashboard will be available at http://localhost:8501
echo Press Ctrl+C to stop all services.
echo.

REM Run Streamlit (will block until Ctrl+C)
streamlit run app.py --server.port 8501 --server.headless true

REM Cleanup after streamlit exits
echo.
echo Stopping services...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq scheduler.py*" >nul 2>&1
echo Services stopped
