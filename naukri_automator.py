"""
naukri_automator.py - Automation engine for Naukri.com
Features:
1. Daily Profile Recency Boost: slightly edits resume headline daily to keep "Profile Updated: Today"
   (Naukri recruiter algorithm ranks recently updated profiles at the very top of search results).
2. High-volume Job Search & Apply: targets 50+ applications across Analyst & APM roles.
3. Workday/Oracle/MNC External Application Routing to the Manual Review Queue.
"""

import os
import re
import csv
import json
import logging
from datetime import datetime
from urllib.parse import quote_plus
from browser_session import BrowserManager, human_delay

logger = logging.getLogger("NaukriAutomator")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
NAUKRI_APPLIED_CSV = os.path.join(DATA_DIR, "naukri_applied_jobs.csv")
NAUKRI_BOOST_LOG = os.path.join(DATA_DIR, "naukri_boost_log.json")
MANUAL_CSV = os.path.join(DATA_DIR, "manual_applications.csv")


class NaukriAutomator:
    def __init__(self, browser_mgr: BrowserManager = None):
        self.browser_mgr = browser_mgr or BrowserManager()
        os.makedirs(DATA_DIR, exist_ok=True)

    def boost_profile(self) -> dict:
        """
        Naukri Recruiter Boost Algorithm:
        Recruiter searches heavily filter candidates by 'Active / Updated in last 24h'.
        This method edits the resume headline slightly (adding or removing a trailing period)
        and saves it, triggering Naukri's system to display 'Updated: Today'.
        """
        logger.info("Starting Naukri Daily Profile Recency Boost...")
        headed_mode = False if os.environ.get("DISPLAY") else None
        context, page = self.browser_mgr.get_context_and_page(force_headless=headed_mode)

        try:
            try:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            except Exception:
                pass
            try:
                page.goto("https://www.naukri.com/mnjuser/profile", wait_until="domcontentloaded", timeout=30000)
            except Exception:
                page.goto("https://www.naukri.com/mnjuser/profile")
            
            human_delay(4.0, 6.0)

            # Check if login is required or blocked
            if "access denied" in page.title().lower():
                logger.error(f"Naukri Bot Challenge detected: '{page.title()}' at {page.url}")
                record = {"status": "Access Denied (Bot Challenge)", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                self._save_boost_log(record)
                return record

            if "login" in page.url or "nlogin" in page.url:
                logger.warning("Naukri login required. Current URL: " + page.url)
                record = {"status": "Login Required", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                self._save_boost_log(record)
                return record

            # Scroll down to trigger lazy-loading of Profile Summary & Headline components
            logger.info("Scrolling profile to trigger lazy-loaded sections...")
            for scroll_pos in [200, 500, 800]:
                try:
                    page.evaluate(f"window.scrollTo(0, {scroll_pos});")
                    human_delay(0.8, 1.2)
                except Exception:
                    pass

            # Wait for any profile card or edit pencil to mount in the DOM
            try:
                page.wait_for_selector(".profileSummary, div.resumeHeadline, div.widgetHead, span.new-pencil, span.edit", timeout=12000)
            except Exception:
                pass

            # Locate Profile Summary / Resume Headline Edit button
            logger.info("Locating Profile Summary / Headline section on Naukri profile...")
            
            # 1. Primary: Profile Summary pencil
            pencil = page.locator(".profileSummary span.new-pencil, .profileSummary img[alt='pencil'], div.profileSummary span.new-pencil, div.widgetHead:has-text('Profile summary') span.edit, span[data-ga-track*='Profile Summary']").first
            if pencil.count() > 0 and pencil.is_visible():
                logger.info("Found Profile Summary edit pencil. Clicking...")
                pencil.scroll_into_view_if_needed()
                human_delay(1.0, 1.5)
                pencil.click()
                human_delay(1.5, 2.5)

                summary_textarea = page.locator("textarea#summary, textarea.fn-inp-md, textarea[name='summary']").first
                if summary_textarea.count() > 0:
                    current_val = summary_textarea.input_value().strip()
                    # Recency hack: toggle trailing period
                    new_val = current_val[:-1] if current_val.endswith(".") else current_val + "."
                    logger.info(f"Toggling summary trailing period: {new_val[-30:]}")
                    summary_textarea.fill(new_val)
                    human_delay(1.0, 2.0)

                    save_btn = page.locator("button.btn-blue:has-text('Save'), button:has-text('Save'), form button[type='submit']").first
                    if save_btn.count() > 0:
                        save_btn.click()
                        human_delay(2.5, 3.5)
                        logger.info("SUCCESS: Profile Summary updated and saved! Naukri profile is now marked 'Updated Today'.")
                        record = {
                            "status": "Success",
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "action": "Toggled Profile Summary period",
                            "headline_preview": new_val[:120]
                        }
                        self._save_boost_log(record)
                        return record

            # 2. Fallback: Resume headline widget
            edit_btn = page.locator("div.resumeHeadline span.edit, span[data-ga-track*='Resume Headline'], div.widgetHead:has-text('Resume headline') span.edit, div.resumeHeadline span.new-pencil, span.icon.edit").first
            if edit_btn.count() > 0 and edit_btn.is_visible():
                logger.info("Found Resume Headline edit button. Clicking...")
                edit_btn.scroll_into_view_if_needed()
                human_delay(1.0, 1.5)
                edit_btn.click()
                human_delay(1.5, 2.5)

                textarea = page.locator("textarea#resumeHeadlineTxt, div.resumeHeadline textarea, textarea.resumeHeadlineTxt").first
                if textarea.count() > 0:
                    current_val = textarea.input_value().strip()
                    new_val = current_val[:-1] if current_val.endswith(".") else current_val + "."
                    textarea.fill(new_val)
                    human_delay(1.0, 2.0)

                    save_btn = page.locator("button:has-text('Save'), div.action button.btn-dark-ot, button[type='submit']:has-text('Save')").first
                    if save_btn.count() > 0:
                        save_btn.click()
                        human_delay(2.0, 3.0)
                        logger.info("SUCCESS: Naukri Profile Headline updated and saved. Profile marked 'Updated Today'!")
                        record = {
                            "status": "Success",
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "action": "Toggled headline period",
                            "headline_preview": new_val[:120]
                        }
                        self._save_boost_log(record)
                        return record

            # Capture debug screenshot for review
            debug_shot = os.path.join(DATA_DIR, "naukri_profile_screen.png")
            try:
                page.screenshot(path=debug_shot, full_page=False)
                logger.info(f"Captured debug screenshot at {debug_shot}")
            except Exception:
                pass

            logger.warning(f"Could not interact with headline or summary edit button. Current page title: {page.title()}, URL: {page.url}")
            record = {"status": "Headline Element Not Found", "url": page.url, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            self._save_boost_log(record)
            return record

        except Exception as e:
            logger.error(f"Error during Naukri profile boost: {e}")
            return {"status": f"Error: {e}", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        finally:
            self.browser_mgr.close()

    def upload_resume(self, resume_path: str) -> dict:
        """Uploads a new resume directly to the candidate's Naukri profile."""
        if not os.path.exists(resume_path):
            return {"status": "Error", "message": f"File not found: {resume_path}"}

        logger.info(f"Uploading new resume to Naukri: {os.path.basename(resume_path)}...")
        context, page = self.browser_mgr.get_context_and_page()

        try:
            page.goto("https://www.naukri.com/mnjuser/profile", wait_until="domcontentloaded")
            human_delay(3.5, 4.5)

            file_input = page.locator("input[type='file'].upload-input, input[type='file']").first
            if file_input.count() > 0:
                file_input.set_input_files(resume_path)
                human_delay(3.0, 5.0)

                # Wait for upload confirmation toast
                logger.info("Resume file set into Naukri upload input. Waiting for confirmation...")
                human_delay(3.0, 4.0)

                # Record boost
                record = {
                    "status": "Success",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "action": f"Uploaded new resume: {os.path.basename(resume_path)}",
                    "headline_preview": f"Resume updated to {os.path.basename(resume_path)}"
                }
                self._save_boost_log(record)
                return {"status": "Success", "message": f"Uploaded {os.path.basename(resume_path)} to Naukri"}

            return {"status": "Failed", "message": "Naukri upload input not found"}

        except Exception as e:
            logger.error(f"Error uploading resume to Naukri: {e}")
            return {"status": "Error", "message": str(e)}
        finally:
            self.browser_mgr.close()

    def apply_jobs(self, target_roles: list = None, daily_target: int = 50) -> dict:
        """
        Searches Naukri for target roles and applies directly (up to daily_target, 50+).
        External company site / Workday / Oracle / MNC redirects are logged to the manual queue.
        """
        if not target_roles:
            target_roles = ["Analyst", "Data Analyst", "Business Analyst", "Associate Product Manager", "Product Manager"]

        logger.info(f"Starting Naukri High-Volume Auto-Apply (Target: {daily_target} applications)...")
        headed_mode = False if os.environ.get("DISPLAY") else None
        context, page = self.browser_mgr.get_context_and_page(force_headless=headed_mode)

        applied_list = []
        manual_list = []
        seen_job_urls = self._get_seen_urls()

        try:
            try:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            except Exception:
                pass

            for role in target_roles:
                if len(applied_list) >= daily_target:
                    break

                search_url = f"https://www.naukri.com/{quote_plus(role.lower().replace(' ', '-'))}-jobs?k={quote_plus(role)}"
                logger.info(f"Navigating to Naukri search for '{role}'...")
                
                try:
                    page.goto(search_url, wait_until="domcontentloaded")
                    human_delay(3.5, 5.0)
                except Exception as e:
                    logger.warning(f"Error loading Naukri URL: {e}")
                    continue

                if "access denied" in page.title().lower():
                    logger.error(f"Naukri bot protection blocked access (Title: '{page.title()}').")
                    continue

                for page_num in range(1, 4):  # Check up to 3 pages per role
                    if len(applied_list) >= daily_target:
                        break

                    # Wait for job cards or listings to render in DOM
                    try:
                        page.wait_for_selector('.cust-job-tuple, .srp-jobtuple-wrapper, article.jobTuple, div[data-job-id], a[href*="/job-listings"]', timeout=10000)
                    except Exception:
                        pass

                    # Extract job tuples with resilient fallback
                    jobs_data = page.evaluate('''() => {
                        let tuples = Array.from(document.querySelectorAll('.cust-job-tuple, .srp-jobtuple-wrapper, article.jobTuple, div[data-job-id]'));
                        if (tuples.length === 0) {
                            const anchors = Array.from(document.querySelectorAll('a[href*="/job-listings"]')).filter(a => a.innerText.trim().length > 3);
                            return anchors.map(a => ({
                                title: a.innerText.trim(),
                                url: a.href,
                                company: 'Company',
                                experience: '',
                                location: 'India'
                            }));
                        }
                        return tuples.map(t => {
                            const titleEl = t.querySelector('a.title, .job-title, a[href*="/job-listings"]');
                            const compEl = t.querySelector('a.comp-name, .company-name, .subTitle');
                            const expEl = t.querySelector('.exp-wrap, .experience, .exp');
                            const locEl = t.querySelector('.loc-wrap, .location, .loc');
                            return {
                                title: titleEl ? titleEl.innerText.trim() : 'Analyst Role',
                                url: titleEl ? titleEl.href : '',
                                company: compEl ? compEl.innerText.trim() : 'Company',
                                experience: expEl ? expEl.innerText.trim() : '',
                                location: locEl ? locEl.innerText.trim() : ''
                            };
                        });
                    }''')

                    logger.info(f"Page {page_num}: Found {len(jobs_data)} job postings for '{role}'.")

                    for j in jobs_data:
                        if len(applied_list) >= daily_target:
                            break

                        job_url = j.get("url", "")
                        title = j.get("title", "Analyst Role")
                        company = j.get("company", "Company")

                        if not job_url or job_url in seen_job_urls:
                            continue

                        seen_job_urls.add(job_url)

                        # Open Job Listing
                        try:
                            page.goto(job_url, wait_until="domcontentloaded")
                            human_delay(2.0, 3.5)

                            # Check for Apply Button
                            apply_btn = page.locator("button#apply-button, button:has-text('Apply'), a:has-text('Apply on company site')").first
                            if apply_btn.count() == 0 or not apply_btn.is_visible():
                                continue

                            btn_text = apply_btn.inner_text().strip().lower()

                            # If it redirects to company site / Workday / Oracle / MNC:
                            if "company site" in btn_text or "external" in btn_text:
                                logger.info(f"[NAUKRI MANUAL QUEUE] MNC / External Redirect: '{title}' at '{company}'")
                                item = {
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "job_id": str(abs(hash(job_url))),
                                    "title": title,
                                    "company": company,
                                    "location": j.get("location", "India"),
                                    "job_url": job_url,
                                    "direct_application_url": job_url,
                                    "reason": f"Naukri External {company} Site (Manual Submission Required)"
                                }
                                self._save_manual_job(item)
                                manual_list.append(item)

                            else:
                                # Direct Apply on Naukri
                                logger.info(f"[NAUKRI APPLY] Directly applying to '{title}' at '{company}'...")
                                apply_btn.click()
                                human_delay(2.0, 3.5)

                                # Handle screening questionnaire or confirmation popup
                                applied_ok, reason = self._handle_naukri_modals(page)
                                if not applied_ok:
                                    logger.info(f"[NAUKRI MANUAL QUEUE] Screening Questionnaire requires manual input: '{title}' at '{company}' -> {reason}")
                                    item = {
                                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        "job_id": str(abs(hash(job_url))),
                                        "title": title,
                                        "company": company,
                                        "location": j.get("location", "India"),
                                        "job_url": job_url,
                                        "direct_application_url": job_url,
                                        "reason": f"Naukri Questionnaire: {reason}"
                                    }
                                    self._save_manual_job(item)
                                    manual_list.append(item)
                                else:
                                    record = {
                                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        "title": title,
                                        "company": company,
                                        "experience": j.get("experience", ""),
                                        "location": j.get("location", ""),
                                        "job_url": job_url
                                    }
                                    self._save_naukri_applied(record)
                                    applied_list.append(record)
                                    logger.info(f"SUCCESS: Submitted Naukri application ({len(applied_list)}/{daily_target})!")

                                human_delay(1.5, 3.0)

                        except Exception as e:
                            logger.debug(f"Error applying to {title}: {e}")
                            continue

                    # Try to click next page on Naukri
                    next_btn = page.locator("a:has-text('Next'), a.fright.fs14.btn-secondary").first
                    if next_btn.count() > 0 and next_btn.is_visible():
                        next_btn.click()
                        human_delay(3.0, 4.5)
                    else:
                        break

            return {
                "applied_count": len(applied_list),
                "manual_queued_count": len(manual_list),
                "applied_jobs": applied_list,
                "manual_jobs": manual_list
            }

        except Exception as e:
            logger.error(f"Error during Naukri auto-apply: {e}")
            return {"applied_count": len(applied_list), "manual_queued_count": len(manual_list)}
        finally:
            self.browser_mgr.close()

    def _handle_naukri_modals(self, page) -> tuple:
        """
        Detects Naukri screening drawers, chatbots, or questionnaire modals.
        Attempts to auto-fill standard questions based on candidate profile.
        Returns:
            (True, "Applied Directly") if no modal or successfully auto-completed.
            (False, reason) if complex questionnaire requires manual intervention.
        """
        try:
            # 1. Check if questionnaire/drawer exists
            drawer = page.locator("div.drawer-wrapper, div.apply-message, div.chatbot-container, div[class*='drawer'], div[class*='questionnaire']").first
            if drawer.count() == 0 or not drawer.is_visible():
                return True, "Direct Submit"

            logger.info("Naukri screening questionnaire detected! Analyzing questions...")
            human_delay(1.5, 2.5)

            # Check for essay / subjective textareas
            textareas = drawer.locator("textarea").all()
            if len(textareas) > 1:
                return False, "Complex Multi-Question Essay/Subjective Form"

            # Fill text/number inputs
            inputs = drawer.locator("input[type='text'], input[type='number'], input:not([type])").all()
            for inp in inputs:
                try:
                    if not inp.is_visible():
                        continue
                    curr_val = inp.input_value().strip()
                    if curr_val:
                        continue

                    # Evaluate context from placeholder, name, or parent label
                    label_text = page.evaluate('''(el) => {
                        const lbl = el.closest('div.input-field, div.form-group, div')?.innerText || '';
                        return (lbl + ' ' + (el.placeholder || '') + ' ' + (el.name || '')).toLowerCase();
                    }''', inp.element_handle())

                    if any(k in label_text for k in ["experience", "years", "yr"]):
                        inp.fill("1")
                    elif any(k in label_text for k in ["ctc", "salary"]):
                        inp.fill("800000" if "expected" in label_text else "0")
                    elif any(k in label_text for k in ["notice", "days"]):
                        inp.fill("15")
                    elif any(k in label_text for k in ["city", "location"]):
                        inp.fill("Mumbai")
                    elif any(k in label_text for k in ["college", "university"]):
                        inp.fill("Punjab Engineering College")
                    else:
                        inp.fill("1")
                    human_delay(0.3, 0.6)
                except Exception:
                    pass

            # Handle Radio Buttons / Checkboxes (select Yes or Immediate)
            radios = drawer.locator("input[type='radio'], input[type='checkbox']").all()
            for r in radios:
                try:
                    r_text = page.evaluate('''(el) => {
                        return (el.parentElement?.innerText || '').toLowerCase();
                    }''', r.element_handle())
                    if any(k in r_text for k in ["yes", "agree", "immediate", "full time"]):
                        r.check()
                        human_delay(0.2, 0.5)
                except Exception:
                    pass

            # Handle Dropdowns
            dropdowns = drawer.locator("select").all()
            for dd in dropdowns:
                try:
                    options = dd.locator("option").all()
                    if len(options) > 1:
                        options[1].click()
                except Exception:
                    pass

            # Click Submit / Apply in modal
            modal_submit = drawer.locator("button:has-text('Apply and continue'), button:has-text('Submit'), button:has-text('Save and apply'), button[type='submit']").first
            if modal_submit.count() > 0 and modal_submit.is_visible():
                modal_submit.click()
                human_delay(2.5, 3.5)

                # If drawer is still open and has error message, manual intervention is needed
                if drawer.is_visible():
                    err = drawer.locator("span.error, div.error-message, p.error, .mandatory").first
                    if err.count() > 0 and err.is_visible():
                        err_text = err.inner_text().strip()[:60]
                        logger.warning(f"Questionnaire has unfilled mandatory requirement: {err_text}")
                        return False, f"Mandatory Requirement: {err_text}"

                return True, "Questionnaire Auto-Filled & Submitted"

            return True, "Modal Submitted"

        except Exception as e:
            logger.warning(f"Error handling modal: {e}")
            return False, f"Questionnaire Error: {e}"

    def _save_naukri_applied(self, record: dict):
        file_exists = os.path.exists(NAUKRI_APPLIED_CSV)
        with open(NAUKRI_APPLIED_CSV, "a", newline="", encoding="utf-8") as f:
            fieldnames = ["timestamp", "title", "company", "experience", "location", "job_url"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(record)

    def _save_manual_job(self, item: dict):
        file_exists = os.path.exists(MANUAL_CSV)
        with open(MANUAL_CSV, "a", newline="", encoding="utf-8") as f:
            fieldnames = ["timestamp", "job_id", "title", "company", "location", "job_url", "direct_application_url", "reason"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(item)

    def _save_boost_log(self, record: dict):
        history = []
        if os.path.exists(NAUKRI_BOOST_LOG):
            try:
                with open(NAUKRI_BOOST_LOG, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                pass
        history.append(record)
        with open(NAUKRI_BOOST_LOG, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

    def _get_seen_urls(self) -> set:
        seen = set()
        if os.path.exists(NAUKRI_APPLIED_CSV):
            try:
                with open(NAUKRI_APPLIED_CSV, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        seen.add(r.get("job_url", ""))
            except Exception:
                pass
        return seen

    def get_boost_status(self) -> dict:
        if os.path.exists(NAUKRI_BOOST_LOG):
            try:
                with open(NAUKRI_BOOST_LOG, "r", encoding="utf-8") as f:
                    history = json.load(f)
                    if history:
                        return history[-1]
            except Exception:
                pass
        return {"status": "Never boosted", "timestamp": "N/A"}
