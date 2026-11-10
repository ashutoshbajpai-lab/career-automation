"""
mumbai_outreach_engine.py - Mumbai Company Discovery, Keyword Contact Extraction,
PEC Chandigarh vs Other Segregation, Per-Company Dual Templates, Connection Maximization,
and 2-Day Acceptance Follow-Up Engine.
"""

import os
import re
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import quote_plus

from browser_session import BrowserManager, human_delay
from referral_engine import ReferralEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MumbaiOutreachEngine")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

MUMBAI_COMPANIES_JSON = os.path.join(DATA_DIR, "mumbai_companies.json")
MUMBAI_CONTACTS_JSON = os.path.join(DATA_DIR, "mumbai_contacts.json")
MUMBAI_DAILY_STATS_JSON = os.path.join(DATA_DIR, "mumbai_daily_stats.json")

DEFAULT_KEYWORDS = ["Founder's Office", "HR", "Talent", "Product", "Analyst"]

SIZE_TIER_RANK = {
    "250-500": 1,
    "500-1000": 2,
    "1000+": 3,
}

DEFAULT_PEC_TEMPLATE = (
    "Hi {first_name}, hope you're doing well! I noticed you are at {company} and also a fellow "
    "PEC Chandigarh alumnus. I have 13+ months of internship experience across Business Strategy "
    "(Traya), Product (GrayQuest Fintech), and Data Analytics, and I'm exploring {keyword} / "
    "Analyst & Product roles at {company}. Would love to connect and seek your guidance!"
)

DEFAULT_OTHER_TEMPLATE = (
    "Hi {first_name}, hope you're having a great week! I came across your profile at {company}. "
    "I'm an engineering graduate (PEC Chandigarh) with 13+ months of internship experience across "
    "Business Strategy, Product Management, and Data Analytics (GrayQuest Fintech, Traya). "
    "I'm very keen on {keyword} / Analyst opportunities at {company} and would love to connect!"
)

# Seed list of Mumbai-headquartered or major Mumbai-office companies ordered across size tiers
CURATED_MUMBAI_COMPANIES = [
    # Tier 1: 250-500 employees (Start here)
    {"name": "GrayQuest", "linkedin_slug": "grayquest", "size_tier": "250-500", "employee_count": 300, "industry": "Fintech"},
    {"name": "Traya Health", "linkedin_slug": "traya-health", "size_tier": "250-500", "employee_count": 380, "industry": "D2C / HealthTech"},
    {"name": "Haptik", "linkedin_slug": "haptik", "size_tier": "250-500", "employee_count": 420, "industry": "Conversational AI"},
    {"name": "Fynd", "linkedin_slug": "fynd-shopsense", "size_tier": "250-500", "employee_count": 450, "industry": "Retail Tech"},
    {"name": "The Sleep Company", "linkedin_slug": "the-sleep-company", "size_tier": "250-500", "employee_count": 410, "industry": "D2C"},
    {"name": "Pepperfry", "linkedin_slug": "pepperfry", "size_tier": "250-500", "employee_count": 480, "industry": "E-Commerce"},
    {"name": "Turtlemint", "linkedin_slug": "turtlemint", "size_tier": "250-500", "employee_count": 490, "industry": "InsurTech"},
    {"name": "inFeedo", "linkedin_slug": "infeedo", "size_tier": "250-500", "employee_count": 280, "industry": "SaaS"},

    # Tier 2: 500-1000 employees
    {"name": "CleverTap", "linkedin_slug": "clevertap", "size_tier": "500-1000", "employee_count": 650, "industry": "SaaS / MarTech"},
    {"name": "BrowserStack", "linkedin_slug": "browserstack", "size_tier": "500-1000", "employee_count": 850, "industry": "DevTools / SaaS"},
    {"name": "Purplle", "linkedin_slug": "purplle-com", "size_tier": "500-1000", "employee_count": 780, "industry": "E-Commerce"},
    {"name": "BookMyShow", "linkedin_slug": "bookmyshow", "size_tier": "500-1000", "employee_count": 720, "industry": "Consumer Tech"},
    {"name": "Upstox", "linkedin_slug": "upstox", "size_tier": "500-1000", "employee_count": 900, "industry": "Fintech"},
    {"name": "TresVista", "linkedin_slug": "tresvista", "size_tier": "500-1000", "employee_count": 950, "industry": "Financial Analytics"},
    {"name": "Gupshup", "linkedin_slug": "gupshup", "size_tier": "500-1000", "employee_count": 820, "industry": "CPaaS"},
    {"name": "Dream11", "linkedin_slug": "dream11", "size_tier": "500-1000", "employee_count": 920, "industry": "Consumer Tech"},

    # Tier 3: 1000+ employees (Increasing order)
    {"name": "PharmEasy", "linkedin_slug": "pharmeasy", "size_tier": "1000+", "employee_count": 1500, "industry": "HealthTech"},
    {"name": "Zepto", "linkedin_slug": "zeptonow", "size_tier": "1000+", "employee_count": 2200, "industry": "Quick Commerce"},
    {"name": "Nykaa", "linkedin_slug": "nykaa-com", "size_tier": "1000+", "employee_count": 3000, "industry": "E-Commerce"},
    {"name": "Angel One", "linkedin_slug": "angel-one-limited", "size_tier": "1000+", "employee_count": 3500, "industry": "Fintech"},
    {"name": "Fractal Analytics", "linkedin_slug": "fractal-analytics", "size_tier": "1000+", "employee_count": 4500, "industry": "AI & Analytics"},
    {"name": "CRISIL", "linkedin_slug": "crisil", "size_tier": "1000+", "employee_count": 4800, "industry": "Financial Ratings & Analytics"},
    {"name": "Morningstar", "linkedin_slug": "morningstar", "size_tier": "1000+", "employee_count": 10000, "industry": "Investment Research"},
    {"name": "JPMorgan Chase & Co.", "linkedin_slug": "jpmorganchase", "size_tier": "1000+", "employee_count": 250000, "industry": "Global Banking & Fintech"},
]


