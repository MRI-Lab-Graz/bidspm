#!/bin/bash
# Setup script for Apptainer with custom temporary directory

# Set Apptainer cache and temp directories to use /data/local space
export APPTAINER_CACHEDIR="/data/local/apptainer_cache"
export APPTAINER_TMPDIR="/data/local/apptainer_tmp" 
export TMPDIR="/data/local/apptainer_tmp"

# Create directories if they don't exist
mkdir -p "$APPTAINER_CACHEDIR"
mkdir -p "$APPTAINER_TMPDIR"

# Print current settings
echo "🔧 Apptainer Environment Setup:"
echo "   Cache Directory: $APPTAINER_CACHEDIR"
echo "   Temp Directory: $APPTAINER_TMPDIR"
echo "   Available space: $(df -h /data/local | tail -1 | awk '{print $4}')"

# Check if SIF file already exists
SIF_FILE="/data/local/apptainer_cache/bidspm_latest.sif"
if [ -f "$SIF_FILE" ]; then
    echo "✅ SIF file already exists: $SIF_FILE"
    echo "   Size: $(du -h "$SIF_FILE" | cut -f1)"
else
    echo "📦 SIF file will be created: $SIF_FILE"
fi