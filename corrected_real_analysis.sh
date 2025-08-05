#!/bin/bash
# BIDSPM Real Processing Performance Test - Corrected Version
# Author: Karl Koschutnig, MRI Lab Graz
# Misst die tatsächliche Bearbeitungszeit der drei Container

echo "🚀 BIDSPM Processing Time Performance Test"
echo "=========================================="
echo "Test: Actual processing duration measurement"
echo "Date: $(date)"
echo ""

# Define containers to test
CONTAINERS=(
    "cpplab/bidspm:latest"
    "bidspm:mri-lab-graz" 
    "bidspm:performance-enhanced"
)

NAMES=(
    "Original (cpplab/bidspm)"
    "Stable (mri-lab-graz)"
    "Enhanced (performance-optimized)"
)

# Backup original files
cp config.json config.json.backup
cp container.json container.json.backup

RESULTS_FILE="processing_performance_$(date +%Y%m%d_%H%M%S).txt"
echo "BIDSPM Processing Performance Results - $(date)" > "$RESULTS_FILE"
echo "===============================================" >> "$RESULTS_FILE"
echo "Test: Actual processing time measurement" >> "$RESULTS_FILE"
echo "Command: python bidspm.py -s config.json -c container.json" >> "$RESULTS_FILE"
echo "" >> "$RESULTS_FILE"

echo "📊 Testing ${#CONTAINERS[@]} containers for actual processing time..."
echo ""

# Test each container
for i in "${!CONTAINERS[@]}"; do
    CONTAINER="${CONTAINERS[$i]}"
    NAME="${NAMES[$i]}"
    
    echo "🧪 Test $((i+1))/${#CONTAINERS[@]}: $NAME"
    echo "   Container: $CONTAINER"
    
    # Check if container exists
    if ! docker image inspect "$CONTAINER" &>/dev/null; then
        echo "   ❌ Container not found, skipping"
        continue
    fi
    
    # Update container.json
    cat > container.json << EOF
{
  "container_type": "docker",
  "docker_image": "$CONTAINER",
  "apptainer_image": "",
  "description": "Performance test",
  "author": "Karl Koschutnig",
  "organization": "MRI Lab Graz"
}
EOF
    
    # Update config.json with the correct container
    cat > config.json << EOF
{
  "WD": "/Volumes/Thunder/138",
  "BIDS_DIR": "/Volumes/Thunder/138/rawdata",
  "DERIVATIVES_DIR": "/Volumes/Thunder/138/derivatives",
  "FMRIPREP_DIR": "/Volumes/Thunder/138/derivatives/fmriprep",
  "DOCKER_IMAGE": "$CONTAINER",
  "SPACE": "MNI152NLin6Asym",
  "FWHM": 8,
  "SMOOTH": false,
  "STATS": true,
  "DATASET": false,
  "MODELS_FILE": "model_d1c.json",
  "TASKS": ["symbol"],
  "VERBOSITY": 2,
  "SUBJECTS": ["sub-138004"]
}
EOF
    
    echo "   ⏱️  Starting processing timer..."
    
    # TIC - Record start time (seconds only for compatibility)
    START_TIME=$(date +%s)
    
    # Run BIDSPM with actual processing
    echo "   🔄 Running BIDSPM processing..."
    python bidspm.py -s config.json -c container.json > "processing_${i}.log" 2>&1
    EXIT_CODE=$?
    
    # TOC - Record end time
    END_TIME=$(date +%s)
    
    # Calculate duration in seconds
    DURATION=$((END_TIME - START_TIME))
    
    # Check processing results
    if grep -q "All processing complete\|Processing complete" "processing_${i}.log"; then
        STATUS="✅ COMPLETED"
        echo "   ✅ Processing completed successfully"
    elif grep -q "SPACE validation failed\|No BOLD files found" "processing_${i}.log"; then
        STATUS="⚠️  VALIDATION FAILED"
        echo "   ⚠️  Processing stopped at validation (expected)"
    elif grep -q "Error\|Failed\|Exception" "processing_${i}.log"; then
        STATUS="❌ ERROR"
        echo "   ❌ Processing failed with error"
    else
        STATUS="❓ UNKNOWN"
        echo "   ❓ Unknown processing result"
    fi
    
    echo "   ⏱️  Processing time: ${DURATION} seconds"
    echo "   📊 Exit code: $EXIT_CODE"
    echo ""
    
    # Log results
    echo "$NAME:" >> "$RESULTS_FILE"
    echo "  Container: $CONTAINER" >> "$RESULTS_FILE"
    echo "  Processing Time: ${DURATION} seconds" >> "$RESULTS_FILE"
    echo "  Status: $STATUS" >> "$RESULTS_FILE"
    echo "  Exit Code: $EXIT_CODE" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
    
    # Brief pause between tests
    sleep 2
