"""
daily_scheduler.py - 24/7 Autonomous Background Scheduler for Cloud & Local deployment.
Runs:
1. Hourly/Daily Gmail Inbox Sweep: Never miss a screening round cleared, test link, or interview call.
2. Daily Naukri Recency Boost: Refreshes profile summary so recruiters always see 'Updated: Today'.
3. Daily Naukri 50+ Mass Apply: Continually submits on-platform applications.
4. LinkedIn Feed & Form Harvester: Extracts Google Forms and recruiter emails.
"""

import os
import time
import schedule
import logging
from datetime import datetime

from email_tracker import EmailTracker
from naukri_automator import NaukriAutomator
from recruitment_dispatcher import sync_leads

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DailyScheduler")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SCHEDULER_LOG = os.path.join(DATA_DIR, "scheduler_history.log")


def append_history(msg: str):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SCHEDULER_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


def job_scan_gmail():
    logger.info("SCHEDULED TASK: Checking Gmail inbox for screening cleared updates...")
    try:
        t = EmailTracker()
        results = t.scan_full_inbox()
        passed = t.get_screening_passed()
        msg = f"Gmail inbox sweep completed. Found {len(passed)} screening-passed opportunities out of {len(results)} updates."
        logger.info(msg)
        append_history(msg)
    except Exception as e:
        logger.error(f"Error in scheduled Gmail sweep: {e}")
        append_history(f"ERROR in Gmail sweep: {e}")


def job_naukri_boost():
    logger.info("SCHEDULED TASK: Executing daily Naukri recency boost...")
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
    logger.info("SCHEDULED TASK: Starting Naukri 50+ mass apply run...")
    try:
        n = NaukriAutomator()
        res = n.apply_jobs(daily_target=50)
        msg = f"Naukri Mass Apply finished: {res.get('applied_count')} direct applies, {res.get('manual_queued_count')} queued to manual desk."
        logger.info(msg)
        append_history(msg)
    except Exception as e:
        logger.error(f"Error in scheduled Naukri apply: {e}")
        append_history(f"ERROR in Naukri apply: {e}")


def job_harvest_leads():
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


def start_scheduler():
    logger.info("Starting Autonomous 24/7 Career Scheduler...")

    # Schedule routines:
    # 1. Email check every 3 hours (so you never miss an interview or screening passed notice)
    schedule.every(3).hours.do(job_scan_gmail)

    # 2. Daily morning routine (09:00 AM)
    schedule.every().day.at("09:00").do(job_naukri_boost)
    schedule.every().day.at("09:15").do(job_scan_gmail)
    schedule.every().day.at("09:30").do(job_naukri_apply)
    schedule.every().day.at("10:30").do(job_harvest_leads)

    # 3. Afternoon check (02:00 PM)
    schedule.every().day.at("14:00").do(job_scan_gmail)

    # 4. Evening routine (06:30 PM)
    schedule.every().day.at("18:30").do(job_scan_gmail)
    schedule.every().day.at("19:00").do(job_harvest_leads)

    append_history("Daily Scheduler initialized with 24/7 routines.")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    start_scheduler()
