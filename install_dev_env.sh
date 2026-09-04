#!/bin/bash

GREEN='\033[0;32m'
RESET='\033[0m'

print_info() {
    echo -e "${GREEN}[INFO] $1${RESET}"
}

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="$SCRIPT_DIR/.venv"

# Create virtual environment if not exists
if [ ! -d "$VENV_DIR" ]; then
    print_info "Creating virtual environment in $VENV_DIR..."
    python -m venv "$VENV_DIR"
    chmod +x "$VENV_DIR/bin/activate"
else
    print_info "Virtual environment already exists."
fi

# Activate venv and install packages
print_info "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

print_info "Upgrading pip..."
pip install --upgrade pip

print_info "Installing gne in editable mode (dependencies come from pyproject.toml)..."
pip install -e "$SCRIPT_DIR[test]"

print_info "Setup complete!"
print_info "You can now use 'gne' command via the wrapper at tool/gne.sh"
