#!/bin/bash

# BIDSPM Atlas Error Diagnostic Script
# Analyzes the specifiecho '📁 Looking for echo ""
echo "🔬 Checking function availability in container..."
echo "================================================"
apptainer exec "$TEST_SIF" bash -c "
cd /home/neuro/bidspm
echo '🧮 Testing Octave functionality:'

# Test basic Octave functionality
octave --eval 'disp("Octave working")' 2>/dev/null || echo 'Octave basic test failed'

echo ''
echo '📋 Checking MATLAB path setup:'
octave --eval 'path' 2>/dev/null | grep -E '(bidspm|CPP_ROI|spm)' || echo 'BIDSPM/SPM paths not in MATLAB path'

echo ''
echo '🔍 Looking for returnAtlasDir function:'
find /home/neuro/bidspm -name '*.m' -exec grep -l 'function.*returnAtlasDir' {} \; 2>/dev/null || echo 'returnAtlasDir function definition not found'

echo ''
echo '📁 Looking for returnAtlasDir.m file:'
find /home/neuro/bidspm -name 'returnAtlasDir.m' 2>/dev/null || echo 'returnAtlasDir.m file not found'

echo ''
echo '📂 Checking CPP_ROI atlas directory structure:'
ls -la /home/neuro/bidspm/lib/CPP_ROI/atlas/ 2>/dev/null || echo 'CPP_ROI atlas directory not found'

echo ''
echo '🧮 Testing MATLAB path with atlas directory:'
octave --eval "
addpath('/home/neuro/bidspm/lib/CPP_ROI/atlas');
if exist('returnAtlasDir', 'file')
    disp('✅ returnAtlasDir function accessible with explicit path');
    try
        atlasDir = returnAtlasDir();
        disp(['✅ returnAtlasDir() works, returns: ' atlasDir]);
    catch e
        disp(['❌ returnAtlasDir() call failed: ' e.message]);
    end
else
    disp('❌ returnAtlasDir function not accessible even with explicit path');
end
" 2>/dev/null || echo 'MATLAB test with explicit atlas path failed'
"rnAtlasDir.m file:'
find /home/neuro/bidspm -name 'returnAtlasDir.m' 2>/dev/null || echo 'returnAtlasDir.m file not found'

echo ''
echo '📂 Checking CPP_ROI atlas directory structure:'
ls -la /home/neuro/bidspm/lib/CPP_ROI/atlas/ 2>/dev/null || echo 'CPP_ROI atlas directory not found'

