"""
mumbai_outreach_engine.py - Mumbai Company Discovery (Guest API + Public Company Size/HQ Enrichment
+ Logged-In Paginated Search), Keyword Contact Extraction, PEC Chandigarh vs Other Segregation,
Per-Company Dual Templates, Connection Maximization, Sending List & Daily Acceptance Follow-Up Engine.
"""

import os
import re
import time
import html as html_lib
import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime
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
    "<250": 4,
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

# Expanded seed directory of verified Mumbai companies across 250-500, 500-1000, and 1000+ tiers
CURATED_MUMBAI_COMPANIES = [
    # Tier 1: 250-500 employees (Start here)
    {"name": "inFeedo", "linkedin_slug": "infeedo", "size_tier": "250-500", "employee_count": 280, "industry": "SaaS / HRTech"},
    {"name": "GrayQuest", "linkedin_slug": "grayquest", "size_tier": "250-500", "employee_count": 300, "industry": "Fintech"},
    {"name": "Traya Health", "linkedin_slug": "traya-health", "size_tier": "250-500", "employee_count": 380, "industry": "D2C / HealthTech"},
    {"name": "The Sleep Company", "linkedin_slug": "the-sleep-company-official", "size_tier": "250-500", "employee_count": 410, "industry": "D2C"},
    {"name": "LogiNext", "linkedin_slug": "loginext-solutions", "size_tier": "250-500", "employee_count": 390, "industry": "Logistics SaaS"},
    {"name": "Haptik", "linkedin_slug": "haptik", "size_tier": "250-500", "employee_count": 420, "industry": "Conversational AI"},
    {"name": "Fynd", "linkedin_slug": "fynd-shopsense", "size_tier": "250-500", "employee_count": 450, "industry": "Retail Tech"},
    {"name": "Pepperfry", "linkedin_slug": "pepperfry", "size_tier": "250-500", "employee_count": 480, "industry": "E-Commerce"},
    {"name": "Turtlemint", "linkedin_slug": "turtlemint", "size_tier": "250-500", "employee_count": 490, "industry": "InsurTech"},
    {"name": "WebEngage", "linkedin_slug": "webengage", "size_tier": "250-500", "employee_count": 340, "industry": "MarTech SaaS"},
    {"name": "Mintifi", "linkedin_slug": "mintifi", "size_tier": "250-500", "employee_count": 360, "industry": "Supply Chain Fintech"},
    {"name": "mSwipe", "linkedin_slug": "mswipe-technologies", "size_tier": "250-500", "employee_count": 440, "industry": "Payments Fintech"},
    {"name": "Bureau.id", "linkedin_slug": "bureau-id", "size_tier": "250-500", "employee_count": 260, "industry": "Fraud & Identity AI"},
    {"name": "Freopay", "linkedin_slug": "freo-money", "size_tier": "250-500", "employee_count": 310, "industry": "Consumer Fintech"},
    {"name": "KISSHT", "linkedin_slug": "kissht", "size_tier": "250-500", "employee_count": 460, "industry": "Digital Lending"},
    {"name": "Zouk", "linkedin_slug": "zouk", "size_tier": "250-500", "employee_count": 290, "industry": "D2C Lifestyle"},
    {"name": "Pilgrim", "linkedin_slug": "discoverpilgrim", "size_tier": "250-500", "employee_count": 320, "industry": "D2C Personal Care"},
    {"name": "Neogrowth", "linkedin_slug": "neogrowth-credit-pvt-ltd", "size_tier": "250-500", "employee_count": 470, "industry": "SME Lending"},
    {"name": "Paymate", "linkedin_slug": "paymate", "size_tier": "250-500", "employee_count": 330, "industry": "B2B Payments"},
    {"name": "Coverfox", "linkedin_slug": "coverfox-insurance", "size_tier": "250-500", "employee_count": 350, "industry": "InsurTech"},

    # Tier 2: 500-1000 employees
    {"name": "CleverTap", "linkedin_slug": "clevertap", "size_tier": "500-1000", "employee_count": 650, "industry": "SaaS / MarTech"},
    {"name": "BrowserStack", "linkedin_slug": "browserstack", "size_tier": "500-1000", "employee_count": 850, "industry": "DevTools / SaaS"},
    {"name": "Purplle", "linkedin_slug": "purplle-com", "size_tier": "500-1000", "employee_count": 780, "industry": "E-Commerce"},
    {"name": "BookMyShow", "linkedin_slug": "bookmyshow", "size_tier": "500-1000", "employee_count": 720, "industry": "Consumer Tech"},
    {"name": "Upstox", "linkedin_slug": "upstox", "size_tier": "500-1000", "employee_count": 900, "industry": "Fintech / Broking"},
    {"name": "TresVista", "linkedin_slug": "tresvista", "size_tier": "500-1000", "employee_count": 950, "industry": "Financial Analytics"},
    {"name": "Gupshup", "linkedin_slug": "gupshup", "size_tier": "500-1000", "employee_count": 820, "industry": "CPaaS"},
    {"name": "Dream11", "linkedin_slug": "dream11", "size_tier": "500-1000", "employee_count": 920, "industry": "Consumer Tech"},
    {"name": "Lendingkart", "linkedin_slug": "lendingkart", "size_tier": "500-1000", "employee_count": 800, "industry": "Fintech"},
    {"name": "PaySense", "linkedin_slug": "paysense", "size_tier": "500-1000", "employee_count": 620, "industry": "Consumer Lending"},
    {"name": "Rebel Foods", "linkedin_slug": "rebel-foods", "size_tier": "500-1000", "employee_count": 980, "industry": "Cloud Kitchens / D2C"},
    {"name": "Sugar Cosmetics", "linkedin_slug": "sugar-cosmetics", "size_tier": "500-1000", "employee_count": 760, "industry": "D2C Beauty"},
    {"name": "Furlenco", "linkedin_slug": "furlenco", "size_tier": "500-1000", "employee_count": 580, "industry": "Consumer Subscription"},
    {"name": "InCred Finance", "linkedin_slug": "incred-finance", "size_tier": "500-1000", "employee_count": 870, "industry": "NBFC / Fintech"},
    {"name": "FlexiLoans", "linkedin_slug": "flexiloans", "size_tier": "500-1000", "employee_count": 560, "industry": "MSME Fintech"},
    {"name": "Juspay", "linkedin_slug": "juspay-technologies", "size_tier": "500-1000", "employee_count": 790, "industry": "Payments Infrastructure"},
    {"name": "Good Glamm Group", "linkedin_slug": "good-glamm-group", "size_tier": "500-1000", "employee_count": 890, "industry": "D2C / Content-to-Commerce"},
    {"name": "Acko", "linkedin_slug": "acko", "size_tier": "500-1000", "employee_count": 840, "industry": "InsurTech"},

    # Tier 3: 1000+ employees (Increasing order)
    {"name": "PharmEasy", "linkedin_slug": "pharmeasy", "size_tier": "1000+", "employee_count": 1500, "industry": "HealthTech"},
    {"name": "Zepto", "linkedin_slug": "zeptonow", "size_tier": "1000+", "employee_count": 2200, "industry": "Quick Commerce"},
    {"name": "Nykaa", "linkedin_slug": "nykaa-com", "size_tier": "1000+", "employee_count": 3000, "industry": "E-Commerce"},
    {"name": "Angel One", "linkedin_slug": "angel-one-limited", "size_tier": "1000+", "employee_count": 3500, "industry": "Fintech"},
    {"name": "Pine Labs", "linkedin_slug": "pine-labs", "size_tier": "1000+", "employee_count": 3800, "industry": "Merchant Payments"},
    {"name": "Fractal Analytics", "linkedin_slug": "fractal-analytics", "size_tier": "1000+", "employee_count": 4500, "industry": "AI & Analytics"},
    {"name": "CRISIL", "linkedin_slug": "crisil", "size_tier": "1000+", "employee_count": 4800, "industry": "Financial Ratings & Analytics"},
    {"name": "BillDesk", "linkedin_slug": "billdesk", "size_tier": "1000+", "employee_count": 1800, "industry": "Payments Fintech"},
    {"name": "CitiusTech", "linkedin_slug": "citiustech", "size_tier": "1000+", "employee_count": 7500, "industry": "Healthcare Tech"},
    {"name": "Synechron", "linkedin_slug": "synechron", "size_tier": "1000+", "employee_count": 14000, "industry": "FinTech Consulting"},
    {"name": "Morningstar", "linkedin_slug": "morningstar", "size_tier": "1000+", "employee_count": 10000, "industry": "Investment Research"},
    {"name": "IDFC FIRST Bank", "linkedin_slug": "idfcfirstbank", "size_tier": "1000+", "employee_count": 35000, "industry": "Banking"},
    {"name": "Kotak Mahindra Bank", "linkedin_slug": "kotak-mahindra-bank", "size_tier": "1000+", "employee_count": 75000, "industry": "Banking & Finance"},
    {"name": "HDFC Bank", "linkedin_slug": "hdfc-bank", "size_tier": "1000+", "employee_count": 170000, "industry": "Banking"},
    {"name": "ICICI Bank", "linkedin_slug": "icici-bank", "size_tier": "1000+", "employee_count": 130000, "industry": "Banking"},
    {"name": "JPMorgan Chase & Co.", "linkedin_slug": "jpmorganchase", "size_tier": "1000+", "employee_count": 250000, "industry": "Global Banking & Fintech"},
    {"name": "Morgan Stanley", "linkedin_slug": "morgan-stanley", "size_tier": "1000+", "employee_count": 80000, "industry": "Investment Banking"},
    {"name": "Goldman Sachs", "linkedin_slug": "goldman-sachs", "size_tier": "1000+", "employee_count": 45000, "industry": "Investment Banking"},
    {"name": "Nomura", "linkedin_slug": "nomura", "size_tier": "1000+", "employee_count": 26000, "industry": "Investment Banking"},
    {"name": "PwC India", "linkedin_slug": "pwc-india", "size_tier": "1000+", "employee_count": 30000, "industry": "Consulting"},
    {"name": "EY India", "linkedin_slug": "ernstandyoung", "size_tier": "1000+", "employee_count": 70000, "industry": "Consulting & Analytics"},
    {"name": "Deloitte India", "linkedin_slug": "deloitte", "size_tier": "1000+", "employee_count": 90000, "industry": "Consulting & Analytics"},
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
        if "founder" in clean_kw and ("founder" in low or "chief of staff" in low):
            return kw.strip()
        if clean_kw == "hr" and (re.search(r"\bhr\b", low) or "human resource" in low or "people ops" in low):
            return "HR"
        if "talent" in clean_kw and ("talent" in low or "recruiter" in low or "hiring" in low):
            return "Talent"
    return ""


def _parse_employee_count(size_text: str) -> tuple:
    """Returns (size_tier, estimated_count) strictly ordered across 250-500, 500-1000, 1000+."""
    low = (size_text or "").lower().replace(",", "")
    nums = [int(n) for n in re.findall(r"\d+", low)]
    if not nums:
        return "500-1000", 600
    low_val = nums[0]
    high_val = nums[1] if len(nums) >= 2 else low_val
    if high_val <= 200 and "+" not in low:
        return "<250", max(high_val, 50)
    if (201 <= low_val <= 500) or (high_val == 500):
        return "250-500", 350 if low_val == 201 else low_val
    if (501 <= low_val <= 1000) or (high_val == 1000):
        return "500-1000", 750 if low_val == 501 else low_val
    return "1000+", low_val


def _fetch_public_company_metadata(slug: str) -> dict:
    """Reads Company size, Headquarters, and Industry from public LinkedIn company page without needing li_at."""
    url = f"https://www.linkedin.com/company/{slug}"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        html = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", errors="ignore")
        size_m = re.search(r"Company size\s*</dt>\s*<dd[^>]*>(.*?)</dd>", html, re.DOTALL | re.I)
        hq_m = re.search(r"Headquarters\s*</dt>\s*<dd[^>]*>(.*?)</dd>", html, re.DOTALL | re.I)
        ind_m = re.search(r"Industry\s*</dt>\s*<dd[^>]*>(.*?)</dd>", html, re.DOTALL | re.I)

        clean = lambda m: html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(1)).strip()) if m else ""
        size_str = clean(size_m)
        hq_str = clean(hq_m)
        ind_str = clean(ind_m)

        tier, est_cnt = _parse_employee_count(size_str)
        return {
            "size_tier": tier,
            "employee_count": est_cnt,
            "size_text": size_str,
            "headquarters": hq_str,
            "industry": ind_str or "Enterprise / Hiring in Mumbai",
        }
    except Exception:
        return {}


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
        companies.sort(key=lambda c: (
            SIZE_TIER_RANK.get(c.get("size_tier", "1000+"), 4),
            int(c.get("employee_count", 1000)),
            c.get("name", "").lower(),
        ))
        return companies

    def save_companies(self, companies: list):
        companies.sort(key=lambda c: (
            SIZE_TIER_RANK.get(c.get("size_tier", "1000+"), 4),
            int(c.get("employee_count", 1000)),
            c.get("name", "").lower(),
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
    # Step 1: Deep Mumbai Company Discovery (Guest API + Enrichment + Logged-In + Curated)
    # ------------------------------------------------------------------
    def _build_company_obj(
        self,
        name: str,
        linkedin_slug: str = "",
        size_tier: str = "250-500",
        employee_count: int = 350,
        industry: str = "Tech / Corporate",
        city: str = "Mumbai",
        headquarters: str = "Mumbai, Maharashtra",
    ) -> dict:
        slug = linkedin_slug or _make_slug(name)
        return {
            "id": str(abs(hash(slug or name.lower()))),
            "name": html_lib.unescape(name.strip()),
            "linkedin_slug": slug,
            "city": city,
            "headquarters": headquarters,
            "size_tier": size_tier,
            "size_sort_rank": SIZE_TIER_RANK.get(size_tier, 4),
            "employee_count": int(employee_count),
            "industry": html_lib.unescape(industry),
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
            city="Mumbai",
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

    def generate_mumbai_companies(self, try_live_linkedin: bool = True, enrich_limit: int = 60, log_cb=None) -> dict:
        """
        Comprehensive Mumbai company discovery engine:
        1. Merges curated 60+ Mumbai firms across 250-500, 500-1000, 1000+.
        2. Queries LinkedIn's Public Mumbai Jobs Guest API across 12 role & location keywords
           (discovers 100+ active Mumbai hiring companies even without cookies) and enriches
           headcount/HQ/industry from their public LinkedIn company pages.
        3. When li_at is authenticated, also crawls paginated LinkedIn Company Search across
           Mumbai size brackets (201-500, 501-1000, 1001+) pages 1..4.
        4. Sorts strictly in increasing size order: 250-500 -> 500-1000 -> 1000+.
        """
        def log(msg):
            logger.info(msg)
            if log_cb:
                log_cb(msg)

        existing = self.get_companies()
        by_slug = {c.get("linkedin_slug"): c for c in existing if c.get("linkedin_slug")}
        by_name = {c.get("name", "").lower(): c for c in existing}
        added_count = 0

        # Step A: Merge Curated Directory (60+ verified Mumbai firms)
        for seed in CURATED_MUMBAI_COMPANIES:
            slug = seed["linkedin_slug"]
            if slug not in by_slug and seed["name"].lower() not in by_name:
                obj = self._build_company_obj(**seed, city="Mumbai")
                existing.append(obj)
                by_slug[slug] = obj
                by_name[seed["name"].lower()] = obj
                added_count += 1

        if try_live_linkedin:
            # Step B: Public Mumbai Hiring Companies Discovery via LinkedIn Guest Jobs API (No login needed)
            log("Scanning live Mumbai companies via LinkedIn Public Discovery (Mumbai, Navi Mumbai, Thane)...")
            guest_queries = [
                ("Analyst", "Mumbai"),
                ("Product Manager", "Mumbai"),
                ("Business Analyst", "Mumbai"),
                ("Strategy", "Mumbai"),
                ("Data Analyst", "Mumbai"),
                ("Human Resources", "Mumbai"),
                ("Talent Acquisition", "Mumbai"),
                ("Founder's Office", "Mumbai"),
                ("Finance", "Mumbai"),
                ("Software", "Mumbai"),
                ("Analyst", "Navi Mumbai"),
                ("Product", "Thane"),
            ]
            discovered_guest = {}
            for kw, loc in guest_queries:
                for start in [0, 25]:
                    url = (
                        f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                        f"?keywords={urllib.parse.quote(kw)}&location={urllib.parse.quote(loc)}&start={start}"
                    )
                    try:
                        req = urllib.request.Request(
                            url,
                            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
                        )
                        raw_html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
                        matches = re.findall(
                            r'<a[^>]*href="(https://[^"]*linkedin\.com/company/([^"/?]+))[^"]*"[^>]*>(.*?)</a>',
                            raw_html,
                            re.DOTALL,
                        )
                        for _, slug, raw_name in matches:
                            slug_clean = slug.strip().lower().rstrip("/")
                            name_clean = html_lib.unescape(re.sub(r"<[^>]+>", "", raw_name).strip())
                            if slug_clean and name_clean and slug_clean not in discovered_guest:
                                discovered_guest[slug_clean] = name_clean
                        time.sleep(0.75)  # Polite throttle to avoid 429
                    except Exception:
                        time.sleep(1.5)

            log(f"Public Mumbai search uncovered {len(discovered_guest)} companies. Enriching company sizes & HQ...")

            enriched_so_far = 0
            for slug, comp_name in discovered_guest.items():
                if slug in by_slug or comp_name.lower() in by_name:
                    continue
                if enriched_so_far < enrich_limit:
                    meta = _fetch_public_company_metadata(slug)
                    enriched_so_far += 1
                    time.sleep(0.35)
                else:
                    meta = {}

                size_tier = meta.get("size_tier", "500-1000")
                est_cnt = meta.get("employee_count", 600)
                industry = meta.get("industry", "Hiring in Mumbai")
                hq = meta.get("headquarters") or "Mumbai Office"

                obj = self._build_company_obj(
                    name=comp_name,
                    linkedin_slug=slug,
                    size_tier=size_tier,
                    employee_count=est_cnt,
                    industry=industry,
                    city="Mumbai",
                    headquarters=hq,
                )
                existing.append(obj)
                by_slug[slug] = obj
                by_name[comp_name.lower()] = obj
                added_count += 1

            # Step C: Logged-in Paginated LinkedIn Company Search (if session is active)
            tier_queries = [
                ("250-500", "E", 350),
                ("500-1000", "F", 750),
                ("1000+", "G", 2500),
                ("1000+", "H", 7500),
            ]
            context = None
            try:
                context, page = self.browser_mgr.get_context_and_page(force_headless=True)
                if self.browser_mgr.ensure_logged_in(page, timeout_sec=8):
                    for tier_label, size_code, default_cnt in tier_queries:
                        for pg in range(1, 4):  # Paginate pages 1..3
                            url = (
                                f"https://www.linkedin.com/search/results/companies/"
                                f"?companyHqGeo=%5B%22106164952%22%5D&companySize=%5B%22{size_code}%22%5D"
                                f"&origin=FACETED_SEARCH&page={pg}"
                            )
                            page.goto(url, wait_until="domcontentloaded")
                            human_delay(2.5, 3.5)

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
                            if not discovered:
                                break
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
                            log(f"Logged-in search page {pg} ({tier_label}): +{len(discovered)} checked.")
                else:
                    log("LinkedIn cookie expired for logged-in search — update li_at for extra private search results.")
            except Exception as e:
                logger.debug(f"Logged-in search skipped: {e}")
            finally:
                if context:
                    self.browser_mgr.close()

        self.save_companies(existing)
        sorted_companies = self.get_companies()
        log(f"✅ Mumbai Directory ready: {len(sorted_companies)} companies total ({added_count} newly added), sorted 250-500 → 500-1000 → 1000+.")
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
        limit_per_company: int = 25,
        log_cb=None,
    ) -> dict:
        """
        For each company (in increasing size order unless specified):
        1. Searches for PEC Chandigarh alumni at that company -> category = 'pec_alumni'
        2. Searches for target keywords (Founder's Office, HR, Talent, Product, Analyst)
           -> category = 'other' (or 'pec_alumni' if PEC detected)
        3. Connected (1st-degree) people go directly to 'sending_list' so they're ready to message!
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

            if not self.browser_mgr.ensure_logged_in(page, timeout_sec=10):
                log("⚠️ LinkedIn session expired (/uas/login). Please click 'LinkedIn: Update Key' in top bar to paste fresh li_at cookie.")
                return {"status": "Auth Required", "message": "LinkedIn authentication required (update li_at cookie)."}

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
                                "workflow_stage": "sending_list" if is_1st else "discovered",
                                "discovered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "connection_sent_at": None,
                                "accepted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if is_1st else None,
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
                                "workflow_stage": "sending_list" if is_1st else "discovered",
                                "discovered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "connection_sent_at": None,
                                "accepted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if is_1st else None,
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
    # Step 3: Maximize Connection Requests + Message Sending List
    # ------------------------------------------------------------------
    def run_connect_and_message_cycle(
        self,
        company_ids: list = None,
        contact_ids: list = None,
        max_connects: int = 25,
        max_messages: int = 25,
        log_cb=None,
    ) -> dict:
        """
        Executes in strict increasing company size order (250-500 -> 500-1000 -> 1000+):
        1. Sends messages to everyone currently in 'sending_list' (already connected & unmessaged).
        2. Visits 'discovered' contacts:
           - If connected (1st degree): adds to Sending List & sends company PEC/Other template immediately -> 'completed'.
           - If NOT connected: sends clean Connection Request (maximizing quota) -> moves to 'incomplete_pending_accept'.
        """
        def log(msg):
            logger.info(msg)
            if log_cb:
                log_cb(msg)

        companies = self.get_companies()
        companies_by_id = {str(c.get("id")): c for c in companies}
        all_contacts = self.get_contacts()

        candidates = [
            c for c in all_contacts
            if c.get("workflow_stage") in ("discovered", "sending_list")
        ]
        if company_ids:
            id_set = {str(cid) for cid in company_ids}
            candidates = [c for c in candidates if str(c.get("company_id")) in id_set]
        if contact_ids:
            cset = {str(cid) for cid in contact_ids}
            candidates = [c for c in candidates if str(c.get("id")) in cset]

        # Priority: Sending List (accepted/ready) first, then smallest size tier (250-500 -> 500-1000 -> 1000+), PEC alumni first
        candidates.sort(key=lambda c: (
            0 if c.get("workflow_stage") == "sending_list" else 1,
            SIZE_TIER_RANK.get(c.get("size_tier", "1000+"), 4),
            int((companies_by_id.get(str(c.get("company_id"))) or {}).get("employee_count", 1000)),
            0 if c.get("is_pec_alumni") else 1,
        ))

        if not candidates:
            return {"status": "Idle", "message": "No new discovered or ready contacts queued."}

        context, page = self.browser_mgr.get_context_and_page(force_headless=True)
        connects_sent = 0
        messages_sent = 0

        try:
            try:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            except Exception:
                pass

            if not self.browser_mgr.ensure_logged_in(page, timeout_sec=10):
                return {"status": "Auth Required", "message": "LinkedIn login required (update li_at cookie)."}

            for contact in candidates:
                if connects_sent >= max_connects and messages_sent >= max_messages:
                    break

                purl = contact.get("profile_url")
                name = contact.get("name", "Contact")
                comp_name = contact.get("company_name", "")
                if not purl:
                    continue

                try:
                    log(f"Processing {name} ({comp_name}, {contact.get('size_tier')}, {'PEC' if contact.get('is_pec_alumni') else 'Other'})...")
                    page.goto(purl, wait_until="domcontentloaded")
                    human_delay(2.5, 4.0)

                    pending_btn = page.locator("main button:has-text('Pending'), main span:has-text('Pending')").first
                    is_already_pending = pending_btn.count() > 0 and pending_btn.is_visible()

                    is_1st_badge = page.locator("main span.dist-value:has-text('1st'), main span:has-text('• 1st')").first.count() > 0
                    msg_btn = page.locator("main button:has-text('Message')").first
                    can_direct_msg = is_1st_badge and msg_btn.count() > 0 and msg_btn.is_visible()

                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if can_direct_msg:
                        contact["connection_status"] = "connected_ready"
                        contact["workflow_stage"] = "sending_list"
                        if not contact.get("accepted_at"):
                            contact["accepted_at"] = now_str

                        if messages_sent < max_messages:
                            msg_text = self._render_message_for_contact(contact, companies_by_id)
                            sent = self.referral_engine._send_direct_message(page, msg_text)
                            if sent:
                                messages_sent += 1
                                contact["connection_status"] = "messaged"
                                contact["workflow_stage"] = "completed"
                                contact["messaged_at"] = now_str
                                contact["message_used"] = msg_text
                                self._increment_daily_stat("messages_sent", 1)
                                log(f"[COMPLETED] Sent tailored message to {name} ({comp_name}).")
                    elif is_already_pending:
                        contact["connection_status"] = "connection_sent"
                        contact["workflow_stage"] = "incomplete_pending_accept"
                        if not contact.get("connection_sent_at"):
                            contact["connection_sent_at"] = now_str
                        log(f"[INCOMPLETE] Invite pending for {name} ({comp_name}); tracked for daily check.")
                    else:
                        if connects_sent >= max_connects:
                            continue
                        sent = self.referral_engine._send_connection_request(page, note_text="")
                        if sent:
                            connects_sent += 1
                            contact["connection_status"] = "connection_sent"
                            contact["workflow_stage"] = "incomplete_pending_accept"
                            contact["connection_sent_at"] = now_str
                            self._increment_daily_stat("connections_sent", 1)
                            log(f"[INCOMPLETE] Connection request sent to {name} ({comp_name}). Tracked for daily check.")
                        else:
                            log(f"Could not find Connect button for {name} (may be Follow-only).")

                    human_delay(2.0, 3.5)
                except Exception as e:
                    logger.warning(f"Error processing {name}: {e}")

            self.save_contacts(all_contacts)
            log(f"Cycle finished: {connects_sent} connection requests sent, {messages_sent} messages sent.")
            return {
                "status": "Success",
                "connections_sent": connects_sent,
                "messages_sent": messages_sent,
            }
        finally:
            self.browser_mgr.close()

    # ------------------------------------------------------------------
    # Step 4: Daily Check of ALL Un-Messaged Pending Contacts -> Add to Sending List & Send
    # ------------------------------------------------------------------
    def run_daily_acceptance_and_send(
        self,
        min_age_days: int = 0,
        check_all_pending: bool = True,
        send_immediately: bool = True,
        log_cb=None,
    ) -> dict:
        """
        Runs daily against ALL people whose message has NOT been sent yet:
        1. Fast scan of LinkedIn Recently Added Connections (/mynetwork/invite-connect/connections/)
           to promote accepted contacts immediately into the Sending List!
        2. Verifies remaining 'incomplete_pending_accept' profiles directly.
        3. Any accepted contact is added to 'sending_list' and (if send_immediately=True)
           messaged with their company's customized PEC or Other template -> moved from
           Incomplete/Sending List to Completed!
        """
        def log(msg):
            logger.info(msg)
            if log_cb:
                log_cb(msg)

        companies = self.get_companies()
        companies_by_id = {str(c.get("id")): c for c in companies}
        all_contacts = self.get_contacts()
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        pending_contacts = [
            c for c in all_contacts
            if c.get("workflow_stage") == "incomplete_pending_accept"
        ]
        ready_to_send_contacts = [
            c for c in all_contacts
            if c.get("workflow_stage") == "sending_list"
        ]

        if not pending_contacts and not ready_to_send_contacts:
            log("No pending connections or Sending List contacts need processing today.")
            return {
                "status": "Success",
                "checked_count": 0,
                "added_to_sending_list": 0,
                "accepted_and_messaged": 0,
                "still_pending": 0,
            }

        context, page = self.browser_mgr.get_context_and_page(force_headless=True)
        promoted_count = 0
        messaged_count = 0
        still_pending_count = 0

        try:
            try:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            except Exception:
                pass

            if not self.browser_mgr.ensure_logged_in(page, timeout_sec=10):
                return {"status": "Auth Required", "message": "LinkedIn login required (update li_at cookie)."}

            # Phase A: Fast batch sync via Recently Added Connections page
            recent_connected_urls = set()
            if pending_contacts:
                try:
                    log("Checking Recently Added Connections on LinkedIn for fast acceptance matching...")
                    page.goto("https://www.linkedin.com/mynetwork/invite-connect/connections/", wait_until="domcontentloaded")
                    human_delay(3.0, 4.0)
                    recent_urls = page.evaluate('''() => {
                        const urls = [];
                        document.querySelectorAll("a[href*='/in/']").forEach(a => {
                            if (a.href) urls.push(a.href.split('?')[0].replace(/\\/+$/, ''));
                        });
                        return Array.from(new Set(urls));
                    }''')
                    recent_connected_urls = set(recent_urls)
                    log(f"Loaded {len(recent_connected_urls)} recent 1st-degree connections.")
                except Exception as e:
                    logger.debug(f"Could not batch scan connections page: {e}")

            # Promote any pending contact found in recent connections directly into Sending List
            remaining_to_probe = []
            for c in pending_contacts:
                clean_purl = (c.get("profile_url") or "").split("?")[0].rstrip("/")
                c["last_checked_at"] = now_str
                if clean_purl and clean_purl in recent_connected_urls:
                    c["workflow_stage"] = "sending_list"
                    c["connection_status"] = "connected_ready"
                    c["accepted_at"] = now_str
                    promoted_count += 1
                    ready_to_send_contacts.append(c)
                    self._increment_daily_stat("acceptances_detected", 1)
                    log(f"[ACCEPTED -> SENDING LIST] {c.get('name')} ({c.get('company_name')}) added to Sending List!")
                else:
                    remaining_to_probe.append(c)

            # Phase B: Direct profile verification for remaining pending contacts
            for c in remaining_to_probe:
                purl = c.get("profile_url")
                if not purl:
                    continue
                try:
                    page.goto(purl, wait_until="domcontentloaded")
                    human_delay(2.0, 3.0)
                    c["last_checked_at"] = now_str

                    is_1st_badge = page.locator("main span.dist-value:has-text('1st'), main span:has-text('• 1st')").first.count() > 0
                    msg_btn = page.locator("main button:has-text('Message')").first

                    if is_1st_badge and msg_btn.count() > 0 and msg_btn.is_visible():
                        c["workflow_stage"] = "sending_list"
                        c["connection_status"] = "connected_ready"
                        c["accepted_at"] = now_str
                        promoted_count += 1
                        ready_to_send_contacts.append(c)
                        self._increment_daily_stat("acceptances_detected", 1)
                        log(f"[ACCEPTED -> SENDING LIST] {c.get('name')} ({c.get('company_name')}) accepted! Added to Sending List.")
                    else:
                        still_pending_count += 1
                except Exception as e:
                    logger.warning(f"Error verifying {c.get('name')}: {e}")

            # Phase C: Send customized company template to everyone in Sending List
            if send_immediately and ready_to_send_contacts:
                log(f"Sending customized messages to {len(ready_to_send_contacts)} accepted contacts in Sending List...")
                for c in ready_to_send_contacts:
                    if c.get("workflow_stage") == "completed":
                        continue
                    purl = c.get("profile_url")
                    if not purl:
                        continue
                    try:
                        page.goto(purl, wait_until="domcontentloaded")
                        human_delay(2.0, 3.0)
                        msg_text = self._render_message_for_contact(c, companies_by_id)
                        sent = self.referral_engine._send_direct_message(page, msg_text)
                        if sent:
                            messaged_count += 1
                            c["connection_status"] = "messaged"
                            c["workflow_stage"] = "completed"
                            c["messaged_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            c["message_used"] = msg_text
                            self._increment_daily_stat("messages_sent", 1)
                            self._increment_daily_stat("completed_followups", 1)
                            log(f"[SENDING LIST -> COMPLETED] Delivered message to {c.get('name')} ({c.get('company_name')}).")
                        human_delay(2.0, 3.5)
                    except Exception as e:
                        logger.warning(f"Error sending message to {c.get('name')}: {e}")

            self.save_contacts(all_contacts)
            log(f"Daily Check Complete: {promoted_count} newly accepted → Sending List, {messaged_count} messaged & moved to Completed, {still_pending_count} still pending.")
            return {
                "status": "Success",
                "checked_count": len(pending_contacts),
                "added_to_sending_list": promoted_count,
                "accepted_and_messaged": messaged_count,
                "still_pending": still_pending_count,
            }
        finally:
            self.browser_mgr.close()

    # Backwards-compatible alias
    def run_2day_followup_check(self, min_age_days: int = 0, check_all_pending: bool = True, log_cb=None) -> dict:
        return self.run_daily_acceptance_and_send(min_age_days=0, check_all_pending=True, send_immediately=True, log_cb=log_cb)

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
        comp_counts = {}
        for c in contacts:
            cid = str(c.get("company_id"))
            if cid not in comp_counts:
                comp_counts[cid] = {"pec": 0, "other": 0, "incomplete": 0, "sending_list": 0, "completed": 0}
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
                    except Exception:
                        c["days_pending"] = 0
            elif stage == "sending_list":
                comp_counts[cid]["sending_list"] += 1
            elif stage == "completed":
                comp_counts[cid]["completed"] += 1

        for comp in companies:
            counts = comp_counts.get(str(comp.get("id")), {"pec": 0, "other": 0, "incomplete": 0, "sending_list": 0, "completed": 0})
            comp["counts"] = counts

        discovered = [c for c in contacts if c.get("workflow_stage") == "discovered"]
        incomplete = [c for c in contacts if c.get("workflow_stage") == "incomplete_pending_accept"]
        sending_list = [c for c in contacts if c.get("workflow_stage") == "sending_list"]
        completed = [c for c in contacts if c.get("workflow_stage") == "completed"]
        pec_contacts = [c for c in contacts if c.get("is_pec_alumni")]
        other_contacts = [c for c in contacts if not c.get("is_pec_alumni")]

        daily_history = sorted(daily_stats.values(), key=lambda x: x.get("date", ""), reverse=True)

        return {
            "companies": companies,
            "contacts": contacts,
            "discovered": discovered,
            "incomplete": incomplete,
            "sending_list": sending_list,
            "completed": completed,
            "pec_contacts": pec_contacts,
            "other_contacts": other_contacts,
            "today_stats": today_stat,
            "daily_history": daily_history,
            "counts": {
                "companies": len(companies),
                "total_contacts": len(contacts),
                "pec": len(pec_contacts),
                "other": len(other_contacts),
                "discovered": len(discovered),
                "incomplete": len(incomplete),
                "sending_list": len(sending_list),
                "completed": len(completed),
            },
        }
