#!/bin/bash

# setup.sh - Setup script for bidspm-runner
# This script sets up a Python virtual environment (.bidspm) and installs
# dependencies using UV package manager.
# Use --local-install to install BIDSPM locally instead of using containers.

set -e  # Exit on any error

# Default options
LOCAL_INSTALL=false
SETUP_CONTAINERS=true
SETUP_APPTAINER=false
SETUP_OCTAVE=false
FORCE_PLATFORM=""
CHECK_DEPS_ONLY=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --local-install)
            LOCAL_INSTALL=true
            shift
            ;;
        --containers-only)
            SETUP_CONTAINERS=true
            LOCAL_INSTALL=false
            shift
            ;;
        --apptainer)
            SETUP_APPTAINER=true
            SETUP_CONTAINERS=true
            shift
            ;;
        --octave-local)
            SETUP_OCTAVE=true
            LOCAL_INSTALL=true
            shift
            ;;
        --check-octave-deps)
            CHECK_DEPS_ONLY=true
            shift
            ;;
        --platform)
            FORCE_PLATFORM="$2"
            shift 2
            ;;
        -h|--help)
            echo "BIDSPM Unified Setup Script"
            echo "=========================="
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Installation Options:"
            echo "  --local-install       Install BIDSPM locally (no containers)"
            echo "  --containers-only     Setup only container support (default)"
            echo "  --octave-local        Install Octave locally in repository"
            echo ""
            echo "Container Options:"
            echo "  --apptainer          Setup Apptainer with custom cache directories"
            echo "  --platform PLATFORM  Force specific platform (docker/apptainer)"
            echo ""
            echo "Utility Options:"
            echo "  --check-octave-deps  Check if dependencies for local Octave compilation are available"
            echo ""
            echo "General Options:"
            echo "  -h, --help           Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                               # Standard container setup"
            echo "  $0 --local-install               # Local BIDSPM with system Octave"
            echo "  $0 --local-install --octave-local  # Full local install with Octave"
            echo "  $0 --apptainer                   # Container setup optimized for HPC"
            echo "  $0 --platform docker             # Force Docker container setup"
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

