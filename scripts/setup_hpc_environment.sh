#!/bin/bash
# HPC Environment Setup for BIDSPM Local Execution
# This script sets up the environment for running BIDSPM locally

# Add SPM12 to MATLAB/Octave path
export SPM12_PATH="$(pwd)/external/spm12_standalone"
export BIDSPM_PATH="$(pwd)/local_src/bidspm_local"

# Add local Octave to PATH if available
if [ -d "$(pwd)/external/octave/bin" ]; then
    export PATH="$(pwd)/external/octave/bin:$PATH"
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
