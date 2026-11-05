"""
company_network_expander.py - Regional Company & Startup Network Expander.
Features:
1. Targets companies in the region (Mumbai, Startups, Fintech, E-commerce, SaaS).
2. Searches company Job sections for aligned roles (Analyst, APM, Product Manager, Business/Data Analyst).
3. Navigates to the People section of each company.
4. Sends Connection Requests ONLY (NO note attached, clean 1-click connect).
5. Separate from direct messaging.
"""

import os
import re
import csv
import json
import logging
from datetime import datetime
from urllib.parse import quote_plus

from browser_session import BrowserManager, human_delay
from referral_engine import ReferralEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CompanyExpander")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DISCOVERED_JOBS_FILE = os.path.join(DATA_DIR, "discovered_company_jobs.json")
CONNECTIONS_LOG = os.path.join(DATA_DIR, "connection_requests_sent.csv")
OUTREACH_CSV = os.path.join(DATA_DIR, "outreach_tracker.csv")

DEFAULT_MUMBAI_STARTUPS = [
    {"name": "Zepto", "slug": "zeptonow"},
    {"name": "Nykaa", "slug": "nykaa-com"},
    {"name": "BookMyShow", "slug": "bookmyshow"},
    {"name": "BrowserStack", "slug": "browserstack"},
    {"name": "CleverTap", "slug": "clevertap"},
    {"name": "Dream11", "slug": "dream11"},
    {"name": "Gupshup", "slug": "gupshup"},
    {"name": "Fractal", "slug": "fractal-analytics"},
    {"name": "AngelOne", "slug": "angel-one-limited"},
    {"name": "Upstox", "slug": "upstox"},
    {"name": "Swiggy", "slug": "swiggy-in"},
    {"name": "Razorpay", "slug": "razorpay"},
    {"name": "CRED", "slug": "cred_club"},
    {"name": "PhonePe", "slug": "phonepe-internet"},
    {"name": "Groww", "slug": "groww-in"}
]


