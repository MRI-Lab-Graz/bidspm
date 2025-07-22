#!/bin/bash
# BIDSPM-specific wrapper for build_apptainer.sh

# Default paths for BIDSPM
BIDSPM_OUTPUT_DIR="/data/local/container/bidspm"
BIDSPM_TEMP_DIR="/tmp/apptainer_bidspm"
BIDSPM_REPO="cpplab/bidspm"

echo "🧠 BIDSPM Apptainer Image Builder"
echo "================================"

# Check if build_apptainer.sh exists
if [ ! -f "./build_apptainer.sh" ]; then
    echo "❌ build_apptainer.sh not found in current directory"
    exit 1
fi

echo "📋 Building BIDSPM image with the following settings:"
echo "   Repository: $BIDSPM_REPO"
echo "   Output Directory: $BIDSPM_OUTPUT_DIR"
echo "   Temp Directory: $BIDSPM_TEMP_DIR"
echo ""

# Create directories if they don't exist
mkdir -p "$BIDSPM_OUTPUT_DIR"
mkdir -p "$BIDSPM_TEMP_DIR"

# Run the build script with pre-filled inputs
echo "$BIDSPM_REPO" | ./build_apptainer.sh -o "$BIDSPM_OUTPUT_DIR" -t "$BIDSPM_TEMP_DIR"

echo ""
echo "✅ BIDSPM build completed!"
echo "🔍 Run './test_apptainer_remote.sh' to validate the installation"
