#!/bin/bash

# setup.sh - Setup script for bidspm-runner
# This script sets up a Python virtual environment using venv and installs
# dependencies using UV package manager on Ubuntu systems.

set -e  # Exit on any error

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
    if ! command -v apt-get &> /dev/null; then
        print_error "This script is designed for Ubuntu/Debian systems with apt-get package manager."
        exit 1
    fi
    print_success "Running on Ubuntu/Debian system"
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
install_system_deps() {
    print_status "Installing system dependencies..."
    
    # Update package list
    sudo apt-get update
    
    # Install required packages
    sudo apt-get install -y \
        python3-venv \
        python3-pip \
        curl \
        build-essential \
        python3-dev
    
    print_success "System dependencies installed"
}

# Install UV package manager
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

# Create and activate virtual environment
create_venv() {
    print_status "Creating Python virtual environment '.bidspm'..."
    
    # Remove existing venv if it exists
    if [ -d ".bidspm" ]; then
        print_warning "Existing .bidspm virtual environment found. Removing it..."
        rm -rf .bidspm
    fi
    
    # Create new virtual environment
    python3 -m venv .bidspm
    
    print_success "Virtual environment '.bidspm' created"
}

# Install dependencies using UV
install_dependencies() {
    print_status "Installing Python dependencies using UV..."
    
    # Activate virtual environment
    source .bidspm/bin/activate
    
    # Add UV to PATH if not already there
    export PATH="$HOME/.cargo/bin:$PATH"
    
    # Install dependencies from pyproject.toml
    if [ -f "pyproject.toml" ]; then
        uv pip install -e .
        print_success "Dependencies installed from pyproject.toml"
    else
        print_error "pyproject.toml not found in current directory"
        exit 1
    fi
    
    # Verify installation by listing installed packages
    print_status "Installed packages:"
    uv pip list
}

# Create activation script
create_activation_script() {
    print_status "Creating activation script..."
    
    cat > activate_bidspm.sh << 'EOF'
#!/bin/bash
# Activation script for bidspm-runner environment

# Add UV to PATH
export PATH="$HOME/.cargo/bin:$PATH"

# Activate virtual environment
source .bidspm/bin/activate

echo "BIDSPM virtual environment activated!"
echo "Python path: $(which python)"
echo "UV path: $(which uv)"
echo ""
echo "To deactivate, run: deactivate"
EOF
    
    chmod +x activate_bidspm.sh
    print_success "Activation script created: ./activate_bidspm.sh"
}

# Main setup function
main() {
    echo "========================================"
    echo "     BIDSPM Runner Setup Script"
    echo "========================================"
    echo ""
    
    check_os
    check_python
    install_system_deps
    install_uv
    create_venv
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
    echo "To test the installation, try:"
    echo "  python3 bidspm.py"
    echo ""
}

# Run main function
main "$@"