class CompanyNetworkExpander:
    def __init__(self, browser_mgr: BrowserManager = None):
        self.browser_mgr = browser_mgr or BrowserManager()
        os.makedirs(DATA_DIR, exist_ok=True)
        self.referral_engine = ReferralEngine(self.browser_mgr)

    def load_config(self) -> dict:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def run_company_expansion(self, max_companies: int = 4, max_connects_per_company: int = 3) -> dict:
        """
        Main execution:
        1. Evaluates target companies in Mumbai & Startups.
        2. Searches aligned jobs in each company's /jobs/ section.
        3. Enters /people/ section and sends CONNECTION REQUEST ONLY (No note).
        """
        cfg = self.load_config()
        target_roles = cfg.get("target_roles", ["Analyst", "Product Manager", "Associate Product Manager"])
        
        context, page = self.browser_mgr.get_context_and_page()
        try:
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
        except Exception:
            pass
        if not self.browser_mgr.ensure_logged_in(page):
            logger.error("LinkedIn login required for company network expansion.")
            return {"status": "Failed", "reason": "Not logged in"}

        companies = DEFAULT_MUMBAI_STARTUPS[:max_companies]
        total_connections_sent = 0
        total_jobs_found = []
        sent_records = []

        logger.info(f"Starting Regional & Startup Network Expansion for {len(companies)} companies...")

        for comp in companies:
            comp_name = comp["name"]
            comp_slug = comp["slug"]
            logger.info(f"\n--- Processing Company: {comp_name} ({comp_slug}) ---")

            # Step 1: Search Company's Jobs Section for Aligned Roles
            try:
                jobs_url = f"https://www.linkedin.com/company/{comp_slug}/jobs/"
                page.goto(jobs_url, wait_until="domcontentloaded")
                human_delay(3.0, 4.0)

                found_jobs = page.evaluate('''() => {
                    const jobs = [];
                    document.querySelectorAll("li.org-jobs-job-search-results-list__list-item, div.job-card-container, div.artdeco-entity-lockup").forEach(el => {
                        const titleEl = el.querySelector("a[href*='/jobs/view/'], .job-card-list__title, h3");
                        const linkEl = el.querySelector("a[href*='/jobs/view/']");
                        if (titleEl && titleEl.innerText) {
                            const title = titleEl.innerText.trim();
                            const link = linkEl ? linkEl.href.split('?')[0] : '';
                            jobs.push({ title: title, url: link });
                        }
                    });
                    return jobs;
                }''')

                aligned_jobs = []
                for j in found_jobs:
                    title_lower = j.get("title", "").lower()
                    if any(r.lower() in title_lower for r in target_roles) or "analyst" in title_lower or "product" in title_lower:
                        j["company"] = comp_name
                        j["discovered_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        aligned_jobs.append(j)

                if aligned_jobs:
                    logger.info(f"Found {len(aligned_jobs)} aligned jobs at {comp_name}!")
                    total_jobs_found.extend(aligned_jobs)
                    self._save_discovered_jobs(aligned_jobs)
                else:
                    logger.info(f"No active Analyst/PM postings listed on {comp_name} job board today.")

            except Exception as e:
                logger.warning(f"Error checking jobs for {comp_name}: {e}")

            # Step 2: Go to Company's People Section & Send Connection Requests ONLY (NO NOTE)
            try:
                # Priority search: Product, Analytics, Recruiters, and PEC Alumni
                people_url = f"https://www.linkedin.com/company/{comp_slug}/people/?keywords=Product%20Manager"
                page.goto(people_url, wait_until="domcontentloaded")
                human_delay(3.5, 4.5)

                people = self.referral_engine._extract_people_from_page(page, comp_name)
                logger.info(f"Extracted {len(people)} aligned people from {comp_name} people directory.")

                company_connects = 0
                for person in people:
                    if company_connects >= max_connects_per_company:
                        break

                    name = person.get("name", "Unknown")
                    profile_url = person.get("profile_url", "")
                    headline = person.get("headline", "")

                    if not profile_url or self._already_sent(profile_url):
                        continue

                    try:
                        logger.info(f"Navigating to {name} ({comp_name}) to send connection request (No note)...")
                        page.goto(profile_url, wait_until="domcontentloaded")
                        human_delay(3.0, 4.0)

                        # Clean connection request with NO note
                        sent = self.referral_engine._send_connection_request(page, note_text="")
                        if sent:
                            company_connects += 1
                            total_connections_sent += 1
                            rec = {
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "name": name,
                                "company": comp_name,
                                "headline": headline,
                                "profile_url": profile_url,
                                "action_type": "Connection Request (No Note)",
                                "status": "Sent"
                            }
                            self._log_connection(rec)
                            self.referral_engine._record_outreach({
                                "timestamp": rec["timestamp"],
                                "name": name,
                                "company": comp_name,
                                "headline": headline,
                                "profile_url": profile_url,
                                "action_type": "Connection Request (No Note)",
                                "status": "Sent",
                                "message_text": "[Connection Request Only - No Message Attached]"
                            })
                            sent_records.append(rec)
                            logger.info(f"SUCCESS: Connection request sent to {name} ({comp_name})!")
                            human_delay(3.0, 5.0)

                    except Exception as inner_e:
                        logger.warning(f"Could not connect with {name}: {inner_e}")

            except Exception as e:
                logger.warning(f"Error accessing people section for {comp_name}: {e}")

        logger.info(f"\nFINISHED: Sent {total_connections_sent} connection requests across {len(companies)} companies.")
        return {
            "status": "Success",
            "companies_processed": len(companies),
            "connections_sent": total_connections_sent,
            "jobs_found": len(total_jobs_found),
            "records": sent_records
        }

    def _already_sent(self, profile_url: str) -> bool:
        if not os.path.exists(CONNECTIONS_LOG):
            return False
        try:
            with open(CONNECTIONS_LOG, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("profile_url") == profile_url:
                        return True
        except Exception:
            pass
        return False

    def _log_connection(self, item: dict):
        file_exists = os.path.exists(CONNECTIONS_LOG)
        with open(CONNECTIONS_LOG, "a", newline="", encoding="utf-8") as f:
            fieldnames = ["timestamp", "name", "company", "headline", "profile_url", "action_type", "status"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(item)

    def _save_discovered_jobs(self, jobs: list):
        current = []
        if os.path.exists(DISCOVERED_JOBS_FILE):
            try:
                with open(DISCOVERED_JOBS_FILE, "r", encoding="utf-8") as f:
                    current = json.load(f)
            except Exception:
                current = []
        
        seen_urls = {j.get("url") for j in current if j.get("url")}
        for job in jobs:
            if job.get("url") not in seen_urls:
                current.append(job)
                seen_urls.add(job.get("url"))

        with open(DISCOVERED_JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)


if __name__ == "__main__":
    expander = CompanyNetworkExpander()
    res = expander.run_company_expansion(max_companies=2, max_connects_per_company=2)
    print("Expansion Result:", json.dumps(res, indent=2))
