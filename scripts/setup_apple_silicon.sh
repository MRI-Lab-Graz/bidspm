#!/bin/bash
# setup_apple_silicon.sh — BIDSPM installer for Apple Silicon Macs (M1/M2/M3/M4)
#
# Share this single file with students. Running it once sets up everything.
# Analyses run inside the same Docker container as the server — identical results.
#
# Usage:
#   bash setup_apple_silicon.sh              # installs to ~/bidspm
#   bash setup_apple_silicon.sh --dir ~/Desktop/bidspm
#
# What this script does:
#   1. Verifies Apple Silicon + macOS
#   2. Checks Homebrew (guides install if missing)
#   3. Checks Xcode CLI tools (needed for git)
#   4. Clones the repository with all submodules
#   5. Installs UV and creates a Python virtual environment
#   6. Installs all Python dependencies
#   7. Checks Docker Desktop and pulls the bidspm image
#   8. Writes scripts/activate_bidspm.sh for daily use

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_URL="https://github.com/MRI-Lab-Graz/bidspm.git"
DEFAULT_INSTALL_DIR="${HOME}/bidspm"
DOCKER_IMAGE="bidspm/bidspm:latest"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
INSTALL_DIR="$DEFAULT_INSTALL_DIR"
while [[ $# -gt 0 ]]; do
    case $1 in
        --dir)
            INSTALL_DIR="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: bash $(basename "$0") [--dir <path>]"
            echo "  --dir <path>   Installation directory (default: ~/bidspm)"
            exit 0 ;;
        *)
            echo "Unknown option: $1  (use --help for usage)"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
step()    { echo -e "\n${BOLD}── $* ──${NC}"; }

# ---------------------------------------------------------------------------
# Step 1 — Apple Silicon guard
# ---------------------------------------------------------------------------
step "1/8  Checking hardware"

[[ "$(uname -s)" == "Darwin" ]] || error "This script is for macOS only."
[[ "$(uname -m)" == "arm64"  ]] || error "Apple Silicon (arm64) required. Detected: $(uname -m)"

success "Apple Silicon Mac — macOS $(sw_vers -productVersion 2>/dev/null || echo '?')"

# ---------------------------------------------------------------------------
# Step 2 — Homebrew
# ---------------------------------------------------------------------------
step "2/8  Checking Homebrew"

if ! command -v brew &>/dev/null; then
    echo ""
    echo "  Homebrew is not installed. Install it with:"
    echo ""
    echo '    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    echo ""
    echo "  After installation follow the printed instructions to add brew to"
    echo "  your PATH, then rerun this script."
    exit 1
fi
success "Homebrew at $(brew --prefix)"

# ---------------------------------------------------------------------------
# Step 3 — Xcode CLI tools (provides git)
# ---------------------------------------------------------------------------
step "3/8  Checking Xcode CLI tools"

if ! xcode-select -p &>/dev/null; then
    warn "Xcode CLI tools not found — installing (a system dialog will appear)..."
    xcode-select --install
    echo ""
    echo "  Wait for the Xcode CLI tools installation to finish, then rerun this script."
    exit 0
fi
success "Xcode CLI tools present"
command -v git &>/dev/null || error "git not found — please reopen your terminal and try again."

# ---------------------------------------------------------------------------
# Step 4 — Clone repository
# ---------------------------------------------------------------------------
step "4/8  Cloning repository → ${INSTALL_DIR}"

if [[ -d "${INSTALL_DIR}/.git" ]]; then
    warn "Repository already exists — pulling latest changes..."
    git -C "$INSTALL_DIR" pull --ff-only
    git -C "$INSTALL_DIR" submodule update --init --recursive
else
    git clone --recurse-submodules "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
success "Repository ready at ${INSTALL_DIR}"

# ---------------------------------------------------------------------------
# Step 5 — UV + Python virtual environment
# ---------------------------------------------------------------------------
step "5/8  Installing UV and creating Python environment"

UV_BIN="./build/uv"

if [[ -f "$UV_BIN" ]]; then
    warn "UV already present ($("$UV_BIN" --version)) — skipping download."
else
    mkdir -p build
    UV_TARBALL="uv-aarch64-apple-darwin.tar.gz"
    info "Downloading UV for Apple Silicon..."
    curl -LsSf --retry 3 \
        "https://github.com/astral-sh/uv/releases/latest/download/${UV_TARBALL}" \
        -o "build/${UV_TARBALL}" \
        || error "UV download failed — check your internet connection."
    tar -xzf "build/${UV_TARBALL}" -C build --strip-components=1
    rm -f "build/${UV_TARBALL}"
    chmod +x "$UV_BIN"
    success "UV $("$UV_BIN" --version) installed"
fi

