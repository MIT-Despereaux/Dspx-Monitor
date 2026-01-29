"""
Dspx-Monitor Core Module
Shared functionality for both the Streamlit dashboard and the background scheduler.
"""

from __future__ import annotations

import os
import logging
import warnings
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

import pandas as pd

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
LOG_DIR = os.path.join(BASE_DIR, "logs")
SIGNAL_FILE = os.path.join(BASE_DIR, ".refresh_signal")

# Column definitions with units
TEMP_COLUMNS = ["full range", "still", "Platine 4K"]  # Units: K (Kelvin)
TEMP_COLUMNS_ALIAS = {
    "full range": "MC (K)",
    "still": "Still (K)",
    "Platine 4K": "4K (K)"
}
PRESSURE_COLUMNS = ["P1", "P2", "P3"]  # Units: mbar
PRESSURE_K_COLUMNS = ["K3", "K4", "K5", "K6", "K8"]  # Additional pressure sensors
TURBO_COLUMN = "Pumping turbo speed"  # Units: %
RESISTANCE_COLUMNS = ["R MMR1 1", "R MMR1 2", "R MMR1 3"]  # Units: Ohm
MIXTURE_COLUMN = "P/T"  # Mixture percentage
TURBO_AUX_COLUMN = "Turbo AUX"  # OVC turbo status (On/Off)
PULSE_TUBE_COLUMN = "PT"  # Pulse tube status (On/Off)

# Valve positions for the fridge diagram
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


def get_logger(name: str) -> logging.Logger:
    """Get or create a logger with the specified name."""
    return logging.getLogger(name)


def load_secrets() -> Dict[str, str]:
    """
    Load secrets from environment variables and slack.secret file.
    Environment variables take precedence.
    """
    secrets = {}
    secret_keys = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_SIGNING_SECRET"]
    
    # Load from environment variables first
    for key in secret_keys:
        env_value = os.environ.get(key)
        if env_value:
            secrets[key] = env_value
    
    # Load from slack.secret file for any keys not already set
    secrets_file = os.path.join(BASE_DIR, "slack.secret")
    if os.path.exists(secrets_file):
        with open(secrets_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith('#'):
                    continue
                key_value = line.strip().split('=', 1)
                if len(key_value) == 2:
                    key = key_value[0].strip()
                    value = key_value[1].strip()
                    if key not in secrets:
                        secrets[key] = value
    
    return secrets


# ============================================================================
# Data File Functions
# ============================================================================

def get_date_range_from_files() -> tuple[Optional[Any], Optional[Any]]:
    """Get min and max dates from available data files."""
    if not os.path.exists(DATA_DIR):
        return None, None
    
    dates = []
    for f in os.listdir(DATA_DIR):
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


def get_files_for_date_range(start_date, end_date) -> List[str]:
    """Get list of files for the specified date range."""
    if not os.path.exists(DATA_DIR):
        return []
    
    files = []
    current = start_date
    while current <= end_date:
        filename = current.strftime("%m%d%y") + ".txt"
        filepath = os.path.join(DATA_DIR, filename)
        if os.path.exists(filepath):
            files.append(filepath)
        current += timedelta(days=1)
    
    return files


def get_files_for_last_24_hours() -> List[str]:
    """Get files needed to display the last 24 hours of data (today and yesterday)."""
    if not os.path.exists(DATA_DIR):
        return []
    
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    
    files = []
    for d in [yesterday, today]:
        filename = d.strftime("%m%d%y") + ".txt"
        filepath = os.path.join(DATA_DIR, filename)
        if os.path.exists(filepath):
            files.append(filepath)
    
    return files


def get_file_modification_times(files: List[str]) -> Dict[str, float]:
    """Get modification times for a list of files."""
    mtimes = {}
    for f in files:
        try:
            mtimes[f] = os.path.getmtime(f)
        except OSError:
            mtimes[f] = 0
    return mtimes


# ============================================================================
# Data Loading Functions
# ============================================================================

def load_data_file(filepath: str, logger: Optional[logging.Logger] = None) -> Optional[pd.DataFrame]:
    """Load and parse a single TSV data file."""
    if logger:
        logger.info(f"Loading data file: {filepath}")
    
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = pd.read_csv(
                filepath,
                sep="\t",
                encoding="latin-1",
                index_col=False,
                on_bad_lines='skip',
                low_memory=False
            )
        
        # Clean column names
        df.columns = df.columns.str.strip().str.replace('\r', '')
        
        # Clean string data
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].astype(str).str.strip().str.replace('\r', '')
        
        # Parse time column
        if 'heures' in df.columns:
            df['time'] = pd.to_datetime(df['heures'], format='%H:%M:%S', errors='coerce')
            df['time_str'] = df['heures']
        
        if logger:
            logger.info(f"Loaded {len(df)} rows, {len(df.columns)} columns from {os.path.basename(filepath)}")
        
        return df
    
    except Exception as e:
        if logger:
            logger.exception(f"Error loading data file {filepath}: {e}")
        return None


