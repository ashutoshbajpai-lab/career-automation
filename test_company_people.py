import json
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright

profile_dir = "/Users/ashutoshbajpai/.gemini/antigravity/scratch/linkedin_automation/chrome_profile"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=True,
        executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    company = "swiggy-in"
    url = f"https://www.linkedin.com/company/{company}/people/?keywords=Punjab%20Engineering%20College"
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    print("Alumni URL:", page.url)

    alumni = page.evaluate("""() => {
        const results = [];
        const seen = new Set();
        document.querySelectorAll("li, div").forEach(el => {
            const link = el.querySelector("a[href*='/in/']");
            if (link && link.innerText) {
                const name = link.innerText.trim().split('\\n')[0];
                const href = link.href.split('?')[0];
                if (!seen.has(href) && name.length > 2 && name.length < 50 && !name.toLowerCase().includes('view')) {
                    seen.add(href);
                    results.push({
                        name: name,
                        profile_url: href,
                        text: el.innerText ? el.innerText.replace(/\\n+/g, ' ').substring(0, 160) : ''
                    });
                }
            }
        });
        return results.slice(0, 5);
    }""")
    print("Found Alumni:", json.dumps(alumni, indent=2))
    ctx.close()
