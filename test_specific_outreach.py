"""
test_specific_outreach.py - Tests targeted messaging and connection outreach
for the specified LinkedIn profiles:
1. https://www.linkedin.com/in/jaishree-2a970933b/
2. https://www.linkedin.com/in/ojasvi-pandey-9ab32120a/
"""

import os
import csv
import json
import logging
from datetime import datetime
from browser_session import BrowserManager, human_delay

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TargetOutreach")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTREACH_CSV = os.path.join(DATA_DIR, "outreach_tracker.csv")
OUTREACH_JSON = os.path.join(DATA_DIR, "outreach_tracker.json")


def record_outreach(item: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    file_exists = os.path.exists(OUTREACH_CSV)
    with open(OUTREACH_CSV, "a", newline="", encoding="utf-8") as f:
        fieldnames = ["timestamp", "name", "company", "headline", "profile_url", "action_type", "status", "message_text"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(item)

    history = []
    if os.path.exists(OUTREACH_JSON):
        try:
            with open(OUTREACH_JSON, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append(item)
    with open(OUTREACH_JSON, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)
    logger.info(f"Recorded outreach event for {item['name']} into tracker CSV/JSON.")


def send_outreach(page, profile_url: str) -> dict:
    logger.info("=" * 60)
    logger.info(f"Navigating to Profile: {profile_url}")
    logger.info("=" * 60)

    page.goto(profile_url, wait_until="domcontentloaded")
    human_delay(3.5, 4.5)

    # 1. Profile metadata extraction
    data = page.evaluate('''() => {
        let name = "";
        const h1 = document.querySelector("main h1, .pv-top-card h1, h1");
        if (h1) name = h1.innerText.trim();
        if (!name) {
            name = document.title.split(" - ")[0].split(" | ")[0].trim();
        }

        // Clean trailing punctuation or dots
        name = name.replace(/[\\.\\,\\-\\s]+$/, '').trim();

        // Check relationship degree
        const bodyText = document.body.innerText;
        const is1st = bodyText.includes(" • 1st") || bodyText.includes("1st degree connection");

        // Check college/highlight mentions
        const hasPEC = bodyText.toLowerCase().includes("punjab engineering college") || bodyText.toLowerCase().includes("pec");

        // Find compose href if 1st degree
        const composeLink = document.querySelector('main a[href*="/messaging/compose/"]');
        const composeHref = composeLink ? composeLink.getAttribute('href') : null;

        // Check if Connect button exists
        const mainButtons = Array.from(document.querySelectorAll("main button, main a"));
        const connectBtn = mainButtons.find(b => (b.innerText || '').trim().toLowerCase() === 'connect');

        return {
            name: name,
            is1st: is1st,
            hasPEC: hasPEC,
            composeHref: composeHref,
            hasDirectConnect: !!connectBtn
        };
    }''')

    name = data['name']
    first_name = name.split()[0] if name else "there"
    is_1st = data['is1st']
    has_pec = data['hasPEC']
    compose_href = data['composeHref']

    logger.info(f"Candidate: {name} | 1st Degree: {is_1st} | PEC Alumni: {has_pec}")

    # 2. Personalized message tailoring
    if "jaishree" in name.lower() or "jaishree" in profile_url:
        custom_msg = (
            f"Hi {first_name}, hope you are doing well! Great to connect with a fellow PECian here. "
            f"I saw your recent update regarding your experience at Britannia — really inspiring work! "
            f"As I'm actively exploring product management and analytics opportunities, I'd love to stay in touch and exchange notes sometime."
        )
    elif "ojasvi" in name.lower() or "ojasvi" in profile_url:
        custom_msg = (
            f"Hi {first_name}, hope you're having a great week! Saw your update regarding the Dream11 product challenge at Inter IIT Tech Meet — fantastic accomplishment! "
            f"As someone actively working in analytics and product roles, I'd love to stay connected and exchange thoughts on product strategy."
        )
    elif has_pec:
        custom_msg = (
            f"Hi {first_name}, noticed you also went to PEC! As a fellow PEC alumnus exploring product and analytics opportunities, "
            f"I would love to connect and learn from your journey."
        )
    else:
        custom_msg = (
            f"Hi {first_name}, I came across your profile while exploring analytics and product roles. "
            f"I would love to connect with you and stay in touch!"
        )

    action_type = "None"
    status = "Pending"

    # 3. Direct Message Flow for 1st-Degree Connections
    if is_1st or compose_href:
        logger.info(f"Target is a 1st-degree connection. Launching direct message composer...")
        if compose_href:
            compose_url = "https://www.linkedin.com" + compose_href if compose_href.startswith("/") else compose_href
            page.goto(compose_url, wait_until="domcontentloaded")
            human_delay(3.0, 4.0)
        else:
            msg_btn = page.locator("main a[href*='/messaging/compose/'], main a:has-text('Message')").first
            msg_btn.click()
            human_delay(2.5, 3.5)

        # Type message into contenteditable textbox
        textbox = page.locator("div.msg-form__contenteditable[role='textbox'], div[role='textbox'].msg-form__contenteditable").first
        if textbox.count() > 0:
            logger.info("Found message textbox. Entering personalized outreach message...")
            textbox.click()
            human_delay(0.5, 1.0)
            textbox.fill(custom_msg)
            human_delay(1.5, 2.5)

            # Click send button
            send_btn = page.locator("button.msg-form__send-button, button[type='submit']:has-text('Send')").first
            if send_btn.count() > 0 and not send_btn.is_disabled():
                logger.info("Clicking Send button...")
                send_btn.click()
                human_delay(2.5, 3.5)
                action_type = "1st-Degree Direct Message"
                status = "Delivered"
                logger.info("SUCCESS: Direct message delivered successfully!")
            else:
                action_type = "1st-Degree Direct Message"
                status = "Send button disabled/not ready"
        else:
            logger.warning("Could not locate message textbox on compose page.")
            action_type = "1st-Degree Direct Message"
            status = "Textbox Not Found"

    # 4. Connection Request Flow for 2nd/3rd Degree
    else:
        logger.info(f"Target is 2nd/3rd degree. Initiating connection request with note...")
        connect_btn = page.locator("main button:has-text('Connect')").first
        if connect_btn.count() == 0:
            # Check More menu
            more_btn = page.locator("main section button:has-text('More'), main button:has-text('More')").first
            if more_btn.count() > 0:
                more_btn.click()
                human_delay(1.0, 1.5)
                connect_btn = page.locator("[role='menuitem']:has-text('Connect'), button:has-text('Connect')").first

        if connect_btn.count() > 0:
            connect_btn.click()
            human_delay(1.5, 2.5)

            add_note_btn = page.locator("button:has-text('Add a note'), button[aria-label='Add a note']").first
            if add_note_btn.count() > 0 and add_note_btn.is_visible():
                add_note_btn.click()
                human_delay(1.0, 1.5)

                textarea = page.locator("textarea[name='message'], textarea#custom-message").first
                if textarea.count() > 0:
                    textarea.fill(custom_msg[:300])
                    human_delay(1.0, 2.0)

            send_inv_btn = page.locator("button:has-text('Send'), button[aria-label='Send invitation'], button[aria-label='Send now']").first
            if send_inv_btn.count() > 0 and send_inv_btn.is_visible():
                send_inv_btn.click()
                human_delay(2.0, 3.0)
                action_type = "Connection Request + Note"
                status = "Delivered"
                logger.info("SUCCESS: Connection request with note sent successfully!")
            else:
                action_type = "Connection Request"
                status = "Modal Pending"
        else:
            action_type = "Connection Request"
            status = "Already Connected or Pending"

    result_item = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "name": name,
        "company": "PEC Alumni" if has_pec else "IIT Jodhpur",
        "headline": "1st-Degree Connection" if is_1st else "Target Profile",
        "profile_url": profile_url,
        "action_type": action_type,
        "status": status,
        "message_text": custom_msg
    }
    record_outreach(result_item)
    return result_item


def main():
    targets = [
        "https://www.linkedin.com/in/jaishree-2a970933b/",
        "https://www.linkedin.com/in/ojasvi-pandey-9ab32120a/"
    ]

    mgr = BrowserManager()
    context, page = mgr.get_context_and_page()

    results = []
    try:
        for t in targets:
            res = send_outreach(page, t)
            results.append(res)
            human_delay(3.0, 5.0)

        print("\n" + "=" * 60)
        print("         LINKEDIN TARGETED OUTREACH REPORT         ")
        print("=" * 60)
        for r in results:
            print(f"• Candidate: {r['name']}")
            print(f"  Profile:   {r['profile_url']}")
            print(f"  Action:    {r['action_type']}")
            print(f"  Status:    {r['status']}")
            print(f"  Message:   \"{r['message_text'][:120]}...\"\n")

    finally:
        mgr.close()


if __name__ == "__main__":
    main()
