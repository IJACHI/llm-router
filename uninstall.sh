#!/usr/bin/env bash
# ==============================================================================
# Global Uninstaller Script for ijachi & ijachi-code
# Automatically removes shortcut symlinks from ~/.local/bin, uninstalls pip package,
# and clears cached environment binaries.
# ==============================================================================

set -e

BIN_DIR="$HOME/.local/bin"
INSTALL_DIR="$HOME/.ijachi-app"

echo "🗑️ Uninstalling ijachi & ijachi-code..."

# 1. Remove symlinks
for cmd in ijachi ijachi-code ijachi-router ijr; do
    if [ -f "$BIN_DIR/$cmd" ] || [ -L "$BIN_DIR/$cmd" ]; then
        rm -f "$BIN_DIR/$cmd"
        echo "   ✓ Removed binary: $BIN_DIR/$cmd"
    fi
done

# 2. Remove isolated installation directory if present
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    echo "   ✓ Removed application folder: $INSTALL_DIR"
fi

# 3. Pip uninstall if in active python environment
if command -v pip &> /dev/null; then
    pip uninstall -y ijachi-llm-router &> /dev/null || true
    echo "   ✓ Uninstalled PyPI package"
fi

echo ""
echo "=============================================================================="
echo "✨ UNINSTALL COMPLETE! ijachi has been completely removed from your system."
echo "To reinstall anytime, run:"
echo "curl -fsSL https://raw.githubusercontent.com/IJACHI/llm-router/main/install.sh | bash"
echo "=============================================================================="
