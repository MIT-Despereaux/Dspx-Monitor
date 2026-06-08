"""
Dspx-Monitor Core Module
Shared functionality for both the Streamlit dashboard and the background scheduler.
"""

from __future__ import annotations

import os
import logging
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
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

# Fridge state monitoring thresholds
WARM_TEMPERATURE_THRESHOLD_K = 4.5
OPERATING_MC_THRESHOLD_K = 0.1
CONDENSATION_K5_THRESHOLD_MBAR = 2000.0
OPERATING_PRESSURE_THRESHOLD_MBAR = 900.0
DILUTION_TURBO_P1_THRESHOLD_MBAR = 1.0
OPERATING_MC_ALARM_THRESHOLD_K = 0.5
OPERATING_STILL_ALARM_THRESHOLD_K = 1.3
TRANSITION_TIMEOUT = timedelta(hours=5)
OPERATING_PT_OFF_GRACE_PERIOD = timedelta(minutes=1)


class FridgeState(str, Enum):
    """Named stages in a normal dilution refrigerator cycle."""

    WARM = "WARM"
    PT_COOLING_TO_4K = "PT_COOLING_TO_4K"
    TRANSITION_TO_CONDENSATION = "TRANSITION_TO_CONDENSATION"
    CONDENSING = "CONDENSING"
    DILUTION_COOLING_TO_100_MK = "DILUTION_COOLING_TO_100_MK"
    OPERATING = "OPERATING"


COLD_PT_REQUIRED_STATES = {
    FridgeState.TRANSITION_TO_CONDENSATION,
    FridgeState.CONDENSING,
    FridgeState.DILUTION_COOLING_TO_100_MK,
    FridgeState.OPERATING,
}


@dataclass(frozen=True)
class FridgeReading:
    """Normalized values needed to evaluate the fridge state."""

    mc_k: Optional[float] = -1.0
    still_k: Optional[float] = -1.0
    four_k_k: Optional[float] = -1.0
    pt_on: Optional[bool] = False
    k4_mbar: Optional[float] = -1.0
    k5_mbar: Optional[float] = -1.0
    p1_mbar: Optional[float] = -1.0
    dilution_turbo_speed_pct: Optional[float] = 0.0

    @property
    def temperatures(self) -> tuple[Optional[float], Optional[float], Optional[float]]:
        return self.mc_k, self.still_k, self.four_k_k

    @property
    def has_temperatures(self) -> bool:
        return all(value is not None for value in self.temperatures)

    @property
    def all_warm(self) -> bool:
        return self.has_temperatures and all(
            value > WARM_TEMPERATURE_THRESHOLD_K for value in self.temperatures
        )

    @property
    def all_at_4k(self) -> bool:
        return self.has_temperatures and all(
            value <= WARM_TEMPERATURE_THRESHOLD_K for value in self.temperatures
        )


@dataclass(frozen=True)
class StateTransition:
    """Result of evaluating one reading against the tracked state."""

    previous_state: FridgeState
    state: FridgeState
    invalid_transition: Optional[str] = None
    missing_fields: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.state != self.previous_state


@dataclass(frozen=True)
class FridgeFault:
    """An active alarm condition produced by the state evaluator."""

    code: str
    message: str
    severity: str = "normal"

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
# Fridge State Functions
# ============================================================================

def _numeric_value(value: Any) -> Optional[float]:
    """Convert a data value to a finite float, or return None."""
    converted = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(converted) if pd.notna(converted) else None


def _boolean_value(value: Any) -> Optional[bool]:
    """Convert a 0/1 data value to a boolean, or return None."""
    converted = _numeric_value(value)
    if converted == 0:
        return False
    if converted == 1:
        return True
    return None


def extract_fridge_reading(row: pd.Series | Dict[str, Any]) -> FridgeReading:
    """Extract normalized state-machine inputs from a data row."""
    return FridgeReading(
        mc_k=_numeric_value(row.get("full range")),
        still_k=_numeric_value(row.get("still")),
        four_k_k=_numeric_value(row.get("Platine 4K")),
        pt_on=_boolean_value(row.get(PULSE_TUBE_COLUMN)),
        k4_mbar=_numeric_value(row.get("K4")),
        k5_mbar=_numeric_value(row.get("K5")),
        p1_mbar=_numeric_value(row.get("P1")),
        dilution_turbo_speed_pct=_numeric_value(row.get(TURBO_COLUMN)),
    )


def get_missing_state_fields(reading: FridgeReading) -> tuple[str, ...]:
    """Return fields required for state transitions that are missing or invalid."""
    fields = {
        "full range": reading.mc_k,
        "still": reading.still_k,
        "Platine 4K": reading.four_k_k,
        "PT": reading.pt_on,
        "K5": reading.k5_mbar,
    }
    return tuple(name for name, value in fields.items() if value is None)


