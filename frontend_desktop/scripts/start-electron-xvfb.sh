#!/usr/bin/env bash
set -euo pipefail

if ! command -v xvfb-run >/dev/null 2>&1; then
  echo "[BIDSPM Desktop] xvfb-run not found. Install xvfb, or run the app on a machine with a GUI display."
  exit 1
fi

echo "[BIDSPM Desktop] Launching Electron in virtual display (xvfb)."
echo "This is useful for smoke checks, not normal interactive desktop use."

exec xvfb-run -a --server-args='-screen 0 1920x1080x24' electron .