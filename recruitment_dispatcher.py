"""
recruitment_dispatcher.py - Classifies scraped recruitment posts into:
1. Application Forms Pending (Google Forms, Typeforms) -> For manual application.
2. Harvested Recruiter Emails -> Prepares tailored referral / application emails.
"""

import os
import json
import logging
from urllib.parse import quote
from datetime import datetime

logger = logging.getLogger("RecruitmentDispatcher")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
FEED_LEADS_JSON = os.path.join(DATA_DIR, "feed_leads.json")
PENDING_FORMS_JSON = os.path.join(DATA_DIR, "pending_forms.json")
RECRUITER_LEADS_JSON = os.path.join(DATA_DIR, "recruiter_leads.json")

CANDIDATE_NAME = "Ashutosh Bajpai"
CANDIDATE_COLLEGE = "Punjab Engineering College (PEC)"
CANDIDATE_EMAIL = "ashutosh.bajpai.028works@gmail.com"
CANDIDATE_PHONE = "8081377486"


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

    # Load existing if available
    if os.path.exists(PENDING_FORMS_JSON):
        try:
            with open(PENDING_FORMS_JSON, "r", encoding="utf-8") as f:
                pending_forms = json.load(f)
                seen_forms = {item.get("form_url") for item in pending_forms if item.get("form_url")}
        except Exception:
            pending_forms = []

    if os.path.exists(RECRUITER_LEADS_JSON):
        try:
            with open(RECRUITER_LEADS_JSON, "r", encoding="utf-8") as f:
                recruiter_leads = json.load(f)
                seen_emails = {item.get("email") for item in recruiter_leads if item.get("email")}
        except Exception:
            recruiter_leads = []

    for post in feed_leads:
        author = post.get("author", "LinkedIn Poster")
        preview = post.get("preview", "")
        timestamp = post.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # 1. Process Form Links
        forms_str = post.get("form_links", "")
        if forms_str:
            for form_url in [u.strip() for u in forms_str.split(",") if u.strip()]:
                if form_url not in seen_forms:
                    seen_forms.add(form_url)
                    pending_forms.append({
                        "id": str(abs(hash(form_url))),
                        "timestamp": timestamp,
                        "poster": author,
                        "form_url": form_url,
                        "context": preview[:180],
                        "status": "Pending Manual Fill"
                    })

        # 2. Process Recruiter Emails
        emails_str = post.get("emails", "")
        if emails_str:
            for email in [e.strip() for e in emails_str.split(",") if e.strip()]:
                if email not in seen_emails:
                    seen_emails.add(email)
                    subject = f"Application for Analyst / Product Role - {CANDIDATE_NAME} ({CANDIDATE_COLLEGE})"
                    body = (
                        f"Hi {author.split()[0] if author else 'Hiring Team'},\n\n"
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

                    recruiter_leads.append({
                        "id": str(abs(hash(email))),
                        "timestamp": timestamp,
                        "recipient_name": author,
                        "email": email,
                        "subject": subject,
                        "draft_body": body,
                        "mailto_link": mailto,
                        "gmail_web_link": gmail_web_link,
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


if __name__ == "__main__":
    res = sync_leads()
    print("Pending Forms Count:", len(res["forms"]))
    print("Recruiter Leads Count:", len(res["emails"]))
