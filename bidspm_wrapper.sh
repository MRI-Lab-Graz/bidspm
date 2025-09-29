#!/bin/bash
# BIDSPM wrapper script that sets up proper Octave environment

# Set up paths
export SPM12_PATH="$(pwd)/external/spm12_standalone"
export BIDSPM_PATH="$(pwd)/local_src/bidspm_local"
export MATLABPATH="$BIDSPM_PATH:$SPM12_PATH"

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
source .bidspm/bin/activate
.bidspm/bin/bidspm "$@"
.bidspm/bin/bidspm "$@"