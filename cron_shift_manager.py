#!/usr/bin/env python3
"""
cron_shift_manager.py - Daily 8-Hour Cron Shift Manager & Load Watchdog.
Scheduled via macOS crontab to run the 09:00 - 17:00 IST CareerCommand shift:
  - 09:00 - 11:00 IST (2h): Post Scrolling (/feed/foryou/)
  - 11:00 - 13:00 IST (2h wait from feed): Once-daily Naukri Headline + 1h Naukri Apply + 1h Easy Apply
  - 13:00 - 15:00 IST (2h): Post Scrolling (/feed/foryou/) again
  - 15:00 - 17:00 IST (2h wait / rest): PEC Referral (if search open) + Continuous Email Thread Analysis
Also enforces CPU/RAM load management, clears hung Chrome locks >40m, and keeps Render awake if online.
"""

import os
import sys
import json
import time
import fcntl
import argparse
import subprocess
import urllib.request
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CRON_LOG = os.path.join(DATA_DIR, "cron_shift.log")
LOCK_FILE = "/tmp/careercommand_cron.lock"
LOCAL_BASE = "http://127.0.0.1:5055"
RENDER_BASE = "https://career-command-center-vqpj.onrender.com"
SERVICE_LABEL = "com.ashutosh.careercommand"


def log(msg: str):
    os.makedirs(DATA_DIR, exist_ok=True)
    ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(CRON_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def http_json(url: str, method: str = "GET", timeout: int = 8) -> dict:
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def restart_local_service():
    log("🔄 Recovering local CareerCommand LaunchAgent and cleaning stale Chrome/Playwright locks...")
    uid = os.getuid()
    subprocess.run(["launchctl", "stop", SERVICE_LABEL], check=False)
    time.sleep(1)
    subprocess.run(["pkill", "-9", "-f", "chrome_profile"], check=False)
    subprocess.run(["pkill", "-9", "-f", "playwright/driver"], check=False)
    for item in os.listdir(os.path.join(BASE_DIR, "chrome_profile")) if os.path.exists(os.path.join(BASE_DIR, "chrome_profile")) else []:
        if item.startswith("Singleton"):
            try:
                os.unlink(os.path.join(BASE_DIR, "chrome_profile", item))
            except Exception:
                pass
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{SERVICE_LABEL}"], check=False)
    time.sleep(3)


def ensure_local_alive() -> dict:
    try:
        return http_json(f"{LOCAL_BASE}/api/shift/status", timeout=5)
    except Exception:
        restart_local_service()
        return http_json(f"{LOCAL_BASE}/api/shift/status", timeout=8)


def task_stuck_minutes(current_task: dict) -> float:
    if not current_task or not current_task.get("running") or not current_task.get("started_at"):
        return 0.0
    try:
        now_ist = datetime.now(IST)
        hh, mm, ss = [int(x) for x in current_task["started_at"].split(":")]
        started = now_ist.replace(hour=hh, minute=mm, second=ss, microsecond=0)
        diff = (now_ist - started).total_seconds()
        if diff < -3600:
            diff += 86400
        return max(0.0, diff / 60.0)
    except Exception:
        return 0.0


def ping_render_tick():
    """Wakes/ticks Render web service during shift hours so Render Free Tier stays active while Mac is online."""
    try:
        res = http_json(f"{RENDER_BASE}/api/cron/tick", method="POST", timeout=10)
        log(f"☁️ Render tick ok: triggered={res.get('triggered')} | slot={res.get('slot')}")
    except Exception as e:
        log(f"☁️ Render tick note (may be sleeping/cold-booting): {e}")


def run_mode(mode: str, ping_render: bool = True):
    if mode == "status":
        status = ensure_local_alive()
        print(json.dumps(status, indent=2))
        return

    if mode == "start-shift":
        log("☀️ Starting Daily 8-Hour Shift (09:00 - 17:00 IST)...")
        restart_local_service()
        tick = http_json(f"{LOCAL_BASE}/api/cron/tick", method="POST", timeout=10)
        log(f"✅ Local start-shift tick: {tick}")
        if ping_render:
            ping_render_tick()
        return

    if mode == "tick":
        status = ensure_local_alive()
        stuck_mins = task_stuck_minutes(status.get("current_task", {}))
        if stuck_mins > 40.0:
            log(f"⚠️ Watchdog: Task '{status['current_task'].get('name')}' stuck {stuck_mins:.1f}m (>40m). Restarting cleanly...")
            restart_local_service()
            status = ensure_local_alive()

        if not status.get("load_ok", True):
            log(f"⏸️ Load Manager paused new local dispatch: {status.get('load_reason')} (RAM={status.get('ram_mb')} MB)")
        else:
            tick = http_json(f"{LOCAL_BASE}/api/cron/tick", method="POST", timeout=10)
            log(f"⏱️ Local tick: triggered={tick.get('triggered')} running={tick.get('running')} ram={status.get('ram_mb')}MB | {tick.get('slot')}")

        if ping_render:
            ping_render_tick()
        return

    if mode == "end-shift":
        status = ensure_local_alive()
        tick = http_json(f"{LOCAL_BASE}/api/cron/tick", method="POST", timeout=10)
        status = ensure_local_alive()
        log(f"🌙 End-of-Shift (17:00 IST) Report: {json.dumps(status.get('last_report', {}))}")
        if ping_render:
            ping_render_tick()


def main():
    parser = argparse.ArgumentParser(description="CareerCommand 8-Hour Daily Cron Shift Manager")
    parser.add_argument("--mode", choices=["start-shift", "tick", "end-shift", "status"], default="tick")
    parser.add_argument("--no-render", action="store_true", help="Skip pinging Render cloud endpoint")
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOCK_FILE, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("Previous cron_shift_manager run still active — skipping overlapping invocation cleanly.")
            return
        run_mode(args.mode, ping_render=not args.no_render)


if __name__ == "__main__":
    main()
