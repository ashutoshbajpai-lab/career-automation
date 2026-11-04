# Anti-Ban LinkedIn Automation Suite

Automated pipeline designed specifically to protect your LinkedIn profile while extracting hiring leads, Google Forms, and managing applications.

## Key Features

1. **Anti-Ban Architecture (Zero Risk Mode)**:
   - Connects to your authentic Chrome profile on port 9222 via Chrome DevTools Protocol (CDP).
   - Preserves all authentic session cookies, TLS fingerprints, and hardware canvas signatures.
   - Bypasses LinkedIn 2FA & bot-detection checkpoints.
   - Incorporates randomized pauses (2.5–5.5 seconds), human-like smooth scrolling, and strict daily application caps (default: max 12/day).

2. **Feed Harvester**:
   - Scrolls your LinkedIn feed naturally.
   - Unfolds truncated posts ("...see more").
   - Regex-extracts all email addresses (`@...`).
   - Extracts Google Forms (`forms.gle`), Typeforms, Airtables, and Notion recruitment boards.
   - Captures author profile and embedded hiring links.
   - Deduplicates and exports cleanly to `data/feed_leads.csv` and `data/feed_leads.json`.

3. **Jobs Section Filter (Analyst & APM)**:
   - Scans for target roles: Analyst (Data, Business, Product) and Associate Product Manager.
   - **Workday / Oracle / MNC Openings**: As requested, skips auto-apply for external enterprise ATS portals. Aggregates them into `data/manual_applications.csv` for manual application with direct links.
   - **Easy Apply**: Safely completes multi-step forms. If a complex custom essay or unexpected questionnaire is encountered, cancels cleanly and routes it to the manual queue to avoid botched submissions.

---

## Quick Start

### 1. Launch Chrome with Debugging Port (Recommended)
Run the helper script once:
```bash
/Users/ashutoshbajpai/.gemini/antigravity/scratch/linkedin_automation/start_chrome.sh
```
Log in to your LinkedIn account in this Chrome browser if you aren't already.

### 2. Run the Automation
```bash
python3 /Users/ashutoshbajpai/.gemini/antigravity/scratch/linkedin_automation/run_automation.py
```

### 3. Check the Results
All output is stored in `/Users/ashutoshbajpai/.gemini/antigravity/scratch/linkedin_automation/data/`:
- `feed_leads.csv`: All discovered emails, Google forms, and hiring links from the feed.
- `manual_applications.csv`: Workday, Oracle, and MNC openings queued for manual submission.
- `applied_jobs.csv`: Successfully submitted Easy Apply applications.
- `latest_run_summary.md`: Formatted markdown summary of the last run.