def infer_fridge_state(reading: FridgeReading) -> Optional[FridgeState]:
    """Infer the most specific compatible state when no saved state exists."""
    if get_missing_state_fields(reading):
        return None
    if reading.all_warm:
        return FridgeState.PT_COOLING_TO_4K if reading.pt_on else FridgeState.WARM
    if reading.all_at_4k:
        if reading.mc_k < OPERATING_MC_THRESHOLD_K:
            return FridgeState.OPERATING
        if reading.k5_mbar > CONDENSATION_K5_THRESHOLD_MBAR:
            return FridgeState.CONDENSING
        return FridgeState.DILUTION_COOLING_TO_100_MK
    if reading.pt_on:
        return FridgeState.PT_COOLING_TO_4K
    return None


def evaluate_fridge_transition(
    previous_state: FridgeState,
    reading: FridgeReading,
) -> StateTransition:
    """Evaluate one reading while enforcing the ordered fridge lifecycle."""
    missing_fields = get_missing_state_fields(reading)
    if missing_fields:
        return StateTransition(previous_state, previous_state, missing_fields=missing_fields)

    if reading.all_warm and not reading.pt_on:
        return StateTransition(previous_state, FridgeState.WARM)

    invalid_transition = None
    state = previous_state

    if previous_state == FridgeState.WARM:
        if reading.all_warm and reading.pt_on:
            state = FridgeState.PT_COOLING_TO_4K
        elif not reading.all_warm:
            invalid_transition = "Fridge left WARM without entering PT cooling from warm conditions"

    elif previous_state == FridgeState.PT_COOLING_TO_4K:
        if reading.all_at_4k:
            if reading.k5_mbar > CONDENSATION_K5_THRESHOLD_MBAR:
                invalid_transition = "Condensation started before transition time began"
            else:
                state = FridgeState.TRANSITION_TO_CONDENSATION
        elif not reading.pt_on:
            invalid_transition = "Pulse tube turned off before the 4 K cooldown completed"

    elif previous_state == FridgeState.TRANSITION_TO_CONDENSATION:
        if reading.k5_mbar > CONDENSATION_K5_THRESHOLD_MBAR:
            state = FridgeState.CONDENSING
        elif reading.mc_k < OPERATING_MC_THRESHOLD_K:
            invalid_transition = "MC reached operating temperature before condensation"

    elif previous_state == FridgeState.CONDENSING:
        if reading.k5_mbar <= CONDENSATION_K5_THRESHOLD_MBAR:
            state = FridgeState.DILUTION_COOLING_TO_100_MK

    elif previous_state == FridgeState.DILUTION_COOLING_TO_100_MK:
        if reading.k5_mbar > CONDENSATION_K5_THRESHOLD_MBAR:
            invalid_transition = "Condensation restarted after dilution cooling began"
        elif reading.mc_k < OPERATING_MC_THRESHOLD_K:
            state = FridgeState.OPERATING

    return StateTransition(previous_state, state, invalid_transition=invalid_transition)


def evaluate_fridge_faults(
    state: FridgeState,
    reading: FridgeReading,
    state_entered_at: datetime,
    now: datetime,
    pt_off_since: Optional[datetime] = None,
    invalid_transition: Optional[str] = None,
) -> Dict[str, FridgeFault]:
    """Return the active alarm conditions for a tracked fridge state."""
    faults = {}

    if (
        reading.dilution_turbo_speed_pct is not None
        and reading.dilution_turbo_speed_pct > 0
        and reading.p1_mbar is not None
        and reading.p1_mbar > DILUTION_TURBO_P1_THRESHOLD_MBAR
    ):
        faults["dilution_turbo_p1_high"] = FridgeFault(
            "dilution_turbo_p1_high",
            (
                f"P1 is above {DILUTION_TURBO_P1_THRESHOLD_MBAR:.1f} mbar while the dilution turbo is on: "
                f"P1={reading.p1_mbar:.2f} mbar, "
                f"turbo={reading.dilution_turbo_speed_pct:.2f}%"
            ),
            severity="high",
        )

    if invalid_transition:
        faults["invalid_transition"] = FridgeFault(
            "invalid_transition",
            f"Invalid fridge state transition: {invalid_transition}",
        )

    if (
        state == FridgeState.TRANSITION_TO_CONDENSATION
        and now - state_entered_at > TRANSITION_TIMEOUT
    ):
        faults["transition_timeout"] = FridgeFault(
            "transition_timeout",
            f"Transition to condensation has exceeded {TRANSITION_TIMEOUT.total_seconds() / 3600:.1f} hours",
        )

    if state == FridgeState.OPERATING:
        if (
            reading.mc_k is not None
            and reading.mc_k > OPERATING_MC_ALARM_THRESHOLD_K
        ):
            faults["operating_mc_temperature_high"] = FridgeFault(
                "operating_mc_temperature_high",
                f"MC temperature is above {OPERATING_MC_ALARM_THRESHOLD_K * 1000:.1f} mK while operating: {reading.mc_k * 1000:.1f} mK",
            )
        if (
            reading.still_k is not None
            and reading.still_k > OPERATING_STILL_ALARM_THRESHOLD_K
        ):
            faults["operating_still_temperature_high"] = FridgeFault(
                "operating_still_temperature_high",
                f"Still temperature is above {OPERATING_STILL_ALARM_THRESHOLD_K:.3f} K while operating: {reading.still_k:.3f} K",
            )

        high_pressures = [
            f"{name}={value:.2f} mbar"
            for name, value in (("K4", reading.k4_mbar), ("K5", reading.k5_mbar))
            if value is not None and value > OPERATING_PRESSURE_THRESHOLD_MBAR
        ]
        if high_pressures:
            faults["operating_pressure"] = FridgeFault(
                "operating_pressure",
                f"Injection pressure K4/K5 is above {OPERATING_PRESSURE_THRESHOLD_MBAR:.1f} mbar: " + ", ".join(high_pressures),
            )

    if (
        state in COLD_PT_REQUIRED_STATES
        and reading.pt_on is False
        and pt_off_since is not None
    ):
        pt_off_duration = now - pt_off_since
        should_alarm = (
            pt_off_duration > OPERATING_PT_OFF_GRACE_PERIOD
            if state == FridgeState.OPERATING
            else pt_off_duration >= timedelta(0)
        )
        if should_alarm:
            faults["pt_off"] = FridgeFault(
                "pt_off",
                f"Pulse tube is off while fridge state is {state.value}",
            )

    return faults


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
        else:
            # Create a default time_str if heures column is missing
            # This ensures charts will still render even with malformed data
            if logger:
                logger.warning(f"'heures' column not found in {os.path.basename(filepath)}")
            df['time_str'] = '00:00:00'
        
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

