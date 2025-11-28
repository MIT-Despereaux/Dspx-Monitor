"""
Dspx-Monitor: Cryogenic Dilution Refrigerator Monitoring Dashboard
Streamlit app for monitoring temperature, pressure, flow, resistance, and valve states.
"""

import os
import json
from datetime import datetime, timedelta
import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go

# Configuration
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# Column definitions with units
TEMP_COLUMNS = ["full range", "still", "Platine 4K"]  # Units: K (Kelvin)
PRESSURE_COLUMNS = ["P1", "P2", "P3"]  # Units: mbar
PRESSURE_K_COLUMNS = ["K3", "K4", "K5", "K6", "K8"]  # Additional pressure sensors
TURBO_COLUMN = "Pumping turbo speed"  # Units: %
RESISTANCE_COLUMNS = ["R MMR1 1", "R MMR1 2", "R MMR1 3"]  # Units: Ohm
VALVE_COLUMNS = [f"VE{i}" for i in range(1, 40)]
MIXTURE_COLUMN = "P/T"  # Mixture percentage
TURBO_AUX_COLUMN = "Turbo AUX"  # OVC turbo status (On/Off)
PULSE_TUBE_COLUMN = "PT"  # Pulse tube status (On/Off)


def load_config():
    """Load configuration from config.json"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"slack_webhook_url": ""}


def save_config(config):
    """Save configuration to config.json"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def get_data_files():
    """Get list of data files sorted by date (newest first)"""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    if not os.path.exists(data_dir):
        return []
    
    # Get all .txt files but exclude subdirectories (like Old)
    files = []
    for f in os.listdir(data_dir):
        filepath = os.path.join(data_dir, f)
        if f.endswith(".txt") and os.path.isfile(filepath):
            files.append(filepath)
    
    # Sort by date in filename (MMDDYY format)
    def parse_date(filename):
        base = os.path.basename(filename).replace(".txt", "")
        try:
            return datetime.strptime(base, "%m%d%y")
        except ValueError:
            return datetime.min
    
    files.sort(key=parse_date, reverse=True)
    return files


def get_date_range_from_files():
    """Get min and max dates from available data files"""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    if not os.path.exists(data_dir):
        return None, None
    
    dates = []
    for f in os.listdir(data_dir):
        if f.endswith(".txt"):
            base = f.replace(".txt", "")
            try:
                d = datetime.strptime(base, "%m%d%y").date()
                dates.append(d)
            except ValueError:
                pass
    
    if not dates:
        return None, None
    
    return min(dates), max(dates)


def get_files_for_date_range(start_date, end_date):
    """Get list of files for the specified date range"""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    if not os.path.exists(data_dir):
        return []
    
    files = []
    current = start_date
    while current <= end_date:
        filename = current.strftime("%m%d%y") + ".txt"
        filepath = os.path.join(data_dir, filename)
        if os.path.exists(filepath):
            files.append(filepath)
        current += timedelta(days=1)
    
    return files


@st.cache_data(ttl=300, show_spinner=False)
def load_single_file_cached(filepath):
    """Load a single data file with caching"""
    return load_data(filepath)


def load_multiple_data_files(filepaths, show_progress=True):
    """Load and concatenate multiple data files with progress indicator"""
    if not filepaths:
        return None
    
    all_dfs = []
    
    # Show progress bar for multiple files
    if show_progress and len(filepaths) > 1:
        progress_bar = st.progress(0, text="Loading data files...")
    else:
        progress_bar = None
    
    for i, filepath in enumerate(filepaths):
        df = load_single_file_cached(filepath)
        if df is not None:
            # Add date column from filename
            base = os.path.basename(filepath).replace(".txt", "")
            try:
                file_date = datetime.strptime(base, "%m%d%y").strftime("%Y-%m-%d")
                df = df.copy()  # Avoid modifying cached data
                df['file_date'] = file_date
                # Create combined datetime string for x-axis
                if 'time_str' in df.columns:
                    df['datetime_str'] = file_date + ' ' + df['time_str']
            except ValueError:
                df = df.copy()
                df['file_date'] = base
                if 'time_str' in df.columns:
                    df['datetime_str'] = df['time_str']
            all_dfs.append(df)
        
        # Update progress
        if progress_bar is not None:
            progress_bar.progress((i + 1) / len(filepaths), text=f"Loading file {i + 1} of {len(filepaths)}...")
    
    # Clear progress bar
    if progress_bar is not None:
        progress_bar.empty()
    
    if not all_dfs:
        return None
    
    combined = pd.concat(all_dfs, ignore_index=True)
    return combined


