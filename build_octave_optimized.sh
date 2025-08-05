#!/bin/bash
# Build optimized Octave BIDSPM container
# Author: Karl Koschutnig, MRI Lab Graz

echo "🚀 Building Performance-Optimized Octave BIDSPM Container"
echo "========================================================"

# Build with optimizations
docker build \
    --no-cache \
    --progress=plain \
    --file Dockerfile.simple-performance \
    --tag bidspm:simple-performance \
    .

echo ""
echo "✅ Performance-optimized container built successfully!"
echo "📦 Container: bidspm:simple-performance"
echo ""
echo "🧪 Testing container..."
docker run --rm bidspm:simple-performance octave --version
echo ""
echo "🎯 Performance improvements:"
echo "   ✅ Modern Octave (6.x+) from PPA"
echo "   ✅ OpenBLAS optimizations"
echo "   ✅ Multi-core SPM12 compilation"
echo "   ✅ Pre-loaded Octave packages"
echo "   ✅ Performance environment variables"
echo ""
echo "🔧 To use this container, update container.json:"
echo '   "docker_image": "bidspm:simple-performance"'
