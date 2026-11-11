"""
feed_harvester.py - Modern LinkedIn feed harvester.
Extracts hiring posts, email addresses, Google Forms, and career links.
"""

import os
import re
import csv
import json
import time
import logging
import urllib.parse
from datetime import datetime
from browser_session import human_delay, smooth_scroll, is_cloud_low_mem, get_tree_ram_mb

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
    "smartrecruiters.com", "bamboohr.com", "workday.com", "wellfound.com",
    "lnkd.in", "bit.ly", "tinyurl.com"
]

STRONG_HIRING_REGEX = re.compile(
    r"(?:"
    r"#(?:hiringnow|wearehiring|nowhiring|jobopening|jobalert|hiringalert|careeropportunity|"
    r"immediatehiring|recruitment|talentacquisition|openforroles|jobopportunity|joinourteam|hiring)\b|"
    r"\b(?:"
    r"we['’]?re hiring|we are hiring|is hiring|are hiring|now hiring|urgently hiring|active hiring|"
    r"direct hire|mass hiring|bulk hiring|fast[- ]?track hiring|looking to hire|"
    r"hiring alert|job alert|immediate opening|urgent requirement|critical role|hot opportunity|"
    r"career opportunity|multiple openings|growing team|team expansion|expanding our team|we are growing|"
    r"scaling up|adding to (?:the|our) team|join our team|"
    r"quick joiner(?: needed)?|immediate joiner(?: preferred)?|immediate onboarding|"
    r"walk[- ]?in interview|interested candidates|submit application|email your resume|"
    r"onboard(?:ing)?|bring(?:ing)?\s+(?:someone\s+|folks\s+|talent\s+)?on\s*board|"
    r"hiring\s*[:\-–]|hiring\s+(?:a|an|for)\b|seeking\s+(?:a|an)\b|recruiting\b|"
    r"looking to join\b.{0,50}\b(?:startup|team|company)\b|"
    r"looking for\b.{0,80}\b(?:interns?|trainees?|freshers?|associates?|juniors?|analysts?|managers?|heads?|leads?|sales|executives?|specialists?|coordinators?|consultants?|strategists?|marketers?|recruiters?|designers?|professionals?|candidates?|talent|folks|people|team members?|founder['’]?s office|founders office|bizops|operations?|marketing|growth|partnerships?|finance|hr|content)\b|"
    r"open role|open position|job opening|openings? for|vacanc(?:y|ies)|recruiting for|"
    r"share (?:your )?(?:cv|resume)|send (?:your )?(?:cv|resume)|drop (?:your )?(?:cv|resume)|"
    r"reach out at|interested candidates please apply|application form in the comments"
    r"))",
    re.IGNORECASE,
)

HIRING_HASHTAG_SOFT_REGEX = re.compile(
    r"#(?:jobs|careers|jobsearch|remotejobs|hybridwork|fulltimejob)\b",
    re.IGNORECASE,
)

NON_TECH_ROLE_REGEX = re.compile(
    r"\b("
    r"non[- ]?tech|product|apm|analytics|analyst|business|bizops|strategy|strategic|operations|ops|"
    r"marketing|trade marketing|brand|growth|performance marketing|digital marketing|content|copywriter|pr|communications|"
    r"sales|b2b|inside sales|business development|\bbd\b|partnerships?|account manager|client|customer success|crm|"
    r"founder['’]?s office|founders office|chief of staff|management trainee|trainee|fresher|junior|entry[- ]?level|associate|executive|generalist|program manager|project manager|"
    r"finance|financial|accounting|audit|investment|venture|vc|private equity|equity research|consulting|consultant|"
    r"hr|human resources|talent acquisition|\bta\b|recruiter|recruiting|people ops|staffing|"
    r"supply chain|logistics|procurement|category|merchandising|retail|e-?commerce|"
    r"research|market research|ux|ui/ux|design|intern|internship"
    r")\b",
    re.IGNORECASE,
)

