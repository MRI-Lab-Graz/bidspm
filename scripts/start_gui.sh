#!/usr/bin/env bash
# Start the BIDSPM web GUI inside the project's virtual environment.
#   ./scripts/start_gui.sh [bidspm_gui.py options]      e.g. --host 0.0.0.0, --no-browser
# Port: $BIDSPM_PORT (default 5100). Venv: $BIDSPM_VENV (default <repo>/.bidspm).
# Over VS Code Remote SSH the browser is opened by VS Code's port forwarding (see README); on a desktop
# the GUI opens it itself.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${BIDSPM_VENV:-$ROOT/.bidspm}"

if [ ! -f "$VENV/bin/activate" ]; then
    echo "❌ Virtual environment not found at $VENV. Run ./scripts/setup.sh first." >&2
    exit 1
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
cd "$ROOT"
exec python bidspm_gui.py -p "${BIDSPM_PORT:-5100}" "$@"
