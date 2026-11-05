"""
recruitment_dispatcher.py - Classifies scraped recruitment posts into:
1. Application Forms Pending (Google Forms, Typeforms) -> For manual application.
2. Harvested Recruiter Emails -> Prepares tailored referral / application emails.
"""

import os
import json
import logging
import re
from urllib.parse import quote
from datetime import datetime

logger = logging.getLogger("RecruitmentDispatcher")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
FEED_LEADS_JSON = os.path.join(DATA_DIR, "feed_leads.json")
PENDING_FORMS_JSON = os.path.join(DATA_DIR, "pending_forms.json")
RECRUITER_LEADS_JSON = os.path.join(DATA_DIR, "recruiter_leads.json")
DISMISSED_FORMS_JSON = os.path.join(DATA_DIR, "dismissed_forms.json")
DISMISSED_RECRUITERS_JSON = os.path.join(DATA_DIR, "dismissed_recruiters.json")

CANDIDATE_NAME = "Ashutosh Bajpai"
CANDIDATE_COLLEGE = "Punjab Engineering College (PEC)"
CANDIDATE_EMAIL = "ashutosh.bajpai.028works@gmail.com"
CANDIDATE_PHONE = "8081377486"


import re

def clean_extracted_email(email_str: str) -> str:
    """Strips trailing punctuation, numbers, or words glued to domain."""
    em = email_str.strip(' .,:;)"\'')
    m = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.(?:com|in|org|net|co|ai|io|tech|edu|gov|co\.in|ac\.in|[a-zA-Z]{2,8}))', em, re.IGNORECASE)
    return m.group(1).lower() if m else em.lower()


