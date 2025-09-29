#!/bin/bash

# setup.sh - Setup script for bidspm-runner
# This script sets up a Python virtual environment (.bidspm) and installs
# dependencies using UV package manager.
# Use --local-install to install BIDSPM locally instead of using containers.

set -e  # Exit on any error

# Default options
LOCAL_INSTALL=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --local-install)
            LOCAL_INSTALL=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --local-install    Install BIDSPM locally instead of using containers"
            echo "  -h, --help         Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                 # Standard setup with container support"
            echo "  $0 --local-install # Setup with local BIDSPM installation"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running on Ubuntu/Debian
check_os() {
    print_status "Setting up BIDSPM environment..."
    print_success "Cross-platform setup (no sudo required)"
}

# Check if Python 3.8+ is available
check_python() {
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed. Please install Python 3.8 or higher."
        exit 1
    fi
    
    python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    required_version="3.8"
    
    if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)"; then
        print_error "Python ${python_version} detected. Python 3.8 or higher is required."
        exit 1
    fi
    
    print_success "Python ${python_version} detected"
}

# Install system dependencies
install_uv() {
    print_status "Installing UV package manager..."
    
    if command -v uv &> /dev/null; then
        print_warning "UV is already installed. Skipping installation."
        uv --version
        return
    fi
    
    # Install UV using the official installer
    curl -LsSf https://astral.sh/uv/install.sh | sh
    
    # Add UV to PATH for current session
    export PATH="$HOME/.cargo/bin:$PATH"
    
    # Verify installation
    if command -v uv &> /dev/null; then
        print_success "UV installed successfully"
        uv --version
    else
        print_error "UV installation failed"
        exit 1
    fi
}

# Install local BIDSPM
install_local_bidspm() {
    print_status "Installing BIDSPM locally..."
    
    # Check if git is available
    if ! command -v git &> /dev/null; then
        print_error "Git is not installed. Please install git to use --local-install option."
        exit 1
    fi
    
    # Create bidspm_local directory if it doesn't exist
    if [ ! -d "bidspm_local" ]; then
        print_status "Cloning BIDSPM repository..."
        git clone --recurse-submodules https://github.com/cpp-lln-lab/bidspm.git bidspm_local
    else
        print_warning "BIDSPM local directory already exists. Updating..."
        cd bidspm_local
        git pull
        git submodule update --recursive
        cd ..
    fi
    
    # Install BIDSPM as Python package
    print_status "Installing BIDSPM Python package..."
    export PATH="$HOME/.cargo/bin:$PATH"
    
    # Install BIDSPM from local directory
    uv pip install --python .bidspm/bin/python -e ./bidspm_local
    
    # Check if MATLAB/Octave is available
    check_matlab_octave
    
    print_success "Local BIDSPM installation completed"
}

# Check for MATLAB/Octave and configure paths
check_matlab_octave() {
    print_status "Checking for MATLAB/Octave and alternatives..."
    
    MATLAB_PATH=""
    OCTAVE_PATH=""
    MCR_PATH=""
    SPM_STANDALONE=""
    
    # Check for MATLAB
    if command -v matlab &> /dev/null; then
        MATLAB_PATH=$(which matlab)
        print_success "MATLAB found at: $MATLAB_PATH"
    fi
    
    # Check for Octave
    if command -v octave &> /dev/null; then
        OCTAVE_PATH=$(which octave)
        print_success "Octave found at: $OCTAVE_PATH"
    fi
    
    # Check for MATLAB Compiler Runtime (common in HPC/neuroimaging environments)
    if [ -d "/usr/local/freesurfer/MCRv97" ]; then
        MCR_PATH="/usr/local/freesurfer/MCRv97"
        print_success "MATLAB Compiler Runtime found at: $MCR_PATH"
    fi
    
    # Check for system package manager installations
    if command -v apt-get &> /dev/null; then
        print_status "Checking for Octave via package manager..."
        if ! command -v octave &> /dev/null; then
            print_status "Octave not found. You can install it with:"
            print_status "  sudo apt-get update && sudo apt-get install octave"
        fi
    fi
    
    if [ -z "$MATLAB_PATH" ] && [ -z "$OCTAVE_PATH" ] && [ -z "$MCR_PATH" ]; then
        print_warning "No MATLAB, Octave, or MCR found."
        print_warning "Local BIDSPM execution options:"
        print_warning "  1. Install Octave: sudo apt-get install octave (recommended for HPC)"
        print_warning "  2. Install MATLAB and ensure it's in PATH"
        print_warning "  3. Use container execution instead (remove --local flag)"
        return 1
    fi
    
    # Install standalone SPM12 for HPC compatibility
    install_spm12_standalone
    
    # Configure matlab.py in BIDSPM if MATLAB is found
    if [ -n "$MATLAB_PATH" ] && [ -f "bidspm_local/src/matlab.py" ]; then
        print_status "Configuring MATLAB path in BIDSPM..."
        # Create backup
        cp bidspm_local/src/matlab.py bidspm_local/src/matlab.py.backup
        
        # Update matlab.py with correct path
        cat > bidspm_local/src/matlab.py << EOF
"""MATLAB configuration for local installation."""

def get_matlab_executable():
    """Return the path to MATLAB executable."""
    return "$MATLAB_PATH"

if __name__ == "__main__":
    print(get_matlab_executable())
EOF
        print_success "MATLAB path configured in BIDSPM"
    fi
    
    return 0
}