def load_multiple_files(filepaths: List[str], logger: Optional[logging.Logger] = None) -> Optional[pd.DataFrame]:
    """Load and concatenate multiple data files."""
    if not filepaths:
        return None
    
    all_dfs = []
    
    for filepath in filepaths:
        df = load_data_file(filepath, logger)
        if df is not None:
            # Add date column from filename
            base = os.path.basename(filepath).replace(".txt", "")
            try:
                file_date = datetime.strptime(base, "%m%d%y").strftime("%Y-%m-%d")
                df = df.copy()
                df['file_date'] = file_date
                if 'time_str' in df.columns:
                    df['datetime_str'] = file_date + ' ' + df['time_str']
            except ValueError:
                df = df.copy()
                df['file_date'] = base
                if 'time_str' in df.columns:
                    df['datetime_str'] = df['time_str']
            all_dfs.append(df)
    
    if not all_dfs:
        return None
    
    return pd.concat(all_dfs, ignore_index=True)


def filter_to_last_24_hours(df: pd.DataFrame, logger: Optional[logging.Logger] = None) -> pd.DataFrame:
    """Filter dataframe to only include data from the last 24 hours."""
    if df is None or len(df) == 0:
        return df
    
    if 'datetime_str' not in df.columns:
        if logger:
            logger.warning("No datetime_str column, cannot filter to last 24 hours")
        return df
    
    try:
        df = df.copy()
        df['_parsed_datetime'] = pd.to_datetime(df['datetime_str'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
        
        now = datetime.now()
        cutoff = now - timedelta(hours=24)
        
        mask = df['_parsed_datetime'] >= cutoff
        filtered_df = df[mask].copy()
        filtered_df = filtered_df.drop(columns=['_parsed_datetime'])
        
        if logger:
            logger.info(f"Filtered data from {len(df)} to {len(filtered_df)} rows (last 24 hours)")
        
        return filtered_df
    
    except Exception as e:
        if logger:
            logger.exception(f"Error filtering to last 24 hours: {e}")
        return df


# ============================================================================
# Statistics Functions
# ============================================================================

def calculate_daily_stats(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """Calculate daily statistics for temperature columns."""
    stats = {}
    
    for col in TEMP_COLUMNS:
        if col in df.columns:
            values = pd.to_numeric(df[col], errors="coerce")
            
            stats[col] = {
                "min": values.min(),
                "max": values.max(),
                "mean": values.mean(),
                "current": values.iloc[-1] if len(values) > 0 else None,
            }
            
            # Calculate rate of change per 15 minutes
            samples_per_15min = 30  # Data sampled every 30 seconds
            if len(values) >= samples_per_15min:
                rates = []
                for i in range(0, len(values) - samples_per_15min, samples_per_15min):
                    rate = (values.iloc[i + samples_per_15min] - values.iloc[i]) / 15.0
                    if pd.notna(rate):
                        rates.append(rate)
                stats[col]["avg_rate_per_min"] = sum(rates) / len(rates) if rates else 0
            else:
                stats[col]["avg_rate_per_min"] = 0
    
    return stats


# ============================================================================
# Slack Report Functions
# ============================================================================

def build_report_blocks(stats: Dict[str, Dict], filename: str) -> List[Dict]:
    """Build Slack Block Kit blocks for the daily report."""
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
    
    for col, data in stats.items():
        alias = TEMP_COLUMNS_ALIAS.get(col, col)
        current_val = f"{data['current']:.4f}" if data.get('current') is not None else "N/A"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{alias}*\n"
                    f"• Min: `{data['min']:.4f}`\n"
                    f"• Max: `{data['max']:.4f}`\n"
                    f"• Current: `{current_val}`\n"
                    f"• Avg rate: `{data.get('avg_rate_per_min', 0):.8f}` /min"
                )
            }
        })
    
    return blocks


