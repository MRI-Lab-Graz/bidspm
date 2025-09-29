#!/bin/bash
# Build performance-enhanced layer on top of working container
# Author: Karl Koschutnig, MRI Lab Graz

echo "⚡ Building Performance-Enhanced BIDSPM Container"
echo "==============================================="
echo "Base: bidspm:mri-lab-graz (working foundation)"
echo ""

# Build performance layer
docker build \
    --no-cache \
    --progress=plain \
    --file Dockerfile.performance-layer \
    --tag bidspm:performance-enhanced \
    .

echo ""
echo "✅ Performance-enhanced container built successfully!"
echo "📦 Container: bidspm:performance-enhanced"
echo ""
echo "🧪 Testing performance enhancements..."
docker run --rm --entrypoint="" bidspm:performance-enhanced /usr/local/bin/test-performance
echo ""
echo "🎯 Performance improvements:"
echo "   ✅ Optimized threading (4 cores)"
echo "   ✅ Enhanced BLAS configuration"
echo "   ✅ Suppressed warning spam"
echo "   ✅ Pre-loaded critical packages"
echo "   ✅ Faster startup configuration"
echo ""
echo "🔧 To use this container, update container.json:"
echo '   "docker_image": "bidspm:performance-enhanced"'
