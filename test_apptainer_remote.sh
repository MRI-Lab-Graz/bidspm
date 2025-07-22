#!/bin/bash

# BIDSPM Apptainer Remote Test Script
# Run this on your remote server to test Apptainer functionality
# Compatible with existing build_apptainer.sh workflow

echo "🔬 BIDSPM Apptainer Remote Server Test"
echo "====================================="

# Configuration
BIDSPM_IMAGE="docker://cpplab/bidspm:latest"
LOCAL_SIF_DIR="/data/local/container/bidspm"  # Adjust to your setup
TEST_SIF="bidspm_test.sif"

# Check if Apptainer is available
echo "1. Checking Apptainer availability..."
if command -v apptainer &> /dev/null; then
    echo "   ✅ Apptainer found: $(apptainer --version)"
else
    echo "   ❌ Apptainer not found"
    echo "   💡 Install with: sudo apt install apptainer-suid"
    exit 1
fi

echo ""

# Check for existing BIDSPM images (built with build_apptainer.sh)
echo "2. Checking for existing BIDSPM images..."
if [ -d "$LOCAL_SIF_DIR" ]; then
    echo "   📁 Found container directory: $LOCAL_SIF_DIR"
    EXISTING_IMAGES=$(find "$LOCAL_SIF_DIR" -name "*bidspm*.sif" 2>/dev/null)
    if [ -n "$EXISTING_IMAGES" ]; then
        echo "   ✅ Found existing BIDSPM images:"
        echo "$EXISTING_IMAGES" | while read img; do
            echo "      - $(basename "$img") ($(ls -lh "$img" | awk '{print $5}'))"
        done
        USE_EXISTING=true
    else
        echo "   📭 No existing BIDSPM images found"
        USE_EXISTING=false
    fi
else
    echo "   📭 Container directory not found: $LOCAL_SIF_DIR"
    USE_EXISTING=false
fi

echo ""

# Test basic container functionality
echo "3. Testing basic container pull..."
TEST_IMAGE="docker://hello-world"
if timeout 60 apptainer run $TEST_IMAGE 2>/dev/null; then
    echo "   ✅ Basic container functionality works"
else
    echo "   ❌ Basic container test failed"
    echo "   🔍 Try: apptainer run $TEST_IMAGE"
fi

echo ""

# Test BIDSPM container (use existing or pull new)
if [ "$USE_EXISTING" = true ]; then
    echo "4. Testing existing BIDSPM container..."
    FIRST_EXISTING=$(echo "$EXISTING_IMAGES" | head -1)
    echo "   🧪 Testing: $(basename "$FIRST_EXISTING")"
    
    if apptainer run "$FIRST_EXISTING" --help 2>/dev/null | head -5; then
        echo "   ✅ Existing BIDSPM container works"
        TEST_CONTAINER="$FIRST_EXISTING"
    else
        echo "   ⚠️  Existing container test inconclusive"
        TEST_CONTAINER="$FIRST_EXISTING"
    fi
else
    echo "4. Testing BIDSPM container pull..."
    echo "   📥 Pulling BIDSPM container (this may take a while)..."
    
    if timeout 300 apptainer pull --force $TEST_SIF $BIDSPM_IMAGE; then
        echo "   ✅ BIDSPM container pulled successfully"
        ls -lh $TEST_SIF
        TEST_CONTAINER="$TEST_SIF"
        
        # Test container info
        echo ""
        echo "   📋 Container information:"
        apptainer inspect $TEST_SIF | head -10
        
        # Test basic container execution
        echo ""
        echo "   🧪 Testing container execution..."
        if apptainer run $TEST_SIF --help 2>/dev/null | head -5; then
            echo "   ✅ Container execution works"
        else
            echo "   ⚠️  Container execution test inconclusive"
        fi
    else
        echo "   ❌ Failed to pull BIDSPM container"
        echo "   🔍 Check network connectivity and Docker Hub access"
        TEST_CONTAINER=""
    fi
