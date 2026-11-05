"""
run_automation.py - Main runner for the LinkedIn Automation Suite.
Coordinates authentication check, feed harvesting, and job scanning.
"""

import os
import json
import logging
from datetime import datetime
from browser_session import BrowserManager
from feed_harvester import FeedHarvester
from job_scanner import JobScanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("LinkedInAutomator")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
REPORT_FILE = os.path.join(DATA_DIR, "latest_run_summary.md")


def load_json(filepath: str, default: dict) -> dict:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load {filepath}: {e}")
    return default


def save_json(filepath: str, data: dict):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main():
    logger.info("==================================================")
    logger.info("   Starting LinkedIn Automation Execution         ")
    logger.info("==================================================")

    config = load_json(CONFIG_FILE, {
        "target_roles": ["Analyst", "Associate Product Manager"],
        "location": "India",
        "dry_run": True,
        "limits": {
            "max_feed_posts_per_run": 20,
            "max_jobs_evaluated_per_run": 15,
            "max_easy_applies_per_run": 3,
            "max_easy_applies_per_day": 12
        }
    })
    state = load_json(STATE_FILE, {
        "last_run_date": "",
        "daily_apply_count": 0,
        "seen_post_urns": [],
        "seen_job_ids": []
    })

    browser_mgr = BrowserManager()
    new_leads = []
    job_results = {"easy_applied": [], "manual_queued": []}

    try:
        context, page = browser_mgr.get_context_and_page(force_headless=True)
        try:
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
        except Exception:
            pass

        # Step 0: Ensure User is Authenticated
        is_logged_in = browser_mgr.ensure_logged_in(page, timeout_sec=240)
        if not is_logged_in:
            logger.error("Could not verify LinkedIn login. Exiting run safely.")
            return

        # Step 1: Harvest Feed for hiring posts, Google Forms, and Emails
        logger.info("\n--- Phase 1: Feed Harvester ---")
        harvester = FeedHarvester(page=page, config=config, state=state, base_dir=BASE_DIR)
        new_leads = harvester.run()

        # Step 2: Scan Jobs section for Analyst & APM roles
        logger.info("\n--- Phase 2: Jobs Section & Application Router ---")
        job_scanner = JobScanner(page=page, config=config, state=state, base_dir=BASE_DIR)
        job_results = job_scanner.run()

    except Exception as e:
        logger.error(f"Execution error: {e}", exc_info=True)

    finally:
        save_json(STATE_FILE, state)
        browser_mgr.close()
        logger.info("Browser session disconnected.")

    # Generate Markdown Summary Report
    run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    applied_count = len(job_results.get("easy_applied", []))
    manual_count = len(job_results.get("manual_queued", []))
    leads_count = len(new_leads)

    summary_md = f"""# LinkedIn Automation Run Summary - {run_timestamp}

### Quick Stats
- **New Feed Leads Discovered**: {leads_count}
- **Easy Apply Applications Processed**: {applied_count} (Dry-run mode: {config.get('dry_run', False)})
- **Workday / Oracle / MNC Openings Routed to Manual Queue**: {manual_count}
- **Daily Apply Count**: {state.get('daily_apply_count', 0)} / {config.get('limits', {}).get('max_easy_applies_per_day', 12)}

---

## 1. Discovered Feed Leads (Emails / Google Forms / Hiring Posts)
"""
    if new_leads:
        for lead in new_leads:
            author = lead.get("author", "LinkedIn Member")
            profile = lead.get("author_profile", "")
            author_str = f"[{author}]({profile})" if profile else f"**{author}**"
            summary_md += f"""
- {author_str}
  - **Emails**: `{lead.get('emails') or 'None detected'}`
  - **Forms**: `{lead.get('form_links') or 'None detected'}`
  - **Links**: {lead.get('hyperlinks') or 'None'}
  - **Snippet**: *"{lead.get('preview', '')[:140]}..."*
"""
    else:
        summary_md += "\n*No new hiring leads or form links detected in this feed scan.*\n"

    summary_md += """
---

## 2. Workday / Oracle / MNC Openings (Action Required: Apply Manually)
> As requested, all openings from MNCs or external applicant tracking systems (Workday, Oracle, Taleo, Greenhouse, etc.) have been skipped from auto-apply and logged here for your manual submission.

| Company | Role / Title | Direct Opening Link | Detected At |
| :--- | :--- | :--- | :--- |
"""
    manual_jobs = job_results.get("manual_queued", [])
    if manual_jobs:
        for j in manual_jobs:
            summary_md += f"| **{j['company']}** | {j['title']} | [Open Job on LinkedIn]({j['job_url']}) | {j['timestamp']} |\n"
    else:
        summary_md += "| *No new MNC/Workday openings in this batch* | - | - | - |\n"

    summary_md += """
---

## 3. Easy Apply Opportunities
"""
    easy_jobs = job_results.get("easy_applied", [])
    if easy_jobs:
        for j in easy_jobs:
            status_text = "(Test Mode: Identified & eligible)" if j.get("test_mode") else "(Submitted)"
            summary_md += f"- **{j['title']}** at **{j['company']}** {status_text} ([View]({j['url']}))\n"
    else:
        summary_md += "\n*No Easy Apply jobs met the criteria during this run.*\n"

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(summary_md)

    logger.info(f"\nRun summary written to {REPORT_FILE}")
    print("\n" + summary_md)


if __name__ == "__main__":
    main()