done

# Restore original files
mv config.json.backup config.json
mv container.json.backup container.json

echo "📈 Processing Performance Results"
echo "================================="
echo ""

# Display results
cat "$RESULTS_FILE"

echo ""
echo "🏆 Performance Comparison"
echo "========================"

# Extract processing times for comparison
declare -a TIMES=()
declare -a STATUSES=()

for i in "${!CONTAINERS[@]}"; do
    if [ -f "processing_${i}.log" ]; then
        TIME=$(grep -A5 "${NAMES[$i]}:" "$RESULTS_FILE" | grep "Processing Time:" | grep -o '[0-9]*')
        STATUS=$(grep -A5 "${NAMES[$i]}:" "$RESULTS_FILE" | grep "Status:" | cut -d' ' -f3-)
        
        if [ -n "$TIME" ]; then
            TIMES+=("$TIME")
            STATUSES+=("$STATUS")
            echo "📊 ${NAMES[$i]}: ${TIME}s ($STATUS)"
        fi
    fi
done

# Find fastest time
if [ ${#TIMES[@]} -gt 1 ]; then
    echo ""
    echo "🚀 Speed Analysis:"
    
    # Find minimum time
    MIN_TIME=$(printf '%s\n' "${TIMES[@]}" | sort -n | head -1)
    MIN_INDEX=-1
    
    for i in "${!TIMES[@]}"; do
        if [ "${TIMES[$i]}" = "$MIN_TIME" ]; then
            MIN_INDEX=$i
            break
        fi
    fi
    
    if [ $MIN_INDEX -ge 0 ]; then
        echo "🏆 Fastest: ${NAMES[$MIN_INDEX]} (${MIN_TIME}s)"
        
        # Calculate speedup for others
        for i in "${!TIMES[@]}"; do
            if [ $i -ne $MIN_INDEX ]; then
                SPEEDUP=$((${TIMES[$i]} - MIN_TIME))
                if [ $SPEEDUP -gt 0 ]; then
                    echo "   ${SPEEDUP}s slower than fastest"
                elif [ $SPEEDUP -eq 0 ]; then
                    echo "   Same speed as fastest"
                fi
            fi
        done
    fi
fi

echo ""
echo "📁 Detailed Information"
echo "----------------------"
echo "Results file: $RESULTS_FILE"
echo "Processing logs:"
for i in "${!CONTAINERS[@]}"; do
    if [ -f "processing_${i}.log" ]; then
        SIZE=$(du -h "processing_${i}.log" | cut -f1)
        LINES=$(wc -l < "processing_${i}.log")
        echo "  ${NAMES[$i]}: processing_${i}.log ($SIZE, $LINES lines)"
    fi
done

echo ""
echo "💡 Test Notes:"
echo "   • This test measures actual BIDSPM processing time"
echo "   • Each container processes the same configuration"
echo "   • Times include container startup + data processing"
echo "   • Second-precision timing (suitable for container performance)"

echo ""
echo "✅ Processing performance test completed!"
echo "📊 Check $RESULTS_FILE and processing logs for detailed analysis"
