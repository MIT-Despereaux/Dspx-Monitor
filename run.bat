@echo off
REM Dspx-Monitor Startup Script for Windows
REM Run this script from the Dspx-Monitor directory with conda environment activated

echo Starting Dspx-Monitor Dashboard...
echo.
echo The dashboard will be available at http://localhost:8501
echo Press Ctrl+C to stop the server.
echo.

streamlit run app.py --server.port 8501 --server.headless true
