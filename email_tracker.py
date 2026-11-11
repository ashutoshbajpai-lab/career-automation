"""
email_tracker.py - Full Inbox Subject-Line Intelligence Scanner.
Scans the user's primary Gmail inbox, filters career & recruitment emails,
and categorizes them into:
1. Exam / Assessment / Next Steps (CBT, Admit Card, Test links)
2. Active Applications Tracked (SS&C, Smartstream, JPMorgan, mCaffeine, etc.)
3. Outbound Sent Applications (Kotak, APM applications)
4. High-Match Recruiter Invites (Zepto, Barclays, EY, Capgemini, Dentsu)
"""

import os
import re
import json
import logging
from datetime import datetime
from browser_session import BrowserManager, human_delay

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("EmailTracker")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
EMAIL_INTEL_JSON = os.path.join(DATA_DIR, "email_intelligence.json")
PASSED_OPPORTUNITIES_JSON = os.path.join(DATA_DIR, "screening_passed_opportunities.json")


class EmailTracker:
    def __init__(self, browser_mgr: BrowserManager = None):
        self.browser_mgr = browser_mgr or BrowserManager(profile_name="gmail")
        os.makedirs(DATA_DIR, exist_ok=True)

    def scan_full_inbox(self) -> list:
        logger.info("Opening Gmail Inbox to analyze all subject lines...")
        context, page = self.browser_mgr.get_context_and_page(force_headless=True)

        try:
            try:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            except Exception:
                pass
            page.goto("https://mail.google.com/mail/u/0/#inbox", wait_until="domcontentloaded")
            human_delay(5.0, 6.5)

            if any(x in (page.url or "").lower() for x in ("accounts.google.com", "signin", "ServiceLogin".lower())):
                logger.warning("Gmail session requires sign-in; preserving previously saved email intelligence.")
                return self.get_saved_intel()

            # Extract all inbox rows
            raw_emails = page.evaluate('''() => {
                const rows = Array.from(document.querySelectorAll('tr[role="row"], tr.zA'));
                return rows.map((r, idx) => {
                    const senderEl = r.querySelector('.zF, .bA, span[email], .yP');
                    const subjectEl = r.querySelector('.bog, span.bqe, .y6');
                    const snippetEl = r.querySelector('.y2');
                    const dateEl = r.querySelector('.xW, td.xY span');
                    return {
                        id: String(idx + 1),
                        sender: senderEl ? (senderEl.innerText || senderEl.getAttribute('name') || '') : 'Unknown',
                        subject: subjectEl ? subjectEl.innerText.trim() : 'No Subject',
                        snippet: snippetEl ? snippetEl.innerText.trim().replace(/^\\s*-\\s*/, '') : '',
                        date: dateEl ? dateEl.innerText.trim() : ''
                    };
                }).filter(e => e.subject && e.subject !== 'No Subject');
            }''')

            logger.info(f"Extracted {len(raw_emails)} total email rows from primary inbox.")
            if not raw_emails:
                logger.info("No email rows loaded from Gmail DOM; preserving existing saved intelligence.")
                return self.get_saved_intel()

            processed = self._process_and_categorize(raw_emails)

            with open(EMAIL_INTEL_JSON, "w", encoding="utf-8") as f:
                json.dump(processed, f, indent=2)

            logger.info(f"Identified and classified {len(processed)} career/application emails.")
            return processed

        except Exception as e:
            logger.error(f"Error scanning inbox: {e}")
            return self.get_saved_intel()
        finally:
            self.browser_mgr.close()

    def _process_and_categorize(self, raw_emails: list) -> list:
        ignore_senders = ["minimalist", "the5ers", "redotpay", "treks and trails", "help", "swiggy", "zomato", "uber"]
        ignore_subjects = ["complaint", "order #", "verification code", "welcome to", "finish your purchase", "service request", "mac os"]

        career_emails = []

        for em in raw_emails:
            sender = em["sender"]
            subject = em["subject"]
            snippet = em["snippet"]
            s_lower = sender.lower()
            sub_lower = subject.lower()
            snip_lower = snippet.lower()
            combined = f"{s_lower} {sub_lower} {snip_lower}"

            # Check blacklist
            if any(ig in s_lower for ig in ignore_senders):
                continue
            if any(ig in sub_lower for ig in ignore_subjects):
                continue

            # Check whitelist / career indicators
            is_career = any(k in combined for k in [
                "applied", "application", "interview", "assessment", "exam", "admit card",
                "recruitment", "hiring", "cbt", "analyst", "product manager", "apm", "intern",
                "naukri", "linkedin", "job", "career", "shortlist", "candidate", "drive", "talent"
            ])

            if not is_career:
                continue

            # Classify into specific action category
            category = "General Career"
            status_badge = "bg-slate-100 text-slate-700"
            company = sender
            next_action = "Review update in email"

            # 1. Assessment / Exam / Next Steps
            if any(k in combined for k in ["admit card", "online exam", "cbt", "assessment", "intimation for online exam"]):
                category = "Exam / Assessment / Next Steps"
                status_badge = "bg-purple-100 text-purple-700 font-bold"
                if "isro" in combined or "icrb" in combined:
                    company = "ISRO (ICRB)"
                    next_action = "CBT Exam Date & City Intimated / Admit Card Available"
                elif "airports authority" in combined or "ibps" in combined:
                    company = "Airports Authority of India (AAI)"
                    next_action = "Online Exam Intimation (Roll: 1941002075)"
                else:
                    company = sender
                    next_action = "Test link or exam scheduled - Check details"

            # 2. Outbound Sent Applications by User
            elif sender.lower() == "me" or "apm application" in sub_lower or "product manager application" in sub_lower:
                category = "Outbound Sent Application"
                status_badge = "bg-indigo-100 text-indigo-700 font-semibold"
                if "kotak" in sub_lower:
                    company = "Kotak Mahindra"
                else:
                    company = "Direct Recruiter Outreach"
                next_action = "Follow up if no response within 5 days"

            # 3. Direct Application Acknowledged
            elif any(k in sub_lower for k in ["application was sent to", "thank you for applying", "your application for", "received your job application", "applied for"]):
                category = "Active Application Tracked"
                status_badge = "bg-blue-100 text-blue-700 font-semibold"
                if "mcaffeine" in combined:
                    company = "mCaffeine"
                    next_action = "Application Sent for APM (Mumbai)"
                elif "ss&c" in combined:
                    company = "SS&C Technologies"
                    next_action = "Application Acknowledged (SC2 opening)"
                elif "smartstream" in combined:
                    company = "Smartstream Limited (Workable)"
                    next_action = "Application Confirmed via Workable"
                elif "jpmorgan" in combined:
                    company = "JPMorganChase"
                    next_action = "Application Status Acknowledged (Trading Services)"
                elif "dun & bradstreet" in combined:
                    company = "Dun & Bradstreet"
                    next_action = "Application Review Underway"
                elif "eclerx" in combined:
                    company = "eClerx"
                    next_action = "Application Tracked"
                elif "naukri" in s_lower:
                    company = "Naukri Applications"
                    next_action = "Daily application digest confirmed"
                else:
                    company = sender
                    next_action = "Application under initial review"

            # 4. Direct Recruiter Invitations & Match Alerts
            elif any(k in combined for k in ["is hiring:", "hiring", "urgent requirement", "top candidate", "you may be a fit", "job |"]):
                category = "Recruiter Invite / High Match"
                status_badge = "bg-emerald-100 text-emerald-700 font-semibold"
                if "barclays" in combined:
                    company = "Barclays"
                    next_action = "Business Analyst BA4 Opening"
                elif "zepto" in combined:
                    company = "Zepto"
                    next_action = "Associate Product Manager – Planning"
                elif "ey" in combined:
                    company = "EY"
                    next_action = "Associate Consultant Risk Opening"
                elif "capgemini" in combined:
                    company = "Capgemini"
                    next_action = "CX Strategy Role"
                elif "akbar" in combined:
                    company = "Akbar Offshore"
                    next_action = "Associate Product Manager Role"
                elif "shriram" in combined:
                    company = "Shriram Finance"
                    next_action = "Recruiter Invitation to Apply"
                else:
                    company = sender
                    next_action = "Role Match - Click to view opening"

            # Check if this opportunity passed screening phase or has next steps
            is_screening_passed = False
            passed_stage = ""

            if category == "Exam / Assessment / Next Steps":
                is_screening_passed = True
                if "cbt" in combined:
                    passed_stage = "CBT Exam Date & City Intimated"
                elif "admit card" in combined:
                    passed_stage = "Admit Card Released"
                elif "online exam" in combined:
                    passed_stage = "Online Exam Scheduled"
                else:
                    passed_stage = "Assessment / Next Steps Active"
            elif any(k in combined for k in ["interview", "discussion call", "round 1", "round 2"]):
                is_screening_passed = True
                passed_stage = "Interview Scheduled"
            elif any(k in combined for k in ["shortlist", "shortlisted", "next steps in your application", "congratulations"]):
                is_screening_passed = True
                passed_stage = "Screening Cleared / Shortlisted"

            career_emails.append({
                "company": company,
                "sender": sender,
                "subject": subject,
                "snippet": snippet[:140],
                "category": category,
                "status_badge": status_badge,
                "next_action": next_action,
                "is_screening_passed": is_screening_passed,
                "passed_stage": passed_stage,
                "date": em.get("date", "Recent"),
                "gmail_link": "https://mail.google.com/mail/u/0/#inbox"
            })

        # Save screening passed subset
        passed_list = [c for c in career_emails if c.get("is_screening_passed")]
        with open(PASSED_OPPORTUNITIES_JSON, "w", encoding="utf-8") as f:
            json.dump(passed_list, f, indent=2)

        return career_emails

    def get_saved_intel(self) -> list:
        if os.path.exists(EMAIL_INTEL_JSON):
            try:
                with open(EMAIL_INTEL_JSON, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def get_screening_passed(self) -> list:
        if os.path.exists(PASSED_OPPORTUNITIES_JSON):
            try:
                with open(PASSED_OPPORTUNITIES_JSON, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        # Fallback to computing from saved intel
        intel = self.get_saved_intel()
        return [i for i in intel if i.get("is_screening_passed") or i.get("category") == "Exam / Assessment / Next Steps"]


if __name__ == "__main__":
    t = EmailTracker()
    results = t.scan_full_inbox()
    print(f"\nSaved {len(results)} categorized career emails to {EMAIL_INTEL_JSON}")
    for idx, r in enumerate(results[:8]):
        print(f"[{idx+1}] [{r['category']}] {r['company']}: {r['subject']}")
        print(f"     Action: {r['next_action']}\n")
