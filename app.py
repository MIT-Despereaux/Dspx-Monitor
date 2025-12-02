"""
Dspx-Monitor: Cryogenic Dilution Refrigerator Monitoring Dashboard
Streamlit app for monitoring temperature, pressure, flow, resistance, and valve states.
"""

from __future__ import annotations

import os
import base64
import logging
from datetime import datetime, timedelta
import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Setup logging
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Create a unique log file for each app run with timestamp
# Use session state to persist the log filename across Streamlit reruns
if 'log_filename' not in st.__dict__.get('session_state', {}):
    _log_filename = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log"
else:
    _log_filename = None

LOG_FILENAME = _log_filename if _log_filename else datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log"
LOG_FILEPATH = os.path.join(LOG_DIR, LOG_FILENAME)

# Configure logging with explicit handler setup
logger = logging.getLogger("dspx_monitor")
logger.setLevel(logging.INFO)

# Prevent duplicate handlers by checking if we already have a file handler for this path
_has_handlers = False
for handler in logger.handlers:
    if isinstance(handler, logging.FileHandler):
        _has_handlers = True
        break

if not _has_handlers:
    # Clear any existing handlers first
    logger.handlers.clear()
    
    # File handler
    file_handler = logging.FileHandler(LOG_FILEPATH, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)
    
    # Prevent propagation to root logger (avoids duplicates)
    logger.propagate = False
    
    # Initial startup messages
    print("=== Dspx-Monitor Application Started ===")
    print(f"Log file: {LOG_FILEPATH}")
    logger.info("=== Dspx-Monitor Application Started ===")
    logger.info(f"Log file: {LOG_FILEPATH}")

# Load secrets: First check OS environment variables, then fall back to slack.secret file
SECRETS = {}

# Define the secret keys we're looking for
SECRET_KEYS = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_SIGNING_SECRET"]

# First, try to get from OS environment variables
for key in SECRET_KEYS:
    env_value = os.environ.get(key)
    if env_value:
        SECRETS[key] = env_value
        logger.info(f"Loaded {key} from environment variable")

# Then, read from slack.secret file for any keys not already set from env
if os.path.exists("slack.secret"):
    logger.info("Reading secrets from slack.secret file")
    with open("slack.secret", "r", encoding="utf-8") as f:
        lines = f.readlines()
        if lines:
            for line in lines:
                # ignore lines starting with #
                if line.strip().startswith('#'):
                    continue
                key_value = line.strip().split('=', 1)
                if len(key_value) == 2:
                    key = key_value[0].strip()
                    value = key_value[1].strip()
                    # Only use file value if not already set from environment
                    if key not in SECRETS:
                        SECRETS[key] = value
                        logger.info(f"Loaded {key} from slack.secret file")
else:
    logger.warning("slack.secret file not found")

# Configuration
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
# CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# Column definitions with units
TEMP_COLUMNS = ["full range", "still", "Platine 4K"]  # Units: K (Kelvin)
TEMP_COLUMNS_ALIAS = {
    "full range": "Full Range (K)",
    "still": "Still (K)",
    "Platine 4K": "Platine 4K (K)"
}
PRESSURE_COLUMNS = ["P1", "P2", "P3"]  # Units: mbar
PRESSURE_K_COLUMNS = ["K3", "K4", "K5", "K6", "K8"]  # Additional pressure sensors
TURBO_COLUMN = "Pumping turbo speed"  # Units: %
RESISTANCE_COLUMNS = ["R MMR1 1", "R MMR1 2", "R MMR1 3"]  # Units: Ohm
MIXTURE_COLUMN = "P/T"  # Mixture percentage
TURBO_AUX_COLUMN = "Turbo AUX"  # OVC turbo status (On/Off)
PULSE_TUBE_COLUMN = "PT"  # Pulse tube status (On/Off)

