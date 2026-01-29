#!/bin/bash
# Dspx-Monitor Startup Script for Linux/Mac
# Run this script from the Dspx-Monitor directory with conda environment activated

echo "Starting Dspx-Monitor..."
echo ""

# Start the scheduler in the background
echo "Starting background scheduler..."
python scheduler.py &
SCHEDULER_PID=$!
echo "Scheduler started (PID: $SCHEDULER_PID)"
echo ""

# Function to clean up background processes on exit
cleanup() {
    echo ""
    echo "Stopping services..."
    if [ ! -z "$SCHEDULER_PID" ]; then
        kill $SCHEDULER_PID 2>/dev/null
        echo "Scheduler stopped"
    fi
    exit 0
}

# Set up trap to catch Ctrl+C and cleanup
trap cleanup INT TERM

echo "Starting Streamlit dashboard..."
echo "The dashboard will be available at http://localhost:8501"
echo "Press Ctrl+C to stop all services."
echo ""

# Run Streamlit (will block until Ctrl+C)
streamlit run app.py --server.port 8501 --server.headless true

# Cleanup after streamlit exits
cleanup
