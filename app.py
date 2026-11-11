"""
app.py - Meraki UI Command Center for LinkedIn & Naukri Career Automation.
Features:
1. Executive Dashboard matching user's Meraki UI reference
2. Real-time background operations & manual action triggers
3. Gmail Inbox Intelligence (Exam, Assessment, Next Steps, Applications)
4. Application Forms Pending Desk (Google Forms, Typeforms from hiring posts)
5. Recruiter Email Outreach Desk (1-click Gmail compose drafts)
6. Alumni Referral Engine with Punjab Engineering College (PEC) priority
7. Naukri Daily Recency Booster & 50+ Mass Apply
8. Manual Intervention Desk for Enterprise ATS (Workday, Oracle) & Questionnaires
9. Live terminal streaming console
"""

import os
import gc
import csv
import json
import time
import base64
import schedule
import logging
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request, render_template_string
from werkzeug.utils import secure_filename

IST = timezone(timedelta(hours=5, minutes=30))

from browser_session import BrowserManager, is_cloud_low_mem, get_tree_ram_mb, wait_for_ram_cooldown
from referral_engine import ReferralEngine
from naukri_automator import NaukriAutomator
from email_tracker import EmailTracker, EMAIL_INTEL_JSON
from recruitment_dispatcher import (
    sync_leads, PENDING_FORMS_JSON, FEED_POSTS_JSON, EASY_APPLY_JOBS_JSON, RECRUITER_LEADS_JSON, 
    dismiss_pending_form, clear_all_pending_forms, dismiss_recruiter_lead,
    dismiss_pending_forms_batch, dismiss_recruiter_leads_batch,
    dismiss_easy_apply_job, clear_all_easy_apply, dismiss_easy_apply_batch
)
from company_network_expander import CompanyNetworkExpander
from feed_harvester import FeedHarvester
from job_scanner import JobScanner
from mumbai_outreach_engine import MumbaiOutreachEngine, MUMBAI_CONTACTS_JSON, MUMBAI_COMPANIES_JSON

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MerakiApp")

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
MANUAL_CSV = os.path.join(DATA_DIR, "manual_applications.csv")
NAUKRI_APPLIED_CSV = os.path.join(DATA_DIR, "naukri_applied_jobs.csv")
LINKEDIN_APPLIED_CSV = os.path.join(DATA_DIR, "applied_jobs.csv")
OUTREACH_CSV = os.path.join(DATA_DIR, "outreach_tracker.csv")
OUTREACH_JSON = os.path.join(DATA_DIR, "outreach_tracker.json")

# Restore session cookies safely from environment variable if provided
try:
    env_b64 = os.environ.get("SESSION_COOKIES_BASE64", "").strip()
    if env_b64:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, "session_cookies.json"), "wb") as f:
            f.write(base64.b64decode(env_b64))
        logger.info("Session cookies successfully restored from secure environment variable.")
except Exception as e:
    logger.warning(f"Note on restoring session cookies: {e}")

from collections import deque

CURRENT_TASK = {"running": False, "name": "Idle", "started_at": None, "queued": []}
TASK_QUEUE = deque()
TASK_LOCK = threading.Lock()
LIVE_LOGS = []
LAST_PERIODIC_RUNS = {
    "linkedin_feed": 0,
    "naukri_apply": 0,
    "linkedin_apply": 0,
    "scan_gmail": 0,
    "scan_replies": 0,
    "pec_referral": 0,
}


def add_log(msg: str):
    ts = datetime.now(IST).strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    LIVE_LOGS.append(entry)
    logger.info(entry)
    if len(LIVE_LOGS) > 300:
        LIVE_LOGS.pop(0)


@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


LAST_MEM_CHECK = 0
CACHED_MEM_MB = 42.0

