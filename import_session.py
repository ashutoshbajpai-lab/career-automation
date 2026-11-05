"""
import_session.py - Injects the exported session_cookies.json into the cloud Chrome profile.
Ensures the cloud browser is instantly logged into LinkedIn and Naukri.
"""

import os
import json
import base64
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SessionImporter")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")
DATA_DIR = os.path.join(BASE_DIR, "data")
SESSION_FILE = os.path.join(DATA_DIR, "session_cookies.json")


def main():
    # If session cookies passed via environment variable (e.g. Render / Cloud)
    env_b64 = os.environ.get("SESSION_COOKIES_BASE64", "")
    if env_b64 and not os.path.exists(SESSION_FILE):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(SESSION_FILE, "wb") as f:
                f.write(base64.b64decode(env_b64.strip()))
            logger.info("Restored session cookies from SESSION_COOKIES_BASE64 environment variable.")
        except Exception as e:
            logger.error(f"Error decoding SESSION_COOKIES_BASE64: {e}")

    if not os.path.exists(SESSION_FILE) or os.path.getsize(SESSION_FILE) == 0:
        logger.info(f"No session cookies to import (missing or empty at {SESSION_FILE}).")
        return

    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"Could not parse {SESSION_FILE}: {e}")
        return

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
