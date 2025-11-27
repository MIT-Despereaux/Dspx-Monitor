# Dspx-Monitor

Cryogenic Dilution Refrigerator Monitoring Dashboard built with Streamlit.

## Features

- **Temperature Monitoring**: Displays `full range`, `still`, and `Platine 4K` thermometer readings
- **Pressure Monitoring**: Shows `P1`, `P2`, `P3` pressure values
- **Flow & Turbo**: Monitors flow rate and turbo pump speed
- **Resistance Readings**: Displays `R MMR3 1`, `R MMR3 2`, `R MMR3 3`
- **Valve Status Grid**: Visual display of all 39 valves (VE1-VE39)
- **Slack Integration**: Send daily reports with min/max temps and rate of change

## Requirements

- Python 3.8.13
- Windows 7 SP1 32-bit compatible
- Edge 109 or compatible browser

## Installation

### 1. Create Conda Environment

```bash
conda create -n dspx_mon python=3.8.13
conda activate dspx_mon
```

### 2. Install Dependencies

```bash
pip install streamlit==1.22.0 pandas requests
```

## Usage

### Run the Dashboard

```bash
conda activate dspx_mon
streamlit run app.py
```

The dashboard will be available at `http://localhost:8501`

### Slack Integration

1. Create a Slack Incoming Webhook at https://api.slack.com/messaging/webhooks
2. Enter the webhook URL in the sidebar under "Slack Notifications"
3. Click "Send Daily Report" to send a summary to Slack

## Data Format

The app reads TSV files from the `data/` directory with the naming format `MMDDYY.txt`.

Expected columns include:
- `date`, `heures` (time)
- `full range`, `still`, `Platine 4K` (temperatures)
- `P1`, `P2`, `P3` (pressures)
- `FLOW µm`, `Pumping turbo speed`
- `R MMR3 1`, `R MMR3 2`, `R MMR3 3` (resistances)
- `VE1` through `VE39` (valve states)

## File Structure

```
Dspx-Monitor/
├── app.py              # Main Streamlit dashboard
├── config.json         # Slack webhook URL storage
├── README.md           # This file
└── data/
    └── *.txt           # TSV data files (MMDDYY.txt format)
```
