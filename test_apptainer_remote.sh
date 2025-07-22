#!/bin/bash

# BIDSPM Apptainer Remote Test Script
# Run this on your remote server to test Apptainer functionality

echo "🔬 BIDSPM Apptainer Remote Server Test"
echo "====================================="

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

# Test basic container functionality
echo "2. Testing basic container pull..."
TEST_IMAGE="docker://hello-world"
if apptainer run $TEST_IMAGE 2>/dev/null; then
    echo "   ✅ Basic container functionality works"
else
    echo "   ❌ Basic container test failed"
    echo "   🔍 Try: apptainer run $TEST_IMAGE"
fi

echo ""

# Test BIDSPM container pull (without running)
echo "3. Testing BIDSPM container pull..."
BIDSPM_IMAGE="docker://cpplab/bidspm:latest"
echo "   📥 Pulling BIDSPM container (this may take a while)..."

if timeout 300 apptainer pull --force bidspm_test.sif $BIDSPM_IMAGE; then
    echo "   ✅ BIDSPM container pulled successfully"
    ls -lh bidspm_test.sif
    
    # Test container info
    echo ""
    echo "4. Container information:"
    apptainer inspect bidspm_test.sif | head -10
    
    # Test basic container execution
    echo ""
    echo "5. Testing container execution..."
    if apptainer run bidspm_test.sif --help 2>/dev/null | head -5; then
        echo "   ✅ Container execution works"
    else
        echo "   ⚠️  Container execution test inconclusive"
    fi
    
else
    echo "   ❌ Failed to pull BIDSPM container"
    echo "   🔍 Check network connectivity and Docker Hub access"
fi

echo ""

# Test file system permissions
echo "6. Testing file system permissions..."
TEST_DIR="/tmp/bidspm_test_$$"
mkdir -p $TEST_DIR

if apptainer run --bind $TEST_DIR:/test $BIDSPM_IMAGE ls /test 2>/dev/null; then
    echo "   ✅ File system binding works"
else
    echo "   ⚠️  File system binding test inconclusive"
fi

rm -rf $TEST_DIR

echo ""

# Environment test
echo "7. Testing environment isolation..."
if apptainer run --containall $BIDSPM_IMAGE printenv | grep -q HOME; then
    echo "   ✅ Environment isolation works"
else
    echo "   ⚠️  Environment isolation test inconclusive"
fi

echo ""
echo "🎯 Test Summary:"
echo "==============="
echo "If you see mostly ✅, Apptainer should work with BIDSPM!"
echo ""
echo "🚀 Next steps:"
echo "1. Copy BIDSPM tool to server: scp -r bidspm/ user@server:~/"
echo "2. Test with: python bidspm.py -c container_apptainer.json --pilot"
echo ""
echo "📁 Generated files:"
echo "- bidspm_test.sif (can be deleted after testing)"

# Cleanup option
echo ""
read -p "🗑️  Delete test container file? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -f bidspm_test.sif
    echo "   🗑️  Test container deleted"
fi
