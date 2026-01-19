#!/bin/bash

# Configuration
RAW_DIR="/data/local/132"
FMRIPREP_DIR="/data/local/132/derivatives/fmriprep"

echo "🔧 preparing fMRIPrep directory for BIDSPM..."

# 1. Link dataset_description.json (if missing or update name)
# fMRIPrep has its own, which is fine.

# 2. Link participants.tsv and participants.json
if [ -f "$RAW_DIR/participants.tsv" ]; then
    echo "🔗 Linking participants.tsv..."
    ln -sf "$RAW_DIR/participants.tsv" "$FMRIPREP_DIR/participants.tsv"
    ln -sf "$RAW_DIR/participants.json" "$FMRIPREP_DIR/participants.json"
fi

# 3. Link event files for all subjects
echo "🔗 Linking event files..."
find "$RAW_DIR" -name "*_events.tsv" | while read event_file; do
    # Construct relative path from raw root
    rel_path="${event_file#$RAW_DIR/}"
    
    # Target path in fmriprep
    target_path="$FMRIPREP_DIR/$rel_path"
    target_dir=$(dirname "$target_path")
    
    # Check if target directory exists (it should if fmriprep ran for this sub/ses)
    if [ -d "$target_dir" ]; then
        ln -sf "$event_file" "$target_path"
        # Also link JSON sidecar if exists
        json_file="${event_file%.tsv}.json"
        if [ -f "$json_file" ]; then
            ln -sf "$json_file" "${target_path%.tsv}.json"
        fi
    fi
done

echo "✅ fMRIPrep directory is ready."
echo "👉 Now, please update your configuration:"
echo "   Set 'BIDS Folder' to: $FMRIPREP_DIR"