def get_stats():
    global LAST_MEM_CHECK, CACHED_MEM_MB
    today = datetime.now().strftime("%Y-%m-%d")
    naukri_count = 0
    linkedin_count = 0

    if os.path.exists(NAUKRI_APPLIED_CSV):
        try:
            with open(NAUKRI_APPLIED_CSV, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row.get("timestamp", "").startswith(today):
                        naukri_count += 1
        except Exception:
            pass

    if os.path.exists(LINKEDIN_APPLIED_CSV):
        try:
            with open(LINKEDIN_APPLIED_CSV, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row.get("timestamp", "").startswith(today):
                        linkedin_count += 1
        except Exception:
            pass

    manual_items = []
    if os.path.exists(MANUAL_CSV):
        try:
            with open(MANUAL_CSV, "r", encoding="utf-8") as f:
                manual_items = list(csv.DictReader(f))
        except Exception:
            pass

    naukri = NaukriAutomator()
    boost_status = naukri.get_boost_status()

    # Intel counts
    email_intel = []
    if os.path.exists(EMAIL_INTEL_JSON):
        try:
            with open(EMAIL_INTEL_JSON, "r", encoding="utf-8") as f:
                email_intel = json.load(f)
        except Exception:
            pass

    pending_forms = []
    if os.path.exists(PENDING_FORMS_JSON):
        try:
            with open(PENDING_FORMS_JSON, "r", encoding="utf-8") as f:
                pending_forms = json.load(f)
        except Exception:
            pass

    feed_posts = []
    if os.path.exists(FEED_POSTS_JSON):
        try:
            with open(FEED_POSTS_JSON, "r", encoding="utf-8") as f:
                feed_posts = json.load(f)
        except Exception:
            pass

    easy_apply_jobs = []
    if os.path.exists(EASY_APPLY_JOBS_JSON):
        try:
            with open(EASY_APPLY_JOBS_JSON, "r", encoding="utf-8") as f:
                easy_apply_jobs = json.load(f)
        except Exception:
            pass

    recruiter_leads = []
    if os.path.exists(RECRUITER_LEADS_JSON):
        try:
            with open(RECRUITER_LEADS_JSON, "r", encoding="utf-8") as f:
                recruiter_leads = json.load(f)
        except Exception:
            pass

    outreach_records = []
    if os.path.exists(OUTREACH_JSON):
        try:
            with open(OUTREACH_JSON, "r", encoding="utf-8") as f:
                outreach_records = json.load(f)
        except Exception:
            pass

    now_ist = datetime.now(IST)
    is_active_shift = 9 <= now_ist.hour < 17
    now_ts = time.time()
    if now_ts - LAST_MEM_CHECK > 10:
        ram_val = get_tree_ram_mb()
        if ram_val > 0:
            CACHED_MEM_MB = ram_val
        LAST_MEM_CHECK = now_ts

    has_li_at = False
    session_file = os.path.join(DATA_DIR, "session_cookies.json")
    if os.path.exists(session_file):
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                sdata = json.load(f)
            has_li_at = (
                sdata.get("status") != "expired"
                and any(c.get("name") == "li_at" and c.get("value") for c in sdata.get("cookies", []))
            )
        except Exception:
            pass

    mumbai_companies_count = 0
    mumbai_incomplete_count = 0
    try:
        if os.path.exists(MUMBAI_COMPANIES_JSON):
            with open(MUMBAI_COMPANIES_JSON, "r", encoding="utf-8") as f:
                mumbai_companies_count = len(json.load(f))
        if os.path.exists(MUMBAI_CONTACTS_JSON):
            with open(MUMBAI_CONTACTS_JSON, "r", encoding="utf-8") as f:
                mc = json.load(f)
                mumbai_incomplete_count = sum(1 for c in mc if c.get("workflow_stage") == "incomplete_pending_accept")
    except Exception:
        pass

    return {
        "naukri_today": naukri_count,
        "linkedin_today": linkedin_count,
        "total_today": naukri_count + linkedin_count,
        "manual_count": len(manual_items),
        "email_intel_count": len(email_intel),
        "pending_forms_count": len(pending_forms),
        "feed_posts_count": len(feed_posts),
        "easy_apply_count": len(easy_apply_jobs),
        "recruiter_leads_count": len(recruiter_leads),
        "outreach_count": len(outreach_records),
        "mumbai_companies_count": mumbai_companies_count,
        "mumbai_incomplete_count": mumbai_incomplete_count,
        "naukri_boost": boost_status,
        "current_task": CURRENT_TASK,
        "scheduler_status": "Active (8h Shift 09:00 - 17:00 IST)" if is_active_shift else "Standby (Resumes 09:00 AM IST)",
        "ist_time": now_ist.strftime("%H:%M:%S IST"),
        "ram_mb": CACHED_MEM_MB,
        "cloud_mode": is_cloud_low_mem(),
        "linkedin_authenticated": has_li_at
    }


def load_manual_queue():
    items = []
    if os.path.exists(MANUAL_CSV):
        try:
            with open(MANUAL_CSV, "r", encoding="utf-8") as f:
                for idx, row in enumerate(csv.DictReader(f)):
                    row["queue_id"] = str(idx)
                    items.append(row)
        except Exception:
            pass
    return list(reversed(items))


MERAKI_UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Careercommand</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
    body { font-family: 'Plus Jakarta Sans', sans-serif; }
    .custom-scroll::-webkit-scrollbar { width: 5px; height: 5px; }
    .custom-scroll::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
  </style>
</head>
<body class="bg-slate-50 text-slate-800 antialiased flex h-screen overflow-hidden">

  <!-- Left Sidebar (Meraki UI Style) -->
  <aside class="w-64 bg-white border-r border-slate-200/80 flex flex-col justify-between py-6 px-4 z-20 flex-shrink-0">
    <div class="space-y-6">
      
      <!-- Brand Logo -->
      <div class="flex items-center space-x-2.5 px-3">
        <div class="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center font-extrabold text-white shadow-md shadow-indigo-500/30">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
        </div>
        <span class="font-bold text-lg text-slate-900 tracking-tight">Career<span class="text-indigo-600">command</span></span>
      </div>

      <!-- Navigation Links -->
      <nav class="space-y-6">
        <div>
          <span class="px-3 text-[11px] font-bold text-slate-400 uppercase tracking-wider">Operations Hub</span>
          <div class="mt-2 space-y-1">
            <button onclick="switchTab('dashboard')" id="nav-dashboard"
                    class="nav-item w-full flex items-center space-x-3 px-3 py-2.5 rounded-xl text-sm font-semibold transition bg-slate-100 text-slate-900 shadow-sm">
              <i class="fa-solid fa-house w-4 text-indigo-600"></i>
              <span>Dashboard</span>
            </button>
            <button onclick="switchTab('gmail')" id="nav-gmail"
                    class="nav-item w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition">
              <div class="flex items-center space-x-3">
                <i class="fa-solid fa-envelope-open-text w-4 text-purple-600"></i>
                <span>Gmail Intel</span>
              </div>
              <span class="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-purple-100 text-purple-700" id="sidebarGmailBadge">0</span>
            </button>
            <button onclick="switchTab('feed')" id="nav-feed"
                    class="nav-item w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition">
              <div class="flex items-center space-x-3">
                <i class="fa-solid fa-rss w-4 text-teal-600"></i>
                <span>Feed Hiring Posts</span>
              </div>
              <span class="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-teal-100 text-teal-700" id="sidebarFeedBadge">0</span>
            </button>
            <button onclick="switchTab('easy-apply')" id="nav-easy-apply"
                    class="nav-item w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition">
              <div class="flex items-center space-x-3">
                <i class="fa-solid fa-bolt-lightning w-4 text-blue-600"></i>
                <span>Easy Apply & Jobs</span>
              </div>
              <span class="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700" id="sidebarEasyApplyBadge">0</span>
            </button>
            <button onclick="switchTab('recruiters')" id="nav-recruiters"
                    class="nav-item w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition">
              <div class="flex items-center space-x-3">
                <i class="fa-solid fa-paper-plane w-4 text-sky-600"></i>
                <span>Recruiter Emails</span>
              </div>
              <span class="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-sky-100 text-sky-700" id="sidebarRecruitersBadge">0</span>
            </button>
            <button onclick="switchTab('alumni')" id="nav-alumni"
                    class="nav-item w-full flex items-center space-x-3 px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition">
              <i class="fa-solid fa-graduation-cap w-4 text-amber-500"></i>
              <span>PEC Referrals</span>
            </button>
            <button onclick="switchTab('mumbai')" id="nav-mumbai"
                    class="nav-item w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition">
              <div class="flex items-center space-x-3">
                <i class="fa-solid fa-city w-4 text-indigo-600"></i>
                <span>Mumbai Network</span>
              </div>
              <span class="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-indigo-100 text-indigo-700" id="sidebarMumbaiBadge">0</span>
            </button>
            <button onclick="switchTab('naukri')" id="nav-naukri"
                    class="nav-item w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition">
              <div class="flex items-center space-x-3">
                <i class="fa-solid fa-bolt w-4 text-amber-500"></i>
                <span>Naukri Autopilot</span>
              </div>
              <span class="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700" id="sidebarNaukriBadge">0</span>
            </button>
            <button onclick="switchTab('manual')" id="nav-manual"
                    class="nav-item w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition">
              <div class="flex items-center space-x-3">
                <i class="fa-solid fa-clipboard-list w-4 text-rose-500"></i>
                <span>Manual Desk</span>
              </div>
              <span class="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-rose-100 text-rose-600" id="sidebarManualBadge">0</span>
            </button>
            <button onclick="switchTab('resume')" id="nav-resume"
                    class="nav-item w-full flex items-center space-x-3 px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition">
              <i class="fa-solid fa-file-pdf w-4 text-rose-500"></i>
              <span>Active Resume</span>
            </button>
            <button onclick="switchTab('terminal')" id="nav-terminal"
                    class="nav-item w-full flex items-center space-x-3 px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition">
              <i class="fa-solid fa-terminal w-4 text-slate-400"></i>
              <span>Live Terminal</span>
            </button>
          </div>
        </div>

        <div>
          <span class="px-3 text-[11px] font-bold text-slate-400 uppercase tracking-wider">Candidate Profile</span>
          <div class="mt-2 space-y-1">
            <div class="px-3 py-2 rounded-xl text-xs text-slate-500 flex items-center space-x-2 bg-slate-50">
              <i class="fa-solid fa-user-circle text-indigo-600 text-base"></i>
              <div>
                <p class="font-bold text-slate-900 text-xs">Ashutosh Bajpai</p>
                <p class="text-[10px] text-slate-400">PEC Chandigarh • 2026</p>
              </div>
            </div>
            <div class="px-3 py-1 text-[11px] text-slate-400">
              📞 8081377486
            </div>
          </div>
        </div>
      </nav>

    </div>

    <!-- Active State Pill -->
    <div class="p-3 bg-slate-50 rounded-xl border border-slate-200/60 text-xs flex items-center justify-between">
      <div class="flex items-center space-x-2">
        <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
        <span class="text-slate-600 font-medium">Session Active</span>
      </div>
      <span class="text-[10px] text-slate-400">All Platforms</span>
    </div>
  </aside>

  <!-- Main Content Wrapper -->
  <div class="flex-1 flex flex-col min-w-0 overflow-hidden">

    <!-- Top Navbar with Direct Trigger Controls -->
    <header class="bg-white border-b border-slate-200/80 px-6 py-3 flex flex-wrap items-center justify-between gap-3 z-10 flex-shrink-0">
      <div class="min-w-0">
        <nav class="text-xs text-slate-400 font-medium flex items-center space-x-1.5">
          <span>Pages</span>
          <span>/</span>
          <span class="text-slate-800 capitalize" id="currentBreadcrumb">Dashboard</span>
        </nav>
        <h2 class="text-xl font-bold text-slate-900 leading-tight capitalize" id="currentPageHeading">Dashboard</h2>
      </div>

      <!-- Quick Manual Triggers Row -->
      <div class="flex flex-wrap items-center gap-2">
        <!-- MASTER 1-CLICK AUTOPILOT BUTTON -->
        <button onclick="triggerMasterRunAll()" title="Single Button: Naukri Update & 50+ Apply, LinkedIn Easy Apply, Feed Harvester, and Mumbai Startups Connection Requests (No Note)"
                class="bg-gradient-to-r from-emerald-500 via-teal-500 to-indigo-600 hover:from-emerald-600 hover:to-indigo-700 text-white font-extrabold text-xs py-2 px-3.5 rounded-xl transition flex items-center gap-1.5 shadow-md shadow-emerald-500/25 ring-2 ring-emerald-400/30 animate-pulse hover:animate-none cursor-pointer">
          <i class="fa-solid fa-bolt-lightning text-amber-300"></i>
          <span>RUN EVERYTHING</span>
        </button>

        <!-- SINGLE BUTTON: NAUKRI UPDATE & APPLY ONLY -->
        <button onclick="triggerAction('naukri_all')" title="Single Button: Update Naukri Recency & Apply to 50+ Aligned Jobs ONLY"
                class="bg-amber-500 hover:bg-amber-600 text-white font-bold text-xs py-2 px-3 rounded-xl transition flex items-center gap-1.5 shadow-sm shadow-amber-500/25 cursor-pointer">
          <i class="fa-solid fa-bolt text-amber-100"></i>
          <span>Naukri Update & Apply</span>
        </button>

        <!-- SEPARATE DEDICATED MESSAGING BUTTON -->
        <button onclick="triggerAction('send_messages')" title="Send Referral Messages & Notes to Approved Connections (SEPARATE from Connection Requests)"
                class="bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs py-2 px-3 rounded-xl transition flex items-center gap-1.5 shadow-sm shadow-purple-600/30 cursor-pointer">
          <i class="fa-solid fa-comments text-purple-200"></i>
          <span>Send Messages</span>
        </button>

        <!-- STANDALONE COMPANY & STARTUP CONNECTIONS (NO NOTE) -->
        <button onclick="triggerAction('company_connect')" title="Search Mumbai Companies & Startups: check Jobs section, send Connection Requests Only (No Note)"
                class="bg-sky-50 hover:bg-sky-100 text-sky-700 border border-sky-200 font-bold text-xs py-1.5 px-2.5 rounded-xl transition flex items-center gap-1 cursor-pointer">
          <i class="fa-solid fa-building text-sky-600"></i>
          <span>Connect Startups</span>
        </button>

        <button onclick="triggerAction('linkedin_feed')" title="Harvest Feed for 100+ Hiring Posts, Forms & Recruiter Emails"
                class="bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold text-xs py-1.5 px-2.5 rounded-xl transition flex items-center gap-1 cursor-pointer">
          <i class="fa-solid fa-rss text-indigo-500"></i>
          <span>Feed (100+)</span>
        </button>
        <button onclick="triggerAction('linkedin_apply')" title="Execute LinkedIn Easy Apply for Analyst/PM"
                class="bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 font-semibold text-xs py-1.5 px-2.5 rounded-xl transition flex items-center gap-1 cursor-pointer">
          <i class="fa-brands fa-linkedin text-blue-600"></i>
          <span>Easy Apply</span>
        </button>
        <button onclick="triggerAction('scan_gmail')" title="Scan Full Inbox for Application Updates"
                class="bg-purple-50 hover:bg-purple-100 text-purple-700 border border-purple-200 font-semibold text-xs py-1.5 px-2.5 rounded-xl transition flex items-center gap-1 cursor-pointer">
          <i class="fa-solid fa-envelope-circle-check text-purple-600"></i>
          <span>Gmail</span>
        </button>

        <!-- LinkedIn Session Auth Pill & Modal Trigger -->
        <button onclick="openSessionModal()" id="btnSessionModal" title="Manage LinkedIn li_at Cookie & Cloud Authentication"
                class="px-2.5 py-1 text-xs font-semibold rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-300 flex items-center gap-1.5 shadow-sm transition cursor-pointer">
          <i class="fa-brands fa-linkedin text-blue-600 text-xs"></i>
          <span id="sessionStatusText">LinkedIn Auth</span>
        </button>

        <div id="taskStatusPill" class="px-2.5 py-1 text-xs font-semibold rounded-xl bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1.5 shadow-sm">
          <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
          <span id="taskStatusText">System Idle</span>
        </div>
        <button onclick="resetTaskLock()" title="Reset task lock if hung" class="text-[11px] text-slate-400 hover:text-rose-600 transition px-1.5 py-1 flex items-center gap-1 bg-slate-100 hover:bg-rose-50 rounded-lg">
          <i class="fa-solid fa-rotate-left text-slate-500"></i>
          <span>Reset</span>
        </button>
        
        <div class="w-8 h-8 rounded-xl bg-indigo-600 flex items-center justify-center font-bold text-white text-xs shadow-md shadow-indigo-500/20 ml-1">
          AB
        </div>
      </div>
    </header>

    <!-- Scrollable Workspace Body -->
    <main class="flex-1 overflow-y-auto p-8 custom-scroll space-y-6">

      <!-- ========================================== -->
      <!-- TAB 1: DASHBOARD VIEW                       -->
      <!-- ========================================== -->
      <div id="view-dashboard" class="space-y-6">

        <!-- Master Autopilot Single Launch Card -->
        <div class="bg-gradient-to-r from-slate-900 via-indigo-950 to-slate-900 rounded-3xl p-6 text-white border border-indigo-500/20 shadow-xl flex items-center justify-between flex-wrap gap-4">
          <div class="space-y-1.5 max-w-xl">
            <div class="flex items-center gap-2">
              <span class="px-2.5 py-0.5 rounded-full text-[10px] font-extrabold bg-emerald-500 text-slate-950 uppercase tracking-wider flex items-center gap-1.5">
                <span class="w-1.5 h-1.5 rounded-full bg-slate-950 animate-ping"></span> Master One-Click Autopilot
              </span>
              <span class="text-xs text-emerald-300 font-medium">Modular & Clean Execution</span>
            </div>
            <h3 class="text-lg font-bold text-white">Autonomous Career Engine Launchpad</h3>
            <p class="text-xs text-slate-300 leading-relaxed">
              <strong>Single Button Pipeline</strong>: 1. <strong>Naukri Recency Boost</strong> & <strong>50+ Mass Apply</strong> • 2. <strong>LinkedIn Feed Harvester</strong> (Google Forms & Emails) • 3. <strong>LinkedIn Easy Apply</strong> • 4. <strong>Mumbai & Startups Network Expander</strong> (Checks open jobs, sends <em>Connection Requests Only — No Note Attached</em>).
            </p>
            <p class="text-[11px] text-purple-300 flex items-center gap-1.5">
              <i class="fa-solid fa-shield-halved"></i>
              <span>Strict Rule Enforced: Connection requests are sent with <strong>NO notes</strong>. Messaging has its own separate button below.</span>
            </p>
          </div>
          <div class="flex flex-col sm:flex-row items-center gap-3">
            <button onclick="triggerMasterRunAll()" id="btnMasterHeroRun"
                    class="bg-gradient-to-r from-emerald-400 via-teal-400 to-cyan-400 hover:from-emerald-300 hover:to-cyan-300 text-slate-950 font-black text-sm py-3.5 px-6 rounded-2xl shadow-xl shadow-emerald-500/30 flex items-center gap-2.5 transition transform hover:scale-[1.02] active:scale-[0.98] cursor-pointer">
              <i class="fa-solid fa-play text-slate-950 text-base"></i>
              <span id="masterHeroRunLabel">START ALL OPERATIONS</span>
            </button>
            <button onclick="triggerAction('send_messages')"
                    class="bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs py-3.5 px-4 rounded-2xl shadow-lg shadow-purple-600/30 flex items-center gap-2 transition cursor-pointer">
              <i class="fa-solid fa-comments"></i>
              <span>Send Referral Messages (Separate)</span>
            </button>
          </div>
        </div>

        <!-- 4 Metric Cards Row -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          
          <!-- Card 1: Today's Applications -->
          <div class="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm flex items-center justify-between hover:shadow-md transition">
            <div>
              <p class="text-xs font-semibold text-slate-400">Total Applied Today</p>
              <div class="flex items-baseline space-x-2 mt-1">
                <h3 class="text-2xl font-bold text-slate-900" id="cardTodayCount">10</h3>
                <span class="text-xs font-semibold text-emerald-500">+50 Target</span>
              </div>
            </div>
            <div class="w-12 h-12 rounded-xl bg-indigo-600 flex items-center justify-center text-white shadow-md shadow-indigo-600/30">
              <i class="fa-solid fa-paper-plane text-lg"></i>
            </div>
          </div>

          <!-- Card 2: Feed Hiring Posts -->
          <div class="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm flex items-center justify-between hover:shadow-md transition cursor-pointer" onclick="switchTab('feed')">
            <div>
              <p class="text-xs font-semibold text-slate-400">Feed Hiring Posts</p>
              <div class="flex items-baseline space-x-2 mt-1">
                <h3 class="text-2xl font-bold text-slate-900" id="cardFeedCount">0</h3>
                <span class="text-xs font-semibold text-teal-600">Google & Forms</span>
              </div>
            </div>
            <div class="w-12 h-12 rounded-xl bg-teal-600 flex items-center justify-center text-white shadow-md shadow-teal-600/30">
              <i class="fa-solid fa-rss text-lg"></i>
            </div>
          </div>

          <!-- Card 3: Easy Apply & Target Jobs -->
          <div class="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm flex items-center justify-between hover:shadow-md transition cursor-pointer" onclick="switchTab('easy-apply')">
            <div>
              <p class="text-xs font-semibold text-slate-400">Easy Apply & Jobs</p>
              <div class="flex items-baseline space-x-2 mt-1">
                <h3 class="text-2xl font-bold text-slate-900" id="cardEasyApplyCount">0</h3>
                <span class="text-xs font-semibold text-blue-600">0-2 Yrs Roles</span>
              </div>
            </div>
            <div class="w-12 h-12 rounded-xl bg-blue-600 flex items-center justify-center text-white shadow-md shadow-blue-600/30">
              <i class="fa-solid fa-bolt-lightning text-lg"></i>
            </div>
          </div>

          <!-- Card 4: Recruiter Outreach & Leads -->
          <div class="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm flex items-center justify-between hover:shadow-md transition cursor-pointer" onclick="switchTab('recruiters')">
            <div>
              <p class="text-xs font-semibold text-slate-400">Recruiter Emails</p>
              <div class="flex items-baseline space-x-2 mt-1">
                <h3 class="text-2xl font-bold text-slate-900" id="cardRecruiterCount">0</h3>
                <span class="text-xs font-semibold text-sky-500">Drafts Ready</span>
              </div>
            </div>
            <div class="w-12 h-12 rounded-xl bg-sky-500 flex items-center justify-center text-white shadow-md shadow-sky-500/30">
              <i class="fa-solid fa-envelope-open-text text-lg"></i>
            </div>
          </div>

        </div>

        <!-- Meraki Dark Navy Hero Chart Card -->
        <div class="bg-[#1e1b4b] rounded-3xl p-7 text-white shadow-xl relative overflow-hidden">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h3 class="text-lg font-bold">Active Applications & Pipeline Momentum</h3>
              <p class="text-xs text-indigo-200 mt-0.5"><span class="text-emerald-400 font-semibold">+10 applies</span> completed today across platforms</p>
            </div>
            <div class="flex items-center space-x-3 text-xs">
              <span class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span> Direct Applies</span>
              <span class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-indigo-400"></span> PEC Outreach</span>
              <span class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-amber-400"></span> Recruiter Alerts</span>
            </div>
          </div>

          <!-- Stylized Bar Graph matching reference image -->
          <div class="h-44 w-full flex items-end justify-between px-4 pb-2 border-b border-indigo-900/60">
            <div class="flex flex-col items-center gap-2">
              <div class="w-2.5 bg-white rounded-full transition-all duration-500" style="height: 110px;"></div>
              <span class="text-[10px] text-indigo-300 font-medium">Mon</span>
            </div>
            <div class="flex flex-col items-center gap-2">
              <div class="w-2.5 bg-white rounded-full transition-all duration-500" style="height: 85px;"></div>
              <span class="text-[10px] text-indigo-300 font-medium">Tue</span>
            </div>
            <div class="flex flex-col items-center gap-2">
              <div class="w-2.5 bg-white rounded-full transition-all duration-500" style="height: 125px;"></div>
              <span class="text-[10px] text-indigo-300 font-medium">Wed</span>
            </div>
            <div class="flex flex-col items-center gap-2">
              <div class="w-2.5 bg-white rounded-full transition-all duration-500" style="height: 155px;"></div>
              <span class="text-[10px] text-indigo-300 font-medium">Thu</span>
            </div>
            <div class="flex flex-col items-center gap-2">
              <div class="w-2.5 bg-white rounded-full transition-all duration-500" style="height: 100px;"></div>
              <span class="text-[10px] text-indigo-300 font-medium">Fri</span>
            </div>
            <div class="flex flex-col items-center gap-2">
              <div class="w-2.5 bg-white rounded-full transition-all duration-500" style="height: 75px;"></div>
              <span class="text-[10px] text-indigo-300 font-medium">Sat</span>
            </div>
            <div class="flex flex-col items-center gap-2">
              <div class="w-2.5 bg-emerald-400 rounded-full transition-all duration-500 shadow-lg shadow-emerald-400/50" style="height: 140px;"></div>
              <span class="text-[10px] text-emerald-400 font-bold">Today</span>
            </div>
          </div>

          <!-- Bottom 4 Stats Bar from reference image -->
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4 pt-5 mt-2">
            <div>
              <div class="flex items-center space-x-2 text-indigo-200 text-xs">
                <i class="fa-solid fa-bolt text-amber-400"></i>
                <span>Naukri Applies</span>
              </div>
              <h4 class="text-xl font-bold mt-1" id="metricNaukri">10</h4>
              <div class="w-full bg-indigo-950 rounded-full h-1 mt-2">
                <div class="bg-amber-400 h-1 rounded-full" style="width: 100%"></div>
              </div>
            </div>

            <div>
              <div class="flex items-center space-x-2 text-indigo-200 text-xs">
                <i class="fa-solid fa-envelope text-purple-400"></i>
                <span>Gmail Intel</span>
              </div>
              <h4 class="text-xl font-bold mt-1" id="metricGmail">51</h4>
              <div class="w-full bg-indigo-950 rounded-full h-1 mt-2">
                <div class="bg-purple-400 h-1 rounded-full" style="width: 85%"></div>
              </div>
            </div>

            <div>
              <div class="flex items-center space-x-2 text-indigo-200 text-xs">
                <i class="fa-solid fa-graduation-cap text-sky-400"></i>
                <span>PEC Alumni Outreach</span>
              </div>
              <h4 class="text-xl font-bold mt-1">2 Sent</h4>
              <div class="w-full bg-indigo-950 rounded-full h-1 mt-2">
                <div class="bg-sky-400 h-1 rounded-full" style="width: 100%"></div>
              </div>
            </div>

            <div>
              <div class="flex items-center space-x-2 text-indigo-200 text-xs">
                <i class="fa-solid fa-shield-halved text-rose-400"></i>
                <span>Manual Desk</span>
              </div>
              <h4 class="text-xl font-bold mt-1" id="metricManual">12</h4>
              <div class="w-full bg-indigo-950 rounded-full h-1 mt-2">
                <div class="bg-rose-400 h-1 rounded-full" style="width: 45%"></div>
              </div>
            </div>
          </div>

        </div>

        <!-- Two Columns: Recent In-Progress Emails & Quick Manual Desk -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
          
          <!-- Screening Passed & Next Steps Pipeline (Left 7 Cols) -->
          <div class="lg:col-span-7 bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
            <div class="flex items-center justify-between">
              <div>
                <h3 class="font-bold text-slate-900 text-sm flex items-center gap-2">
                  <span class="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
                  <i class="fa-solid fa-trophy text-amber-500"></i>
                  <span>Screening Cleared & Next Steps Pipeline</span>
                </h3>
                <p class="text-xs text-slate-400">Opportunities in progress that passed screening, assessment, or have active exam intimations.</p>
              </div>
              <button onclick="switchTab('gmail')" class="text-xs text-indigo-600 font-semibold hover:underline">View All Inbox Updates</button>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-left text-xs">
                <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                  <tr>
                    <th class="p-2.5">Company / Agency</th>
                    <th class="p-2.5">Opportunity</th>
                    <th class="p-2.5">Stage Cleared</th>
                    <th class="p-2.5">Next Action</th>
                    <th class="p-2.5 text-right">Email</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100" id="mainScreeningPassedTable">
                  <tr><td colspan="5" class="p-4 text-center text-slate-400">Loading screening cleared opportunities...</td></tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Quick Manual Queue (Right 5 Cols) -->
          <div class="lg:col-span-5 bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
            <div class="flex items-center justify-between">
              <div>
                <h3 class="font-bold text-slate-900 text-sm">Manual Desk & Questionnaires</h3>
                <p class="text-xs text-slate-400">Requires manual submission</p>
              </div>
              <button onclick="switchTab('manual')" class="text-xs text-indigo-600 font-semibold hover:underline">View All</button>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-left text-xs">
                <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                  <tr>
                    <th class="p-2.5">Company</th>
                    <th class="p-2.5">Role</th>
                    <th class="p-2.5 text-right">Link</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100" id="quickManualTable">
                  <tr><td colspan="3" class="p-4 text-center text-slate-400">Loading openings...</td></tr>
                </tbody>
              </table>
            </div>
          </div>

        </div>

      </div>

      <!-- ========================================== -->
      <!-- TAB 2: GMAIL INBOX INTELLIGENCE            -->
      <!-- ========================================== -->
      <div id="view-gmail" class="hidden space-y-6">
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h3 class="font-bold text-slate-900 text-base flex items-center gap-2">
                <i class="fa-solid fa-envelope-circle-check text-purple-600"></i>
                <span>Gmail Inbox Application Intelligence</span>
              </h3>
              <p class="text-xs text-slate-400">Scanned directly from primary inbox subject lines: screening updates, exam intimations, and recruiter invites.</p>
            </div>
            <div class="flex items-center gap-2">
              <button onclick="triggerAction('scan_gmail')" class="px-3.5 py-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow-sm shadow-purple-600/30">
                <i class="fa-solid fa-arrows-rotate"></i>
                <span>Scan Full Inbox Now</span>
              </button>
              <a href="https://mail.google.com/mail/u/0/#inbox" target="_blank" class="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-semibold flex items-center gap-1.5">
                <i class="fa-solid fa-arrow-up-right-from-square"></i>
                <span>Open Gmail</span>
              </a>
            </div>
          </div>

          <!-- Category Filter Pills -->
          <div class="flex items-center gap-2 flex-wrap pt-2">
            <button onclick="filterGmailIntel('all')" id="btnGFilterAll" class="px-3 py-1 rounded-lg text-xs font-semibold bg-purple-600 text-white transition">All Updates</button>
            <button onclick="filterGmailIntel('exam')" id="btnGFilterExam" class="px-3 py-1 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition">Exams & Assessments</button>
            <button onclick="filterGmailIntel('applied')" id="btnGFilterApplied" class="px-3 py-1 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition">Active Applications</button>
            <button onclick="filterGmailIntel('invites')" id="btnGFilterInvites" class="px-3 py-1 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition">Recruiter Invites</button>
            <button onclick="filterGmailIntel('outbound')" id="btnGFilterOutbound" class="px-3 py-1 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition">Outbound Sent</button>
          </div>

          <!-- Table -->
          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="p-3">Company / Sender</th>
                  <th class="p-3">Subject Line</th>
                  <th class="p-3">Category</th>
                  <th class="p-3">Action / Next Step</th>
                  <th class="p-3 text-right">View</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100" id="fullGmailTableBody">
                <tr><td colspan="5" class="p-6 text-center text-slate-400">Loading inbox updates...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ========================================== -->
      <!-- TAB 3A: LINKEDIN FEED POSTS & FORMS DESK   -->
      <!-- ========================================== -->
      <div id="view-feed" class="hidden space-y-6">
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h3 class="font-bold text-slate-900 text-base flex items-center gap-2">
                <i class="fa-solid fa-rss text-teal-600"></i>
                <span>LinkedIn Feed Posts &amp; Hiring Forms</span>
              </h3>
              <p class="text-xs text-slate-400">Posts discovered exclusively from scrolling your LinkedIn feed (founders, PMs, and recruiters sharing Google Forms, Typeforms, or hiring calls).</p>
            </div>
            <div class="flex items-center gap-2">
              <button id="btnDeleteSelectedFeed" onclick="deleteSelectedFeedPosts()" class="hidden px-3.5 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow-sm shadow-rose-600/30 transition cursor-pointer">
                <i class="fa-solid fa-trash-can text-xs"></i>
                <span>Delete Selected (<span id="selectedFeedCount">0</span>)</span>
              </button>
              <button onclick="clearAllFeedPosts()" title="Clear all feed posts from desk" class="px-3 py-1.5 bg-slate-100 hover:bg-rose-50 hover:text-rose-600 text-slate-600 rounded-xl text-xs font-semibold flex items-center gap-1.5 border border-slate-200 transition cursor-pointer">
                <i class="fa-solid fa-trash-can text-xs"></i>
                <span>Clear All</span>
              </button>
              <button onclick="triggerAction('linkedin_feed')" class="px-3.5 py-1.5 bg-teal-600 hover:bg-teal-500 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow-sm shadow-teal-600/30 cursor-pointer">
                <i class="fa-solid fa-rss"></i>
                <span>Harvest Fresh Feed Posts</span>
              </button>
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="p-3 w-8"><input type="checkbox" id="selectAllFeed" onchange="toggleSelectAllFeed(this)" class="rounded text-teal-600 cursor-pointer"></th>
                  <th class="p-3">Detected</th>
                  <th class="p-3">Name &amp; Profile</th>
                  <th class="p-3">Job Role, Full JD &amp; Email</th>
                  <th class="p-3">Status</th>
                  <th class="p-3 text-right">Post &amp; Form Links</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100" id="feedPostsTableBody">
                <tr><td colspan="6" class="p-6 text-center text-slate-400">Loading feed hiring posts...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ========================================== -->
      <!-- TAB 3B: EASY APPLY & TARGET JOB LISTINGS   -->
      <!-- ========================================== -->
      <div id="view-easy-apply" class="hidden space-y-6">
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h3 class="font-bold text-slate-900 text-base flex items-center gap-2">
                <i class="fa-solid fa-bolt-lightning text-blue-600"></i>
                <span>Easy Apply &amp; Target Job Board Desk</span>
              </h3>
              <p class="text-xs text-slate-400">Curated 0-2 yrs entry-level Analyst &amp; APM roles from LinkedIn Jobs &amp; verified openings ready for direct or Easy Apply.</p>
            </div>
            <div class="flex items-center gap-2">
              <button id="btnDeleteSelectedJobs" onclick="deleteSelectedEasyApplyJobs()" class="hidden px-3.5 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow-sm shadow-rose-600/30 transition cursor-pointer">
                <i class="fa-solid fa-trash-can text-xs"></i>
                <span>Delete Selected (<span id="selectedJobsCount">0</span>)</span>
              </button>
              <button onclick="clearAllEasyApplyJobs()" title="Clear all easy apply jobs from desk" class="px-3 py-1.5 bg-slate-100 hover:bg-rose-50 hover:text-rose-600 text-slate-600 rounded-xl text-xs font-semibold flex items-center gap-1.5 border border-slate-200 transition cursor-pointer">
                <i class="fa-solid fa-trash-can text-xs"></i>
                <span>Clear All</span>
              </button>
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="p-3 w-8"><input type="checkbox" id="selectAllEasyApply" onchange="toggleSelectAllEasyApply(this)" class="rounded text-blue-600 cursor-pointer"></th>
                  <th class="p-3">Detected</th>
                  <th class="p-3">Target Company</th>
                  <th class="p-3">Role Title</th>
                  <th class="p-3">Location &amp; Exp</th>
                  <th class="p-3">Status</th>
                  <th class="p-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100" id="easyApplyTableBody">
                <tr><td colspan="7" class="p-6 text-center text-slate-400">Loading Easy Apply openings...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Legacy alias view-forms for compatibility -->
      <div id="view-forms" class="hidden"></div>

      <!-- ========================================== -->
      <!-- TAB 4: RECRUITER EMAIL LEADS               -->
      <!-- ========================================== -->
      <div id="view-recruiters" class="hidden space-y-6">
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h3 class="font-bold text-slate-900 text-base flex items-center gap-2">
                <i class="fa-solid fa-paper-plane text-sky-600"></i>
                <span>Harvested Recruiter Emails & Referral Drafts</span>
              </h3>
              <p class="text-xs text-slate-400">Direct recruiter emails extracted from vacancy posts with pre-crafted referral applications ready to send.</p>
            </div>
            <div class="flex items-center gap-2">
              <button id="btnDeleteSelectedRecruiters" onclick="deleteSelectedRecruiters()" class="hidden px-3.5 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow-sm shadow-rose-600/30 transition cursor-pointer">
                <i class="fa-solid fa-trash-can text-xs"></i>
                <span>Delete Selected (<span id="selectedRecruitersCount">0</span>)</span>
              </button>
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="p-3 w-8"><input type="checkbox" id="selectAllRecruiters" onchange="toggleSelectAllRecruiters(this)" class="rounded text-indigo-600 cursor-pointer"></th>
                  <th class="p-3">Detected</th>
                  <th class="p-3">Recruiter / Author</th>
                  <th class="p-3">Recruiter Email</th>
                  <th class="p-3">Draft Application &amp; Tags</th>
                  <th class="p-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100" id="recruiterLeadsTableBody">
                <tr><td colspan="6" class="p-6 text-center text-slate-400">Loading recruiter leads...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ========================================== -->
      <!-- TAB 5: ALUMNI & REFERRALS                  -->
      <!-- ========================================== -->
      <div id="view-alumni" class="hidden space-y-6">
        <!-- Search Controls Card -->
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="font-bold text-slate-900 text-base">Company People Crawler & Alumni Priority</h3>
              <p class="text-xs text-slate-400">Navigates to company's LinkedIn people page, prioritizing <strong>Punjab Engineering College (PEC)</strong> alumni & India tech recruiters.</p>
            </div>
            <span class="px-3 py-1 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-600 border border-indigo-100">
              <i class="fa-solid fa-graduation-cap mr-1"></i> PEC Alumni Priority
            </span>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
            <div class="md:col-span-4">
              <label class="block text-xs font-semibold text-slate-600 mb-1">Target Company</label>
              <input type="text" id="targetCompanyInput" value="Swiggy" placeholder="e.g. Swiggy, Google, Zomato, Deloitte, EY"
                     class="w-full bg-slate-50 border border-slate-200 rounded-xl px-3.5 py-2 text-sm text-slate-800 focus:outline-none focus:border-indigo-500 transition">
            </div>
            <div class="md:col-span-3">
              <label class="block text-xs font-semibold text-slate-600 mb-1">Target Role Keyword</label>
              <input type="text" id="targetRoleInput" value="Product Manager" placeholder="e.g. Product Manager, Analyst, Recruiter"
                     class="w-full bg-slate-50 border border-slate-200 rounded-xl px-3.5 py-2 text-sm text-slate-800 focus:outline-none focus:border-indigo-500 transition">
            </div>
            <div class="md:col-span-3 flex items-center space-x-2 pb-2">
              <input type="checkbox" id="checkPecPriority" checked class="w-4 h-4 text-indigo-600 rounded border-slate-300">
              <label for="checkPecPriority" class="text-xs font-medium text-slate-700">Prioritize PEC Alumni</label>
            </div>
            <div class="md:col-span-2">
              <button onclick="crawlCompanyPeople()" id="btnCrawlPeople"
                      class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs py-2.5 px-4 rounded-xl transition flex items-center justify-center space-x-2 shadow-md shadow-indigo-600/30">
                <i class="fa-solid fa-users-viewfinder"></i>
                <span>Crawl People</span>
              </button>
            </div>
          </div>
        </div>

        <!-- People Candidates Approval Desk -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div class="lg:col-span-7 bg-white p-6 rounded-2xl border border-slate-100 shadow-sm flex flex-col justify-between">
            <div>
              <div class="flex items-center justify-between pb-3 border-b border-slate-100">
                <div>
                  <h4 class="font-bold text-slate-900 text-sm">Discovered Candidates</h4>
                  <p class="text-xs text-slate-400" id="alumniStatsLabel">Select candidates to approve</p>
                </div>
                <div class="flex items-center space-x-2 text-xs">
                  <button onclick="selectAllCandidates(true)" class="text-indigo-600 font-semibold hover:underline">Select All</button>
                  <span class="text-slate-300">•</span>
                  <button onclick="selectAllCandidates(false)" class="text-slate-500 font-medium hover:underline">Deselect All</button>
                </div>
              </div>

              <div class="overflow-y-auto max-h-[380px] divide-y divide-slate-100 my-2 custom-scroll" id="alumniCandidatesContainer">
                <div class="p-8 text-center text-slate-400 text-xs">
                  <i class="fa-solid fa-user-group text-3xl mb-2 text-slate-300"></i>
                  <p>No candidates loaded yet.</p>
                  <p class="text-[11px] text-slate-400 mt-1">Search for a company above to crawl its people page.</p>
                </div>
              </div>
            </div>

            <div class="pt-4 border-t border-slate-100 flex items-center justify-between">
              <span class="text-xs text-slate-500">Selected: <strong class="text-indigo-600" id="alumniSelectedCount">0</strong></span>
              <button onclick="sendApprovedAlumniOutreach()" id="btnSendApprovedAlumni" disabled
                      class="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold py-2 px-5 rounded-xl transition flex items-center space-x-1.5 shadow-md shadow-emerald-600/20">
                <i class="fa-solid fa-paper-plane"></i>
                <span>Send Approved Outreach</span>
              </button>
            </div>
          </div>

          <div class="lg:col-span-5 bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
            <div class="flex items-center justify-between">
              <h4 class="font-bold text-slate-900 text-sm flex items-center gap-2">
                <i class="fa-solid fa-pen-nib text-indigo-600"></i> Fixed Referral & Message Templates
              </h4>
              <span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200" id="templateSavedBadge">
                <i class="fa-solid fa-check"></i> Active & Synced
              </span>
            </div>
            <p class="text-xs text-slate-400">Edit or paste your exact referral template with variables. Click "Save & Update Template" to lock it in for all future runs.</p>

            <!-- Clickable Variable Tags -->
            <div class="space-y-1">
              <span class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Clickable Variables (Inserts at cursor):</span>
              <div class="flex flex-wrap gap-1.5 pt-1">
                <button type="button" onclick="insertVariable('tmplReferral', '{first_name}')" class="px-2 py-0.5 rounded-md bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-[11px] font-mono font-medium transition cursor-pointer">{first_name}</button>
                <button type="button" onclick="insertVariable('tmplReferral', '{company}')" class="px-2 py-0.5 rounded-md bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-[11px] font-mono font-medium transition cursor-pointer">{company}</button>
                <button type="button" onclick="insertVariable('tmplReferral', '{target_role}')" class="px-2 py-0.5 rounded-md bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-[11px] font-mono font-medium transition cursor-pointer">{target_role}</button>
                <button type="button" onclick="insertVariable('tmplReferral', '{college}')" class="px-2 py-0.5 rounded-md bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-[11px] font-mono font-medium transition cursor-pointer">{college}</button>
                <button type="button" onclick="insertVariable('tmplReferral', '{my_name}')" class="px-2 py-0.5 rounded-md bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-[11px] font-mono font-medium transition cursor-pointer">{my_name}</button>
              </div>
            </div>

            <!-- Template 1: Fixed Referral / 1st-Degree Message -->
            <div>
              <div class="flex items-center justify-between mb-1">
                <label class="block text-xs font-semibold text-slate-700">1. Fixed Referral Message (1st-Degree / Warm Leads)</label>
                <span class="text-[10px] text-slate-400">Fixed Template Format</span>
              </div>
              <textarea id="tmplReferral" rows="3" oninput="updateAlumniPreview()"
                        class="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 focus:outline-none focus:border-indigo-500 transition font-sans"></textarea>
            </div>

            <!-- Template 2: Alumni Connection Note -->
            <div>
              <div class="flex items-center justify-between mb-1">
                <label class="block text-xs font-semibold text-slate-700">2. PEC Alumni Connection Note (<= 300 chars)</label>
                <span class="text-[10px] text-slate-400">Cold Connection</span>
              </div>
              <textarea id="tmplAlumni" rows="2" oninput="updateAlumniPreview()"
                        class="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 focus:outline-none focus:border-indigo-500 transition font-sans"></textarea>
            </div>

            <!-- Template 3: Phase 2 Resume Delivery Reply -->
            <div>
              <div class="flex items-center justify-between mb-1">
                <label class="block text-xs font-semibold text-slate-700">3. Two-Phase Resume Reply (Sent when connection asks for CV)</label>
                <span class="text-[10px] text-emerald-600 font-semibold">Attaches Master PDF</span>
              </div>
              <textarea id="tmplResumeReply" rows="2"
                        class="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 focus:outline-none focus:border-indigo-500 transition font-sans"></textarea>
            </div>

            <!-- Update Templates Button -->
            <div class="pt-1">
              <button type="button" onclick="saveTemplates()" id="btnSaveTemplates"
                      class="w-full py-2.5 px-4 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white shadow-md shadow-indigo-200 transition flex items-center justify-center space-x-2">
                <i class="fa-solid fa-floppy-disk"></i>
                <span>Save & Update Templates For Future Outreach</span>
              </button>
            </div>

            <div class="bg-slate-50 rounded-xl p-3.5 border border-slate-200/80">
              <span class="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">Live Personalized Preview</span>
              <p class="text-xs text-slate-700 italic leading-relaxed" id="alumniPreviewBox">Select a candidate on the left to see their personalized message.</p>
            </div>
          </div>
        </div>

        <!-- Sent Outreach History Table -->
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h4 class="font-bold text-slate-900 text-sm flex items-center gap-2">
                <i class="fa-solid fa-clock-rotate-left text-emerald-600"></i> Sent Outreach History & Tracker
              </h4>
              <p class="text-xs text-slate-400">Direct messages and connection invitations delivered with audit timestamps.</p>
            </div>
            <button onclick="loadOutreachHistory()" class="text-xs text-indigo-600 font-semibold hover:underline flex items-center gap-1">
              <i class="fa-solid fa-arrows-rotate"></i> Refresh
            </button>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="p-2.5">Time</th>
                  <th class="p-2.5">Candidate</th>
                  <th class="p-2.5">Category</th>
                  <th class="p-2.5">Action</th>
                  <th class="p-2.5">Status</th>
                  <th class="p-2.5">Delivered Message</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100" id="outreachHistoryTableBody">
                <tr><td colspan="6" class="p-4 text-center text-slate-400">Loading outreach history...</td></tr>
              </tbody>
            </table>
          </div>
        </div>

      </div>

      <!-- ========================================== -->
      <!-- TAB 6: NAUKRI RECENCY BOOSTER               -->
      <!-- ========================================== -->
      <div id="view-naukri" class="hidden space-y-6">
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="font-bold text-slate-900 text-base">Naukri Profile Recency Algorithm Booster</h3>
              <p class="text-xs text-slate-400">Recruiter searches on Naukri prioritize profiles with "Updated: Today".</p>
            </div>
            <button onclick="triggerAction('naukri_boost')"
                    class="bg-amber-500 hover:bg-amber-400 text-white font-semibold text-xs py-2.5 px-5 rounded-xl transition shadow-md shadow-amber-500/20 flex items-center space-x-1.5">
              <i class="fa-solid fa-bolt"></i>
              <span>Boost Recency Now</span>
            </button>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
            <div class="p-4 bg-slate-50 rounded-xl border border-slate-200/60">
              <span class="text-xs text-slate-400 font-semibold uppercase">Current Status</span>
              <h4 class="text-lg font-bold text-slate-900 mt-1" id="naukriTabStatus">Updated: Today</h4>
            </div>
            <div class="p-4 bg-slate-50 rounded-xl border border-slate-200/60">
              <span class="text-xs text-slate-400 font-semibold uppercase">Last Boost Executed</span>
              <h4 class="text-sm font-bold text-slate-700 mt-1" id="naukriLastBoostDate">Today</h4>
            </div>
            <div class="p-4 bg-slate-50 rounded-xl border border-slate-200/60">
              <span class="text-xs text-slate-400 font-semibold uppercase">Recruiter Discoverability</span>
              <h4 class="text-lg font-bold text-emerald-600 mt-1">Top 5% Recency</h4>
            </div>
          </div>
        </div>

        <!-- Naukri Auto-Applied Opportunities Table -->
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h3 class="font-bold text-slate-900 text-base flex items-center gap-2">
                <i class="fa-solid fa-circle-check text-emerald-500"></i>
                <span>Naukri Auto-Applied Roles (0-2 Yrs Experience Target)</span>
              </h3>
              <p class="text-xs text-slate-400">Applications submitted autonomously directly through Naukri's application engine.</p>
            </div>
            <div class="flex items-center gap-2">
              <button onclick="triggerAction('naukri_apply')"
                      class="bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs py-2 px-4 rounded-xl transition shadow-sm flex items-center space-x-1.5 cursor-pointer">
                <i class="fa-solid fa-paper-plane"></i>
                <span>Run Mass Apply (0-2 Yrs)</span>
              </button>
              <span class="text-xs font-bold text-emerald-700 bg-emerald-50 px-3 py-1 rounded-full border border-emerald-200" id="naukriAppliedCountBadge">0 Applied</span>
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="p-3">Applied At</th>
                  <th class="p-3">Company</th>
                  <th class="p-3">Role Title</th>
                  <th class="p-3">Experience</th>
                  <th class="p-3">Location</th>
                  <th class="p-3 text-right">Job Posting</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100" id="naukriAppliedTableBody">
                <tr><td colspan="6" class="p-6 text-center text-slate-400">Loading applied jobs...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ========================================== -->
      <!-- TAB 7: MANUAL INTERVENTION DESK            -->
      <!-- ========================================== -->
      <div id="view-manual" class="hidden space-y-6">
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h3 class="font-bold text-slate-900 text-base">Manual Intervention & Questionnaire Review Desk</h3>
              <p class="text-xs text-slate-400">Openings with complex custom questionnaires or external enterprise portals (Workday, Oracle, Taleo) requiring manual input.</p>
            </div>
            <div class="flex items-center gap-2">
              <button onclick="filterManualQueue('all')" id="btnFilterAll" class="px-3 py-1 rounded-lg text-xs font-semibold bg-indigo-600 text-white transition">All Openings</button>
              <button onclick="filterManualQueue('questionnaire')" id="btnFilterQuestionnaire" class="px-3 py-1 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition">Questionnaires</button>
              <button onclick="filterManualQueue('ats')" id="btnFilterAts" class="px-3 py-1 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition">Enterprise ATS</button>
              <span class="text-xs font-bold text-indigo-600 bg-indigo-50 px-3 py-1 rounded-full border border-indigo-100 ml-2" id="manualTableCount">0 Total</span>
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="p-3">Detected</th>
                  <th class="p-3">Company</th>
                  <th class="p-3">Role Title</th>
                  <th class="p-3">Location</th>
                  <th class="p-3">Category & Reason</th>
                  <th class="p-3 text-right">Direct Job Link</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100" id="fullManualTableBody">
                <tr><td colspan="6" class="p-6 text-center text-slate-400">Loading manual queue...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ========================================== -->
      <!-- TAB 8: ACTIVE MASTER RESUME & UPLOAD DESK  -->
      <!-- ========================================== -->
      <div id="view-resume" class="hidden space-y-6">
        <!-- Resume Status & Metadata -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm md:col-span-2 space-y-4">
            <div class="flex items-center justify-between">
              <div class="flex items-center space-x-3">
                <div class="w-12 h-12 rounded-xl bg-rose-50 flex items-center justify-center text-rose-600 text-xl font-bold">
                  <i class="fa-solid fa-file-pdf"></i>
                </div>
                <div>
                  <h3 class="font-bold text-slate-900 text-base" id="activeResumeName">Loading active resume...</h3>
                  <p class="text-xs text-slate-400" id="activeResumePath">Path: ...</p>
                </div>
              </div>
              <span class="px-3 py-1 rounded-full text-xs font-bold bg-emerald-100 text-emerald-700" id="resumeBadge">Active Master</span>
            </div>

            <div class="grid grid-cols-3 gap-4 pt-4 border-t border-slate-100 text-xs">
              <div>
                <p class="text-slate-400">File Size</p>
                <p class="font-bold text-slate-800 text-sm mt-0.5" id="activeResumeSize">-- KB</p>
              </div>
              <div>
                <p class="text-slate-400">Last Updated</p>
                <p class="font-bold text-slate-800 text-sm mt-0.5" id="activeResumeDate">--</p>
              </div>
              <div>
                <p class="text-slate-400">Naukri Synced</p>
                <p class="font-bold text-emerald-600 text-sm mt-0.5" id="activeResumeNaukriStatus"><i class="fa-solid fa-circle-check"></i> Live Profile</p>
              </div>
            </div>
          </div>

          <div class="bg-gradient-to-br from-indigo-50 to-purple-50 p-6 rounded-2xl border border-indigo-100 space-y-3">
            <h4 class="font-bold text-indigo-950 text-sm flex items-center gap-2">
              <i class="fa-solid fa-shield-halved text-indigo-600"></i> Two-Phase Referral Policy
            </h4>
            <p class="text-xs text-indigo-800/80 leading-relaxed">
              Resumes are <strong>never attached upfront</strong> during cold networking. The engine strictly follows your instructions: it only auto-dispatches your updated resume when a connection replies asking for it (e.g. <em>"share your resume"</em>, <em>"send CV"</em>).
            </p>
            <div class="pt-2">
              <button onclick="triggerResumeScan()" id="btnScanResumeReplies" class="w-full py-2.5 px-4 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-700 text-white shadow-md shadow-indigo-200 transition flex items-center justify-center gap-2">
                <i class="fa-solid fa-arrows-rotate"></i> Scan LinkedIn Replies & Dispatch
              </button>
            </div>
          </div>
        </div>

        <!-- Upload New Resume Form -->
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div>
            <h3 class="font-bold text-slate-900 text-base">Upload & Update Master Resume</h3>
            <p class="text-xs text-slate-400">Upload an updated PDF or DOCX resume. Future applications on LinkedIn, Naukri, and referral replies will immediately utilize this version.</p>
          </div>

          <form id="resumeUploadForm" onsubmit="handleResumeUpload(event)" class="space-y-4">
            <div class="border-2 border-dashed border-slate-200 rounded-2xl p-8 text-center hover:border-indigo-400 transition cursor-pointer bg-slate-50/50" onclick="document.getElementById('resumeFileInput').click()">
              <input type="file" id="resumeFileInput" name="resume" accept=".pdf,.docx" class="hidden" onchange="displaySelectedFile(this)">
              <div class="w-12 h-12 mx-auto rounded-full bg-indigo-50 text-indigo-600 flex items-center justify-center text-xl mb-3">
                <i class="fa-solid fa-cloud-arrow-up"></i>
              </div>
              <p class="text-sm font-semibold text-slate-700" id="uploadFilePrompt">Click or drag & drop to choose new resume (PDF or DOCX)</p>
              <p class="text-xs text-slate-400 mt-1" id="uploadFileDetails">Max file size: 5MB</p>
            </div>

            <div class="flex items-center justify-between flex-wrap gap-4 pt-2">
              <label class="flex items-center space-x-2 text-xs font-medium text-slate-700 cursor-pointer">
                <input type="checkbox" id="syncNaukriCheckbox" checked class="w-4 h-4 rounded text-indigo-600 border-slate-300 focus:ring-indigo-500">
                <span>Automatically sync & push this resume directly to my Naukri.com profile</span>
              </label>

              <button type="submit" id="btnUploadResume" class="px-5 py-2.5 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white shadow-md shadow-indigo-200 transition flex items-center gap-2">
                <i class="fa-solid fa-upload"></i> Upload & Set Active Resume
              </button>
            </div>
            <div id="uploadFeedback" class="hidden p-3 rounded-xl text-xs font-medium"></div>
          </form>
        </div>

        <!-- Dispatched Resumes History -->
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="font-bold text-slate-900 text-base">Two-Phase Resume Dispatches</h3>
              <p class="text-xs text-slate-400">Connections who requested your resume and received the updated master copy.</p>
            </div>
            <span class="text-xs font-bold text-indigo-600 bg-indigo-50 px-3 py-1 rounded-full border border-indigo-100" id="dispatchTableCount">0 Dispatched</span>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="p-3">Dispatched At</th>
                  <th class="p-3">Connection Name</th>
                  <th class="p-3">Matched Request Trigger</th>
                  <th class="p-3">Resume Version Sent</th>
                  <th class="p-3">Status</th>
                  <th class="p-3">Message Dispatched</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100" id="dispatchesTableBody">
                <tr><td colspan="6" class="p-6 text-center text-slate-400">No resumes auto-dispatched yet. They will appear here when connections ask for your CV.</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ========================================== -->
      <!-- TAB 8B: MUMBAI NETWORK & 2-DAY FOLLOW-UP   -->
      <!-- ========================================== -->
      <div id="view-mumbai" class="hidden space-y-6">
        
        <!-- Daily Lifecycle Metrics Row -->
        <div class="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div class="bg-white p-4 rounded-2xl border border-slate-100 shadow-sm">
            <p class="text-[11px] font-semibold text-slate-400 uppercase">Today Connects Sent</p>
            <h3 class="text-2xl font-bold text-indigo-600 mt-1" id="mumbaiTodayConnects">0</h3>
          </div>
          <div class="bg-white p-4 rounded-2xl border border-slate-100 shadow-sm">
            <p class="text-[11px] font-semibold text-slate-400 uppercase">Today Messages Sent</p>
            <h3 class="text-2xl font-bold text-emerald-600 mt-1" id="mumbaiTodayMessages">0</h3>
          </div>
          <div class="bg-white p-4 rounded-2xl border border-slate-100 shadow-sm">
            <p class="text-[11px] font-semibold text-slate-400 uppercase">PEC Alumni Found</p>
            <h3 class="text-2xl font-bold text-amber-600 mt-1" id="mumbaiPecCount">0</h3>
          </div>
          <div class="bg-white p-4 rounded-2xl border border-slate-100 shadow-sm">
            <p class="text-[11px] font-semibold text-slate-400 uppercase">Incomplete / Sending List</p>
            <div class="flex items-baseline gap-2 mt-1">
              <h3 class="text-2xl font-bold text-rose-600" id="mumbaiIncompleteCount">0</h3>
              <span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700"><span id="mumbaiSendingListCount">0</span> ready to send</span>
            </div>
          </div>
          <div class="bg-white p-4 rounded-2xl border border-slate-100 shadow-sm">
            <p class="text-[11px] font-semibold text-slate-400 uppercase">Completed Outreach</p>
            <h3 class="text-2xl font-bold text-teal-600 mt-1" id="mumbaiCompletedCount">0</h3>
          </div>
        </div>

        <!-- Step 1: Mumbai Companies Discovery & Per-Company Template Manager -->
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center justify-between flex-wrap gap-3">
            <div>
              <h3 class="font-bold text-slate-900 text-base flex items-center gap-2">
                <i class="fa-solid fa-city text-indigo-600"></i>
                <span>Step 1: Mumbai Companies Directory (Ordered: 250-500 → 500-1000 → 1000+)</span>
              </h3>
              <p class="text-xs text-slate-400">Click any <strong>Company Name</strong> (e.g. JPMorgan, Zepto, GrayQuest) to edit its custom <strong>PEC Chandigarh Template</strong> &amp; <strong>Other Template</strong>.</p>
            </div>
            <div class="flex items-center gap-2 flex-wrap">
              <button onclick="generateMumbaiCompanies()" id="btnGenMumbaiCompanies"
                      class="px-3.5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-bold flex items-center gap-1.5 shadow-sm shadow-indigo-600/20 cursor-pointer transition">
                <i class="fa-solid fa-wand-magic-sparkles"></i>
                <span>Generate Mumbai Companies (By Size)</span>
              </button>
            </div>
          </div>

          <!-- Prominent Full-Width Search Among Companies Bar -->
          <div class="relative">
            <i class="fa-solid fa-magnifying-glass text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 text-xs"></i>
            <input type="text" id="mumbaiCompanySearch" oninput="renderMumbaiCompanies()"
                   placeholder="Search among all Mumbai companies by name, industry, or LinkedIn slug (e.g. GrayQuest, JPMorgan, FinTech)..."
                   class="w-full bg-slate-50 border border-slate-200 rounded-xl pl-9 pr-24 py-2.5 text-xs text-slate-800 focus:outline-none focus:border-indigo-500 focus:bg-white transition">
            <button onclick="document.getElementById('mumbaiCompanySearch').value=''; renderMumbaiCompanies();" type="button"
                    class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] font-semibold text-slate-400 hover:text-slate-700 px-2 py-0.5 rounded bg-slate-100 cursor-pointer">
              Clear
            </button>
          </div>

          <!-- Quick Add Custom Company + Size Filter Bar -->
          <div class="flex flex-wrap items-center justify-between gap-3 pt-1 pb-2 border-b border-slate-100">
            <div class="flex items-center gap-1.5 flex-wrap">
              <button onclick="filterMumbaiSize('all')" id="btnMSizeAll" class="px-3 py-1 rounded-lg text-xs font-semibold bg-indigo-600 text-white">All Sizes (<span id="mCntAll">0</span>)</button>
              <button onclick="filterMumbaiSize('250-500')" id="btnMSize250" class="px-3 py-1 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200">250-500 (<span id="mCnt250">0</span>)</button>
              <button onclick="filterMumbaiSize('500-1000')" id="btnMSize500" class="px-3 py-1 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200">500-1000 (<span id="mCnt500">0</span>)</button>
              <button onclick="filterMumbaiSize('1000+')" id="btnMSize1000" class="px-3 py-1 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200">1000+ (<span id="mCnt1000">0</span>)</button>
            </div>
            <div class="flex items-center gap-2">
              <input type="text" id="customMumbaiCompanyName" placeholder="Add company (e.g. JP Morgan)" class="bg-slate-50 border border-slate-200 rounded-xl px-3 py-1.5 text-xs text-slate-800 focus:outline-none focus:border-indigo-500">
              <select id="customMumbaiCompanySize" class="bg-slate-50 border border-slate-200 rounded-xl px-2.5 py-1.5 text-xs text-slate-700">
                <option value="250-500">250-500</option>
                <option value="500-1000">500-1000</option>
                <option value="1000+" selected>1000+</option>
              </select>
              <button onclick="addCustomMumbaiCompany()" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-white rounded-xl text-xs font-semibold cursor-pointer">
                + Add Company
              </button>
            </div>
          </div>

          <!-- Companies Table -->
          <div class="overflow-x-auto max-h-72 overflow-y-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider sticky top-0">
                <tr>
                  <th class="p-2.5 w-8"><input type="checkbox" id="selectAllMumbaiCompanies" onchange="toggleAllMumbaiCompanies(this)" class="rounded text-indigo-600 cursor-pointer"></th>
                  <th class="p-2.5">Company Name (Click for Templates)</th>
                  <th class="p-2.5">Headcount Tier</th>
                  <th class="p-2.5">Industry</th>
                  <th class="p-2.5">PEC / Other Contacts</th>
                  <th class="p-2.5">Incomplete / Done</th>
                  <th class="p-2.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100" id="mumbaiCompaniesTableBody">
                <tr><td colspan="7" class="p-4 text-center text-slate-400">Loading Mumbai companies...</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Per-Company Dual Template Editor Panel (Shown when a Company Name is clicked) -->
        <div id="mumbaiTemplateEditorCard" class="hidden bg-indigo-50/60 p-6 rounded-2xl border border-indigo-200 shadow-sm space-y-4">
          <div class="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h3 class="font-bold text-slate-900 text-sm flex items-center gap-2">
                <i class="fa-solid fa-pen-to-square text-indigo-600"></i>
                <span>Custom Message Templates for: <span id="tmplEditorCompanyName" class="text-indigo-700 underline">Company</span></span>
              </h3>
              <p class="text-[11px] text-slate-500">Available placeholders: <code>{first_name}</code>, <code>{name}</code>, <code>{company}</code>, <code>{keyword}</code></p>
            </div>
            <button onclick="closeMumbaiTemplateEditor()" class="text-xs text-slate-500 hover:text-slate-800 px-2.5 py-1 rounded-lg bg-white border border-slate-200 cursor-pointer">
              Close Editor ✕
            </button>
          </div>
          <input type="hidden" id="tmplEditorCompanyId">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="bg-white p-4 rounded-xl border border-amber-200 space-y-2">
              <label class="block text-xs font-bold text-amber-700 flex items-center gap-1.5">
                <i class="fa-solid fa-graduation-cap"></i>
                <span>1. PEC Chandigarh Alumni Template</span>
              </label>
              <textarea id="tmplEditorPec" rows="4" class="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 focus:outline-none focus:border-amber-500"></textarea>
            </div>
            <div class="bg-white p-4 rounded-xl border border-sky-200 space-y-2">
              <label class="block text-xs font-bold text-sky-700 flex items-center gap-1.5">
                <i class="fa-solid fa-user-tie"></i>
                <span>2. Other Contacts Template (HR, Founder's Office, Product, Analyst)</span>
              </label>
              <textarea id="tmplEditorOther" rows="4" class="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 focus:outline-none focus:border-sky-500"></textarea>
            </div>
          </div>
          <div class="flex justify-end gap-2">
            <button onclick="saveMumbaiCompanyTemplates()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-bold shadow-sm cursor-pointer">
              <i class="fa-solid fa-floppy-disk mr-1"></i> Save Company Templates
            </button>
          </div>
        </div>

        <!-- Step 2: Workflow Controls (Extract 30+ Contacts -> Maximize Connects Only -> Daily Check -> Send Messages) -->
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center justify-between flex-wrap gap-3">
            <div>
              <h3 class="font-bold text-slate-900 text-base flex items-center gap-2">
                <i class="fa-solid fa-gears text-teal-600"></i>
                <span>Step 2: Find 30+ Contacts/Company, Maximize Connection Requests &amp; Separate Messaging</span>
              </h3>
              <p class="text-xs text-slate-400">Extracts <strong>30+ contacts minimum</strong> per company, segregates <strong>PEC Chandigarh</strong> vs <strong>Other</strong>, maximizes <strong>Connection Requests Only (No Messages)</strong>, and holds accepted contacts in <strong>Sending List</strong> until you fix templates and click <strong>Send Messages</strong>.</p>
            </div>
          </div>

          <div class="grid grid-cols-1 lg:grid-cols-12 gap-3 items-end">
            <div class="lg:col-span-4">
              <label class="block text-xs font-semibold text-slate-600 mb-1">Target Role / Department Keywords (comma-separated)</label>
              <input type="text" id="mumbaiKeywordsInput" value="Founder's Office, HR, Talent, Product, Analyst"
                     class="w-full bg-slate-50 border border-slate-200 rounded-xl px-3.5 py-2 text-xs text-slate-800 focus:outline-none focus:border-indigo-500">
            </div>
            <div class="lg:col-span-8 flex flex-wrap items-center gap-2">
              <button onclick="generateMumbaiContacts()" class="px-3.5 py-2 bg-teal-600 hover:bg-teal-500 text-white rounded-xl text-xs font-bold flex items-center gap-1.5 shadow-sm shadow-teal-600/20 cursor-pointer">
                <i class="fa-solid fa-magnifying-glass-plus"></i>
                <span>Find 30+ Contacts &amp; Store List</span>
              </button>
              <button onclick="runMumbaiOutreachCycle()" class="px-3.5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-bold flex items-center gap-1.5 shadow-sm shadow-indigo-600/20 cursor-pointer">
                <i class="fa-solid fa-user-plus"></i>
                <span>Maximize Connection Requests Only</span>
              </button>
              <button onclick="runMumbai2DayFollowup()" class="px-3.5 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-xl text-xs font-bold flex items-center gap-1.5 shadow-sm shadow-amber-600/20 cursor-pointer">
                <i class="fa-solid fa-arrows-rotate"></i>
                <span>Daily Check Accepted → Sending List</span>
              </button>
              <button onclick="runMumbaiSendMessagesOnly()" class="px-3.5 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded-xl text-xs font-bold flex items-center gap-1.5 shadow-sm shadow-purple-600/20 cursor-pointer">
                <i class="fa-solid fa-paper-plane"></i>
                <span>Send Messages to Sending List</span>
              </button>
              <button onclick="runMumbaiFullSequence()" class="px-3.5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-bold flex items-center gap-1.5 shadow-sm shadow-emerald-600/20 cursor-pointer">
                <i class="fa-solid fa-forward-step"></i>
                <span>Run Full Sequence (30+ → Connect → Send)</span>
              </button>
            </div>
          </div>
        </div>

        <!-- Step 3: Segregated Contacts & Lifecycle Queues -->
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center gap-2 flex-wrap border-b border-slate-100 pb-3">
            <button onclick="switchMumbaiSubTab('pec')" id="mSubTab-pec" class="px-3.5 py-1.5 rounded-xl text-xs font-bold bg-amber-600 text-white cursor-pointer">
              PEC Chandigarh Alumni (<span id="mTabPecCount">0</span>)
            </button>
            <button onclick="switchMumbaiSubTab('other')" id="mSubTab-other" class="px-3.5 py-1.5 rounded-xl text-xs font-bold bg-slate-100 text-slate-700 hover:bg-slate-200 cursor-pointer">
              Other Target Contacts (<span id="mTabOtherCount">0</span>)
            </button>
            <button onclick="switchMumbaiSubTab('sending')" id="mSubTab-sending" class="px-3.5 py-1.5 rounded-xl text-xs font-bold bg-slate-100 text-slate-700 hover:bg-slate-200 cursor-pointer">
              Sending List (Accepted &amp; Ready) (<span id="mTabSendingCount">0</span>)
            </button>
            <button onclick="switchMumbaiSubTab('incomplete')" id="mSubTab-incomplete" class="px-3.5 py-1.5 rounded-xl text-xs font-bold bg-slate-100 text-slate-700 hover:bg-slate-200 cursor-pointer">
              Incomplete / Pending Accept (<span id="mTabIncompleteCount">0</span>)
            </button>
            <button onclick="switchMumbaiSubTab('completed')" id="mSubTab-completed" class="px-3.5 py-1.5 rounded-xl text-xs font-bold bg-slate-100 text-slate-700 hover:bg-slate-200 cursor-pointer">
              Completed Outreach (<span id="mTabCompletedCount">0</span>)
            </button>
            <button onclick="switchMumbaiSubTab('daily')" id="mSubTab-daily" class="px-3.5 py-1.5 rounded-xl text-xs font-bold bg-slate-100 text-slate-700 hover:bg-slate-200 cursor-pointer">
              Daily Activity Log
            </button>
          </div>

          <!-- Contacts Lifecycle Table -->
          <div id="mumbaiContactsTableWrap" class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="p-3">Contact &amp; Role</th>
                  <th class="p-3">Company &amp; Tier</th>
                  <th class="p-3">Category &amp; Keyword</th>
                  <th class="p-3">Lifecycle Status / Timing</th>
                  <th class="p-3">Message / Action</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100" id="mumbaiContactsTableBody">
                <tr><td colspan="5" class="p-6 text-center text-slate-400">No contacts discovered yet. Select companies above and click "Find & Segregate Contacts".</td></tr>
              </tbody>
            </table>
          </div>

          <!-- Daily Activity Table -->
          <div id="mumbaiDailyTableWrap" class="hidden overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="p-3">Date</th>
                  <th class="p-3">Connection Requests Sent</th>
                  <th class="p-3">Messages Sent (Direct + Follow-up)</th>
                  <th class="p-3">2-Day Acceptances Detected</th>
                  <th class="p-3">Completed Follow-ups</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100" id="mumbaiDailyTableBody">
                <tr><td colspan="5" class="p-6 text-center text-slate-400">No daily activity logged yet.</td></tr>
              </tbody>
            </table>
          </div>
        </div>

      </div>

      <!-- ========================================== -->
      <!-- TAB 9: LIVE BACKGROUND TERMINAL            -->
      <!-- ========================================== -->
      <div id="view-terminal" class="hidden space-y-4">
        <div class="bg-slate-950 text-slate-200 rounded-2xl p-6 shadow-xl border border-slate-800 space-y-3 font-mono">
          <div class="flex items-center justify-between pb-3 border-b border-slate-800">
            <div class="flex items-center space-x-2">
              <span class="w-2.5 h-2.5 rounded-full bg-rose-500"></span>
              <span class="w-2.5 h-2.5 rounded-full bg-amber-500"></span>
              <span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
              <span class="text-xs font-bold text-slate-300 ml-2">Real-time Background Worker Console</span>
            </div>
            <button onclick="clearTerminal()" class="text-xs text-slate-500 hover:text-slate-300">Clear</button>
          </div>
          <div id="fullTerminalBox" class="h-96 overflow-y-auto space-y-1 text-xs leading-relaxed custom-scroll">
            <div class="text-slate-500 italic">Connecting to live automation log stream...</div>
          </div>
        </div>
      </div>

    </main>
  </div>

  <script>
    let activeTab = 'dashboard';
    let alumniCandidates = [];
    let selectedAlumniIndices = new Set();
    let cachedManualJobs = [];
    let cachedGmailIntel = [];
    let currentManualFilter = 'all';
    let currentGmailFilter = 'all';
    const candidateName = "Ashutosh Bajpai";

    function switchTab(tabId) {
      if (tabId === 'forms') tabId = 'feed';
      activeTab = tabId;
      document.querySelectorAll('.nav-item').forEach(el => {
        el.className = "nav-item w-full flex items-center space-x-3 px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition";
      });
      const activeNav = document.getElementById(`nav-${tabId}`);
      if (activeNav) {
        activeNav.className = "nav-item w-full flex items-center space-x-3 px-3 py-2.5 rounded-xl text-sm font-semibold transition bg-slate-100 text-slate-900 shadow-sm";
      }

      ['dashboard', 'gmail', 'feed', 'easy-apply', 'forms', 'recruiters', 'alumni', 'mumbai', 'naukri', 'manual', 'resume', 'terminal'].forEach(t => {
        const el = document.getElementById(`view-${t}`);
        if (el) el.classList.toggle('hidden', t !== tabId);
      });

      const headingMap = {
        dashboard: 'Executive Dashboard',
        gmail: 'Gmail Inbox Intelligence',
        feed: 'LinkedIn Feed Posts & Forms Desk',
        'easy-apply': 'Easy Apply & Target Job Listings Desk',
        forms: 'LinkedIn Feed Posts & Forms Desk',
        recruiters: 'Harvested Recruiter Emails',
        alumni: 'PEC Alumni & Referral Outreach',
        mumbai: 'Mumbai Network Builder & 2-Day Follow-Up',
        naukri: 'Naukri Daily Recency Booster',
        manual: 'Manual Intervention Desk',
        resume: 'Active Master Resume & Two-Phase Referral Desk',
        terminal: 'Live Background Console'
      };

      document.getElementById('currentBreadcrumb').innerText = tabId;
      document.getElementById('currentPageHeading').innerText = headingMap[tabId] || tabId;
      refreshTabView(tabId);
    }

    function refreshTabView(tabId) {
      if (tabId === 'dashboard') { loadManualTable(); loadGmailIntel(); }
      else if (tabId === 'gmail') { loadGmailIntel(); }
      else if (tabId === 'feed' || tabId === 'forms') { loadFeedPosts(); }
      else if (tabId === 'easy-apply') { loadEasyApplyJobs(); }
      else if (tabId === 'recruiters') { loadRecruiterLeads(); }
      else if (tabId === 'alumni') { loadOutreachHistory(); loadTemplates(); }
      else if (tabId === 'mumbai') { loadMumbaiWorkspace(); }
      else if (tabId === 'naukri') { loadNaukriApplied(); }
      else if (tabId === 'manual') { loadManualTable(); }
      else if (tabId === 'resume') { loadResumeStatus(); loadDispatches(); }
      else if (tabId === 'terminal') { pollLogs(); }
    }

    async function pollDashboardData() {
      try {
        const res = await fetch('/api/stats');
        const d = await res.json();
        document.getElementById('cardTodayCount').innerText = d.total_today;
        if (document.getElementById('cardFeedCount')) document.getElementById('cardFeedCount').innerText = d.feed_posts_count ?? d.pending_forms_count ?? 0;
        if (document.getElementById('cardEasyApplyCount')) document.getElementById('cardEasyApplyCount').innerText = d.easy_apply_count ?? 0;
        if (document.getElementById('cardRecruiterCount')) document.getElementById('cardRecruiterCount').innerText = d.recruiter_leads_count ?? 0;

        document.getElementById('sidebarManualBadge').innerText = d.manual_count;
        document.getElementById('sidebarGmailBadge').innerText = d.email_intel_count;
        if (document.getElementById('sidebarFeedBadge')) document.getElementById('sidebarFeedBadge').innerText = d.feed_posts_count ?? 0;
        if (document.getElementById('sidebarEasyApplyBadge')) document.getElementById('sidebarEasyApplyBadge').innerText = d.easy_apply_count ?? 0;
        if (document.getElementById('sidebarFormsBadge')) document.getElementById('sidebarFormsBadge').innerText = d.feed_posts_count ?? 0;
        if (document.getElementById('sidebarMumbaiBadge')) document.getElementById('sidebarMumbaiBadge').innerText = d.mumbai_companies_count ?? 0;
        document.getElementById('sidebarRecruitersBadge').innerText = d.recruiter_leads_count;

        document.getElementById('metricNaukri').innerText = d.naukri_today;
        document.getElementById('metricGmail').innerText = d.email_intel_count;
        document.getElementById('metricManual').innerText = d.manual_count;

        if (d.naukri_boost?.timestamp) {
          document.getElementById('naukriLastBoostDate').innerText = d.naukri_boost.timestamp;
        }

        const ct = d.current_task;
        const pill = document.getElementById('taskStatusPill');
        const pillTxt = document.getElementById('taskStatusText');
        if (pill && ct) {
          if (ct.running) {
            pill.className = "px-2.5 py-1 text-xs font-semibold rounded-xl bg-amber-50 text-amber-700 border border-amber-200 flex items-center gap-1.5 shadow-sm";
            pill.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-500 animate-ping"></span><span>Running: ${ct.name} (${ct.started_at || ''})</span>`;
          } else {
            pill.className = "px-2.5 py-1 text-xs font-semibold rounded-xl bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1.5 shadow-sm";
            pill.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-500"></span><span>System Idle</span>`;
          }
        }

        const badge = document.getElementById('sessionStatusText');
        const badgeBtn = document.getElementById('btnSessionModal');
        if (badge && badgeBtn) {
          if (d.linkedin_authenticated) {
            badgeBtn.className = "px-2.5 py-1 text-xs font-semibold rounded-xl bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1.5 shadow-sm transition cursor-pointer";
            badge.innerText = "LinkedIn: Active";
          } else {
            badgeBtn.className = "px-2.5 py-1 text-xs font-semibold rounded-xl bg-amber-50 text-amber-700 border border-amber-300 flex items-center gap-1.5 shadow-sm transition cursor-pointer animate-pulse";
            badge.innerText = "LinkedIn: Update Key";
          }
        }
      } catch (e) {}
    }

    async function resetTaskLock() {
      if (!confirm("Reset the current background execution lock back to Idle?")) return;
      try {
        const res = await fetch('/api/reset_task', { method: 'POST' });
        const d = await res.json();
        alert(d.message || "Lock reset.");
        pollDashboardData();
      } catch (e) {
        alert("Error resetting lock: " + e);
      }
    }

    async function pollLogs() {
      try {
        const res = await fetch('/api/logs');
        const d = await res.json();
        const box = document.getElementById('fullTerminalBox');
        if (d.logs && d.logs.length) {
          box.innerHTML = d.logs.map(l => {
            const isSuccess = l.includes('SUCCESS');
            const isWarn = l.includes('WARNING') || l.includes('MANUAL');
            const col = isSuccess ? 'text-emerald-400' : isWarn ? 'text-amber-400' : 'text-slate-300';
            return `<div class="${col}">${l}</div>`;
          }).join('');
          box.scrollTop = box.scrollHeight;
        }
      } catch (e) {}
    }

    async function loadScreeningPassed() {
      try {
        const res = await fetch('/api/screening_passed');
        const d = await res.json();
        const tbody = document.getElementById('mainScreeningPassedTable');
        if (!tbody) return;
        if (!d.opportunities || !d.opportunities.length) {
          tbody.innerHTML = '<tr><td colspan="5" class="p-6 text-center text-slate-400">No opportunities have passed screening yet.</td></tr>';
          return;
        }

        tbody.innerHTML = d.opportunities.map(item => `
          <tr class="hover:bg-slate-50 transition">
            <td class="p-3 font-bold text-slate-900 whitespace-nowrap flex items-center gap-1.5">
              <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
              <span>${item.company}</span>
            </td>
            <td class="p-3 font-medium text-slate-800 max-w-xs truncate" title="${item.subject}">
              ${item.subject}
            </td>
            <td class="p-3">
              <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-200">
                ${item.passed_stage || 'Screening Passed'}
              </span>
            </td>
            <td class="p-3 text-slate-700 font-semibold text-[11px]">${item.next_action}</td>
            <td class="p-3 text-right">
              <a href="${item.gmail_link}" target="_blank"
                 class="px-2.5 py-1 bg-purple-50 hover:bg-purple-100 text-purple-700 border border-purple-200 rounded-lg text-xs font-semibold inline-flex items-center gap-1">
                <span>Open Email</span>
                <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
              </a>
            </td>
          </tr>
        `).join('');
      } catch (e) {}
    }

    // Gmail Intel
    async function loadGmailIntel() {
      try {
        const res = await fetch('/api/inbox_intel');
        const d = await res.json();
        cachedGmailIntel = d.intel || [];
        renderGmailTable();
        loadScreeningPassed();
      } catch (e) {}
    }

    function filterGmailIntel(category) {
      currentGmailFilter = category;
      ['btnGFilterAll', 'btnGFilterExam', 'btnGFilterApplied', 'btnGFilterInvites', 'btnGFilterOutbound'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.className = "px-3 py-1 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition";
      });
      const activeMap = {
        all: 'btnGFilterAll',
        exam: 'btnGFilterExam',
        applied: 'btnGFilterApplied',
        invites: 'btnGFilterInvites',
        outbound: 'btnGFilterOutbound'
      };
      const activeBtn = document.getElementById(activeMap[category]);
      if (activeBtn) activeBtn.className = "px-3 py-1 rounded-lg text-xs font-semibold bg-purple-600 text-white transition";

      renderGmailTable();
    }

    function renderGmailTable() {
      const fTable = document.getElementById('fullGmailTableBody');
      const qTable = document.getElementById('quickGmailTable');
      if (!fTable && !qTable) return;

      let filtered = cachedGmailIntel;
      if (currentGmailFilter === 'exam') {
        filtered = cachedGmailIntel.filter(i => i.category.includes('Exam'));
      } else if (currentGmailFilter === 'applied') {
        filtered = cachedGmailIntel.filter(i => i.category.includes('Active Application'));
      } else if (currentGmailFilter === 'invites') {
        filtered = cachedGmailIntel.filter(i => i.category.includes('Recruiter Invite'));
      } else if (currentGmailFilter === 'outbound') {
        filtered = cachedGmailIntel.filter(i => i.category.includes('Outbound'));
      }

      if (!filtered.length) {
        if (fTable) fTable.innerHTML = `<tr><td colspan="5" class="p-6 text-center text-slate-400">No updates match this filter.</td></tr>`;
        return;
      }

      if (fTable) {
        fTable.innerHTML = filtered.map(item => `
          <tr class="hover:bg-slate-50 transition">
            <td class="p-3 font-bold text-slate-900 whitespace-nowrap">${item.company}</td>
            <td class="p-3 text-slate-700 max-w-sm truncate" title="${item.subject}">
              <div class="font-semibold text-slate-800">${item.subject}</div>
              <div class="text-[11px] text-slate-400 truncate">${item.snippet || ''}</div>
            </td>
            <td class="p-3">
              <span class="px-2 py-0.5 rounded text-[10px] ${item.status_badge || 'bg-slate-100 text-slate-700'}">${item.category}</span>
            </td>
            <td class="p-3 font-medium text-slate-700 text-[11px]">${item.next_action}</td>
            <td class="p-3 text-right">
              <a href="${item.gmail_link}" target="_blank"
                 class="px-2.5 py-1 bg-purple-50 hover:bg-purple-100 text-purple-700 border border-purple-200 rounded-lg text-xs font-semibold inline-flex items-center gap-1">
                <span>View</span>
                <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
              </a>
            </td>
          </tr>
        `).join('');
      }

      if (qTable) {
        qTable.innerHTML = cachedGmailIntel.slice(0, 5).map(item => `
          <tr class="hover:bg-slate-50">
            <td class="p-2.5 font-bold text-slate-900">${item.company}</td>
            <td class="p-2.5 text-slate-700 max-w-xs truncate">${item.subject}</td>
            <td class="p-2.5"><span class="px-2 py-0.5 rounded text-[10px] ${item.status_badge}">${item.category.split('/')[0]}</span></td>
            <td class="p-2.5 text-right">
              <a href="${item.gmail_link}" target="_blank" class="text-xs text-purple-600 font-semibold hover:underline">View</a>
            </td>
          </tr>
        `).join('');
      }
    }

    // ==========================================
    // 1. LINKEDIN FEED POSTS & FORMS DESK
    // ==========================================
    async function loadFeedPosts() {
      try {
        const res = await fetch('/api/feed_posts');
        const d = await res.json();
        const tbody = document.getElementById('feedPostsTableBody') || document.getElementById('pendingFormsTableBody');
        if (!tbody) return;

        const posts = d.posts || [];
        if (!posts.length) {
          tbody.innerHTML = `<tr><td colspan="6" class="p-6 text-center text-slate-400">No feed hiring posts currently pending.</td></tr>`;
          updateSelectedFeedCount();
          return;
        }

        tbody.innerHTML = posts.map(f => {
          const tags = f.tags || ['Feed Post', 'Non-Tech Role'];
          const tagsHtml = tags.map(t => {
            const isComment = t.includes('Comment');
            return `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold ${isComment ? 'bg-purple-100 text-purple-700 border border-purple-200' : 'bg-teal-100 text-teal-800 border border-teal-200'}">${t}</span>`;
          }).join(' ');

          const safeText = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
          const roleTitle = safeText(f.job_role || 'Hiring Opportunity');
          const fullDesc = safeText(f.full_description || f.context || '');
          const shortDesc = safeText((f.full_description || f.context || '').slice(0, 190));
          const profileLinkHtml = f.author_url
            ? `<a href="${f.author_url}" target="_blank" class="mt-1 mr-1 px-2 py-0.5 bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200 rounded-md text-[10px] font-semibold inline-flex items-center gap-1 transition"><i class="fa-solid fa-user text-slate-500"></i><span>Profile ↗</span></a>`
            : '';
          const emailHtml = f.email
            ? `<div class="mt-1.5 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-amber-50 border border-amber-200 text-[11px] font-semibold text-amber-800"><i class="fa-solid fa-envelope text-amber-600"></i><a href="mailto:${safeText(f.email)}" class="underline hover:text-amber-950">${safeText(f.email)}</a></div>`
            : '';
          const formBtnHtml = f.form_url
            ? `<a href="${f.form_url}" target="_blank" class="px-3 py-1.5 bg-teal-600 hover:bg-teal-500 text-white rounded-xl text-xs font-semibold inline-flex items-center gap-1.5 shadow-sm shadow-teal-600/20"><span>Open &amp; Fill Form</span><i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i></a>`
            : '';

          return `
            <tr class="hover:bg-slate-50 transition align-top">
              <td class="p-3">
                <input type="checkbox" class="feed-checkbox-item rounded text-teal-600 cursor-pointer" value="${f.id}" onchange="updateSelectedFeedCount()">
              </td>
              <td class="p-3 text-slate-400 text-[11px] whitespace-nowrap">${safeText(f.timestamp)}</td>
              <td class="p-3 font-bold text-slate-900">
                <div class="text-sm font-bold text-slate-900">${safeText(f.poster)}</div>
                <div class="flex flex-wrap items-center">
                  ${profileLinkHtml}
                  <a href="${f.post_url}" target="_blank" class="mt-1 px-2 py-0.5 bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 rounded-md text-[10px] font-semibold inline-flex items-center gap-1 transition" title="Open original post on LinkedIn">
                    <i class="fa-brands fa-linkedin text-blue-600"></i>
                    <span>Post Link ↗</span>
                  </a>
                </div>
              </td>
              <td class="p-3 text-slate-600 max-w-lg">
                <div class="text-xs font-bold text-slate-900 mb-1">Role: ${roleTitle}</div>
                <div class="flex items-center gap-1 flex-wrap mb-1">${tagsHtml}</div>
                <details class="text-xs text-slate-600">
                  <summary class="cursor-pointer text-slate-700 hover:text-slate-950 font-medium">${shortDesc}${fullDesc.length > 190 ? '... <span class="text-teal-700 underline">[Read Full JD]</span>' : ''}</summary>
                  <div class="mt-2 p-2.5 bg-slate-50 border border-slate-200 rounded-lg whitespace-pre-wrap text-[11px] leading-relaxed text-slate-700 max-h-56 overflow-y-auto">${fullDesc}</div>
                </details>
                ${emailHtml}
              </td>
              <td class="p-3 whitespace-nowrap">
                <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-teal-100 text-teal-800">${safeText(f.status || 'Pending')}</span>
              </td>
              <td class="p-3 text-right whitespace-nowrap">
                <div class="inline-flex items-center gap-1.5 justify-end">
                  <a href="${f.post_url}" target="_blank" title="View the original LinkedIn post"
                     class="px-2.5 py-1.5 bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 rounded-xl text-xs font-bold inline-flex items-center gap-1.5 transition">
                    <i class="fa-brands fa-linkedin text-blue-600 text-sm"></i>
                    <span>Source Post ↗</span>
                  </a>
                  ${formBtnHtml}
                  <button onclick="removeFeedPost('${f.id}')" title="Dismiss / Remove this post"
                          class="px-2.5 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-600 border border-rose-200 rounded-xl text-xs font-semibold inline-flex items-center gap-1 transition cursor-pointer">
                    <i class="fa-solid fa-trash-can text-xs"></i>
                    <span>Remove</span>
                  </button>
                </div>
              </td>
            </tr>
          `;
        }).join('');
        updateSelectedFeedCount();
      } catch (e) {}
    }

    function toggleSelectAllFeed(master) {
      document.querySelectorAll('.feed-checkbox-item').forEach(cb => cb.checked = master.checked);
      updateSelectedFeedCount();
    }

    function updateSelectedFeedCount() {
      const selected = Array.from(document.querySelectorAll('.feed-checkbox-item:checked')).map(cb => cb.value);
      const btn = document.getElementById('btnDeleteSelectedFeed') || document.getElementById('btnDeleteSelectedForms');
      const countSpan = document.getElementById('selectedFeedCount') || document.getElementById('selectedFormsCount');
      if (countSpan) countSpan.innerText = selected.length;
      if (btn) {
        if (selected.length > 0) btn.classList.remove('hidden');
        else btn.classList.add('hidden');
      }
    }

    async function deleteSelectedFeedPosts() {
      const selected = Array.from(document.querySelectorAll('.feed-checkbox-item:checked')).map(cb => cb.value);
      if (!selected.length) return;
      if (!confirm(`Delete ${selected.length} selected feed posts from your desk?`)) return;
      try {
        const res = await fetch('/api/feed_posts/delete_batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: selected })
        });
        const d = await res.json();
        if (d.success) {
          loadFeedPosts();
          pollDashboardData();
        }
      } catch (e) {
        alert("Network error: " + e);
      }
    }

    async function removeFeedPost(postId) {
      if (!confirm("Remove this feed post from your desk?")) return;
      try {
        const res = await fetch('/api/feed_posts/remove', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: postId })
        });
        const d = await res.json();
        if (d.success) {
          loadFeedPosts();
          pollDashboardData();
        }
      } catch (e) {
        alert("Network error: " + e);
      }
    }

    async function clearAllFeedPosts() {
      if (!confirm("Are you sure you want to remove ALL feed posts from your desk?")) return;
      try {
        const res = await fetch('/api/feed_posts/clear_all', { method: 'POST' });
        const d = await res.json();
        if (d.success) {
          loadFeedPosts();
          pollDashboardData();
        }
      } catch (e) {
        alert("Network error: " + e);
      }
    }

    // Alias for backwards compatibility
    const loadPendingForms = loadFeedPosts;
    const removePendingForm = removeFeedPost;
    const clearAllPendingForms = clearAllFeedPosts;
    const deleteSelectedForms = deleteSelectedFeedPosts;
    const toggleSelectAllForms = toggleSelectAllFeed;

    // ==========================================
    // 2. EASY APPLY & TARGET JOB LISTINGS DESK
    // ==========================================
    async function loadEasyApplyJobs() {
      try {
        const res = await fetch('/api/easy_apply_jobs');
        const d = await res.json();
        const tbody = document.getElementById('easyApplyTableBody');
        if (!tbody) return;

        const jobs = d.jobs || [];
        if (!jobs.length) {
          tbody.innerHTML = `<tr><td colspan="7" class="p-6 text-center text-slate-400">No Easy Apply jobs currently queued.</td></tr>`;
          updateSelectedJobsCount();
          return;
        }

        tbody.innerHTML = jobs.map(j => {
          return `
            <tr class="hover:bg-slate-50 transition">
              <td class="p-3">
                <input type="checkbox" class="job-checkbox-item rounded text-blue-600 cursor-pointer" value="${j.id}" onchange="updateSelectedJobsCount()">
              </td>
              <td class="p-3 text-slate-400 text-[11px] whitespace-nowrap">${j.timestamp}</td>
              <td class="p-3 font-bold text-slate-900">
                <div class="text-sm font-bold text-slate-900">${j.company}</div>
              </td>
              <td class="p-3 text-slate-700 font-semibold">${j.title}</td>
              <td class="p-3 text-slate-600">
                <div class="text-xs">${j.location}</div>
                <span class="inline-block px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-200 mt-0.5">${j.experience}</span>
              </td>
              <td class="p-3">
                <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800">
                  <i class="fa-solid fa-bolt mr-1"></i>${j.status}
                </span>
              </td>
              <td class="p-3 text-right whitespace-nowrap">
                <div class="inline-flex items-center gap-1.5 justify-end">
                  <a href="${j.job_url}" target="_blank"
                     class="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold inline-flex items-center gap-1.5 shadow-sm shadow-blue-600/20">
                    <i class="fa-brands fa-linkedin text-white"></i>
                    <span>View &amp; Apply ↗</span>
                  </a>
                  <button onclick="removeEasyApplyJob('${j.id}')" title="Dismiss this job"
                          class="px-2.5 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-600 border border-rose-200 rounded-xl text-xs font-semibold inline-flex items-center gap-1 transition cursor-pointer">
                    <i class="fa-solid fa-trash-can text-xs"></i>
                    <span>Remove</span>
                  </button>
                </div>
              </td>
            </tr>
          `;
        }).join('');
        updateSelectedJobsCount();
      } catch (e) {}
    }

    function toggleSelectAllEasyApply(master) {
      document.querySelectorAll('.job-checkbox-item').forEach(cb => cb.checked = master.checked);
      updateSelectedJobsCount();
    }

    function updateSelectedJobsCount() {
      const selected = Array.from(document.querySelectorAll('.job-checkbox-item:checked')).map(cb => cb.value);
      const btn = document.getElementById('btnDeleteSelectedJobs');
      const countSpan = document.getElementById('selectedJobsCount');
      if (countSpan) countSpan.innerText = selected.length;
      if (btn) {
        if (selected.length > 0) btn.classList.remove('hidden');
        else btn.classList.add('hidden');
      }
    }

    async function deleteSelectedEasyApplyJobs() {
      const selected = Array.from(document.querySelectorAll('.job-checkbox-item:checked')).map(cb => cb.value);
      if (!selected.length) return;
      if (!confirm(`Delete ${selected.length} selected Easy Apply job postings?`)) return;
      try {
        const res = await fetch('/api/easy_apply_jobs/delete_batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: selected })
        });
        const d = await res.json();
        if (d.success) {
          loadEasyApplyJobs();
          pollDashboardData();
        }
      } catch (e) {
        alert("Network error: " + e);
      }
    }

    async function removeEasyApplyJob(jobId) {
      if (!confirm("Remove this job posting from your Easy Apply desk?")) return;
      try {
        const res = await fetch('/api/easy_apply_jobs/remove', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: jobId })
        });
        const d = await res.json();
        if (d.success) {
          loadEasyApplyJobs();
          pollDashboardData();
        }
      } catch (e) {
        alert("Network error: " + e);
      }
    }

    async function clearAllEasyApplyJobs() {
      if (!confirm("Are you sure you want to remove ALL Easy Apply jobs from your desk?")) return;
      try {
        const res = await fetch('/api/easy_apply_jobs/clear_all', { method: 'POST' });
        const d = await res.json();
        if (d.success) {
          loadEasyApplyJobs();
          pollDashboardData();
        }
      } catch (e) {
        alert("Network error: " + e);
      }
    }

    // Recruiter Leads
    async function loadRecruiterLeads() {
      try {
        const res = await fetch('/api/recruiter_leads');
        const d = await res.json();
        const tbody = document.getElementById('recruiterLeadsTableBody');
        if (!tbody) return;

        if (!d.emails || !d.emails.length) {
          tbody.innerHTML = `<tr><td colspan="6" class="p-6 text-center text-slate-400">No recruiter leads harvested yet.</td></tr>`;
          updateSelectedRecruitersCount();
          return;
        }

        tbody.innerHTML = d.emails.map(e => {
          const tags = e.tags || ['Recruiting (0-2 Yrs)'];
          const tagsHtml = tags.map(t => `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">${t}</span>`).join(' ');

          return `
            <tr class="hover:bg-slate-50 transition">
              <td class="p-3">
                <input type="checkbox" class="recruiter-checkbox-item rounded text-indigo-600 cursor-pointer" value="${e.id}" onchange="updateSelectedRecruitersCount()">
              </td>
              <td class="p-3 text-slate-400 text-[11px] whitespace-nowrap">${e.timestamp}</td>
              <td class="p-3 font-bold text-slate-900">
                <div class="text-sm font-bold text-slate-900">${e.recipient_name}</div>
                <a href="${e.post_url}" target="_blank" class="mt-1 px-2 py-0.5 bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 rounded-md text-[11px] font-semibold inline-flex items-center gap-1.5 transition" title="Open source LinkedIn post in new tab">
                  <i class="fa-brands fa-linkedin text-blue-600"></i>
                  <span>Source Post ↗</span>
                </a>
              </td>
              <td class="p-3 font-semibold text-indigo-600">${e.email}</td>
              <td class="p-3 text-slate-600 max-w-sm">
                <div class="flex items-center gap-1 flex-wrap mb-1">${tagsHtml}</div>
                <div class="font-medium text-slate-800 text-xs">${e.subject}</div>
                <div class="text-[11px] text-slate-400 truncate">${e.draft_body.slice(0, 80)}...</div>
              </td>
              <td class="p-3 text-right whitespace-nowrap">
                <div class="inline-flex items-center gap-1.5 justify-end">
                  <a href="${e.post_url}" target="_blank" title="View the original LinkedIn post where this recruiter email was shared"
                     class="px-2.5 py-1.5 bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 rounded-xl text-xs font-bold inline-flex items-center gap-1.5 transition">
                    <i class="fa-brands fa-linkedin text-blue-600 text-sm"></i>
                    <span>View Source Post ↗</span>
                  </a>
                  <a href="${e.gmail_web_link}" target="_blank"
                     class="px-3 py-1.5 bg-sky-600 hover:bg-sky-500 text-white rounded-xl text-xs font-semibold inline-flex items-center gap-1.5 shadow-sm shadow-sky-600/20">
                    <i class="fa-solid fa-envelope"></i>
                    <span>Send via Gmail</span>
                  </a>
                  <a href="${e.mailto_link}" class="px-2 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs" title="Open local mail client">
                    <i class="fa-solid fa-paper-plane"></i>
                  </a>
                  <button onclick="removeRecruiterLead('${e.id}')" title="Dismiss / Remove this recruiter lead"
                          class="px-2 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-600 border border-rose-200 rounded-lg text-xs transition cursor-pointer">
                    <i class="fa-solid fa-trash-can text-xs"></i>
                  </button>
                </div>
              </td>
            </tr>
          `;
        }).join('');
        updateSelectedRecruitersCount();
      } catch (e) {}
    }

    function toggleSelectAllRecruiters(master) {
      document.querySelectorAll('.recruiter-checkbox-item').forEach(cb => cb.checked = master.checked);
      updateSelectedRecruitersCount();
    }

    function updateSelectedRecruitersCount() {
      const selected = Array.from(document.querySelectorAll('.recruiter-checkbox-item:checked')).map(cb => cb.value);
      const btn = document.getElementById('btnDeleteSelectedRecruiters');
      const countSpan = document.getElementById('selectedRecruitersCount');
      if (countSpan) countSpan.innerText = selected.length;
      if (btn) {
        if (selected.length > 0) btn.classList.remove('hidden');
        else btn.classList.add('hidden');
      }
    }

    async function deleteSelectedRecruiters() {
      const selected = Array.from(document.querySelectorAll('.recruiter-checkbox-item:checked')).map(cb => cb.value);
      if (!selected.length) return;
      if (!confirm(`Delete ${selected.length} selected recruiter leads from your desk?`)) return;
      try {
        const res = await fetch('/api/recruiter_leads/delete_batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: selected })
        });
        const d = await res.json();
        if (d.success) {
          loadRecruiterLeads();
          pollDashboardData();
        }
      } catch (e) {
        alert("Network error: " + e);
      }
    }

    // Naukri Auto-Applied Jobs Desk
    async function loadNaukriApplied() {
      try {
        const res = await fetch('/api/naukri_applied');
        const d = await res.json();
        const tbody = document.getElementById('naukriAppliedTableBody');
        const badge = document.getElementById('naukriAppliedCountBadge');
        const sideBadge = document.getElementById('sidebarNaukriBadge');
        if (badge) badge.innerText = `${d.count || 0} Applied`;
        if (sideBadge) sideBadge.innerText = d.count || 0;
        if (!tbody) return;

        if (!d.jobs || !d.jobs.length) {
          tbody.innerHTML = `<tr><td colspan="6" class="p-6 text-center text-slate-400">No Naukri applications submitted yet.</td></tr>`;
          return;
        }

        tbody.innerHTML = d.jobs.map(j => `
          <tr class="hover:bg-slate-50 transition">
            <td class="p-3 text-slate-400 text-[11px] whitespace-nowrap">${j.timestamp}</td>
            <td class="p-3 font-bold text-slate-900">${j.company}</td>
            <td class="p-3 font-semibold text-indigo-600">${j.title}</td>
            <td class="p-3">
              <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800 border border-amber-200">
                ${j.experience || '0-2 Yrs'}
              </span>
            </td>
            <td class="p-3 text-slate-600">${j.location || 'India'}</td>
            <td class="p-3 text-right whitespace-nowrap">
              <a href="${j.job_url}" target="_blank"
                 class="px-2.5 py-1.5 bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 rounded-xl text-xs font-semibold inline-flex items-center gap-1.5 transition">
                <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
                <span>View on Naukri ↗</span>
              </a>
            </td>
          </tr>
        `).join('');
      } catch (e) {}
    }

    // Manual Table Filters
    function filterManualQueue(category) {
      currentManualFilter = category;
      ['btnFilterAll', 'btnFilterQuestionnaire', 'btnFilterAts'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.className = "px-3 py-1 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition";
      });
      const activeBtnId = category === 'all' ? 'btnFilterAll' : category === 'questionnaire' ? 'btnFilterQuestionnaire' : 'btnFilterAts';
      const activeBtn = document.getElementById(activeBtnId);
      if (activeBtn) activeBtn.className = "px-3 py-1 rounded-lg text-xs font-semibold bg-indigo-600 text-white transition";

      renderManualTable();
    }

    function renderManualTable() {
      const fTable = document.getElementById('fullManualTableBody');
      const qTable = document.getElementById('quickManualTable');
      if (!fTable && !qTable) return;

      let filtered = cachedManualJobs;
      if (currentManualFilter === 'questionnaire') {
        filtered = cachedManualJobs.filter(j => (j.reason || '').toLowerCase().includes('questionnaire') || (j.reason || '').toLowerCase().includes('requirement'));
      } else if (currentManualFilter === 'ats') {
        filtered = cachedManualJobs.filter(j => !(j.reason || '').toLowerCase().includes('questionnaire'));
      }

      if (!filtered.length) {
        if (fTable) fTable.innerHTML = `<tr><td colspan="6" class="p-6 text-center text-slate-400">No openings match this category filter.</td></tr>`;
        return;
      }

      const rowsHtml = filtered.map(j => {
        const isQuestionnaire = (j.reason || '').toLowerCase().includes('questionnaire') || (j.reason || '').toLowerCase().includes('requirement');
        const badge = isQuestionnaire
          ? `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-purple-100 text-purple-700 border border-purple-200">Questionnaire Needed</span>`
          : `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-100 text-amber-700 border border-amber-200">Enterprise ATS</span>`;

        return `
          <tr class="hover:bg-slate-50 transition">
            <td class="p-3 text-slate-400 text-[11px] whitespace-nowrap">${j.timestamp}</td>
            <td class="p-3 font-semibold text-slate-900">${j.company}</td>
            <td class="p-3 font-medium text-indigo-600">${j.title}</td>
            <td class="p-3 text-slate-500">${j.location}</td>
            <td class="p-3">
              <div class="flex items-center gap-1.5 flex-wrap">
                ${badge}
                <span class="text-slate-600 text-[11px] truncate max-w-xs" title="${(j.reason || '').replace(/"/g, '&quot;')}">${j.reason}</span>
              </div>
            </td>
            <td class="p-3 text-right">
              <a href="${j.direct_application_url || j.job_url}" target="_blank"
                 class="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold transition inline-flex items-center gap-1.5 shadow-sm shadow-indigo-600/20">
                <span>Open & Apply</span>
                <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
              </a>
            </td>
          </tr>
        `;
      }).join('');

      if (fTable) fTable.innerHTML = rowsHtml;
      if (qTable) {
        qTable.innerHTML = cachedManualJobs.slice(0, 5).map(j => `
          <tr class="hover:bg-slate-50">
            <td class="p-2.5 font-semibold text-slate-900">${j.company}</td>
            <td class="p-2.5 font-medium text-indigo-600 truncate max-w-xs">${j.title}</td>
            <td class="p-2.5 text-right">
              <a href="${j.direct_application_url || j.job_url}" target="_blank"
                 class="px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded text-xs font-semibold">Apply</a>
            </td>
          </tr>
        `).join('');
      }
    }

    async function loadManualTable() {
      try {
        const res = await fetch('/api/manual_queue');
        const d = await res.json();
        cachedManualJobs = d.queue || [];
        renderManualTable();
      } catch (e) {}
    }

    // Outreach History
    async function loadOutreachHistory() {
      try {
        const res = await fetch('/api/outreach_tracker');
        const d = await res.json();
        const tbody = document.getElementById('outreachHistoryTableBody');
        if (!tbody) return;
        if (!d.history || d.history.length === 0) {
          tbody.innerHTML = '<tr><td colspan="6" class="p-4 text-center text-slate-400">No outreach sent yet.</td></tr>';
          return;
        }

        tbody.innerHTML = d.history.slice().reverse().map(item => `
          <tr class="hover:bg-slate-50 transition">
            <td class="p-2.5 text-slate-500 whitespace-nowrap">${item.timestamp || 'N/A'}</td>
            <td class="p-2.5 font-bold text-slate-900">
              <a href="${item.profile_url}" target="_blank" class="hover:underline text-indigo-600 flex items-center gap-1">
                ${item.name} <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
              </a>
            </td>
            <td class="p-2.5">
              <span class="px-2 py-0.5 rounded text-[10px] font-semibold ${item.company.includes('PEC') ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-700'}">
                ${item.company || item.headline || 'General'}
              </span>
            </td>
            <td class="p-2.5 text-slate-700 font-medium">${item.action_type || 'Direct Message'}</td>
            <td class="p-2.5">
              <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-700">
                ${item.status || 'Delivered'}
              </span>
            </td>
            <td class="p-2.5 text-slate-600 max-w-xs truncate" title="${(item.message_text || '').replace(/"/g, '&quot;')}">
              "${(item.message_text || '').slice(0, 75)}..."
            </td>
          </tr>
        `).join('');
      } catch (e) {}
    }

    // Alumni Crawl Functions
    async function crawlCompanyPeople() {
      const company = document.getElementById('targetCompanyInput').value.trim();
      const role = document.getElementById('targetRoleInput').value.trim();
      const prioritizeAlumni = document.getElementById('checkPecPriority').checked;

      if (!company) return alert("Please enter target company");
      const btn = document.getElementById('btnCrawlPeople');
      btn.innerHTML = `<i class="fa-solid fa-spinner animate-spin"></i><span>Crawling...</span>`;
      btn.disabled = true;

      try {
        const res = await fetch('/api/crawl_company', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ company, role, prioritize_alumni: prioritizeAlumni, limit: 15 })
        });
        const d = await res.json();
        alumniCandidates = d.people || [];
        selectedAlumniIndices.clear();
        alumniCandidates.slice(0, 5).forEach((_, i) => selectedAlumniIndices.add(i));
        renderAlumniList();
      } catch (e) {
        alert("Crawling failed: " + e);
      } finally {
        btn.innerHTML = `<i class="fa-solid fa-users-viewfinder"></i><span>Crawl People</span>`;
        btn.disabled = false;
      }
    }

    function renderAlumniList() {
      const c = document.getElementById('alumniCandidatesContainer');
      if (!alumniCandidates.length) {
        c.innerHTML = `<div class="p-8 text-center text-slate-400 text-xs">No candidates found for this company.</div>`;
        return;
      }

      c.innerHTML = alumniCandidates.map((p, idx) => {
        const isChecked = selectedAlumniIndices.has(idx);
        const isAlumni = p.is_alumni || (p.tier && p.tier.includes('PEC'));
        const badgeColor = isAlumni ? 'bg-amber-50 text-amber-600 border-amber-200' : 'bg-indigo-50 text-indigo-600 border-indigo-200';
        const badgeLabel = isAlumni ? '🌟 PEC Alumni' : (p.tier || 'Team Match');

        return `
          <div class="p-3 hover:bg-slate-50 transition flex items-center justify-between cursor-pointer" onclick="toggleAlumniCandidate(${idx})">
            <div class="flex items-center space-x-3">
              <input type="checkbox" ${isChecked ? 'checked' : ''} onclick="event.stopPropagation(); toggleAlumniCandidate(${idx})" class="w-4 h-4 rounded text-indigo-600 cursor-pointer">
              <div class="w-8 h-8 rounded-full ${isAlumni ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-700'} flex items-center justify-center font-bold text-xs">
                ${p.name.charAt(0)}
              </div>
              <div>
                <div class="flex items-center space-x-2">
                  <span class="text-xs font-bold text-slate-900">${p.name}</span>
                  <span class="text-[10px] px-1.5 py-0.5 rounded border ${badgeColor}">${badgeLabel}</span>
                </div>
                <p class="text-[11px] text-slate-400 truncate max-w-sm">${p.headline || p.company || ''}</p>
              </div>
            </div>
            <a href="${p.profile_url}" target="_blank" onclick="event.stopPropagation()" class="text-xs text-indigo-600 hover:underline">View Profile</a>
          </div>
        `;
      }).join('');

      document.getElementById('alumniSelectedCount').innerText = selectedAlumniIndices.size;
      document.getElementById('btnSendApprovedAlumni').disabled = selectedAlumniIndices.size === 0;
      updateAlumniPreview();
    }

    function toggleAlumniCandidate(idx) {
      if (selectedAlumniIndices.has(idx)) selectedAlumniIndices.delete(idx);
      else selectedAlumniIndices.add(idx);
      renderAlumniList();
    }

    function selectAllCandidates(selectAll) {
      if (selectAll) alumniCandidates.forEach((_, i) => selectedAlumniIndices.add(i));
      else selectedAlumniIndices.clear();
      renderAlumniList();
    }

    function insertVariable(targetId, variableTag) {
      const el = document.getElementById(targetId);
      if (!el) return;
      const start = el.selectionStart || el.value.length;
      const end = el.selectionEnd || el.value.length;
      const text = el.value;
      el.value = text.substring(0, start) + variableTag + text.substring(end);
      el.focus();
      el.selectionStart = el.selectionEnd = start + variableTag.length;
      updateAlumniPreview();
    }

    async function loadTemplates() {
      try {
        const res = await fetch('/api/templates');
        const d = await res.json();
        const tmpls = d.templates || {};
        if (tmpls.referral_template && document.getElementById('tmplReferral')) {
          document.getElementById('tmplReferral').value = tmpls.referral_template;
        }
        if (tmpls.alumni_template && document.getElementById('tmplAlumni')) {
          document.getElementById('tmplAlumni').value = tmpls.alumni_template;
        }
        if (tmpls.resume_dispatch_template && document.getElementById('tmplResumeReply')) {
          document.getElementById('tmplResumeReply').value = tmpls.resume_dispatch_template;
        }
        updateAlumniPreview();
      } catch (e) {
        console.error("Error loading templates:", e);
      }
    }

    async function saveTemplates() {
      const btn = document.getElementById('btnSaveTemplates');
      const badge = document.getElementById('templateSavedBadge');
      const referralTmpl = document.getElementById('tmplReferral').value;
      const alumniTmpl = document.getElementById('tmplAlumni').value;
      const resumeTmpl = document.getElementById('tmplResumeReply').value;

      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving to Config...';

      try {
        const res = await fetch('/api/templates', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            referral_template: referralTmpl,
            alumni_template: alumniTmpl,
            resume_dispatch_template: resumeTmpl
          })
        });
        const d = await res.json();
        if (d.status === "Success") {
          badge.className = "text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500 text-white shadow-sm";
          badge.innerHTML = '<i class="fa-solid fa-circle-check"></i> Saved Permanently!';
          setTimeout(() => {
            badge.className = "text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200";
            badge.innerHTML = '<i class="fa-solid fa-check"></i> Active & Synced';
          }, 3000);
          alert("Success! Your message templates have been permanently saved in config.json. All future runs and referral outreach will use this exact format.");
        } else {
          alert("Error saving: " + (d.message || "Failed"));
        }
      } catch (e) {
        alert("Network error saving templates: " + e);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> <span>Save & Update Templates For Future Outreach</span>';
      }
    }

    function updateAlumniPreview() {
      const firstIdx = Array.from(selectedAlumniIndices)[0];
      const previewBox = document.getElementById('alumniPreviewBox');
      const p = (firstIdx !== undefined && alumniCandidates[firstIdx]) ? alumniCandidates[firstIdx] : {
        name: "Jaishree Sharma",
        company: "Google",
        headline: "PEC Alumnus • Product",
        is_alumni: true
      };

      const isAlumni = p.is_alumni || (p.tier && p.tier.includes('PEC'));
      const is1st = p.is_connection || (p.degree === '1st');
      let tmpl = "";
      if (is1st) tmpl = document.getElementById('tmplReferral')?.value || "";
      else if (isAlumni) tmpl = document.getElementById('tmplAlumni')?.value || "";
      else tmpl = document.getElementById('tmplReferral')?.value || "";

      if (!tmpl) tmpl = document.getElementById('tmplReferral')?.value || "";

      const firstName = (p.name || '').split(' ')[0] || 'there';
      const rendered = tmpl.replace(/{first_name}/g, firstName)
                           .replace(/{name}/g, p.name)
                           .replace(/{company}/g, p.company || 'Google')
                           .replace(/{target_role}/g, "Analyst / Product Manager")
                           .replace(/{college}/g, "PEC")
                           .replace(/{my_name}/g, candidateName);

      previewBox.innerText = `To ${p.name} (${is1st ? '1st-Degree Referral' : (isAlumni ? 'PEC Alumni Note' : 'Outreach Note')}): "${rendered}"`;
    }

    async function sendApprovedAlumniOutreach() {
      const selected = Array.from(selectedAlumniIndices).map(i => alumniCandidates[i]);
      if (!selected.length) return;
      if (!confirm(`Send outreach to ${selected.length} approved candidates?`)) return;

      try {
        const res = await fetch('/api/send_alumni_batch', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            people: selected,
            alumni_template: document.getElementById('tmplAlumni').value,
            connect_template: document.getElementById('tmplReferral').value,
            sender_name: candidateName
          })
        });
        const d = await res.json();
        alert(`Finished! Processed ${d.results.length} outreach messages.`);
        loadOutreachHistory();
      } catch (e) {
        alert("Failed to send: " + e);
      }
    }

    async function loadResumeStatus() {
      try {
        const res = await fetch('/api/resume_status');
        const d = await res.json();
        if (d.exists) {
          document.getElementById('activeResumeName').innerText = d.filename;
          document.getElementById('activeResumePath').innerText = "Path: " + d.path;
          document.getElementById('activeResumeSize').innerText = d.size_kb + " KB";
          document.getElementById('activeResumeDate').innerText = d.modified;
          document.getElementById('resumeBadge').innerText = "Active Master";
          document.getElementById('resumeBadge').className = "px-3 py-1 rounded-full text-xs font-bold bg-emerald-100 text-emerald-700";
        } else {
          document.getElementById('activeResumeName').innerText = "No active resume uploaded";
          document.getElementById('activeResumePath').innerText = "Please upload a master resume below";
          document.getElementById('activeResumeSize').innerText = "--";
          document.getElementById('activeResumeDate').innerText = "--";
          document.getElementById('resumeBadge').innerText = "Missing";
          document.getElementById('resumeBadge').className = "px-3 py-1 rounded-full text-xs font-bold bg-rose-100 text-rose-700";
        }
      } catch (e) {
        console.error("Error loading resume status:", e);
      }
    }

    function displaySelectedFile(input) {
      if (input.files && input.files[0]) {
        const file = input.files[0];
        document.getElementById('uploadFilePrompt').innerText = file.name;
        document.getElementById('uploadFileDetails').innerText = `${(file.size / 1024).toFixed(1)} KB — Ready to upload and activate`;
      }
    }

    async function handleResumeUpload(e) {
      e.preventDefault();
      const input = document.getElementById('resumeFileInput');
      if (!input.files || !input.files[0]) {
        alert("Please choose a resume file (.pdf or .docx) first!");
        return;
      }

      const syncNaukri = document.getElementById('syncNaukriCheckbox').checked;
      const formData = new FormData();
      formData.append('resume', input.files[0]);
      formData.append('sync_naukri', syncNaukri ? 'true' : 'false');

      const btn = document.getElementById('btnUploadResume');
      const feedback = document.getElementById('uploadFeedback');
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Uploading & Updating...';
      feedback.className = "p-3 rounded-xl text-xs font-medium bg-amber-50 text-amber-800 border border-amber-200 block";
      feedback.innerText = syncNaukri ? "Uploading file and syncing to Naukri.com profile in background..." : "Saving master resume file...";

      try {
        const res = await fetch('/api/upload_resume', {
          method: 'POST',
          body: formData
        });
        const d = await res.json();
        if (d.success) {
          feedback.className = "p-3 rounded-xl text-xs font-medium bg-emerald-50 text-emerald-800 border border-emerald-200 block";
          feedback.innerHTML = `<strong>Success!</strong> Master resume updated to <strong>${d.filename}</strong>. Next applications & referral replies will automatically use this file.<br><span class="text-[11px] text-emerald-700">Naukri Sync: ${d.naukri_message}</span>`;
          loadResumeStatus();
        } else {
          feedback.className = "p-3 rounded-xl text-xs font-medium bg-rose-50 text-rose-800 border border-rose-200 block";
          feedback.innerText = "Error: " + (d.error || "Upload failed");
        }
      } catch (err) {
        feedback.className = "p-3 rounded-xl text-xs font-medium bg-rose-50 text-rose-800 border border-rose-200 block";
        feedback.innerText = "Network Error: " + err;
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-upload"></i> Upload & Set Active Resume';
      }
    }

    async function loadDispatches() {
      try {
        const res = await fetch('/api/dispatches');
        const d = await res.json();
        const dispatches = d.dispatches || [];
        document.getElementById('dispatchTableCount').innerText = `${dispatches.length} Dispatched`;

        const tbody = document.getElementById('dispatchesTableBody');
        if (!dispatches.length) {
          tbody.innerHTML = '<tr><td colspan="6" class="p-6 text-center text-slate-400">No resumes auto-dispatched yet. They will appear here when connections ask for your CV.</td></tr>';
          return;
        }

        tbody.innerHTML = dispatches.map(item => `
          <tr class="hover:bg-slate-50 transition">
            <td class="p-3 text-slate-400 whitespace-nowrap">${item.timestamp}</td>
            <td class="p-3 font-semibold text-slate-900">${item.contact_name}</td>
            <td class="p-3"><span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-50 text-indigo-700 border border-indigo-100">${item.matched_keyword}</span></td>
            <td class="p-3 font-mono text-[11px] text-slate-600">${item.resume_sent}</td>
            <td class="p-3"><span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-700">${item.status}</span></td>
            <td class="p-3 text-slate-600 text-xs italic truncate max-w-xs" title="${item.message}">${item.message}</td>
          </tr>
        `).join('');
      } catch (e) {
        console.error("Error loading dispatches:", e);
      }
    }

    async function triggerResumeScan() {
      const btn = document.getElementById('btnScanResumeReplies');
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Scanning LinkedIn Inbox...';
      try {
        const res = await fetch('/api/run/scan_replies', { method: 'POST' });
        const d = await res.json();
        alert(d.message || "Started LinkedIn message inbox scan for resume requests.");
      } catch (e) {
        alert("Error: " + e);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Scan LinkedIn Replies & Dispatch';
      }
    }

    async function triggerMasterRunAll() {
      if (!confirm("Launch all operations simultaneously across Naukri, LinkedIn, and Gmail?")) return;

      const btn = document.getElementById('btnMasterHeroRun');
      const label = document.getElementById('masterHeroRunLabel');
      if (btn) btn.disabled = true;
      if (label) label.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> RUNNING ALL OPERATIONS...';

      try {
        const res = await fetch('/api/run/run_all', { method: 'POST' });
        const d = await res.json();
        switchTab('terminal');
        alert(d.message || "Master Autopilot launched in background! Switching to live terminal console.");
        pollDashboardData();
      } catch (e) {
        alert("Error launching master autopilot: " + e);
      } finally {
        setTimeout(() => {
          if (btn) btn.disabled = false;
          if (label) label.innerText = 'START ALL OPERATIONS';
        }, 3000);
      }
    }

    async function triggerAction(actionType) {
      if (!confirm(`Trigger ${actionType} in background?`)) return;
      try {
        const res = await fetch(`/api/run/${actionType}`, { method: 'POST' });
        const d = await res.json();
        alert(d.message || 'Started');
        pollDashboardData();
      } catch (e) {
        alert("Error starting action: " + e);
      }
    }

    function clearTerminal() {
      document.getElementById('fullTerminalBox').innerHTML = '<div class="text-slate-500 italic">Terminal cleared.</div>';
    }

    function openSessionModal() {
      document.getElementById('sessionModal').classList.remove('hidden');
    }

    function closeSessionModal() {
      document.getElementById('sessionModal').classList.add('hidden');
    }

    async function launchLinkedInLogin() {
      const btn = document.getElementById('btnLaunchLoginBrowser');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Opening Chrome...';
      }
      try {
        const res = await fetch('/api/launch_linkedin_login', { method: 'POST' });
        const d = await res.json();
        alert(d.message || d.error || 'Done');
        if (d.success) {
          closeSessionModal();
          switchTab('terminal');
        }
      } catch (err) {
        alert('Error: ' + err);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i class="fa-brands fa-chrome"></i> Open Chrome Sign-In Window';
        }
      }
    }

    async function submitSessionCookie() {
      const liAt = document.getElementById('inputLiAt').value.trim();
      if (!liAt) {
        alert('Please enter a valid li_at cookie string.');
        return;
      }
      const btn = document.getElementById('btnSaveCookie');
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Verifying & Syncing...';
      try {
        const res = await fetch('/api/update_cookies', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ li_at: liAt })
        });
        const d = await res.json();
        if (d.success) {
          alert('SUCCESS: Live LinkedIn cookie verified, saved & synced to Render! You can now run "Find 30+ Contacts & Store List".');
          closeSessionModal();
          pollDashboardData();
        } else {
          alert('Error: ' + (d.error || 'Failed to update cookie'));
        }
      } catch (err) {
        alert('Network error: ' + err);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-cloud-arrow-up"></i> Verify, Save & Sync to Render';
      }
    }

    async function removeRecruiterLead(leadId) {
      if (!confirm("Remove this recruiter lead from your desk?")) return;
      try {
        const res = await fetch('/api/recruiter_leads/remove', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: leadId })
        });
        const d = await res.json();
        if (d.success) {
          loadRecruiterLeads();
          pollDashboardData();
        } else {
          alert("Error: " + (d.error || "Could not remove recruiter lead"));
        }
      } catch (e) {
        alert("Network error: " + e);
      }
    }

    // ==========================================
    // MUMBAI NETWORK BUILDER & 2-DAY FOLLOW-UP JS
    // ==========================================
    let mumbaiWorkspaceData = null;
    let currentMumbaiSizeFilter = 'all';
    let currentMumbaiSubTab = 'pec';

    async function loadMumbaiWorkspace() {
      try {
        const res = await fetch('/api/mumbai/summary');
        const d = await res.json();
        mumbaiWorkspaceData = d;

        if (document.getElementById('mumbaiTodayConnects')) document.getElementById('mumbaiTodayConnects').innerText = d.today_stats?.connections_sent ?? 0;
        if (document.getElementById('mumbaiTodayMessages')) document.getElementById('mumbaiTodayMessages').innerText = d.today_stats?.messages_sent ?? 0;
        if (document.getElementById('mumbaiPecCount')) document.getElementById('mumbaiPecCount').innerText = d.counts?.pec ?? 0;
        if (document.getElementById('mumbaiIncompleteCount')) document.getElementById('mumbaiIncompleteCount').innerText = d.counts?.incomplete ?? 0;
        if (document.getElementById('mumbaiSendingListCount')) document.getElementById('mumbaiSendingListCount').innerText = d.counts?.sending_list ?? 0;
        if (document.getElementById('mumbaiCompletedCount')) document.getElementById('mumbaiCompletedCount').innerText = d.counts?.completed ?? 0;

        if (document.getElementById('mTabPecCount')) document.getElementById('mTabPecCount').innerText = d.counts?.pec ?? 0;
        if (document.getElementById('mTabOtherCount')) document.getElementById('mTabOtherCount').innerText = d.counts?.other ?? 0;
        if (document.getElementById('mTabSendingCount')) document.getElementById('mTabSendingCount').innerText = d.counts?.sending_list ?? 0;
        if (document.getElementById('mTabIncompleteCount')) document.getElementById('mTabIncompleteCount').innerText = d.counts?.incomplete ?? 0;
        if (document.getElementById('mTabCompletedCount')) document.getElementById('mTabCompletedCount').innerText = d.counts?.completed ?? 0;

        renderMumbaiCompanies();
        renderMumbaiContactsSubTab();
      } catch (e) {}
    }

    function filterMumbaiSize(tier) {
      currentMumbaiSizeFilter = tier;
      const map = { 'all': 'btnMSizeAll', '250-500': 'btnMSize250', '500-1000': 'btnMSize500', '1000+': 'btnMSize1000' };
      Object.values(map).forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.className = "px-3 py-1 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200";
      });
      const active = document.getElementById(map[tier]);
      if (active) active.className = "px-3 py-1 rounded-lg text-xs font-semibold bg-indigo-600 text-white";
      renderMumbaiCompanies();
    }

    function renderMumbaiCompanies() {
      const tbody = document.getElementById('mumbaiCompaniesTableBody');
      if (!tbody || !mumbaiWorkspaceData) return;

      const allList = mumbaiWorkspaceData.companies || [];
      const c250 = allList.filter(c => c.size_tier === '250-500').length;
      const c500 = allList.filter(c => c.size_tier === '500-1000').length;
      const c1000 = allList.filter(c => c.size_tier === '1000+').length;
      if (document.getElementById('mCntAll')) document.getElementById('mCntAll').innerText = allList.length;
      if (document.getElementById('mCnt250')) document.getElementById('mCnt250').innerText = c250;
      if (document.getElementById('mCnt500')) document.getElementById('mCnt500').innerText = c500;
      if (document.getElementById('mCnt1000')) document.getElementById('mCnt1000').innerText = c1000;

      let list = allList;
      if (currentMumbaiSizeFilter !== 'all') {
        list = list.filter(c => c.size_tier === currentMumbaiSizeFilter);
      }
      const q = (document.getElementById('mumbaiCompanySearch')?.value || '').trim().toLowerCase();
      if (q) {
        list = list.filter(c => (c.name || '').toLowerCase().includes(q) || (c.industry || '').toLowerCase().includes(q));
      }

      if (!list.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="p-4 text-center text-slate-400">No companies found for this size bracket. Click "Generate Mumbai Companies" above.</td></tr>`;
        return;
      }

      tbody.innerHTML = list.map(c => {
        const tierBadge = c.size_tier === '250-500'
          ? 'bg-emerald-100 text-emerald-800 border-emerald-200'
          : (c.size_tier === '500-1000' ? 'bg-sky-100 text-sky-800 border-sky-200' : 'bg-purple-100 text-purple-800 border-purple-200');
        const cnt = c.counts || { pec: 0, other: 0, incomplete: 0, completed: 0 };

        return `
          <tr class="hover:bg-slate-50 transition">
            <td class="p-2.5">
              <input type="checkbox" class="mumbai-comp-cb rounded text-indigo-600 cursor-pointer" value="${c.id}">
            </td>
            <td class="p-2.5">
              <button onclick="openMumbaiTemplateEditor('${c.id}')" class="text-left font-bold text-indigo-700 hover:text-indigo-900 hover:underline flex items-center gap-1.5 cursor-pointer" title="Click to customize PEC & Other message templates for ${c.name}">
                <span>${c.name}</span>
                <i class="fa-solid fa-pen-to-square text-[10px] text-indigo-400"></i>
              </button>
            </td>
            <td class="p-2.5">
              <span class="px-2 py-0.5 rounded-full text-[10px] font-bold border ${tierBadge}">${c.size_tier} (~${c.employee_count})</span>
            </td>
            <td class="p-2.5 text-slate-500">${c.industry || 'Corporate'}</td>
            <td class="p-2.5 whitespace-nowrap">
              <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-100 text-amber-800">${cnt.pec} PEC</span>
              <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-100 text-slate-700 ml-1">${cnt.other} Other</span>
            </td>
            <td class="p-2.5 whitespace-nowrap">
              <span class="text-[11px] font-semibold text-rose-600">${cnt.incomplete} Pending</span>
              <span class="text-slate-300 mx-1">/</span>
              <span class="text-[11px] font-semibold text-teal-600">${cnt.completed} Done</span>
            </td>
            <td class="p-2.5 text-right whitespace-nowrap">
              <button onclick="openMumbaiTemplateEditor('${c.id}')" class="px-2.5 py-1 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 rounded-lg text-[11px] font-semibold mr-1 cursor-pointer">
                Templates
              </button>
              <button onclick="generateContactsSingleCompany('${c.id}')" class="px-2.5 py-1 bg-teal-600 hover:bg-teal-500 text-white rounded-lg text-[11px] font-semibold cursor-pointer">
                Find Contacts
              </button>
            </td>
          </tr>
        `;
      }).join('');
    }

    function toggleAllMumbaiCompanies(master) {
      document.querySelectorAll('.mumbai-comp-cb').forEach(cb => cb.checked = master.checked);
    }

    function openMumbaiTemplateEditor(companyId) {
      if (!mumbaiWorkspaceData) return;
      const comp = (mumbaiWorkspaceData.companies || []).find(c => String(c.id) === String(companyId));
      if (!comp) return;

      document.getElementById('tmplEditorCompanyId').value = comp.id;
      document.getElementById('tmplEditorCompanyName').innerText = `${comp.name} (${comp.size_tier})`;
      document.getElementById('tmplEditorPec').value = comp.pec_template || '';
      document.getElementById('tmplEditorOther').value = comp.other_template || '';
      const card = document.getElementById('mumbaiTemplateEditorCard');
      card.classList.remove('hidden');
      card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function closeMumbaiTemplateEditor() {
      document.getElementById('mumbaiTemplateEditorCard').classList.add('hidden');
    }

    async function saveMumbaiCompanyTemplates() {
      const companyId = document.getElementById('tmplEditorCompanyId').value;
      const pecTemplate = document.getElementById('tmplEditorPec').value;
      const otherTemplate = document.getElementById('tmplEditorOther').value;

      try {
        const res = await fetch('/api/mumbai/companies/templates', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ company_id: companyId, pec_template: pecTemplate, other_template: otherTemplate })
        });
        const d = await res.json();
        if (d.success) {
          alert('Saved custom PEC & Other templates for this company!');
          loadMumbaiWorkspace();
        } else {
          alert('Error: ' + (d.error || 'Failed to save templates'));
        }
      } catch (e) {
        alert('Network error: ' + e);
      }
    }

    async function generateMumbaiCompanies() {
      const btn = document.getElementById('btnGenMumbaiCompanies');
      if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generating...'; }
      try {
        const res = await fetch('/api/mumbai/companies/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ try_live_linkedin: true }) });
        const d = await res.json();
        alert(d.message || 'Mumbai company generation started in background! Check Live Terminal or wait a few seconds.');
        loadMumbaiWorkspace();
      } catch (e) {
        alert('Error: ' + e);
      } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Mumbai Companies (By Size)'; }
      }
    }

    async function addCustomMumbaiCompany() {
      const name = document.getElementById('customMumbaiCompanyName').value.trim();
      const sizeTier = document.getElementById('customMumbaiCompanySize').value;
      if (!name) { alert('Please enter a company name (e.g. JP Morgan).'); return; }
      try {
        const res = await fetch('/api/mumbai/companies/add', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, size_tier: sizeTier })
        });
        const d = await res.json();
        if (d.success) {
          document.getElementById('customMumbaiCompanyName').value = '';
          loadMumbaiWorkspace();
          openMumbaiTemplateEditor(d.company.id);
        }
      } catch (e) {
        alert('Network error: ' + e);
      }
    }

    function _getSelectedMumbaiCompanyIds() {
      return Array.from(document.querySelectorAll('.mumbai-comp-cb:checked')).map(cb => cb.value);
    }

    async function generateContactsSingleCompany(companyId) {
      const kw = document.getElementById('mumbaiKeywordsInput').value;
      try {
        const res = await fetch('/api/mumbai/contacts/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ company_ids: [companyId], keywords: kw })
        });
        const d = await res.json();
        alert(d.message || 'Started extracting & segregating contacts (PEC vs Other) in background!');
        switchTab('terminal');
      } catch (e) { alert('Error: ' + e); }
    }

    async function generateMumbaiContacts() {
      const companyIds = _getSelectedMumbaiCompanyIds();
      const kw = document.getElementById('mumbaiKeywordsInput').value;
      try {
        const res = await fetch('/api/mumbai/contacts/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            company_ids: companyIds,
            keywords: kw,
            max_companies: 2,
            min_contacts_per_company: 30,
            limit_per_company: 45
          })
        });
        const d = await res.json();
        alert(d.message || '30+ contacts/company discovery started in background! Watch Live Terminal.');
        switchTab('terminal');
      } catch (e) { alert('Error: ' + e); }
    }

    async function runMumbaiOutreachCycle() {
      const companyIds = _getSelectedMumbaiCompanyIds();
      try {
        const res = await fetch('/api/mumbai/outreach/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            company_ids: companyIds,
            max_connects: 35,
            max_messages: 0,
            connect_only: true
          })
        });
        const d = await res.json();
        alert(d.message || 'Connection Request Maximization (No Messages) started in background!');
        switchTab('terminal');
      } catch (e) { alert('Error: ' + e); }
    }

    async function runMumbai2DayFollowup() {
      try {
        const res = await fetch('/api/mumbai/followup/check', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ min_age_days: 0, check_all_pending: true, send_immediately: false })
        });
        const d = await res.json();
        alert(d.message || 'Daily acceptance check started! Newly accepted contacts will move into Sending List (messages held until you click Send Messages).');
        switchTab('terminal');
      } catch (e) { alert('Error: ' + e); }
    }

    async function runMumbaiSendMessagesOnly() {
      const companyIds = _getSelectedMumbaiCompanyIds();
      if (!confirm('Have you verified/customized your per-company PEC & Other templates? This will send messages ONLY to accepted contacts currently in your Sending List.')) return;
      try {
        const res = await fetch('/api/mumbai/messages/send', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ company_ids: companyIds, max_messages: 35 })
        });
        const d = await res.json();
        alert(d.message || 'Sending List message dispatch started in background!');
        switchTab('terminal');
      } catch (e) { alert('Error: ' + e); }
    }

    async function runMumbaiFullSequence() {
      const companyIds = _getSelectedMumbaiCompanyIds();
      const kw = document.getElementById('mumbaiKeywordsInput').value;
      if (!confirm('Run sequential pipeline: (1) Find 30+ Contacts & Store List → (2) Maximize Connection Requests → (3) Check Accepted → (4) Send Customized Templates to Sending List?')) return;
      try {
        const res = await fetch('/api/mumbai/sequence/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            company_ids: companyIds,
            keywords: kw,
            max_companies: 2,
            min_contacts_per_company: 30,
            max_connects: 35,
            max_messages: 35,
            include_send_messages: true
          })
        });
        const d = await res.json();
        alert(d.message || d.error || 'Full Mumbai outreach sequence started in background!');
        switchTab('terminal');
      } catch (e) { alert('Error: ' + e); }
    }

    function switchMumbaiSubTab(sub) {
      currentMumbaiSubTab = sub;
      const styles = {
        pec: 'bg-amber-600 text-white',
        other: 'bg-sky-600 text-white',
        sending: 'bg-indigo-600 text-white',
        incomplete: 'bg-rose-600 text-white',
        completed: 'bg-teal-600 text-white',
        daily: 'bg-indigo-600 text-white'
      };
      ['pec', 'other', 'sending', 'incomplete', 'completed', 'daily'].forEach(k => {
        const btn = document.getElementById(`mSubTab-${k}`);
        if (btn) {
          btn.className = k === sub
            ? `px-3.5 py-1.5 rounded-xl text-xs font-bold cursor-pointer ${styles[k]}`
            : 'px-3.5 py-1.5 rounded-xl text-xs font-bold bg-slate-100 text-slate-700 hover:bg-slate-200 cursor-pointer';
        }
      });

      const isDaily = sub === 'daily';
      document.getElementById('mumbaiContactsTableWrap').classList.toggle('hidden', isDaily);
      document.getElementById('mumbaiDailyTableWrap').classList.toggle('hidden', !isDaily);
      renderMumbaiContactsSubTab();
    }

    function renderMumbaiContactsSubTab() {
      if (!mumbaiWorkspaceData) return;
      if (currentMumbaiSubTab === 'daily') {
        const dtbody = document.getElementById('mumbaiDailyTableBody');
        const hist = mumbaiWorkspaceData.daily_history || [];
        if (!hist.length) {
          dtbody.innerHTML = `<tr><td colspan="5" class="p-6 text-center text-slate-400">No daily activity logged yet.</td></tr>`;
          return;
        }
        dtbody.innerHTML = hist.map(r => `
          <tr class="hover:bg-slate-50">
            <td class="p-3 font-bold text-slate-800">${r.date}</td>
            <td class="p-3 font-bold text-indigo-600">${r.connections_sent || 0}</td>
            <td class="p-3 font-bold text-emerald-600">${r.messages_sent || 0}</td>
            <td class="p-3 font-bold text-amber-600">${r.acceptances_detected || 0}</td>
            <td class="p-3 font-bold text-teal-600">${r.completed_followups || 0}</td>
          </tr>
        `).join('');
        return;
      }

      const tbody = document.getElementById('mumbaiContactsTableBody');
      if (!tbody) return;

      let rows = [];
      if (currentMumbaiSubTab === 'pec') rows = mumbaiWorkspaceData.pec_contacts || [];
      else if (currentMumbaiSubTab === 'other') rows = mumbaiWorkspaceData.other_contacts || [];
      else if (currentMumbaiSubTab === 'sending') rows = mumbaiWorkspaceData.sending_list || [];
      else if (currentMumbaiSubTab === 'incomplete') rows = mumbaiWorkspaceData.incomplete || [];
      else if (currentMumbaiSubTab === 'completed') rows = mumbaiWorkspaceData.completed || [];

      if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="5" class="p-6 text-center text-slate-400">No contacts in this category yet.</td></tr>`;
        return;
      }

      tbody.innerHTML = rows.map(c => {
        const catBadge = c.is_pec_alumni
          ? '<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800">PEC Chandigarh</span>'
          : '<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-700">Other</span>';

        let stageBadge = '<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-600">Discovered</span>';
        if (c.workflow_stage === 'incomplete_pending_accept') {
          const days = c.days_pending ?? 0;
          stageBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-100 text-rose-700">Incomplete (Day ${days})</span><div class="text-[10px] text-slate-400 mt-0.5">Sent: ${c.connection_sent_at || '--'}</div>`;
        } else if (c.workflow_stage === 'sending_list') {
          stageBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-100 text-indigo-800">Sending List (Accepted ✓)</span><div class="text-[10px] text-slate-400 mt-0.5">Accepted: ${c.accepted_at || '--'}</div>`;
        } else if (c.workflow_stage === 'completed') {
          stageBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-teal-100 text-teal-800">Completed ✓</span><div class="text-[10px] text-slate-400 mt-0.5">Msg: ${c.messaged_at || '--'}</div>`;
        }

        const msgPreview = c.message_used
          ? `<div class="text-[11px] text-slate-600 max-w-xs truncate" title="${c.message_used}">${c.message_used}</div>`
          : `<span class="text-[11px] text-slate-400 italic">${c.connection_status === 'connected_ready' ? '1st Degree (Ready to Message)' : 'Will send invite/template'}</span>`;

        return `
          <tr class="hover:bg-slate-50 transition">
            <td class="p-3">
              <div class="font-bold text-slate-900">${c.name}</div>
              <div class="text-[11px] text-slate-500 max-w-xs truncate" title="${c.headline}">${c.headline || ''}</div>
            </td>
            <td class="p-3">
              <div class="font-semibold text-indigo-700">${c.company_name}</div>
              <div class="text-[10px] text-slate-400">${c.size_tier || ''}</div>
            </td>
            <td class="p-3">
              ${catBadge}
              <div class="mt-1"><span class="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 text-[10px] font-semibold">${c.matched_keyword || 'Target'}</span></div>
            </td>
            <td class="p-3">${stageBadge}</td>
            <td class="p-3">
              ${msgPreview}
              <a href="${c.profile_url}" target="_blank" class="inline-flex items-center gap-1 text-[11px] text-blue-600 font-semibold hover:underline mt-1">
                <i class="fa-brands fa-linkedin"></i> View Profile ↗
              </a>
            </td>
          </tr>
        `;
      }).join('');
    }

    // Smart Load-Managed Polling: Stats + Logs when active; only refresh currently visible tab
    setInterval(pollDashboardData, 4000);
    setInterval(() => {
      if (activeTab === 'terminal') pollLogs();
    }, 2000);
    setInterval(() => {
      refreshTabView(activeTab);
    }, 6000);

    // Initial Boot Fetch
    pollDashboardData();
    pollLogs();
    loadManualTable();
    loadGmailIntel();
    loadFeedPosts();
    loadEasyApplyJobs();
    loadRecruiterLeads();
    loadNaukriApplied();
    loadMumbaiWorkspace();
    loadOutreachHistory();
    loadTemplates();
    loadResumeStatus();
    loadDispatches();
  </script>
  <!-- LinkedIn Session Auth Modal -->
  <div id="sessionModal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="bg-white rounded-3xl max-w-lg w-full shadow-2xl border border-slate-200 overflow-hidden">
      <div class="px-6 py-5 bg-slate-50 border-b border-slate-100 flex items-center justify-between">
        <div class="flex items-center gap-2.5">
          <div class="w-8 h-8 rounded-xl bg-blue-100 text-blue-700 flex items-center justify-center">
            <i class="fa-brands fa-linkedin text-base"></i>
          </div>
          <div>
            <h3 class="font-bold text-slate-900 text-sm">LinkedIn Session Authentication</h3>
            <p class="text-xs text-slate-500">Cloud & Local Headless Authentication</p>
          </div>
        </div>
        <button onclick="closeSessionModal()" class="text-slate-400 hover:text-slate-700 p-1.5 rounded-lg cursor-pointer">
          <i class="fa-solid fa-xmark text-sm"></i>
        </button>
      </div>

      <div class="p-6 space-y-4">
        <div class="p-3.5 bg-emerald-50 border border-emerald-200 rounded-2xl text-xs text-emerald-900 flex items-center justify-between gap-3">
          <div>
            <div class="font-bold">Option 1 (Fastest on Mac): Sign in with Chrome</div>
            <p class="text-[11px] text-emerald-700">Opens a visible Chrome login window and auto-saves your verified LinkedIn session once you sign in.</p>
          </div>
          <button onclick="launchLinkedInLogin()" id="btnLaunchLoginBrowser" class="px-3.5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-xl shadow-sm whitespace-nowrap flex items-center gap-1.5 cursor-pointer">
            <i class="fa-brands fa-chrome"></i>
            <span>Open Chrome Sign-In Window</span>
          </button>
        </div>

        <div class="p-3.5 bg-blue-50 border border-blue-200 rounded-2xl text-xs text-blue-800 space-y-1">
          <div class="font-bold flex items-center gap-1.5">
            <i class="fa-solid fa-circle-info"></i> Option 2: Paste your li_at cookie manually:
          </div>
          <ol class="list-decimal list-inside space-y-0.5 text-blue-700 text-[11px] pl-1">
            <li>Open <a href="https://www.linkedin.com" target="_blank" class="underline font-semibold">LinkedIn.com</a> in your browser.</li>
            <li>Press <strong>F12</strong> (or Right-click &gt; <em>Inspect</em>), switch to <strong>Application</strong> (or <em>Storage</em>).</li>
            <li>Click <strong>Cookies</strong> &gt; <code>https://www.linkedin.com</code>, copy value of <strong><code>li_at</code></strong>.</li>
          </ol>
        </div>

        <div>
          <label class="block text-xs font-bold text-slate-700 mb-1.5">Paste li_at Cookie String</label>
          <textarea id="inputLiAt" rows="3" placeholder="AQEDAUC..." class="w-full text-xs font-mono p-3 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:outline-none"></textarea>
        </div>

        <div class="flex items-center justify-between pt-2">
          <button onclick="closeSessionModal()" class="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-xl transition cursor-pointer">
            Cancel
          </button>
          <button onclick="submitSessionCookie()" id="btnSaveCookie" class="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold rounded-xl shadow-md shadow-blue-600/30 flex items-center gap-1.5 transition cursor-pointer">
            <i class="fa-solid fa-cloud-arrow-up"></i>
            <span>Verify, Save &amp; Sync to Render</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(MERAKI_UI_HTML)