def sync_leads():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(FEED_LEADS_JSON):
        return {"forms": [], "emails": []}

    try:
        with open(FEED_LEADS_JSON, "r", encoding="utf-8") as f:
            feed_leads = json.load(f)
    except Exception:
        feed_leads = []

    pending_forms = []
    recruiter_leads = []
    seen_forms = set()
    seen_emails = set()

    # Load dismissed / removed items so they are permanently excluded
    dismissed_forms = set()
    if os.path.exists(DISMISSED_FORMS_JSON):
        try:
            with open(DISMISSED_FORMS_JSON, "r", encoding="utf-8") as f:
                dismissed_forms = set(json.load(f))
        except Exception:
            pass

    dismissed_emails = set()
    if os.path.exists(DISMISSED_RECRUITERS_JSON):
        try:
            with open(DISMISSED_RECRUITERS_JSON, "r", encoding="utf-8") as f:
                dismissed_emails = set(json.load(f))
        except Exception:
            pass

    # Load existing if available and backfill post_url
    if os.path.exists(PENDING_FORMS_JSON):
        try:
            with open(PENDING_FORMS_JSON, "r", encoding="utf-8") as f:
                pending_forms = [item for item in json.load(f) if item.get("form_url") not in dismissed_forms and item.get("id") not in dismissed_forms]
                for item in pending_forms:
                    if not item.get("post_url"):
                        ctx = item.get("context", "").replace("Feed post", "").strip()[:50]
                        item["post_url"] = f"https://www.linkedin.com/search/results/content/?keywords={quote(ctx or item.get('poster', 'hiring'))}"
                seen_forms = {item.get("form_url") for item in pending_forms if item.get("form_url")}
        except Exception:
            pending_forms = []

    if os.path.exists(RECRUITER_LEADS_JSON):
        try:
            with open(RECRUITER_LEADS_JSON, "r", encoding="utf-8") as f:
                raw_leads = json.load(f)
                recruiter_leads = []
                for item in raw_leads:
                    if item.get("email") in dismissed_emails or item.get("id") in dismissed_emails:
                        continue
                    item["email"] = clean_extracted_email(item.get("email", ""))
                    if not item["email"] or len(item["email"]) < 6:
                        continue
                    if not item.get("post_url"):
                        item["post_url"] = f"https://www.linkedin.com/search/results/content/?keywords={quote(item['email'])}"
                    # Fix 'Hi LinkedIn' salutation if present
                    if "Hi LinkedIn," in item.get("draft_body", ""):
                        item["draft_body"] = item["draft_body"].replace("Hi LinkedIn,", "Hi Hiring Team,")
                    recruiter_leads.append(item)
                seen_emails = {item.get("email") for item in recruiter_leads if item.get("email")}
        except Exception:
            recruiter_leads = []
            recruiter_leads = []

    for post in feed_leads:
        raw_author = post.get("author", "").strip()
        preview = post.get("preview", "")
        timestamp = post.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        post_url = post.get("post_url", "").strip()
        post_tags = post.get("tags", ["Recruiting (0-2 Yrs)"])

        # Clean author name from preview if needed
        author = raw_author
        if not author or any(k in author.lower() for k in ["member", "feed post", "hiring lead", "linkedin poster"]):
            m = re.search(r"(?:likes this|commented|reposted this|finds this insightful|follows this page)\s*([A-Za-z0-9\s\.\,\-]+?)\s*(?:•|\d+[hdwmy]|Follow|Promoted|$)", preview, re.IGNORECASE)
            if m:
                cand = m.group(1).strip()
                cand = re.sub(r"^(?:and \d+ other connections? like this|reposted this)\s*", "", cand, flags=re.IGNORECASE).strip()
                if len(cand) > 2 and len(cand) < 45:
                    author = cand
        if not author or any(k in author.lower() for k in ["member", "feed post", "hiring lead", "linkedin poster"]):
            author = "Hiring Lead"

        if not post_url:
            clean_auth = re.sub(r"\s*\(.*?\)", "", author).strip()
            if clean_auth and clean_auth != "Hiring Lead":
                q = f'"{clean_auth}" {re.sub(r"[^\w\s]", "", preview[:40]).strip()}'
            else:
                q = re.sub(r"[^\w\s]", "", preview[:50]).strip() or "hiring"
            post_url = f"https://www.linkedin.com/search/results/content/?keywords={quote(q)}"

        # 1. Process Form Links & External Application Links
        forms_str = post.get("form_links", "")
        if forms_str:
            for form_url in [u.strip() for u in forms_str.split(",") if u.strip()]:
                if form_url not in seen_forms and form_url not in dismissed_forms:
                    seen_forms.add(form_url)
                    pending_forms.append({
                        "id": str(abs(hash(form_url))),
                        "timestamp": timestamp,
                        "poster": author,
                        "form_url": form_url,
                        "post_url": post_url,
                        "tags": post_tags,
                        "context": preview[:180],
                        "status": "Pending Manual Fill"
                    })
        elif post.get("hyperlinks"):
            for link in [u.strip() for u in post.get("hyperlinks", "").split(",") if u.strip()]:
                if link not in seen_forms and link not in dismissed_forms and not any(ign in link.lower() for ign in ["linkedin.com", "apple.com", "play.google.com"]):
                    seen_forms.add(link)
                    pending_forms.append({
                        "id": str(abs(hash(link))),
                        "timestamp": timestamp,
                        "poster": author,
                        "form_url": link,
                        "post_url": post_url,
                        "tags": post_tags,
                        "context": preview[:180],
                        "status": "Pending Manual Fill"
                    })

        # 2. Process Recruiter Emails
        emails_str = post.get("emails", "")
        if emails_str:
            for raw_email in [e.strip() for e in emails_str.split(",") if e.strip()]:
                email = clean_extracted_email(raw_email)
                if not email or len(email) < 6:
                    continue
                if email not in seen_emails and email not in dismissed_emails:
                    seen_emails.add(email)

                    lead_author = author
                    if lead_author in ["Hiring Lead", "LinkedIn Member"] or not lead_author:
                        domain = email.split("@")[1].split(".")[0].lower()
                        brand_map = {
                            "qualcomm": "Qualcomm Careers",
                            "uflexltd": "Uflex Limited HR",
                            "blackbuck": "BlackBuck Talent Team",
                            "gmrinfo": "GMR Group Careers",
                            "mastersunion": "Palak Pruthi (Masters’ Union)",
                            "pinnacleu": "Shanaya Vasisht (PinnacleU)",
                            "freshworks": "Freshworks Recruiting",
                            "adobe": "Adobe Talent Team",
                            "tcs": "TCS Recruitment Desk",
                            "delhivery": "Delhivery Careers",
                            "phonepe": "PhonePe Talent Team",
                            "hcltech": "HCLTech Hiring Team",
                            "deshaw": "D. E. Shaw Careers",
                            "zohocorp": "Zoho Talent Acquisition",
                            "mphasis": "Mphasis Talent Team",
                            "hexaware": "Hexaware Careers",
                            "browserstack": "BrowserStack Hiring",
                            "nttdata": "NTT DATA Careers",
                            "inmobi": "InMobi Recruiting Team",
                            "coforge": "Coforge Talent Team",
                            "maruti": "Maruti Suzuki Recruitment",
                            "almarinaholding": "Al Marina Holding",
                            "eatclutch": "Clutch Hiring Team",
                            "paibytwo": "PaiByTwo Recruitment",
                            "aavishkaar": "Aavishkaar Capital",
                            "wakefit": "Wakefit Recruiting",
                            "algoanalytics": "AlgoAnalytics Hiring"
                        }
                        lead_author = brand_map.get(domain, f"{domain.capitalize()} Hiring Team")

                    # Salutation
                    first_tok = lead_author.split()[0].capitalize()
                    if any(k in lead_author.lower() for k in ["team", "careers", "group", "desk", "lead", "holding", "services", "consulting"]):
                        salutation = "Hiring Team"
                    else:
                        salutation = first_tok

                    subject = f"Application for Analyst / Product Role - {CANDIDATE_NAME} ({CANDIDATE_COLLEGE})"
                    body = (
                        f"Hi {salutation},\n\n"
                        f"I came across your recruitment post regarding the opening and would love to be considered. "
                        f"I am a final-year student at {CANDIDATE_COLLEGE} with hands-on experience in Product and Data Analysis, "
                        f"market research, and cross-functional execution.\n\n"
                        f"My details:\n"
                        f"• Name: {CANDIDATE_NAME}\n"
                        f"• Email: {CANDIDATE_EMAIL}\n"
                        f"• Phone: {CANDIDATE_PHONE}\n"
                        f"• Institute: {CANDIDATE_COLLEGE}\n\n"
                        f"I have attached my resume and would be delighted to discuss how my skill set aligns with your team's goals.\n\n"
                        f"Best regards,\n"
                        f"{CANDIDATE_NAME}"
                    )
                    mailto = f"mailto:{email}?subject={quote(subject)}&body={quote(body)}"
                    gmail_web_link = f"https://mail.google.com/mail/?view=cm&fs=1&to={quote(email)}&su={quote(subject)}&body={quote(body)}"

                    recruiter_post_url = post_url
                    if not recruiter_post_url or "keywords=" in recruiter_post_url or "hiring" in recruiter_post_url:
                        clean_auth = re.sub(r"\s*\(.*?\)", "", lead_author).strip()
                        if clean_auth and not any(k in clean_auth.lower() for k in ["team", "lead", "desk", "careers"]):
                            q = f'"{clean_auth}" "{email}"'
                        else:
                            q = f'"{email}"'
                        recruiter_post_url = f"https://www.linkedin.com/search/results/content/?keywords={quote(q)}"

                    recruiter_leads.append({
                        "id": str(abs(hash(email))),
                        "timestamp": timestamp,
                        "recipient_name": lead_author,
                        "email": email,
                        "subject": subject,
                        "draft_body": body,
                        "mailto_link": mailto,
                        "gmail_web_link": gmail_web_link,
                        "post_url": recruiter_post_url,
                        "tags": post_tags,
                        "status": "Draft Prepared",
                        "context": preview[:180]
                    })

    # Save to disk
    with open(PENDING_FORMS_JSON, "w", encoding="utf-8") as f:
        json.dump(pending_forms, f, indent=2)

    with open(RECRUITER_LEADS_JSON, "w", encoding="utf-8") as f:
        json.dump(recruiter_leads, f, indent=2)

    logger.info(f"Synced {len(pending_forms)} pending application forms and {len(recruiter_leads)} recruiter leads.")
    return {"forms": pending_forms, "emails": recruiter_leads}