# Install SPM12 standalone for HPC compatibility
install_spm12_standalone() {
    print_status "Setting up SPM12 for local BIDSPM execution..."
    
    SPM12_DIR="spm12_standalone"
    
    if [ ! -d "$SPM12_DIR" ]; then
        print_status "Downloading SPM12 for Octave compatibility..."
        git clone https://github.com/spm/spm12.git "$SPM12_DIR" --depth 1
        
        if [ $? -eq 0 ]; then
            print_success "SPM12 cloned successfully"
            
            # If Octave is available, compile SPM for Octave
            if command -v octave &> /dev/null; then
                print_status "Compiling SPM12 for Octave compatibility..."
                cd "$SPM12_DIR"
                
                # Clean and compile for Octave (as per HPC documentation)
                make -C src PLATFORM=octave distclean 2>/dev/null || true
                if make -C src PLATFORM=octave; then
                    make -C src PLATFORM=octave install
                    print_success "SPM12 compiled for Octave"
                else
                    print_warning "SPM12 compilation for Octave failed, but SPM12 is still available"
                fi
                cd ..
            else
                print_status "SPM12 downloaded (Octave not available for compilation)"
            fi
        else
            print_warning "Failed to clone SPM12, but local BIDSPM may still work with existing installations"
        fi
    else
        print_success "SPM12 already available at $SPM12_DIR"
    fi
    
    # Create environment setup script
    create_hpc_environment_script
}

# Create HPC-compatible environment setup script
create_hpc_environment_script() {
    print_status "Creating HPC environment script..."
    
    cat > setup_hpc_environment.sh << 'EOF'
#!/bin/bash
# HPC Environment Setup for BIDSPM Local Execution
# This script sets up the environment for running BIDSPM locally

# Add SPM12 to MATLAB/Octave path
export SPM12_PATH="$(pwd)/spm12_standalone"
export BIDSPM_PATH="$(pwd)/bidspm_local"

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
    fi
}

# Run test if called directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    test_environment
fi
EOF
    
    chmod +x setup_hpc_environment.sh
    print_success "HPC environment script created: ./setup_hpc_environment.sh"
}

# Create and activate virtual environment
create_venv() {
    print_status "Creating Python virtual environment '.bidspm'..."
    
    # Remove existing venv if it exists
    if [ -d ".bidspm" ]; then
        print_warning "Existing .bidspm virtual environment found. Removing it..."
        rm -rf .bidspm
    fi
    
    # Create new virtual environment using UV
    export PATH="$HOME/.cargo/bin:$PATH"
    uv venv .bidspm
    
    print_success "Virtual environment '.bidspm' created"
}

# Install dependencies using UV
install_dependencies() {
    print_status "Installing Python dependencies using UV..."
    
    # Add UV to PATH if not already there
    export PATH="$HOME/.cargo/bin:$PATH"
    
    # Install dependencies from pyproject.toml using UV with the virtual environment
    if [ -f "pyproject.toml" ]; then
        # Use UV to install the project in the virtual environment
        uv pip install --python .bidspm/bin/python -e .
        print_success "Dependencies installed from pyproject.toml"
    else
        print_error "pyproject.toml not found in current directory"
        exit 1
    fi
    
    # Verify installation by listing installed packages
    print_status "Installed packages:"
    uv pip list --python .bidspm/bin/python
}

# Create activation script
create_activation_script() {
    print_status "Creating activation script..."
    
    cat > activate_bidspm.sh << 'EOF'
#!/bin/bash
# Activation script for bidspm-runner environment

# Activate virtual environment
source .bidspm/bin/activate

echo "BIDSPM virtual environment activated!"
echo "Python path: $(which python)"
echo ""
echo "To deactivate, run: deactivate"
EOF
    chmod +x activate_bidspm.sh
    print_success "Activation script created: ./activate_bidspm.sh"
}

# Main setup function
main() {
    echo "========================================"
    if [ "$LOCAL_INSTALL" = true ]; then
        echo "     BIDSPM Local Installation Setup"
    else
        echo "     BIDSPM Runner Setup Script"
    fi
    echo "========================================"
    echo ""
    
    check_os
    check_python
    install_uv
    create_venv
    
    if [ "$LOCAL_INSTALL" = true ]; then
        install_local_bidspm
    fi
    
    install_dependencies
    create_activation_script
    
    echo ""
    echo "========================================"
    print_success "Setup completed successfully!"
    echo "========================================"
    echo ""
    echo "To activate the environment, run:"
    echo "  source ./activate_bidspm.sh"
    echo ""
    echo "Or manually:"
    echo "  source .bidspm/bin/activate"
    echo ""
    
    if [ "$LOCAL_INSTALL" = true ]; then
        echo "Local BIDSPM installation includes:"
        echo "  - BIDSPM Python CLI (bidspm command)"
        echo "  - Local MATLAB/Octave integration"
        echo "  - SPM12 standalone installation"
        echo "  - HPC environment compatibility"
        echo "  - No container dependencies"
        echo ""
        echo "To test the local installation:"
        echo "  source .bidspm/bin/activate"
        echo "  ./setup_hpc_environment.sh"
        echo ""
        echo "To use with your custom runner:"
        echo "  python3 bidspm.py --local --action smooth --pilot"
        echo ""
        echo "HPC Notes:"
        echo "  - If on an HPC system, load required modules first:"
        echo "    module load octave  # or equivalent for your system"
        echo "  - For systems with module environments, consider creating"
        echo "    a module file for BIDSPM local installation"
    else
        echo "To test the installation, try:"
        echo "  python3 bidspm.py"
    fi
    echo ""
}

# Run main function
main "$@"
