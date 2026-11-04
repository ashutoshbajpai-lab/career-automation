#!/usr/bin/env bash
# start_chrome.sh - Launches Google Chrome with remote debugging port 9222
# This allows the automation to attach directly to your real Chrome browser session,
# completely bypassing CAPTCHA, 2FA, and anti-bot bans.

echo "Launching Google Chrome with remote debugging port 9222..."
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 &
echo "Chrome is ready. Make sure you are signed in to LinkedIn in this Chrome window."
