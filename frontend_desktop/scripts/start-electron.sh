#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  cat <<'EOF'
[BIDSPM Desktop] No GUI display detected.

This host appears headless (no DISPLAY/WAYLAND_DISPLAY), so Electron cannot open a window.

Use one of these options:
1) Run the desktop app on your local machine (macOS/Windows/Linux artifact).
2) Use X forwarding from macOS (XQuartz + ssh -Y) if you need remote GUI.
3) For a non-interactive smoke run on this server, use: npm run start:xvfb

Tip: The Flask web UI still works remotely via forwarded browser ports.
EOF
  exit 1
fi

exec electron .