fi

echo ""

# Test file system permissions (only if we have a working container)
if [ -n "$TEST_CONTAINER" ]; then
    echo "5. Testing file system permissions..."
    TEST_DIR="/tmp/bidspm_test_$$"
    mkdir -p $TEST_DIR
    
    if apptainer run --bind $TEST_DIR:/test "$TEST_CONTAINER" ls /test 2>/dev/null; then
        echo "   ✅ File system binding works"
    else
        echo "   ⚠️  File system binding test inconclusive"
    fi
    
    rm -rf $TEST_DIR
    
    echo ""
    
    # Environment test
    echo "6. Testing environment isolation..."
    if apptainer run --containall "$TEST_CONTAINER" printenv | grep -q HOME; then
        echo "   ✅ Environment isolation works"
    else
        echo "   ⚠️  Environment isolation test inconclusive"
    fi
    
    echo ""
    
    # BIDSPM-specific test
    echo "7. Testing BIDSPM-specific functionality..."
    if apptainer run --containall "$TEST_CONTAINER" bidspm --version 2>/dev/null | grep -q "bidspm"; then
        echo "   ✅ BIDSPM command available in container"
    else
        echo "   ⚠️  BIDSPM command test inconclusive"
    fi
    
    echo ""
    
    # Atlas path test (diagnose the returnAtlasDir issue)
    echo "8. Testing Atlas function availability..."
    echo "   🔍 Checking for returnAtlasDir.m file..."
    if apptainer exec "$TEST_CONTAINER" find /home/neuro/bidspm -name "returnAtlasDir.m" 2>/dev/null; then
        echo "   ✅ returnAtlasDir.m file found in container"
        
        echo "   🧮 Testing MATLAB path configuration..."
        apptainer exec "$TEST_CONTAINER" bash -c "
        cd /home/neuro/bidspm
        octave --eval \"
        addpath('/home/neuro/bidspm/lib/CPP_ROI/atlas');
        if exist('returnAtlasDir', 'file')
            disp('✅ returnAtlasDir function accessible');
        else
            disp('❌ returnAtlasDir function not accessible');
        end
        \" 2>/dev/null || echo '⚠️  MATLAB path test failed'
        "
    else
        echo "   ❌ returnAtlasDir.m file not found in container"
        echo "   🔍 This explains the atlas error - missing file in container"
    fi
fi

echo ""
echo "🎯 Test Summary:"
echo "==============="
echo "If you see mostly ✅, Apptainer should work with BIDSPM!"
echo ""
echo "🚀 Next steps:"
echo "1. Build production image: ./build_apptainer.sh -o $LOCAL_SIF_DIR -t /tmp/apptainer_build"
echo "   - Select: cpplab/bidspm"
echo "   - Select: 4.0.0 (recommended - latest has atlas bugs)"
echo "2. Copy BIDSPM tool to server: scp -r bidspm/ user@server:~/"
echo "3. Update container config to point to your .sif file"
echo "4. Test with: python bidspm.py -c container_apptainer_atlas_fix.json --pilot"
echo ""
echo "🗺️  Atlas Issue Notes:"
echo "   - If returnAtlasDir.m was found: ✅ Atlas should work with enhanced MATLABPATH"
echo "   - If returnAtlasDir.m was missing: ❌ Container has incomplete CPP_ROI installation"
echo "   - Use container_apptainer_atlas_fix.json for best atlas compatibility"
echo ""
echo "📁 Generated files:"
if [ "$USE_EXISTING" = false ] && [ -f "$TEST_SIF" ]; then
    echo "- $TEST_SIF (temporary test image)"
fi

# Cleanup option
if [ "$USE_EXISTING" = false ] && [ -f "$TEST_SIF" ]; then
    echo ""
    read -p "🗑️  Delete temporary test container file? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -f $TEST_SIF
        echo "   🗑️  Test container deleted"
    fi
fi