@app.route("/api/stats")
def stats():
    return jsonify(get_stats())


@app.route("/api/logs")
def logs():
    return jsonify({"logs": LIVE_LOGS[-100:]})


@app.route("/api/manual_queue")
def manual_queue():
    return jsonify({"queue": load_manual_queue()})


@app.route("/api/naukri_applied")
def api_naukri_applied():
    applied = []
    if os.path.exists(NAUKRI_APPLIED_CSV):
        try:
            with open(NAUKRI_APPLIED_CSV, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    applied.append(row)
        except Exception as e:
            logger.error(f"Error reading {NAUKRI_APPLIED_CSV}: {e}")
    return jsonify({"jobs": list(reversed(applied)), "count": len(applied)})


@app.route("/api/outreach_tracker")
def outreach_tracker():
    engine = ReferralEngine()
    return jsonify({"history": engine.get_history()})


@app.route("/api/inbox_intel")
def inbox_intel():
    tracker = EmailTracker()
    return jsonify({"intel": tracker.get_saved_intel()})


@app.route("/api/screening_passed")
def screening_passed():
    tracker = EmailTracker()
    return jsonify({"opportunities": tracker.get_screening_passed()})


@app.route("/api/feed_posts")
def feed_posts_route():
    res = sync_leads()
    return jsonify({"posts": res.get("feed_posts", [])})


@app.route("/api/feed_posts/remove", methods=["POST"])
def remove_feed_post_route():
    data = request.json or {}
    form_id = data.get("id")
    form_url = data.get("form_url")
    if not form_id and not form_url:
        return jsonify({"success": False, "error": "Missing form id or url"}), 400
    dismiss_pending_form(form_id=form_id, form_url=form_url)
    res = sync_leads()
    add_log(f"🗑️ Feed post {form_id or form_url} removed from desk.")
    return jsonify({"success": True, "remaining_count": len(res.get("feed_posts", []))})


@app.route("/api/feed_posts/clear_all", methods=["POST"])
def clear_all_feed_posts_route():
    cleared = clear_all_pending_forms()
    add_log(f"🗑️ Cleared all {cleared} feed posts from desk.")
    return jsonify({"success": True, "cleared_count": cleared})


@app.route("/api/feed_posts/delete_batch", methods=["POST"])
def delete_feed_posts_batch_route():
    data = request.json or {}
    ids = data.get("ids", [])
    if not ids:
        return jsonify({"success": False, "error": "No IDs provided"}), 400
    removed = dismiss_pending_forms_batch(ids)
    res = sync_leads()
    add_log(f"🗑️ Removed {removed} selected feed posts from desk.")
    return jsonify({"success": True, "removed_count": removed, "remaining_count": len(res.get("feed_posts", []))})


@app.route("/api/easy_apply_jobs")
def easy_apply_jobs_route():
    res = sync_leads()
    return jsonify({"jobs": res.get("easy_apply_jobs", [])})


@app.route("/api/easy_apply_jobs/remove", methods=["POST"])
def remove_easy_apply_job_route():
    data = request.json or {}
    job_id = data.get("id")
    job_url = data.get("job_url")
    if not job_id and not job_url:
        return jsonify({"success": False, "error": "Missing job id or url"}), 400
    dismiss_easy_apply_job(job_id=job_id, job_url=job_url)
    res = sync_leads()
    add_log(f"🗑️ Easy Apply job {job_id or job_url} removed from desk.")
    return jsonify({"success": True, "remaining_count": len(res.get("easy_apply_jobs", []))})


@app.route("/api/easy_apply_jobs/clear_all", methods=["POST"])
def clear_all_easy_apply_jobs_route():
    cleared = clear_all_easy_apply()
    add_log(f"🗑️ Cleared all {cleared} Easy Apply jobs from desk.")
    return jsonify({"success": True, "cleared_count": cleared})


@app.route("/api/easy_apply_jobs/delete_batch", methods=["POST"])
def delete_easy_apply_batch_route():
    data = request.json or {}
    ids = data.get("ids", [])
    if not ids:
        return jsonify({"success": False, "error": "No IDs provided"}), 400
    removed = dismiss_easy_apply_batch(ids)
    res = sync_leads()
    add_log(f"🗑️ Removed {removed} selected Easy Apply jobs from desk.")
    return jsonify({"success": True, "removed_count": removed, "remaining_count": len(res.get("easy_apply_jobs", []))})


@app.route("/api/pending_forms")
def pending_forms():
    res = sync_leads()
    return jsonify({"forms": res.get("forms", [])})


@app.route("/api/pending_forms/remove", methods=["POST"])
def remove_pending_form_route():
    data = request.json or {}
    form_id = data.get("id")
    form_url = data.get("form_url")
    if not form_id and not form_url:
        return jsonify({"success": False, "error": "Missing form id or url"}), 400
    dismiss_pending_form(form_id=form_id, form_url=form_url)
    res = sync_leads()
    add_log(f"🗑️ Application form {form_id or form_url} removed from pending desk.")
    return jsonify({"success": True, "remaining_count": len(res.get("forms", []))})


@app.route("/api/pending_forms/clear_all", methods=["POST"])
def clear_all_pending_forms_route():
    cleared = clear_all_pending_forms()
    add_log(f"🗑️ Cleared all {cleared} pending application forms from desk.")
    return jsonify({"success": True, "cleared_count": cleared})


@app.route("/api/pending_forms/delete_batch", methods=["POST"])
def delete_pending_forms_batch_route():
    data = request.json or {}
    ids = data.get("ids", [])
    if not ids:
        return jsonify({"success": False, "error": "No IDs provided"}), 400
    removed = dismiss_pending_forms_batch(ids)
    res = sync_leads()
    add_log(f"🗑️ Removed {removed} selected application forms from desk.")
    return jsonify({"success": True, "removed_count": removed, "remaining_count": len(res.get("forms", []))})


@app.route("/api/recruiter_leads")
def recruiter_leads():
    res = sync_leads()
    return jsonify({"emails": res.get("emails", [])})


@app.route("/api/recruiter_leads/remove", methods=["POST"])
def remove_recruiter_lead_route():
    data = request.json or {}
    lead_id = data.get("id")
    email = data.get("email")
    if not lead_id and not email:
        return jsonify({"success": False, "error": "Missing lead id or email"}), 400
    dismiss_recruiter_lead(lead_id=lead_id, email=email)
    res = sync_leads()
    add_log(f"🗑️ Recruiter lead {lead_id or email} removed from desk.")
    return jsonify({"success": True, "remaining_count": len(res.get("emails", []))})


@app.route("/api/recruiter_leads/delete_batch", methods=["POST"])
def delete_recruiter_leads_batch_route():
    data = request.json or {}
    ids = data.get("ids", [])
    if not ids:
        return jsonify({"success": False, "error": "No IDs provided"}), 400
    removed = dismiss_recruiter_leads_batch(ids)
    res = sync_leads()
    add_log(f"🗑️ Removed {removed} selected recruiter leads from desk.")
    return jsonify({"success": True, "removed_count": removed, "remaining_count": len(res.get("emails", []))})


@app.route("/api/crawl_company", methods=["POST"])
def crawl_company():
    data = request.json or {}
    company = data.get("company", "Swiggy")
    role = data.get("role", "Product Manager")
    prioritize_alumni = data.get("prioritize_alumni", True)
    limit = int(data.get("limit", 15))

    engine = ReferralEngine()
    people = engine.search_company_people(
        company=company,
        role=role,
        prioritize_alumni=prioritize_alumni,
        limit=limit
    )
    return jsonify({"people": people})


@app.route("/api/send_alumni_batch", methods=["POST"])
def send_alumni_batch():
    data = request.json or {}
    people = data.get("people", [])
    alumni_tmpl = data.get("alumni_template", "")
    connect_tmpl = data.get("connect_template", "")
    sender_name = data.get("sender_name", "Ashutosh Bajpai")

    engine = ReferralEngine()
    results = engine.send_outreach_batch(
        people=people,
        connect_template=connect_tmpl,
        message_template=connect_tmpl,
        alumni_template=alumni_tmpl,
        sender_name=sender_name
    )
    return jsonify({"results": results})


@app.route("/api/templates", methods=["GET", "POST"])
def handle_templates():
    if request.method == "POST":
        data = request.json or {}
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if "templates" not in cfg:
                cfg["templates"] = {}
            if "referral_template" in data:
                cfg["templates"]["referral_template"] = data["referral_template"]
            if "alumni_template" in data:
                cfg["templates"]["alumni_template"] = data["alumni_template"]
            if "recruiter_template" in data:
                cfg["templates"]["recruiter_template"] = data["recruiter_template"]
            if "resume_dispatch_template" in data:
                cfg["templates"]["resume_dispatch_template"] = data["resume_dispatch_template"]
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            add_log("SUCCESS: Saved custom message templates permanently in config.json")
            return jsonify({"status": "Success", "message": "Templates saved successfully"})
        except Exception as e:
            return jsonify({"status": "Error", "message": str(e)}), 500
    else:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return jsonify({"templates": cfg.get("templates", {})})
        except Exception as e:
            return jsonify({"templates": {}}), 500


@app.route("/api/resume_status")
def resume_status():
    cfg_resume = ""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            cfg_resume = cfg.get("candidate_profile", {}).get("resume_path", "")
    except Exception:
        pass

    if cfg_resume and os.path.exists(cfg_resume):
        size_kb = round(os.path.getsize(cfg_resume) / 1024.0, 1)
        mod_time = datetime.fromtimestamp(os.path.getmtime(cfg_resume)).strftime("%b %d, %Y %H:%M")
        return jsonify({
            "exists": True,
            "filename": os.path.basename(cfg_resume),
            "path": cfg_resume,
            "size_kb": size_kb,
            "modified": mod_time,
            "naukri_synced": True
        })
    return jsonify({
        "exists": False,
        "filename": "No resume found",
        "path": "",
        "size_kb": 0,
        "modified": "--",
        "naukri_synced": False
    })


@app.route("/api/upload_resume", methods=["POST"])
def upload_resume_route():
    if "resume" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["resume"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    filename = secure_filename(file.filename)
    resumes_dir = os.path.join(DATA_DIR, "resumes")
    os.makedirs(resumes_dir, exist_ok=True)
    target_path = os.path.join(resumes_dir, filename)
    file.save(target_path)

    # Update config.json
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["candidate_profile"]["resume_path"] = target_path
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logger.error(f"Error updating config.json: {e}")

    sync_naukri = request.form.get("sync_naukri") == "true"
    naukri_msg = "Not requested"
    if sync_naukri:
        if CURRENT_TASK["running"]:
            naukri_msg = f"Task '{CURRENT_TASK['name']}' currently running. Resume saved; Naukri sync will trigger when idle."
            add_log(f"NOTICE: Resume '{filename}' saved. Naukri sync deferred because '{CURRENT_TASK['name']}' is running.")
        else:
            try:
                naukri = NaukriAutomator()
                res = naukri.upload_resume(target_path)
                naukri_msg = res.get("message", "Uploaded to Naukri")
                add_log(f"SUCCESS: Synced new resume '{filename}' to Naukri.com")
            except Exception as e:
                naukri_msg = f"Naukri sync notice: {e}"
                add_log(f"NOTICE: Naukri resume upload notice: {e}")

    add_log(f"SUCCESS: Uploaded and set active master resume: {filename}")
    return jsonify({
        "success": True,
        "filename": filename,
        "path": target_path,
        "naukri_message": naukri_msg
    })


@app.route("/api/dispatches")
def dispatches_route():
    engine = ReferralEngine()
    return jsonify({"dispatches": engine.get_dispatches()})


# ==============================================================================
# MUMBAI NETWORK & 2-DAY FOLLOW-UP API ROUTES
# ==============================================================================
@app.route("/api/mumbai/summary")
def mumbai_summary_route():
    engine = MumbaiOutreachEngine()
    return jsonify(engine.get_workspace_summary())


@app.route("/api/mumbai/companies/generate", methods=["POST"])
def mumbai_generate_companies_route():
    data = request.json or {}
    try_live = data.get("try_live_linkedin", True)
    if CURRENT_TASK["running"] and try_live:
        # Still merge curated instantaneously if background browser is busy
        engine = MumbaiOutreachEngine()
        res = engine.generate_mumbai_companies(try_live_linkedin=False, log_cb=add_log)
        return jsonify({"success": True, "message": "Merged Mumbai companies directory (250-500 -> 500-1000 -> 1000+).", **res})

    def _run():
        global CURRENT_TASK
        CURRENT_TASK["running"] = True
        CURRENT_TASK["name"] = "Mumbai Companies Discovery"
        CURRENT_TASK["started_at"] = datetime.now(IST).strftime("%H:%M:%S")
        try:
            engine = MumbaiOutreachEngine()
            engine.generate_mumbai_companies(try_live_linkedin=try_live, log_cb=add_log)
        except Exception as e:
            add_log(f"ERROR in Mumbai company generation: {e}")
        finally:
            CURRENT_TASK["running"] = False
            CURRENT_TASK["name"] = "Idle"
            CURRENT_TASK["started_at"] = None

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"success": True, "message": "Started Mumbai Companies generation (250-500 → 500-1000 → 1000+) in background."})


