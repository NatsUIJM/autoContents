#!/bin/zsh

echo "Script starting..."

# Get script directory and parent directory
SCRIPT_DIR=${0:a:h}
PROJECT_DIR=$(dirname "$SCRIPT_DIR")

# Check admin rights
if [ $(id -u) -ne 0 ]; then
    echo "[X] Please run with sudo!"
    exit 1
else
    echo "[OK] Admin rights confirmed"
fi

# Check Homebrew
if command -v brew >/dev/null 2>&1; then
    echo "[1/6] Homebrew is already installed, skipping..."
else
    echo "[1/6] Installing Homebrew..."
    /bin/zsh -c "$(curl -fsSL https://gitee.com/cunkai/HomebrewCN/raw/master/Homebrew.sh)"
    if [ $? -ne 0 ]; then
        echo "Homebrew installation failed"
        exit 1
    fi
fi

# Check Python 3.11
if command -v python3.11 >/dev/null 2>&1; then
    echo "[2/6] Python 3.11 is already installed, skipping..."
else
    echo "[2/6] Installing Python 3.11..."
    brew install python@3.11
    if [ $? -ne 0 ]; then
        echo "Python installation failed"
        exit 1
    fi
fi

# Check Poppler
echo "[3/6] Checking Poppler..."
if brew list poppler >/dev/null 2>&1; then
    echo "Poppler is already installed, skipping..."
else
    echo "Installing Poppler..."
    brew install poppler
    if [ $? -ne 0 ]; then
        echo "Poppler installation failed"
        exit 1
    fi
fi

echo "Current directory: $(pwd)"

# Change to project directory
echo "Changing to project directory: $PROJECT_DIR"
cd "$PROJECT_DIR"
if [ $? -ne 0 ]; then
    echo "Failed to change directory"
    exit 1
fi

# Create virtual environment
echo "[4/6] Creating virtual environment..."
python3.11 -m venv .venv
if [ $? -ne 0 ]; then
    echo "Virtual environment creation failed"
    exit 1
fi

# Activate virtual environment and set pip source
echo "[5/6] Setting pip source..."
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

# Install dependencies
echo "[6/6] Installing project dependencies..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Dependencies installation failed"
    exit 1
fi

echo ""
echo "[OK] All installations completed!"