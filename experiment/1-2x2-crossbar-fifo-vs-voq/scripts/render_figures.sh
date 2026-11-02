#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIG="$ROOT/docs/figures"

if command -v google-chrome >/dev/null 2>&1; then
    CHROME=google-chrome
elif command -v chromium >/dev/null 2>&1; then
    CHROME=chromium
elif command -v chromium-browser >/dev/null 2>&1; then
    CHROME=chromium-browser
else
    echo "ERROR: need google-chrome or chromium" >&2
    exit 2
fi

render() {
    local name="$1"
    local h="$2"
    "$CHROME" \
        --headless=new \
        --no-sandbox \
        --disable-gpu \
        --disable-dev-shm-usage \
        --hide-scrollbars \
        --default-background-color=FFFFFFFF \
        --window-size="1200,$h" \
        --screenshot="$FIG/$name.png" \
        "file://$FIG/$name.svg" >/dev/null 2>&1
    echo "rendered $name.png"
}

render fifo-architecture 720
render voq-architecture 720
render xp-architecture 720
render verification-flow 620