@app.route("/api/mumbai/companies/add", methods=["POST"])
def mumbai_add_company_route():
    data = request.json or {}
    name = data.get("name", "").strip()
    size_tier = data.get("size_tier", "1000+")
    if not name:
        return jsonify({"success": False, "error": "Company name is required"}), 400
    engine = MumbaiOutreachEngine()
    comp = engine.add_custom_company(name=name, size_tier=size_tier, industry=data.get("industry", "Corporate / Fintech"))
    add_log(f"➕ Added Mumbai company '{comp['name']}' ({comp['size_tier']} tier).")
    return jsonify({"success": True, "company": comp})


@app.route("/api/mumbai/companies/templates", methods=["POST"])
def mumbai_save_templates_route():
    data = request.json or {}
    company_id = data.get("company_id")
    pec_template = data.get("pec_template")
    other_template = data.get("other_template")
    if not company_id:
        return jsonify({"success": False, "error": "Missing company_id"}), 400
    engine = MumbaiOutreachEngine()
    updated = engine.update_company_templates(company_id, pec_template, other_template)
    if not updated:
        return jsonify({"success": False, "error": "Company not found"}), 404
    add_log(f"💾 Saved custom PEC Alumni & Other templates for '{updated['name']}'.")
    return jsonify({"success": True, "company": updated})