# Valve positions for the fridge diagram (x, y coordinates in SVG viewBox units)
# These positions need to be calibrated to match the actual diagram
# Format: {valve_name: (x, y)}
VALVE_POSITIONS = {
    "VE1": (698, 135),
    "VE2": (698, 798),
    "VE3": (698, 1319),
    "VE5": (71, 1319),
    "VE6": (71, 798),
    "VE7": (71, 135),
    "VE8": (793, 798),
    "VE9": (561, 1320),
    "VE12": (346, 1126),
    "VE13": (257, 798),
    "VE14": (380, 798),
    "VE16": (258, 1319),
    "VE17": (166, 694),
    "VE22": (254, 135),
    "VE23": (877, 187),
    "VE26": (605, 1126),
    "VE27": (399, 1320),
    "VE28": (967, 1320),
    "VE30": (322, 562),
    "VE31": (456, 350),
    "VE32": (614, 560),
    "VE33": (877, 694),
    "VE37": (611, 97),
}
VALVE_COLUMNS = list(VALVE_POSITIONS.keys())


def display_metric(label, value):
    """Display a metric value (compatible with Streamlit 0.62)"""
    st.markdown(f"**{label}:** {value}")

def send_slack_dm(bot_token: str, user_id: str, message: str, blocks: list = None) -> tuple[bool, str]:
    """
    Send a direct message to a specific user.
    
    Args:
        bot_token: Slack bot token (xoxb-...)
        user_id: The user's Slack ID (e.g., U123456789)
        message: Plain text message (used as fallback for blocks)
        blocks: Optional Block Kit blocks for rich formatting
    
    Returns:
        Tuple of (success: bool, message: str)
    """
    logger.info(f"Attempting to send DM to user: {user_id}")
    
    if not bot_token:
        logger.error("No Slack bot token configured")
        return False, "No Slack bot token configured"
    if not user_id:
        logger.error("No user ID provided")
        return False, "No user ID provided"
    
    try:
        client = WebClient(token=bot_token)
        
        # Open a DM conversation with the user (creates one if it doesn't exist)
        response = client.conversations_open(users=[user_id])
        dm_channel_id = response["channel"]["id"]
        logger.debug(f"Opened DM channel: {dm_channel_id}")
        
        # Post the message to the DM channel
        kwargs = {
            "channel": dm_channel_id,
            "text": message
        }
        if blocks:
            kwargs["blocks"] = blocks
        
        client.chat_postMessage(**kwargs)
        logger.info(f"DM sent successfully to user {user_id}")
        return True, f"DM sent successfully to user {user_id}"
    
    except SlackApiError as e:
        logger.error(f"Slack API error sending DM: {e.response['error']}")
        return False, f"Slack API error: {e.response['error']}"
    except Exception as e:
        logger.exception(f"Error sending DM: {str(e)}")
        return False, f"Error sending DM: {str(e)}"


def send_slack_channel_message(bot_token: str, channel: str, message: str, blocks: list = None) -> tuple[bool, str]:
    """
    Send a message to a public or private channel.
    
    Args:
        bot_token: Slack bot token (xoxb-...)
        channel: Channel name (e.g., #general) or channel ID (e.g., C123456789)
        message: Plain text message (used as fallback for blocks)
        blocks: Optional Block Kit blocks for rich formatting
    
    Returns:
        Tuple of (success: bool, message: str)
    """
    logger.info(f"Attempting to send message to channel: {channel}")
    
    if not bot_token:
        logger.error("No Slack bot token configured")
        return False, "No Slack bot token configured"
    if not channel:
        logger.error("No channel provided")
        return False, "No channel provided"
    
    # Remove # prefix if present
    if channel.startswith("#"):
        channel = channel[1:]
    
    try:
        client = WebClient(token=bot_token)
        
        kwargs = {
            "channel": channel,
            "text": message
        }
        if blocks:
            kwargs["blocks"] = blocks
        
        client.chat_postMessage(**kwargs)
        logger.info(f"Message sent successfully to channel {channel}")
        return True, f"Message sent successfully to channel {channel}"
    
    except SlackApiError as e:
        logger.error(f"Slack API error sending to channel: {e.response['error']}")
        return False, f"Slack API error: {e.response['error']}"
    except Exception as e:
        logger.exception(f"Error sending message to channel: {str(e)}")
        return False, f"Error sending message: {str(e)}"


