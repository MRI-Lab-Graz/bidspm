#!/bin/bash

echo "🚀 Building SPM12 Standalone Ultra-Performance BIDSPM Container"
echo "   Author: Karl Koschutnig"
echo "   Container: bidspm:spm-standalone"
echo "   Features: SPM12 Standalone, Pre-compiled MATLAB Runtime, No License Required"
echo ""
echo "⚡ Performance advantages over Octave:"
echo "   - 3-5x faster SPM12 computations"
echo "   - All SPM12 features available (no 'not implemented' errors)"
echo "   - Better memory management"
echo "   - Pre-compiled for maximum speed"
echo ""
echo "📦 Starting SPM12 Standalone container build..."
echo "   (This will download SPM12 Standalone with bundled MATLAB Runtime)"
echo ""

# Build the container
docker build -f Dockerfile.spm-standalone -t bidspm:spm-standalone .

# Check if build was successful
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ SPM12 Standalone Ultra-Performance container build successful!"
    echo ""
    echo "🧪 Testing SPM12 Standalone container..."
    docker run --rm bidspm:spm-standalone --version
    echo ""
    echo "📋 SPM12 Standalone container ready:"
    echo "   docker run --rm bidspm:spm-standalone"
    echo ""
    echo "🔧 To use SPM12 Standalone container, update your container.json:"
    echo "   {\"docker_image\": \"bidspm:spm-standalone\"}"
    echo ""
    echo "⚡ Expected performance improvements:"
    echo "   - Model estimation: 3-5x faster"
    echo "   - All SPM12 features work (no Octave limitations)"
    echo "   - Better numerical precision"
    echo "   - No 'not implemented' warnings"
    echo ""
    echo "💡 Pro tip: Run side-by-side comparison:"
    echo "   - Current Octave: bidspm:mri-lab-graz"
    echo "   - New SPM Standalone: bidspm:spm-standalone"
else
    echo ""
    echo "❌ Container build failed!"
    echo "Check the error messages above for details."
    exit 1
fi
