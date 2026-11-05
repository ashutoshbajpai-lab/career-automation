"""
feed_harvester.py - Modern LinkedIn feed harvester.
Extracts hiring posts, email addresses, Google Forms, and career links.
"""

import os
import re
import csv
import json
import logging
import urllib.parse
from datetime import datetime
from browser_session import human_delay, smooth_scroll

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
FORM_DOMAINS = ["forms.gle", "docs.google.com/forms", "typeform.com", "airtable.com", "notion.site", "notion.so", "tally.so"]


def extract_real_url(href: str) -> str:
    """Decodes LinkedIn redirect wrappers (https://www.linkedin.com/safety/go/?url=...)"""
    if not href:
        return ""
    if "safety/go" in href and "url=" in href:
        m = re.search(r'[?&]url=([^&]+)', href)
        if m:
            return urllib.parse.unquote(m.group(1))
    return href


class FeedHarvester:
    def __init__(self, page, config: dict, state: dict, base_dir: str, log_cb=None):
        self.page = page
        self.config = config
        self.state = state
        self.base_dir = base_dir
        self.log_cb = log_cb
        self.data_dir = os.path.join(base_dir, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        self.leads_csv = os.path.join(self.data_dir, "feed_leads.csv")
        self.leads_json = os.path.join(self.data_dir, "feed_leads.json")

    def _log(self, msg: str):
        logger.info(msg)
        if self.log_cb:
            try:
                self.log_cb(msg)
            except Exception:
                pass

    def run(self) -> list:
        self._log("Configuring lightweight page route (blocking media & heavy fonts to optimize RAM)...")
        try:
            self.page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
        except Exception:
            pass

        self._log("Navigating to LinkedIn feed (https://www.linkedin.com/feed/)...")
        try:
            self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=35000)
        except Exception as e:
            self._log(f"Navigation fallback: {e}")
            try:
                self.page.goto("https://www.linkedin.com/feed/", wait_until="commit", timeout=20000)
            except Exception:
                pass
        human_delay(2.0, 3.0)

        current_url = self.page.url
        current_title = self.page.title()
        self._log(f"Arrived at LinkedIn. Page Title: '{current_title}' | URL: {current_url}")

        # Check if login or checkpoint
        if "login" in current_url or "checkpoint" in current_url:
            self._log(f"⚠️ LinkedIn requires authentication / checkpoint: {current_url}")
            return []

        target_posts = int(self.config.get("limits", {}).get("max_feed_posts_per_run", 100))
        if target_posts < 100:
            target_posts = 100

        self._log(f"🚀 Starting deep feed harvester: targeting at least {target_posts}+ posts...")
        seen_card_hashes = set()
        raw_items = []
        max_scroll_passes = 65

        for scroll_i in range(1, max_scroll_passes + 1):
            # 1. High-performance card extraction using textContent (zero layout reflow)
            try:
                batch = self.page.evaluate('''() => {
                    const mounts = Array.from(document.querySelectorAll('[data-lazy-mount-id], div.feed-shared-update-v2, div[data-urn*="activity"]'));
                    const results = [];
                    mounts.forEach(el => {
                        const rawText = (el.textContent || '').trim();
                        if (rawText.length > 120) {
                            const authorEl = el.querySelector(".update-components-actor__name, .feed-shared-actor__name, span[dir='ltr'] span");
                            const authorName = authorEl ? (authorEl.textContent || '').trim() : '';
                            const links = Array.from(el.querySelectorAll('a')).map(a => ({
                                href: a.href,
                                text: (a.textContent || '').trim()
                            }));
                            results.push({
                                text: rawText,
                                author: authorName,
                                links: links
                            });
                        }
                    });
                    return results;
                }''')
                for card in batch:
                    h = abs(hash(card["text"][:120]))
                    if h not in seen_card_hashes:
                        seen_card_hashes.add(h)
                        raw_items.append(card)
            except Exception:
                pass

            if len(raw_items) >= target_posts:
                self._log(f"🎯 Milestone reached: Collected {len(raw_items)} distinct posts ({target_posts}+ target achieved at pass {scroll_i})!")
                break

            if scroll_i % 5 == 0:
                self._log(f"Progress: Pass {scroll_i}/{max_scroll_passes} - Scrolled through {len(raw_items)} distinct posts so far...")

            # 2. Smoothly advance <main> container scroll position & trigger LinkedIn infinite scroll
            try:
                self.page.evaluate('''() => {
                    const main = document.querySelector('main') || document.scrollingElement || document.body;
                    main.scrollTop += 950;
                    window.scrollBy(0, 950);
                }''')
                human_delay(0.9, 1.4)
            except Exception:
                pass

            if scroll_i % 15 == 0:
                import gc
                gc.collect()

        self._log(f"Analyzed feed: Successfully extracted {len(raw_items)} distinct post cards. Filtering for opportunities...")

        seen_urns = set(self.state.get("seen_post_urns", []))
        new_leads = []
        max_posts = max(100, int(self.config.get("limits", {}).get("max_feed_posts_per_run", 100)))
        lead_keywords = [k.lower() for k in self.config.get("lead_keywords", ["hiring", "intern", "analyst", "product", "referral", "opening", "job"])]

        for item in raw_items:
            if len(new_leads) >= max_posts:
                break

            text = item["text"]
            text_lower = text.lower()

            # Generate pseudo-hash URN to prevent duplicates
            hash_id = str(abs(hash(text[:120])))
            if hash_id in seen_urns:
                continue

            # Extract Emails
            emails = list(set(EMAIL_REGEX.findall(text)))

            # Extract Forms & External links
            form_links = []
            external_links = []

            for l in item["links"]:
                href = extract_real_url(l["href"])
                if not href or "linkedin.com/in/" in href or "linkedin.com/feed/" in href or "linkedin.com/article" in href:
                    continue

                if any(domain in href.lower() for domain in FORM_DOMAINS):
                    if href not in form_links:
                        form_links.append(href)
                elif href.startswith("http") and href not in external_links:
                    external_links.append(href)

            # Check text directly for form links
            for domain in FORM_DOMAINS:
                matches = re.findall(rf'https?://[^\s]+{re.escape(domain)}[^\s]*', text)
                for m in matches:
                    clean_m = m.strip("),.>")
                    if clean_m not in form_links:
                        form_links.append(clean_m)

            # Extract Author from element metadata or text header
            author = item.get("author", "").strip()
            if not author:
                lines = [line.strip() for line in text.split("\n") if line.strip() and not line.strip().startswith("Feed post") and not "likes this" in line]
                author = lines[0] if lines else "LinkedIn Member"

            has_keyword = any(kw in text_lower for kw in lead_keywords)
            if emails or form_links or (has_keyword and external_links):
                record = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "author": author[:60],
                    "emails": ", ".join(emails),
                    "form_links": ", ".join(form_links),
                    "hyperlinks": ", ".join(external_links[:3]),
                    "preview": text[:200].replace("\n", " ").strip(),
                    "id": hash_id
                }
                new_leads.append(record)
                seen_urns.add(hash_id)
                self._log(f"🎯 [LEAD DISCOVERED] Author: {author[:25]} | Emails: {', '.join(emails) or 'None'} | Forms: {', '.join(form_links) or 'None'}")

        self.state["seen_post_urns"] = list(seen_urns)[-500:]
        self._save_leads(new_leads)
        self._log(f"Feed Harvester finished: Collected {len(new_leads)} new leads.")
        return new_leads

    def _save_leads(self, leads: list):
        if not leads:
            return

        file_exists = os.path.exists(self.leads_csv)
        with open(self.leads_csv, "a", newline="", encoding="utf-8") as f:
            fieldnames = ["timestamp", "author", "emails", "form_links", "hyperlinks", "preview", "id"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            for l in leads:
                writer.writerow(l)

        existing_json = []
        if os.path.exists(self.leads_json):
            try:
                with open(self.leads_json, "r", encoding="utf-8") as f:
                    existing_json = json.load(f)
            except Exception:
                existing_json = []

        existing_json.extend(leads)
        with open(self.leads_json, "w", encoding="utf-8") as f:
            json.dump(existing_json, f, indent=2)

        logger.info(f"Saved {len(leads)} leads to {self.leads_csv}")
