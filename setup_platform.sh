#!/bin/bash

# BIDSPM Multi-Platform Deployment Script

echo "🚀 BIDSPM Multi-Platform Setup"
echo "=============================="

# Detect platform
if [[ "$OSTYPE" == "darwin"* ]]; then
    PLATFORM="macos"
    echo "📱 Detected: macOS"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    PLATFORM="linux"
    echo "🐧 Detected: Linux"
else
    PLATFORM="unknown"
    echo "❓ Detected: Unknown platform ($OSTYPE)"
fi

# Copy appropriate container configuration
case $PLATFORM in
    "macos")
        echo "🐳 Setting up Docker configuration for macOS..."
        cp container.json container_active.json
        echo "✅ Docker configuration ready"
        echo "💡 Use: python bidspm.py -c container_active.json"
        ;;
    "linux")
        echo "🔍 Checking for container runtimes on Linux..."
        
        if command -v apptainer &> /dev/null; then
            echo "📦 Apptainer found - setting up for HPC environment"
            cp container_production.json container_active.json
            echo "✅ Apptainer configuration ready"
        elif command -v docker &> /dev/null; then
            echo "🐳 Docker found - setting up Docker configuration"
            cp container.json container_active.json
            echo "✅ Docker configuration ready"
        else
            echo "❌ Neither Apptainer nor Docker found!"
            echo "💡 Install one of them first:"
            echo "   - Apptainer: https://apptainer.org/docs/user/latest/quick_start.html"
            echo "   - Docker: https://docs.docker.com/engine/install/"
            exit 1
        fi
        ;;
    *)
        echo "⚠️  Unknown platform - defaulting to Docker"
        cp container.json container_active.json
        ;;
esac

echo ""
echo "🎯 Platform-specific setup complete!"
echo "💡 Usage:"
echo "   - Development/Piloting: python bidspm.py --pilot"
echo "   - Production: python bidspm.py -s your_config.json"
echo "   - Auto-detection: Script will automatically select the right container"
