"""
referral_engine.py - Advanced Company People & Alumni Referral Engine.
Features:
1. Company Page Crawler (linkedin.com/company/{company}/people/):
   - Priority 1: Punjab Engineering College (PEC) Alumni working at the company
   - Priority 2: Product Management & Analytics domain team members in India
   - Priority 3: Technical Recruiters & Talent Acquisition
2. 1st-Degree Connection extraction
3. Multi-select outreach execution with tailored alumni referral messages
4. Full tracking in CSV and JSON
"""

import os
import re
import csv
import json
import logging
from datetime import datetime
from urllib.parse import quote_plus
from browser_session import BrowserManager, human_delay

logger = logging.getLogger("ReferralEngine")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTREACH_CSV = os.path.join(DATA_DIR, "outreach_tracker.csv")
OUTREACH_JSON = os.path.join(DATA_DIR, "outreach_tracker.json")

USER_COLLEGE = "Punjab Engineering College"
USER_COLLEGE_SHORT = "PEC"

DEFAULT_FIXED_REFERRAL_TEMPLATE = (
    "Hi {first_name}, hope you are doing well! I noticed you are working at {company}. "
    "As a fellow engineer from {college} exploring {target_role} opportunities, I would love to connect "
    "and see if you might be open to referring me for suitable openings at {company}. "
    "Would be grateful to learn from your experience!"
)

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DISPATCH_JSON = os.path.join(DATA_DIR, "resume_dispatches.json")

def get_templates() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            return cfg.get("templates", {})
    except Exception:
        return {}



