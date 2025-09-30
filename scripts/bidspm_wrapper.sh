#!/bin/bash
# BIDSPM wrapper script that sets up proper Octave environment

# Determine project root relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Set up paths
export SPM12_PATH="$PROJECT_ROOT/external/spm12_standalone"
export BIDSPM_PATH="$PROJECT_ROOT/local_src/bidspm_local"
export MATLABPATH="$BIDSPM_PATH:$SPM12_PATH"
export BIDSPM_PROJECT_ROOT="$PROJECT_ROOT"
if [ -f "$PROJECT_ROOT/octave/octave_startup.m" ]; then
    export OCTAVE_SITE_INITFILE="$PROJECT_ROOT/octave/octave_startup.m"
fi

# Create Octave startup file that will be automatically loaded
mkdir -p ~/.octave
cat > ~/.octave/octaverc << 'EOF'
% Auto-setup for BIDSPM
warning('off', 'all');
spm12_path = getenv('SPM12_PATH');
bidspm_path = getenv('BIDSPM_PATH');
if ~isempty(spm12_path) && exist(spm12_path, 'dir')
    addpath(spm12_path);
end
if ~isempty(bidspm_path) && exist(bidspm_path, 'dir')
    addpath(bidspm_path);
    addpath(fullfile(bidspm_path, 'src'));
    addpath(genpath(fullfile(bidspm_path, 'lib')));
end
EOF

# Now run the actual BIDSPM CLI with all arguments passed through
source "$PROJECT_ROOT/.bidspm/bin/activate"
"$PROJECT_ROOT/.bidspm/bin/bidspm" "$@"