# Check dependencies for local Octave compilation
check_octave_dependencies() {
    print_status "🔍 Checking dependencies for local Octave compilation..."
    
    MISSING_DEPS=()
    AVAILABLE_DEPS=()
    
    # Check essential build tools
    if command -v gcc &> /dev/null; then
        AVAILABLE_DEPS+=("gcc: $(gcc --version | head -1)")
    else
        MISSING_DEPS+=("build-essential")
    fi
    
    if command -v gfortran &> /dev/null; then
        AVAILABLE_DEPS+=("gfortran: $(gfortran --version | head -1)")
    else
        MISSING_DEPS+=("gfortran")
    fi
    
    if command -v make &> /dev/null; then
        AVAILABLE_DEPS+=("make: $(make --version | head -1)")
    else
        MISSING_DEPS+=("make")
    fi
    
    # Check libraries
    if pkg-config --exists blas 2>/dev/null; then
        AVAILABLE_DEPS+=("BLAS library found")
    else
        MISSING_DEPS+=("libopenblas-dev")
    fi
    
    if pkg-config --exists lapack 2>/dev/null; then
        AVAILABLE_DEPS+=("LAPACK library found")
    else
        MISSING_DEPS+=("liblapack-dev")
    fi
    
    if pkg-config --exists libpcre 2>/dev/null; then
        AVAILABLE_DEPS+=("PCRE library found")
    else
        MISSING_DEPS+=("libpcre3-dev")
    fi
    
    # Additional useful dependencies
    if pkg-config --exists zlib 2>/dev/null; then
        AVAILABLE_DEPS+=("zlib found")
    else
        MISSING_DEPS+=("zlib1g-dev")
    fi
    
    # Show results
    if [ ${#AVAILABLE_DEPS[@]} -gt 0 ]; then
        print_success "✅ Available dependencies:"
        for dep in "${AVAILABLE_DEPS[@]}"; do
            echo "   ✓ $dep"
        done
    fi
    
    if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
        print_warning "❌ Missing dependencies:"
        for dep in "${MISSING_DEPS[@]}"; do
            echo "   ✗ $dep"
        done
        echo ""
        print_status "💡 Install missing dependencies with:"
        print_status "   sudo apt-get update && sudo apt-get install ${MISSING_DEPS[*]}"
        echo ""
        print_status "📊 Estimated compilation time: 15-30 minutes"
        print_status "💾 Required disk space: ~500MB for build, ~200MB final installation"
        echo ""
        return 1
    else
        print_success "🎉 All dependencies are available for local Octave compilation!"
        print_status "📊 Estimated compilation time: 15-30 minutes"
        print_status "💾 Required disk space: ~500MB for build, ~200MB final installation"
        echo ""
        return 0
    fi
}

# Check if running on Ubuntu/Debian
check_os() {
    print_status "Setting up BIDSPM environment..."
    print_success "Cross-platform setup (no sudo required)"
}

# Detect platform and configure containers
detect_platform() {
    if [ -n "$FORCE_PLATFORM" ]; then
        case $FORCE_PLATFORM in
            "docker"|"apptainer")
                PLATFORM="$FORCE_PLATFORM"
                print_status "Platform forced to: $PLATFORM"
                ;;
            *)
                print_error "Invalid platform: $FORCE_PLATFORM. Use 'docker' or 'apptainer'"
                exit 1
                ;;
        esac
        return
    fi

    print_status "🚀 Detecting platform and container runtime..."
    
    if [[ "$OSTYPE" == "darwin"* ]]; then
        OS_TYPE="macos"
        print_status "📱 Detected: macOS"
        PLATFORM="docker"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS_TYPE="linux"
        print_status "🐧 Detected: Linux"
        
        # Auto-detect container runtime on Linux
        if command -v apptainer &> /dev/null; then
            PLATFORM="apptainer"
            print_status "📦 Apptainer found - configuring for HPC environment"
        elif command -v docker &> /dev/null; then
            PLATFORM="docker"
            print_status "🐳 Docker found - configuring Docker setup"
        else
            print_warning "No container runtime found"
            PLATFORM="none"
        fi
    else
        OS_TYPE="unknown"
        PLATFORM="docker"
        print_warning "❓ Unknown platform ($OSTYPE) - defaulting to Docker"
    fi
}

# Setup container configurations
setup_containers() {
    if [ "$SETUP_CONTAINERS" = false ]; then
        return
    fi
    
    print_status "🔧 Setting up container configurations..."
    
    # Ensure container config files exist
    if [ ! -f "containers/container.json" ]; then
        print_error "Container configuration files not found in containers/ directory"
        return 1
    fi
    
    case $PLATFORM in
        "docker")
            print_status "🐳 Configuring Docker setup..."
            cp containers/container.json containers/container_active.json
            print_success "Docker configuration ready"
            ;;
        "apptainer")
            if [ -f "containers/container_apptainer.json" ]; then
                print_status "📦 Configuring Apptainer setup..."
                cp containers/container_apptainer.json containers/container_active.json
                print_success "Apptainer configuration ready"
                
                # Setup Apptainer-specific environment
                setup_apptainer_environment
            else
                print_warning "Apptainer config not found, using default container config"
                cp containers/container.json containers/container_active.json
            fi
            ;;
        "none")
            print_warning "No container runtime found!"
            print_status "💡 Install options:"
            print_status "   - Apptainer: https://apptainer.org/docs/user/latest/quick_start.html"
            print_status "   - Docker: https://docs.docker.com/engine/install/"
            print_status "   - Or use --local-install flag for containerless setup"
            ;;
        *)
            print_warning "Unknown platform - using default Docker config"
            cp containers/container.json containers/container_active.json
            ;;
    esac
}