def send_slack_message(bot_token: str, target: str, message: str, blocks: list = None, is_user: bool = False) -> tuple[bool, str]:
    """
    Unified function to send a message to either a user (DM) or a channel.
    
    Args:
        bot_token: Slack bot token (xoxb-...)
        target: Either a user ID (for DM) or channel name/ID (for channel message)
        message: Plain text message (used as fallback for blocks)
        blocks: Optional Block Kit blocks for rich formatting
        is_user: If True, treat target as a user ID and send a DM
    
    Returns:
        Tuple of (success: bool, message: str)
    """
    if is_user:
        return send_slack_dm(bot_token, target, message, blocks)
    else:
        return send_slack_channel_message(bot_token, target, message, blocks)


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


@st.cache(ttl=300, show_spinner=False, allow_output_mutation=True)
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
        progress_bar = st.progress(0)
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
            progress_bar.progress((i + 1) / len(filepaths))
    
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
    logger.info(f"Loading data file: {filepath}")
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
        
        logger.info(f"Loaded {len(df)} rows, {len(df.columns)} columns from {os.path.basename(filepath)}")
        return df
    except Exception as e:
        logger.exception(f"Error loading data file {filepath}: {e}")
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


def build_report_blocks(stats, filename):
    """Build Slack Block Kit blocks for the daily report"""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🌡️ Dspx-Monitor Daily Report",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Data file:* `{os.path.basename(filename) if '/' in filename else filename}`\n*Report time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
        },
        {"type": "divider"}
    ]
    
    # Add temperature stats
    for col, data in stats.items():
        alias = TEMP_COLUMNS_ALIAS.get(col, col)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{alias}*\n"
                    f"• Min: `{data['min']:.4f}`\n"
                    f"• Max: `{data['max']:.4f}`\n"
                    f"• Current: `{data['current']:.4f}`\n"
                    f"• Avg rate of change: `{data['avg_rate_per_min']:.8f}` /min"
                )
            }
        })
    
    return blocks


def build_report_text(stats, filename):
    """Build plain text version of the daily report (for fallback/notifications)"""
    lines = [
        "🌡️ Dspx-Monitor Daily Report",
        f"Data: {os.path.basename(filename) if '/' in filename else filename}",
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ""
    ]
    
    for col, data in stats.items():
        lines.append(f"{col}: Min={data['min']:.6f}, Max={data['max']:.6f}, Rate={data['avg_rate_per_min']:.8f}/min")
        
    return "\n".join(lines)


def send_slack_report_sdk(bot_token: str, target: str, stats: dict, filename: str, is_user: bool = False) -> tuple[bool, str]:
    """
    Send daily report to Slack using the SDK (supports both channels and DMs).
    
    Args:
        bot_token: Slack bot token
        target: Channel name/ID or user ID
        stats: Dictionary of statistics from calculate_daily_stats()
        filename: Name of the data file or date range string
        is_user: If True, send as a DM to the user
    
    Returns:
        Tuple of (success: bool, message: str)
    """
    blocks = build_report_blocks(stats, filename)
    text = build_report_text(stats, filename)
    
    return send_slack_message(bot_token, target, text, blocks, is_user)


def render_valve_grid(df):
    """Render valve status as a colored grid"""
    if df is None or len(df) == 0:
        return
    
    # Get latest valve states
    latest = df.iloc[-1]
    
    # Display valve states in a simple list
    valve_states = []
    for valve_name in VALVE_COLUMNS:
        if valve_name in df.columns:
            try:
                state = int(latest[valve_name])
                color = "[O]" if state == 1 else "[X]"
                valve_states.append(f"{color} {valve_name}")
            except (ValueError, TypeError):
                valve_states.append(f"[?] {valve_name}")
    
    # Display in rows of 8
    for i in range(0, len(valve_states), 8):
        st.write(" | ".join(valve_states[i:i+8]))


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

