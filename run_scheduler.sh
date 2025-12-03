#!/bin/bash
# Run the Dspx-Monitor background scheduler
# This should be run separately from the Streamlit dashboard

cd "$(dirname "$0")"

# Activate conda environment if available
if command -v conda &> /dev/null; then
    eval "$(conda shell.bash hook)"
    conda activate dspx_mon 2>/dev/null || true
fi

# Set the Slack report target (configure as needed)
# Uncomment and set ONE of these:
# export SLACK_REPORT_CHANNEL="#your-channel"
# export SLACK_REPORT_USER="U123456789"

echo "Starting Dspx-Monitor Scheduler..."
echo "Press Ctrl+C to stop"
echo ""

python scheduler.py
