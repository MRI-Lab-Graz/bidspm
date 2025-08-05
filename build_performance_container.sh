#!/bin/bash
# High-Performance BIDSPM Container Builder
# Author: Karl Koschutnig, MRI Lab Graz

echo "🚀 Building High-Performance BIDSPM Container"
echo "   Optimizations: Multi-core compilation, OpenBLAS, UV package manager"
echo "   Container: bidspm:performance"
echo ""

# Get number of available cores for parallel compilation
CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo "4")
echo "📊 Using $CORES CPU cores for compilation"

# Start Docker build with performance optimizations
echo "📦 Starting optimized Docker build..."
docker build \
    --file dockerfile.performance \
    --tag bidspm:performance \
    --build-arg CORES=$CORES \
    .

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ High-performance container build successful!"
    echo ""
    echo "🧪 Testing performance container..."
    docker run --rm bidspm:performance --version
    echo ""
    echo "📋 Performance container ready:"
    echo "   docker run --rm bidspm:performance"
    echo ""
    echo "🔬 For optimized analysis, update container.json:"
    echo "   Change docker_image to: bidspm:performance"
    echo ""
    echo "⚡ Performance improvements:"
    echo "   - Multi-core SPM12 compilation"
    echo "   - OpenBLAS optimized math libraries"
    echo "   - UV ultra-fast package manager"
    echo "   - Reduced container layers"
else
    echo "❌ Container build failed"
    exit 1
fi