@app.route("/api/mumbai/contacts/generate", methods=["POST"])
def mumbai_generate_contacts_route():
    if CURRENT_TASK["running"]:
        return jsonify({"success": False, "error": f"Task '{CURRENT_TASK['name']}' is currently running."}), 400

    data = request.json or {}
    company_ids = data.get("company_ids", [])
    raw_kw = data.get("keywords", "Founder's Office, HR, Talent, Product, Analyst")
    keywords = [k.strip() for k in raw_kw.split(",") if k.strip()] if isinstance(raw_kw, str) else raw_kw
    max_companies = int(data.get("max_companies", 5))
    min_contacts_per_company = int(data.get("min_contacts_per_company", 30))
    limit_per_company = int(data.get("limit_per_company", 45))

    def _run():
        global CURRENT_TASK
        CURRENT_TASK["running"] = True
        CURRENT_TASK["name"] = "Mumbai Contacts (30+/Co) Extraction"
        CURRENT_TASK["started_at"] = datetime.now(IST).strftime("%H:%M:%S")
        try:
            engine = MumbaiOutreachEngine()
            engine.generate_contacts_for_companies(
                company_ids=company_ids or None,
                keywords=keywords,
                max_companies=max_companies,
                min_contacts_per_company=min_contacts_per_company,
                limit_per_company=limit_per_company,
                log_cb=add_log
            )
        except Exception as e:
            add_log(f"ERROR extracting Mumbai company contacts: {e}")
        finally:
            CURRENT_TASK["running"] = False
            CURRENT_TASK["name"] = "Idle"
            CURRENT_TASK["started_at"] = None

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"success": True, "message": "Started 30+ Contacts/Company LinkedIn discovery & PEC/Other segregation in background!"})


