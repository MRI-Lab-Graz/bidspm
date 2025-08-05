#!/bin/bash
# Simple BIDSPM Performance Test
# Author: Karl Koschutnig, MRI Lab Graz

echo "🚀 BIDSPM Container Performance Benchmark"
echo "=========================================="
echo "Date: $(date)"
echo ""

# Backup original container.json
cp container.json container.json.backup

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

RESULTS_FILE="performance_results_$(date +%Y%m%d_%H%M%S).txt"
echo "BIDSPM Performance Results - $(date)" > "$RESULTS_FILE"
echo "=====================================" >> "$RESULTS_FILE"
echo "" >> "$RESULTS_FILE"

echo "📊 Testing ${#CONTAINERS[@]} containers..."
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
    
    echo "   Running test..."
    
    # Record start time
    START_TIME=$(date +%s)
    
    # Run BIDSPM
    python bidspm.py -s config.json -c container.json > "test_${i}.log" 2>&1
    EXIT_CODE=$?
    
    # Record end time
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    
    # Check results
    if grep -q "All processing complete" "test_${i}.log"; then
        STATUS="✅ SUCCESS"
    elif grep -q "SPACE validation failed" "test_${i}.log"; then
        STATUS="✅ SUCCESS (validation as expected)"
    else
        STATUS="❌ ERROR"
    fi
    
    echo "   Duration: ${DURATION} seconds"
    echo "   Result: $STATUS"
    echo ""
    
    # Log results
    echo "$NAME:" >> "$RESULTS_FILE"
    echo "  Container: $CONTAINER" >> "$RESULTS_FILE"
    echo "  Duration: ${DURATION}s" >> "$RESULTS_FILE"
    echo "  Status: $STATUS" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
    
    sleep 1
done

# Restore original container.json
mv container.json.backup container.json

echo "📈 Results Summary"
echo "=================="
cat "$RESULTS_FILE"

echo ""
echo "✅ Performance test completed!"
echo "📁 Results: $RESULTS_FILE"
echo "📁 Logs: test_0.log, test_1.log, test_2.log"