# Setup Apptainer-specific environment and directories
setup_apptainer_environment() {
    print_status "🔧 Setting up Apptainer environment..."
    
    # Set Apptainer cache and temp directories to use /data/local space
    export APPTAINER_CACHEDIR="/data/local/apptainer_cache"
    export APPTAINER_TMPDIR="/data/local/apptainer_tmp" 
    export TMPDIR="/data/local/apptainer_tmp"
    
    # Create directories if they don't exist
    mkdir -p "$APPTAINER_CACHEDIR"
    mkdir -p "$APPTAINER_TMPDIR"
    
    # Add to environment activation script
    cat >> activate_bidspm.sh << 'EOF'

# Apptainer environment variables
export APPTAINER_CACHEDIR="/data/local/apptainer_cache"
export APPTAINER_TMPDIR="/data/local/apptainer_tmp"
export TMPDIR="/data/local/apptainer_tmp"
EOF
    
    print_success "Apptainer environment configured:"
    print_status "   Cache Directory: $APPTAINER_CACHEDIR"
    print_status "   Temp Directory: $APPTAINER_TMPDIR"
    
    # Show available space
    if [ -d "/data/local" ]; then
        SPACE=$(df -h /data/local 2>/dev/null | tail -1 | awk '{print $4}' || echo "unknown")
        print_status "   Available space: $SPACE"
    fi
    
    # Check if SIF file already exists
    SIF_FILE="/data/local/apptainer_cache/bidspm_latest.sif"
    if [ -f "$SIF_FILE" ]; then
        SIZE=$(du -h "$SIF_FILE" 2>/dev/null | cut -f1 || echo "unknown")
        print_success "✅ SIF file already exists: $SIF_FILE (Size: $SIZE)"
    else
        print_status "📦 SIF file will be created: $SIF_FILE"
    fi
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
    print_status "Installing UV package manager locally to repository..."
    
    # Check if UV is already available in the local bin
    if [ -f "./build/uv" ]; then
        print_warning "UV is already installed locally. Skipping installation."
        ./build/uv --version
        return
    fi
    
    # Create build directory for local tools
    mkdir -p build
    
    # Download UV directly to the repository
    print_status "Downloading UV to ./build/ directory..."
    
    # Detect architecture
    ARCH=$(uname -m)
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    
    if [ "$ARCH" = "x86_64" ]; then
        ARCH_NAME="x86_64"
    elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
        ARCH_NAME="aarch64"
    else
        print_error "Unsupported architecture: $ARCH"
        exit 1
    fi
    
    # Download UV binary
    UV_URL="https://github.com/astral-sh/uv/releases/latest/download/uv-${ARCH_NAME}-unknown-${OS}-gnu.tar.gz"
    
    cd build
    curl -LsSf "$UV_URL" | tar xz --strip-components=1
    chmod +x uv
    cd ..
    
    # Verify installation
    if [ -f "./build/uv" ]; then
        print_success "UV installed successfully to ./build/uv"
        ./build/uv --version
    else
        print_error "UV installation failed"
        exit 1
    fi
}

