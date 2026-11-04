import os
import json
import logging
from browser_session import BrowserManager, human_delay

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Inspector")

def inspect_profile(profile_url: str):
    mgr = BrowserManager()
    ctx, page = mgr.get_context_and_page()
    try:
        page.goto(profile_url, wait_until="domcontentloaded")
        human_delay(4.0, 5.0)

        # 1. Get Title and URL
        title = page.title()
        curr_url = page.url
        logger.info(f"Page title: {title}")
        logger.info(f"Current URL: {curr_url}")

        # 2. Extract profile info
        info = page.evaluate('''() => {
            let name = "";
            const h1 = document.querySelector("main h1, .pv-top-card h1, h1");
            if (h1) name = h1.innerText.trim();
            if (!name) {
                const parts = document.title.split(" - ")[0].split(" | ")[0];
                name = parts.trim();
            }

            let headline = "";
            const hlEl = document.querySelector("main .text-body-medium, .pv-top-card .text-body-medium");
            if (hlEl) headline = hlEl.innerText.trim();

            // Find top card action buttons strictly inside main
            const mainButtons = Array.from(document.querySelectorAll("main button, main a.artdeco-button")).map(el => ({
                text: (el.innerText || "").trim(),
                aria: el.getAttribute("aria-label") || "",
                tagName: el.tagName
            }));

            return {
                name: name,
                headline: headline,
                buttons: mainButtons
            };
        }''')

        logger.info(f"Extracted Name: {info['name']}")
        logger.info(f"Extracted Headline: {info['headline']}")
        logger.info("Main buttons found:")
        for b in info['buttons']:
            if b['text'] or b['aria']:
                logger.info(f"  [{b['tagName']}] text='{b['text']}' | aria='{b['aria']}'")

    finally:
        mgr.close()

if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.linkedin.com/in/jaishree-2a970933b/"
    inspect_profile(url)
