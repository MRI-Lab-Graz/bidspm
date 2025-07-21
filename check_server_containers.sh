#!/bin/bash

# Server Container Runtime Check Script

echo "🔍 Checking container runtimes on server..."
echo "=========================================="

# Check Docker
if command -v docker &> /dev/null; then
    echo "🐳 Docker: ✅ Available"
    docker --version
    
    # Check if user can run docker without sudo
    if docker ps &> /dev/null; then
        echo "   👤 User permissions: ✅ Can run without sudo"
        DOCKER_STATUS="ready"
    else
        echo "   👤 User permissions: ❌ Requires sudo (check with admin)"
        DOCKER_STATUS="needs_sudo"
    fi
else
    echo "🐳 Docker: ❌ Not available"
    DOCKER_STATUS="missing"
fi

echo ""

# Check Apptainer
if command -v apptainer &> /dev/null; then
    echo "📦 Apptainer: ✅ Available"
    apptainer --version
    APPTAINER_STATUS="ready"
elif command -v singularity &> /dev/null; then
    echo "📦 Singularity: ✅ Available (older version of Apptainer)"
    singularity --version
    APPTAINER_STATUS="singularity"
else
    echo "📦 Apptainer: ❌ Not available"
    APPTAINER_STATUS="missing"
fi

echo ""
echo "💡 Recommendations:"
echo "==================="

if [[ "$DOCKER_STATUS" == "ready" ]]; then
    echo "🎯 RECOMMENDED: Use Docker"
    echo "   - Same environment as your macOS development setup"
    echo "   - Easy to maintain and debug"
    echo "   - Consistent experience across platforms"
    echo ""
    echo "📝 Configuration: Use container.json (Docker config)"
elif [[ "$APPTAINER_STATUS" == "ready" || "$APPTAINER_STATUS" == "singularity" ]]; then
    echo "🎯 RECOMMENDED: Use Apptainer/Singularity"
    echo "   - Better suited for HPC environments"
    echo "   - No root privileges required"
    echo "   - Optimized for scientific computing"
    echo ""
    echo "📝 Configuration: Use container_production.json (Apptainer config)"
else
    echo "❌ No container runtime available"
    echo "💡 Install Docker or Apptainer first"
fi

echo ""
echo "🚀 To test with the current BIDSPM tool:"
if [[ "$DOCKER_STATUS" == "ready" ]]; then
    echo "   python bidspm.py -c container.json --pilot"
fi
if [[ "$APPTAINER_STATUS" == "ready" ]]; then
    echo "   python bidspm.py -c container_production.json --pilot"
fi