class ReferralEngine:
    def __init__(self, browser_mgr: BrowserManager = None):
        self.browser_mgr = browser_mgr or BrowserManager(profile_name="linkedin")
        os.makedirs(DATA_DIR, exist_ok=True)

    def search_company_people(self, company: str, role: str = "Recruiter", prioritize_alumni: bool = True, limit: int = 15) -> list:
        """
        Navigates to the company's LinkedIn /people/ page:
        1. Searches for PEC / Punjab Engineering College alumni first (Tier 1)
        2. Searches for target roles (Analyst, Product Manager, Recruiter) in India (Tier 2/3)
        """
        context, page = self.browser_mgr.get_context_and_page(force_headless=True)
        try:
            try:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            except Exception:
                pass

            if not self.browser_mgr.ensure_logged_in(page):
                return []

            company_slug = company.strip().lower().replace(" ", "-").replace(".", "")
            results = []
            seen_urls = set()

            # Step A: Alumni Search on Company People Page
            if prioritize_alumni:
                alumni_url = f"https://www.linkedin.com/company/{company_slug}/people/?keywords={quote_plus(USER_COLLEGE)}"
                logger.info(f"Checking {company} for {USER_COLLEGE} alumni...")
                try:
                    page.goto(alumni_url, wait_until="domcontentloaded")
                    human_delay(3.5, 4.5)
                    alumni_found = self._extract_people_from_page(page, company, is_alumni=True)
                    for p in alumni_found:
                        if p["profile_url"] not in seen_urls:
                            seen_urls.add(p["profile_url"])
                            p["tier"] = "Tier 1: PEC Alumni"
                            p["priority"] = 1
                            results.append(p)
                    logger.info(f"Found {len(alumni_found)} PEC alumni at {company}!")
                except Exception as e:
                    logger.debug(f"Alumni search error: {e}")

            # Step B: Role & Recruiter Search
            role_query = f"{company} {role} India"
            search_url = f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(role_query)}"
            logger.info(f"Searching {role} at {company} (India)...")
            try:
                page.goto(search_url, wait_until="domcontentloaded")
                human_delay(3.0, 4.5)
                role_people = self._extract_search_results(page, company, role)
                for p in role_people:
                    if p["profile_url"] not in seen_urls:
                        seen_urls.add(p["profile_url"])
                        is_recruiter = any(k in p["headline"].lower() for k in ["recruiter", "talent", "hiring", "ta", "hr"])
                        p["tier"] = "Tier 3: Recruiter" if is_recruiter else "Tier 2: Role Match"
                        p["priority"] = 3 if is_recruiter else 2
                        results.append(p)
            except Exception as e:
                logger.debug(f"Role search error: {e}")

            # Sort by priority (Tier 1 Alumni first, then Role Matches, then Recruiters)
            results.sort(key=lambda x: x.get("priority", 2))
            return results[:limit]
        finally:
            self.browser_mgr.close()

    @staticmethod
    def _extract_cards_js() -> str:
        return '''() => {
            const results = [];
            const seen = new Set();
            const mainEl = document.querySelector('main') || document.body;
            const cardSelectors = [
                'div[data-view-name="search-entity-result-universal-template"]',
                'li.reusable-search__result-container',
                'div.entity-result',
                'li.org-people-profile-card',
                'div.org-people-profile-card',
                '[data-chameleon-result-urn]',
                'div.scaffold-finite-scroll__content li'
            ];
            let cards = [];
            for (const sel of cardSelectors) {
                const found = Array.from(mainEl.querySelectorAll(sel)).filter(el => !el.closest('aside, nav, header'));
                if (found.length > 0) {
                    cards = found;
                    break;
                }
            }
            if (cards.length === 0) {
                cards = Array.from(mainEl.querySelectorAll('li, [role="listitem"]'))
                    .filter(el => !el.closest('aside, nav, header') && el.querySelector("a[href*='/in/']"));
            }

            cards.forEach(card => {
                const allInLinks = Array.from(card.querySelectorAll("a[href*='/in/']")).filter(a => {
                    if (a.closest('.entity-result__insights, .reusable-search-simple-insight, .member-insights')) return false;
                    const txt = (a.innerText || '').trim();
                    if (!txt || txt.length < 3 || txt.length > 65) return false;
                    const lower = txt.toLowerCase();
                    if (
                        lower.includes('mutual connection') ||
                        lower.includes('works here') ||
                        lower.includes('view ') ||
                        lower.includes('linkedin member') ||
                        lower.includes('skip to')
                    ) return false;
                    return true;
                });
                const link = allInLinks.find(a => a.querySelector('span[aria-hidden="true"]')) || allInLinks[0];
                if (!link) return;

                const spanName = link.querySelector('span[aria-hidden="true"]');
                const rawName = ((spanName ? spanName.innerText : link.innerText) || '')
                    .trim().split('\\n')[0].replace(/•.*$/, '').trim();
                const href = link.href.split('?')[0].replace(/\\/+$/, '');
                if (!href || seen.has(href) || rawName.length < 3 || rawName.length > 55) return;

                const cardText = (card.innerText || '').replace(/\\s+/g, ' ').trim();
                if (!cardText || cardText.includes('Skip to search') || cardText.includes('0 notifications')) return;

                const subEl = card.querySelector('.entity-result__primary-subtitle, .artdeco-entity-lockup__subtitle, .t-14.t-black.t-normal');
                const sumEl = card.querySelector('.entity-result__summary, .entity-result__secondary-subtitle');
                const h1 = subEl ? (subEl.innerText || '').replace(/\\s+/g, ' ').trim() : '';
                const h2 = sumEl ? (sumEl.innerText || '').replace(/\\s+/g, ' ').trim() : '';
                const headline = [h1, h2].filter(Boolean).join(' · ') || cardText.substring(0, 160);

                let degree = '2nd/3rd';
                if (cardText.includes('• 1st') || cardText.includes('1st degree')) degree = '1st';
                else if (cardText.includes('• 2nd')) degree = '2nd';
                else if (cardText.includes('• 3rd')) degree = '3rd';

                seen.add(href);
                results.push({
                    name: rawName,
                    profile_url: href,
                    headline: headline.substring(0, 220),
                    full_card_text: cardText.substring(0, 400),
                    degree: degree,
                    is_connection: degree === '1st'
                });
            });
            return results;
        }'''

    def _extract_people_from_page(self, page, company: str, is_alumni: bool = False) -> list:
        people = page.evaluate(self._extract_cards_js())
        cleaned = []
        for p in people:
            p["company"] = company
            p["is_alumni"] = is_alumni
            p["degree"] = "PEC Alumni" if is_alumni else p.get("degree", "2nd/3rd")
            cleaned.append(p)
        return cleaned

    def _extract_search_results(self, page, company: str, role: str) -> list:
        people = page.evaluate(self._extract_cards_js())
        cleaned = []
        for p in people:
            p["company"] = company
            p["target_role"] = role
            cleaned.append(p)
        return cleaned

    def get_existing_connections(self, limit: int = 20) -> list:
        context, page = self.browser_mgr.get_context_and_page(force_headless=True)
        try:
            try:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            except Exception:
                pass

            if not self.browser_mgr.ensure_logged_in(page):
                return []

            try:
                page.goto("https://www.linkedin.com/mynetwork/invite-connect/connections/", wait_until="domcontentloaded")
                human_delay(3.0, 4.5)
            except Exception:
                return []

            connections = page.evaluate('''() => {
                const results = [];
                const seen = new Set();
                document.querySelectorAll("li, div").forEach(c => {
                    const link = c.querySelector("a[href*='/in/']");
                    if (link && link.innerText) {
                        const rawName = link.innerText.trim().split('\\n')[0];
                        const href = link.href.split('?')[0];
                        if (!seen.has(href) && rawName.length > 2 && rawName.length < 50 && !rawName.toLowerCase().includes('view') && !rawName.toLowerCase().includes('connect')) {
                            seen.add(href);
                            const p = c.querySelector('p, span.mn-connection-card__occupation, span');
                            results.push({
                                name: rawName,
                                profile_url: href,
                                headline: p ? p.innerText.trim() : 'Existing Connection',
                                degree: '1st',
                                is_connection: true,
                                tier: '1st Degree Connection'
                            });
                        }
                    }
                });
                return results;
            }''')

            return connections[:limit]
        finally:
            self.browser_mgr.close()

    def send_outreach_batch(self, people: list, connect_template: str = "", message_template: str = "", alumni_template: str = "", sender_name: str = "Ashutosh Bajpai", target_role: str = "Analyst / APM") -> list:
        context, page = self.browser_mgr.get_context_and_page(force_headless=True)
        try:
            try:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            except Exception:
                pass

            if not self.browser_mgr.ensure_logged_in(page):
                return []

            saved_tmpls = get_templates()
            if not message_template:
                message_template = saved_tmpls.get("referral_template", DEFAULT_FIXED_REFERRAL_TEMPLATE)
            if not alumni_template:
                alumni_template = saved_tmpls.get("alumni_template", DEFAULT_FIXED_REFERRAL_TEMPLATE)
            if not connect_template:
                connect_template = saved_tmpls.get("recruiter_template", DEFAULT_FIXED_REFERRAL_TEMPLATE)

            results = []
            for person in people:
                name = person.get("name", "Unknown")
                profile_url = person.get("profile_url", "")
                is_1st = person.get("is_connection", False) or person.get("degree") == "1st"
                is_alumni = person.get("is_alumni", False) or "Alumni" in person.get("tier", "")

                try:
                    page.goto(profile_url, wait_until="domcontentloaded")
                    human_delay(3.0, 4.5)

                    if is_1st:
                        msg_text = self._format_msg(message_template, person, sender_name, target_role)
                        sent = self._send_direct_message(page, msg_text)
                        action = "Direct Message"
                    else:
                        template_to_use = alumni_template if (is_alumni and alumni_template) else connect_template
                        note_text = self._format_msg(template_to_use, person, sender_name, target_role)[:300]
                        sent = self._send_connection_request(page, note_text)
                        action = "Alumni Connection Note" if is_alumni else "Connection Request"
                        msg_text = note_text

                    record = {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "name": name,
                        "company": person.get("company", "N/A"),
                        "headline": person.get("headline", ""),
                        "profile_url": profile_url,
                        "action_type": action,
                        "status": "Delivered" if sent else "Failed/Sent",
                        "message_text": msg_text
                    }
                    self._record_outreach(record)
                    results.append(record)
                    human_delay(3.5, 5.5)

                except Exception as e:
                    results.append({"name": name, "status": f"Error: {e}"})

            return results
        finally:
            self.browser_mgr.close()

    def _format_msg(self, template: str, person: dict, sender_name: str, target_role: str) -> str:
        first = person.get("name", "there").split()[0]
        return template.replace("{first_name}", first)\
                       .replace("{name}", person.get("name", ""))\
                       .replace("{company}", person.get("company", "your company"))\
                       .replace("{target_role}", target_role)\
                       .replace("{college}", USER_COLLEGE_SHORT)\
                       .replace("{my_name}", sender_name).strip()

    def _send_direct_message(self, page, message_text: str) -> bool:
        try:
            msg_btn = page.locator("button:has-text('Message'), a:has-text('Message')").first
            if msg_btn.count() == 0 or not msg_btn.is_visible():
                return False
            msg_btn.click()
            human_delay(1.5, 2.5)

            chat_box = page.locator("div.msg-form__contenteditable, div[role='textbox']").first
            if chat_box.count() == 0:
                return False
            chat_box.fill(message_text)
            human_delay(1.0, 1.5)

            send_btn = page.locator("button.msg-form__send-button, button[type='submit']:has-text('Send')").first
            if send_btn.count() > 0 and send_btn.is_visible():
                send_btn.click()
                human_delay(1.5, 2.0)
                return True
            return False
        except Exception:
            return False

    def _send_connection_request(self, page, note_text: str = "") -> bool:
        """
        Sends connection request.
        If note_text is empty (default), sends clean connection request WITHOUT any note.
        Only adds a note if note_text is explicitly provided.
        """
        try:
            connect_btn = page.locator("button:has-text('Connect'), button[aria-label*='Invite'][aria-label*='to connect']").first
            if connect_btn.count() == 0 or not connect_btn.is_visible():
                more_btn = page.locator("main section button:has-text('More'), main button[aria-label='More actions']").first
                if more_btn.count() > 0 and more_btn.is_visible():
                    more_btn.click()
                    human_delay(0.8, 1.5)
                    connect_btn = page.locator("div.artdeco-dropdown__content button:has-text('Connect'), [role='menuitem']:has-text('Connect')").first

            if connect_btn.count() == 0:
                return False

            connect_btn.click()
            human_delay(1.5, 2.5)

            # Option A: Clean connection request with NO note (User requested: connection request only)
            if not note_text:
                send_no_note = page.locator("button:has-text('Send without a note'), button[aria-label*='Send without a note'], button:has-text('Send now'), button[aria-label='Send now']").first
                if send_no_note.count() > 0 and send_no_note.is_visible():
                    send_no_note.click()
                    human_delay(1.5, 2.0)
                    return True

            # Option B: Add a note only when note_text is explicitly passed
            if note_text:
                add_note_btn = page.locator("button:has-text('Add a note'), button[aria-label='Add a note']").first
                if add_note_btn.count() > 0 and add_note_btn.is_visible():
                    add_note_btn.click()
                    human_delay(0.8, 1.5)
                    textarea = page.locator("textarea[name='message'], textarea#custom-message").first
                    if textarea.count() > 0:
                        textarea.fill(note_text)
                        human_delay(1.0, 1.5)

            send_btn = page.locator("button:has-text('Send'), button[aria-label='Send invitation'], button[aria-label='Send now']").first
            if send_btn.count() > 0 and send_btn.is_visible():
                send_btn.click()
                human_delay(1.5, 2.0)
                return True
            return False
        except Exception:
            return False

    def _record_outreach(self, item: dict):
        file_exists = os.path.exists(OUTREACH_CSV)
        with open(OUTREACH_CSV, "a", newline="", encoding="utf-8") as f:
            fieldnames = ["timestamp", "name", "company", "headline", "profile_url", "action_type", "status", "message_text"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(item)

        history = self.get_history()
        history.append(item)
        with open(OUTREACH_JSON, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

    def get_history(self) -> list:
        if os.path.exists(OUTREACH_JSON):
            try:
                with open(OUTREACH_JSON, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def get_dispatches(self) -> list:
        if os.path.exists(DISPATCH_JSON):
            try:
                with open(DISPATCH_JSON, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _record_dispatch(self, dispatch_record: dict):
        dispatches = self.get_dispatches()
        dispatches.append(dispatch_record)
        with open(DISPATCH_JSON, "w", encoding="utf-8") as f:
            json.dump(dispatches, f, indent=2)

    def check_inbox_and_dispatch_resume(self, max_threads: int = 15) -> list:
        """
        Two-Phase Referral Engine:
        Scans recent LinkedIn messaging threads. If a contact has replied requesting a resume
        ('share your resume', 'send CV', etc.), attaches the updated master resume file and sends it.
        """
        # Determine master resume file
        resume_path = ""
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                resume_path = cfg.get("candidate_profile", {}).get("resume_path", "")
        except Exception:
            pass

        if not resume_path or not os.path.exists(resume_path):
            logger.warning(f"Master resume file not found or invalid: {resume_path}")
            return [{"status": "Skipped", "reason": "No valid master resume configured"}]

        context, page = self.browser_mgr.get_context_and_page(force_headless=True)
        try:
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
        except Exception:
            pass
        if not self.browser_mgr.ensure_logged_in(page):
            return [{"status": "Failed", "reason": "LinkedIn login failed"}]

        logger.info("Scanning LinkedIn messaging inbox for resume requests...")
        dispatched_items = []
        already_dispatched = {d.get("thread_id") or d.get("contact_name") for d in self.get_dispatches()}

        keywords = [
            "share your resume", "share resume", "send your resume", "send resume",
            "send your cv", "send cv", "share your cv", "share cv",
            "forward your resume", "drop your resume", "drop your cv",
            "attach your resume", "send across your resume", "pass your resume",
            "share it with me", "send it over"
        ]

        try:
            page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
            human_delay(3.5, 4.5)

            # Extract recent conversation elements
            conversations = page.locator("li.msg-conversation-listitem, li.msg-conversation-card")
            count = min(conversations.count(), max_threads)
            logger.info(f"Found {conversations.count()} active messaging threads. Checking top {count}...")

            for i in range(count):
                try:
                    conv = conversations.nth(i)
                    conv.scroll_into_view_if_needed()
                    conv.click()
                    human_delay(2.0, 3.0)

                    # Extract participant name
                    name_el = page.locator("h2.msg-entity-lockup__title, h2[data-anonymize='person-name'], .msg-title-bar__title").first
                    contact_name = name_el.inner_text().strip() if name_el.count() > 0 else f"Contact_{i}"

                    if contact_name in already_dispatched:
                        logger.info(f"Resume already dispatched to {contact_name}. Skipping.")
                        continue

                    # Read all messages in thread
                    messages_text = page.locator(".msg-s-message-list-container, .msg-s-message-group").all_inner_texts()
                    full_text = " ".join(messages_text).lower()

                    # Check for resume request keywords
                    matched_kw = next((kw for kw in keywords if kw in full_text), None)
                    if not matched_kw:
                        continue

                    # Verify if candidate already sent a reply after request
                    # If match found, compose dispatch
                    first_name = contact_name.split()[0] if contact_name else "there"
                    saved_tmpls = get_templates()
                    custom_resume_tmpl = saved_tmpls.get("resume_dispatch_template") or (
                        "Hi {first_name}, thank you so much for offering to refer me! "
                        "I have attached my updated resume ({resume_filename}). Really appreciate your time and support!"
                    )
                    reply_msg = custom_resume_tmpl.replace("{first_name}", first_name)\
                                                  .replace("{resume_filename}", os.path.basename(resume_path))\
                                                  .replace("{my_name}", "Ashutosh Bajpai")

                    logger.info(f"Trigger matched ('{matched_kw}') for {contact_name}! Dispatching resume...")

                    # Attach resume file
                    file_input = page.locator("input[type='file'].msg-form__attachment-upload-input, input[type='file']").first
                    if file_input.count() > 0:
                        file_input.set_input_files(resume_path)
                        human_delay(2.5, 3.5)

                    # Enter reply message
                    text_box = page.locator("div.msg-form__contenteditable, div[role='textbox']").first
                    if text_box.count() > 0:
                        text_box.fill(reply_msg)
                        human_delay(1.5, 2.0)

                    # Click Send
                    send_btn = page.locator("button.msg-form__send-button, button[type='submit']:has-text('Send')").first
                    if send_btn.count() > 0 and send_btn.is_visible():
                        send_btn.click()
                        human_delay(2.0, 3.0)

                        record = {
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "contact_name": contact_name,
                            "matched_keyword": matched_kw,
                            "resume_sent": os.path.basename(resume_path),
                            "status": "Delivered",
                            "message": reply_msg
                        }
                        self._record_dispatch(record)
                        self._record_outreach({
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "name": contact_name,
                            "company": "LinkedIn Connection",
                            "headline": "Referral Partner",
                            "profile_url": "https://www.linkedin.com/messaging/",
                            "action_type": "Resume Dispatched (Phase 2)",
                            "status": "Delivered",
                            "message_text": reply_msg
                        })
                        dispatched_items.append(record)
                        logger.info(f"SUCCESS: Resume sent to {contact_name}!")
                        human_delay(3.0, 4.0)

                except Exception as inner_e:
                    logger.warning(f"Error inspecting thread {i}: {inner_e}")
                    continue

        except Exception as e:
            logger.error(f"Error scanning inbox: {e}")
        finally:
            self.browser_mgr.close()

        return dispatched_items
