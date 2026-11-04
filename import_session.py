"""
import_session.py - Injects the exported session_cookies.json into the cloud Chrome profile.
Ensures the cloud browser is instantly logged into LinkedIn and Naukri.
"""

import os
import json
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SessionImporter")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")
SESSION_FILE = os.path.join(BASE_DIR, "data", "session_cookies.json")


def main():
    if not os.path.exists(SESSION_FILE):
        logger.error(f"Session file not found at: {SESSION_FILE}")
        return

    with open(SESSION_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    cookies = data.get("cookies", [])
    logger.info(f"Injecting {len(cookies)} session cookies into cloud profile...")

    os.makedirs(PROFILE_DIR, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        ctx.add_cookies(cookies)
        ctx.close()

    logger.info("SUCCESS: Cookies imported! Cloud instance is authenticated.")


if __name__ == "__main__":
    main()
