#!/bin/bash
# Real-world BIDSPM Performance Test - Optimized for Container Startup Performance
# Author: Karl Koschutnig, MRI Lab Graz
# Tests container startup and validation performance

set -e

echo "🚀 BIDSPM Container Performance Benchmark"
echo "=========================================="
echo "Test: Container startup + validation performance"
echo "Command: python bidspm.py -s config.json -c container.json"
echo "Test Date: $(date)"
echo ""

# Define containers to test
declare -a CONTAINERS=(
    "cpplab/bidspm:latest"
    "bidspm:mri-lab-graz" 
    "bidspm:performance-enhanced"
)

declare -a CONTAINER_NAMES=(
    "Original (cpplab/bidspm)"
    "Stable (mri-lab-graz)"
    "Enhanced (performance-optimized)"
)

# Check if containers exist
echo "🔍 Checking available containers..."
AVAILABLE_CONTAINERS=()
AVAILABLE_NAMES=()

for i in "${!CONTAINERS[@]}"; do
    container="${CONTAINERS[$i]}"
    if docker image inspect "$container" &>/dev/null; then
        echo "   ✅ $container - Available"
        AVAILABLE_CONTAINERS+=("$container")
        AVAILABLE_NAMES+=("${CONTAINER_NAMES[$i]}")
    else
        echo "   ❌ $container - Not found"
    fi
done

