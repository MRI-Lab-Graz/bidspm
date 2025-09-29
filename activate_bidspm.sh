#!/bin/bash
# Activation script for bidspm-runner environment

# Activate virtual environment
source .bidspm/bin/activate

echo "🚀 BIDSPM environment activated!"
echo "Python path: $(which python)"

# Apptainer environment variables
export APPTAINER_CACHEDIR="/data/local/apptainer_cache"
export APPTAINER_TMPDIR="/data/local/apptainer_tmp"
export TMPDIR="/data/local/apptainer_tmp"
echo "📦 Apptainer cache configured: $APPTAINER_CACHEDIR"

# Local BIDSPM environment
export SPM12_PATH="$(pwd)/external/spm12_standalone"
export BIDSPM_PATH="$(pwd)/local_src/bidspm_local"
echo "🧠 BIDSPM local environment configured"
echo "   SPM12: $SPM12_PATH"
echo "   BIDSPM: $BIDSPM_PATH"

echo ""
echo "To deactivate, run: deactivate"
