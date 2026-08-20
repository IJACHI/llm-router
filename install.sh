#!/usr/bin/env bash
# ==============================================================================
# Global Installer Script for ijachi & ijachi-code
# Automatically sets up Python virtualenv, installs package, registers global
# shortcuts (ijachi, ijachi-code, ijachi-router), and configures shell PATH.
# ==============================================================================

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"

echo "🚀 Installing ijachi-llm-router & ijachi-code globally..."

# 1. Ensure ~/.local/bin exists
mkdir -p "$BIN_DIR"

# 2. Setup Virtualenv if missing
if [ ! -d "$REPO_DIR/.venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv "$REPO_DIR/.venv"
fi

# 3. Install package editable
echo "⚙️ Installing package dependencies..."
"$REPO_DIR/.venv/bin/pip" install -e "$REPO_DIR"

# 4. Symlink global executables
echo "🔗 Registering global shortcut binaries in $BIN_DIR..."
for cmd in ijachi ijachi-code ijachi-router ijr; do
    if [ -f "$REPO_DIR/.venv/bin/$cmd" ]; then
        ln -sf "$REPO_DIR/.venv/bin/$cmd" "$BIN_DIR/$cmd"
        echo "   ✓ $cmd -> $BIN_DIR/$cmd"
    fi
done

# 5. Configure Shell PATH in ~/.zshrc and ~/.bashrc
SHELL_CONFIGS=("$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile")
PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'

for cfg in "${SHELL_CONFIGS[@]}"; do
    if [ -f "$cfg" ]; then
        if ! grep -q "\$HOME/\.local/bin" "$cfg"; then
            echo "" >> "$cfg"
            echo "# ijachi global PATH" >> "$cfg"
            echo "$PATH_LINE" >> "$cfg"
            echo "   ✓ Added PATH to $cfg"
        fi
    fi
done

echo ""
echo "=============================================================================="
echo "🎉 SUCCESS! ijachi & ijachi-code are now globally installed!"
echo "Type 'ijachi' or 'ijachi-code' in any terminal window to launch."
echo "=============================================================================="
