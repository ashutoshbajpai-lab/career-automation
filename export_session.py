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

    has_li_at = any(c['name'] == 'li_at' for c in linkedin_cookies)
    logger.info(f"Found {len(linkedin_cookies)} LinkedIn cookies (li_at present: {has_li_at}).")
    logger.info(f"Found {len(naukri_cookies)} Naukri cookies.")

    if not has_li_at:
        logger.error("ABORTING EXPORT: No active 'li_at' cookie found in profile! Preserving existing session file.")
        return

    payload = {
        "exported_at": os.popen("date").read().strip(),
        "cookies": cookies
    }

    payload_str = json.dumps(payload, indent=2)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(payload_str)

    logger.info(f"Successfully exported session to: {OUTPUT_FILE}")

    # Auto-sync to Render
    import base64
    import requests
    b64_val = base64.b64encode(payload_str.encode("utf-8")).decode("utf-8")
    url = "https://api.render.com/v1/services/srv-dblnjm6c6qcc73bpkv70/env-vars/SESSION_COOKIES_BASE64"
    headers = {
        "Authorization": "Bearer rnd_V7GNSF2DNymcat6NZAAz8ONRbGkh",
        "Content-Type": "application/json"
    }
    try:
        res = requests.put(url, headers=headers, json={"value": b64_val}, timeout=15)
        if res.status_code in (200, 201):
            logger.info("✅ SUCCESS: Fresh cookies uploaded to Render cloud! Service will auto-deploy with verified login.")
    except Exception as e:
        logger.warning(f"Could not push to Render: {e}")
    print("\n" + "=" * 65)
    print(f"SUCCESS: Session bundle saved to {OUTPUT_FILE}")
    print("This file contains your verified login sessions for cloud deployment.")
    print("=" * 65)


if __name__ == "__main__":
    main()
