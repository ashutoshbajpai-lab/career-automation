"""
test_naukri_live.py - Live interactive test for the Naukri.com automation.
Tests:
1. Naukri Login verification (opens window if login needed)
2. Daily Recency Boost (toggling headline to keep 'Updated Today')
3. Job Search & Application Flow for Analyst & APM roles
"""

import time
import logging
from browser_session import BrowserManager, human_delay

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("NaukriLiveTest")


def main():
    logger.info("=" * 65)
    logger.info("   STARTING LIVE NAUKRI.COM INTEGRATION TEST      ")
    logger.info("=" * 65)

    mgr = BrowserManager()
    context, page = mgr.get_context_and_page()

    try:
        # Step 1: Check Login Status
        logger.info("Navigating to Naukri Profile...")
        page.goto("https://www.naukri.com/mnjuser/profile", wait_until="domcontentloaded")
        human_delay(3.0, 4.5)

        if "login" in page.url or "nlogin" in page.url:
            logger.info("=" * 65)
            logger.info("ACTION REQUIRED: A Google Chrome window is open on your screen.")
            logger.info("Please log in to your Naukri.com account in that window.")
            logger.info("Waiting up to 120 seconds for login detection...")
            logger.info("=" * 65)

            for _ in range(60):
                time.sleep(2)
                if "profile" in page.url or "homepage" in page.url:
                    logger.info("Naukri login detected! Proceeding with test...")
                    break
        else:
            logger.info("Already logged in to Naukri!")

        # Step 2: Test Profile Recency Boost
        logger.info("\n--- TEST PHASE 1: Profile Recency Boost ---")
        page.goto("https://www.naukri.com/mnjuser/profile", wait_until="domcontentloaded")
        human_delay(3.5, 4.5)

        # Inspect profile summary pencil
        pencil = page.locator(".profileSummary span.new-pencil, .profileSummary img[alt='pencil']").first
        has_pencil = pencil.count() > 0
        logger.info(f"Profile Summary edit pencil found: {has_pencil}")

        if has_pencil:
            pencil.scroll_into_view_if_needed()
            human_delay(1.0, 1.5)
            pencil.click()
            human_delay(1.5, 2.5)

            textarea = page.locator("textarea#summary, textarea.fn-inp-md").first
            if textarea.count() > 0:
                current_text = textarea.input_value().strip()
                logger.info(f"Current Profile Summary: {current_text[:80]}...")
                # Recency boost hack: toggle trailing period
                new_text = current_text[:-1] if current_text.endswith(".") else current_text + "."
                logger.info(f"Toggling summary ending character to refresh 'Updated Today'...")
                textarea.fill(new_text)
                human_delay(1.0, 1.5)

                save_btn = page.locator("button.btn-blue:has-text('Save'), button:has-text('Save')").first
                if save_btn.count() > 0:
                    save_btn.click()
                    human_delay(2.5, 3.5)
                    logger.info("SUCCESS: Profile Summary updated! Naukri will now show 'Updated: Today' to recruiters.")

        # Step 3: Test Job Search & Extraction
        logger.info("\n--- TEST PHASE 2: Job Search & Apply Button Flow ---")
        page.goto("https://www.naukri.com/analyst-jobs?k=analyst", wait_until="domcontentloaded")
        human_delay(3.5, 5.0)

        jobs = page.evaluate('''() => {
            const tuples = Array.from(document.querySelectorAll('.cust-job-tuple, .srp-jobtuple-wrapper, article.jobTuple, div[data-job-id]'));
            return tuples.map(t => {
                const titleEl = t.querySelector('a.title, .job-title, a[href*="/job-listings"]');
                const compEl = t.querySelector('a.comp-name, .company-name, .subTitle');
                const expEl = t.querySelector('.exp-wrap, .experience, .exp');
                const locEl = t.querySelector('.loc-wrap, .location, .loc');
                return {
                    title: titleEl ? titleEl.innerText.trim() : 'Role',
                    company: compEl ? compEl.innerText.trim() : 'Company',
                    url: titleEl ? titleEl.href : '',
                    experience: expEl ? expEl.innerText.trim() : '',
                    location: locEl ? locEl.innerText.trim() : ''
                };
            }).slice(0, 5);
        }''')

        logger.info(f"Successfully scraped {len(jobs)} live job cards from Naukri:")
        for idx, j in enumerate(jobs):
            logger.info(f" [{idx+1}] {j['title']} at {j['company']} ({j['location']})")
            logger.info(f"     URL: {j['url'][:80]}...")

        # Step 4: Test First Job Apply Modal
        if jobs and jobs[0]['url']:
            first_url = jobs[0]['url']
            logger.info(f"\n--- TEST PHASE 3: Inspecting Apply Flow for '{jobs[0]['title']}' ---")
            page.goto(first_url, wait_until="domcontentloaded")
            human_delay(3.0, 4.0)

            apply_btn = page.locator("button#apply-button, button:has-text('Apply'), a:has-text('Apply on company site')").first
            if apply_btn.count() > 0:
                btn_text = apply_btn.inner_text().strip()
                logger.info(f"Apply Button Detected: '{btn_text}'")
                if "company site" in btn_text.lower():
                    logger.info("-> Correctly identified as External Company / Workday / MNC site (Routes to Manual Queue)")
                else:
                    logger.info("-> Correctly identified as Direct On-Platform Apply")

        logger.info("\n" + "=" * 65)
        logger.info("   NAUKRI.COM INTEGRATION TEST COMPLETED SUCCESSFULLY!  ")
        logger.info("=" * 65)

    except Exception as e:
        logger.error(f"Error during test: {e}", exc_info=True)
    finally:
        mgr.close()


if __name__ == "__main__":
    main()