def calculate_stats(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """Calculate statistics for temperature and pressure columns for the entire dataset."""
    stats = {}
    
    # Temperature columns with rate calculation
    for col in TEMP_COLUMNS:
        if col in df.columns:
            values = pd.to_numeric(df[col], errors="coerce")
            
            stats[col] = {
                "min": values.min(),
                "max": values.max(),
                "mean": values.mean(),
                "current": values.iloc[-1] if len(values) > 0 else None,
                "type": "temperature"
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
    
    # Pressure columns (P1, P2, P3)
    pressure_cols = ["P1", "P2", "P3"]
    for col in pressure_cols:
        if col in df.columns:
            values = pd.to_numeric(df[col], errors="coerce")
            stats[col] = {
                "min": values.min(),
                "max": values.max(),
                "mean": values.mean(),
                "current": values.iloc[-1] if len(values) > 0 else None,
                "type": "pressure"
            }
    
    # K5 pressure (injection pressure)
    if "K5" in df.columns:
        values = pd.to_numeric(df["K5"], errors="coerce")
        stats["K5"] = {
            "min": values.min(),
            "max": values.max(),
            "mean": values.mean(),
            "current": values.iloc[-1] if len(values) > 0 else None,
            "type": "pressure"
        }
    
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
    
    # Add temperature readings
    for col, data in stats.items():
        if data.get('type') == 'temperature':
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
    
    # Add pressure readings
    pressure_labels = {
        "P1": "P1 - DU Evaporation Pressure (mbar)",
        "P2": "P2 - Pressure (mbar)",
        "P3": "P3 - OVC Pressure (mbar)",
        "K5": "K5 - Injection Pressure (mbar)"
    }
    
    for col, data in stats.items():
        if data.get('type') == 'pressure':
            label = pressure_labels.get(col, f"{col} (mbar)")
            current_val = f"{data['current']:.2e}" if data.get('current') is not None else "N/A"
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{label}*\n"
                        f"• Min: `{data['min']:.2e}`\n"
                        f"• Max: `{data['max']:.2e}`\n"
                        f"• Current: `{current_val}`"
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
    
    # Temperature values
    for col, data in stats.items():
        if data.get('type') == 'temperature':
            current_val = f"{data['current']:.6f}" if data.get('current') is not None else "N/A"
            lines.append(f"{col}: Min={data['min']:.6f}, Max={data['max']:.6f}, Current={current_val}")
    
    # Pressure values
    for col, data in stats.items():
        if data.get('type') == 'pressure':
            current_val = f"{data['current']:.2e}" if data.get('current') is not None else "N/A"
            lines.append(f"{col}: Min={data['min']:.2e}, Max={data['max']:.2e}, Current={current_val}")
    
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
        
        return True, "Message sent successfully"
    
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
        with open(SIGNAL_FILE, 'w', encoding='utf-8') as f:
            f.write(str(datetime.now().timestamp()))
    except Exception:
        pass


def read_refresh_signal() -> Optional[float]:
    """Read the refresh signal timestamp. Returns None if no signal."""
    try:
        if os.path.exists(SIGNAL_FILE):
            with open(SIGNAL_FILE, 'r', encoding='utf-8') as f:
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
