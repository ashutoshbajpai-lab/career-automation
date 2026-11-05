"""
browser_session.py - Manages browser connection with stealth anti-detection.
Supports:
1. Connecting to an existing Google Chrome instance on port 9222 (safest)
2. Fallback to a persistent browser profile with interactive login & cookie persistence
"""

import os
import time
import json
import random
import logging
import threading
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CDP_URL = "http://localhost:9222"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")
BROWSER_LOCK = threading.Lock()


def human_delay(min_sec: float = 2.0, max_sec: float = 4.5):
    """Sleep with randomized jitter to emulate human reading/scrolling."""
    duration = random.uniform(min_sec, max_sec)
    time.sleep(duration)


def smooth_scroll(page, total_pixels: int = 1000, steps: int = 4):
    """Simulate human scrolling with varied step sizes and pauses."""
    step_size = total_pixels // steps
    for _ in range(steps):
        jitter = random.randint(-30, 50)
        actual_step = max(50, step_size + jitter)
        try:
            page.evaluate(f"window.scrollBy({{ top: {actual_step}, behavior: 'smooth' }});")
        except Exception:
            pass
        time.sleep(random.uniform(0.7, 1.5))


class BrowserManager:
    def __init__(self, profile_name: str = "default"):
        self.playwright = None
        self.browser = None
        self.context = None
        self.is_cdp = False
        self.profile_name = profile_name
        self.has_lock = False

    def get_context_and_page(self, force_headless: bool = None):
        self.playwright = sync_playwright().start()

        # Method 1: Try connecting to Chrome running with --remote-debugging-port=9222
        try:
            logger.info("Checking for Chrome on debugging port 9222...")
            self.browser = self.playwright.chromium.connect_over_cdp(CDP_URL, timeout=2000)
            self.context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
            self.is_cdp = True
            logger.info("Connected to existing Chrome session successfully (CDP mode).")
            
            for page in self.context.pages:
                if "linkedin.com" in page.url:
                    return self.context, page
            page = self.context.new_page()
            return self.context, page

        except Exception:
            logger.info("Chrome port 9222 not available. Using persistent automation profile.")

        # Method 2: Launch persistent browser context with isolated profile per platform
        target_profile_dir = PROFILE_DIR if self.profile_name == "default" else os.path.join(BASE_DIR, f"chrome_profile_{self.profile_name}")
        os.makedirs(target_profile_dir, exist_ok=True)
        
        # Clean up stale singleton lock if process is dead
        for lock_file in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
            lp = os.path.join(target_profile_dir, lock_file)
            if os.path.exists(lp) or os.path.islink(lp):
                try:
                    os.unlink(lp)
                except Exception:
                    pass

        # Concurrency safety: acquire execution lock with fast 5s timeout instead of hanging 180s
        if not BROWSER_LOCK.acquire(timeout=5):
            raise RuntimeError(f"Browser is busy with another active task. Deferred '{self.profile_name}' operation.")
        self.has_lock = True

        chrome_executable = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        
        if force_headless is not None:
            is_headless = force_headless
        else:
            headless_env = os.environ.get("HEADLESS", "").lower()
            if headless_env in ("true", "1"):
                is_headless = True
            elif headless_env in ("false", "0"):
                is_headless = False
            else:
                is_headless = True  # Lean, high-performance default for LinkedIn & cloud

        launch_kwargs = {
            "user_data_dir": target_profile_dir,
            "headless": is_headless,
            "viewport": {"width": 1280, "height": 800},
            "ignore_default_args": ["--enable-automation"],
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-accelerated-2d-canvas",
                "--no-zygote",
                "--window-size=1280,800",
                "--js-flags=--max-old-space-size=96",
                "--renderer-process-limit=1",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-sync"
            ]
        }
        if os.path.exists(chrome_executable):
            launch_kwargs["executable_path"] = chrome_executable

        logger.info(f"Launching Playwright context (profile={self.profile_name}, headless={is_headless}, DISPLAY={os.environ.get('DISPLAY', 'None')})...")
        self.context = self.playwright.chromium.launch_persistent_context(**launch_kwargs)

        # Automatically inject session cookies if present
        session_file = os.path.join(BASE_DIR, "data", "session_cookies.json")
        if os.path.exists(session_file):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                cookies = sdata.get("cookies", [])
                if cookies:
                    self.context.add_cookies(cookies)
                    logger.info(f"Injected {len(cookies)} authentication cookies into browser session.")
            except Exception as e:
                logger.warning(f"Failed to auto-inject cookies: {e}")

        page = self.context.pages[0] if self.context.pages else self.context.new_page()

        # Keep popups alive during Google OAuth SSO flow
        self.context.on("page", lambda new_p: logger.info(f"Opened popup/tab: {new_p.url or 'authenticating'}"))

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        return self.context, page

    def ensure_logged_in(self, page, timeout_sec: int = 300) -> bool:
        """
        Deterministic check for LinkedIn authentication using the official li_at cookie.
        If missing, opens login page and waits up to timeout_sec for the user to sign in.
        """
        cookies = self.context.cookies(["https://www.linkedin.com"])
        if any(c["name"] == "li_at" for c in cookies):
            logger.info("Session verified: User is logged in to LinkedIn (li_at cookie active).")
            return True

        logger.info("=" * 65)
        logger.info("ACTION REQUIRED: A Google Chrome window is open on your screen.")
        logger.info("Please log in to your LinkedIn account in that browser window.")
        logger.info(f"Waiting up to {timeout_sec} seconds for you to sign in...")
        logger.info("=" * 65)

        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

        start = time.time()
        while time.time() - start < timeout_sec:
            time.sleep(2)
            cookies = self.context.cookies(["https://www.linkedin.com"])
            if any(c["name"] == "li_at" for c in cookies):
                logger.info("SUCCESS: Login detected! Authentication session saved.")
                time.sleep(2)
                return True

        logger.error("Timed out waiting for LinkedIn sign in.")
        return False

    def close(self):
        try:
            if self.is_cdp:
                if self.browser:
                    self.browser.close()
            else:
                if self.context:
                    self.context.close()
            if self.playwright:
                self.playwright.stop()
        except Exception as e:
            logger.debug(f"Error during browser close: {e}")
        finally:
            self.browser = None
            self.context = None
            self.playwright = None
            if self.has_lock:
                try:
                    BROWSER_LOCK.release()
                except Exception:
                    pass
                self.has_lock = False
            import gc
            gc.collect()