echo ''
echo '🧮 Testing MATLAB path with atlas directory:'
octave --eval '
addpath(\"/home/neuro/bidspm/lib/CPP_ROI/atlas\");
if exist(\"returnAtlasDir\", \"file\")
    disp(\"✅ returnAtlasDir function accessible with explicit path\");
    try
        atlasDir = returnAtlasDir();
        disp([\"✅ returnAtlasDir() works, returns: \" atlasDir]);
    catch e
        disp([\"❌ returnAtlasDir() call failed: \" e.message]);
    end
else
    disp(\"❌ returnAtlasDir function not accessible even with explicit path\");
end
' 2>/dev/null || echo 'MATLAB test with explicit atlas path failed'Dir' undefined error

echo "🔍 BIDSPM Atlas Error Diagnostic"
echo "================================"

# Configuration
BIDSPM_VERSION=${1:-"4.0.0"}  # Default to 4.0.0, can be overridden
CONTAINER_IMAGE="docker://cpplab/bidspm:${BIDSPM_VERSION}"
TEST_SIF="bidspm_debug_${BIDSPM_VERSION}.sif"

echo "🧪 Testing BIDSPM version: $BIDSPM_VERSION"
echo "📦 Container: $CONTAINER_IMAGE"
echo ""

# Pull container if needed
if [ ! -f "$TEST_SIF" ]; then
    echo "📥 Pulling container..."
    if ! apptainer pull --force "$TEST_SIF" "$CONTAINER_IMAGE"; then
        echo "❌ Failed to pull container"
        exit 1
    fi
fi

echo "🔍 Container inspection:"
echo "======================="
apptainer inspect "$TEST_SIF" | grep -E "(org.label-schema|Author|Description|Version)"
echo ""

echo "🗂️  Checking MATLAB/Octave paths in container..."
echo "================================================"
apptainer exec "$TEST_SIF" bash -c "
echo '📁 MATLAB/Octave installation:'
ls -la /usr/share/octave/ 2>/dev/null || echo 'No Octave found in /usr/share/octave'
ls -la /opt/spm12/ 2>/dev/null || echo 'No SPM12 found in /opt/spm12'
echo ''

echo '📁 BIDSPM installation:'
ls -la /home/neuro/bidspm/ 2>/dev/null || echo 'No BIDSPM found in /home/neuro/bidspm'
echo ''

echo '📁 CPP_ROI library:'
ls -la /home/neuro/bidspm/lib/CPP_ROI/ 2>/dev/null || echo 'No CPP_ROI found'
echo ''

echo '📁 Atlas directories:'
find /home/neuro/bidspm -name '*atlas*' -type d 2>/dev/null || echo 'No atlas directories found'
echo ''

echo '📁 Specific problem file:'
ls -la /home/neuro/bidspm/lib/CPP_ROI/src/atlas/copyAtlasToSpmDir.m 2>/dev/null || echo 'copyAtlasToSpmDir.m not found'
"

echo ""
echo "🔬 Checking function availability in container..."
echo "================================================"
apptainer exec "$TEST_SIF" bash -c "
cd /home/neuro/bidspm
echo '🧮 Testing Octave functionality:'

# Test basic Octave functionality
octave --eval 'disp(\"Octave working\")' 2>/dev/null || echo 'Octave basic test failed'

echo ''
echo '📋 Checking MATLAB path setup:'
octave --eval 'path' 2>/dev/null | grep -E '(bidspm|CPP_ROI|spm)' || echo 'BIDSPM/SPM paths not in MATLAB path'

echo ''
echo '🔍 Looking for returnAtlasDir function:'
find /home/neuro/bidspm -name '*.m' -exec grep -l 'function.*returnAtlasDir' {} \; 2>/dev/null || echo 'returnAtlasDir function definition not found'

echo ''
echo '� Looking for returnAtlasDir.m file:'
find /home/neuro/bidspm -name 'returnAtlasDir.m' 2>/dev/null || echo 'returnAtlasDir.m file not found'

echo ''
echo '�🔍 Checking if returnAtlasDir is called but not defined:'
grep -r 'returnAtlasDir' /home/neuro/bidspm/lib/CPP_ROI/ 2>/dev/null | head -10 || echo 'No references to returnAtlasDir found'

echo ''
echo '📂 CPP_ROI atlas directory structure:'
ls -la /home/neuro/bidspm/lib/CPP_ROI/atlas/ 2>/dev/null || echo 'CPP_ROI atlas directory not found'

echo ''
echo '🗂️ Checking if atlas directory should contain returnAtlasDir.m:'
find /home/neuro/bidspm/lib/CPP_ROI -name 'atlas' -type d -exec ls -la {} \; 2>/dev/null || echo 'No atlas directories found'
"

echo ""
echo "🛠️  Testing potential fixes..."
echo "============================="

# Test 1: Try with minimal BIDSPM call
echo "Test 1: Minimal BIDSPM version check"
if apptainer run --containall --cleanenv "$TEST_SIF" --version 2>&1 | grep -q "bidspm"; then
    echo "   ✅ Basic BIDSPM version check works"
else
    echo "   ❌ Basic BIDSPM version check fails"
fi

echo ""

# Test 2: Try with atlas skip environment variable
echo "Test 2: BIDSPM with atlas initialization skip"
if timeout 30 apptainer run --containall --cleanenv \
    --env "BIDSPM_SKIP_ATLAS_INIT=1" \
    --env "HOME=/tmp" \
    "$TEST_SIF" --version 2>&1 | grep -q "bidspm"; then
    echo "   ✅ BIDSPM with atlas skip works"
else
    echo "   ❌ BIDSPM with atlas skip still fails"
fi

echo ""

# Test 3: Check file permissions
echo "Test 3: File permission analysis"
apptainer exec "$TEST_SIF" bash -c "
echo '📋 Permission check:'
ls -la /home/neuro/bidspm/lib/CPP_ROI/src/atlas/ 2>/dev/null | head -10
echo ''
echo '📝 File accessibility:'
if [ -r '/home/neuro/bidspm/lib/CPP_ROI/src/atlas/copyAtlasToSpmDir.m' ]; then
    echo '   ✅ copyAtlasToSpmDir.m is readable'
else
    echo '   ❌ copyAtlasToSpmDir.m is not readable'
fi
"

echo ""
echo "💡 Diagnostic Summary:"
echo "====================="
echo "If 'returnAtlasDir' is undefined, this suggests:"
echo "1. Missing function definition in CPP_ROI library"
echo "2. MATLAB/Octave path configuration issue"
echo "3. Incomplete or corrupted container image"
echo "4. Version compatibility issue between BIDSPM and CPP_ROI"
echo ""
echo "🔧 Recommended fixes to try:"
echo "1. Use BIDSPM_SKIP_ATLAS_INIT=1 environment variable"
echo "2. Test different BIDSPM container versions"
echo "3. Mount writable atlas directories"
echo "4. Check if specific CPP_ROI version is needed"
echo ""

# Cleanup option
read -p "🗑️  Delete test container $TEST_SIF? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -f "$TEST_SIF"
    echo "   🗑️  Test container deleted"
fi