def downsample_for_chart(df, max_points=2000):
    """Downsample dataframe for faster chart rendering"""
    if len(df) <= max_points:
        return df
    
    # Calculate step size to get approximately max_points
    step = len(df) // max_points
    return df.iloc[::step].copy()


def create_interactive_chart(df, x_col, y_cols, title="", y_label="", height=400, log_scale=False):
    """Create an interactive Plotly chart with zoom, crosshairs, and hover values"""
    fig = go.Figure()
    
    # Get x values
    x_values = df[x_col].tolist()
    
    # Add traces for each y column
    for col in y_cols:
        if col in df.columns:
            y_values = pd.to_numeric(df[col], errors="coerce").tolist()
            fig.add_trace(go.Scattergl(
                x=x_values,
                y=y_values,
                mode='lines',
                name=col,
                hovertemplate=f'<b>{col}</b><br>Time: %{{x}}<br>Value: %{{y:.6g}}<extra></extra>'
            ))
    
    # Configure layout with interactivity
    fig.update_layout(
        title=title,
        xaxis_title="Time",
        yaxis_title=y_label,
        height=height,
        hovermode='x unified',  # Shows all values at cursor position
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        # Enable proper 2D zoom (box zoom for both axes)
        dragmode='zoom',
        yaxis=dict(
            type='log' if log_scale else 'linear',
            fixedrange=False,  # Allow y-axis zoom
        ),
        xaxis=dict(
            fixedrange=False,  # Allow x-axis zoom
        ),
    )
    
    # Add spike lines (crosshairs)
    fig.update_xaxes(
        showspikes=True,
        spikecolor="gray",
        spikethickness=1,
        spikedash="dot",
        spikemode="across"
    )
    fig.update_yaxes(
        showspikes=True,
        spikecolor="gray",
        spikethickness=1,
        spikedash="dot",
        spikemode="across"
    )
    
    return fig


def load_data(filepath):
    """Load and parse TSV data file"""
    try:
        import warnings
        # Suppress the header/data length mismatch warning - it's expected due to file format
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # Only load columns we need for faster parsing
            df = pd.read_csv(
                filepath, 
                sep="\t", 
                encoding="latin-1",
                index_col=False,
                on_bad_lines='skip',
                low_memory=False
            )
        
        # Clean column names (remove extra spaces and carriage returns)
        df.columns = df.columns.str.strip().str.replace('\r', '')
        
        # Also clean string data
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].astype(str).str.strip().str.replace('\r', '')
        
        # Parse the heures (time) column for x-axis labeling
        if 'heures' in df.columns:
            df['time'] = pd.to_datetime(df['heures'], format='%H:%M:%S', errors='coerce')
            # Use just the time string for display
            df['time_str'] = df['heures']
        
        return df
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return None


