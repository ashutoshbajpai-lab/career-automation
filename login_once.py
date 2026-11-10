"""
login_once.py - Interactive one-time login assistant.
Opens Google Chrome on your screen so you can sign in to LinkedIn & Naukri once.
Automatically exports cookies and syncs them to Render cloud deployment.
"""

import os
import json
import time
import base64
import logging
import requests
from browser_session import BrowserManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SessionLogin")

RENDER_SERVICE_ID = "srv-dblnjm6c6qcc73bpkv70"
RENDER_API_KEY = "rnd_V7GNSF2DNymcat6NZAAz8ONRbGkh"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "session_cookies.json")


def sync_cookies_to_render(b64_payload: str):
    logger.info("Syncing updated session cookies to Render cloud service...")
    url = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars/SESSION_COOKIES_BASE64"
    headers = {
        "Authorization": f"Bearer {RENDER_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        res = requests.put(url, headers=headers, json={"value": b64_payload}, timeout=15)
        if res.status_code in (200, 201):
            logger.info("✅ SUCCESS: Fresh cookies uploaded to Render cloud! Service will auto-deploy with verified login.")
        else:
            logger.warning(f"Render API response ({res.status_code}): {res.text}")
    except Exception as e:
        logger.error(f"Failed to sync cookies to Render: {e}")


def main():
    logger.info("=" * 65)
    logger.info("Opening Google Chrome for LinkedIn & Naukri Login...")
    logger.info("=" * 65)

    mgr = BrowserManager()
    context, page = mgr.get_context_and_page(force_headless=False)

    # Clear any stale/expired LinkedIn cookies so the wait loop doesn't exit prematurely
    try:
        context.clear_cookies()
    except Exception:
        pass

    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
    logger.info("Please sign in (via Google SSO or Email/Password) in the opened Chrome window.")
    logger.info("Waiting for your LinkedIn login to complete...")

    while True:
        time.sleep(2)
        try:
            cur_url = (page.url or "").lower()
            cookies = context.cookies(["https://www.linkedin.com"])
            li_at = next((c["value"] for c in cookies if c["name"] == "li_at" and c.get("value")), None)
            on_logged_in_route = (
                "linkedin.com" in cur_url
                and not any(x in cur_url for x in ("/login", "/uas/login", "/checkpoint", "/authwall", "signup"))
            )
            if li_at and on_logged_in_route and mgr.probe_li_at_valid(li_at):
                logger.info("=" * 65)
                logger.info("SUCCESS! Live LinkedIn authentication cookie (li_at) verified.")
                break
        except Exception:
            pass

    # Give 3 seconds to ensure session is fully written
    time.sleep(3)

    # Export all cookies
    all_cookies = context.cookies([
        "https://www.linkedin.com",
        "https://www.naukri.com",
        "https://mail.google.com",
        "https://accounts.google.com"
    ])
    mgr.close()

    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {
        "status": "active",
        "exported_at": os.popen("date").read().strip(),
        "cookies": all_cookies
    }
    payload_str = json.dumps(payload, indent=2)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(payload_str)

    logger.info(f"Saved {len(all_cookies)} cookies to {OUTPUT_FILE}")

    # Base64 encode and push to Render
    b64_val = base64.b64encode(payload_str.encode("utf-8")).decode("utf-8")
    sync_cookies_to_render(b64_val)

    print("\n" + "=" * 65)
    print("ALL DONE! Your LinkedIn & Naukri sessions are saved and deployed to Render.")
    print("=" * 65)


if __name__ == "__main__":
    main()