# Install local Octave from source
install_local_octave() {
    if [ "$SETUP_OCTAVE" = false ]; then
        return
    fi
    
    print_status "🔧 Installing Octave locally from source..."
    
    # Check if already installed
    if [ -d "external/octave" ] && [ -f "external/octave/bin/octave" ]; then
        print_success "Local Octave already installed at external/octave/"
        return
    fi
    
    # Create external directory
    mkdir -p external
    cd external
    
    # Download Octave source with multiple fallback mirrors
    OCTAVE_VERSION="8.4.0"
    OCTAVE_MIRRORS=(
        "http://ftp.gnu.org/gnu/octave/octave-${OCTAVE_VERSION}.tar.gz"
        "https://ftpmirror.gnu.org/octave/octave-${OCTAVE_VERSION}.tar.gz"
        "http://mirrors.kernel.org/gnu/octave/octave-${OCTAVE_VERSION}.tar.gz"
        "https://mirror.ibcp.fr/pub/gnu/octave/octave-${OCTAVE_VERSION}.tar.gz"
    )
    
    print_status "Downloading Octave ${OCTAVE_VERSION}..."
    DOWNLOAD_SUCCESS=false
    
    for mirror in "${OCTAVE_MIRRORS[@]}"; do
        print_status "Trying mirror: $mirror"
        if curl -L --connect-timeout 30 --max-time 300 "$mirror" -o "octave-${OCTAVE_VERSION}.tar.gz"; then
            DOWNLOAD_SUCCESS=true
            print_success "Download successful from: $mirror"
            break
        else
            print_warning "Failed to download from: $mirror"
        fi
    done
    
    if [ "$DOWNLOAD_SUCCESS" = false ]; then
        print_error "Failed to download Octave source from all mirrors"
        print_status "💡 Alternative options:"
        print_status "   1. Install system Octave: sudo apt-get install octave"
        print_status "   2. Use containers instead: ./scripts/setup.sh --local-install"
        print_status "   3. Try again later when mirrors are available"
        cd ..
        return 1
    fi
    
    print_status "Extracting Octave source..."
    if ! tar -xzf "octave-${OCTAVE_VERSION}.tar.gz"; then
        print_error "Failed to extract Octave source"
        cd ..
        return 1
    fi
    cd "octave-${OCTAVE_VERSION}"
    
    # Check for build dependencies
    print_status "Checking build dependencies..."
    MISSING_DEPS=()
    
    if ! command -v gcc &> /dev/null; then
        MISSING_DEPS+=("build-essential")
    fi
    if ! command -v gfortran &> /dev/null; then
        MISSING_DEPS+=("gfortran")
    fi
    if ! pkg-config --exists blas 2>/dev/null; then
        MISSING_DEPS+=("libopenblas-dev")
    fi
    if ! pkg-config --exists lapack 2>/dev/null; then
        MISSING_DEPS+=("liblapack-dev")
    fi
    if ! pkg-config --exists libpcre 2>/dev/null; then
        MISSING_DEPS+=("libpcre3-dev")
    fi
    
    if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
        print_error "Missing build dependencies: ${MISSING_DEPS[*]}"
        print_status "Install them with: sudo apt-get install ${MISSING_DEPS[*]}"
        print_status "Or use system Octave instead: sudo apt-get install octave"
        cd ../..
        return 1
    fi
    
    # Configure for local installation
    print_status "Configuring Octave build (this may take a while)..."
    if ! ./configure --prefix="$(pwd)/../octave" --disable-docs --disable-gui --disable-java; then
        print_error "Octave configuration failed."
        print_status "💡 Consider using system Octave instead:"
        print_status "   sudo apt-get install octave"
        print_status "   Then run: ./scripts/setup.sh --local-install"
        cd ../..
        return 1
    fi
    
    # Build Octave
    print_status "Building Octave (this will take 15-30 minutes)..."
    NPROC=$(nproc 2>/dev/null || echo "2")
    if ! make -j$NPROC; then
        print_error "Octave build failed"
        print_status "💡 This is likely due to missing dependencies or compilation errors."
        print_status "   Consider using system Octave: sudo apt-get install octave"
        cd ../..
        return 1
    fi
    
    # Install locally
    print_status "Installing Octave locally..."
    if ! make install; then
        print_error "Octave installation failed"
        cd ../..
        return 1
    fi
    
    cd ../..
    
    # Verify installation
    if [ -f "external/octave/bin/octave" ]; then
        print_success "Local Octave installed successfully!"
        print_status "Octave binary: $(pwd)/external/octave/bin/octave"
        
        # Test the installation
        if external/octave/bin/octave --eval "disp('Octave test successful')" &>/dev/null; then
            print_success "Octave test passed"
        else
            print_warning "Octave installed but test failed"
        fi
    else
        print_error "Octave installation appears to have failed"
        return 1
    fi
    
    # Clean up source files to save space
    print_status "Cleaning up source files..."
    rm -rf "external/octave-${OCTAVE_VERSION}" "external/octave-${OCTAVE_VERSION}.tar.gz"
    
    return 0
}
install_local_bidspm() {
    print_status "Installing BIDSPM locally..."
    
    # Check if git is available
    if ! command -v git &> /dev/null; then
        print_error "Git is not installed. Please install git to use --local-install option."
        exit 1
    fi
    
    # Create local_src/bidspm_local directory if it doesn't exist
    if [ ! -d "local_src/bidspm_local" ]; then
        print_status "Cloning BIDSPM repository..."
        mkdir -p local_src
        git clone --recurse-submodules https://github.com/cpp-lln-lab/bidspm.git local_src/bidspm_local
    else
        print_warning "BIDSPM local directory already exists. Updating..."
        cd local_src/bidspm_local
        git pull
        git submodule update --recursive
        cd ../..
    fi
    
    # Install BIDSPM as Python package
    print_status "Installing BIDSPM Python package..."
    
    # Install BIDSPM from local directory
    ./build/uv pip install --python .bidspm/bin/python -e ./local_src/bidspm_local
    
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
    if [ -n "$MATLAB_PATH" ] && [ -f "local_src/bidspm_local/src/matlab.py" ]; then
        print_status "Configuring MATLAB path in BIDSPM..."
        # Create backup
        cp local_src/bidspm_local/src/matlab.py local_src/bidspm_local/src/matlab.py.backup
        
        # Update matlab.py with correct path
        cat > local_src/bidspm_local/src/matlab.py << EOF
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
    
    SPM12_DIR="external/spm12_standalone"
    
    if [ ! -d "$SPM12_DIR" ]; then
        print_status "Downloading SPM12 for Octave compatibility..."
        mkdir -p external
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
    
    cat > scripts/setup_hpc_environment.sh << 'EOF'
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
EOF
    
    chmod +x scripts/setup_hpc_environment.sh
    print_success "HPC environment script created: ./scripts/setup_hpc_environment.sh"
}

