"""
job_scanner.py - Scans LinkedIn Jobs for Analyst / APM roles, handles Easy Apply,
optimizes and uploads candidate resume, and routes Workday/Oracle/MNC jobs to manual review.
"""

import os
import re
import csv
import logging
import urllib.parse
from datetime import datetime
from urllib.parse import quote_plus
from browser_session import human_delay

logger = logging.getLogger(__name__)

MNC_OR_ATS_KEYWORDS = [
    "workday", "oracle", "taleo", "greenhouse", "lever", "icims",
    "deloitte", "pwc", "ey", "kpmg", "accenture", "google", "microsoft", "amazon",
    "meta", "apple", "godrej", "idfc", "infosys", "general mills", "swiggy",
    "zomato", "flipkart", "morgan stanley", "goldman sachs", "jpmorgan", "bain", "mckinsey"
]


def extract_real_url(href: str) -> str:
    if not href:
        return ""
    if "safety/go" in href and "url=" in href:
        m = re.search(r'[?&]url=([^&]+)', href)
        if m:
            return urllib.parse.unquote(m.group(1))
    return href


class JobScanner:
    def __init__(self, page, config: dict, state: dict, base_dir: str, log_cb=None):
        self.page = page
        self.config = config
        self.state = state
        self.base_dir = base_dir
        self.log_cb = log_cb
        self.data_dir = os.path.join(base_dir, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        self.manual_csv = os.path.join(self.data_dir, "manual_applications.csv")
        self.applied_csv = os.path.join(self.data_dir, "applied_jobs.csv")

    def _log(self, msg: str):
        logger.info(msg)
        if self.log_cb:
            try:
                self.log_cb(msg)
            except Exception:
                pass

    def run(self) -> dict:
        self._log("Starting LinkedIn Job Scanner & Application Router...")
        try:
            self.page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
        except Exception:
            pass
        target_roles = self.config.get("target_roles", ["Analyst", "Associate Product Manager"])
        location = self.config.get("location", "India")
        limits = self.config.get("limits", {})
        max_jobs = limits.get("max_jobs_evaluated_per_run", 15)
        max_easy_applies = limits.get("max_easy_applies_per_run", 3)
        max_daily_applies = limits.get("max_easy_applies_per_day", 12)
        dry_run = self.config.get("dry_run", False)

        today_str = datetime.now().strftime("%Y-%m-%d")
        if self.state.get("last_run_date") != today_str:
            self.state["last_run_date"] = today_str
            self.state["daily_apply_count"] = 0

        current_daily_count = self.state.get("daily_apply_count", 0)
        seen_job_ids = set(self.state.get("seen_job_ids", []))

        results = {
            "easy_applied": [],
            "manual_queued": []
        }

        easy_applies_this_run = 0
        jobs_evaluated_count = 0

        for role in target_roles[:3]:
            if jobs_evaluated_count >= max_jobs:
                break

            search_url = f"https://www.linkedin.com/jobs/search-results/?keywords={quote_plus(role)}&location={quote_plus(location)}"
            logger.info(f"Navigating to job search: '{role}' in '{location}'...")
            
            try:
                self.page.goto(search_url, wait_until="domcontentloaded")
                human_delay(3.5, 5.0)
            except Exception as e:
                logger.warning(f"Navigation warning: {e}")
                continue

            for job_idx in range(6):
                if jobs_evaluated_count >= max_jobs:
                    break

                job_info = self.page.evaluate('''() => {
                    let title = '';
                    const spans = Array.from(document.querySelectorAll('span, h1, h2, h3'));
                    for (let s of spans) {
                        const t = s.innerText ? s.innerText.trim() : '';
                        if (t && (t.toLowerCase().includes('analyst') || t.toLowerCase().includes('product') || t.toLowerCase().includes('manager')) && t.length < 80) {
                            title = t.replace('(Verified job)', '').trim();
                            break;
                        }
                    }
                    if (!title) {
                        const h1 = document.querySelector('h1');
                        if (h1) title = h1.innerText.trim();
                    }

                    const compLink = Array.from(document.querySelectorAll('a')).find(a => a.href && a.href.includes('/company/'));
                    const company = compLink ? compLink.innerText.trim() : 'Unknown Company';

                    const applyElement = Array.from(document.querySelectorAll('a, button')).find(el => {
                        const text = (el.innerText || '').toLowerCase();
                        const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                        return text.includes('apply') || aria.includes('apply');
                    });

                    let applyType = 'External';
                    let applyUrl = '';
                    if (applyElement) {
                        const text = (applyElement.innerText || '').trim();
                        if (text.includes('Easy Apply')) {
                            applyType = 'Easy Apply';
                        } else {
                            applyType = 'External';
                            applyUrl = applyElement.href || window.location.href;
                        }
                    }

                    return {
                        title: title || 'Analyst Role',
                        company: company,
                        applyType: applyType,
                        applyUrl: applyUrl,
                        url: window.location.href
                    };
                }''')

                title = job_info["title"]
                company = job_info["company"]
                apply_type = job_info["applyType"]
                external_url = extract_real_url(job_info["applyUrl"])
                job_url = job_info["url"]

                m = re.search(r'currentJobId=(\d+)', job_url) or re.search(r'/jobs/view/(\d+)', job_url)
                job_id = m.group(1) if m else str(abs(hash(title + company)))

                if job_id in seen_job_ids:
                    self._click_next()
                    continue

                seen_job_ids.add(job_id)
                jobs_evaluated_count += 1

                # Rule 1: Check if MNC or External ATS (Workday, Oracle, etc.)
                is_mnc = any(k in company.lower() or k in external_url.lower() for k in MNC_OR_ATS_KEYWORDS)

                if apply_type == "External" or is_mnc:
                    logger.info(f"[MANUAL QUEUE] MNC/Workday/External: '{title}' at '{company}'")
                    item = {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "job_id": job_id,
                        "title": title,
                        "company": company,
                        "location": location,
                        "job_url": job_url,
                        "direct_application_url": external_url or job_url,
                        "reason": f"External {company} Portal (Manual Submission Required)"
                    }
                    self._save_manual_job(item)
                    results["manual_queued"].append(item)

                else:
                    # Rule 2: Easy Apply available
                    if dry_run:
                        logger.info(f"[EASY APPLY - DRY RUN] Found: '{title}' at '{company}'")
                        results["easy_applied"].append({"title": title, "company": company, "url": job_url, "test_mode": True})
                    elif current_daily_count < max_daily_applies and easy_applies_this_run < max_easy_applies:
                        logger.info(f"[EASY APPLY - LIVE] Directly applying with optimized resume: '{title}' at '{company}'...")
                        applied = self._execute_direct_easy_apply(title, company, job_url)
                        if applied:
                            easy_applies_this_run += 1
                            current_daily_count += 1
                            self.state["daily_apply_count"] = current_daily_count
                            results["easy_applied"].append({"title": title, "company": company, "url": job_url, "test_mode": False})
                    else:
                        logger.info(f"[SAFETY CAP] Quota reached for Easy Apply today ({current_daily_count}/{max_daily_applies}). Queuing for next run.")
                        item = {
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "job_id": job_id,
                            "title": title,
                            "company": company,
                            "location": location,
                            "job_url": job_url,
                            "direct_application_url": job_url,
                            "reason": "Easy Apply Daily Safety Cap Reached"
                        }
                        self._save_manual_job(item)
                        results["manual_queued"].append(item)

                advanced = self._click_next()
                if not advanced:
                    break
                human_delay(2.5, 4.0)

        self.state["seen_job_ids"] = list(seen_job_ids)[-1000:]
        return results

    def _execute_direct_easy_apply(self, title: str, company: str, job_url: str) -> bool:
        """Executes the Easy Apply flow directly, uploading/selecting the optimized resume."""
        profile = self.config.get("candidate_profile", {})
        resume_path = profile.get("resume_path", "")

        try:
            # Click Easy Apply button
            apply_btn = self.page.locator("button:has-text('Easy Apply'), button[aria-label*='Easy Apply']").first
            if apply_btn.count() == 0 or not apply_btn.is_visible():
                return False

            apply_btn.click()
            human_delay(2.0, 3.0)

            modal = self.page.locator("div.jobs-easy-apply-modal, div[role='dialog']").first
            if modal.count() == 0:
                return False

            # Multi-step wizard handler (up to 7 steps)
            for step_i in range(7):
                # 1. Fill Phone if empty
                phone_input = modal.locator("input[id*='phoneNumber'], input[type='tel']").first
                if phone_input.count() > 0 and not phone_input.input_value():
                    phone = profile.get("phone", "")
                    if phone:
                        phone_input.fill(phone)

                # 2. Handle Resume Upload / Selection
                if resume_path and os.path.exists(resume_path):
                    # Check for file upload input
                    file_input = modal.locator("input[type='file']").first
                    if file_input.count() > 0:
                        logger.info(f"Uploading optimized resume: {os.path.basename(resume_path)}")
                        file_input.set_input_files(resume_path)
                        human_delay(1.5, 2.5)

                # 3. Handle Common Questions
                # Check for experience years inputs
                text_inputs = modal.locator("input[type='text'], input[type='number']").all()
                for inp in text_inputs:
                    try:
                        val = inp.input_value()
                        if not val:
                            # Default to 1 year of experience
                            inp.fill(profile.get("years_of_experience", "1"))
                    except Exception:
                        pass

                # Check for yes/no radio buttons (Authorization / Sponsorship)
                yes_radios = modal.locator("label:has-text('Yes')").all()
                for r in yes_radios:
                    try:
                        # Authorizations usually want Yes
                        r.click()
                    except Exception:
                        pass

                # 4. Check for 'Submit application' button
                submit_btn = modal.locator("button:has-text('Submit application'), button[aria-label='Submit application']").first
                if submit_btn.count() > 0 and submit_btn.is_visible():
                    submit_btn.click()
                    human_delay(2.5, 4.0)
                    logger.info(f"SUCCESS: Directly submitted Easy Apply for '{title}' at '{company}'!")
                    self._record_applied_job(title, company, job_url)
                    self._close_modal_if_open()
                    return True

                # 5. Check for Next or Review
                next_btn = modal.locator("button:has-text('Next'), button[aria-label='Continue to next step']").first
                review_btn = modal.locator("button:has-text('Review'), button[aria-label='Review your application']").first

                error_elements = modal.locator(".artdeco-inline-feedback--error").all()
                if error_elements:
                    logger.info("Encountered complex custom question requirement. Aborting auto-apply and routing to manual queue.")
                    self._cancel_easy_apply()
                    return False

                if next_btn.count() > 0 and next_btn.is_visible():
                    next_btn.click()
                    human_delay(1.2, 2.2)
                elif review_btn.count() > 0 and review_btn.is_visible():
                    review_btn.click()
                    human_delay(1.2, 2.2)
                else:
                    break

            self._cancel_easy_apply()
            return False

        except Exception as e:
            logger.warning(f"Error during Easy Apply execution: {e}")
            self._cancel_easy_apply()
            return False

    def _click_next(self) -> bool:
        try:
            return self.page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const nextBtn = btns.find(b => b.innerText.trim() === 'Next' || b.getAttribute('aria-label') === 'Next');
                if (nextBtn && !nextBtn.disabled) {
                    nextBtn.click();
                    return true;
                }
                return false;
            }''')
        except Exception:
            return False

    def _cancel_easy_apply(self):
        try:
            dismiss_btn = self.page.locator("button[aria-label='Dismiss'], button.artdeco-modal__dismiss").first
            if dismiss_btn.count() > 0:
                dismiss_btn.click()
                human_delay(0.5, 1.0)
                confirm_discard = self.page.locator("button[data-control-name='discard_application_confirm_btn'], button:has-text('Discard')").first
                if confirm_discard.count() > 0:
                    confirm_discard.click()
        except Exception:
            pass

    def _close_modal_if_open(self):
        try:
            close_btn = self.page.locator("button[aria-label='Dismiss']").first
            if close_btn.count() > 0 and close_btn.is_visible():
                close_btn.click()
        except Exception:
            pass

    def _save_manual_job(self, item: dict):
        file_exists = os.path.exists(self.manual_csv)
        with open(self.manual_csv, "a", newline="", encoding="utf-8") as f:
            fieldnames = ["timestamp", "job_id", "title", "company", "location", "job_url", "direct_application_url", "reason"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(item)

    def _record_applied_job(self, title: str, company: str, job_url: str):
        file_exists = os.path.exists(self.applied_csv)
        with open(self.applied_csv, "a", newline="", encoding="utf-8") as f:
            fieldnames = ["timestamp", "title", "company", "job_url"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "title": title,
                "company": company,
                "job_url": job_url
            })