def render_fridge_diagram(df):
    """Render the fridge diagram with valve status overlays"""
    if df is None or len(df) == 0:
        st.warning("No data available for diagram")
        return
    
    # Load the static SVG background
    svg_path = os.path.join(ASSETS_DIR, "dspx_diagram_static.svg")
    if not os.path.exists(svg_path):
        st.warning(f"Diagram not found at {svg_path}")
        return
    
    # Get latest valve states
    latest = df.iloc[-1]
    valve_states = {}
    for valve in VALVE_COLUMNS:
        if valve in df.columns:
            try:
                valve_states[valve] = int(latest[valve])
            except (ValueError, TypeError):
                valve_states[valve] = -1  # Unknown state
    
    # Read the base SVG
    with open(svg_path, "r", encoding="utf-8") as f:
        svg_content = f.read()
    
    # Create valve overlay SVG elements
    valve_overlays = []
    for valve, pos in VALVE_POSITIONS.items():
        if valve in valve_states:
            state = valve_states[valve]
            if state == 1:
                color = "#00ff00"  # Green for open
            elif state == 0:
                color = "#ff0000"  # Red for closed
            else:
                color = "#808080"  # Gray for unknown
            
            x, y = pos
            # Create a circle with the valve state
            valve_overlays.append(
                f'<g transform="translate({x},{y})">' 
                f'<circle r="28" fill="{color}" stroke="#000" stroke-width="3" opacity="0.9"/>'
                f'<text x="0" y="5" text-anchor="middle" font-size="20" font-weight="bold" fill="#000">{valve.replace("VE", "")}</text>'
                f'</g>'
            )
    
    # Insert valve overlays into SVG (before closing </svg> tag)
    overlay_group = '<g id="valve-overlays">' + ''.join(valve_overlays) + '</g>'
    modified_svg = svg_content.replace("</svg>", overlay_group + "</svg>")
    
    # Encode SVG as base64 and display as image (Streamlit 0.62 compatible)
    b64 = base64.b64encode(modified_svg.encode("utf-8")).decode("utf-8")
    html = f'<p style="text-align:center;"><img src="data:image/svg+xml;base64,{b64}" style="max-width: 600px;"/></p>'
    st.write(html, unsafe_allow_html=True)
    
    # Add a legend
    st.write("[GREEN] Open | [RED] Closed | [GRAY] Unknown")