if [ ${#AVAILABLE_CONTAINERS[@]} -eq 0 ]; then
    echo "❌ No containers available for testing!"
    exit 1
fi

echo ""

# Backup original container.json
cp container.json container.json.backup

# Results file
RESULTS_FILE="performance_results_$(date +%Y%m%d_%H%M%S).txt"
echo "BIDSPM Container Performance Results - $(date)" > "$RESULTS_FILE"
echo "===============================================" >> "$RESULTS_FILE"
echo "Test: Container startup + data validation" >> "$RESULTS_FILE"
echo "Command: python bidspm.py -s config.json -c container.json" >> "$RESULTS_FILE"
echo "" >> "$RESULTS_FILE"

echo "📊 Testing ${#AVAILABLE_CONTAINERS[@]} containers..."
echo ""

# Test each available container
for i in "${!AVAILABLE_CONTAINERS[@]}"; do
    CONTAINER="${AVAILABLE_CONTAINERS[$i]}"
    CONTAINER_NAME="${AVAILABLE_NAMES[$i]}"
    
    echo "🧪 Test $((i+1))/${#AVAILABLE_CONTAINERS[@]}: $CONTAINER_NAME"
    echo "   Container: $CONTAINER"
    
    # Update container.json with current container
    cat > container.json << EOF
{
  "container_type": "docker",
  "docker_image": "$CONTAINER",
  "apptainer_image": "",
  "description": "Performance test container",
  "author": "Karl Koschutnig",
  "organization": "MRI Lab Graz"
}
EOF
    
    echo "   Status: Testing container startup and validation..."
    
    # Record start time
    START_TIME=$(date +%s)
    
    # Run BIDSPM and capture output (expecting validation failure - that's OK for timing)
    python bidspm.py -s config.json -c container.json > "test_output_${i}.log" 2>&1
    EXIT_CODE=$?
    
    # Record end time
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    
    # Check what happened
    if grep -q "Processing complete" "test_output_${i}.log"; then
        STATUS="COMPLETE"
        echo "   Status: ✅ Processing completed"
    elif grep -q "SPACE validation failed\|No BOLD files found" "test_output_${i}.log"; then
        STATUS="VALIDATION_EXPECTED"
        echo "   Status: ✅ Container startup successful (validation failed as expected)"
    elif grep -q "Error\|Failed\|Exception" "test_output_${i}.log"; then
        STATUS="ERROR" 
        echo "   Status: ❌ Container error"
    else
        STATUS="UNKNOWN"
        echo "   Status: ⚠️  Unknown result"
    fi
    
    echo "   Duration: ${DURATION} seconds"
    echo "   Exit Code: $EXIT_CODE"
    
    # Log to results file
    echo "$CONTAINER_NAME:" >> "$RESULTS_FILE"
    echo "  Container: $CONTAINER" >> "$RESULTS_FILE"
    echo "  Duration: ${DURATION} seconds" >> "$RESULTS_FILE"
    echo "  Status: $STATUS" >> "$RESULTS_FILE"
    echo "  Exit Code: $EXIT_CODE" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
    
    echo ""
    
    # Brief pause between tests
    sleep 1
done

# Restore original container.json
mv container.json.backup container.json

echo "📈 Performance Test Results"
echo "==========================="
echo ""

# Display results
while IFS= read -r line; do
    echo "$line"
done < "$RESULTS_FILE"

echo ""
echo "📁 Detailed Information"
echo "----------------------"
echo "Results file: $RESULTS_FILE"
echo "Log files:"
for i in "${!AVAILABLE_CONTAINERS[@]}"; do
    if [ -f "test_output_${i}.log" ]; then
        SIZE=$(du -h "test_output_${i}.log" | cut -f1)
        echo "  Container $((i+1)): test_output_${i}.log ($SIZE)"
    fi
done

echo ""
echo "🎯 Performance Summary"
echo "---------------------"

# Extract and display results
declare -a DURATIONS=()
declare -a STATUSES=()

for i in "${!AVAILABLE_CONTAINERS[@]}"; do
    CONTAINER_NAME="${AVAILABLE_NAMES[$i]}"
    DURATION=$(grep -A4 "$CONTAINER_NAME:" "$RESULTS_FILE" | grep "Duration:" | grep -o '[0-9]*')
    STATUS=$(grep -A4 "$CONTAINER_NAME:" "$RESULTS_FILE" | grep "Status:" | cut -d' ' -f3-)
    
    if [[ "$STATUS" == "VALIDATION_EXPECTED" || "$STATUS" == "COMPLETE" ]]; then
        echo "✅ $CONTAINER_NAME: ${DURATION}s (startup successful)"
        DURATIONS+=("$DURATION")
        STATUSES+=("SUCCESS")
    else
        echo "❌ $CONTAINER_NAME: ${DURATION}s ($STATUS)"
        DURATIONS+=("$DURATION")
        STATUSES+=("$STATUS")
    fi
done

# Find fastest successful container
if [ ${#DURATIONS[@]} -gt 1 ]; then
    echo ""
    echo "📊 Performance Comparison:"
    
    MIN_DURATION=999999
    MIN_INDEX=-1
    
    for i in "${!DURATIONS[@]}"; do
        if [[ "${STATUSES[$i]}" == "SUCCESS" && "${DURATIONS[$i]}" -lt "$MIN_DURATION" ]]; then
            MIN_DURATION=${DURATIONS[$i]}
            MIN_INDEX=$i
        fi
    done
    
    if [ $MIN_INDEX -ge 0 ]; then
        echo "🏆 Fastest: ${AVAILABLE_NAMES[$MIN_INDEX]} (${MIN_DURATION}s)"
        
        # Calculate speedup
        for i in "${!DURATIONS[@]}"; do
            if [ $i -ne $MIN_INDEX ] && [[ "${STATUSES[$i]}" == "SUCCESS" ]]; then
                SPEEDUP=$(( ${DURATIONS[$i]} - MIN_DURATION ))
                if [ $SPEEDUP -gt 0 ]; then
                    echo "   ${SPEEDUP}s faster than ${AVAILABLE_NAMES[$i]}"
                fi
            fi
        done
    fi
fi

echo ""
echo "💡 Test Notes:"
echo "   • This test measures container startup + BIDS validation time"
echo "   • Data validation failures are expected (no actual data processing)" 
echo "   • Focus is on container initialization performance"

echo ""
echo "✅ Performance benchmark completed!"
echo "📊 Check $RESULTS_FILE and log files for detailed analysis"
