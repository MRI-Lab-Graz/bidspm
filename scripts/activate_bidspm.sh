#!/bin/bash
# Activation script for bidspm-runner environment

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ ! -d "$PROJECT_ROOT/.bidspm" ]; then
    echo "❌ Virtual environment not found. Please run ./scripts/setup.sh first."
    return 1 2>/dev/null || exit 1
fi

source "$PROJECT_ROOT/.bidspm/bin/activate"

export BIDSPM_PROJECT_ROOT="$PROJECT_ROOT"

echo "🚀 BIDSPM environment activated!"
echo "Project root: $PROJECT_ROOT"
echo "Python path: $(which python)"

# Apptainer environment variables (respect pre-set values, e.g. on HPC)
: "${APPTAINER_CACHEDIR:=$PROJECT_ROOT/.apptainer_cache}"
: "${APPTAINER_TMPDIR:=$PROJECT_ROOT/.apptainer_tmp}"
export APPTAINER_CACHEDIR
export APPTAINER_TMPDIR
export TMPDIR="$APPTAINER_TMPDIR"
echo "📦 Apptainer cache configured: $APPTAINER_CACHEDIR"

echo ""
echo "To deactivate, run: deactivate"
