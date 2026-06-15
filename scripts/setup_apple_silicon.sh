#!/bin/bash
# setup_apple_silicon.sh
# BIDSPM setup script for Apple Silicon Macs (M1 / M2 / M3 / M4)
#
# Usage:
#   chmod +x scripts/setup_apple_silicon.sh
#   ./scripts/setup_apple_silicon.sh
#
# What this script does:
#   1. Verifies you are on Apple Silicon
#   2. Checks for Homebrew (and guides you to install it)
#   3. Installs UV (fast Python package manager)
#   4. Creates a Python virtual environment (.bidspm/)
#   5. Installs all Python dependencies
#   6. Checks for Docker Desktop (required for container-based runs)
#   7. Creates an activation script for daily use

set -e  # Exit immediately on any error

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }
step()    { echo -e "\n${BOLD}==> $*${NC}"; }

# ---------------------------------------------------------------------------
# 1. Platform guard — Apple Silicon only
# ---------------------------------------------------------------------------
step "Checking hardware"

OS=$(uname -s)
ARCH=$(uname -m)

if [[ "$OS" != "Darwin" ]]; then
    error "This script is for macOS only. Detected OS: $OS"
    error "For Linux / HPC, use:  ./scripts/setup.sh"
    exit 1
fi

if [[ "$ARCH" != "arm64" ]]; then
    error "This script targets Apple Silicon (arm64). Detected: $ARCH"
    error "Intel Mac users: install Rosetta 2 and rerun, or use the generic setup."
    error "  softwareupdate --install-rosetta --agree-to-license"
    exit 1
fi

success "Apple Silicon Mac detected (${ARCH})"
SW_VERS=$(sw_vers -productVersion 2>/dev/null || echo "unknown")
info "macOS version: ${SW_VERS}"

# ---------------------------------------------------------------------------
# 2. Homebrew
# ---------------------------------------------------------------------------
step "Checking Homebrew"

if ! command -v brew &>/dev/null; then
    error "Homebrew is not installed."
    echo ""
    echo "  Install it with:"
    echo "    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo ""
    echo "  After installation, follow the instructions to add brew to your PATH,"
    echo "  then rerun this script."
    exit 1
fi

BREW_PREFIX=$(brew --prefix)
success "Homebrew found at ${BREW_PREFIX}"

# ---------------------------------------------------------------------------
# 3. Python 3.9+
# ---------------------------------------------------------------------------
step "Checking Python"

PYTHON_BIN=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        VER=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [[ "$MAJOR" -ge 3 && "$MINOR" -ge 9 ]]; then
            PYTHON_BIN=$(command -v "$candidate")
            break
        fi
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    error "Python 3.9 or newer is required but was not found."
    echo ""
    echo "  Install via Homebrew:"
    echo "    brew install python@3.12"
    echo ""
    echo "  Then rerun this script."
    exit 1
fi

PY_VERSION=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
success "Python ${PY_VERSION} found at ${PYTHON_BIN}"

# ---------------------------------------------------------------------------
# 4. UV — fast Python package manager (Apple Silicon native binary)
# ---------------------------------------------------------------------------
step "Installing UV package manager"

UV_BIN="./build/uv"

if [[ -f "$UV_BIN" ]]; then
    UV_VER=$("$UV_BIN" --version 2>/dev/null || echo "unknown")
    warn "UV already installed locally (${UV_VER}). Skipping download."
else
    mkdir -p build

    UV_TARBALL="uv-aarch64-apple-darwin.tar.gz"
    UV_URL="https://github.com/astral-sh/uv/releases/latest/download/${UV_TARBALL}"

    info "Downloading UV for Apple Silicon..."
    if ! curl -LsSf --retry 3 --retry-delay 2 "$UV_URL" -o "build/${UV_TARBALL}"; then
        error "Failed to download UV from GitHub."
        echo "  Check your internet connection and try again."
        exit 1
    fi

    info "Extracting UV..."
    tar -xzf "build/${UV_TARBALL}" -C build --strip-components=1
    rm -f "build/${UV_TARBALL}"
    chmod +x "$UV_BIN"

    if [[ ! -f "$UV_BIN" ]]; then
        error "UV extraction failed — binary not found at ${UV_BIN}"
        exit 1
    fi

    UV_VER=$("$UV_BIN" --version)
    success "UV installed: ${UV_VER}"
