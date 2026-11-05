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

        # Method 2: Launch persistent browser context with authenticated profile
        target_profile_dir = PROFILE_DIR
        os.makedirs(target_profile_dir, exist_ok=True)
        
        # Clean up stale singleton locks or leftover locks if process was terminated
        try:
            for item in os.listdir(target_profile_dir):
                if item.startswith("Singleton") or item.endswith(".lock") or item == "lockfile":
                    lp = os.path.join(target_profile_dir, item)
                    try:
                        os.unlink(lp)
                    except Exception:
                        pass
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
            "timeout": 35000,
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "viewport": {"width": 1024, "height": 768},
            "locale": "en-US",
            "timezone_id": "Asia/Kolkata",
            "ignore_default_args": ["--enable-automation"],
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-gpu-compositing",
                "--use-gl=disabled",
                "--disable-software-rasterizer",
                "--blink-settings=imagesEnabled=false",
                "--renderer-process-limit=1",
                "--no-zygote",
                "--mute-audio",
                "--disk-cache-size=1",
                "--media-cache-size=1",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-sync",
                "--disable-features=AudioServiceOutOfProcess,IsolateOrigins,site-per-process,Translate,OptimizationHints,MediaRouter,BackForwardCache",
                "--js-flags=--max-old-space-size=160 --optimize_for_size"
            ]
        }
        if os.path.exists(chrome_executable):
            launch_kwargs["executable_path"] = chrome_executable

        logger.info(f"Launching Playwright context (profile={self.profile_name}, headless={is_headless}, DISPLAY={os.environ.get('DISPLAY', 'None')})...")
        self.context = self.playwright.chromium.launch_persistent_context(**launch_kwargs)

        # Automatically inject session cookies if present
        session_file = os.path.join(BASE_DIR, "data", "session_cookies.json")
        cookies = []
        if os.path.exists(session_file):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                cookies = sdata.get("cookies", [])
            except Exception as e:
                logger.warning(f"Failed to auto-inject cookies from file: {e}")

        # Fallback to SESSION_COOKIES_BASE64 if file missing or empty
        if not cookies:
            env_b64 = os.environ.get("SESSION_COOKIES_BASE64", "")
            if env_b64:
                try:
                    import base64
                    sdata = json.loads(base64.b64decode(env_b64.strip()).decode("utf-8"))
                    cookies = sdata.get("cookies", [])
                except Exception as e:
                    logger.warning(f"Failed to decode SESSION_COOKIES_BASE64: {e}")

        if cookies:
            try:
                self.context.add_cookies(cookies)
                logger.info(f"Injected {len(cookies)} authentication cookies into browser session.")
            except Exception as e:
                logger.warning(f"Failed to add all cookies en masse: {e}. Retrying individually...")
                added = 0
                for c in cookies:
                    try:
                        self.context.add_cookies([c])
                        added += 1
                    except Exception:
                        pass
                logger.info(f"Injected {added}/{len(cookies)} authentication cookies individually.")

        page = self.context.pages[0] if self.context.pages else self.context.new_page()

        # Keep popups alive during Google OAuth SSO flow
        self.context.on("page", lambda new_p: logger.info(f"Opened popup/tab: {new_p.url or 'authenticating'}"))

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.navigator.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        try:
            page.set_extra_http_headers({
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"macOS"',
                "Upgrade-Insecure-Requests": "1"
            })
        except Exception:
            pass

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
