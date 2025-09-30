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

# Apptainer environment variables
export APPTAINER_CACHEDIR="/data/local/apptainer_cache"
export APPTAINER_TMPDIR="/data/local/apptainer_tmp"
export TMPDIR="/data/local/apptainer_tmp"
echo "📦 Apptainer cache configured: $APPTAINER_CACHEDIR"

# Local Octave installation
if [ -d "$PROJECT_ROOT/external/octave/bin" ]; then
	export PATH="$PROJECT_ROOT/external/octave/bin:$PATH"
	export LD_LIBRARY_PATH="$PROJECT_ROOT/external/octave/lib:$PROJECT_ROOT/external/octave/lib/octave/8.4.0:$LD_LIBRARY_PATH"
	echo "🔧 Local Octave added to PATH: $PROJECT_ROOT/external/octave/bin"
fi

# Local BIDSPM environment
export SPM12_PATH="$PROJECT_ROOT/external/spm12_standalone"
export BIDSPM_PATH="$PROJECT_ROOT/local_src/bidspm_local"
export SPM_HOME="$SPM12_PATH"
export SPM_STANDALONE_HOME="$SPM12_PATH"
export BIDSPM_SKIP_OCTAVE_FORGE=1

if [ -d "$BIDSPM_PATH/src" ]; then
	export MATLABPATH="$BIDSPM_PATH:$BIDSPM_PATH/src:$SPM12_PATH:${MATLABPATH}"
	export OCTAVE_PATH="$BIDSPM_PATH:$BIDSPM_PATH/src:$BIDSPM_PATH/lib:$SPM12_PATH:${OCTAVE_PATH}"
fi

if [ -f "$PROJECT_ROOT/octave/octave_startup.m" ]; then
	export OCTAVE_SITE_INITFILE="$PROJECT_ROOT/octave/octave_startup.m"
fi

echo "🧠 BIDSPM local environment configured"
echo "   SPM12: $SPM12_PATH"
echo "   BIDSPM: $BIDSPM_PATH"

echo ""
echo "To deactivate, run: deactivate"
