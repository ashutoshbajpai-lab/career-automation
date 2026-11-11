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


def is_cloud_low_mem() -> bool:
    """Detects 512MB Render cloud container or explicit LOW_MEM_MODE=1 testing."""
    return bool(
        os.environ.get("RENDER")
        or os.environ.get("RENDER_SERVICE_ID")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or os.environ.get("LOW_MEM_MODE") == "1"
    )


def get_tree_ram_mb() -> float:
    """Returns total RSS memory in MB for Python process plus all Chromium child processes."""
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        total = proc.memory_info().rss
        for child in proc.children(recursive=True):
            try:
                total += child.memory_info().rss
            except Exception:
                pass
        return round(total / (1024 * 1024), 1)
    except Exception:
        return 0.0


def wait_for_ram_cooldown(soft_limit_mb: float = 350.0, max_wait_sec: float = 6.0, log_cb=None) -> float:
    """Runs garbage collection and briefly waits if child Chromium RSS is still winding down."""
    import gc
    gc.collect()
    ram = get_tree_ram_mb()
    waited = 0.0
    while ram > soft_limit_mb and waited < max_wait_sec:
        time.sleep(1.0)
        waited += 1.0
        gc.collect()
        ram = get_tree_ram_mb()
    if log_cb and ram > 0:
        log_cb(f"📊 [LOAD MANAGER] Active Tree RAM: {ram} MB ({'Cloud 512MB Mode' if is_cloud_low_mem() else 'Local Mode'})")
    return ram


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
                "--headless=new",
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
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                f"--js-flags=--max-old-space-size={'128' if is_cloud_low_mem() else '160'} --optimize_for_size"
            ]
        }
        if os.path.exists(chrome_executable):
            launch_kwargs["executable_path"] = chrome_executable

        logger.info(f"Launching Playwright context (profile={self.profile_name}, headless={is_headless}, DISPLAY={os.environ.get('DISPLAY', 'None')})...")
        self.context = self.playwright.chromium.launch_persistent_context(**launch_kwargs)

        # Automatically inject session cookies only if active (do not inject known-expired cookies)
        session_file = os.path.join(BASE_DIR, "data", "session_cookies.json")
        cookies = []
        sdata = {}
        if os.path.exists(session_file):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                if sdata.get("status") != "expired":
                    cookies = sdata.get("cookies", [])
            except Exception as e:
                logger.warning(f"Failed to auto-inject cookies from file: {e}")

        # Fallback to SESSION_COOKIES_BASE64 if file missing or empty
        if not cookies and sdata.get("status") != "expired":
            env_b64 = os.environ.get("SESSION_COOKIES_BASE64", "")
            if env_b64:
                try:
                    import base64
                    sdata = json.loads(base64.b64decode(env_b64.strip()).decode("utf-8"))
                    if sdata.get("status") != "expired":
                        cookies = sdata.get("cookies", [])
                except Exception as e:
                    logger.warning(f"Failed to decode SESSION_COOKIES_BASE64: {e}")

        if cookies:
            # Remove any stale LinkedIn cookies stored in chrome_profile (e.g. .www.linkedin.com li_at
            # or expired JSESSIONID) so they never conflict with session_cookies.json.
            if any(c.get("name") == "li_at" and c.get("value") for c in cookies):
                try:
                    import re
                    self.context.clear_cookies(domain=re.compile(r"linkedin\.com$"))
                except Exception:
                    try:
                        self.context.clear_cookies(name="li_at")
                    except Exception:
                        pass
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

        # Note: Do NOT set page.set_extra_http_headers with custom CORS-triggering headers.
        # Chromium already provides standard headers matching user_agent and locale.

        return self.context, page

    @staticmethod
    def probe_li_at_valid(li_at_val: str) -> bool:
        """Lightweight live check whether a LinkedIn li_at cookie still accesses /feed/ without login redirect."""
        if not li_at_val or len(li_at_val.strip()) < 20 or any(c.isspace() for c in li_at_val):
            return False
        try:
            import requests
            session = requests.Session()
            session.max_redirects = 5
            session.cookies.set("li_at", li_at_val, domain=".linkedin.com")
            res = session.get(
                "https://www.linkedin.com/feed/",
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                    )
                },
                allow_redirects=True,
                timeout=8,
            )
            final_url = (res.url or "").lower()
            if any(x in final_url for x in ("login", "uas/login", "authwall", "checkpoint")):
                return False
            title_snippet = (res.text[:2000] if res.text else "").lower()
            if "linkedin login" in title_snippet or "sign in | linkedin" in title_snippet:
                return False
            if res.status_code in (429, 999):
                return False
            return True
        except Exception as e:
            if "TooManyRedirects" in type(e).__name__ or "redirect" in str(e).lower():
                logger.warning("probe_li_at_valid hit redirect loop (revoked/expired LinkedIn session).")
                return False
            logger.debug(f"probe_li_at_valid transient error (deferring to browser): {e}")
            return True

    @staticmethod
    def mark_session_expired(reason: str = "redirected_to_login"):
        """Marks session_cookies.json as expired so dashboard status flips to 'LinkedIn: Update Key'."""
        session_file = os.path.join(BASE_DIR, "data", "session_cookies.json")
        if not os.path.exists(session_file):
            return
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                sdata = json.load(f)
            sdata["status"] = "expired"
            sdata["expired_reason"] = reason
            sdata["expired_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(sdata, f, indent=2)
        except Exception as e:
            logger.debug(f"Could not mark session_cookies.json expired: {e}")

    @staticmethod
    def _load_linkedin_credentials() -> tuple:
        """Loads explicit LinkedIn email/password from env vars or gitignored local credentials file."""
        email = (os.environ.get("LINKEDIN_EMAIL") or "").strip()
        password = os.environ.get("LINKEDIN_PASSWORD") or ""
        if email and password:
            return email, password
        cred_file = os.path.join(BASE_DIR, "data", "linkedin_credentials.json")
        if os.path.exists(cred_file):
            try:
                with open(cred_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                return (cdata.get("email") or "").strip(), (cdata.get("password") or "")
            except Exception:
                pass
        return "", ""

    def _export_active_cookies(self):
        """Exports the active browser context's cookies to data/session_cookies.json cleanly."""
        session_file = os.path.join(BASE_DIR, "data", "session_cookies.json")
        try:
            existing_other = []
            if os.path.exists(session_file):
                try:
                    with open(session_file, "r", encoding="utf-8") as f:
                        prev = json.load(f).get("cookies", [])
                    existing_other = [c for c in prev if "linkedin" not in (c.get("domain") or "").lower()]
                except Exception:
                    existing_other = []

            li_cookies = self.context.cookies(["https://www.linkedin.com"])
            merged = existing_other + li_cookies
            payload = {
                "status": "active",
                "exported_at": time.strftime("%a %b %d %H:%M:%S %Z %Y"),
                "cookies": merged,
            }
            os.makedirs(os.path.dirname(session_file), exist_ok=True)
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            logger.info(f"Saved {len(merged)} active session cookies to data/session_cookies.json.")
        except Exception as e:
            logger.warning(f"Could not export active cookies: {e}")

    def ensure_logged_in(self, page, timeout_sec: int = 300) -> bool:
        """
        Ensures LinkedIn is logged in:
        1. Reuses active Chrome/session li_at cookie if valid.
        2. If missing/expired, signs in with configured LinkedIn email & password credentials.
        3. Never bypasses CAPTCHAs/2FA checkpoints — pauses/reports cleanly if triggered.
        """
        cookies = self.context.cookies(["https://www.linkedin.com"])
        li_at_cookies = [c for c in cookies if c["name"] == "li_at" and c.get("value")]
        if li_at_cookies:
            if self.is_cdp or any(self.probe_li_at_valid(c["value"]) for c in li_at_cookies):
                logger.info("Session verified: User is logged in to LinkedIn (li_at cookie active).")
                return True
            logger.warning("Existing li_at cookie expired/revoked — refreshing via LinkedIn credentials login...")
            self.mark_session_expired("stale_li_at_refresh")

        # Clear stale LinkedIn cookies before fresh credential sign-in
        try:
            import re
            self.context.clear_cookies(domain=re.compile(r"linkedin\.com$"))
        except Exception:
            pass

        email, password = self._load_linkedin_credentials()
        if email and password:
            logger.info(f"Signing in to LinkedIn with configured account ({email})...")
            try:
                page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
                human_delay(1.2, 2.0)

                # Guard if already redirected to /feed by persistent profile
                if any(p in (page.url or "").lower() for p in ("/feed", "/mynetwork", "/in/", "/jobs")):
                    self._export_active_cookies()
                    return True

                import re
                user_inp = page.locator("input#username, input[name='session_key'], input[type='email'], input[autocomplete='username']").locator("visible=true").first
                pass_inp = page.locator("input#password, input[name='session_password'], input[type='password']").locator("visible=true").first
                submit_btn = page.locator("button").filter(has_text=re.compile(r"^\s*Sign in\s*$")).locator("visible=true").first
                if submit_btn.count() == 0:
                    submit_btn = page.locator("button[type='submit']").locator("visible=true").first

                if user_inp.count() > 0 and pass_inp.count() > 0:
                    user_inp.click()
                    page.keyboard.press("ControlOrMeta+a")
                    page.keyboard.press("Backspace")
                    user_inp.fill(email)
                    human_delay(0.4, 0.8)
                    pass_inp.click()
                    page.keyboard.press("ControlOrMeta+a")
                    page.keyboard.press("Backspace")
                    pass_inp.fill(password)
                    human_delay(0.5, 1.0)
                    if submit_btn.count() > 0:
                        submit_btn.click()
                    else:
                        pass_inp.press("Enter")

                    # Wait cleanly up to 15s for login result
                    for _ in range(15):
                        time.sleep(1.0)
                        cur_url = (page.url or "").lower()
                        try:
                            body_low = (page.locator("body").inner_text() or "").lower()
                            if "wrong email or password" in body_low or "couldn't find a linkedin account" in body_low:
                                logger.error("⚠️ LinkedIn rejected the configured email or password ('Wrong email or password'). Please double-check your LinkedIn credentials.")
                                return False
                        except Exception:
                            pass
                        if any(k in cur_url for k in ("checkpoint", "challenge", "captcha")):
                            logger.warning("⚠️ LinkedIn triggered a 2FA / checkpoint verification challenge during sign-in. Complete verification once cleanly in Chrome (not bypassed).")
                            self.mark_session_expired("checkpoint_verification_required")
                            if os.environ.get("DISPLAY") or timeout_sec > 20:
                                logger.info(f"Waiting up to {timeout_sec}s for manual verification in visible browser...")
                                break
                            return False
                        if any(p in cur_url for p in ("/feed", "/mynetwork", "/in/", "/jobs")):
                            cookies_now = self.context.cookies(["https://www.linkedin.com"])
                            if any(c["name"] == "li_at" and c.get("value") for c in cookies_now):
                                self._export_active_cookies()
                                logger.info("✅ LinkedIn credential login succeeded cleanly!")
                                return True

                    cur_url = (page.url or "").lower()
                    if any(k in cur_url for k in ("checkpoint", "challenge", "captcha")):
                        self.mark_session_expired("checkpoint_verification_required")
                        return False
                    cookies_now = self.context.cookies(["https://www.linkedin.com"])
                    if any(c["name"] == "li_at" and c.get("value") for c in cookies_now):
                        self._export_active_cookies()
                        logger.info("✅ LinkedIn credential login succeeded cleanly!")
                        return True
                    logger.warning(f"LinkedIn login landed on unexpected URL: {page.url}")
                    return False
            except Exception as e:
                logger.warning(f"Credential login attempt error: {e}")

        logger.info("Manual LinkedIn sign-in required — waiting up to timeout if browser is interactive...")
        if not os.environ.get("DISPLAY") and timeout_sec <= 20:
            return False

        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        start = time.time()
        while time.time() - start < timeout_sec:
            time.sleep(2)
            cookies = self.context.cookies(["https://www.linkedin.com"])
            cur_url = (page.url or "").lower()
            if any(c["name"] == "li_at" and c.get("value") for c in cookies) and not any(x in cur_url for x in ("/login", "/checkpoint", "/challenge")):
                self._export_active_cookies()
                logger.info("SUCCESS: Login detected! Authentication session saved.")
                time.sleep(1.5)
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