def dismiss_pending_form(form_id: str = None, form_url: str = None) -> bool:
    """Removes a form from pending_forms.json and permanently blacklists it from reappearing."""
    os.makedirs(DATA_DIR, exist_ok=True)
    pending_forms = []
    if os.path.exists(PENDING_FORMS_JSON):
        try:
            with open(PENDING_FORMS_JSON, "r", encoding="utf-8") as f:
                pending_forms = json.load(f)
        except Exception:
            pending_forms = []

    dismissed_forms = set()
    if os.path.exists(DISMISSED_FORMS_JSON):
        try:
            with open(DISMISSED_FORMS_JSON, "r", encoding="utf-8") as f:
                dismissed_forms = set(json.load(f))
        except Exception:
            pass

    remaining = []
    for item in pending_forms:
        if (form_id and item.get("id") == form_id) or (form_url and item.get("form_url") == form_url):
            target_url = item.get("form_url")
            if target_url:
                dismissed_forms.add(target_url)
            if item.get("id"):
                dismissed_forms.add(item.get("id"))
        else:
            remaining.append(item)

    if form_url:
        dismissed_forms.add(form_url)
    if form_id:
        dismissed_forms.add(form_id)

    with open(PENDING_FORMS_JSON, "w", encoding="utf-8") as f:
        json.dump(remaining, f, indent=2)

    with open(DISMISSED_FORMS_JSON, "w", encoding="utf-8") as f:
        json.dump(list(dismissed_forms), f, indent=2)

    return True