@app.route("/api/mumbai/outreach/run", methods=["POST"])
def mumbai_run_outreach_route():
    if CURRENT_TASK["running"]:
        return jsonify({"success": False, "error": f"Task '{CURRENT_TASK['name']}' is currently running."}), 400

    data = request.json or {}
    company_ids = data.get("company_ids", [])
    contact_ids = data.get("contact_ids", [])
    max_connects = int(data.get("max_connects", 35))
    max_messages = int(data.get("max_messages", 0))
    connect_only = bool(data.get("connect_only", True))

    def _run():
        global CURRENT_TASK
        CURRENT_TASK["running"] = True
        CURRENT_TASK["name"] = "Mumbai Connection Maximization (No Msg)" if connect_only else "Mumbai Connect & Outreach Cycle"
        CURRENT_TASK["started_at"] = datetime.now(IST).strftime("%H:%M:%S")
        try:
            engine = MumbaiOutreachEngine()
            engine.run_connect_and_message_cycle(
                company_ids=company_ids or None,
                contact_ids=contact_ids or None,
                max_connects=max_connects,
                max_messages=max_messages,
                connect_only=connect_only,
                log_cb=add_log
            )
        except Exception as e:
            add_log(f"ERROR in Mumbai connect cycle: {e}")
        finally:
            CURRENT_TASK["running"] = False
            CURRENT_TASK["name"] = "Idle"
            CURRENT_TASK["started_at"] = None

    threading.Thread(target=_run, daemon=True).start()
    msg = (
        "Started Connection Request Maximization ONLY (no messages sent; 1st-degree contacts queued in Sending List)!"
        if connect_only else
        "Started Connection Maximization & 1st-Degree Messaging cycle in background!"
    )
    return jsonify({"success": True, "message": msg})


