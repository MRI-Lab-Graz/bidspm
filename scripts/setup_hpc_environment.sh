#!/bin/bash
# HPC Environment Setup for BIDSPM Local Execution
# This script sets up the environment for running BIDSPM locally

# Determine project root relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export BIDSPM_PROJECT_ROOT="$PROJECT_ROOT"
export SPM12_PATH="$PROJECT_ROOT/external/spm12_standalone"
export BIDSPM_PATH="$PROJECT_ROOT/local_src/bidspm_local"
export SPM_HOME="$SPM12_PATH"
export SPM_STANDALONE_HOME="$SPM12_PATH"

if [ -d "$PROJECT_ROOT/local_src/bidspm_local/src" ]; then
    export MATLABPATH="$PROJECT_ROOT/local_src/bidspm_local:$PROJECT_ROOT/local_src/bidspm_local/src:$PROJECT_ROOT/external/spm12_standalone:${MATLABPATH}"
    export OCTAVE_PATH="$PROJECT_ROOT/local_src/bidspm_local:$PROJECT_ROOT/local_src/bidspm_local/src:$PROJECT_ROOT/local_src/bidspm_local/lib:$PROJECT_ROOT/external/spm12_standalone:${OCTAVE_PATH}"
fi

if [ -f "$PROJECT_ROOT/octave/octave_startup.m" ]; then
    export OCTAVE_SITE_INITFILE="$PROJECT_ROOT/octave/octave_startup.m"
fi

# Add local Octave to PATH if available
if [ -d "$PROJECT_ROOT/external/octave/bin" ]; then
    export PATH="$PROJECT_ROOT/external/octave/bin:$PATH"
    echo "✅ Local Octave added to PATH"
fi

# Check for MATLAB Compiler Runtime
if [ -d "/usr/local/freesurfer/MCRv97" ]; then
    export MCR_ROOT="/usr/local/freesurfer/MCRv97"
    export PATH="$MCR_ROOT/bin:$PATH"
    export LD_LIBRARY_PATH="$MCR_ROOT/runtime/glnxa64:$MCR_ROOT/bin/glnxa64:$LD_LIBRARY_PATH"
    echo "✅ MATLAB Compiler Runtime configured"
fi

# Function to test the environment
test_environment() {
    echo "🔧 Testing BIDSPM local environment..."
    
    if command -v octave &> /dev/null; then
        echo "✅ Octave found: $(which octave)"
        
        # Test SPM12 loading
        octave --eval "addpath('$SPM12_PATH'); try; spm('version'); fprintf('✅ SPM12 loaded successfully\n'); catch; fprintf('⚠️ SPM12 loading failed\n'); end; exit" 2>/dev/null
        
        # Test BIDSPM loading
        octave --eval "addpath('$BIDSPM_PATH'); try; bidspm('version'); fprintf('✅ BIDSPM loaded successfully\n'); catch; fprintf('⚠️ BIDSPM loading failed\n'); end; exit" 2>/dev/null
        
    elif command -v matlab &> /dev/null; then
        echo "✅ MATLAB found: $(which matlab)"
    else
        echo "⚠️ Neither MATLAB nor Octave found in PATH"
        echo "   Consider installing Octave: sudo apt-get install octave"
        echo "   Or run setup with: ./scripts/setup.sh --local-install --octave-local"
    fi
}

# Run test if called directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    test_environment
fi