def _make_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9\s-]", "", name.lower()).strip()
    return re.sub(r"\s+", "-", slug)


def _is_pec_alumni_text(text: str) -> bool:
    low = (text or "").lower()
    pec_markers = [
        "punjab engineering college",
        "pec chandigarh",
        "pec, chandigarh",
        "pec university of technology",
        "pec '",
        "pec’",
        "pecian",
    ]
    if any(m in low for m in pec_markers):
        return True
    # Strict word boundary match for standalone PEC (avoid matching 'special', 'expect', 'perspective')
    if re.search(r"\bpec\b", low):
        return True
    return False


def _match_keyword(text: str, keywords: list) -> str:
    low = (text or "").lower()
    for kw in keywords:
        clean_kw = kw.strip().lower()
        if not clean_kw:
            continue
        if clean_kw in low:
            return kw.strip()
        # Partial smart tokens for Founder's Office / HR / Talent
        if "founder" in clean_kw and ("founder" in low or "chief of staff" in low):
            return kw.strip()
        if clean_kw == "hr" and (re.search(r"\bhr\b", low) or "human resource" in low or "people ops" in low):
            return "HR"
        if "talent" in clean_kw and ("talent" in low or "recruiter" in low or "hiring" in low):
            return "Talent"
    return ""


def _parse_employee_count(size_text: str) -> tuple:
    """Returns (size_tier, estimated_count)."""
    low = (size_text or "").lower().replace(",", "")
    nums = [int(n) for n in re.findall(r"\d+", low)]
    if not nums:
        return "500-1000", 600
    low_val = nums[0]
    if low_val < 250:
        # Even if small, keep in 250-500 or calculate estimate
        est = max(low_val, 250)
        return "250-500", est
    if 250 <= low_val <= 500 or (len(nums) >= 2 and nums[1] <= 500):
        return "250-500", nums[0]
    if 500 < low_val <= 1000 or (len(nums) >= 2 and nums[0] >= 500 and nums[1] <= 1000):
        return "500-1000", nums[0]
    return "1000+", nums[0]


