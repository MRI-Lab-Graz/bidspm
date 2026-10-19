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

# A venv whose interpreter is missing or dangling (e.g. it was built from a Python that has since moved) would
# silently fall through to whatever `python` comes first on PATH. Refuse it instead.
if ! "$VENV/bin/python" -c "import sys" 2>/dev/null; then
    echo "❌ $VENV/bin/python does not work (missing or dangling). Run ./scripts/setup.sh to rebuild the venv." >&2
    exit 1
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
cd "$ROOT"
export PYTHONUNBUFFERED=1   # the startup self-check must show up in a redirected log, not at exit
exec "$VENV/bin/python" bidspm_gui.py -p "${BIDSPM_PORT:-5100}" "$@"
