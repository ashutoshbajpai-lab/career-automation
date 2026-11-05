#!/usr/bin/env bash

# Start Xvfb only if explicitly forced to headed mode
if [ "$HEADLESS" = "false" ] && command -v Xvfb >/dev/null 2>&1; then
    echo "--> Starting lightweight Xvfb virtual display on :99..."
    Xvfb :99 -screen 0 1024x768x16 -nolisten tcp -ac +extension GLX +render -noreset &
    export DISPLAY=:99
    sleep 2
else
    echo "--> Running in ultra-lightweight headless stealth mode (RAM < 160MB)..."
    unset DISPLAY
fi

echo "--> Launching Careercommand on Port ${PORT:-5055}..."
python3 app.py
