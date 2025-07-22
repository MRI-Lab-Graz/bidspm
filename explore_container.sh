#!/bin/bash

# Interactive BIDSPM Container Explorer
# Run this to get an interactive shell inside the BIDSPM container

echo "🔍 BIDSPM Container Interactive Explorer"
echo "======================================="

# Configuration
BIDSPM_IMAGE="docker://cpplab/bidspm:latest"
LOCAL_SIF_DIR="/data/local/container/bidspm"

echo "Available options:"
echo "1. Use Docker Hub image directly (slower first time)"
echo "2. Use local .sif file (if available)"
echo "3. Pull fresh container and explore"
echo ""

# Check for existing images
if [ -d "$LOCAL_SIF_DIR" ]; then
    EXISTING_IMAGES=$(find "$LOCAL_SIF_DIR" -name "*bidspm*.sif" 2>/dev/null)
    if [ -n "$EXISTING_IMAGES" ]; then
        echo "📁 Found existing BIDSPM images:"
        echo "$EXISTING_IMAGES" | nl -w2 -s') '
        echo ""
    fi
fi

read -p "🚀 Choose option (1-3) or press Enter for option 1: " choice

case $choice in
    2)
        if [ -n "$EXISTING_IMAGES" ]; then
            echo "Available .sif files:"
            echo "$EXISTING_IMAGES" | nl -w2 -s') '
            read -p "Select file number: " file_num
            SELECTED_SIF=$(echo "$EXISTING_IMAGES" | sed -n "${file_num}p")
            if [ -f "$SELECTED_SIF" ]; then
                echo "🐚 Starting interactive shell with: $(basename "$SELECTED_SIF")"
                echo ""
                echo "📝 Useful commands once inside:"
                echo "   ls -la /home/neuro/bidspm/lib/"
                echo "   find /home/neuro/bidspm -name 'returnAtlasDir.m'"
                echo "   ls -la /home/neuro/bidspm/lib/CPP_ROI/atlas/"
                echo "   bidspm --version"
                echo "   exit  # to leave the container"
                echo ""
                echo "🚀 Starting shell..."
                apptainer shell "$SELECTED_SIF"
            else
                echo "❌ Invalid selection"
                exit 1
            fi
        else
            echo "❌ No .sif files found"
            exit 1
        fi
        ;;
    3)
        echo "📥 Pulling fresh container..."
        TEMP_SIF="bidspm_explore_$(date +%s).sif"
        if apptainer pull "$TEMP_SIF" "$BIDSPM_IMAGE"; then
            echo "🐚 Starting interactive shell with fresh container"
            echo ""
            echo "📝 Useful commands once inside:"
            echo "   ls -la /home/neuro/bidspm/lib/"
            echo "   find /home/neuro/bidspm -name 'returnAtlasDir.m'"
            echo "   ls -la /home/neuro/bidspm/lib/CPP_ROI/atlas/"
            echo "   bidspm --version"
            echo "   exit  # to leave the container"
            echo ""
            echo "🚀 Starting shell..."
            apptainer shell "$TEMP_SIF"
            
            # Cleanup
            echo ""
            read -p "🗑️  Delete temporary container file $TEMP_SIF? (y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                rm -f "$TEMP_SIF"
                echo "   🗑️  Temporary container deleted"
            fi
        else
            echo "❌ Failed to pull container"
            exit 1
        fi
        ;;
    *)
        echo "🐚 Starting interactive shell with Docker Hub image (no local download)"
        echo ""
        echo "📝 Useful commands once inside:"
        echo "   ls -la /home/neuro/bidspm/lib/"
        echo "   find /home/neuro/bidspm -name 'returnAtlasDir.m'"
        echo "   ls -la /home/neuro/bidspm/lib/CPP_ROI/atlas/"
        echo "   bidspm --version"
        echo "   exit  # to leave the container"
        echo ""
        echo "🚀 Starting shell..."
        apptainer shell "$BIDSPM_IMAGE"
        ;;
esac

echo ""
echo "🎯 Container exploration completed!"
echo "💡 If you found missing files, that confirms the container packaging issue."
