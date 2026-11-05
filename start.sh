#!/usr/bin/env bash
set -e

if [ -n "$SESSION_COOKIES_BASE64" ]; then
    echo "--> Restoring session cookies from secure environment variable..."
    mkdir -p data
    echo "$SESSION_COOKIES_BASE64" | base64 -d > data/session_cookies.json
fi

# Start Xvfb virtual frame buffer for full headed stealth execution on Linux
if command -v Xvfb >/dev/null 2>&1; then
    echo "--> Starting lightweight Xvfb virtual display on :99..."
    Xvfb :99 -screen 0 1024x768x16 -nolisten tcp -ac +extension GLX +render -noreset &
    export DISPLAY=:99
    sleep 2
fi

echo "--> Initializing Cloud Session Cookies..."
python3 import_session.py || true

echo "--> Launching Meraki Career Command Center with Integrated 10h Shift Scheduler on Port ${PORT:-5055}..."
python3 app.py
