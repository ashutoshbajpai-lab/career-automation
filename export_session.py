"""
export_session.py - Exports your authenticated LinkedIn & Naukri sessions from your local Mac
to a portable session_cookies.json file. This allows your Oracle Cloud VM to run fully logged-in
without ever asking for passwords or triggering 2FA checkpoints.
"""

import os
import json
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SessionExporter")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "session_cookies.json")


def main():
    logger.info("Exporting authenticated session cookies for Oracle Cloud...")
    os.makedirs(DATA_DIR, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        )
        cookies = ctx.cookies([
            "https://www.linkedin.com",
            "https://www.naukri.com",
            "https://mail.google.com",
            "https://accounts.google.com"
        ])
        ctx.close()

    linkedin_cookies = [c for c in cookies if "linkedin" in c.get("domain", "")]
    naukri_cookies = [c for c in cookies if "naukri" in c.get("domain", "")]

    logger.info(f"Found {len(linkedin_cookies)} LinkedIn cookies (li_at present: {any(c['name'] == 'li_at' for c in linkedin_cookies)}).")
    logger.info(f"Found {len(naukri_cookies)} Naukri cookies.")

    payload = {
        "exported_at": os.popen("date").read().strip(),
        "cookies": cookies
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    logger.info(f"Successfully exported session to: {OUTPUT_FILE}")
    print("\n" + "=" * 65)
    print(f"SUCCESS: Session bundle saved to {OUTPUT_FILE}")
    print("This file contains your verified login sessions for cloud deployment.")
    print("=" * 65)


if __name__ == "__main__":
    main()