def clear_all_pending_forms() -> int:
    """Clears all pending forms and marks them as dismissed."""
    os.makedirs(DATA_DIR, exist_ok=True)
    pending_forms = []
    if os.path.exists(PENDING_FORMS_JSON):
        try:
            with open(PENDING_FORMS_JSON, "r", encoding="utf-8") as f:
                pending_forms = json.load(f)
        except Exception:
            pending_forms = []

    dismissed_forms = set()
    if os.path.exists(DISMISSED_FORMS_JSON):
        try:
            with open(DISMISSED_FORMS_JSON, "r", encoding="utf-8") as f:
                dismissed_forms = set(json.load(f))
        except Exception:
            pass

    for item in pending_forms:
        if item.get("form_url"):
            dismissed_forms.add(item.get("form_url"))
        if item.get("id"):
            dismissed_forms.add(item.get("id"))

    count = len(pending_forms)
    with open(PENDING_FORMS_JSON, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

    with open(DISMISSED_FORMS_JSON, "w", encoding="utf-8") as f:
        json.dump(list(dismissed_forms), f, indent=2)

    return count


def dismiss_pending_forms_batch(form_ids: list) -> int:
    """Removes multiple pending forms by their IDs and blacklists them from reappearing."""
    if not form_ids:
        return 0
    os.makedirs(DATA_DIR, exist_ok=True)
    id_set = set(str(i) for i in form_ids)

    pending_forms = []
    if os.path.exists(PENDING_FORMS_JSON):
        try:
            with open(PENDING_FORMS_JSON, "r", encoding="utf-8") as f:
                pending_forms = json.load(f)
        except Exception:
            pending_forms = []

    dismissed_forms = set()
    if os.path.exists(DISMISSED_FORMS_JSON):
        try:
            with open(DISMISSED_FORMS_JSON, "r", encoding="utf-8") as f:
                dismissed_forms = set(json.load(f))
        except Exception:
            pass

    remaining = []
    removed_count = 0
    for item in pending_forms:
        if str(item.get("id")) in id_set:
            removed_count += 1
            if item.get("form_url"):
                dismissed_forms.add(item.get("form_url"))
            if item.get("id"):
                dismissed_forms.add(str(item.get("id")))
        else:
            remaining.append(item)

    with open(PENDING_FORMS_JSON, "w", encoding="utf-8") as f:
        json.dump(remaining, f, indent=2)

    with open(DISMISSED_FORMS_JSON, "w", encoding="utf-8") as f:
        json.dump(list(dismissed_forms), f, indent=2)

    return removed_count


def dismiss_recruiter_lead(lead_id: str = None, email: str = None) -> bool:
    """Removes a recruiter email lead and blacklists it from reappearing."""
    os.makedirs(DATA_DIR, exist_ok=True)
    recruiter_leads = []
    if os.path.exists(RECRUITER_LEADS_JSON):
        try:
            with open(RECRUITER_LEADS_JSON, "r", encoding="utf-8") as f:
                recruiter_leads = json.load(f)
        except Exception:
            recruiter_leads = []

    dismissed_emails = set()
    if os.path.exists(DISMISSED_RECRUITERS_JSON):
        try:
            with open(DISMISSED_RECRUITERS_JSON, "r", encoding="utf-8") as f:
                dismissed_emails = set(json.load(f))
        except Exception:
            pass

    remaining = []
    for item in recruiter_leads:
        if (lead_id and str(item.get("id")) == str(lead_id)) or (email and item.get("email") == email):
            if item.get("email"):
                dismissed_emails.add(item.get("email"))
            if item.get("id"):
                dismissed_emails.add(str(item.get("id")))
        else:
            remaining.append(item)

    if email:
        dismissed_emails.add(email)
    if lead_id:
        dismissed_emails.add(str(lead_id))

    with open(RECRUITER_LEADS_JSON, "w", encoding="utf-8") as f:
        json.dump(remaining, f, indent=2)

    with open(DISMISSED_RECRUITERS_JSON, "w", encoding="utf-8") as f:
        json.dump(list(dismissed_emails), f, indent=2)

    return True


def dismiss_recruiter_leads_batch(lead_ids: list) -> int:
    """Removes multiple recruiter leads by their IDs and blacklists them from reappearing."""
    if not lead_ids:
        return 0
    os.makedirs(DATA_DIR, exist_ok=True)
    id_set = set(str(i) for i in lead_ids)

    recruiter_leads = []
    if os.path.exists(RECRUITER_LEADS_JSON):
        try:
            with open(RECRUITER_LEADS_JSON, "r", encoding="utf-8") as f:
                recruiter_leads = json.load(f)
        except Exception:
            recruiter_leads = []

    dismissed_emails = set()
    if os.path.exists(DISMISSED_RECRUITERS_JSON):
        try:
            with open(DISMISSED_RECRUITERS_JSON, "r", encoding="utf-8") as f:
                dismissed_emails = set(json.load(f))
        except Exception:
            pass

    remaining = []
    removed_count = 0
    for item in recruiter_leads:
        if str(item.get("id")) in id_set:
            removed_count += 1
            if item.get("email"):
                dismissed_emails.add(item.get("email"))
            if item.get("id"):
                dismissed_emails.add(str(item.get("id")))
        else:
            remaining.append(item)

    with open(RECRUITER_LEADS_JSON, "w", encoding="utf-8") as f:
        json.dump(remaining, f, indent=2)

    with open(DISMISSED_RECRUITERS_JSON, "w", encoding="utf-8") as f:
        json.dump(list(dismissed_emails), f, indent=2)

    return removed_count
    """Removes a recruiter email lead and blacklists it from reappearing."""
    os.makedirs(DATA_DIR, exist_ok=True)
    recruiter_leads = []
    if os.path.exists(RECRUITER_LEADS_JSON):
        try:
            with open(RECRUITER_LEADS_JSON, "r", encoding="utf-8") as f:
                recruiter_leads = json.load(f)
        except Exception:
            recruiter_leads = []

    dismissed_emails = set()
    if os.path.exists(DISMISSED_RECRUITERS_JSON):
        try:
            with open(DISMISSED_RECRUITERS_JSON, "r", encoding="utf-8") as f:
                dismissed_emails = set(json.load(f))
        except Exception:
            pass

    remaining = []
    for item in recruiter_leads:
        if (lead_id and item.get("id") == lead_id) or (email and item.get("email") == email):
            if item.get("email"):
                dismissed_emails.add(item.get("email"))
            if item.get("id"):
                dismissed_emails.add(item.get("id"))
        else:
            remaining.append(item)

    if email:
        dismissed_emails.add(email)
    if lead_id:
        dismissed_emails.add(lead_id)

    with open(RECRUITER_LEADS_JSON, "w", encoding="utf-8") as f:
        json.dump(remaining, f, indent=2)

    with open(DISMISSED_RECRUITERS_JSON, "w", encoding="utf-8") as f:
        json.dump(list(dismissed_emails), f, indent=2)

    return True


if __name__ == "__main__":
    res = sync_leads()
    print("Pending Forms Count:", len(res["forms"]))
    print("Recruiter Leads Count:", len(res["emails"]))
