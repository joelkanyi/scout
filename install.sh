#!/usr/bin/env bash
# Scout — One-line installer
# Usage: curl -fsSL https://raw.githubusercontent.com/joelkanyi/scout/main/install.sh | bash
set -euo pipefail

SCOUT_DIR="$HOME/scout"
VENV_DIR="$SCOUT_DIR/.venv"
REPO_URL="https://github.com/joelkanyi/scout.git"

# ── Colors ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}[scout]${NC} $1"; }
ok()    { echo -e "${GREEN}[  ok ]${NC} $1"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $1"; }
fail()  { echo -e "${RED}[fail]${NC} $1"; exit 1; }

echo ""
echo -e "${BOLD}╔════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   Scout — Automated Job Applications  ║${NC}"
echo -e "${BOLD}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Scout supports 3 AI providers:"
echo -e "    ${GREEN}1) Google Gemini${NC}  — free (default)"
echo -e "    ${GREEN}2) Ollama${NC}         — free, runs locally"
echo -e "    ${GREEN}3) Anthropic${NC}      — paid (~\$5/month, best quality)"
echo ""
echo -e "  The setup wizard will help you choose."
echo ""

# ── 1. Check OS ─────────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
    Darwin) info "Detected macOS" ;;
    Linux)  info "Detected Linux" ;;
    *)      fail "Unsupported OS: $OS. Scout works on macOS and Linux." ;;
esac

# ── 2. Check git ────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    if [[ "$OS" == "Darwin" ]]; then
        info "Installing git via Xcode Command Line Tools..."
        xcode-select --install 2>/dev/null || true
        fail "Please re-run this script after Xcode tools finish installing."
    else
        info "Installing git..."
        sudo apt-get update -qq && sudo apt-get install -y -qq git
    fi
fi
ok "Git found"

