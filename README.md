# Dspx-Monitor

Cryogenic Dilution Refrigerator Monitoring Dashboard built with Streamlit and Plotly.

## Features

### Temperature Monitoring
- Displays `full range`, `still`, and `Platine 4K` thermometer readings (K)
- Interactive charts with zoom, pan, and crosshairs
- Optional logarithmic Y-axis scale

### Pressure Monitoring
- Shows `P1`, `P2`, `P3` pressure values (mbar)
- Log scale enabled by default for pressure data
- Interactive charts with full zoom capabilities

### Turbo Pump Speed
- Monitors main turbo pump speed (%)
- Real-time status display

### Resistance Readings
- Displays `R MMR1 1`, `R MMR1 2`, `R MMR1 3` (Ω)
- Optional logarithmic Y-axis scale

### Mixture Percentage (P/T)
- Shows mixture percentage over time

### OVC Turbo Status (Turbo AUX)
- Displays On/Off status with visual indicators
- Timeline chart showing state changes

### Pulse Tube Status (PT)
- Displays On/Off status with visual indicators
- Timeline chart showing state changes

### Fridge State Monitoring
- The background scheduler tracks the refrigerator through `WARM`, `PT_COOLING_TO_4K`,
  `TRANSITION_TO_CONDENSATION`, `CONDENSING`, `DILUTION_COOLING_TO_100_MK`, and
  `OPERATING`
- State is inferred from the `full range`, `still`, `Platine 4K`, `PT`, and `K5` readings
- Runtime state, timers, and alarm counts are persisted in `logs/fridge_state.json`
- State transitions and invalid readings are written to the scheduler log

### Scheduler Alarms
- High-severity alert in every fridge state when the dilution turbo speed is above 0% and `P1` exceeds 1 mbar
- Alerts while operating when MC temperature exceeds 500 mK or Still temperature exceeds 1.3 K
- Alerts when transition to condensation exceeds 5 hours
- Alerts while operating when either `K4` or `K5` is above 900 mbar
- Alerts when PT is off in cold states, with a 1-minute grace period while operating
- Alerts on out-of-order state transitions
- Each continuous fault sends at most 3 successful Slack messages, at least 5 minutes apart

### Valve Status
- Visual grid display of all 39 valves (VE1-VE39)
- 🟢 Open | 🔴 Closed
- Interactive timeline chart (VE1 shown by default)
- Click legend to show/hide individual valves

### Slack Integration
- Configure webhook URL for notifications
- Send daily reports with min/max temps and rate of change

### Interactive Charts (Plotly)
- **Zoom**: Click and drag to zoom in on any area (X and Y axes)
- **Pan**: Hold Shift and drag to pan
- **Reset**: Double-click to reset zoom
- **Crosshairs**: Hover to see values at cursor position
- **Unified Hover**: Shows all trace values at cursor X position

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

**Option A: Using setup.py (recommended)**
```bash
pip install -e .
```

**Option B: Manual installation**
```bash
pip install streamlit==1.22.0 pandas requests plotly
```

## Usage

### Windows (Recommended)

1. Open Command Prompt
2. Navigate to the Dspx-Monitor directory
3. Activate the conda environment:
   ```cmd
   conda activate dspx_mon
   ```
4. Run the startup script:
   ```cmd
   run.bat
   ```

### Linux/Mac

```bash
conda activate dspx_mon
streamlit run app.py --server.port 8501
```

The dashboard will be available at `http://localhost:8501`

Run the scheduler separately to enable state tracking, alarms, refresh signaling, and
daily Slack reports:

```bash
python scheduler.py
```

Run the test suite with:

```bash
pytest
```

### Date Range Selection

- Use the calendar date pickers in the sidebar to select a date range
- The app will load and combine data from all files within the selected range
- Data is cached for 5 minutes for faster subsequent loads

### Slack Integration

1. Create a Slack Incoming Webhook at https://api.slack.com/messaging/webhooks
2. Enter the webhook URL in the sidebar under "Slack Notifications"
3. Click "Send Daily Report" to send a summary to Slack

## Data Format

The app reads TSV files from the `data/` directory with the naming format `MMDDYY.txt`.

Expected columns include:
- `date`, `heures` (time)
- `full range`, `still`, `Platine 4K` (temperatures in K)
- `P1`, `P2`, `P3` (pressures in mbar)
- `Pumping turbo speed` (turbo pump %)
- `R MMR1 1`, `R MMR1 2`, `R MMR1 3` (resistances in Ω)
- `P/T` (mixture percentage)
- `Turbo AUX` (OVC turbo status 0/1)
- `PT` (pulse tube status 0/1)
- `VE1` through `VE39` (valve states 0/1)

## File Structure

```
Dspx-Monitor/
├── app.py              # Main Streamlit dashboard
├── setup.py            # Package installation script
├── run.bat             # Windows startup script
├── config.json         # Slack webhook URL storage
├── README.md           # This file
└── data/
    └── *.txt           # TSV data files (MMDDYY.txt format)
```

## Troubleshooting

### Charts not rendering
- Ensure Plotly is installed: `pip install plotly`
- Try refreshing the page (F5)

### Slow loading with large date ranges
- Data is downsampled automatically for performance
- First load may take time; subsequent loads are cached

### Memory issues
- Reduce the date range selection
- Close other browser tabs