@app.route("/api/mumbai/messages/send", methods=["POST"])
def mumbai_send_messages_route():
    if CURRENT_TASK["running"]:
        return jsonify({"success": False, "error": f"Task '{CURRENT_TASK['name']}' is currently running."}), 400

    data = request.json or {}
    company_ids = data.get("company_ids", [])
    contact_ids = data.get("contact_ids", [])
    max_messages = int(data.get("max_messages", 35))

    def _run():
        global CURRENT_TASK
        CURRENT_TASK["running"] = True
        CURRENT_TASK["name"] = "Mumbai Sending List Dispatch"
        CURRENT_TASK["started_at"] = datetime.now(IST).strftime("%H:%M:%S")
        try:
            engine = MumbaiOutreachEngine()
            engine.run_send_messages_only(
                company_ids=company_ids or None,
                contact_ids=contact_ids or None,
                max_messages=max_messages,
                log_cb=add_log
            )
        except Exception as e:
            add_log(f"ERROR sending Mumbai Sending List messages: {e}")
        finally:
            CURRENT_TASK["running"] = False
            CURRENT_TASK["name"] = "Idle"
            CURRENT_TASK["started_at"] = None

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"success": True, "message": "Started sending customized PEC/Other messages to accepted contacts in Sending List!"})


@app.route("/api/mumbai/followup/check", methods=["POST"])
def mumbai_followup_check_route():
    if CURRENT_TASK["running"]:
        return jsonify({"success": False, "error": f"Task '{CURRENT_TASK['name']}' is currently running."}), 400

    data = request.json or {}
    min_age_days = int(data.get("min_age_days", 0))
    check_all_pending = bool(data.get("check_all_pending", True))
    send_immediately = bool(data.get("send_immediately", False))

    def _run():
        global CURRENT_TASK
        CURRENT_TASK["running"] = True
        CURRENT_TASK["name"] = "Daily Acceptance Check → Sending List"
        CURRENT_TASK["started_at"] = datetime.now(IST).strftime("%H:%M:%S")
        try:
            engine = MumbaiOutreachEngine()
            engine.run_daily_acceptance_and_send(
                min_age_days=min_age_days,
                check_all_pending=check_all_pending,
                send_immediately=send_immediately,
                log_cb=add_log
            )
        except Exception as e:
            add_log(f"ERROR in daily acceptance follow-up check: {e}")
        finally:
            CURRENT_TASK["running"] = False
            CURRENT_TASK["name"] = "Idle"
            CURRENT_TASK["started_at"] = None

    threading.Thread(target=_run, daemon=True).start()
    msg = (
        "Started Daily Check: promoting all accepted connections into Sending List (messages held until you click Send Messages)!"
        if not send_immediately else
        "Started Daily Check for all accepted connections -> Sending List & Message!"
    )
    return jsonify({"success": True, "message": msg})


@app.route("/api/mumbai/sequence/run", methods=["POST"])
def mumbai_run_sequence_route():
    with TASK_LOCK:
        if CURRENT_TASK["running"]:
            return jsonify({"success": False, "error": f"Task '{CURRENT_TASK['name']}' is currently running."}), 400
        CURRENT_TASK["running"] = True
        CURRENT_TASK["name"] = "Mumbai Full Outreach Sequence"
        CURRENT_TASK["started_at"] = datetime.now(IST).strftime("%H:%M:%S")

    data = request.json or {}
    company_ids = data.get("company_ids", [])
    raw_kw = data.get("keywords", "Founder's Office, HR, Talent, Product, Analyst")
    keywords = [k.strip() for k in raw_kw.split(",") if k.strip()] if isinstance(raw_kw, str) else raw_kw
    max_companies = int(data.get("max_companies", 2))
    min_contacts_per_company = int(data.get("min_contacts_per_company", 30))
    max_connects = int(data.get("max_connects", 35))
    max_messages = int(data.get("max_messages", 35))
    include_send_messages = bool(data.get("include_send_messages", True))

    def _run():
        try:
            engine = MumbaiOutreachEngine()
            engine.run_full_pipeline_sequence(
                company_ids=company_ids or None,
                keywords=keywords,
                max_companies=max_companies,
                min_contacts_per_company=min_contacts_per_company,
                max_connects=max_connects,
                max_messages=max_messages,
                include_send_messages=include_send_messages,
                log_cb=add_log,
            )
        except Exception as e:
            add_log(f"ERROR in Mumbai sequential pipeline: {e}")
        finally:
            import gc
            gc.collect()
            with TASK_LOCK:
                CURRENT_TASK["running"] = False
                CURRENT_TASK["name"] = "Idle"
                CURRENT_TASK["started_at"] = None

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"success": True, "message": "Started Mumbai Sequential Pipeline: 30+ Contacts → Maximize Connects → Sending List → Send Messages!"})


def load_json_file(filepath: str, default: dict) -> dict:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default

def save_json_file(filepath: str, data: dict):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


@app.route("/api/reset_task", methods=["POST"])
def reset_task():
    with TASK_LOCK:
        TASK_QUEUE.clear()
        CURRENT_TASK["running"] = False
        CURRENT_TASK["name"] = "Idle"
        CURRENT_TASK["started_at"] = None
        CURRENT_TASK["queued"] = []
    add_log("SYSTEM: Task execution lock & queue forcibly reset to Idle.")
    return jsonify({"status": "success", "message": "Task lock and queue reset to Idle."})


