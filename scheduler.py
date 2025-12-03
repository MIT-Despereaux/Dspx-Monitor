#!/usr/bin/env python3
"""
Dspx-Monitor Background Scheduler
Runs independently of the Streamlit dashboard to:
1. Check data files every minute and signal dashboard to refresh
2. Send daily reports to Slack at 3 PM
"""

from __future__ import annotations

import os
import sys
import time
import logging
import schedule
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import shared core module
from core import (
    LOG_DIR,
    load_secrets,
    get_files_for_last_24_hours,
    get_file_modification_times,
    load_multiple_files,
    filter_to_last_24_hours,
    calculate_daily_stats,
    send_daily_report,
    write_refresh_signal,
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

# Load secrets
SECRETS = load_secrets()

# Slack channel/user to send reports to
SLACK_REPORT_CHANNEL = os.environ.get("SLACK_REPORT_CHANNEL", "")
SLACK_REPORT_USER = os.environ.get("SLACK_REPORT_USER", "")

# Track file modification times
file_mtimes = {}


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
    stats = calculate_daily_stats(df)
    
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
    """Scheduled job: Check for file updates every minute."""
    logger.debug("Running file check...")
    check_file_updates()


def job_send_daily_report():
    """Scheduled job: Send daily report at 3 PM."""
    send_scheduled_report()


def main():
    """Main scheduler loop."""
    logger.info("=" * 50)
    logger.info("Dspx-Monitor Scheduler Started")
    logger.info(f"Report time: {REPORT_TIME}")
    logger.info(f"File check interval: {CHECK_INTERVAL_MINUTES} minute(s)")
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
