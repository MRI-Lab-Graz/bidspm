#!/bin/bash

# Development Version Fix Test
echo "🔬 Development Version Atlas Fix"
echo "==============================="

CONTAINER_PATH="/data/local/container/bidspm/bidspm_latest.sif"

echo "1. Finding all returnAtlasDir.m files..."
apptainer exec "$CONTAINER_PATH" find /home/neuro -name "returnAtlasDir.m" -type f

echo ""
echo "2. Checking CPP_ROI structure in dev version..."
apptainer exec "$CONTAINER_PATH" ls -la /home/neuro/bidspm/lib/CPP_ROI/

echo ""
echo "3. Testing with function location discovery..."
ATLAS_FILE=$(apptainer exec "$CONTAINER_PATH" find /home/neuro -name "returnAtlasDir.m" -type f | head -1)
if [ -n "$ATLAS_FILE" ]; then
    ATLAS_DIR=$(dirname "$ATLAS_FILE")
    echo "Found returnAtlasDir.m in: $ATLAS_DIR"
    
    echo ""
    echo "4. Testing with discovered path..."
    apptainer exec \
        --containall \
        --cleanenv \
        --env "MATLABPATH=/home/neuro/bidspm:$ATLAS_DIR:/opt/spm12" \
        "$CONTAINER_PATH" \
        octave --eval "
        fprintf('Testing with discovered path: $ATLAS_DIR\n');
        if exist('returnAtlasDir', 'file') == 2
            fprintf('✅ SUCCESS: returnAtlasDir found!\n');
        else
            fprintf('❌ Still not found\n');
        end
        "
else
    echo "❌ returnAtlasDir.m not found anywhere!"
fi

echo ""
echo "5. Alternative: Try skipping atlas completely..."
apptainer run \
    --containall \
    --writable-tmpfs \
    --cleanenv \
    --env "HOME=/tmp" \
    --env "BIDSPM_SKIP_ATLAS_INIT=1" \
    --env "CPP_ROI_SKIP_ATLAS=1" \
    --env "SKIP_ATLAS=1" \
    --env "NO_ATLAS=1" \
    "$CONTAINER_PATH" \
    --version 2>&1 | head -5
