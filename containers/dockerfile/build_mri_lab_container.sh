#!/bin/bash
# Build script for BIDSPM MRI Lab Graz Container
# Author: Karl Koschutnig

set -e

# The Dockerfile COPYs bidspm_overrides/ from the repo root, so the build
# context must be the repo root, not this directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Must match containers/container.json's "docker_image", or bidspm.py won't
# find the image it just built.
IMAGE_TAG="bidspm/bidspm:latest"

echo "🚀 Building BIDSPM Container for MRI Lab Graz"
echo "   Author: Karl Koschutnig"
echo "   Container: $IMAGE_TAG"
echo "   Features: Python 3.12 slim, Octave 8.x, BIDSPM 4.0, SPM12, UV"
echo ""

# Build the container
echo "📦 Starting Docker build..."
docker build -t "$IMAGE_TAG" -f "$SCRIPT_DIR/dockerfile" "$REPO_ROOT" --progress=plain

# Check build result
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Container build successful!"
    echo ""
    echo "🧪 Testing container..."
    docker run --rm --entrypoint octave "$IMAGE_TAG" --version
    echo ""
    echo "📋 Container ready to use:"
    echo "   docker run --rm $IMAGE_TAG"
    echo ""
    echo "🔬 For REAL SPM analysis, use:"
    echo "   python bidspm.py -s config/config.json -c containers/container.json"
    echo ""
else
    echo ""
    echo "❌ Container build failed!"
    echo "   Check the error messages above for details"
    exit 1
fi