fi

# ---------------------------------------------------------------------------
# 5. Python virtual environment
# ---------------------------------------------------------------------------
step "Creating Python virtual environment (.bidspm/)"

if [[ -d ".bidspm" ]]; then
    warn "Existing .bidspm environment found — removing and recreating."
    rm -rf .bidspm
fi

"$UV_BIN" venv .bidspm --python "$PYTHON_BIN"
success "Virtual environment created at .bidspm/"

VENV_PYTHON=".bidspm/bin/python"

# ---------------------------------------------------------------------------
# 6. Python dependencies
# ---------------------------------------------------------------------------
step "Installing Python dependencies"

if [[ ! -f "requirements.txt" ]]; then
    error "requirements.txt not found. Are you running this from the bidspm root directory?"
    exit 1
fi

info "Installing from requirements.txt..."
"$UV_BIN" pip install --python "$VENV_PYTHON" -r requirements.txt
success "Python dependencies installed"

info "Installed packages:"
"$UV_BIN" pip list --python "$VENV_PYTHON"

# ---------------------------------------------------------------------------
# 7. Docker Desktop
# ---------------------------------------------------------------------------
step "Checking Docker Desktop"

if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    DOCKER_VER=$(docker --version 2>/dev/null | head -1)
    success "Docker is running: ${DOCKER_VER}"
else
    warn "Docker Desktop is not running (or not installed)."
    echo ""
    echo "  BIDSPM uses Docker to run fMRIPrep / SPM containers."
    echo ""
    echo "  Download Docker Desktop for Apple Silicon:"
    echo "    https://www.docker.com/products/docker-desktop/"
    echo ""
    echo "  After installing, launch Docker Desktop and rerun this script"
    echo "  if you want the check to pass — or just continue and start"
    echo "  Docker when you are ready to run an analysis."
fi

# ---------------------------------------------------------------------------
# 8. Container configuration
# ---------------------------------------------------------------------------
step "Setting up container configuration"

if [[ -f "containers/container.json" ]]; then
    cp containers/container.json containers/container_active.json
    success "Docker container configuration ready (containers/container_active.json)"
else
    warn "containers/container.json not found — skipping container config copy."
fi

# ---------------------------------------------------------------------------
# 9. Activation script (macOS-specific)
# ---------------------------------------------------------------------------
step "Creating activation script (scripts/activate_bidspm.sh)"

ACTIVATE_SCRIPT="scripts/activate_bidspm.sh"

cat > "$ACTIVATE_SCRIPT" << 'ACTIVATE_EOF'
#!/bin/bash
# Activate the BIDSPM Python environment on Apple Silicon Mac.
# Usage:  source scripts/activate_bidspm.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -d "$PROJECT_ROOT/.bidspm" ]]; then
    echo "ERROR: Virtual environment not found. Run ./scripts/setup_apple_silicon.sh first."
    return 1 2>/dev/null || exit 1
fi

source "$PROJECT_ROOT/.bidspm/bin/activate"

export BIDSPM_PROJECT_ROOT="$PROJECT_ROOT"

echo "BIDSPM environment activated"
echo "  Project : $PROJECT_ROOT"
echo "  Python  : $(which python)"
echo ""
echo "To deactivate: deactivate"
ACTIVATE_EOF

chmod +x "$ACTIVATE_SCRIPT"
success "Activation script written to ${ACTIVATE_SCRIPT}"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}======================================================${NC}"
echo -e "${GREEN}${BOLD}  BIDSPM — Apple Silicon setup complete!${NC}"
echo -e "${BOLD}======================================================${NC}"
echo ""
echo "  Activate the environment:"
echo "    source scripts/activate_bidspm.sh"
echo ""
echo "  Run a pilot analysis:"
echo "    source scripts/activate_bidspm.sh"
echo "    python bidspm.py --pilot"
echo ""
echo "  Start the web interface:"
echo "    source scripts/activate_bidspm.sh"
echo "    python web_interface.py"
echo ""
if ! (command -v docker &>/dev/null && docker info &>/dev/null 2>&1); then
    echo -e "  ${YELLOW}Remember:${NC} Start Docker Desktop before running any analysis."
    echo ""
fi