def main():
    # Note: st.set_page_config not available in Streamlit 0.62
    # Page will use default settings
    
    logger.info("Dashboard main() function called")
    
    st.title("Dspx-Monitor Dashboard")
    st.text("Cryogenic Dilution Refrigerator Monitoring System")
    
    # Get available date range from files
    min_date, max_date = get_date_range_from_files()
    logger.info(f"Available date range: {min_date} to {max_date}")
    
    # Sidebar
    st.sidebar.header("Settings")
    
    # Date range selection with calendar picker
    if min_date is None or max_date is None:
        logger.warning("No data files found in data/ directory")
        st.sidebar.error("No data files found in data/ directory")
        return
    
    st.sidebar.subheader("Date Range")
    
    # Date picker for start and end dates
    start_date = st.sidebar.date_input(
        "Start Date",
        value=max_date,  # Default to most recent date
        min_value=min_date,
        max_value=max_date
    )
    
    end_date = st.sidebar.date_input(
        "End Date",
        value=max_date,  # Default to most recent date
        min_value=min_date,
        max_value=max_date
    )
    
    # Validate date range
    if start_date > end_date:
        logger.warning(f"Invalid date range: {start_date} > {end_date}")
        st.sidebar.error("Start date must be before or equal to end date")
        return
    
    # Show how many files will be loaded
    files_to_load = get_files_for_date_range(start_date, end_date)
    logger.info(f"Selected date range: {start_date} to {end_date}, {len(files_to_load)} files to load")
    st.sidebar.text(f"{len(files_to_load)} file(s) available in range")
    
    if st.sidebar.button("Refresh Data"):
        logger.info("User requested data refresh")
        st.caching.clear_cache()
    
    st.sidebar.markdown("---")
    
    # Slack configuration
    st.sidebar.header("Slack Notifications")
    
    # Check if bot token is available from environment or secrets file
    bot_token = SECRETS.get("SLACK_BOT_TOKEN", "")
    has_bot_token = bool(bot_token)
    
    if has_bot_token:
        # Check if it came from environment or file
        if os.environ.get("SLACK_BOT_TOKEN"):
            st.sidebar.success("✓ Bot token configured (from environment variable)")
        else:
            st.sidebar.success("✓ Bot token configured (from slack.secret)")
    else:
        st.sidebar.warning("⚠ No bot token found. Set SLACK_BOT_TOKEN env var or add to slack.secret")
    
    # Message destination selection
    st.sidebar.subheader("Send Report To")
    send_method = st.sidebar.radio(
        "Destination Type",
        options=["Channel", "User (DM)"],
        index=0
    )
    
    if send_method == "Channel":
        st.sidebar.text("Enter channel name (#general) or ID (C123456789)")
        channel = st.sidebar.text_input(
            "Channel Name or ID",
            value=""
        )
        
        if st.sidebar.button("Send to Channel"):
            if not has_bot_token:
                st.sidebar.error("Bot token not configured. Set SLACK_BOT_TOKEN env var or add to slack.secret")
            elif not channel:
                st.sidebar.error("Please enter a channel name or ID")
            elif files_to_load:
                df = load_multiple_data_files(files_to_load)
                if df is not None:
                    stats = calculate_daily_stats(df)
                    date_range_str = f"{start_date} to {end_date}"
                    success, message = send_slack_report_sdk(bot_token, channel, stats, date_range_str, is_user=False)
                    if success:
                        st.sidebar.success(message)
                    else:
                        st.sidebar.error(message)
            else:
                st.sidebar.error("No files available for selected date range")
    
    elif send_method == "User (DM)":
        st.sidebar.text("Enter user ID (starts with U, e.g., U123456789)")
        user_id = st.sidebar.text_input(
            "User ID",
            value=""
        )
        
        if st.sidebar.button("Send DM to User"):
            if not has_bot_token:
                st.sidebar.error("Bot token not configured. Set SLACK_BOT_TOKEN env var or add to slack.secret")
            elif not user_id:
                st.sidebar.error("Please enter a user ID")
            elif files_to_load:
                df = load_multiple_data_files(files_to_load)
                if df is not None:
                    stats = calculate_daily_stats(df)
                    date_range_str = f"{start_date} to {end_date}"
                    success, message = send_slack_report_sdk(bot_token, user_id, stats, date_range_str, is_user=True)
                    if success:
                        st.sidebar.success(message)
                    else:
                        st.sidebar.error(message)
            else:
                st.sidebar.error("No files available for selected date range")
    
    # Load data for selected date range
    if not files_to_load:
        logger.warning("No data files found for selected date range")
        st.error("No data files found for selected date range")
        return
    
    logger.info(f"Loading {len(files_to_load)} data files for date range {start_date} to {end_date}")
    df = load_multiple_data_files(files_to_load)
    
    if df is None:
        logger.error("Failed to load data files")
        st.error("Failed to load data files")
        return
    
    # Display info
    date_range_str = f"{start_date}" if start_date == end_date else f"{start_date} to {end_date}"
    logger.info(f"Successfully loaded data: {len(df)} rows, {len(df.columns)} columns")
    st.info(f"Date Range: {date_range_str} | Files: {len(files_to_load)} | Rows: {len(df)} | Columns: {len(df.columns)}")
    
    # Determine which time column to use (datetime_str for multi-file, time_str for single)
    time_col = 'datetime_str' if 'datetime_str' in df.columns else 'time_str'
    has_time = time_col in df.columns
    
    # Temperature Section
    st.header("Temperatures (K)")
    st.text("Latest reading from selected date range")
    
    # Current values as metrics
    if len(df) > 0:
        temp_cols_available = [c for c in TEMP_COLUMNS if c in df.columns]
        if temp_cols_available:
            for col_name in temp_cols_available:
                current_val = pd.to_numeric(df[col_name], errors="coerce").iloc[-1]
                val_str = f"{current_val:.6f}" if pd.notna(current_val) else "N/A"
                display_metric(f"{col_name} (K)", val_str)
    
    # Temperature charts with time x-axis (downsampled for performance)
    temp_cols = [c for c in TEMP_COLUMNS if c in df.columns]
    if temp_cols and has_time:
        temp_log = st.checkbox("Log scale", value=False, key="temp_log")
        temp_df = df[[time_col] + temp_cols].copy()
        temp_df = downsample_for_chart(temp_df)
        fig = create_interactive_chart(temp_df, time_col, temp_cols, y_label="Temperature (K)", log_scale=temp_log)
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Pressure Section
    st.header("Pressure (mbar)")
    st.text("Latest reading from selected date range")
    
    pressure_cols_available = [c for c in PRESSURE_COLUMNS if c in df.columns]
    if pressure_cols_available:
        for col_name in pressure_cols_available:
            current_val = pd.to_numeric(df[col_name], errors="coerce").iloc[-1]
            val_str = f"{current_val:.6e}" if pd.notna(current_val) else "N/A"
            display_metric(f"{col_name} (mbar)", val_str)
        
        if has_time:
            pressure_log = st.checkbox("Log scale", value=True, key="pressure_log")
            pressure_df = df[[time_col] + pressure_cols_available].copy()
            pressure_df = downsample_for_chart(pressure_df)
            fig = create_interactive_chart(pressure_df, time_col, pressure_cols_available, y_label="Pressure (mbar)", log_scale=pressure_log)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Pressure K Section (K3, K4, K5, K6, K8)
    st.header("Pressure Sensors (K3-K8)")
    st.text("Latest reading from selected date range")
    
    pressure_k_cols_available = [c for c in PRESSURE_K_COLUMNS if c in df.columns]
    if pressure_k_cols_available:
        for col_name in pressure_k_cols_available:
            current_val = pd.to_numeric(df[col_name], errors="coerce").iloc[-1]
            val_str = f"{current_val:.2f}" if pd.notna(current_val) else "N/A"
            display_metric(col_name, val_str)
        
        if has_time:
            pressure_k_log = st.checkbox("Log scale", value=False, key="pressure_k_log")
            pressure_k_df = df[[time_col] + pressure_k_cols_available].copy()
            pressure_k_df = downsample_for_chart(pressure_k_df)
            fig = create_interactive_chart(pressure_k_df, time_col, pressure_k_cols_available, y_label="Pressure", log_scale=pressure_k_log)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Turbo Speed Section
    st.header("Turbo Pump Speed (%)")
    st.text("Latest reading from selected date range")
    
    if TURBO_COLUMN in df.columns:
        current_val = pd.to_numeric(df[TURBO_COLUMN], errors='coerce').iloc[-1]
        val_str = f"{current_val:.2f}" if pd.notna(current_val) else "N/A"
        display_metric(f"{TURBO_COLUMN} (%)", val_str)
        
        if has_time:
            turbo_df = df[[time_col, TURBO_COLUMN]].copy()
            turbo_df = downsample_for_chart(turbo_df)
            fig = create_interactive_chart(turbo_df, time_col, [TURBO_COLUMN], y_label="Speed (%)", log_scale=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Resistance Section
    st.header("Resistance MMR1 (Ohm)")
    st.text("Latest reading from selected date range")
    
    resistance_cols_available = [c for c in RESISTANCE_COLUMNS if c in df.columns]
    if resistance_cols_available:
        for col_name in resistance_cols_available:
            current_val = pd.to_numeric(df[col_name], errors="coerce").iloc[-1]
            val_str = f"{current_val:.3f}" if pd.notna(current_val) else "N/A"
            display_metric(f"{col_name} (Ohm)", val_str)
        
        if has_time:
            resistance_log = st.checkbox("Log scale", value=False, key="resistance_log")
            resistance_df = df[[time_col] + resistance_cols_available].copy()
            resistance_df = downsample_for_chart(resistance_df)
            fig = create_interactive_chart(resistance_df, time_col, resistance_cols_available, y_label="Resistance (Ohm)", log_scale=resistance_log)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Mixture Percentage Section (P/T)
    st.header("Mixture Percentage (P/T)")
    st.text("Latest reading from selected date range")
    
    if MIXTURE_COLUMN in df.columns:
        current_val = pd.to_numeric(df[MIXTURE_COLUMN], errors="coerce").iloc[-1]
        val_str = f"{current_val:.3f}" if pd.notna(current_val) else "N/A"
        display_metric("P/T (%)", val_str)
        
        if has_time:
            mixture_df = df[[time_col, MIXTURE_COLUMN]].copy()
            mixture_df = downsample_for_chart(mixture_df)
            fig = create_interactive_chart(mixture_df, time_col, [MIXTURE_COLUMN], y_label="Mixture (%)", log_scale=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # OVC Turbo Status Section (Turbo AUX)
    st.header("OVC Turbo Status (Turbo AUX)")
    st.text("Latest reading from selected date range")
    
    if TURBO_AUX_COLUMN in df.columns:
        current_val = pd.to_numeric(df[TURBO_AUX_COLUMN], errors="coerce").iloc[-1]
        status_text = "ON" if current_val == 1 else "OFF"
        status_icon = "[ON]" if current_val == 1 else "[OFF]"
        display_metric("Turbo AUX", f"{status_icon} {status_text}")
        
        if has_time:
            turbo_aux_df = df[[time_col, TURBO_AUX_COLUMN]].copy()
            turbo_aux_df = downsample_for_chart(turbo_aux_df)
            fig = create_interactive_chart(turbo_aux_df, time_col, [TURBO_AUX_COLUMN], y_label="Status (0=Off, 1=On)", log_scale=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Pulse Tube Status Section (PT)
    st.header("Pulse Tube Status (PT)")
    st.text("Latest reading from selected date range")
    
    if PULSE_TUBE_COLUMN in df.columns:
        current_val = pd.to_numeric(df[PULSE_TUBE_COLUMN], errors="coerce").iloc[-1]
        status_text = "ON" if current_val == 1 else "OFF"
        status_icon = "[ON]" if current_val == 1 else "[OFF]"
        display_metric("Pulse Tube", f"{status_icon} {status_text}")
        
        if has_time:
            pt_df = df[[time_col, PULSE_TUBE_COLUMN]].copy()
            pt_df = downsample_for_chart(pt_df)
            fig = create_interactive_chart(pt_df, time_col, [PULSE_TUBE_COLUMN], y_label="Status (0=Off, 1=On)", log_scale=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'scrollZoom': True})
    
    # Valve Status Section
    st.header("Valve Status")
    
    # Current state grid
    st.subheader("Current State")
    st.text("[O] Open | [X] Closed")
    render_valve_grid(df)
    
    # Valve timeline chart
    st.subheader("Valve Timeline")
    st.text("Shows valve open/close states over time (1 = open, 0 = closed)")
    render_valve_timeline(df)
    
    # Fridge Diagram with Valve Status
    st.subheader("Fridge Diagram")
    st.text("Visual representation of valve states on the fridge schematic")
    render_fridge_diagram(df)
    
    # Raw data section (using checkbox since expander not available in 0.62)
    st.subheader("Raw Data")
    if st.checkbox("Show Raw Data"):
        # Use st.table or st.write instead of st.dataframe for better compatibility
        # Convert any datetime columns to strings to avoid timezone issues
        df_display = df.copy()
        # Remove time_str column as it's not correct
        if 'time_str' in df_display.columns:
            df_display = df_display.drop(columns=['time_str'])
        if 'time' in df_display.columns:
            df_display = df_display.drop(columns=['time'])
        if 'file_date' in df_display.columns:
            df_display = df_display.drop(columns=['file_date'])
        for col in df_display.columns:
            if df_display[col].dtype == 'datetime64[ns]' or 'datetime' in str(df_display[col].dtype):
                df_display[col] = df_display[col].astype(str)
        st.write(df_display)


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Dspx-Monitor Dashboard starting")
    logger.info("=" * 50)
    main()
