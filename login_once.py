"""
login_once.py - Interactive one-time login assistant.
Opens Google Chrome with anti-automation flags disabled so Google Sign-In (OAuth SSO)
and LinkedIn 2FA work seamlessly without closing or blocking the tab.
"""

import time
import logging
from browser_session import BrowserManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LinkedInLogin")


def main():
    logger.info("=" * 65)
    logger.info("Opening Google Chrome for One-Time LinkedIn Login...")
    logger.info("=" * 65)

    mgr = BrowserManager()
    context, page = mgr.get_context_and_page()

    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
    logger.info("Please sign in (via Google SSO or Email/Password) in the opened Chrome window.")
    logger.info("Waiting for your login to complete...")

    while True:
        time.sleep(2)
        try:
            cookies = context.cookies(["https://www.linkedin.com"])
            if any(c["name"] == "li_at" for c in cookies):
                logger.info("=" * 65)
                logger.info("SUCCESS! LinkedIn authentication cookie (li_at) detected.")
                logger.info("Your session is now saved permanently for automated runs.")
                logger.info("=" * 65)
                time.sleep(3)
                break
        except Exception:
            pass

    mgr.close()
    print("\nYou are all set! The automation will now run without prompting for login.")


if __name__ == "__main__":
    main()