PURE_TECH_ONLY_REGEX = re.compile(
    r"\b("
    r"software engineer|software developer|\bsde\b|frontend|back[- ]?end|full[- ]?stack|fullstack|"
    r"devops|\bsre\b|kubernetes|docker|react\.?js|angular|vue\.?js|node\.?js|golang|rust|"
    r"java developer|python developer|c\+\+|\.net|ios developer|android developer|flutter|"
    r"qa automation|selenium|embedded|firmware|blockchain|solidity|cloud architect|mlops|data engineer"
    r")\b",
    re.IGNORECASE,
)

NON_HIRING_NOISE_REGEX = re.compile(
    r"\b("
    r"started a new position|happy to share that i|thrilled to announce|"
    r"completed (?:a|my) certification|free webinar|live masterclass|"
    r"subscribe to (?:my|our) newsletter|download our (?:ebook|guide)"
    r")\b",
    re.IGNORECASE,
)


def is_genuine_hiring_post(text: str, emails: list, form_links: list, external_links: list, comment_links: list) -> tuple:
    """
    Strictly verifies that a LinkedIn feed post is an active hiring post
    across ALL non-tech roles and hiring hashtags/phrases (Hiring, Hiring Alert,
    Expanding/Growing Team, Immediate Onboarding, Walk-in Interview, Founder's Office,
    Fresher/Associate/Junior/Analyst/Executive, etc.), filtering out pure coding-only
    roles and non-hiring chatter.
    """
    low = (text or "").lower()
    has_strong_hiring = bool(STRONG_HIRING_REGEX.search(low))
    has_soft_hashtag = bool(HIRING_HASHTAG_SOFT_REGEX.search(low)) and bool(
        emails or form_links or external_links or comment_links
    )
    if not (has_strong_hiring or has_soft_hashtag):
        return False, []

    if NON_HIRING_NOISE_REGEX.search(low) and not re.search(
        r"(?:\b(?:we['’]?re hiring|we are hiring|hiring\s*:|apply here|submit application|email your resume|share (?:your )?(?:cv|resume))\b|#(wearehiring|hiringnow|nowhiring)\b)",
        low,
    ):
        return False, []

    has_non_tech = bool(NON_TECH_ROLE_REGEX.search(low))
    is_pure_tech_only = bool(PURE_TECH_ONLY_REGEX.search(low)) and not has_non_tech
    if is_pure_tech_only:
        return False, []

    has_actionable = bool(
        emails
        or form_links
        or external_links
        or comment_links
        or re.search(
            r"\b(dm me|send dm|message me|ping me|in the comments|comment below|comment ['\"]?interested|"
            r"reach out|apply here|apply now|apply today|apply via|submit application|fill the form|link in bio|"
            r"walk[- ]?in interview|email your resume|share (?:your )?(?:cv|resume)|send (?:your )?(?:cv|resume)|drop (?:your )?(?:cv|resume))\b",
            low,
        )
    )
    if not has_actionable:
        return False, []

    tags = []
    has_junior = any(k in low for k in ["0-2", "0-1", "1-2", "0-3", "1-3", "2-3", "fresher", "intern", "internship", "entry level", "entry-level", "graduate", "junior", "associate", "analyst", "trainee", "founder's office", "founder’s office", "founders office"])
    has_senior = any(k in low for k in ["5+ years", "6+ years", "7+ years", "8+ years", "10+ years", "head –", "head -", "director", "vp"])
    if has_junior:
        tags.append("Recruiting (0-3 Yrs)")
    elif has_senior:
        tags.append("Hiring (Experienced)")
    else:
        tags.append("Hiring Post")

    if has_non_tech:
        tags.append("Non-Tech Role")
    if any(k in low for k in ["hybrid", "#hybridwork"]):
        tags.append("Hybrid")
    elif any(k in low for k in ["remote", "#remotejobs"]):
        tags.append("Remote")
    elif any(k in low for k in ["on-site", "onsite", "in-office", "in office"]):
        tags.append("On-Site")
    if "pan-india" in low or "pan india" in low:
        tags.append("Pan-India")

    if emails:
        tags.append("Direct Email")
    if form_links or comment_links or "comments" in low or "submit application" in low:
        tags.append("Apply Link / Form")
    elif "dm me" in low or "message me" in low:
        tags.append("DM Hiring Lead")
    elif "walk-in" in low or "walk in" in low:
        tags.append("Walk-In Interview")
    return True, tags


