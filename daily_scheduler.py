"""
daily_scheduler.py - 10-Hour Daily Autonomous Shift Scheduler (09:00 AM - 07:00 PM IST).
Active 10 hours a day during peak recruiter business hours in India:
1. 09:00 AM: Naukri Recency Boost ('Updated Today')
2. 09:30 AM: Morning 50+ Mass Apply Batch
3. 11:30 AM: LinkedIn Feed Harvesting & Form Extractor
4. 01:00 PM: Midday Inbox Sweep & Two-Phase Resume Reply Scanner
5. 03:30 PM: Afternoon Application Check & Lead Sync
6. 05:30 PM: Evening Recruiter Email & Form Extraction
7. 06:45 PM: Final Gmail Inbox Sweep for Screening Rounds Cleared
8. 07:00 PM: 10-Hour Shift Wrap-Up (Enters Night Standby till next 9 AM)
"""

import os
import time
import schedule
import logging
from datetime import datetime

from email_tracker import EmailTracker
from naukri_automator import NaukriAutomator
from recruitment_dispatcher import sync_leads
from referral_engine import ReferralEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DailyScheduler")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SCHEDULER_LOG = os.path.join(DATA_DIR, "scheduler_history.log")


def append_history(msg: str):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SCHEDULER_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


def is_active_10hr_window() -> bool:
    """Checks if current time is within the 10-hour recruiter window (09:00 - 19:00)."""
    now = datetime.now()
    return 9 <= now.hour < 19


def job_scan_gmail():
    if not is_active_10hr_window():
        return
    logger.info("SCHEDULED TASK: Checking Gmail inbox for screening cleared updates...")
    try:
        t = EmailTracker()
        results = t.scan_full_inbox()
        passed = t.get_screening_passed()
        msg = f"Gmail sweep completed: {len(passed)} screening-passed opportunities out of {len(results)} career updates."
        logger.info(msg)
        append_history(msg)
    except Exception as e:
        logger.error(f"Error in scheduled Gmail sweep: {e}")
        append_history(f"ERROR in Gmail sweep: {e}")


def job_naukri_boost():
    logger.info("SCHEDULED TASK (09:00 AM): Executing daily Naukri recency boost ('Updated Today')...")
    try:
        n = NaukriAutomator()
        res = n.boost_profile()
        msg = f"Naukri Recency Boost executed: {res.get('status')}"
        logger.info(msg)
        append_history(msg)
    except Exception as e:
        logger.error(f"Error in scheduled Naukri boost: {e}")
        append_history(f"ERROR in Naukri boost: {e}")


def job_naukri_apply():
    if not is_active_10hr_window():
        logger.info("Outside 10-hour business shift. Skipping application run.")
        return
    logger.info("SCHEDULED TASK: Starting Naukri 50+ mass apply run...")
    try:
        n = NaukriAutomator()
        res = n.apply_jobs(daily_target=50)
        msg = f"Naukri Mass Apply: {res.get('applied_count')} applied, {res.get('manual_queued_count')} queued to manual desk."
        logger.info(msg)
        append_history(msg)
    except Exception as e:
        logger.error(f"Error in scheduled Naukri apply: {e}")
        append_history(f"ERROR in Naukri apply: {e}")


def job_harvest_leads():
    if not is_active_10hr_window():
        return
    logger.info("SCHEDULED TASK: Harvesting LinkedIn feed for vacancy forms and recruiter leads...")
    try:
        os.system(f"python3 {os.path.join(BASE_DIR, 'run_automation.py')}")
        res = sync_leads()
        msg = f"Feed harvest finished: {len(res.get('forms', []))} forms, {len(res.get('emails', []))} recruiter leads synced."
        logger.info(msg)
        append_history(msg)
    except Exception as e:
        logger.error(f"Error in scheduled feed harvest: {e}")
        append_history(f"ERROR in feed harvest: {e}")


def job_scan_resume_replies():
    if not is_active_10hr_window():
        return
    logger.info("SCHEDULED TASK: Scanning LinkedIn inbox for resume requests ('share your resume')...")
    try:
        engine = ReferralEngine()
        dispatches = engine.check_inbox_and_dispatch_resume()
        msg = f"Two-Phase Resume Scanner: Auto-dispatched resume to {len(dispatches)} connections."
        logger.info(msg)
        append_history(msg)
    except Exception as e:
        logger.error(f"Error in resume reply scanner: {e}")
        append_history(f"ERROR in resume reply scanner: {e}")


def job_shift_wrap_up():
    logger.info("10-Hour Shift Complete (07:00 PM). Entering night standby until 09:00 AM tomorrow.")
    append_history("10-Hour Recruiter Shift Completed (09:00 AM - 07:00 PM IST). Enters Night Standby.")


def start_scheduler():
    logger.info("Starting Autonomous 10-Hour Daily Shift Scheduler (09:00 AM - 07:00 PM IST)...")

    # CONTINUOUS RECURRING SCRAPING THROUGHOUT THE 10-HOUR WINDOW:
    # 1. Feed Harvester runs every 45 minutes to catch newly posted hiring forms & leads:
    schedule.every(45).minutes.do(job_harvest_leads)

    # 2. Gmail Inbox Sweeper runs every 30 minutes for new screening/exam updates:
    schedule.every(30).minutes.do(job_scan_gmail)

    # 3. Two-Phase Resume Reply Scanner runs every 30 minutes to reply to recruiter requests:
    schedule.every(30).minutes.do(job_scan_resume_replies)

    # FIXED TIME MILESTONES:
    # 09:00 AM: Start Shift with Profile Recency Boost
    schedule.every().day.at("09:00").do(job_naukri_boost)
    schedule.every().day.at("09:30").do(job_naukri_apply)
    schedule.every().day.at("15:30").do(job_naukri_apply)
    schedule.every().day.at("19:00").do(job_shift_wrap_up)

    append_history("10-Hour Daily Continuous Shift Scheduler active (Continuous 30m/45m scraping from 09:00 AM - 07:00 PM IST).")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    start_scheduler()