# ── 3. Homebrew (macOS only) ───────────────────────────────────────
if [[ "$OS" == "Darwin" ]]; then
    if ! command -v brew &>/dev/null; then
        info "Installing Homebrew..."
        NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL --retry 5 --retry-all-errors https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Add brew to PATH for this session
        if [[ -f /opt/homebrew/bin/brew ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [[ -f /usr/local/bin/brew ]]; then
            eval "$(/usr/local/bin/brew shellenv)"
        fi
        ok "Homebrew installed"
    else
        ok "Homebrew found"
    fi
fi

# ── 4. Python 3.12+ ────────────────────────────────────────────────
install_python() {
    if [[ "$OS" == "Darwin" ]]; then
        info "Installing Python 3.12 via Homebrew..."
        brew install python@3.12
    else
        info "Installing Python 3.12 via apt..."
        sudo apt-get update -qq
        sudo apt-get install -y -qq python3.12 python3.12-venv python3-pip
    fi
}

PYTHON=""
for cmd in python3.12 python3.13 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.minor}')" 2>/dev/null || echo "0")
        if [[ "$ver" -ge 12 ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    install_python
    # Re-check after install
    for cmd in python3.12 python3.13 python3; do
        if command -v "$cmd" &>/dev/null; then
            ver=$("$cmd" -c "import sys; print(f'{sys.version_info.minor}')" 2>/dev/null || echo "0")
            if [[ "$ver" -ge 12 ]]; then
                PYTHON="$cmd"
                break
            fi
        fi
    done
    if [[ -z "$PYTHON" ]]; then
        fail "Python 3.12+ installation failed. Please install it manually."
    fi
fi

py_version=$("$PYTHON" --version)
ok "Python: $py_version"

# ── 5. Node.js (for building the UI) ───────────────────────────────
if ! command -v node &>/dev/null; then
    info "Installing Node.js..."
    if [[ "$OS" == "Darwin" ]]; then
        brew install node
    else
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
        sudo apt-get install -y -qq nodejs
    fi
fi
ok "Node.js: $(node --version)"

# ── 6. System deps for WeasyPrint (PDF export) ─────────────────────
if [[ "$OS" == "Linux" ]]; then
    info "Installing system dependencies..."
    sudo apt-get install -y -qq \
        libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \
        libffi-dev shared-mime-info 2>/dev/null || warn "Some system deps may be missing, WeasyPrint may not work"
    ok "System dependencies installed"
elif [[ "$OS" == "Darwin" ]]; then
    info "Installing Pango for PDF export..."
    brew install pango || warn "Could not install Pango, PDF resume export may not work"
    ok "System dependencies installed"
fi

# ── 7. Clone or update Scout ──────────────────────────────────────
if [[ -d "$SCOUT_DIR/.git" ]]; then
    info "Scout already installed at $SCOUT_DIR — updating..."
    git -C "$SCOUT_DIR" pull --ff-only 2>/dev/null || warn "Could not auto-update (you may have local changes)"
    ok "Scout updated"
else
    if [[ -d "$SCOUT_DIR" ]]; then
        fail "$SCOUT_DIR already exists but is not a Scout install. Move or remove it first."
    fi
    info "Downloading Scout..."
    git clone "$REPO_URL" "$SCOUT_DIR"
    ok "Scout downloaded to $SCOUT_DIR"
fi

cd "$SCOUT_DIR"

# ── 8. Python virtual environment ─────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
ok "Virtual environment ready"

# ── 9. Install Python dependencies ────────────────────────────────
info "Installing Python packages (this takes a minute)..."
pip install --quiet --upgrade pip
if ! pip install --quiet -e .; then
    fail "Python package installation failed. Check the output above."
fi
ok "Python packages installed"

# ── 10. Playwright browser ─────────────────────────────────────────
info "Installing browser for auto-apply (Chromium)..."
if ! playwright install chromium; then
    warn "Chromium install failed — auto-apply won't work, but everything else will"
fi
ok "Chromium browser ready"

# ── 11. Build the web UI ──────────────────────────────────────────
info "Building the dashboard UI..."
cd ui
if ! npm ci --silent; then
    warn "npm install failed — dashboard won't be available, CLI still works"
    cd ..
else
    if ! npm run build; then
        warn "Dashboard build failed — CLI still works, dashboard won't be available"
    else
        ok "Dashboard built"
    fi
    cd ..
fi

# ── 12. Create data directories ───────────────────────────────────
mkdir -p data config/answers config/credentials resume/generated

# ── 13. Add 'scout' to PATH ──────────────────────────────────────
SHELL_RC=""
if [[ -f "$HOME/.zshrc" ]]; then
    SHELL_RC="$HOME/.zshrc"
elif [[ -f "$HOME/.bashrc" ]]; then
    SHELL_RC="$HOME/.bashrc"
elif [[ -f "$HOME/.bash_profile" ]]; then
    SHELL_RC="$HOME/.bash_profile"
fi

SCOUT_BIN="$VENV_DIR/bin"
PATH_LINE="export PATH=\"$SCOUT_BIN:\$PATH\""

if [[ -n "$SHELL_RC" ]]; then
    if ! grep -qF "$SCOUT_BIN" "$SHELL_RC" 2>/dev/null; then
        echo "" >> "$SHELL_RC"
        echo "# Scout — Automated Job Applications" >> "$SHELL_RC"
        echo "$PATH_LINE" >> "$SHELL_RC"
        ok "Added 'scout' to your PATH in $SHELL_RC"
    else
        ok "'scout' already in PATH"
    fi
else
    warn "Could not find shell config file. Add this to your shell profile manually:"
    echo "  $PATH_LINE"
fi

# Make scout available in current session
export PATH="$SCOUT_BIN:$PATH"

# ── 14. Health check ───────────────────────────────────────────────
info "Running a health check..."
"$SCOUT_BIN/scout" doctor || true

# ── Done! ──────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}Scout installed successfully!${NC}"
echo ""
echo -e "  Next step — run the setup wizard:"
echo ""
echo -e "    ${CYAN}scout setup${NC}"
echo ""
echo -e "  This will ask for your API key, job preferences,"
echo -e "  and resume info. Takes about 3 minutes."
echo ""
if [[ -n "$SHELL_RC" ]]; then
    echo -e "  ${YELLOW}Open a new terminal first, or run: source $SHELL_RC${NC}"
else
    echo -e "  ${YELLOW}You may need to open a new terminal for the 'scout' command to work.${NC}"
fi
echo ""