def extract_real_url(href: str) -> str:
    """Decodes LinkedIn redirect wrappers (https://www.linkedin.com/safety/go/?url=...)"""
    if not href:
        return ""
    if "safety/go" in href and "url=" in href:
        m = re.search(r'[?&]url=([^&]+)', href)
        if m:
            return urllib.parse.unquote(m.group(1))
    return href


def clean_post_description(raw_text: str, author: str = "") -> str:
    """Strips LinkedIn feed UI chrome lines and returns the detailed post JD/body cleanly."""
    if not raw_text:
        return ""
    noise_exact = {
        "feed post", "follow", "following", "connect", "like", "comment", "repost", "send",
        "promoted", "… more", "... more", "see more", "see translation",
    }
    noise_re = re.compile(
        r"^(?:"
        r"Feed post|"
        r"(?:Followed|Reposted|Commented) by .*|"
        r".*\b(?:likes this|loves this|celebrates this|finds this insightful|commented on|reposted this|follows this page)$|"
        r"[•\s]*(?:1st|2nd|3rd\+?)\s*$|"
        r"\d+[\d,]*\s*(?:followers|connections?|comments?|reposts?|reactions?)\s*$|"
        r"\d+[smhdwyo]\s*(?:•\s*Edited)?\s*$|"
        r"Reaction button.*|Open reactions menu.*"
        r")$",
        re.IGNORECASE,
    )
    cleaned = []
    skipped_header = False
    author_low = (author or "").strip().lower()
    for line in raw_text.splitlines():
        s = line.strip()
        if not s:
            continue
        sl = s.lower()
        if sl in noise_exact or noise_re.match(s):
            continue
        if not skipped_header and author_low and (sl == author_low or sl.startswith(author_low + " •")):
            skipped_header = True
            continue
        cleaned.append(s)
    # Trim trailing comment preview noise after action bar if present
    text_out = "\n".join(cleaned).strip()
    return text_out[:3000]


