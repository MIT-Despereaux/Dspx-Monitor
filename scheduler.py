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
import logging
import schedule
import pandas as pd
from datetime import datetime

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

# Track K5 pressure monitoring state
k5_above_threshold = False
k5_threshold_start_time = None
K5_THRESHOLD = 2000  # mbar


def check_k5_pressure():
    """Monitor K5 pressure and send condensation monitoring alerts when it crosses threshold."""
    global k5_above_threshold, k5_threshold_start_time
    
    # Load latest data
    files = get_files_for_last_24_hours()
    if not files:
        return
    
    df = load_multiple_files(files, logger)
    if df is None or len(df) == 0:
        return
    
    # Get latest K5 value
    if "K5" not in df.columns:
        logger.warning("K5 column not found in data")
        return
    
    k5_values = pd.to_numeric(df["K5"], errors="coerce")
    current_k5 = k5_values.iloc[-1]
    
    if pd.isna(current_k5):
        return
    
    logger.debug(f"K5 current value: {current_k5:.2f} mbar (threshold: {K5_THRESHOLD} mbar)")
    
    bot_token = SECRETS.get("SLACK_BOT_TOKEN", "")
    target = SLACK_REPORT_CHANNEL or SLACK_REPORT_USER
    is_dm = bool(SLACK_REPORT_USER and not SLACK_REPORT_CHANNEL)
    
    # Check if K5 crossed above threshold
    if current_k5 > K5_THRESHOLD and not k5_above_threshold:
        k5_above_threshold = True
        k5_threshold_start_time = datetime.now()
        
        logger.warning(f"ℹ️ Condensation starting (K5: {current_k5:.2f} mbar, threshold: {K5_THRESHOLD} mbar)")
        
        if bot_token and target:
            # Build alert message
            alert_text = f"ℹ️ Condensation Monitoring\n\nCondensation starting\nK5 value: {current_k5:.2f} mbar (threshold: {K5_THRESHOLD} mbar)\nTime: {k5_threshold_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
            
            alert_blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "ℹ️ Condensation Monitoring",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Condensation starting*\n• K5 threshold: `{K5_THRESHOLD} mbar`\n• Current K5: `{current_k5:.2f} mbar`\n• Start time: {k5_threshold_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
                    }
                }
            ]
            
            success, message = send_slack_message(
                bot_token=bot_token,
                target=target,
                text=alert_text,
                blocks=alert_blocks,
                is_dm=is_dm,
                logger=logger
            )
            
            if success:
                logger.info("Condensation alert sent successfully")
            else:
                logger.error(f"Failed to send condensation alert: {message}")
    
    # Check if K5 dropped below threshold
    elif current_k5 <= K5_THRESHOLD and k5_above_threshold:
        duration = datetime.now() - k5_threshold_start_time
        k5_above_threshold = False
        
        # Format duration
        hours = int(duration.total_seconds() // 3600)
        minutes = int((duration.total_seconds() % 3600) // 60)
        seconds = int(duration.total_seconds() % 60)
        duration_str = f"{hours}h {minutes}m {seconds}s"
        
        logger.info(f"ℹ️ Condensation finished (K5: {current_k5:.2f} mbar, duration: {duration_str})")
        
        if bot_token and target:
            # Build recovery message
            recovery_text = f"ℹ️ Condensation Monitoring\n\nCondensation finished\nTotal time: {duration_str}\nK5 value: {current_k5:.2f} mbar (threshold: {K5_THRESHOLD} mbar)\nEnd time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            recovery_blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "ℹ️ Condensation Monitoring",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Condensation finished*\n• Total time: `{duration_str}`\n• K5 threshold: `{K5_THRESHOLD} mbar`\n• Current K5: `{current_k5:.2f} mbar`\n• End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    }
                }
            ]
            
            success, message = send_slack_message(
                bot_token=bot_token,
                target=target,
                text=recovery_text,
                blocks=recovery_blocks,
                is_dm=is_dm,
                logger=logger
            )
            
            if success:
                logger.info("Condensation finished alert sent successfully")
            else:
                logger.error(f"Failed to send condensation finished alert: {message}")
        
        k5_threshold_start_time = None


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
    """Scheduled job: Check for file updates and K5 pressure every minute."""
    logger.debug("Running file check...")
    check_file_updates()
    check_k5_pressure()


def job_send_daily_report():
    """Scheduled job: Send daily report at 3 PM."""
    send_scheduled_report()


def main():
    """Main scheduler loop."""
    logger.info("=" * 50)
    logger.info("Dspx-Monitor Scheduler Started")
    logger.info(f"Report time: {REPORT_TIME}")
    logger.info(f"File check interval: {CHECK_INTERVAL_MINUTES} minute(s)")
    logger.info(f"K5 condensation monitoring threshold: {K5_THRESHOLD} mbar")
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