def build_report_text(stats: Dict[str, Dict], filename: str) -> str:
    """Build plain text version of the daily report."""
    lines = [
        "🌡️ Dspx-Monitor Daily Report",
        f"Data: {os.path.basename(filename) if '/' in filename else filename}",
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ""
    ]
    
    for col, data in stats.items():
        current_val = f"{data['current']:.6f}" if data.get('current') is not None else "N/A"
        lines.append(f"{col}: Min={data['min']:.6f}, Max={data['max']:.6f}, Current={current_val}")
    
    return "\n".join(lines)


def send_slack_message(
    bot_token: str,
    target: str,
    text: str,
    blocks: Optional[List[Dict]] = None,
    is_dm: bool = False,
    logger: Optional[logging.Logger] = None
) -> tuple[bool, str]:
    """
    Send a message to Slack (channel or DM).
    
    Args:
        bot_token: Slack bot token
        target: Channel name/ID or user ID
        text: Plain text message
        blocks: Optional Block Kit blocks
        is_dm: If True, send as DM to user
        logger: Optional logger
    
    Returns:
        Tuple of (success, message)
    """
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    
    if not bot_token:
        return False, "No Slack bot token configured"
    
    if not target:
        return False, "No target specified"
    
    try:
        client = WebClient(token=bot_token)
        
        if is_dm:
            # Open DM conversation first
            response = client.conversations_open(users=[target])
            channel_id = response["channel"]["id"]
        else:
            channel_id = target.lstrip("#")
        
        kwargs = {"channel": channel_id, "text": text}
        if blocks:
            kwargs["blocks"] = blocks
        
        client.chat_postMessage(**kwargs)
        
        if logger:
            logger.info(f"Message sent to {'user ' + target if is_dm else 'channel ' + target}")
        
        return True, f"Message sent successfully"
    
    except SlackApiError as e:
        error_msg = f"Slack API error: {e.response['error']}"
        if logger:
            logger.error(error_msg)
        return False, error_msg
    
    except Exception as e:
        error_msg = f"Error sending message: {str(e)}"
        if logger:
            logger.exception(error_msg)
        return False, error_msg


def send_daily_report(
    bot_token: str,
    target: str,
    stats: Dict[str, Dict],
    filename: str,
    is_dm: bool = False,
    logger: Optional[logging.Logger] = None
) -> tuple[bool, str]:
    """Send daily report to Slack."""
    blocks = build_report_blocks(stats, filename)
    text = build_report_text(stats, filename)
    return send_slack_message(bot_token, target, text, blocks, is_dm, logger)


# ============================================================================
# Signal File Functions (for scheduler -> dashboard communication)
# ============================================================================

def write_refresh_signal():
    """Write a signal file to indicate data has been updated."""
    try:
        with open(SIGNAL_FILE, 'w') as f:
            f.write(str(datetime.now().timestamp()))
    except Exception:
        pass


def read_refresh_signal() -> Optional[float]:
    """Read the refresh signal timestamp. Returns None if no signal."""
    try:
        if os.path.exists(SIGNAL_FILE):
            with open(SIGNAL_FILE, 'r') as f:
                return float(f.read().strip())
    except Exception:
        pass
    return None


def clear_refresh_signal():
    """Clear the refresh signal file."""
    try:
        if os.path.exists(SIGNAL_FILE):
            os.remove(SIGNAL_FILE)
    except Exception:
        pass