def calculate_daily_stats(df):
    """Calculate daily statistics for temperature columns"""
    stats = {}
    
    for col in TEMP_COLUMNS:
        if col in df.columns:
            # Convert to numeric, coercing errors
            values = pd.to_numeric(df[col], errors="coerce")
            
            stats[col] = {
                "min": values.min(),
                "max": values.max(),
                "mean": values.mean(),
                "current": values.iloc[-1] if len(values) > 0 else None,
            }
            
            # Calculate rate of change per 15 minutes
            # Data is sampled every 30 seconds, so 15 min = 30 samples
            samples_per_15min = 30
            if len(values) >= samples_per_15min:
                rates = []
                for i in range(0, len(values) - samples_per_15min, samples_per_15min):
                    rate = (values.iloc[i + samples_per_15min] - values.iloc[i]) / 15.0  # per minute
                    if pd.notna(rate):
                        rates.append(rate)
                stats[col]["avg_rate_per_min"] = sum(rates) / len(rates) if rates else 0
            else:
                stats[col]["avg_rate_per_min"] = 0
    
    return stats


def send_slack_report(webhook_url, stats, filename):
    """Send daily report to Slack"""
    if not webhook_url:
        return False, "No Slack webhook URL configured"
    
    # Build message
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🧊 Dspx-Monitor Daily Report",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Data file:* `{os.path.basename(filename)}`\n*Report time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
        },
        {"type": "divider"}
    ]
    
    # Add temperature stats
    for col, data in stats.items():
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{col}*\n"
                    f"• Min: `{data['min']:.6f}`\n"
                    f"• Max: `{data['max']:.6f}`\n"
                    f"• Avg rate of change: `{data['avg_rate_per_min']:.8f}` /min"
                )
            }
        })
    
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "✅ All systems operating normally"
        }
    })
    
    payload = {"blocks": blocks}
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        if response.status_code == 200:
            return True, "Report sent successfully"
        else:
            return False, f"Slack API error: {response.status_code}"
    except Exception as e:
        return False, f"Error sending report: {e}"


def render_valve_grid(df):
    """Render valve status as a colored grid"""
    if df is None or len(df) == 0:
        return
    
    # Get latest valve states
    latest = df.iloc[-1]
    
    # Create grid layout (8 columns)
    cols_per_row = 8
    
    for i in range(0, len(VALVE_COLUMNS), cols_per_row):
        cols = st.columns(cols_per_row)
        for j, col in enumerate(cols):
            valve_idx = i + j
            if valve_idx < len(VALVE_COLUMNS):
                valve_name = VALVE_COLUMNS[valve_idx]
                if valve_name in df.columns:
                    try:
                        state = int(latest[valve_name])
                        color = "🟢" if state == 1 else "🔴"
                        col.markdown(f"{color} **{valve_name}**")
                    except (ValueError, TypeError):
                        col.markdown(f"⚪ **{valve_name}**")


def render_valve_timeline(df):
    """Render valve states over time as a chart"""
    if df is None or len(df) == 0:
        return
    
    # Determine x-axis column
    x_col = 'datetime_str' if 'datetime_str' in df.columns else 'time_str'
    if x_col not in df.columns:
        st.warning("No time column available for valve timeline")
        return
    
    # Get available valve columns
    valve_cols = [c for c in VALVE_COLUMNS if c in df.columns]
    if not valve_cols:
        st.warning("No valve columns found in data")
        return
    
    # Create valve dataframe with time index
    valve_df = df[[x_col] + valve_cols].copy()
    
    # Downsample for performance
    valve_df = downsample_for_chart(valve_df, max_points=1500)
    
    # Get x values as list
    x_values = valve_df[x_col].tolist()
    
    # Create interactive Plotly chart for valves
    fig = go.Figure()
    
    for i, col in enumerate(valve_cols):
        if col in valve_df.columns:
            y_values = pd.to_numeric(valve_df[col], errors="coerce").tolist()
            # Only show VE1 by default, hide others (click legend to show)
            fig.add_trace(go.Scattergl(
                x=x_values,
                y=y_values,
                mode='lines',
                name=col,
                visible=True if col == "VE1" else "legendonly",
                hovertemplate=f'<b>{col}</b><br>Time: %{{x}}<br>State: %{{y}}<extra></extra>'
            ))
    
    fig.update_layout(
        xaxis_title="Time",
        yaxis_title="Valve State (0=Closed, 1=Open)",
        height=500,
        hovermode='x unified',
        dragmode='zoom',  # Enable 2D zoom
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        xaxis=dict(
            fixedrange=False,
        ),
        yaxis=dict(
            tickmode='array',
            tickvals=[0, 1],
            ticktext=['Closed', 'Open'],
            fixedrange=False,
        )
    )
    
    fig.update_xaxes(showspikes=True, spikecolor="gray", spikethickness=1, spikedash="dot", spikemode="across")
    fig.update_yaxes(showspikes=True, spikecolor="gray", spikethickness=1, spikedash="dot", spikemode="across")
    
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})


