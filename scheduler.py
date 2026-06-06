#!/usr/bin/env python3
"""
Dspx-Monitor Background Scheduler
Runs independently of the Streamlit dashboard to:
1. Check data files every minute and signal dashboard to refresh
2. Send daily reports to Slack at 3 PM
"""

from __future__ import annotations

import os
import time
import json
import logging
import schedule
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional

# Import shared core module
from core import (
    LOG_DIR,
    load_secrets,
    get_files_for_last_24_hours,
    get_file_modification_times,
    load_multiple_files,
    filter_to_last_24_hours,
    calculate_stats,
    send_daily_report,
    write_refresh_signal,
    send_slack_message,
    COLD_PT_REQUIRED_STATES,
    FridgeFault,
    FridgeState,
    StateTransition,
    evaluate_fridge_faults,
    evaluate_fridge_transition,
    extract_fridge_reading,
    infer_fridge_state,
)

# Setup logging
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILEPATH = os.path.join(LOG_DIR, "scheduler.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILEPATH, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("dspx_scheduler")

# Configuration
REPORT_TIME = "15:00"  # 3 PM
CHECK_INTERVAL_MINUTES = 1
ALARM_INTERVAL = timedelta(minutes=5)
MAX_ALARM_MESSAGES = 3
FRIDGE_STATE_FILE = os.path.join(LOG_DIR, "fridge_state.json")

# Load secrets
SECRETS = load_secrets()

# Slack channel/user to send reports to
SLACK_REPORT_CHANNEL = os.environ.get("SLACK_REPORT_CHANNEL", "")
SLACK_REPORT_USER = os.environ.get("SLACK_REPORT_USER", "")

# Track file modification times
file_mtimes = {}


@dataclass
class AlarmRecord:
    """Rate-limiting state for one continuous fault."""

    message: str
    successful_sends: int = 0
    last_sent_at: Optional[datetime] = None


@dataclass
class FridgeRuntimeState:
    """Scheduler-owned state that survives process restarts."""

    state: FridgeState
    state_entered_at: datetime
    pt_off_since: Optional[datetime] = None
    alarms: Dict[str, AlarmRecord] = field(default_factory=dict)


fridge_runtime_state: Optional[FridgeRuntimeState] = None


def _datetime_to_text(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _datetime_from_text(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def save_fridge_runtime_state(
    runtime: FridgeRuntimeState,
    filepath: Optional[str] = None,
) -> None:
    """Persist scheduler state atomically."""
    filepath = filepath or FRIDGE_STATE_FILE
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    payload = {
        "state": runtime.state.value,
        "state_entered_at": _datetime_to_text(runtime.state_entered_at),
        "pt_off_since": _datetime_to_text(runtime.pt_off_since),
        "alarms": {
            code: {
                "message": record.message,
                "successful_sends": record.successful_sends,
                "last_sent_at": _datetime_to_text(record.last_sent_at),
            }
            for code, record in runtime.alarms.items()
        },
    }
    temporary_path = filepath + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as state_file:
        json.dump(payload, state_file, indent=2)
    os.replace(temporary_path, filepath)


def load_fridge_runtime_state(
    filepath: Optional[str] = None,
) -> Optional[FridgeRuntimeState]:
    """Restore persisted scheduler state, returning None when it is unusable."""
    filepath = filepath or FRIDGE_STATE_FILE
    try:
        with open(filepath, "r", encoding="utf-8") as state_file:
            payload = json.load(state_file)
        state_entered_at = _datetime_from_text(payload["state_entered_at"])
        if state_entered_at is None:
            raise ValueError("state_entered_at is required")
        return FridgeRuntimeState(
            state=FridgeState(payload["state"]),
            state_entered_at=state_entered_at,
            pt_off_since=_datetime_from_text(payload.get("pt_off_since")),
            alarms={
                code: AlarmRecord(
                    message=record["message"],
                    successful_sends=int(record.get("successful_sends", 0)),
                    last_sent_at=_datetime_from_text(record.get("last_sent_at")),
                )
                for code, record in payload.get("alarms", {}).items()
            },
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        logger.warning(f"Could not restore fridge state from {filepath}: {error}")
        return None


def update_fridge_runtime(
    runtime: FridgeRuntimeState,
    reading,
    now: datetime,
) -> tuple[FridgeRuntimeState, Dict[str, FridgeFault], StateTransition]:
    """Advance runtime state and calculate active faults without sending messages."""
    transition = evaluate_fridge_transition(runtime.state, reading)
    if transition.changed:
        runtime.state = transition.state
        runtime.state_entered_at = now

    if runtime.state in COLD_PT_REQUIRED_STATES and reading.pt_on is False:
        runtime.pt_off_since = runtime.pt_off_since or now
    else:
        runtime.pt_off_since = None

    faults = evaluate_fridge_faults(
        runtime.state,
        reading,
        runtime.state_entered_at,
        now,
        runtime.pt_off_since,
        transition.invalid_transition,
    )

    for code in list(runtime.alarms):
        if code not in faults:
            del runtime.alarms[code]
    for code, fault in faults.items():
        record = runtime.alarms.get(code)
        if record is None or (
            code == "invalid_transition" and record.message != fault.message
        ):
            runtime.alarms[code] = AlarmRecord(message=fault.message)
        else:
            record.message = fault.message

    return runtime, faults, transition


def alarm_is_due(record: AlarmRecord, now: datetime) -> bool:
    """Return whether another Slack message may be attempted for a fault."""
    if record.successful_sends >= MAX_ALARM_MESSAGES:
        return False
    return record.last_sent_at is None or now - record.last_sent_at >= ALARM_INTERVAL


def _slack_destination() -> tuple[str, str, bool]:
    return (
        SECRETS.get("SLACK_BOT_TOKEN", ""),
        SLACK_REPORT_CHANNEL or SLACK_REPORT_USER,
        bool(SLACK_REPORT_USER and not SLACK_REPORT_CHANNEL),
    )


def _send_state_message(title: str, message: str, now: datetime) -> bool:
    bot_token, target, is_dm = _slack_destination()
    if not bot_token or not target:
        return False
    text = f"{title}\n\n{message}\nTime: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    blocks = [{
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*{title}*\n{message}\n*Time:* {now.strftime('%Y-%m-%d %H:%M:%S')}"},
    }]
    success, error = send_slack_message(
        bot_token=bot_token,
        target=target,
        text=text,
        blocks=blocks,
        is_dm=is_dm,
        logger=logger,
    )
    if not success:
        logger.error(f"Failed to send fridge state message: {error}")
    return success


def _format_duration(duration: timedelta) -> str:
    total_seconds = int(duration.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"


def check_fridge_state(now: Optional[datetime] = None):
    """Load the latest reading, advance state, and send eligible alerts."""
    global fridge_runtime_state

    now = now or datetime.now()
    files = get_files_for_last_24_hours()
    if not files:
        return None
    df = load_multiple_files(files, logger)
    if df is None or len(df) == 0:
        return None

    reading = extract_fridge_reading(df.iloc[-1])
    if fridge_runtime_state is None:
        fridge_runtime_state = load_fridge_runtime_state()
    if fridge_runtime_state is None:
        inferred_state = infer_fridge_state(reading)
        if inferred_state is None:
            logger.warning("Could not infer initial fridge state from the latest reading")
            return None
        fridge_runtime_state = FridgeRuntimeState(inferred_state, now)
        logger.info(f"Initialized fridge state as {inferred_state.value}")

    previous_state_entered_at = fridge_runtime_state.state_entered_at
    runtime, faults, transition = update_fridge_runtime(fridge_runtime_state, reading, now)

    if transition.missing_fields:
        logger.warning(f"Missing or invalid fridge state fields: {', '.join(transition.missing_fields)}")
    if transition.changed:
        logger.info(f"Fridge state changed: {transition.previous_state.value} -> {transition.state.value}")
        if transition.state == FridgeState.CONDENSING:
            _send_state_message(
                "Condensation Monitoring",
                f"Condensation starting\nK5 value: {reading.k5_mbar:.2f} mbar",
                now,
            )
        elif (
            transition.previous_state == FridgeState.CONDENSING
            and transition.state == FridgeState.DILUTION_COOLING_TO_100_MK
        ):
            _send_state_message(
                "Condensation Monitoring",
                (
                    "Condensation finished\n"
                    f"Total time: {_format_duration(now - previous_state_entered_at)}\n"
                    f"K5 value: {reading.k5_mbar:.2f} mbar"
                ),
                now,
            )

    for code, fault in faults.items():
        record = runtime.alarms[code]
        if alarm_is_due(record, now):
            logger.warning(f"Fridge alarm: {fault.message}")
            title = "HIGH SEVERITY Fridge Alarm" if fault.severity == "high" else "Fridge Alarm"
            if _send_state_message(title, fault.message, now):
                record.successful_sends += 1
                record.last_sent_at = now

    try:
        save_fridge_runtime_state(runtime)
    except OSError as error:
        logger.error(f"Could not persist fridge state: {error}")
    fridge_runtime_state = runtime
    return runtime


def check_file_updates():
    """Check if data files have been updated and signal dashboard."""
    global file_mtimes
    
    files = get_files_for_last_24_hours()
    current_mtimes = get_file_modification_times(files)
    
    # Check for changes
    files_changed = False
    for filepath, mtime in current_mtimes.items():
        filename = os.path.basename(filepath)
        if filepath in file_mtimes:
            if mtime > file_mtimes[filepath]:
                logger.info(f"File updated: {filename}")
                files_changed = True
        else:
            # New file
            logger.info(f"New file detected: {filename}")
            files_changed = True
    
    # Update stored modification times
    file_mtimes = current_mtimes
    
    # If files changed, write signal for dashboard to pick up
    if files_changed:
        logger.info("Writing refresh signal for dashboard")
        write_refresh_signal()
    
    return files_changed


def send_scheduled_report():
    """Send the daily report to Slack."""
    logger.info("=" * 50)
    logger.info("Running scheduled daily report (3 PM)")
    logger.info("=" * 50)
    
    bot_token = SECRETS.get("SLACK_BOT_TOKEN", "")
    
    if not bot_token:
        logger.error("No SLACK_BOT_TOKEN configured, cannot send report")
        return False
    
    # Determine target
    target = SLACK_REPORT_CHANNEL or SLACK_REPORT_USER
    is_dm = bool(SLACK_REPORT_USER and not SLACK_REPORT_CHANNEL)
    
    if not target:
        logger.error("No SLACK_REPORT_CHANNEL or SLACK_REPORT_USER configured")
        return False
    
    # Load and process data
    files = get_files_for_last_24_hours()
    if not files:
        logger.error("No data files found for report")
        return False
    
    df = load_multiple_files(files, logger)
    if df is None:
        logger.error("Failed to load data for report")
        return False
    
    df = filter_to_last_24_hours(df, logger)
    stats = calculate_stats(df)
    
    if not stats:
        logger.error("No statistics calculated")
        return False
    
    # Send report
    success, message = send_daily_report(
        bot_token=bot_token,
        target=target,
        stats=stats,
        filename="Last 24 hours",
        is_dm=is_dm,
        logger=logger
    )
    
    if success:
        logger.info(f"Daily report sent to {'user ' + target if is_dm else 'channel ' + target}")
    else:
        logger.error(f"Failed to send report: {message}")
    
    return success


def job_check_files():
    """Scheduled job: Check for file updates and fridge state every minute."""
    logger.debug("Running file check...")
    check_file_updates()
    check_fridge_state()


def job_send_daily_report():
    """Scheduled job: Send daily report at 3 PM."""
    send_scheduled_report()


def main():
    """Main scheduler loop."""
    logger.info("=" * 50)
    logger.info("Dspx-Monitor Scheduler Started")
    logger.info(f"Report time: {REPORT_TIME}")
    logger.info(f"File check interval: {CHECK_INTERVAL_MINUTES} minute(s)")
    logger.info(f"Fridge state file: {FRIDGE_STATE_FILE}")
    logger.info("=" * 50)
    
    # Check configuration
    if not SECRETS.get("SLACK_BOT_TOKEN"):
        logger.warning("SLACK_BOT_TOKEN not configured - reports will not be sent")
    
    if not (SLACK_REPORT_CHANNEL or SLACK_REPORT_USER):
        logger.warning("Neither SLACK_REPORT_CHANNEL nor SLACK_REPORT_USER configured")
        logger.warning("Set one of these environment variables to receive reports")
    else:
        target = SLACK_REPORT_CHANNEL or SLACK_REPORT_USER
        logger.info(f"Reports will be sent to: {target}")
    
    # Initialize file modification times
    global file_mtimes
    files = get_files_for_last_24_hours()
    file_mtimes = get_file_modification_times(files)
    logger.info(f"Monitoring {len(files)} file(s)")
    
    # Schedule jobs
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(job_check_files)
    schedule.every().day.at(REPORT_TIME).do(job_send_daily_report)
    
    logger.info(f"Scheduled: File check every {CHECK_INTERVAL_MINUTES} minute(s)")
    logger.info(f"Scheduled: Daily report at {REPORT_TIME}")
    logger.info("Scheduler running... Press Ctrl+C to stop")
    
    # Run the scheduler loop
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
    except Exception as e:
        logger.exception(f"Scheduler error: {e}")


if __name__ == "__main__":
    main()
