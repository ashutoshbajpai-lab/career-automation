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

EMAIL_REGEX = re.compile(r'\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.(?:com|in|org|net|co|ai|io|tech|edu|gov|co\.in|ac\.in|[a-zA-Z]{2,8})\b', re.IGNORECASE)

def clean_extracted_email(email_str: str) -> str:
    """Strips trailing punctuation, numbers, or words glued to domain."""
    em = email_str.strip(' .,:;)"\'')
    m = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.(?:com|in|org|net|co|ai|io|tech|edu|gov|co\.in|ac\.in|[a-zA-Z]{2,8}))', em, re.IGNORECASE)
    return m.group(1).lower() if m else em.lower()
FORM_DOMAINS = [
    "forms.gle", "docs.google.com/forms", "typeform.com", "airtable.com", 
    "notion.site", "notion.so", "tally.so", "forms.office.com", 
    "surveymonkey.com", "greenhouse.io", "lever.co", "ashbyhq.com", 
    "smartrecruiters.com", "bamboohr.com", "workday.com", "wellfound.com"
]


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
        max_scroll_passes = 120

        for scroll_i in range(1, max_scroll_passes + 1):
            try:
                new_cards = self.page.evaluate('''() => {
                    // Click see more to expand truncated recruiter emails and links
                    document.querySelectorAll('button.feed-shared-inline-show-more-text, button[aria-label*="see more"], .feed-shared-see-more-less-toggle').forEach(b => {
                        try { b.click(); } catch(e) {}
                    });
                    
                    // Match top-level post containers
                    const potentialElements = Array.from(document.querySelectorAll(
                        'div.feed-shared-update-v2, div[data-urn*="urn:li:"], div[data-id*="urn:li:"], div[data-view-name="feed-full-update"], [data-lazy-mount-id]'
                    ));
                    
                    const processedCards = new Set();
                    const results = [];
                    
                    potentialElements.forEach(el => {
                        const card = el.closest('div.feed-shared-update-v2, div[data-urn*="urn:li:"], div[data-id*="urn:li:"], div[data-view-name="feed-full-update"]') || el;
                        if (!card || processedCards.has(card) || card.hasAttribute('data-harvested')) return;
                        processedCards.add(card);
                        card.setAttribute('data-harvested', '1');

                        const rawText = (card.innerText || card.textContent || '').trim();
                        if (rawText.length > 60) {
                            // Extract author name
                            const authorEl = card.querySelector(
                                ".update-components-actor__name span[aria-hidden='true'], " +
                                ".update-components-actor__name, " +
                                ".feed-shared-actor__name span[aria-hidden='true'], " +
                                ".feed-shared-actor__name, " +
                                "span.update-components-actor__title span[aria-hidden='true'], " +
                                "a.update-components-actor__meta-link"
                            );
                            let authorName = authorEl ? (authorEl.textContent || '').trim() : '';
                            if (!authorName) {
                                const lines = rawText.split('\\n').map(l => l.trim()).filter(l => l && !l.startsWith('Feed post'));
                                if (lines.length) authorName = lines[0].split('•')[0].trim();
                            }

                            // Extract post URN and direct permalink
                            let urn = card.getAttribute('data-urn') || 
                                      card.getAttribute('data-id') || 
                                      card.getAttribute('data-chameleon-urn') || '';

                            if (!urn) {
                                const urnEl = card.querySelector('[data-urn*="urn:li:"], [data-id*="urn:li:"]');
                                if (urnEl) urn = urnEl.getAttribute('data-urn') || urnEl.getAttribute('data-id') || '';
                            }

                            let postPermalink = '';
                            if (urn && urn.includes('urn:li:')) {
                                postPermalink = `https://www.linkedin.com/feed/update/${urn}/`;
                            }

                            const links = Array.from(card.querySelectorAll('a')).map(a => a.href).filter(h => h && h.startsWith('http'));
                            if (!postPermalink) {
                                const timestampLink = card.querySelector('a[href*="/feed/update/urn:li:"], a.update-components-actor__sub-description-link, a[href*="/posts/"]');
                                if (timestampLink && timestampLink.href) {
                                    const m = timestampLink.href.match(/urn:li:(?:activity|ugcPost|share):[0-9]+/);
                                    if (m) {
                                        postPermalink = `https://www.linkedin.com/feed/update/${m[0]}/`;
                                    } else {
                                        postPermalink = timestampLink.href.split('?')[0];
                                    }
                                }
                            }
                            if (!postPermalink) {
                                const foundLink = links.find(h => h.includes('/feed/update/urn:li:') || h.includes('/posts/'));
                                if (foundLink) postPermalink = foundLink.split('?')[0];
                            }

                            results.push({
                                text: rawText,
                                author: authorName,
                                post_url: postPermalink,
                                links: links
                            });
                        }
                    });
                    const main = document.querySelector('main') || document.scrollingElement || document.body;
                    main.scrollTop += 1400;
                    window.scrollBy(0, 1400);
                    window.dispatchEvent(new Event('scroll'));
                    return results;
                }''')
                for card in new_cards:
                    h = abs(hash(card["text"][:120]))
                    if h not in seen_card_hashes:
                        seen_card_hashes.add(h)
                        raw_items.append(card)
            except Exception as e:
                self._log(f"⚠️ Pass {scroll_i} note: {e}")

            if len(raw_items) >= target_posts:
                self._log(f"🎯 Milestone reached: Collected {len(raw_items)} distinct posts ({target_posts}+ target achieved at pass {scroll_i})!")
                break

            if scroll_i % 5 == 0:
                self._log(f"Progress: Pass {scroll_i}/{max_scroll_passes} - Scrolled through {len(raw_items)} distinct posts so far...")

            human_delay(0.9, 1.3)
            if scroll_i % 15 == 0:
                import gc
                gc.collect()

        self._log(f"Analyzed feed: Successfully extracted {len(raw_items)} distinct post cards. Filtering for opportunities...")

        seen_urns = set(self.state.get("seen_post_urns", []))
        new_leads = []
        max_posts = max(100, int(self.config.get("limits", {}).get("max_feed_posts_per_run", 100)))
        lead_keywords = [
            "hiring", "hire", "recruit", "intern", "internship", "analyst", "product", "associate", 
            "referral", "opening", "openings", "job", "jobs", "vacancy", "vacancies", "career", "careers", 
            "join our team", "dm me", "apply here", "send resume", "send cv", "drop your resume", "share cv"
        ]

        for item in raw_items:
            if len(new_leads) >= max_posts:
                break

            text = item["text"]
            text_lower = text.lower()

            # Generate pseudo-hash URN to prevent duplicates
            hash_id = str(abs(hash(text[:120])))
            if hash_id in seen_urns:
                continue

            # Extract and sanitize Emails
            raw_emails = list(set(EMAIL_REGEX.findall(text)))
            emails = list(set(clean_extracted_email(e) for e in raw_emails if clean_extracted_email(e)))

            # Extract Forms & External links
            form_links = []
            external_links = []
            post_url = item.get("post_url", "")

            for href_raw in item.get("links", []):
                href = extract_real_url(href_raw)
                if not href or "linkedin.com/in/" in href or "linkedin.com/article" in href:
                    continue

                if "linkedin.com/feed/update/urn:li:activity:" in href or "linkedin.com/posts/" in href:
                    if not post_url:
                        post_url = href.split("?")[0]
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
            if not author or author.lower() in ["linkedin member", "linkedin", "member"]:
                # Pattern: "...likes this<Author> •" or "...reposted this<Author> •" or "...commented<Author> •"
                m = re.search(r"(?:likes this|commented|reposted this|finds this insightful|follows this page)\s*([A-Za-z0-9\s\.\,\-]+?)\s*(?:•|\d+[hdwmy]|Follow|Promoted|$)", text, re.IGNORECASE)
                if m:
                    cand = m.group(1).strip()
                    cand = re.sub(r"^(?:and \d+ other connections? like this|reposted this)\s*", "", cand, flags=re.IGNORECASE).strip()
                    if len(cand) > 2 and len(cand) < 45:
                        author = cand

            if not author or author.lower() in ["linkedin member", "linkedin", "member"]:
                lines = [line.strip() for line in text.split("\n") if line.strip() and not line.strip().startswith("Feed post") and not "likes this" in line]
                if lines:
                    cand = lines[0].split("•")[0].strip()
                    cand = re.sub(r"\d+[\d,]*\s*(?:followers|connections?|Promoted)?.*$", "", cand).strip()
                    author = cand if len(cand) > 2 and len(cand) < 45 else "Hiring Lead"
                else:
                    author = "Hiring Lead"

            # Construct verified fallback post URL if direct link wasn't captured
            if not post_url:
                clean_auth = re.sub(r"\s*\(.*?\)", "", author).strip()
                if clean_auth and clean_auth != "Hiring Lead":
                    if emails:
                        search_kw = f'"{clean_auth}" "{emails[0]}"'
                    else:
                        snip = re.sub(r"[^\w\s]", "", text[:40]).strip()
                        search_kw = f'"{clean_auth}" {snip}'
                elif emails:
                    search_kw = f'"{emails[0]}"'
                else:
                    snip = re.sub(r"[^\w\s]", "", text[:50]).strip()
                    search_kw = snip or "hiring"
                post_url = f"https://www.linkedin.com/search/results/content/?keywords={urllib.parse.quote(search_kw)}"

            has_keyword = any(kw in text_lower for kw in lead_keywords)
            has_actionable = bool(emails or form_links or external_links or any(w in text_lower for w in ["dm", "comment", "email", "cv", "resume", "apply"]))
            
            if has_keyword and has_actionable:
                record = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "author": author[:60],
                    "emails": ", ".join(emails),
                    "form_links": ", ".join(form_links),
                    "hyperlinks": ", ".join(external_links[:3]),
                    "post_url": post_url,
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
            fieldnames = ["timestamp", "author", "emails", "form_links", "hyperlinks", "post_url", "preview", "id"]
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
