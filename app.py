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
import schedule
import logging
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request, render_template_string
from werkzeug.utils import secure_filename

IST = timezone(timedelta(hours=5, minutes=30))

from browser_session import BrowserManager
from referral_engine import ReferralEngine
from naukri_automator import NaukriAutomator
from email_tracker import EmailTracker, EMAIL_INTEL_JSON
from recruitment_dispatcher import sync_leads, PENDING_FORMS_JSON, RECRUITER_LEADS_JSON
from company_network_expander import CompanyNetworkExpander
from feed_harvester import FeedHarvester
from job_scanner import JobScanner

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

CURRENT_TASK = {"running": False, "name": "Idle", "started_at": None}
LIVE_LOGS = []


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


def get_stats():
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
    is_active_shift = 9 <= now_ist.hour < 19
    mem_mb = 0
    try:
        import psutil
        p = psutil.Process(os.getpid())
        mem_mb = round(p.memory_info().rss / 1024 / 1024, 1)
        for child in p.children(recursive=True):
            mem_mb += round(child.memory_info().rss / 1024 / 1024, 1)
        mem_mb = round(mem_mb, 1)
    except Exception:
        pass

    return {
        "naukri_today": naukri_count,
        "linkedin_today": linkedin_count,
        "total_today": naukri_count + linkedin_count,
        "manual_count": len(manual_items),
        "email_intel_count": len(email_intel),
        "pending_forms_count": len(pending_forms),
        "recruiter_leads_count": len(recruiter_leads),
        "outreach_count": len(outreach_records),
        "naukri_boost": boost_status,
        "current_task": CURRENT_TASK,
        "scheduler_status": "Active (10h Shift 09:00 - 19:00 IST)" if is_active_shift else "Standby (Resumes 09:00 AM IST)",
        "ist_time": now_ist.strftime("%H:%M:%S IST"),
        "ram_mb": mem_mb
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
            <button onclick="switchTab('forms')" id="nav-forms"
                    class="nav-item w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition">
              <div class="flex items-center space-x-3">
                <i class="fa-solid fa-file-pen w-4 text-teal-600"></i>
                <span>Pending Forms</span>
              </div>
              <span class="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-teal-100 text-teal-700" id="sidebarFormsBadge">0</span>
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
            <button onclick="switchTab('naukri')" id="nav-naukri"
                    class="nav-item w-full flex items-center space-x-3 px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition">
              <i class="fa-solid fa-bolt w-4 text-amber-500"></i>
              <span>Naukri Booster</span>
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
    <header class="bg-white border-b border-slate-200/80 px-8 py-3.5 flex items-center justify-between z-10 flex-shrink-0">
      <div>
        <nav class="text-xs text-slate-400 font-medium flex items-center space-x-1.5">
          <span>Pages</span>
          <span>/</span>
          <span class="text-slate-800 capitalize" id="currentBreadcrumb">Dashboard</span>
        </nav>
        <h2 class="text-xl font-bold text-slate-900 leading-tight capitalize" id="currentPageHeading">Dashboard</h2>
      </div>

      <!-- Quick Manual Triggers Row -->
      <div class="flex items-center space-x-2">
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

          <!-- Card 2: Gmail In-Progress Updates -->
          <div class="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm flex items-center justify-between hover:shadow-md transition cursor-pointer" onclick="switchTab('gmail')">
            <div>
              <p class="text-xs font-semibold text-slate-400">In-Progress Emails</p>
              <div class="flex items-baseline space-x-2 mt-1">
                <h3 class="text-2xl font-bold text-slate-900" id="cardGmailCount">51</h3>
                <span class="text-xs font-semibold text-purple-500">Inbox Intel</span>
              </div>
            </div>
            <div class="w-12 h-12 rounded-xl bg-purple-600 flex items-center justify-center text-white shadow-md shadow-purple-600/30">
              <i class="fa-solid fa-envelope-open-text text-lg"></i>
            </div>
          </div>

          <!-- Card 3: Manual Queue & Pending Forms -->
          <div class="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm flex items-center justify-between hover:shadow-md transition cursor-pointer" onclick="switchTab('manual')">
            <div>
              <p class="text-xs font-semibold text-slate-400">Manual Desk & Forms</p>
              <div class="flex items-baseline space-x-2 mt-1">
                <h3 class="text-2xl font-bold text-slate-900" id="cardManualCount">12</h3>
                <span class="text-xs font-semibold text-rose-500">Requires Action</span>
              </div>
            </div>
            <div class="w-12 h-12 rounded-xl bg-rose-500 flex items-center justify-center text-white shadow-md shadow-rose-500/30">
              <i class="fa-solid fa-clipboard-list text-lg"></i>
            </div>
          </div>

          <!-- Card 4: Recruiter Outreach & Leads -->
          <div class="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm flex items-center justify-between hover:shadow-md transition cursor-pointer" onclick="switchTab('alumni')">
            <div>
              <p class="text-xs font-semibold text-slate-400">Direct Outreaches</p>
              <div class="flex items-baseline space-x-2 mt-1">
                <h3 class="text-2xl font-bold text-slate-900" id="cardOutreachCount">2</h3>
                <span class="text-xs font-semibold text-indigo-500">Delivered</span>
              </div>
            </div>
            <div class="w-12 h-12 rounded-xl bg-emerald-500 flex items-center justify-center text-white shadow-md shadow-emerald-500/30">
              <i class="fa-solid fa-users text-lg"></i>
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
      <!-- TAB 3: APPLICATION FORMS PENDING           -->
      <!-- ========================================== -->
      <div id="view-forms" class="hidden space-y-6">
        <div class="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm space-y-4">
          <div class="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h3 class="font-bold text-slate-900 text-base flex items-center gap-2">
                <i class="fa-solid fa-file-pen text-teal-600"></i>
                <span>Application Forms Pending (Google Forms & Typeforms)</span>
              </h3>
              <p class="text-xs text-slate-400">Hiring vacancy posts containing direct Google Forms or Typeforms. Saved here for your manual application.</p>
            </div>
            <button onclick="triggerAction('linkedin_feed')" class="px-3.5 py-1.5 bg-teal-600 hover:bg-teal-500 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow-sm shadow-teal-600/30">
              <i class="fa-solid fa-rss"></i>
              <span>Harvest Fresh Feed Posts</span>
            </button>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="p-3">Detected</th>
                  <th class="p-3">Poster / Company</th>
                  <th class="p-3">Context / Hiring Details</th>
                  <th class="p-3">Status</th>
                  <th class="p-3 text-right">Direct Form</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100" id="pendingFormsTableBody">
                <tr><td colspan="5" class="p-6 text-center text-slate-400">Loading pending forms...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

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
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-50 text-slate-400 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="p-3">Detected</th>
                  <th class="p-3">Recruiter / Author</th>
                  <th class="p-3">Recruiter Email</th>
                  <th class="p-3">Draft Application Preview</th>
                  <th class="p-3 text-right">Send Email</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100" id="recruiterLeadsTableBody">
                <tr><td colspan="5" class="p-6 text-center text-slate-400">Loading recruiter leads...</td></tr>
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
      activeTab = tabId;
      document.querySelectorAll('.nav-item').forEach(el => {
        el.className = "nav-item w-full flex items-center space-x-3 px-3 py-2.5 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition";
      });
      const activeNav = document.getElementById(`nav-${tabId}`);
      if (activeNav) {
        activeNav.className = "nav-item w-full flex items-center space-x-3 px-3 py-2.5 rounded-xl text-sm font-semibold transition bg-slate-100 text-slate-900 shadow-sm";
      }

      ['dashboard', 'gmail', 'forms', 'recruiters', 'alumni', 'naukri', 'manual', 'resume', 'terminal'].forEach(t => {
        const el = document.getElementById(`view-${t}`);
        if (el) el.classList.toggle('hidden', t !== tabId);
      });

      const headingMap = {
        dashboard: 'Executive Dashboard',
        gmail: 'Gmail Inbox Intelligence',
        forms: 'Application Forms Pending',
        recruiters: 'Harvested Recruiter Emails',
        alumni: 'PEC Alumni & Referral Outreach',
        naukri: 'Naukri Daily Recency Booster',
        manual: 'Manual Intervention Desk',
        resume: 'Active Master Resume & Two-Phase Referral Desk',
        terminal: 'Live Background Console'
      };

      document.getElementById('currentBreadcrumb').innerText = tabId;
      document.getElementById('currentPageHeading').innerText = headingMap[tabId] || tabId;
    }

    async function pollDashboardData() {
      try {
        const res = await fetch('/api/stats');
        const d = await res.json();
        document.getElementById('cardTodayCount').innerText = d.total_today;
        document.getElementById('cardGmailCount').innerText = d.email_intel_count;
        document.getElementById('cardManualCount').innerText = d.manual_count;
        document.getElementById('cardOutreachCount').innerText = d.outreach_count;

        document.getElementById('sidebarManualBadge').innerText = d.manual_count;
        document.getElementById('sidebarGmailBadge').innerText = d.email_intel_count;
        document.getElementById('sidebarFormsBadge').innerText = d.pending_forms_count;
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

    // Pending Forms
    async function loadPendingForms() {
      try {
        const res = await fetch('/api/pending_forms');
        const d = await res.json();
        const tbody = document.getElementById('pendingFormsTableBody');
        if (!tbody) return;

        if (!d.forms || !d.forms.length) {
          tbody.innerHTML = `<tr><td colspan="5" class="p-6 text-center text-slate-400">No application forms pending.</td></tr>`;
          return;
        }

        tbody.innerHTML = d.forms.map(f => `
          <tr class="hover:bg-slate-50 transition">
            <td class="p-3 text-slate-400 text-[11px] whitespace-nowrap">${f.timestamp}</td>
            <td class="p-3 font-bold text-slate-900">${f.poster}</td>
            <td class="p-3 text-slate-600 max-w-md truncate" title="${f.context}">${f.context}</td>
            <td class="p-3">
              <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-teal-100 text-teal-800">${f.status}</span>
            </td>
            <td class="p-3 text-right">
              <a href="${f.form_url}" target="_blank"
                 class="px-3.5 py-1.5 bg-teal-600 hover:bg-teal-500 text-white rounded-xl text-xs font-semibold inline-flex items-center gap-1.5 shadow-sm shadow-teal-600/20">
                <span>Open & Fill Form</span>
                <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
              </a>
            </td>
          </tr>
        `).join('');
      } catch (e) {}
    }

    // Recruiter Leads
    async function loadRecruiterLeads() {
      try {
        const res = await fetch('/api/recruiter_leads');
        const d = await res.json();
        const tbody = document.getElementById('recruiterLeadsTableBody');
        if (!tbody) return;

        if (!d.emails || !d.emails.length) {
          tbody.innerHTML = `<tr><td colspan="5" class="p-6 text-center text-slate-400">No recruiter leads harvested yet.</td></tr>`;
          return;
        }

        tbody.innerHTML = d.emails.map(e => `
          <tr class="hover:bg-slate-50 transition">
            <td class="p-3 text-slate-400 text-[11px] whitespace-nowrap">${e.timestamp}</td>
            <td class="p-3 font-bold text-slate-900">${e.recipient_name}</td>
            <td class="p-3 font-semibold text-indigo-600">${e.email}</td>
            <td class="p-3 text-slate-600 max-w-sm truncate" title="${e.draft_body}">
              <div class="font-medium text-slate-800 text-xs">${e.subject}</div>
              <div class="text-[11px] text-slate-400 truncate">${e.draft_body.slice(0, 80)}...</div>
            </td>
            <td class="p-3 text-right whitespace-nowrap">
              <a href="${e.gmail_web_link}" target="_blank"
                 class="px-3 py-1.5 bg-sky-600 hover:bg-sky-500 text-white rounded-xl text-xs font-semibold inline-flex items-center gap-1.5 shadow-sm shadow-sky-600/20 mr-1.5">
                <i class="fa-solid fa-envelope"></i>
                <span>Send via Gmail</span>
              </a>
              <a href="${e.mailto_link}" class="px-2 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs" title="Open local mail client">
                <i class="fa-solid fa-paper-plane"></i>
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

    // Polling Intervals
    setInterval(pollDashboardData, 3000);
    setInterval(pollLogs, 1500);
    setInterval(loadManualTable, 5000);
    setInterval(loadGmailIntel, 6000);
    setInterval(loadPendingForms, 6000);
    setInterval(loadRecruiterLeads, 6000);
    setInterval(loadOutreachHistory, 5000);
    setInterval(loadDispatches, 8000);

    pollDashboardData();
    pollLogs();
    loadManualTable();
    loadGmailIntel();
    loadPendingForms();
    loadRecruiterLeads();
    loadOutreachHistory();
    loadTemplates();
    loadResumeStatus();
    loadDispatches();
  </script>
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


@app.route("/api/pending_forms")
def pending_forms():
    res = sync_leads()
    return jsonify({"forms": res.get("forms", [])})


@app.route("/api/recruiter_leads")
def recruiter_leads():
    res = sync_leads()
    return jsonify({"emails": res.get("emails", [])})


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
    global CURRENT_TASK
    CURRENT_TASK["running"] = False
    CURRENT_TASK["name"] = "Idle"
    CURRENT_TASK["started_at"] = None
    add_log("SYSTEM: Task execution lock forcibly reset to Idle.")
    return jsonify({"status": "success", "message": "Task reset to Idle."})


def execute_task(task_type):
    CURRENT_TASK["running"] = True
    CURRENT_TASK["name"] = task_type
    CURRENT_TASK["started_at"] = datetime.now(IST).strftime("%H:%M:%S")

    try:
        if task_type == "run_all":
            add_log("🚀 MASTER AUTOPILOT ACTIVATED: Running all operations across Naukri, LinkedIn, and Gmail...")

            # 1. Naukri Recency Boost
            add_log("[1/6] Launching Naukri Daily Recency Boost ('Updated: Today')...")
            try:
                naukri = NaukriAutomator()
                res_boost = naukri.boost_profile()
                add_log(f"✅ [1/6] Naukri Boost completed: {res_boost.get('status')}")
            except Exception as e:
                add_log(f"⚠️ [1/6] Naukri Boost notice: {e}")

            # 2. Naukri 50+ Mass Apply with Questionnaire Handling
            add_log("[2/6] Launching Naukri High-Volume Mass Apply (Target: 50+)...")
            try:
                naukri = NaukriAutomator()
                res_apply = naukri.apply_jobs(daily_target=50)
                add_log(f"✅ [2/6] Naukri Mass Apply finished! Applied: {res_apply.get('applied_count')}, Queued: {res_apply.get('manual_queued_count')}")
            except Exception as e:
                add_log(f"⚠️ [2/6] Naukri Apply notice: {e}")

            # 3. LinkedIn Feed Harvester & Leads Dispatcher
            add_log("[3/6] Harvesting LinkedIn Feed for Hiring Posts, Google Forms & Recruiter Emails...")
            try:
                mgr = BrowserManager(profile_name="linkedin")
                try:
                    context, page = mgr.get_context_and_page(force_headless=True)
                    config = load_json_file(os.path.join(BASE_DIR, "config.json"), {"limits": {"max_feed_posts_per_run": 100}})
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
            add_log("[4/6] Launching LinkedIn Easy Apply & Job Scanner...")
            try:
                mgr = BrowserManager(profile_name="linkedin")
                try:
                    context, page = mgr.get_context_and_page(force_headless=True)
                    config = load_json_file(os.path.join(BASE_DIR, "config.json"), {
                        "target_roles": ["Analyst", "Associate Product Manager"],
                        "location": "India",
                        "dry_run": False,
                        "limits": {"max_jobs_evaluated_per_run": 10, "max_easy_applies_per_run": 2}
                    })
                    state = load_json_file(os.path.join(DATA_DIR, "state.json"), {"seen_job_ids": []})
                    scanner = JobScanner(page=page, config=config, state=state, base_dir=BASE_DIR, log_cb=add_log)
                    res = scanner.run()
                    save_json_file(os.path.join(DATA_DIR, "state.json"), state)
                    add_log(f"✅ [4/6] LinkedIn Easy Apply completed (Applied: {len(res.get('easy_applied', []))}, Queued: {len(res.get('manual_queued', []))}).")
                finally:
                    mgr.close()
            except Exception as e:
                add_log(f"⚠️ [4/6] LinkedIn Easy Apply notice: {e}")

            # 5. Regional Companies & Startups Network Expander (Mumbai & Startups)
            add_log("[5/6] Searching Mumbai Companies & Startups (Jobs Search + Connection Requests Only, NO NOTE)...")
            try:
                expander = CompanyNetworkExpander()
                res_expand = expander.run_company_expansion(max_companies=3, max_connects_per_company=2)
                add_log(f"✅ [5/6] Company Expander complete: Checked {res_expand.get('companies_processed')} companies, found {res_expand.get('jobs_found')} aligned jobs, sent {res_expand.get('connections_sent')} connection requests (No note).")
            except Exception as e:
                add_log(f"⚠️ [5/6] Company Expander notice: {e}")

            # 6. Full Gmail Inbox Subject-Line Analysis
            add_log("[6/6] Sweeping Full Gmail Inbox for Screening Cleared, Exam Dates & Test Links...")
            try:
                tracker = EmailTracker()
                intel = tracker.scan_full_inbox()
                passed = tracker.get_screening_passed()
                add_log(f"✅ [6/6] Gmail Inbox Sweep completed! Categorized {len(intel)} career emails ({len(passed)} screening cleared).")
            except Exception as e:
                add_log(f"⚠️ [6/6] Gmail notice: {e}")

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
                config = load_json_file(os.path.join(BASE_DIR, "config.json"), {
                    "target_roles": ["Analyst", "Associate Product Manager", "Product Manager"],
                    "location": "India",
                    "dry_run": False,
                    "limits": {"max_jobs_evaluated_per_run": 10, "max_easy_applies_per_run": 3, "max_easy_applies_per_day": 12}
                })
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
            add_log("🚀 Starting LinkedIn Feed Harvester (Target: 100+ Posts)...")
            mgr = BrowserManager(profile_name="linkedin")
            try:
                context, page = mgr.get_context_and_page(force_headless=True)
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

    except Exception as e:
        add_log(f"ERROR during {task_type}: {e}")
    finally:
        CURRENT_TASK["running"] = False
        CURRENT_TASK["name"] = "Idle"
        import gc
        gc.collect()


@app.route("/api/run/<task_type>", methods=["POST"])
def run_task(task_type):
    if CURRENT_TASK["running"]:
        return jsonify({"error": f"Task '{CURRENT_TASK['name']}' is running."}), 400

    t = threading.Thread(target=execute_task, args=(task_type,), daemon=True)
    t.start()
    return jsonify({"message": f"Task '{task_type}' launched in background."})


def autonomous_10h_scheduler():
    """
    Runs inside app.py as a lightweight background daemon thread.
    Enforces the 10-hour daily recruiter shift (09:00 AM - 07:00 PM IST).
    Guarantees zero process bloat and zero memory leaks.
    """
    logger.info("Starting Integrated Autonomous 10-Hour Shift Scheduler (09:00 - 19:00 IST)...")

    def scheduled_job(task_name):
        now_ist = datetime.now(IST)
        if not (9 <= now_ist.hour < 19):
            logger.info(f"Outside 10-hour IST window ({now_ist.strftime('%H:%M')} IST). Skipping scheduled '{task_name}'.")
            return
        if CURRENT_TASK["running"]:
            add_log(f"⏸️ [SCHEDULER] '{task_name}' deferred: Task '{CURRENT_TASK['name']}' is currently running.")
            return
        add_log(f"⏰ [10h SHIFT SCHEDULER] Triggering '{task_name}' at {now_ist.strftime('%H:%M:%S')} IST")
        t = threading.Thread(target=execute_task, args=(task_name,), daemon=True)
        t.start()

    # Recurring scans during active 10h window:
    schedule.every(45).minutes.do(lambda: scheduled_job("linkedin_feed"))
    schedule.every(30).minutes.do(lambda: scheduled_job("scan_gmail"))
    schedule.every(40).minutes.do(lambda: scheduled_job("scan_replies"))

    last_milestone = None
    while True:
        try:
            now_ist = datetime.now(IST)
            time_str = now_ist.strftime("%H:%M")

            if 9 <= now_ist.hour < 19:
                if time_str == "09:00" and last_milestone != f"{now_ist.date()}_naukri_boost":
                    last_milestone = f"{now_ist.date()}_naukri_boost"
                    scheduled_job("naukri_boost")
                elif time_str == "09:30" and last_milestone != f"{now_ist.date()}_naukri_apply_am":
                    last_milestone = f"{now_ist.date()}_naukri_apply_am"
                    scheduled_job("naukri_apply")
                elif time_str == "15:30" and last_milestone != f"{now_ist.date()}_naukri_apply_pm":
                    last_milestone = f"{now_ist.date()}_naukri_apply_pm"
                    scheduled_job("naukri_apply")
                elif time_str == "18:45" and last_milestone != f"{now_ist.date()}_gmail_pm":
                    last_milestone = f"{now_ist.date()}_gmail_pm"
                    scheduled_job("scan_gmail")

            if time_str == "19:00" and last_milestone != f"{now_ist.date()}_shift_end":
                last_milestone = f"{now_ist.date()}_shift_end"
                add_log("🌙 [10h SHIFT COMPLETE] 07:00 PM IST reached. Standby until 09:00 AM tomorrow.")

            schedule.run_pending()
        except Exception as e:
            logger.error(f"Error in autonomous scheduler: {e}")

        time.sleep(30)


# Launch autonomous scheduler thread immediately on server startup
sched_thread = threading.Thread(target=autonomous_10h_scheduler, daemon=True)
sched_thread.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5055))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info(f"Starting Careercommand on http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)