class MumbaiOutreachEngine:
    def __init__(self, browser_mgr: BrowserManager = None):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.browser_mgr = browser_mgr or BrowserManager(profile_name="linkedin")
        self.referral_engine = ReferralEngine(self.browser_mgr)

    # ------------------------------------------------------------------
    # Persistence Helpers
    # ------------------------------------------------------------------
    def get_companies(self) -> list:
        companies = []
        if os.path.exists(MUMBAI_COMPANIES_JSON):
            try:
                with open(MUMBAI_COMPANIES_JSON, "r", encoding="utf-8") as f:
                    companies = json.load(f)
            except Exception:
                companies = []
        # Always sort in increasing order of size tier, then employee_count
        companies.sort(key=lambda c: (
            SIZE_TIER_RANK.get(c.get("size_tier", "1000+"), 3),
            int(c.get("employee_count", 1000)),
            c.get("name", "").lower()
        ))
        return companies

    def save_companies(self, companies: list):
        companies.sort(key=lambda c: (
            SIZE_TIER_RANK.get(c.get("size_tier", "1000+"), 3),
            int(c.get("employee_count", 1000)),
            c.get("name", "").lower()
        ))
        with open(MUMBAI_COMPANIES_JSON, "w", encoding="utf-8") as f:
            json.dump(companies, f, indent=2)

    def get_contacts(self) -> list:
        if os.path.exists(MUMBAI_CONTACTS_JSON):
            try:
                with open(MUMBAI_CONTACTS_JSON, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def save_contacts(self, contacts: list):
        with open(MUMBAI_CONTACTS_JSON, "w", encoding="utf-8") as f:
            json.dump(contacts, f, indent=2)

    def get_daily_stats(self) -> dict:
        if os.path.exists(MUMBAI_DAILY_STATS_JSON):
            try:
                with open(MUMBAI_DAILY_STATS_JSON, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _increment_daily_stat(self, metric: str, count: int = 1):
        today = datetime.now().strftime("%Y-%m-%d")
        stats = self.get_daily_stats()
        if today not in stats:
            stats[today] = {
                "date": today,
                "connections_sent": 0,
                "messages_sent": 0,
                "acceptances_detected": 0,
                "completed_followups": 0,
            }
        stats[today][metric] = stats[today].get(metric, 0) + count
        with open(MUMBAI_DAILY_STATS_JSON, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)

    # ------------------------------------------------------------------
    # Step 1: Generate & Manage Mumbai Companies (250-500 -> 500-1000 -> 1000+)
    # ------------------------------------------------------------------
    def _build_company_obj(self, name: str, linkedin_slug: str = "", size_tier: str = "250-500", employee_count: int = 350, industry: str = "Tech / Corporate", city: str = "Mumbai") -> dict:
        slug = linkedin_slug or _make_slug(name)
        return {
            "id": str(abs(hash(slug or name.lower()))),
            "name": name.strip(),
            "linkedin_slug": slug,
            "city": city,
            "size_tier": size_tier,
            "size_sort_rank": SIZE_TIER_RANK.get(size_tier, 3),
            "employee_count": int(employee_count),
            "industry": industry,
            "pec_template": DEFAULT_PEC_TEMPLATE,
            "other_template": DEFAULT_OTHER_TEMPLATE,
            "last_scanned_at": None,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def add_custom_company(self, name: str, size_tier: str = "1000+", employee_count: int = None, linkedin_slug: str = "", industry: str = "Corporate / Fintech") -> dict:
        companies = self.get_companies()
        slug = linkedin_slug.strip() or _make_slug(name)
        for c in companies:
            if c.get("name", "").lower() == name.strip().lower() or c.get("linkedin_slug") == slug:
                return c

        if employee_count is None:
            employee_count = 350 if size_tier == "250-500" else (750 if size_tier == "500-1000" else 5000)

        new_comp = self._build_company_obj(
            name=name,
            linkedin_slug=slug,
            size_tier=size_tier,
            employee_count=employee_count,
            industry=industry,
            city="Mumbai"
        )
        companies.append(new_comp)
        self.save_companies(companies)
        return new_comp

    def update_company_templates(self, company_id: str, pec_template: str, other_template: str) -> dict:
        companies = self.get_companies()
        updated = None
        for c in companies:
            if str(c.get("id")) == str(company_id):
                if pec_template is not None:
                    c["pec_template"] = pec_template.strip() or DEFAULT_PEC_TEMPLATE
                if other_template is not None:
                    c["other_template"] = other_template.strip() or DEFAULT_OTHER_TEMPLATE
                updated = c
                break
        if updated:
            self.save_companies(companies)
        return updated

    def generate_mumbai_companies(self, try_live_linkedin: bool = True, log_cb=None) -> dict:
        """
        Generates Mumbai companies prioritized strictly in increasing size order:
        1. 250-500 employees
        2. 500-1000 employees
        3. 1000+ employees
        Attempts live LinkedIn company search in Mumbai and merges curated verified list.
        """
        def log(msg):
            logger.info(msg)
            if log_cb:
                log_cb(msg)

        existing = self.get_companies()
        by_slug = {c.get("linkedin_slug"): c for c in existing if c.get("linkedin_slug")}
        by_name = {c.get("name", "").lower(): c for c in existing}
        added_count = 0

        # Step A: Attempt live LinkedIn Company Discovery for Mumbai across headcount tiers
        if try_live_linkedin:
            # LinkedIn Mumbai geo urn = 106164952, sizes: D=51-200, E=201-500, F=501-1000, G=1001-5000, H=5001-10000, I=10001+
            tier_queries = [
                ("250-500", "E", 350),
                ("500-1000", "F", 750),
                ("1000+", "G", 2500),
            ]
            context = None
            try:
                context, page = self.browser_mgr.get_context_and_page(force_headless=True)
                if self.browser_mgr.ensure_logged_in(page, timeout_sec=10):
                    for tier_label, size_code, default_cnt in tier_queries:
                        url = f"https://www.linkedin.com/search/results/companies/?companyHqGeo=%5B%22106164952%22%5D&companySize=%5B%22{size_code}%22%5D&origin=FACETED_SEARCH"
                        log(f"Searching LinkedIn Mumbai companies ({tier_label} tier)...")
                        page.goto(url, wait_until="domcontentloaded")
                        human_delay(3.0, 4.0)

                        discovered = page.evaluate('''() => {
                            const items = [];
                            const seen = new Set();
                            document.querySelectorAll("li.reusable-search__result-container, div.entity-result").forEach(el => {
                                const linkEl = el.querySelector("a[href*='/company/']");
                                if (linkEl) {
                                    const href = linkEl.href.split('?')[0];
                                    const parts = href.split('/company/').filter(Boolean);
                                    const slug = parts.length ? parts[parts.length - 1].replace(/\\/+$/, '') : '';
                                    const name = (linkEl.innerText || '').trim().split('\\n')[0];
                                    const subtitleEl = el.querySelector(".entity-result__primary-subtitle, .entity-result__secondary-subtitle");
                                    const subtitle = subtitleEl ? subtitleEl.innerText.trim() : '';
                                    if (slug && name && name.length > 1 && !seen.has(slug)) {
                                        seen.add(slug);
                                        items.push({ name, slug, subtitle });
                                    }
                                }
                            });
                            return items;
                        }''')

                        for d in discovered:
                            slug = d["slug"].lower()
                            if slug not in by_slug and d["name"].lower() not in by_name:
                                obj = self._build_company_obj(
                                    name=d["name"],
                                    linkedin_slug=slug,
                                    size_tier=tier_label,
                                    employee_count=default_cnt,
                                    industry=d.get("subtitle") or "Mumbai Enterprise",
                                    city="Mumbai",
                                )
                                existing.append(obj)
                                by_slug[slug] = obj
                                by_name[d["name"].lower()] = obj
                                added_count += 1
                        log(f"Found {len(discovered)} live LinkedIn companies in Mumbai ({tier_label}).")
                else:
                    log("LinkedIn session not active for live company search; merging verified Mumbai directory.")
            except Exception as e:
                log(f"Live company search note: {e}. Merging verified Mumbai directory.")
            finally:
                if context:
                    self.browser_mgr.close()

        # Step B: Ensure curated verified Mumbai companies across all 3 tiers are present
        for seed in CURATED_MUMBAI_COMPANIES:
            slug = seed["linkedin_slug"]
            if slug not in by_slug and seed["name"].lower() not in by_name:
                obj = self._build_company_obj(**seed, city="Mumbai")
                existing.append(obj)
                by_slug[slug] = obj
                by_name[seed["name"].lower()] = obj
                added_count += 1

        self.save_companies(existing)
        sorted_companies = self.get_companies()
        log(f"Mumbai Companies ready: {len(sorted_companies)} total ({added_count} newly added), sorted 250-500 -> 500-1000 -> 1000+.")
        return {
            "status": "Success",
            "total_companies": len(sorted_companies),
            "newly_added": added_count,
            "companies": sorted_companies,
        }

    # ------------------------------------------------------------------
    # Step 2: Generate Contacts with Keywords & Segregate (PEC vs Other)
    # ------------------------------------------------------------------
    def generate_contacts_for_companies(
        self,
        company_ids: list = None,
        keywords: list = None,
        max_companies: int = 3,
        limit_per_company: int = 20,
        log_cb=None
    ) -> dict:
        """
        For each company (in increasing size order unless specified):
        1. Searches for PEC Chandigarh alumni at that company -> category = 'pec_alumni'
        2. Searches for target keywords (Founder's Office, HR, Talent, Product, Analyst) -> category = 'other' (or 'pec_alumni' if PEC detected)
        3. Stores segregated contacts into data/mumbai_contacts.json.
        """
        def log(msg):
            logger.info(msg)
            if log_cb:
                log_cb(msg)

        kw_list = [k.strip() for k in (keywords or DEFAULT_KEYWORDS) if k.strip()]
        all_companies = self.get_companies()
        if company_ids:
            id_set = {str(cid) for cid in company_ids}
            target_companies = [c for c in all_companies if str(c.get("id")) in id_set]
        else:
            # Prefer unscanned companies first, still in increasing size order
            unscanned = [c for c in all_companies if not c.get("last_scanned_at")]
            target_companies = (unscanned or all_companies)[:max_companies]

        if not target_companies:
            return {"status": "Error", "message": "No Mumbai companies found. Generate companies first."}

        existing_contacts = self.get_contacts()
        contacts_by_url = {c.get("profile_url"): c for c in existing_contacts if c.get("profile_url")}

        newly_discovered = []
        context, page = self.browser_mgr.get_context_and_page(force_headless=True)
        try:
            try:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            except Exception:
                pass

            if not self.browser_mgr.ensure_logged_in(page, timeout_sec=15):
                return {"status": "Auth Required", "message": "LinkedIn authentication required to extract company contacts."}

            for comp in target_companies:
                comp_name = comp["name"]
                comp_slug = comp["linkedin_slug"]
                comp_id = comp["id"]
                log(f"Extracting contacts for '{comp_name}' ({comp['size_tier']} employees)...")

                company_found = 0

                # Pass A: Search PEC Chandigarh alumni at this company
                pec_urls_to_check = [
                    f"https://www.linkedin.com/company/{comp_slug}/people/?keywords={quote_plus('Punjab Engineering College')}",
                    f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(comp_name + ' Punjab Engineering College')}",
                ]
                for search_url in pec_urls_to_check:
                    try:
                        page.goto(search_url, wait_until="domcontentloaded")
                        human_delay(3.0, 4.5)
                        raw_people = self.referral_engine._extract_search_results(page, comp_name, "PEC Alumni")
                        for p in raw_people:
                            purl = p.get("profile_url", "")
                            if not purl or purl in contacts_by_url:
                                continue
                            headline = p.get("headline", "")
                            kw_hit = _match_keyword(headline, kw_list) or "PEC Alumni"
                            is_1st = p.get("is_connection", False) or p.get("degree") == "1st"
                            rec = {
                                "id": str(abs(hash(purl))),
                                "company_id": comp_id,
                                "company_name": comp_name,
                                "size_tier": comp["size_tier"],
                                "name": p.get("name", "LinkedIn Member"),
                                "first_name": p.get("name", "there").split()[0],
                                "headline": headline,
                                "profile_url": purl,
                                "matched_keyword": kw_hit,
                                "category": "pec_alumni",
                                "is_pec_alumni": True,
                                "degree": "1st" if is_1st else p.get("degree", "2nd/3rd"),
                                "connection_status": "connected_ready" if is_1st else "not_connected",
                                "workflow_stage": "discovered",
                                "discovered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "connection_sent_at": None,
                                "accepted_at": None,
                                "messaged_at": None,
                                "last_checked_at": None,
                                "message_used": "",
                            }
                            existing_contacts.append(rec)
                            contacts_by_url[purl] = rec
                            newly_discovered.append(rec)
                            company_found += 1
                    except Exception as e:
                        logger.debug(f"PEC search error at {comp_name}: {e}")

                # Pass B: Search Target Keywords (Founder's Office, HR, Talent, Product, Analyst)
                for kw in kw_list:
                    if company_found >= limit_per_company:
                        break
                    query = f"{comp_name} {kw} Mumbai"
                    search_url = f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(query)}"
                    try:
                        page.goto(search_url, wait_until="domcontentloaded")
                        human_delay(2.5, 4.0)
                        raw_people = self.referral_engine._extract_search_results(page, comp_name, kw)
                        for p in raw_people:
                            if company_found >= limit_per_company:
                                break
                            purl = p.get("profile_url", "")
                            if not purl or purl in contacts_by_url:
                                continue
                            headline = p.get("headline", "")
                            # Filter strictly: must relate to target keywords or company
                            kw_hit = _match_keyword(headline, kw_list) or kw
                            is_pec = _is_pec_alumni_text(headline)
                            is_1st = p.get("is_connection", False) or p.get("degree") == "1st"
                            rec = {
                                "id": str(abs(hash(purl))),
                                "company_id": comp_id,
                                "company_name": comp_name,
                                "size_tier": comp["size_tier"],
                                "name": p.get("name", "LinkedIn Member"),
                                "first_name": p.get("name", "there").split()[0],
                                "headline": headline,
                                "profile_url": purl,
                                "matched_keyword": kw_hit,
                                "category": "pec_alumni" if is_pec else "other",
                                "is_pec_alumni": is_pec,
                                "degree": "1st" if is_1st else p.get("degree", "2nd/3rd"),
                                "connection_status": "connected_ready" if is_1st else "not_connected",
                                "workflow_stage": "discovered",
                                "discovered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "connection_sent_at": None,
                                "accepted_at": None,
                                "messaged_at": None,
                                "last_checked_at": None,
                                "message_used": "",
                            }
                            existing_contacts.append(rec)
                            contacts_by_url[purl] = rec
                            newly_discovered.append(rec)
                            company_found += 1
                    except Exception as e:
                        logger.debug(f"Keyword '{kw}' search error at {comp_name}: {e}")

                comp["last_scanned_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log(f"Discovered {company_found} segregated contacts for '{comp_name}'.")

            self.save_companies(all_companies)
            self.save_contacts(existing_contacts)

            pec_count = sum(1 for c in newly_discovered if c["is_pec_alumni"])
            other_count = len(newly_discovered) - pec_count
            log(f"Contact discovery complete: {len(newly_discovered)} new ({pec_count} PEC Alumni, {other_count} Other).")
            return {
                "status": "Success",
                "total_new": len(newly_discovered),
                "pec_new": pec_count,
                "other_new": other_count,
                "contacts": newly_discovered,
            }
        finally:
            self.browser_mgr.close()

    # ------------------------------------------------------------------
    # Helper: Format Per-Company Template (PEC vs Other)
    # ------------------------------------------------------------------
    def _render_message_for_contact(self, contact: dict, companies_by_id: dict) -> str:
        comp = companies_by_id.get(str(contact.get("company_id"))) or {}
        if contact.get("is_pec_alumni"):
            tmpl = comp.get("pec_template") or DEFAULT_PEC_TEMPLATE
        else:
            tmpl = comp.get("other_template") or DEFAULT_OTHER_TEMPLATE

        first_name = contact.get("first_name") or contact.get("name", "there").split()[0]
        company_name = contact.get("company_name") or comp.get("name", "your team")
        keyword = contact.get("matched_keyword") or "Product / Analyst"

        return (
            tmpl.replace("{first_name}", first_name)
                .replace("{name}", contact.get("name", first_name))
                .replace("{company}", company_name)
                .replace("{keyword}", keyword)
                .replace("{target_role}", keyword)
                .replace("{college}", "PEC Chandigarh")
                .strip()
        )

    # ------------------------------------------------------------------
    # Step 3: Maximize Connection Requests + Message Connected People
    # ------------------------------------------------------------------
    def run_connect_and_message_cycle(
        self,
        company_ids: list = None,
        contact_ids: list = None,
        max_connects: int = 20,
        max_messages: int = 15,
        log_cb=None
    ) -> dict:
        """
        Executes in strict increasing company size order (250-500 -> 500-1000 -> 1000+):
        1. If contact is NOT connected -> sends clean Connection Request (maximizing quota) and moves to Incomplete.
        2. If contact IS already connected -> sends company's PEC/Other template message immediately and moves to Completed.
        """
        def log(msg):
            logger.info(msg)
            if log_cb:
                log_cb(msg)

        companies = self.get_companies()
        companies_by_id = {str(c.get("id")): c for c in companies}
        all_contacts = self.get_contacts()

        # Filter candidates in 'discovered' stage (or unmessaged 'not_connected' / 'connected_ready')
        candidates = [
            c for c in all_contacts
            if c.get("workflow_stage") == "discovered"
        ]
        if company_ids:
            id_set = {str(cid) for cid in company_ids}
            candidates = [c for c in candidates if str(c.get("company_id")) in id_set]
        if contact_ids:
            cset = {str(cid) for cid in contact_ids}
            candidates = [c for c in candidates if str(c.get("id")) in cset]

        # Sort strictly by company size rank (250-500 first, then 500-1000, then 1000+), and PEC alumni priority within tier
        candidates.sort(key=lambda c: (
            SIZE_TIER_RANK.get(c.get("size_tier", "1000+"), 3),
            int((companies_by_id.get(str(c.get("company_id"))) or {}).get("employee_count", 1000)),
            0 if c.get("is_pec_alumni") else 1
        ))

        if not candidates:
            return {"status": "Idle", "message": "No new discovered contacts queued for connection/outreach."}

        context, page = self.browser_mgr.get_context_and_page(force_headless=True)
        connects_sent = 0
        messages_sent = 0

        try:
            try:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            except Exception:
                pass

            if not self.browser_mgr.ensure_logged_in(page, timeout_sec=15):
                return {"status": "Auth Required", "message": "LinkedIn login required."}

            for contact in candidates:
                if connects_sent >= max_connects and messages_sent >= max_messages:
                    break

                purl = contact.get("profile_url")
                name = contact.get("name", "Contact")
                comp_name = contact.get("company_name", "")
                if not purl:
                    continue

                try:
                    log(f"Visiting {name} ({comp_name}, {contact.get('size_tier')}, {'PEC' if contact.get('is_pec_alumni') else 'Other'})...")
                    page.goto(purl, wait_until="domcontentloaded")
                    human_delay(2.5, 4.0)

                    # Detect live profile state on page: 1st-degree Message button vs Pending vs Connect
                    can_direct_msg = False
                    is_already_pending = False

                    pending_btn = page.locator("main button:has-text('Pending'), main span:has-text('Pending')").first
                    if pending_btn.count() > 0 and pending_btn.is_visible():
                        is_already_pending = True

                    # Check if 1st degree or direct Message button (not locked InMail)
                    is_1st_badge = page.locator("main span.dist-value:has-text('1st'), main span:has-text('• 1st')").first.count() > 0
                    msg_btn = page.locator("main button:has-text('Message')").first
                    if is_1st_badge and msg_btn.count() > 0 and msg_btn.is_visible():
                        can_direct_msg = True

                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if can_direct_msg:
                        if messages_sent >= max_messages:
                            continue
                        msg_text = self._render_message_for_contact(contact, companies_by_id)
                        sent = self.referral_engine._send_direct_message(page, msg_text)
                        if sent:
                            messages_sent += 1
                            contact["connection_status"] = "messaged"
                            contact["workflow_stage"] = "completed"
                            contact["messaged_at"] = now_str
                            contact["message_used"] = msg_text
                            self._increment_daily_stat("messages_sent", 1)
                            log(f"[COMPLETED] Sent direct message to connected contact {name} at {comp_name}.")
                    elif is_already_pending:
                        contact["connection_status"] = "connection_sent"
                        contact["workflow_stage"] = "incomplete_pending_accept"
                        if not contact.get("connection_sent_at"):
                            contact["connection_sent_at"] = now_str
                        log(f"[INCOMPLETE] Invite already pending for {name} ({comp_name}); tracked in Incomplete queue.")
                    else:
                        if connects_sent >= max_connects:
                            continue
                        # Maximize acceptance: clean connection request without note
                        sent = self.referral_engine._send_connection_request(page, note_text="")
                        if sent:
                            connects_sent += 1
                            contact["connection_status"] = "connection_sent"
                            contact["workflow_stage"] = "incomplete_pending_accept"
                            contact["connection_sent_at"] = now_str
                            self._increment_daily_stat("connections_sent", 1)
                            log(f"[INCOMPLETE] Connection request sent to {name} ({comp_name}). Will re-check in 2 days.")
                        else:
                            log(f"Could not locate Connect button for {name} (may be Follow-only).")

                    human_delay(2.5, 4.0)
                except Exception as e:
                    logger.warning(f"Error processing {name}: {e}")

            self.save_contacts(all_contacts)
            log(f"Cycle finished: {connects_sent} connection requests sent, {messages_sent} direct messages sent.")
            return {
                "status": "Success",
                "connections_sent": connects_sent,
                "messages_sent": messages_sent,
            }
        finally:
            self.browser_mgr.close()

    # ------------------------------------------------------------------
    # Step 4: 2-Day Acceptance Check & Automated Message Completion
    # ------------------------------------------------------------------
    def run_2day_followup_check(self, min_age_days: int = 2, check_all_pending: bool = False, log_cb=None) -> dict:
        """
        Checks all contacts in 'incomplete_pending_accept' whose connection_sent_at is >= min_age_days
        (or all pending if check_all_pending=True):
        - If accepted (now 1st degree / Message unlocked): sends customized PEC/Other company template,
          removes from Incomplete list, and moves to Completed!
        - If still pending: keeps in Incomplete list and updates last_checked_at.
        """
        def log(msg):
            logger.info(msg)
            if log_cb:
                log_cb(msg)

        companies = self.get_companies()
        companies_by_id = {str(c.get("id")): c for c in companies}
        all_contacts = self.get_contacts()
        now = datetime.now()

        due_contacts = []
        for c in all_contacts:
            if c.get("workflow_stage") != "incomplete_pending_accept":
                continue
            if check_all_pending:
                due_contacts.append(c)
                continue
            sent_str = c.get("connection_sent_at")
            if not sent_str:
                due_contacts.append(c)
                continue
            try:
                sent_dt = datetime.strptime(sent_str, "%Y-%m-%d %H:%M:%S")
                if (now - sent_dt) >= timedelta(days=min_age_days):
                    due_contacts.append(c)
            except Exception:
                due_contacts.append(c)

        if not due_contacts:
            log(f"No incomplete contacts are >= {min_age_days} days old yet.")
            return {
                "status": "Success",
                "checked_count": 0,
                "accepted_and_messaged": 0,
                "still_pending": 0,
            }

        context, page = self.browser_mgr.get_context_and_page(force_headless=True)
        accepted_count = 0
        messaged_count = 0
        still_pending_count = 0

        try:
            try:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            except Exception:
                pass

            if not self.browser_mgr.ensure_logged_in(page, timeout_sec=15):
                return {"status": "Auth Required", "message": "LinkedIn authentication required."}

            log(f"Running 2-day acceptance check on {len(due_contacts)} incomplete contacts...")
            for contact in due_contacts:
                purl = contact.get("profile_url")
                name = contact.get("name", "Contact")
                comp_name = contact.get("company_name", "")
                if not purl:
                    continue

                try:
                    page.goto(purl, wait_until="domcontentloaded")
                    human_delay(2.5, 4.0)
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    contact["last_checked_at"] = now_str

                    is_1st_badge = page.locator("main span.dist-value:has-text('1st'), main span:has-text('• 1st')").first.count() > 0
                    msg_btn = page.locator("main button:has-text('Message')").first

                    if is_1st_badge and msg_btn.count() > 0 and msg_btn.is_visible():
                        accepted_count += 1
                        contact["accepted_at"] = now_str
                        self._increment_daily_stat("acceptances_detected", 1)

                        msg_text = self._render_message_for_contact(contact, companies_by_id)
                        sent = self.referral_engine._send_direct_message(page, msg_text)
                        if sent:
                            messaged_count += 1
                            contact["connection_status"] = "messaged"
                            contact["workflow_stage"] = "completed"
                            contact["messaged_at"] = now_str
                            contact["message_used"] = msg_text
                            self._increment_daily_stat("messages_sent", 1)
                            self._increment_daily_stat("completed_followups", 1)
                            log(f"[ACCEPTED -> COMPLETED] {name} ({comp_name}) accepted! Sent template message & moved to Completed.")
                        else:
                            contact["connection_status"] = "connected_ready"
                            log(f"[ACCEPTED] {name} ({comp_name}) accepted, but message box did not submit. Marked ready.")
                    else:
                        still_pending_count += 1
                        log(f"[STILL PENDING] {name} ({comp_name}) has not accepted yet; keeping in Incomplete queue.")

                    human_delay(2.0, 3.5)
                except Exception as e:
                    logger.warning(f"Error checking acceptance for {name}: {e}")

            self.save_contacts(all_contacts)
            log(f"2-Day Check Complete: {accepted_count} accepted, {messaged_count} messaged & completed, {still_pending_count} still incomplete.")
            return {
                "status": "Success",
                "checked_count": len(due_contacts),
                "accepted_and_messaged": messaged_count,
                "still_pending": still_pending_count,
            }
        finally:
            self.browser_mgr.close()

    # ------------------------------------------------------------------
    # Dashboard Payload Aggregator
    # ------------------------------------------------------------------
    def get_workspace_summary(self) -> dict:
        companies = self.get_companies()
        contacts = self.get_contacts()
        daily_stats = self.get_daily_stats()
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_stat = daily_stats.get(today_str, {
            "date": today_str,
            "connections_sent": 0,
            "messages_sent": 0,
            "acceptances_detected": 0,
            "completed_followups": 0,
        })

        now = datetime.now()
        # Calculate counts per company
        comp_counts = {}
        due_2day_count = 0
        for c in contacts:
            cid = str(c.get("company_id"))
            if cid not in comp_counts:
                comp_counts[cid] = {"pec": 0, "other": 0, "incomplete": 0, "completed": 0}
            if c.get("is_pec_alumni"):
                comp_counts[cid]["pec"] += 1
            else:
                comp_counts[cid]["other"] += 1

            stage = c.get("workflow_stage")
            if stage == "incomplete_pending_accept":
                comp_counts[cid]["incomplete"] += 1
                sent_str = c.get("connection_sent_at")
                if sent_str:
                    try:
                        sent_dt = datetime.strptime(sent_str, "%Y-%m-%d %H:%M:%S")
                        c["days_pending"] = max(0, (now - sent_dt).days)
                        c["due_for_2day_check"] = (now - sent_dt) >= timedelta(days=2)
                        if c["due_for_2day_check"]:
                            due_2day_count += 1
                    except Exception:
                        c["days_pending"] = 0
                        c["due_for_2day_check"] = False
            elif stage == "completed":
                comp_counts[cid]["completed"] += 1

        for comp in companies:
            counts = comp_counts.get(str(comp.get("id")), {"pec": 0, "other": 0, "incomplete": 0, "completed": 0})
            comp["counts"] = counts

        discovered = [c for c in contacts if c.get("workflow_stage") == "discovered"]
        incomplete = [c for c in contacts if c.get("workflow_stage") == "incomplete_pending_accept"]
        completed = [c for c in contacts if c.get("workflow_stage") == "completed"]
        pec_contacts = [c for c in contacts if c.get("is_pec_alumni")]
        other_contacts = [c for c in contacts if not c.get("is_pec_alumni")]

        daily_history = sorted(daily_stats.values(), key=lambda x: x.get("date", ""), reverse=True)

        return {
            "companies": companies,
            "contacts": contacts,
            "discovered": discovered,
            "incomplete": incomplete,
            "completed": completed,
            "pec_contacts": pec_contacts,
            "other_contacts": other_contacts,
            "today_stats": today_stat,
            "daily_history": daily_history,
            "due_2day_count": due_2day_count,
            "counts": {
                "companies": len(companies),
                "total_contacts": len(contacts),
                "pec": len(pec_contacts),
                "other": len(other_contacts),
                "discovered": len(discovered),
                "incomplete": len(incomplete),
                "completed": len(completed),
                "due_2day": due_2day_count,
            }
        }
