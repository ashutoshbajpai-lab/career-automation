import os, json, time
from playwright.sync_api import sync_playwright

BASE_DIR = "/Users/ashutoshbajpai/.gemini/antigravity/scratch/linkedin_automation"
session_file = os.path.join(BASE_DIR, "data", "session_cookies.json")
with open(session_file) as f:
    cookies = json.load(f).get("cookies", [])

from browser_session import BrowserManager
mgr = BrowserManager(profile_name="default")
context, page = mgr.get_context_and_page(force_headless=True)
page.route("**/*", lambda r: r.abort() if r.request.resource_type in ["image", "media", "font"] else r.continue_())
page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
time.sleep(4)

script = '''() => {
    const main = document.querySelector('main');
    if (!main) return { error: 'No main element found', url: window.location.href, title: document.title };
    
    // Find all article or post containers
    const containers = Array.from(main.querySelectorAll('div, section, article')).filter(el => {
        return (el.innerText || '').length > 80 && el.querySelector('a[href*="/in/"]');
    });
    
    return {
        url: window.location.href,
        title: document.title,
        mainChildren: main.children.length,
        potentialContainers: containers.length,
        samples: containers.slice(0, 3).map(c => ({
            tag: c.tagName,
            className: c.className,
            textSnippet: (c.innerText || '').slice(0, 100),
            hasAuthorLink: !!c.querySelector('a[href*="/in/"]')
        }))
    };
}'''

result = page.evaluate(script)
print(json.dumps(result, indent=2))
mgr.close()
