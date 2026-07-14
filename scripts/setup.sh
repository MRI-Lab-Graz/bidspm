#!/bin/bash

# setup.sh - Setup script for bidspm-runner
# This script sets up a Python virtual environment (.bidspm) and installs
# dependencies using UV package manager, then configures container execution
# (Docker or Apptainer).

set -e  # Exit on any error

# Default options
SETUP_CONTAINERS=true
SETUP_APPTAINER=false
FORCE_PLATFORM=""
FORCE_INSTALL=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --force)
            FORCE_INSTALL=true
            shift
            ;;
        --apptainer)
            SETUP_APPTAINER=true
            SETUP_CONTAINERS=true
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
            echo "Container Options:"
            echo "  --apptainer          Setup Apptainer with custom cache directories"
            echo "  --platform PLATFORM  Force specific platform (docker/apptainer)"
            echo ""
            echo "Utility Options:"
            echo "  --force              Force installation even if locked"
            echo ""
            echo "General Options:"
            echo "  -h, --help           Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                               # Standard container setup"
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

    # Respect pre-set env vars (e.g. HPC clusters pointing at scratch storage);
    # otherwise default to repo-local cache/tmp dirs so this works out of the
    # box on any machine.
    : "${APPTAINER_CACHEDIR:=$(pwd)/.apptainer_cache}"
    : "${APPTAINER_TMPDIR:=$(pwd)/.apptainer_tmp}"
    export APPTAINER_CACHEDIR
    export APPTAINER_TMPDIR
    export TMPDIR="$APPTAINER_TMPDIR"

    mkdir -p "$APPTAINER_CACHEDIR"
    mkdir -p "$APPTAINER_TMPDIR"

    print_success "Apptainer environment configured:"
    print_status "   Cache Directory: $APPTAINER_CACHEDIR"
    print_status "   Temp Directory: $APPTAINER_TMPDIR"

    SPACE=$(df -h "$APPTAINER_CACHEDIR" 2>/dev/null | tail -1 | awk '{print $4}' || echo "unknown")
    print_status "   Available space: $SPACE"
}

# Check if Python 3.8+ is available
check_python() {
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed. Please install Python 3.8 or higher."
        exit 1
    fi

    python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

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

    # Install dependencies from requirements.txt using UV with the virtual environment
    if [ -f "requirements.txt" ]; then
        print_status "Installing dependencies from requirements.txt..."
        ./build/uv pip install --python .bidspm/bin/python -r requirements.txt
        print_success "Dependencies installed successfully"
    else
        print_error "requirements.txt not found in current directory"
        exit 1
    fi

    # Verify installation by listing installed packages
    print_status "Installed packages:"
    ./build/uv pip list --python .bidspm/bin/python
}

# Create activation script
create_activation_script() {
    print_status "Creating activation script..."

    cat > scripts/activate_bidspm.sh << 'EOF'
#!/bin/bash
# Activation script for bidspm-runner environment

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ ! -d "$PROJECT_ROOT/.bidspm" ]; then
    echo "❌ Virtual environment not found. Please run ./scripts/setup.sh first."
    return 1 2>/dev/null || exit 1
fi

source "$PROJECT_ROOT/.bidspm/bin/activate"

export BIDSPM_PROJECT_ROOT="$PROJECT_ROOT"

echo "🚀 BIDSPM environment activated!"
echo "Project root: $PROJECT_ROOT"
echo "Python path: $(which python)"
EOF

    # Add platform-specific environment variables
    if [ "$SETUP_APPTAINER" = true ] || [ "$PLATFORM" = "apptainer" ]; then
        cat >> scripts/activate_bidspm.sh << 'EOF'

# Apptainer environment variables (respect pre-set values, e.g. on HPC)
: "${APPTAINER_CACHEDIR:=$PROJECT_ROOT/.apptainer_cache}"
: "${APPTAINER_TMPDIR:=$PROJECT_ROOT/.apptainer_tmp}"
export APPTAINER_CACHEDIR
export APPTAINER_TMPDIR
export TMPDIR="$APPTAINER_TMPDIR"
echo "📦 Apptainer cache configured: $APPTAINER_CACHEDIR"
EOF
    fi

    cat >> scripts/activate_bidspm.sh << 'EOF'

echo ""
echo "To deactivate, run: deactivate"
EOF

    chmod +x scripts/activate_bidspm.sh
    print_success "Activation script created: ./scripts/activate_bidspm.sh"
}

# Main setup function
main() {
    echo "========================================"
    echo "     BIDSPM Container Setup"
    echo "========================================"
    echo ""

    check_os
    check_python

    detect_platform
    setup_containers

    # Install UV package manager
    install_uv
    create_venv
    install_dependencies
    create_activation_script

    echo ""
    echo "========================================"
    print_success "Setup completed successfully!"
    echo "========================================"
    echo ""

    print_success "✅ Container Setup Complete"
    echo ""
    echo "🐳 Container platform: $PLATFORM"
    if [ "$PLATFORM" = "apptainer" ]; then
        echo "📦 Apptainer cache/temp dirs configured (see ./scripts/activate_bidspm.sh)"
    fi
    echo ""
    echo "🚀 To activate the environment:"
    echo "  source ./scripts/activate_bidspm.sh"
    echo ""
    echo "🧪 To test the installation:"
    echo "  python3 bidspm.py --pilot"
    echo ""
    echo "🎯 Usage examples:"
    echo "  - Development/Piloting: python bidspm.py --pilot"
    echo "  - Production: python bidspm.py -s your_config.json"
    echo "  - Auto-detection: Script will automatically select the right container"
    echo ""
}

# Check for lock file
if [ -f ".install.lock" ] && [ "$FORCE_INSTALL" = false ]; then
    print_status "🔒 Installation is locked to prevent accidental overwritting."
    print_status "   The setup has already completed successfully."
    print_status "   Use --force to override, or remove '.install.lock'."
    exit 0
fi

# Run main function
if main "$@"; then
    # Lock the installation on success
    touch .install.lock
    print_status "🔒 Installation locked. (Created .install.lock)"
fi