# Find Python 3.9+
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$candidate" &>/dev/null; then
        if "$candidate" -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" 2>/dev/null; then
            PYTHON_BIN=$(command -v "$candidate")
            break
        fi
    fi
done
if [[ -z "$PYTHON_BIN" ]]; then
    echo ""
    echo "  Python 3.9+ not found. Install via Homebrew:"
    echo "    brew install python@3.12"
    echo "  Then rerun this script."
    exit 1
fi
info "Python $("$PYTHON_BIN" --version 2>&1 | awk '{print $2}') at ${PYTHON_BIN}"

# Create venv
if [[ -d ".bidspm" ]]; then
    warn "Existing .bidspm environment found — recreating."
    rm -rf .bidspm
fi
"$UV_BIN" venv .bidspm --python "$PYTHON_BIN"
success "Virtual environment created"

# ---------------------------------------------------------------------------
# Step 6 — Python dependencies
# ---------------------------------------------------------------------------
step "6/8  Installing Python dependencies"

[[ -f "requirements.txt" ]] || error "requirements.txt not found — run this script from the repo root."
"$UV_BIN" pip install --python ".bidspm/bin/python" -r requirements.txt
success "Python dependencies installed"

# ---------------------------------------------------------------------------
# Step 7 — Docker Desktop + image pull
# ---------------------------------------------------------------------------
step "7/8  Checking Docker Desktop and pulling bidspm image"

if ! command -v docker &>/dev/null; then
    echo ""
    echo "  Docker Desktop is not installed."
    echo ""
    echo "  Download it here (choose 'Apple Silicon'):"
    echo "    https://www.docker.com/products/docker-desktop/"
    echo ""
    echo "  After installing and launching Docker Desktop, rerun this script"
    echo "  to pull the bidspm image."
    echo ""
    warn "Skipping image pull — complete Docker setup and rerun."
elif ! docker info &>/dev/null 2>&1; then
    echo ""
    warn "Docker is installed but not running."
    echo "  Please open Docker Desktop, wait for it to finish starting,"
    echo "  then rerun this script to pull the bidspm image."
    echo ""
else
    success "Docker Desktop is running"

    info "Pulling ${DOCKER_IMAGE} (this can take a few minutes the first time)..."
    docker pull "$DOCKER_IMAGE" && success "Image ${DOCKER_IMAGE} ready" \
        || warn "Image pull failed — check your internet connection and try: docker pull ${DOCKER_IMAGE}"

    # Write Docker container config
    mkdir -p containers
    cat > containers/container_active.json << EOF
{
  "container_type": "docker",
  "docker_image": "${DOCKER_IMAGE}",
  "apptainer_image": ""
}
EOF
    success "containers/container_active.json written"
fi

# ---------------------------------------------------------------------------
# Step 8 — Activation script
# ---------------------------------------------------------------------------
step "8/8  Writing activation script"

mkdir -p scripts

cat > scripts/activate_bidspm.sh << 'ACTIVATE_EOF'
#!/bin/bash
# Activate the BIDSPM environment on Apple Silicon Mac.
# Usage:  source scripts/activate_bidspm.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -d "$PROJECT_ROOT/.bidspm" ]]; then
    echo "ERROR: Virtual environment not found."
    echo "       Run scripts/setup_apple_silicon.sh first."
    return 1 2>/dev/null || exit 1
fi

source "$PROJECT_ROOT/.bidspm/bin/activate"

export BIDSPM_PROJECT_ROOT="$PROJECT_ROOT"

echo ""
echo "BIDSPM environment activated"
echo "  Project : $PROJECT_ROOT"
echo "  Python  : $(which python)"
echo "  Docker  : $(docker --version 2>/dev/null | head -1 || echo 'not found')"
echo ""
echo "Run an analysis:     python bidspm.py --action smooth stats"
echo "Pilot (1 subject):   python bidspm.py --action smooth --pilot"
echo "Web interface:       python web_interface.py"
echo "Deactivate:          deactivate"
ACTIVATE_EOF

chmod +x scripts/activate_bidspm.sh
success "scripts/activate_bidspm.sh written"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  BIDSPM setup complete!${NC}"
echo -e "${BOLD}══════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Installation path : ${BOLD}${INSTALL_DIR}${NC}"
echo ""
echo "  To get started:"
echo "    cd ${INSTALL_DIR}"
echo "    source scripts/activate_bidspm.sh"
echo "    python bidspm.py --action smooth --pilot"
echo ""
if ! (command -v docker &>/dev/null && docker info &>/dev/null 2>&1); then
    echo -e "  ${YELLOW}Reminder:${NC} Install and start Docker Desktop, then run:"
    echo "    docker pull ${DOCKER_IMAGE}"
    echo "    cp containers/container.json containers/container_active.json"
    echo ""
fi