@app.route("/api/launch_linkedin_login", methods=["POST"])
def launch_linkedin_login_route():
    if os.environ.get("RENDER"):
        return jsonify({
            "success": False,
            "error": "Interactive Chrome sign-in only runs on your local Mac dashboard (http://127.0.0.1:5055). On Render, paste your li_at cookie instead."
        }), 400
    import subprocess
    import sys
    script_path = os.path.join(BASE_DIR, "login_once.py")
    try:
        subprocess.Popen([sys.executable, script_path], cwd=BASE_DIR)
        add_log("🌐 Opened visible Chrome window for LinkedIn sign-in (login_once.py). Complete login there to auto-sync session!")
        return jsonify({
            "success": True,
            "message": "Chrome LinkedIn Login window opened on your Mac! Please sign in there — once you reach LinkedIn Feed, your session will auto-save and sync to Render."
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Could not launch Chrome login helper: {e}"}), 500


@app.route("/api/update_cookies", methods=["POST"])
def update_cookies_route():
    data = request.json or {}
    li_at_val = (data.get("li_at") or "").strip().strip('"').strip("'").rstrip(";")
    if li_at_val.lower().startswith("li_at="):
        li_at_val = li_at_val.split("=", 1)[1].strip().strip('"').strip("'").rstrip(";")
    if not li_at_val:
        return jsonify({"success": False, "error": "No li_at cookie value provided."}), 400

    # Verify live against LinkedIn before saving so expired/typo strings aren't accepted
    if not BrowserManager.probe_li_at_valid(li_at_val):
        return jsonify({
            "success": False,
            "error": "That li_at cookie is expired or invalid (LinkedIn redirected /feed to login). Please copy a fresh li_at cookie from an active LinkedIn session or use 'Open Chrome Sign-In Window'."
        }), 400

    session_file = os.path.join(DATA_DIR, "session_cookies.json")
    cookies = []
    if os.path.exists(session_file):
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                cookies = json.load(f).get("cookies", [])
        except Exception:
            cookies = []

    # Remove stale mismatched LinkedIn cookies (e.g. old JSESSIONID/liap from earlier sessions)
    # while preserving Naukri/Google cookies, then store the single fresh .linkedin.com li_at.
    cookies = [c for c in cookies if "linkedin" not in (c.get("domain") or "").lower()]
    cookies.append({
        "name": "li_at",
        "value": li_at_val,
        "domain": ".linkedin.com",
        "path": "/",
        "expires": time.time() + (365 * 24 * 3600),
        "httpOnly": True,
        "secure": True,
        "sameSite": "None"
    })

    payload = {
        "status": "active",
        "exported_at": datetime.now(IST).strftime("%a %b %d %H:%M:%S IST %Y"),
        "cookies": cookies
    }
    payload_str = json.dumps(payload, indent=2)
    save_json_file(session_file, payload)

    # Sync to Render cloud environment variable
    import base64
    import requests
    b64_val = base64.b64encode(payload_str.encode("utf-8")).decode("utf-8")
    try:
        url = "https://api.render.com/v1/services/srv-dblnjm6c6qcc73bpkv70/env-vars/SESSION_COOKIES_BASE64"
        headers = {
            "Authorization": "Bearer rnd_V7GNSF2DNymcat6NZAAz8ONRbGkh",
            "Content-Type": "application/json"
        }
        res = requests.put(url, headers=headers, json={"value": b64_val}, timeout=10)
        logger.info(f"Pushed updated session cookies to Render: status {res.status_code}")
    except Exception as e:
        logger.warning(f"Could not push updated cookies to Render env var: {e}")

    add_log("🔑 SUCCESS: LinkedIn authentication session cookie (li_at) updated and synced to cloud deployment!")
    return jsonify({"success": True, "message": "LinkedIn li_at cookie successfully updated and synced to Render!"})


def execute_task(task_type):
    CURRENT_TASK["running"] = True
    CURRENT_TASK["name"] = task_type
    CURRENT_TASK["started_at"] = datetime.now(IST).strftime("%H:%M:%S")

    task_failed = False
    try:
        if task_type == "run_all":
            cloud_mode = is_cloud_low_mem()
            add_log(f"🚀 MASTER AUTOPILOT ACTIVATED ({'Cloud 512MB Safe Load Mode' if cloud_mode else 'Local Mode'}): Running sequential steps with RAM cooldown guards...")
            wait_for_ram_cooldown(soft_limit_mb=350.0, max_wait_sec=6.0, log_cb=add_log)

            def _cloud_headroom_ok(step_label: str) -> bool:
                ram = wait_for_ram_cooldown(soft_limit_mb=350.0, max_wait_sec=6.0, log_cb=add_log)
                if cloud_mode and ram > 430.0:
                    add_log(f"⚠️ [LOAD MANAGER] RAM at {ram} MB (>430 MB safety ceiling). Deferring '{step_label}' cleanly to protect Render 512MB stability.")
                    return False
                return True

            # 1. Naukri Recency Boost
            add_log("[1/6] Launching Naukri Daily Recency Boost ('Updated: Today')...")
            try:
                naukri = NaukriAutomator()
                res_boost = naukri.boost_profile()
                add_log(f"✅ [1/6] Naukri Boost completed: {res_boost.get('status')}")
            except Exception as e:
                add_log(f"⚠️ [1/6] Naukri Boost notice: {e}")

            # 2. Naukri Mass Apply (Scaled cleanly on 512MB Cloud)
            naukri_target = 15 if cloud_mode else 50
            naukri_pages = 2 if cloud_mode else 5
            if _cloud_headroom_ok("[2/6] Naukri Mass Apply"):
                add_log(f"[2/6] Launching Naukri Mass Apply (Target: {naukri_target}, Pages/Role: {naukri_pages})...")
                try:
                    naukri = NaukriAutomator()
                    res_apply = naukri.apply_jobs(daily_target=naukri_target, max_pages_per_role=naukri_pages)
                    add_log(f"✅ [2/6] Naukri Mass Apply finished! Applied: {res_apply.get('applied_count')}, Queued: {res_apply.get('manual_queued_count')}")
                except Exception as e:
                    add_log(f"⚠️ [2/6] Naukri Apply notice: {e}")

            # 3. LinkedIn Feed Harvester & Leads Dispatcher
            feed_target = 40 if cloud_mode else 100
            if _cloud_headroom_ok("[3/6] LinkedIn Feed Harvester"):
                add_log(f"[3/6] Harvesting LinkedIn Feed (Target: {feed_target}+ posts)...")
                try:
                    mgr = BrowserManager(profile_name="linkedin")
                    try:
                        context, page = mgr.get_context_and_page(force_headless=True)
                        config = load_json_file(os.path.join(BASE_DIR, "config.json"), {"limits": {"max_feed_posts_per_run": feed_target}})
                        if cloud_mode:
                            config.setdefault("limits", {})["max_feed_posts_per_run"] = feed_target
                        state = load_json_file(os.path.join(DATA_DIR, "state.json"), {"seen_post_urns": []})
                        harvester = FeedHarvester(page=page, config=config, state=state, base_dir=BASE_DIR, log_cb=add_log)
                        new_leads = harvester.run()
                        save_json_file(os.path.join(DATA_DIR, "state.json"), state)
                        synced = sync_leads()
                        add_log(f"✅ [3/6] Feed Harvest completed: {len(new_leads)} new leads found ({len(synced.get('forms', []))} forms, {len(synced.get('emails', []))} recruiter emails).")
                    finally:
                        mgr.close()
                except Exception as e:
                    add_log(f"⚠️ [3/6] Feed Harvest notice: {e}")

            # 4. LinkedIn Job Scanner & Easy Apply
            if _cloud_headroom_ok("[4/6] LinkedIn Easy Apply"):
                add_log("[4/6] Launching LinkedIn Easy Apply & Job Scanner...")
                try:
                    mgr = BrowserManager(profile_name="linkedin")
                    try:
                        context, page = mgr.get_context_and_page(force_headless=True)
                        config = load_json_file(os.path.join(BASE_DIR, "config.json"), {
                            "target_roles": ["Analyst", "Associate Product Manager"],
                            "location": "India",
                            "dry_run": False,
                            "limits": {"max_jobs_evaluated_per_run": 5 if cloud_mode else 10, "max_easy_applies_per_run": 2}
                        })
                        if cloud_mode:
                            config.setdefault("limits", {})["max_jobs_evaluated_per_run"] = 5
                        state = load_json_file(os.path.join(DATA_DIR, "state.json"), {"seen_job_ids": []})
                        scanner = JobScanner(page=page, config=config, state=state, base_dir=BASE_DIR, log_cb=add_log)
                        res = scanner.run()
                        save_json_file(os.path.join(DATA_DIR, "state.json"), state)
                        add_log(f"✅ [4/6] LinkedIn Easy Apply completed (Applied: {len(res.get('easy_applied', []))}, Queued: {len(res.get('manual_queued', []))}).")
                    finally:
                        mgr.close()
                except Exception as e:
                    add_log(f"⚠️ [4/6] LinkedIn Easy Apply notice: {e}")

            # 5. Regional Companies & Startups Network Expander
            if _cloud_headroom_ok("[5/6] Company Expander"):
                add_log("[5/6] Searching Mumbai Companies & Startups (Connection Requests Only, NO NOTE)...")
                try:
                    expander = CompanyNetworkExpander()
                    res_expand = expander.run_company_expansion(max_companies=2 if cloud_mode else 3, max_connects_per_company=2)
                    add_log(f"✅ [5/6] Company Expander complete: Checked {res_expand.get('companies_processed')} companies, found {res_expand.get('jobs_found')} aligned jobs, sent {res_expand.get('connections_sent')} connection requests (No note).")
                except Exception as e:
                    add_log(f"⚠️ [5/6] Company Expander notice: {e}")

            # 6. Full Gmail Inbox Subject-Line Analysis
            if _cloud_headroom_ok("[6/6] Gmail Inbox Sweep"):
                add_log("[6/6] Sweeping Full Gmail Inbox for Screening Cleared, Exam Dates & Test Links...")
                try:
                    tracker = EmailTracker()
                    intel = tracker.scan_full_inbox()
                    passed = tracker.get_screening_passed()
                    add_log(f"✅ [6/6] Gmail Inbox Sweep completed! Categorized {len(intel)} career emails ({len(passed)} screening cleared).")
                except Exception as e:
                    add_log(f"⚠️ [6/6] Gmail notice: {e}")

            wait_for_ram_cooldown(soft_limit_mb=350.0, max_wait_sec=4.0, log_cb=add_log)
            add_log("🎉 ALL OPERATIONS FINISHED SUCCESSFULLY! All dashboard metrics, queues, and tables updated.")

        elif task_type == "company_connect":
            add_log("Starting Regional Companies & Startups Network Expander (Connection Request Only, No Note)...")
            expander = CompanyNetworkExpander()
            res_expand = expander.run_company_expansion(max_companies=4, max_connects_per_company=3)
            add_log(f"SUCCESS: Checked {res_expand.get('companies_processed')} companies, sent {res_expand.get('connections_sent')} connection requests (No Note), found {res_expand.get('jobs_found')} jobs.")

        elif task_type == "send_messages":
            add_log("Starting Dedicated Messaging / Referral Outreach to Connections...")
            engine = ReferralEngine()
            conns = engine.get_existing_connections(limit=10)
            results = engine.send_outreach_batch(conns)
            add_log(f"SUCCESS: Sent {len(results)} personalized referral messages.")

        elif task_type in ["naukri_all", "naukri_update_and_apply"]:
            add_log("⚡ NAUKRI AUTOPILOT ACTIVATED: Running Recency Boost & 50+ Mass Apply...")
            try:
                naukri = NaukriAutomator()
                add_log("[1/2] Updating Naukri profile headline for 'Updated: Today' boost...")
                res_boost = naukri.boost_profile()
                add_log(f"✅ [1/2] Naukri Boost completed: {res_boost.get('status')}")
            except Exception as e:
                add_log(f"⚠️ [1/2] Naukri Boost notice: {e}")

            try:
                naukri = NaukriAutomator()
                add_log("[2/2] Launching Naukri High-Volume Mass Apply (Target: 50+)...")
                res_apply = naukri.apply_jobs(daily_target=50)
                add_log(f"✅ [2/2] Naukri Mass Apply finished! Applied: {res_apply.get('applied_count')}, Queued: {res_apply.get('manual_queued_count')}")
            except Exception as e:
                add_log(f"⚠️ [2/2] Naukri Apply notice: {e}")
            add_log("🎉 Naukri Update & Mass Apply operations completed!")

        elif task_type == "naukri_boost":
            add_log("Starting Naukri Daily Recency Boost...")
            naukri = NaukriAutomator()
            res = naukri.boost_profile()
            add_log(f"SUCCESS: Naukri Boost completed with status: {res.get('status')}")

        elif task_type == "naukri_apply":
            add_log("Starting Naukri High-Volume Mass Apply (Target: 50+)...")
            naukri = NaukriAutomator()
            res = naukri.apply_jobs(daily_target=50)
            add_log(f"SUCCESS: Naukri Mass Apply finished! Applied: {res.get('applied_count')}, Manual Queue: {res.get('manual_queued_count')}")

        elif task_type == "linkedin_apply":
            add_log("🚀 Starting LinkedIn Easy Apply & Job Scanner...")
            mgr = BrowserManager(profile_name="linkedin")
            try:
                context, page = mgr.get_context_and_page(force_headless=True)
                mgr.ensure_logged_in(page, timeout_sec=15)
                config = load_json_file(os.path.join(BASE_DIR, "config.json"), {
                    "target_roles": ["Analyst", "Associate Product Manager", "Product Manager"],
                    "location": "India",
                    "dry_run": False,
                    "limits": {"max_jobs_evaluated_per_run": 10, "max_easy_applies_per_run": 3, "max_easy_applies_per_day": 12}
                })
                if is_cloud_low_mem():
                    config.setdefault("limits", {})["max_jobs_evaluated_per_run"] = 6
                state = load_json_file(os.path.join(DATA_DIR, "state.json"), {"seen_job_ids": []})
                scanner = JobScanner(page=page, config=config, state=state, base_dir=BASE_DIR, log_cb=add_log)
                res = scanner.run()
                save_json_file(os.path.join(DATA_DIR, "state.json"), state)
                applied = len(res.get("easy_applied", []))
                queued = len(res.get("manual_queued", []))
                add_log(f"🎉 SUCCESS: LinkedIn Job Scanner finished! Easy Applied: {applied}, Manual Queued: {queued}.")
            except Exception as e:
                add_log(f"❌ ERROR in LinkedIn Job Scanner: {e}")
            finally:
                mgr.close()

        elif task_type == "linkedin_feed":
            add_log("🚀 Starting LinkedIn For You Feed Harvester (/feed/foryou/, Target: 100+ Posts)...")
            mgr = BrowserManager(profile_name="linkedin")
            try:
                context, page = mgr.get_context_and_page(force_headless=True)
                mgr.ensure_logged_in(page, timeout_sec=15)
                config = load_json_file(os.path.join(BASE_DIR, "config.json"), {"limits": {"max_feed_posts_per_run": 100}})
                state = load_json_file(os.path.join(DATA_DIR, "state.json"), {"seen_post_urns": []})
                harvester = FeedHarvester(page=page, config=config, state=state, base_dir=BASE_DIR, log_cb=add_log)
                new_leads = harvester.run()
                save_json_file(os.path.join(DATA_DIR, "state.json"), state)
                synced = sync_leads()
                add_log(f"🎉 SUCCESS: LinkedIn Feed Harvester completed! Discovered {len(new_leads)} new hiring leads.")
                add_log(f"📊 Live Desks Updated: {len(synced.get('forms', []))} Pending Forms, {len(synced.get('emails', []))} Recruiter Leads.")
            except Exception as e:
                add_log(f"❌ ERROR in LinkedIn Feed Harvester: {e}")
            finally:
                mgr.close()

        elif task_type == "scan_gmail":
            add_log("Starting Full Gmail Inbox Subject-Line Analysis...")
            tracker = EmailTracker()
            intel = tracker.scan_full_inbox()
            add_log(f"SUCCESS: Gmail Inbox Analysis completed! Categorized {len(intel)} career updates.")

        elif task_type == "scan_replies":
            add_log("Starting LinkedIn Message Scan for Resume Requests (Two-Phase)...")
            engine = ReferralEngine()
            results = engine.check_inbox_and_dispatch_resume()
            add_log(f"SUCCESS: LinkedIn Inbox Scan finished. Dispatched resumes to {len(results)} contacts.")

        elif task_type == "mumbai_followup":
            add_log("🏙️ Running Daily Mumbai Connection Acceptance Check → Sending List...")
            meng = MumbaiOutreachEngine()
            res = meng.run_daily_acceptance_and_send(min_age_days=0, check_all_pending=True, send_immediately=False, log_cb=add_log)
            add_log(f"✅ Mumbai Daily Check finished: {res.get('added_to_sending_list', 0)} promoted to Sending List, {res.get('still_pending', 0)} still pending.")

        elif task_type == "pec_referral":
            state_path = os.path.join(DATA_DIR, "state.json")
            state_obj = load_json_file(state_path, {})
            now_ts = time.time()
            cooldown_until = float(state_obj.get("pec_search_cooldown_until", 0) or 0)
            if cooldown_until > now_ts:
                rem_mins = int((cooldown_until - now_ts) / 60)
                add_log(f"⏸️ [PEC REFERRAL] LinkedIn search limit cooldown active (~{rem_mins}m left). Skipping search cleanly.")
            else:
                add_log("🎓 [PEC REFERRAL] Probing whether LinkedIn Search is open before running PEC Alumni referrals...")
                search_open = False
                limit_reason = ""
                mgr = BrowserManager(profile_name="linkedin")
                try:
                    context, page = mgr.get_context_and_page(force_headless=True)
                    if not mgr.ensure_logged_in(page, timeout_sec=15):
                        limit_reason = "LinkedIn authentication unavailable"
                    else:
                        try:
                            page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
                        except Exception:
                            pass
                        try:
                            resp = page.goto(
                                "https://www.linkedin.com/search/results/people/?keywords=Punjab%20Engineering%20College",
                                wait_until="domcontentloaded",
                                timeout=25000,
                            )
                            time.sleep(2.0)
                            cur_url = (page.url or "").lower()
                            body_lower = (page.evaluate("() => (document.body && document.body.innerText ? document.body.innerText : '').slice(0, 3000)") or "").lower()
                            status_code = resp.status if resp else 200
                            if status_code in (429, 999) or any(k in cur_url for k in ("checkpoint", "uas/login", "authwall")):
                                limit_reason = f"HTTP {status_code} / gate ({cur_url})"
                            elif any(k in body_lower for k in (
                                "commercial use limit",
                                "monthly limit on profile searches",
                                "you've reached the monthly limit",
                                "reached the limit",
                                "unlock unlimited search",
                                "too many requests",
                            )):
                                limit_reason = "LinkedIn monthly/commercial search limit active"
                            else:
                                search_open = True
                        except Exception as pe:
                            limit_reason = f"Search probe exception: {pe}"
                finally:
                    mgr.close()

                if not search_open:
                    state_obj["pec_search_cooldown_until"] = time.time() + (4 * 3600)
                    state_obj["pec_search_status"] = f"Blocked ({limit_reason})"
                    save_json_file(state_path, state_obj)
                    add_log(f"⏸️ [PEC REFERRAL] Search still restricted ({limit_reason}). Deferred 4h cleanly.")
                else:
                    state_obj["pec_search_cooldown_until"] = 0
                    state_obj["pec_search_status"] = "Open"
                    save_json_file(state_path, state_obj)
                    add_log("✅ [PEC REFERRAL] LinkedIn Search is OPEN! Running PEC Alumni referral outreach & acceptance check...")
                    meng = MumbaiOutreachEngine()
                    pec_ids = [
                        c.get("id") for c in meng.get_contacts()
                        if c.get("is_pec_alumni") and c.get("workflow_stage") == "discovered"
                    ]
                    max_act = 3 if is_cloud_low_mem() else 6
                    c_res = {"connections_sent": 0}
                    if pec_ids:
                        c_res = meng.run_connect_and_message_cycle(contact_ids=pec_ids[:max_act], max_connects=max_act, connect_only=True, log_cb=add_log)
                    else:
                        c_res = meng.run_connect_and_message_cycle(max_connects=max_act, connect_only=True, log_cb=add_log)
                    f_res = meng.run_daily_acceptance_and_send(min_age_days=0, check_all_pending=True, send_immediately=True, log_cb=add_log)
                    add_log(f"🎓 [PEC REFERRAL] Complete: connections_sent={c_res.get('connections_sent', 0)}, accepted_messaged={f_res.get('accepted_and_messaged', 0)}")

    except Exception as e:
        task_failed = True
        add_log(f"ERROR during {task_type}: {e}")
    finally:
        if task_type in LAST_PERIODIC_RUNS:
            # Anchor cooldown to completion time (+30m extra backoff if it errored) so failed jobs never spin-loop
            LAST_PERIODIC_RUNS[task_type] = time.time() + (1800 if task_failed else 0)
        import gc
        gc.collect()
        next_task = None
        with TASK_LOCK:
            if TASK_QUEUE:
                next_task = TASK_QUEUE.popleft()
                CURRENT_TASK["queued"] = list(TASK_QUEUE)
                CURRENT_TASK["running"] = True
                CURRENT_TASK["name"] = next_task
                CURRENT_TASK["started_at"] = datetime.now(IST).strftime("%H:%M:%S")
            else:
                CURRENT_TASK["running"] = False
                CURRENT_TASK["name"] = "Idle"
                CURRENT_TASK["started_at"] = None
                CURRENT_TASK["queued"] = []
        if next_task:
            add_log(f"⏭️ [TASK QUEUE] Launching next queued operation: '{next_task}'")
            threading.Thread(target=execute_task, args=(next_task,), daemon=True).start()


def enqueue_or_run_task(task_type: str) -> tuple:
    """Safely runs task immediately if idle, or queues it sequentially to prevent Chromium/memory overload."""
    with TASK_LOCK:
        if not CURRENT_TASK["running"]:
            CURRENT_TASK["running"] = True
            CURRENT_TASK["name"] = task_type
            CURRENT_TASK["started_at"] = datetime.now(IST).strftime("%H:%M:%S")
            CURRENT_TASK["queued"] = list(TASK_QUEUE)
            threading.Thread(target=execute_task, args=(task_type,), daemon=True).start()
            return True, f"Task '{task_type}' launched in background."
        if task_type not in TASK_QUEUE and CURRENT_TASK["name"] != task_type:
            TASK_QUEUE.append(task_type)
            CURRENT_TASK["queued"] = list(TASK_QUEUE)
            add_log(f"📥 [TASK QUEUE] Queued '{task_type}' behind '{CURRENT_TASK['name']}' (Queue size: {len(TASK_QUEUE)}).")
            return True, f"Task '{task_type}' safely queued behind '{CURRENT_TASK['name']}'."
        return False, f"Task '{task_type}' is already running or queued."


@app.route("/api/run/<task_type>", methods=["POST"])
def run_task(task_type):
    ok, msg = enqueue_or_run_task(task_type)
    return jsonify({"message": msg, "queued": CURRENT_TASK.get("queued", [])})


MILESTONE_FILE = os.path.join(DATA_DIR, "daily_milestones.json")
SHIFT_REPORT_FILE = os.path.join(DATA_DIR, "daily_shift_report.json")


def _load_milestones() -> set:
    if os.path.exists(MILESTONE_FILE):
        try:
            with open(MILESTONE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def _record_milestone(m_name: str):
    completed = _load_milestones()
    completed.add(m_name)
    try:
        with open(MILESTONE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(completed)[-200:], f, indent=2)
    except Exception:
        pass


def _system_load_ok() -> tuple:
    """Enforces RAM and CPU load-management headroom before starting browser automation."""
    cloud_mode = is_cloud_low_mem()
    ram_limit = 405.0 if cloud_mode else 1400.0
    ram_mb = wait_for_ram_cooldown(soft_limit_mb=min(ram_limit, 360.0 if cloud_mode else 900.0), max_wait_sec=2.0)
    if ram_mb > ram_limit:
        return False, f"RAM {ram_mb} MB exceeds ceiling ({ram_limit} MB)", ram_mb
    try:
        load1 = os.getloadavg()[0]
        cpu_cnt = os.cpu_count() or 4
        cpu_ceil = max(4.0, cpu_cnt * 1.35)
        if not cloud_mode and load1 > cpu_ceil:
            return False, f"CPU 1m load {load1:.2f} exceeds ceiling ({cpu_ceil:.2f})", ram_mb
    except Exception:
        pass
    return True, "OK", ram_mb


def _current_shift_slot(now_ist: datetime) -> str:
    h = now_ist.hour
    if 9 <= h < 11:
        return "09:00-11:00 IST | Active Post Scrolling (/feed/foryou/ - 2h Block #1)"
    if h == 11:
        return "11:00-12:00 IST | Wait Feed #1: Naukri Headline + 1h Naukri Apply"
    if h == 12:
        return "12:00-13:00 IST | Wait Feed #1: 1h LinkedIn Easy Apply"
    if 13 <= h < 15:
        return "13:00-15:00 IST | Active Post Scrolling (/feed/foryou/ - 2h Block #2)"
    if 15 <= h < 17:
        return "15:00-17:00 IST | Wait Feed #2: PEC Referral (When Search Open) + Continuous Email Analysis"
    return "Off-Shift (17:00-09:00 IST Standby)"


def _write_daily_shift_report(now_ist: datetime):
    try:
        stats = get_stats()
        state_obj = load_json_file(os.path.join(DATA_DIR, "state.json"), {})
        report = {
            "date": str(now_ist.date()),
            "generated_at_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
            "shift": "09:00 - 17:00 IST (8 Hours)",
            "feed_posts_count": stats.get("feed_posts_count", 0),
            "naukri_applied_today": stats.get("naukri_today", 0),
            "naukri_boost": stats.get("naukri_boost", {}),
            "linkedin_easy_apply_today": stats.get("linkedin_today", 0),
            "email_intel_count": stats.get("email_intel_count", 0),
            "pec_search_status": state_obj.get("pec_search_status", "Pending Check"),
            "mumbai_incomplete_count": stats.get("mumbai_incomplete_count", 0),
        }
        save_json_file(SHIFT_REPORT_FILE, report)
    except Exception as e:
        logger.warning(f"Shift report save note: {e}")


def _trigger_scheduled_job(task_name: str, source: str = "8h SHIFT") -> bool:
    now_ist = datetime.now(IST)
    if not (9 <= now_ist.hour < 17):
        return False
    load_ok, reason, ram_mb = _system_load_ok()
    if not load_ok:
        add_log(f"⏸️ [LOAD MANAGER] Deferred '{task_name}' ({reason}).")
        return False
    with TASK_LOCK:
        if CURRENT_TASK["running"]:
            return False
        CURRENT_TASK["running"] = True
        CURRENT_TASK["name"] = task_name
        CURRENT_TASK["started_at"] = now_ist.strftime("%H:%M:%S")
        add_log(f"⏰ [{source}] Triggering '{task_name}' at {now_ist.strftime('%H:%M:%S')} IST (RAM: {ram_mb} MB | Slot: {_current_shift_slot(now_ist)})")
        if task_name in LAST_PERIODIC_RUNS:
            LAST_PERIODIC_RUNS[task_name] = time.time()
        threading.Thread(target=execute_task, args=(task_name,), daemon=True).start()
        return True


def evaluate_8h_shift_tick(source: str = "8h SHIFT") -> dict:
    """
    Executes one scheduling decision for the 8-hour daily shift (09:00 - 17:00 IST):
      - 09:00-11:00 IST (2h): Post Scrolling (/feed/foryou/) every 20m + email checks between batches
      - 11:00-13:00 IST (2h wait from feed): Once-daily Naukri Headline Boost -> 1h Naukri Apply (11:00-12:00) -> 1h LinkedIn Easy Apply (12:00-13:00)
      - 13:00-15:00 IST (2h): Post Scrolling (/feed/foryou/) again every 20m + email checks between batches
      - 15:00-17:00 IST (2h wait from feed / rest of time): PEC Referral check (when search limit is open) + Continuous Email Thread Analysis & Replies
    """
    now_ist = datetime.now(IST)
    today_str = str(now_ist.date())
    h = now_ist.hour
    now_ts = time.time()

    if not (9 <= h < 17):
        if h >= 17:
            completed = _load_milestones()
            shift_end_key = f"{today_str}_shift_end_8h"
            if shift_end_key not in completed:
                _record_milestone(shift_end_key)
                _write_daily_shift_report(now_ist)
                add_log("🌙 [8h SHIFT COMPLETE] 05:00 PM IST reached. End-of-day report saved; standby until 09:00 AM tomorrow.")
        return {"triggered": None, "slot": _current_shift_slot(now_ist), "running": CURRENT_TASK["running"]}

    if CURRENT_TASK["running"]:
        return {"triggered": None, "slot": _current_shift_slot(now_ist), "running": True, "current": CURRENT_TASK["name"]}

    completed = _load_milestones()
    boost_key = f"{today_str}_naukri_boost"
    triggered = None

    # 1. Ideal Non-Feed Hours (11:00-13:00): Once-a-day Headline Boost + 1h Naukri Apply + 1h Easy Apply
    if 11 <= h < 13:
        if boost_key not in completed:
            if _trigger_scheduled_job("naukri_boost", source):
                _record_milestone(boost_key)
                triggered = "naukri_boost"
        elif h == 11 and (now_ts - LAST_PERIODIC_RUNS["naukri_apply"]) > (5 * 60):
            if _trigger_scheduled_job("naukri_apply", source):
                triggered = "naukri_apply"
        elif h == 12 and (now_ts - LAST_PERIODIC_RUNS["linkedin_apply"]) > (5 * 60):
            if _trigger_scheduled_job("linkedin_apply", source):
                triggered = "linkedin_apply"

    # 2. Active Feed Scrolling Windows (2h ON: 09:00-11:00, wait 2h, 2h ON: 13:00-15:00)
    elif h in (9, 10, 13, 14):
        if (now_ts - LAST_PERIODIC_RUNS["linkedin_feed"]) > (20 * 60):
            if _trigger_scheduled_job("linkedin_feed", source):
                triggered = "linkedin_feed"

    # 3. Late Wait Window (15:00-17:00): Catch up headline boost if app started late + PEC Referral when Search is open
    elif h in (15, 16):
        if boost_key not in completed:
            if _trigger_scheduled_job("naukri_boost", source):
                _record_milestone(boost_key)
                triggered = "naukri_boost"
        elif (now_ts - LAST_PERIODIC_RUNS["pec_referral"]) > (90 * 60):
            if _trigger_scheduled_job("pec_referral", source):
                triggered = "pec_referral"

    # 4. Rest-of-time within the 8h shift: Continuously analyze Email Threads & Inbox Replies
    if not triggered and not CURRENT_TASK["running"]:
        if (now_ts - LAST_PERIODIC_RUNS["scan_gmail"]) > (15 * 60):
            if _trigger_scheduled_job("scan_gmail", source):
                triggered = "scan_gmail"
        elif (now_ts - LAST_PERIODIC_RUNS["scan_replies"]) > (45 * 60):
            if _trigger_scheduled_job("scan_replies", source):
                triggered = "scan_replies"

    return {"triggered": triggered, "slot": _current_shift_slot(now_ist), "running": CURRENT_TASK["running"]}


@app.route("/api/cron/tick", methods=["POST", "GET"])
def api_cron_tick():
    """Cron & external keep-alive endpoint to execute one load-checked 8-hour shift tick."""
    res = evaluate_8h_shift_tick(source="CRON TICK")
    return jsonify({"status": "ok", "ist_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"), **res})


@app.route("/api/shift/status", methods=["GET"])
def api_shift_status():
    """Returns current 8-hour shift slot, load metrics, PEC search-limit state, and end-of-day report."""
    now_ist = datetime.now(IST)
    load_ok, reason, ram_mb = _system_load_ok()
    state_obj = load_json_file(os.path.join(DATA_DIR, "state.json"), {})
    report = load_json_file(SHIFT_REPORT_FILE, {})
    return jsonify({
        "ist_time": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "active_shift": 9 <= now_ist.hour < 17,
        "slot": _current_shift_slot(now_ist),
        "load_ok": load_ok,
        "load_reason": reason,
        "ram_mb": ram_mb,
        "pec_search_status": state_obj.get("pec_search_status", "Unknown"),
        "pec_search_cooldown_until": state_obj.get("pec_search_cooldown_until", 0),
        "current_task": CURRENT_TASK,
        "last_report": report,
    })


def autonomous_8h_scheduler():
    """
    Runs inside app.py as a lightweight background daemon thread.
    Enforces the 8-hour daily shift (09:00 AM - 05:00 PM IST).
    """
    logger.info("Starting Integrated Autonomous 8-Hour Shift Scheduler (09:00 - 17:00 IST)...")
    while True:
        try:
            evaluate_8h_shift_tick(source="8h SHIFT SCHEDULER")
        except Exception as e:
            logger.error(f"Error in autonomous scheduler: {e}")
        time.sleep(30)


# Launch autonomous 8h scheduler thread immediately on server startup
sched_thread = threading.Thread(target=autonomous_8h_scheduler, daemon=True)
sched_thread.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5055))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info(f"Starting Careercommand on http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)