# Create and activate virtual environment
create_venv() {
    print_status "Creating Python virtual environment '.bidspm'..."
    
    # Remove existing venv if it exists
    if [ -d ".bidspm" ]; then
        print_warning "Existing .bidspm virtual environment found. Removing it..."
        rm -rf .bidspm
    fi
    
    # Create new virtual environment using local UV
    ./build/uv venv .bidspm
    
    print_success "Virtual environment '.bidspm' created"
}

# Install dependencies using UV
install_dependencies() {
    print_status "Installing Python dependencies using UV..."
    
    # Add UV to PATH if not already there
    export PATH="$HOME/.cargo/bin:$PATH"
    
    # Install dependencies from build/pyproject.toml using UV with the virtual environment
    if [ -f "build/pyproject.toml" ]; then
        # Install dependencies specified in pyproject.toml
        print_status "Installing dependencies: requests, jsonschema..."
        ./build/uv pip install --python .bidspm/bin/python requests jsonschema
        print_success "Dependencies installed successfully"
    else
        print_error "build/pyproject.toml not found in current directory"
        exit 1
    fi
    
    # Verify installation by listing installed packages
    print_status "Installed packages:"
    ./build/uv pip list --python .bidspm/bin/python
}

# Create activation script
create_activation_script() {
    print_status "Creating activation script..."
    
    cat > activate_bidspm.sh << 'EOF'
#!/bin/bash
# Activation script for bidspm-runner environment

# Activate virtual environment
source .bidspm/bin/activate

echo "🚀 BIDSPM environment activated!"
echo "Python path: $(which python)"
EOF

    # Add platform-specific environment variables
    if [ "$SETUP_APPTAINER" = true ] || [ "$PLATFORM" = "apptainer" ]; then
        cat >> activate_bidspm.sh << 'EOF'

# Apptainer environment variables
export APPTAINER_CACHEDIR="/data/local/apptainer_cache"
export APPTAINER_TMPDIR="/data/local/apptainer_tmp"
export TMPDIR="/data/local/apptainer_tmp"
echo "📦 Apptainer cache configured: $APPTAINER_CACHEDIR"
EOF
    fi

    # Add local Octave to PATH if installed
    if [ "$SETUP_OCTAVE" = true ] && [ -d "external/octave" ]; then
        cat >> activate_bidspm.sh << 'EOF'

# Local Octave installation
export PATH="$(pwd)/external/octave/bin:$PATH"
echo "🔧 Local Octave added to PATH: $(pwd)/external/octave/bin"
EOF
    fi

    # Add local BIDSPM environment if installed
    if [ "$LOCAL_INSTALL" = true ]; then
        cat >> activate_bidspm.sh << 'EOF'

# Local BIDSPM environment
export SPM12_PATH="$(pwd)/external/spm12_standalone"
export BIDSPM_PATH="$(pwd)/local_src/bidspm_local"
echo "🧠 BIDSPM local environment configured"
echo "   SPM12: $SPM12_PATH"
echo "   BIDSPM: $BIDSPM_PATH"
EOF
    fi

    cat >> activate_bidspm.sh << 'EOF'

echo ""
echo "To deactivate, run: deactivate"
EOF
    
    chmod +x activate_bidspm.sh
    print_success "Activation script created: ./activate_bidspm.sh"
}

