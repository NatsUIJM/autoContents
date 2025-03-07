#!/bin/zsh

echo "Script starting..."

# Install Xcode Command Line Tools
echo "[0/8] Installing Xcode Command Line Tools..."
xcode-select --install || true

SCRIPT_DIR=${0:a:h}
PROJECT_DIR=$(dirname "$SCRIPT_DIR")

# Check Homebrew first (as normal user)
if command -v brew >/dev/null 2>&1; then
    echo "[1/8] Homebrew is already installed, skipping..."
else
    echo "[1/8] Installing Homebrew..."
    if [ $(id -u) -eq 0 ]; then
        echo "Detected root user. Homebrew must be installed as a normal user."
        echo "Please run the script without sudo first."
        exit 1
    fi
    /bin/zsh -c "$(curl -fsSL https://gitee.com/cunkai/HomebrewCN/raw/master/Homebrew.sh)" || {
        echo "Homebrew installation failed"
        exit 1
    }
    eval "$(/opt/homebrew/bin/brew shellenv)"
    
    echo "Homebrew installed successfully."
    exit 0
fi

# Function to run command as user, falling back to sudo -u if su -c fails
run_as_user() {
    local cmd="$1"
    if ! su - $SUDO_USER -c "$cmd" 2>/dev/null; then
        echo "su command failed, trying with sudo -u instead..."
        sudo -u $SUDO_USER $cmd
        return $?
    fi
    return 0
}

# Install brew packages as normal user
echo "[2/8] Installing Python 3.11..."
if command -v python3.11 >/dev/null 2>&1; then
    echo "Python 3.11 is already installed, skipping..."
else
    run_as_user "brew install python@3.11"
    if [ $? -ne 0 ]; then
        echo "Python installation failed"
        exit 1
    fi
    # 添加 Python 3.11 到 PATH
    echo 'export PATH="/opt/homebrew/opt/python@3.11/bin:$PATH"' >> ~/.zshrc
    source ~/.zshrc
fi

echo "[3/8] Checking Poppler..."
if brew list poppler >/dev/null 2>&1; then
    echo "Poppler is already installed, checking binary..."
    if command -v pdftotext >/dev/null 2>&1; then
        echo "Poppler binary found, skipping..."
    else
        echo "Poppler binary not found, reinstalling..."
        run_as_user "brew reinstall poppler"
        if [ $? -ne 0 ]; then
            echo "Poppler reinstallation failed"
            exit 1
        fi
    fi
else
    echo "Installing Poppler..."
    run_as_user "brew install poppler"
    if [ $? -ne 0 ]; then
        echo "Poppler installation failed"
        exit 1
    fi
fi

# Now check for sudo rights for remaining operations
if [ $(id -u) -ne 0 ]; then
    echo "[X] Please run remaining operations with sudo!"
    exit 1
else
    echo "[OK] Admin rights confirmed for remaining operations"
fi

echo "Current directory: $(pwd)"
echo "Changing to project directory: $PROJECT_DIR"
cd "$PROJECT_DIR"
if [ $? -ne 0 ]; then
    echo "Failed to change directory"
    exit 1
fi

echo "[4/8] Creating virtual environment..."
python3.11 -m venv .venv
if [ $? -ne 0 ]; then
    echo "Virtual environment creation failed"
    exit 1
fi

echo "[5/8] Setting pip source..."
source .venv/bin/activate
if [ $? -ne 0 ]; then
    echo "Virtual environment activation failed"
    exit 1
fi

pip config set global.index-url https://mirrors.aliyun.com/pypi/simple
if [ $? -ne 0 ]; then
    echo "Pip source configuration failed"
    exit 1
fi

echo "[6/8] Installing project dependencies..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Dependencies installation failed"
    exit 1
fi

echo "[7/8] Setting execute permissions for macos_start.command..."
chmod +x "$PROJECT_DIR/macos_start.command"
if [ $? -ne 0 ]; then
    echo "Setting execute permissions failed"
    exit 1
fi

echo ""
echo "[8/8] All installations completed!"