def extract_job_role(description: str) -> str:
    """Extracts the job role/title being hired for from LinkedIn hiring post text."""
    if not description:
        return "Hiring Opportunity"
    patterns = [
        r"(?:we(?:'re| are)\s+hiring|now hiring|urgently hiring|hiring)\s*[:\-–]\s*([^\n|•.]{3,85})",
        r"(?:looking to onboard|onboarding|bring(?:ing)?\s+on\s*board|we(?:'re| are)\s+hiring(?:\s+for)?(?:\s+a|\s+an)?)\s+([^\n.!?]{3,75})",
        r"(?:looking for|seeking)\s+(?:an?\s+)?([^\n.!?]{3,75}?\b(?:interns?|associates?|analysts?|managers?|engineers?|developers?|designers?|heads?|leads?|sales|executives?|specialists?|consultants?)\b[^\n.!?]{0,25})",
        r"(?:role|position|opening|vacancy)\s*[:\-–]\s*([^\n|•]{3,80})",
        r"looking to join an early stage\s+([^\n?.!]{3,75})",
    ]
    for pat in patterns:
        m = re.search(pat, description, re.IGNORECASE)
        if m:
            role = re.sub(r"\s+", " ", m.group(1)).strip(" :-–|•.,!?\t")
            role = re.sub(r"^(?:a|an|the)\s+", "", role, flags=re.IGNORECASE)
            # Trim trailing filler clauses
            role = re.split(r"\s+(?:for \d|based in|at [A-Z]|to drive|to join|with \d)", role, maxsplit=1)[0].strip(" :-–|•.,")
            if 3 <= len(role) <= 85:
                return role
    # Fallback: first line containing a known role keyword
    role_kw = re.compile(
        r"\b(intern|trainee|analyst|associate|product manager|apm|manager|head|lead|sales|bd|business development|"
        r"marketing|operations|ops|strategy|bizops|growth|partnerships?|finance|hr|recruiter|designer|consultant|executive|coordinator)\b",
        re.IGNORECASE,
    )
    for line in description.splitlines():
        s = line.strip()
        if role_kw.search(s) and len(s) <= 85:
            return re.sub(r"\s+", " ", s)
    return "Hiring Opportunity"


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
        try:
            self.page.route(
                "**/*",
                lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_()
            )
        except Exception:
            pass

        feed_url = "https://www.linkedin.com/feed/foryou/"
        self._log(f"Opening LinkedIn Home → For You feed ({feed_url})...")
        nav_ok = False
        try:
            # Click navbar Home tab if already on a signed-in LinkedIn page, then ensure /feed/foryou/
            if "linkedin.com" in (self.page.url or "").lower():
                home_tab = self.page.locator("header nav a[href*='/feed'], nav a:has-text('Home')").locator("visible=true").first
                if home_tab.count() > 0:
                    try:
                        home_tab.click(timeout=5000)
                        human_delay(1.5, 2.5)
                        nav_ok = True
                    except Exception:
                        pass
            if "/feed/foryou" not in (self.page.url or "").lower():
                resp = self.page.goto(feed_url, wait_until="domcontentloaded", timeout=35000)
                if not resp or resp.status != 429:
                    nav_ok = True
        except Exception as e:
            self._log(f"Navigation fallback: {e}")
            if "ERR_TOO_MANY_REDIRECTS" not in str(e):
                try:
                    self.page.goto(feed_url, wait_until="commit", timeout=20000)
                    nav_ok = True
                except Exception:
                    pass
        human_delay(2.0, 3.0)

        current_url = (self.page.url or "").lower()
        try:
            current_title = self.page.title()
        except Exception:
            current_title = "Redirecting / Unavailable"
        self._log(f"Arrived at LinkedIn. Page Title: '{current_title}' | URL: {current_url}")

        # Check if login, checkpoint, redirect loop, or blank error page -> use public guest jobs fallback
        if (
            not nav_ok
            or not current_url
            or current_url.startswith("about:")
            or current_url.startswith("chrome-error")
            or any(k in current_url for k in ("login", "checkpoint", "authwall", "signup"))
        ):
            self._log(f"⚠️ LinkedIn feed unavailable ({current_url or 'redirect/error'}).")
            self._log("🔑 TIP: Click 'LinkedIn Auth' in the dashboard header to update your session cookie.")
            self._log("🌐 Activating Instant Public Jobs Engine (Harvesting 0-2 Yrs Analyst & PM Roles across India)...")
            return self._harvest_public_guest_jobs()

        low_mem = is_cloud_low_mem()
        default_target = 28 if low_mem else 60
        target_posts = int(self.config.get("limits", {}).get("max_feed_posts_per_run", default_target))
        if low_mem:
            target_posts = min(target_posts, 28)
        elif target_posts > 80:
            target_posts = 60

        self._log(f"🚀 Starting deep feed harvester: targeting {target_posts} posts per batch (LowMem={low_mem})...")
        seen_card_hashes = set()
        raw_items = []
        max_scroll_passes = 24 if low_mem else 45
        stale_passes = 0
        scroll_started_at = time.time()
        max_scroll_seconds = 90 if low_mem else 180

        for scroll_i in range(1, max_scroll_passes + 1):
            if time.time() - scroll_started_at >= max_scroll_seconds:
                self._log(f"⏱️ Feed batch time cap ({max_scroll_seconds}s) reached at pass {scroll_i} with {len(raw_items)} posts.")
                break
            prev_raw_count = len(raw_items)
            try:
                # Expand truncated "... more" / "see more" buttons inside unharvested main feed cards once
                clicked_more = self.page.evaluate('''() => {
                    const scope = document.querySelector('main#workspace') || document.querySelector('main') || document;
                    let clicked = 0;
                    scope.querySelectorAll(
                        'button[data-testid="expandable-text-button"], ' +
                        'button.feed-shared-inline-show-more-text, ' +
                        'button[aria-label*="see more" i], ' +
                        '.feed-shared-see-more-less-toggle'
                    ).forEach(b => {
                        if (b.getAttribute('data-more-clicked') === '1') return;
                        if (b.closest('[data-harvested="1"]')) return;
                        b.setAttribute('data-more-clicked', '1');
                        try { b.click(); clicked++; } catch(e) {}
                    });
                    return clicked;
                }''')
                if clicked_more:
                    self.page.wait_for_timeout(200)

                new_cards = self.page.evaluate('''() => {
                    // Match top-level post containers (SDUI /feed/foryou/ + legacy feed)
                    const cardSelector = (
                        'div[componentkey^="update-card-focus"], ' +
                        'div[componentkey*="FeedType_MAIN_FEED"], ' +
                        'div.feed-shared-update-v2, ' +
                        'div[data-urn*="urn:li:"], ' +
                        'div[data-id*="urn:li:"], ' +
                        'div[data-view-name="feed-full-update"]'
                    );
                    let potentialElements = Array.from(document.querySelectorAll(cardSelector));
                    if (!potentialElements.length) {
                        potentialElements = Array.from(document.querySelectorAll('[data-lazy-mount-id]'));
                    }
                    
                    const processedCards = new Set();
                    const results = [];
                    
                    potentialElements.forEach(el => {
                        const card = el.closest(cardSelector) || el;
                        if (!card || processedCards.has(card) || card.hasAttribute('data-harvested')) return;
                        processedCards.add(card);
                        card.setAttribute('data-harvested', '1');

                        const rawText = (card.innerText || card.textContent || '').trim();
                        if (rawText.length > 60) {
                            // Extract author name: SDUI control menu aria-label first, then legacy actor selectors, then clean lines
                            let authorName = '';
                            const ctrlBtn = card.querySelector('button[aria-label^="Open control menu for post by "], button[aria-label*="post by " i]');
                            if (ctrlBtn) {
                                const aria = ctrlBtn.getAttribute('aria-label') || '';
                                const m = aria.match(/post by\\s+(.+)$/i);
                                if (m && m[1]) authorName = m[1].trim();
                            }
                            if (!authorName) {
                                const authorEl = card.querySelector(
                                    ".update-components-actor__name span[aria-hidden='true'], " +
                                    ".update-components-actor__name, " +
                                    ".feed-shared-actor__name span[aria-hidden='true'], " +
                                    ".feed-shared-actor__name, " +
                                    "span.update-components-actor__title span[aria-hidden='true'], " +
                                    "a.update-components-actor__meta-link"
                                );
                                authorName = authorEl ? (authorEl.textContent || '').trim() : '';
                            }
                            if (!authorName) {
                                const skipRe = /^(Feed post|Followed by|Reposted by|Promoted|\\d+|.*\\b(likes this|loves this|celebrates|finds this insightful|commented on|follows this page))$/i;
                                const lines = rawText.split('\\n').map(l => l.trim()).filter(l => l && !skipRe.test(l));
                                if (lines.length) authorName = lines[0].split('•')[0].trim();
                            }

                            let authorUrl = '';
                            const actorLinks = Array.from(card.querySelectorAll('a[href*="/in/"], a[href*="/company/"]'));
                            for (const al of actorLinks) {
                                const txt = (al.innerText || '').trim().toLowerCase();
                                const aLow = (authorName || '').toLowerCase();
                                if (aLow && txt && (txt.includes(aLow) || aLow.includes(txt.split('•')[0].trim()))) {
                                    authorUrl = (al.href || '').split('?')[0];
                                    break;
                                }
                            }
                            if (!authorUrl && actorLinks.length) {
                                const nonLike = actorLinks.find(al => {
                                    const pText = (al.parentElement?.innerText || '').toLowerCase();
                                    return !pText.includes('likes this') && !pText.includes('commented') && !pText.includes('reposted') && !pText.includes('followed by');
                                }) || actorLinks[0];
                                authorUrl = (nonLike.href || '').split('?')[0];
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
                                const menuBtn = card.querySelector('button.feed-shared-control-menu__trigger, button[aria-label*="Control menu for update"], button[aria-label*="More actions"], button[aria-label*="share"]');
                                if (menuBtn) {
                                    const aria = menuBtn.getAttribute('aria-label') || '';
                                    const m = aria.match(/urn:li:(?:activity|ugcPost|share):[0-9]+/);
                                    if (m) postPermalink = `https://www.linkedin.com/feed/update/${m[0]}/`;
                                }
                            }
                            if (!postPermalink) {
                                const foundLink = links.find(h => h.includes('/feed/update/urn:li:') || h.includes('/posts/'));
                                if (foundLink) postPermalink = foundLink.split('?')[0];
                            }

                            // Check for "link in comment" / "pinned in comment"
                            const commentTriggers = ['link in comment', 'links in comment', 'form in comment', 'pinned in comment', 'pinned comment', 'link below in comment', 'apply in comment'];
                            const lower = rawText.toLowerCase();
                            let commentLinks = [];
                            if (commentTriggers.some(k => lower.includes(k))) {
                                try {
                                    const cBtn = card.querySelector('button[aria-label*="Comment"], button.comment-button, button.show-prev-comments');
                                    if (cBtn) cBtn.click();
                                } catch(e) {}
                            }
                            const commentEls = Array.from(card.querySelectorAll('.comments-comment-item, .comments-comments-list__comment-item, div[data-comment-id], .feed-shared-comment-item'));
                            commentEls.forEach(c => {
                                Array.from(c.querySelectorAll('a')).forEach(a => {
                                    if (a.href && a.href.startsWith('http') && !a.href.includes('linkedin.com/in/')) {
                                        commentLinks.push(a.href);
                                    }
                                });
                            });

                            results.push({
                                text: rawText,
                                author: authorName,
                                author_url: authorUrl,
                                post_url: postPermalink,
                                links: links,
                                comment_links: commentLinks
                            });
                        }
                    });
                    const main = document.querySelector('main#workspace') || document.querySelector('main') || document.scrollingElement || document.body;
                    main.scrollTop += 1400;
                    main.dispatchEvent(new Event('scroll'));
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
                err_str = str(e)
                self._log(f"⚠️ Pass {scroll_i} note: {err_str}")
                if any(k in err_str for k in ("Target crashed", "Target closed", "Execution context", "crashed")):
                    self._log(f"🛑 Stopping scroll cleanly after {len(raw_items)} posts due to browser tab memory limit.")
                    break

            if len(raw_items) >= target_posts:
                self._log(f"🎯 Milestone reached: Collected {len(raw_items)} distinct posts ({target_posts}+ target achieved at pass {scroll_i})!")
                break

            if len(raw_items) == prev_raw_count:
                stale_passes += 1
                if stale_passes >= 8:
                    self._log(f"Stopping feed scroll after {stale_passes} consecutive passes with no new cards ({len(raw_items)} collected).")
                    break
            else:
                stale_passes = 0

            if scroll_i % 5 == 0:
                self._log(f"Progress: Pass {scroll_i}/{max_scroll_passes} - Scrolled through {len(raw_items)} distinct posts so far...")

            human_delay(0.9, 1.3)
            if scroll_i % 10 == 0:
                import gc
                gc.collect()
                if low_mem and get_tree_ram_mb() > 410.0:
                    self._log(f"⚠️ [LOAD MANAGER] Cloud RAM reached {get_tree_ram_mb()} MB at pass {scroll_i} — stopping scroll cleanly.")
                    break

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
            tags = []

            # Process links in post body and links in comments
            all_raw_links = list(item.get("links", []))
            comment_links = list(item.get("comment_links", []))
            if comment_links:
                for cl in comment_links:
                    if cl not in all_raw_links:
                        all_raw_links.append(cl)

            for href_raw in all_raw_links:
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
                        if href_raw in comment_links:
                            tags.append("Comment Link Extracted")
                elif href.startswith("http") and href not in external_links:
                    external_links.append(href)
                    if href_raw in comment_links:
                        tags.append("Comment Link Extracted")

            # Check text directly for form links
            for domain in FORM_DOMAINS:
                matches = re.findall(rf'https?://[^\s]+{re.escape(domain)}[^\s]*', text)
                for m in matches:
                    clean_m = m.strip("),.>")
                    if clean_m not in form_links:
                        form_links.append(clean_m)

            # Strict active-hiring filter: only capture real hiring posts (not generic commentary/tips)
            is_hiring, hiring_tags = is_genuine_hiring_post(text, emails, form_links, external_links, comment_links)
            if not is_hiring:
                continue
            for ht in hiring_tags:
                if ht not in tags:
                    tags.append(ht)

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

            full_desc = clean_post_description(text, author=author)
            job_role = extract_job_role(full_desc)
            author_url = (item.get("author_url") or "").strip()

            record = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "author": author[:60],
                "author_url": author_url,
                "job_role": job_role,
                "job_description": full_desc,
                "emails": ", ".join(emails),
                "form_links": ", ".join(form_links),
                "hyperlinks": ", ".join(external_links[:3]),
                "post_url": post_url,
                "tags": tags,
                "preview": full_desc[:320].replace("\n", " ").strip(),
                "id": hash_id
            }
            new_leads.append(record)
            seen_urns.add(hash_id)
            self._log(f"🎯 [LEAD DISCOVERED] {author[:25]} | Role: {job_role[:35]} | Emails: {', '.join(emails) or 'None'} | Forms: {', '.join(form_links) or 'None'}")

        self.state["seen_post_urns"] = list(seen_urns)[-500:]
        self._save_leads(new_leads)
        self._log(f"Feed Harvester finished: Collected {len(new_leads)} new leads.")
        return new_leads

    def _harvest_public_guest_jobs(self) -> list:
        """
        Public Guest Fallback: Fetches live verified 0-2 yrs roles from LinkedIn Guest API
        without requiring user session cookies.
        """
        queries = ["analyst", "product intern", "business analyst", "associate product manager"]
        fallback_leads = []
        seen_urns = set(self.state.get("seen_post_urns", []))

        for q in queries:
            url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={urllib.parse.quote(q)}&location=India&f_E=1%2C2"
            try:
                req = urllib.request.Request(
                    url, 
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
                
                titles = re.findall(r"<h3[^>]*class=\"base-search-card__title\"[^>]*>(.*?)</h3>", html, re.DOTALL)
                companies = re.findall(r"<h4[^>]*class=\"base-search-card__subtitle\"[^>]*>(.*?)</h4>", html, re.DOTALL)
                links = re.findall(r"<a[^>]*class=\"base-card__full-link[^\"]*\"[^>]*href=\"([^\"]+)\"", html)
                locations = re.findall(r"<span[^>]*class=\"job-search-card__location\"[^>]*>(.*?)</span>", html, re.DOTALL)

                for t, c, l, loc in zip(titles, companies, links, locations):
                    title = re.sub(r"<[^>]+>", "", t).strip()
                    comp = re.sub(r"<[^>]+>", "", c).strip()
                    link = l.split("?")[0].strip()
                    location = re.sub(r"<[^>]+>", "", loc).strip()
                    hash_id = str(abs(hash(link)))[:12]

                    if hash_id in seen_urns:
                        continue
                    seen_urns.add(hash_id)

                    lead = {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "author": comp,
                        "emails": "",
                        "form_links": link,
                        "hyperlinks": link,
                        "post_url": link,
                        "tags": ["Recruiting (0-2 Yrs)", "Verified Public Role"],
                        "preview": f"Role: {title} at {comp} ({location}). Target: 0-2 Years Experience. Direct Application.",
                        "id": hash_id
                    }
                    fallback_leads.append(lead)
                    self._log(f"🎯 [PUBLIC ROLE FOUND] {title} at {comp} ({location})")
            except Exception as e:
                logger.warning(f"Error querying guest jobs for query '{q}': {e}")

        self.state["seen_post_urns"] = list(seen_urns)[-500:]
        if fallback_leads:
            self._save_leads(fallback_leads)
            self._log(f"✅ Harvested {len(fallback_leads)} verified active junior/entry roles via public jobs engine.")
        return fallback_leads

    def _save_leads(self, leads: list):
        if not leads:
            return

        file_exists = os.path.exists(self.leads_csv)
        with open(self.leads_csv, "a", newline="", encoding="utf-8") as f:
            fieldnames = ["timestamp", "author", "author_url", "job_role", "emails", "form_links", "hyperlinks", "post_url", "job_description", "preview", "tags", "id"]
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            for l in leads:
                row = dict(l)
                if isinstance(row.get("tags"), list):
                    row["tags"] = ", ".join(row["tags"])
                writer.writerow(row)

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
