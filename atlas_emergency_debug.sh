#!/bin/bash

# Atlas Error Emergency Debug
# Run this to test if our fixes work

echo "🚨 Atlas Error Emergency Debug"
echo "=============================="

# Update this path to your actual container
CONTAINER_PATH="/data/local/container/bidspm/bidspm_latest.sif"

echo "Testing container: $CONTAINER_PATH"
echo ""

if [ ! -f "$CONTAINER_PATH" ]; then
    echo "❌ Container not found. Please update CONTAINER_PATH in this script."
    exit 1
fi

echo "1. Testing MATLAB path with our environment..."
echo "   Expected: returnAtlasDir should be found"

apptainer exec \
    --containall \
    --cleanenv \
    --env "HOME=/tmp" \
    --env "MATLABPATH=/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/atlas:/opt/spm12" \
    "$CONTAINER_PATH" \
    bash -c "
echo 'MATLABPATH inside container:'
echo \$MATLABPATH
echo ''
octave --eval \"
fprintf('Testing returnAtlasDir accessibility...\\n');
if exist('returnAtlasDir', 'file') == 2
    fprintf('✅ SUCCESS: returnAtlasDir found in path\\n');
    try
        result = returnAtlasDir();
        fprintf('✅ SUCCESS: returnAtlasDir() executed, returned: %s\\n', result);
    catch ME
        fprintf('❌ ERROR: returnAtlasDir() call failed: %s\\n', ME.message);
    end
else
    fprintf('❌ ERROR: returnAtlasDir not found in path\\n');
    fprintf('Available functions with Atlas in name:\\n');
    which -all atlas
end
\"
"

echo ""
echo "2. Testing BIDSPM with atlas skip..."
echo "   Expected: Should skip atlas initialization"

apptainer run \
    --containall \
    --writable-tmpfs \
    --cleanenv \
    --env "HOME=/tmp" \
    --env "TMPDIR=/tmp" \
    --env "BIDSPM_SKIP_ATLAS_INIT=1" \
    --env "CPP_ROI_SKIP_ATLAS=1" \
    --env "MATLABPATH=/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/atlas:/opt/spm12" \
    "$CONTAINER_PATH" \
    --version 2>&1 | head -10

echo ""
echo "3. Full command simulation (what bidspm.py runs)..."

# Create temporary directories
TMP_DIR="/tmp/bidspm_debug_$$"
mkdir -p "$TMP_DIR"

apptainer run \
    --containall \
    --writable-tmpfs \
    --cleanenv \
    --bind "$TMP_DIR:/tmp" \
    --env "HOME=/tmp" \
    --env "TMPDIR=/tmp" \
    --env "TMP=/tmp" \
    --env "MATLAB_LOG_DIR=/tmp" \
    --env "SPM_HTML_BROWSER=0" \
    --env "BIDSPM_SKIP_ATLAS_INIT=1" \
    --env "OCTAVE_EXECUTABLE=/usr/bin/octave" \
    --env "MATLABPATH=/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/atlas:/opt/spm12" \
    --env "CPP_ROI_SKIP_ATLAS=1" \
    "$CONTAINER_PATH" \
    --help 2>&1 | head -20

# Cleanup
rm -rf "$TMP_DIR"

echo ""
echo "🎯 Analysis:"
echo "============"
echo "- If test 1 shows ✅ SUCCESS: Environment fix works"
echo "- If test 2 works: Atlas skip works"  
echo "- If test 3 fails: There's another issue"
echo ""
echo "Please run this and share the output!"