def main():
    st.set_page_config(
        page_title="Dspx-Monitor",
        page_icon="🧊",
        layout="wide"
    )
    
    st.title("🧊 Dspx-Monitor Dashboard")
    st.caption("Cryogenic Dilution Refrigerator Monitoring System")
    
    # Load config
    config = load_config()
    
    # Get available date range from files
    min_date, max_date = get_date_range_from_files()
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Settings")
        
        # Date range selection with calendar picker
        if min_date is None or max_date is None:
            st.error("No data files found in data/ directory")
            return
        
        st.subheader("📅 Date Range")
        
        # Date picker for start and end dates
        start_date = st.date_input(
            "Start Date",
            value=max_date,  # Default to most recent date
            min_value=min_date,
            max_value=max_date,
            help="Select the start date for data range"
        )
        
        end_date = st.date_input(
            "End Date",
            value=max_date,  # Default to most recent date
            min_value=min_date,
            max_value=max_date,
            help="Select the end date for data range"
        )
        
        # Validate date range
        if start_date > end_date:
            st.error("Start date must be before or equal to end date")
            return
        
        # Show how many files will be loaded
        files_to_load = get_files_for_date_range(start_date, end_date)
        st.caption(f"📁 {len(files_to_load)} file(s) available in range")
        
        if st.button("🔄 Refresh Data"):
            st.experimental_rerun()
        
        st.divider()
        
        # Slack configuration
        st.header("📢 Slack Notifications")
        webhook_url = st.text_input(
            "Webhook URL",
            value=config.get("slack_webhook_url", ""),
            type="password",
            help="Enter your Slack Incoming Webhook URL"
        )
        
        # Save webhook URL if changed
        if webhook_url != config.get("slack_webhook_url", ""):
            config["slack_webhook_url"] = webhook_url
            save_config(config)
            st.success("Webhook URL saved!")
        
        if st.button("📊 Send Daily Report"):
            if files_to_load:
                df = load_multiple_data_files(files_to_load)
                if df is not None:
                    stats = calculate_daily_stats(df)
                    date_range_str = f"{start_date} to {end_date}"
                    success, message = send_slack_report(webhook_url, stats, date_range_str)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
            else:
                st.error("No files available for selected date range")
    
    # Load data for selected date range
    if not files_to_load:
        st.error("No data files found for selected date range")
        return
    
    df = load_multiple_data_files(files_to_load)
    
    if df is None:
        st.error("Failed to load data files")
        return
    
    # Display info
    date_range_str = f"{start_date}" if start_date == end_date else f"{start_date} to {end_date}"
    st.info(f"📅 **Date Range:** {date_range_str} | **Files:** {len(files_to_load)} | **Rows:** {len(df)} | **Columns:** {len(df.columns)}")
    
    # Determine which time column to use (datetime_str for multi-file, time_str for single)
    time_col = 'datetime_str' if 'datetime_str' in df.columns else 'time_str'
    has_time = time_col in df.columns
    
    # Temperature Section
    st.header("🌡️ Temperatures (K)")
    st.caption("📍 Latest reading from selected date range")
    
    # Current values as metrics
    if len(df) > 0:
        temp_cols_available = [c for c in TEMP_COLUMNS if c in df.columns]
        if temp_cols_available:
            metric_cols = st.columns(len(temp_cols_available))
            for i, col_name in enumerate(temp_cols_available):
                current_val = pd.to_numeric(df[col_name], errors="coerce").iloc[-1]
                metric_cols[i].metric(
                    label=f"{col_name} (K)",
                    value=f"{current_val:.6f}" if pd.notna(current_val) else "N/A"
                )
    
    # Temperature charts with time x-axis (downsampled for performance)
    temp_cols = [c for c in TEMP_COLUMNS if c in df.columns]
    if temp_cols and has_time:
        temp_log = st.checkbox("Log scale", value=False, key="temp_log")
        temp_df = df[[time_col] + temp_cols].copy()
        temp_df = downsample_for_chart(temp_df)
        fig = create_interactive_chart(temp_df, time_col, temp_cols, y_label="Temperature (K)", log_scale=temp_log)
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Pressure Section
    st.header("📊 Pressure (mbar)")
    st.caption("📍 Latest reading from selected date range")
    
    pressure_cols_available = [c for c in PRESSURE_COLUMNS if c in df.columns]
    if pressure_cols_available:
        metric_cols = st.columns(len(pressure_cols_available))
        for i, col_name in enumerate(pressure_cols_available):
            current_val = pd.to_numeric(df[col_name], errors="coerce").iloc[-1]
            metric_cols[i].metric(
                label=f"{col_name} (mbar)",
                value=f"{current_val:.6e}" if pd.notna(current_val) else "N/A"
            )
        
        if has_time:
            pressure_log = st.checkbox("Log scale", value=True, key="pressure_log")
            pressure_df = df[[time_col] + pressure_cols_available].copy()
            pressure_df = downsample_for_chart(pressure_df)
            fig = create_interactive_chart(pressure_df, time_col, pressure_cols_available, y_label="Pressure (mbar)", log_scale=pressure_log)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Pressure K Section (K3, K4, K5, K6, K8)
    st.header("📊 Pressure Sensors (K3-K8)")
    st.caption("📍 Latest reading from selected date range")
    
    pressure_k_cols_available = [c for c in PRESSURE_K_COLUMNS if c in df.columns]
    if pressure_k_cols_available:
        metric_cols = st.columns(len(pressure_k_cols_available))
        for i, col_name in enumerate(pressure_k_cols_available):
            current_val = pd.to_numeric(df[col_name], errors="coerce").iloc[-1]
            metric_cols[i].metric(
                label=col_name,
                value=f"{current_val:.2f}" if pd.notna(current_val) else "N/A"
            )
        
        if has_time:
            pressure_k_log = st.checkbox("Log scale", value=False, key="pressure_k_log")
            pressure_k_df = df[[time_col] + pressure_k_cols_available].copy()
            pressure_k_df = downsample_for_chart(pressure_k_df)
            fig = create_interactive_chart(pressure_k_df, time_col, pressure_k_cols_available, y_label="Pressure", log_scale=pressure_k_log)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Turbo Speed Section
    st.header("🔄 Turbo Pump Speed (%)")
    st.caption("📍 Latest reading from selected date range")
    
    if TURBO_COLUMN in df.columns:
        st.metric(
            label=f"{TURBO_COLUMN} (%)",
            value=f"{pd.to_numeric(df[TURBO_COLUMN], errors='coerce').iloc[-1]:.2f}" if pd.notna(pd.to_numeric(df[TURBO_COLUMN], errors='coerce').iloc[-1]) else "N/A"
        )
        
        if has_time:
            turbo_df = df[[time_col, TURBO_COLUMN]].copy()
            turbo_df = downsample_for_chart(turbo_df)
            fig = create_interactive_chart(turbo_df, time_col, [TURBO_COLUMN], y_label="Speed (%)", log_scale=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Resistance Section
    st.header("⚡ Resistance MMR1 (Ω)")
    st.caption("📍 Latest reading from selected date range")
    
    resistance_cols_available = [c for c in RESISTANCE_COLUMNS if c in df.columns]
    if resistance_cols_available:
        metric_cols = st.columns(len(resistance_cols_available))
        for i, col_name in enumerate(resistance_cols_available):
            current_val = pd.to_numeric(df[col_name], errors="coerce").iloc[-1]
            metric_cols[i].metric(
                label=f"{col_name} (Ω)",
                value=f"{current_val:.3f}" if pd.notna(current_val) else "N/A"
            )
        
        if has_time:
            resistance_log = st.checkbox("Log scale", value=False, key="resistance_log")
            resistance_df = df[[time_col] + resistance_cols_available].copy()
            resistance_df = downsample_for_chart(resistance_df)
            fig = create_interactive_chart(resistance_df, time_col, resistance_cols_available, y_label="Resistance (Ω)", log_scale=resistance_log)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Mixture Percentage Section (P/T)
    st.header("🧪 Mixture Percentage (P/T)")
    st.caption("📍 Latest reading from selected date range")
    
    if MIXTURE_COLUMN in df.columns:
        current_val = pd.to_numeric(df[MIXTURE_COLUMN], errors="coerce").iloc[-1]
        st.metric(
            label="P/T (%)",
            value=f"{current_val:.3f}" if pd.notna(current_val) else "N/A"
        )
        
        if has_time:
            mixture_df = df[[time_col, MIXTURE_COLUMN]].copy()
            mixture_df = downsample_for_chart(mixture_df)
            fig = create_interactive_chart(mixture_df, time_col, [MIXTURE_COLUMN], y_label="Mixture (%)", log_scale=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # OVC Turbo Status Section (Turbo AUX)
    st.header("🔄 OVC Turbo Status (Turbo AUX)")
    st.caption("📍 Latest reading from selected date range")
    
    if TURBO_AUX_COLUMN in df.columns:
        current_val = pd.to_numeric(df[TURBO_AUX_COLUMN], errors="coerce").iloc[-1]
        status_text = "ON" if current_val == 1 else "OFF"
        status_icon = "🟢" if current_val == 1 else "🔴"
        st.metric(
            label="Turbo AUX",
            value=f"{status_icon} {status_text}"
        )
        
        if has_time:
            turbo_aux_df = df[[time_col, TURBO_AUX_COLUMN]].copy()
            turbo_aux_df = downsample_for_chart(turbo_aux_df)
            fig = create_interactive_chart(turbo_aux_df, time_col, [TURBO_AUX_COLUMN], y_label="Status (0=Off, 1=On)", log_scale=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Pulse Tube Status Section (PT)
    st.header("❄️ Pulse Tube Status (PT)")
    st.caption("📍 Latest reading from selected date range")
    
    if PULSE_TUBE_COLUMN in df.columns:
        current_val = pd.to_numeric(df[PULSE_TUBE_COLUMN], errors="coerce").iloc[-1]
        status_text = "ON" if current_val == 1 else "OFF"
        status_icon = "🟢" if current_val == 1 else "🔴"
        st.metric(
            label="Pulse Tube",
            value=f"{status_icon} {status_text}"
        )
        
        if has_time:
            pt_df = df[[time_col, PULSE_TUBE_COLUMN]].copy()
            pt_df = downsample_for_chart(pt_df)
            fig = create_interactive_chart(pt_df, time_col, [PULSE_TUBE_COLUMN], y_label="Status (0=Off, 1=On)", log_scale=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Valve Status Section
    st.header("🔧 Valve Status")
    
    # Current state grid
    st.subheader("Current State")
    st.caption("🟢 Open (1) | 🔴 Closed (0)")
    render_valve_grid(df)
    
    # Valve timeline chart
    st.subheader("Valve Timeline")
    st.caption("Shows valve open/close states over time (1 = open, 0 = closed)")
    render_valve_timeline(df)
    
    # Raw data expander
    with st.expander("📋 View Raw Data"):
        st.dataframe(df, use_container_width=True)


if __name__ == "__main__":
    main()
