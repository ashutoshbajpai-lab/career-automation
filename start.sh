#!/usr/bin/env bash
set -e

if [ -n "$SESSION_COOKIES_BASE64" ]; then
    echo "--> Restoring session cookies from secure environment variable..."
    mkdir -p data
    echo "$SESSION_COOKIES_BASE64" | base64 -d > data/session_cookies.json
fi

echo "--> Initializing Cloud Session Cookies..."
python3 import_session.py || true

echo "--> Starting Autonomous Background Scheduler (24/7)..."
python3 daily_scheduler.py &

echo "--> Launching Meraki Career Command Center on Port ${PORT:-5055}..."
python3 app.py
