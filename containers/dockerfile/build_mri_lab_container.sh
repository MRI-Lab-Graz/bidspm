#!/bin/bash
# Build script for BIDSPM MRI Lab Graz Container
# Author: Karl Koschutnig

set -e

# The Dockerfile COPYs bidspm_overrides/ from the repo root, so the build
# context must be the repo root, not this directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "🚀 Building BIDSPM Container for MRI Lab Graz"
echo "   Author: Karl Koschutnig"
echo "   Container: bidspm:mri-lab-graz"
echo "   Features: Python 3.12 slim, Octave 8.x, BIDSPM 4.0, SPM12, UV"
echo ""

# Build the container
echo "📦 Starting Docker build..."
docker build -t bidspm:mri-lab-graz -f "$SCRIPT_DIR/dockerfile" "$REPO_ROOT" --progress=plain

# Check build result
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Container build successful!"
    echo ""
    echo "🧪 Testing container..."
    docker run --rm bidspm:mri-lab-graz octave --version
    echo ""
    echo "📋 Container ready to use:"
    echo "   docker run --rm bidspm:mri-lab-graz"
    echo ""
    echo "🔬 For REAL SPM analysis, use:"
    echo "   python enhanced_bidspm.py -s config.json -c container.json"
    echo ""
else
    echo ""
    echo "❌ Container build failed!"
    echo "   Check the error messages above for details"
    exit 1
fi