# Main setup function
main() {
    # Handle utility functions first
    if [ "$CHECK_DEPS_ONLY" = true ]; then
        check_octave_dependencies
        exit $?
    fi
    
    echo "========================================"
    if [ "$LOCAL_INSTALL" = true ]; then
        if [ "$SETUP_OCTAVE" = true ]; then
            echo "     BIDSPM Complete Local Setup"
            echo "    (with local Octave compilation)"
        else
            echo "     BIDSPM Local Installation Setup"
        fi
    else
        echo "     BIDSPM Container Setup"
    fi
    echo "========================================"
    echo ""
    
    check_os
    check_python
    
    # Detect platform and setup containers (unless local-only)
    if [ "$LOCAL_INSTALL" = false ] || [ "$SETUP_CONTAINERS" = true ]; then
        detect_platform
        setup_containers
    fi
    
    # Install UV package manager
    install_uv
    create_venv
    
    # Install local Octave if requested
    if [ "$SETUP_OCTAVE" = true ]; then
        install_local_octave
        if [ $? -ne 0 ]; then
            print_warning "Local Octave installation failed, continuing with system Octave"
            SETUP_OCTAVE=false
        fi
    fi
    
    # Install local BIDSPM if requested
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
    
    # Platform-specific usage instructions
    if [ "$LOCAL_INSTALL" = true ]; then
        print_success "✅ Local BIDSPM Installation Complete"
        echo ""
        echo "🔧 Local installation includes:"
        echo "  - BIDSPM Python CLI (bidspm command)"
        if [ "$SETUP_OCTAVE" = true ]; then
            echo "  - Local Octave installation (external/octave/)"
        else
            echo "  - System MATLAB/Octave integration"
        fi
        echo "  - SPM12 standalone installation"
        echo "  - HPC environment compatibility"
        echo "  - No container dependencies"
        echo ""
        echo "🚀 To activate the environment:"
        echo "  source ./activate_bidspm.sh"
        echo ""
        echo "🧪 To test the local installation:"
        echo "  source .bidspm/bin/activate"
        echo "  ./scripts/setup_hpc_environment.sh"
        echo ""
        echo "🎯 To use with your custom runner:"
        echo "  python3 bidspm.py --local --action smooth --pilot"
        echo ""
        if [ "$SETUP_OCTAVE" = false ]; then
            echo "💡 HPC Notes:"
            echo "  - If on an HPC system, load required modules first:"
            echo "    module load octave  # or equivalent for your system"
            echo "  - For complete local setup, use: $0 --local-install --octave-local"
        fi
    else
        print_success "✅ Container Setup Complete"
        echo ""
        echo "🐳 Container platform: $PLATFORM"
        if [ "$PLATFORM" = "apptainer" ]; then
            echo "📦 Apptainer optimized for HPC with /data/local storage"
            echo "   Cache: /data/local/apptainer_cache"
            echo "   Temp:  /data/local/apptainer_tmp"
        fi
        echo ""
        echo "🚀 To activate the environment:"
        echo "  source ./activate_bidspm.sh"
        echo ""
        echo "🧪 To test the installation:"
        echo "  python3 bidspm.py --pilot"
        echo ""
        echo "🎯 Usage examples:"
        echo "  - Development/Piloting: python bidspm.py --pilot"
        echo "  - Production: python bidspm.py -s your_config.json"
        echo "  - Auto-detection: Script will automatically select the right container"
    fi
    echo ""
}

# Run main function
main "$@"
