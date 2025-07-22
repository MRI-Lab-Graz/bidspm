#!/bin/bash

# BIDSPM Version Test Script
# Tests different BIDSPM container versions to find a working one

echo "🔍 BIDSPM Container Version Tester"
echo "=================================="

# Available BIDSPM versions to test (add more as needed)
VERSIONS=(
    "4.0.0"
    "3.2.1" 
    "3.2.0"
    "3.1.0"
    "latest"
)

BIDSPM_REPO="cpplab/bidspm"
TEST_DIR="/tmp/bidspm_version_test_$$"
mkdir -p "$TEST_DIR"

echo "🧪 Testing different BIDSPM container versions..."
echo "Looking for a version without the 'returnAtlasDir' bug"
echo ""

for VERSION in "${VERSIONS[@]}"; do
    echo "📦 Testing version: $VERSION"
    
    # Pull the specific version
    SIF_FILE="$TEST_DIR/bidspm_${VERSION}.sif"
    DOCKER_IMAGE="docker://${BIDSPM_REPO}:${VERSION}"
    
    echo "   📥 Pulling $DOCKER_IMAGE..."
    if timeout 180 apptainer pull "$SIF_FILE" "$DOCKER_IMAGE" &>/dev/null; then
        echo "   ✅ Successfully pulled"
        
        # Test basic execution
        echo "   🧪 Testing basic execution..."
        if timeout 30 apptainer run "$SIF_FILE" --help &>/dev/null; then
            echo "   ✅ Basic execution works"
            
            # Test with a minimal command that might trigger the atlas error
            echo "   🔬 Testing for atlas initialization..."
            TEST_OUTPUT=$(timeout 60 apptainer run --containall "$SIF_FILE" bidspm --version 2>&1)
            
            if echo "$TEST_OUTPUT" | grep -q "returnAtlasDir"; then
                echo "   ❌ Contains returnAtlasDir bug"
            elif echo "$TEST_OUTPUT" | grep -q "bidspm\|version"; then
                echo "   ✅ No atlas bug detected - VERSION $VERSION LOOKS GOOD!"
                echo "   📋 Output: $(echo "$TEST_OUTPUT" | head -1)"
                WORKING_VERSION="$VERSION"
            else
                echo "   ⚠️  Inconclusive test result"
            fi
        else
            echo "   ❌ Basic execution failed"
        fi
    else
        echo "   ❌ Failed to pull"
    fi
    
    echo ""
done

# Cleanup test files
rm -rf "$TEST_DIR"

echo "🎯 Test Results Summary:"
echo "======================"
if [ -n "$WORKING_VERSION" ]; then
    echo "✅ RECOMMENDED VERSION: $WORKING_VERSION"
    echo ""
    echo "🔧 To use this version:"
    echo "1. Update your container configs:"
    echo "   - docker://cpplab/bidspm:$WORKING_VERSION"
    echo "2. Rebuild with: ./build_apptainer.sh"
    echo "3. Select tag: $WORKING_VERSION"
else
    echo "❌ No working version found"
    echo "💡 Recommendations:"
    echo "1. Check BIDSPM GitHub releases for known working versions"
    echo "2. Report the bug to: https://github.com/cpp-lln-lab/bidspm/issues"
    echo "3. Try older stable versions manually"
fi
