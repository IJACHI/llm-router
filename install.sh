#!/usr/bin/env bash
# ==============================================================================
# Global One-Line Installer Script for ijachi & ijachi-code
# Works both locally and remotely via:
# curl -fsSL https://raw.githubusercontent.com/IJACHI/llm-router/main/install.sh | bash
# ==============================================================================

set -e

INSTALL_DIR="$HOME/.ijachi-app"
BIN_DIR="$HOME/.local/bin"
REPO_URL="https://github.com/IJACHI/llm-router.git"

echo "🚀 Installing ijachi & ijachi-code globally..."

mkdir -p "$BIN_DIR"

# 1. Determine if running locally inside repo or via curl remote pipe
if [ -f "pyproject.toml" ] && [ -d "ijachi_router" ]; then
    TARGET_DIR="$(pwd)"
else
    TARGET_DIR="$INSTALL_DIR"
    if [ -d "$TARGET_DIR" ]; then
        echo "🔄 Updating existing installation in $TARGET_DIR..."
        git -C "$TARGET_DIR" pull --rebase origin main || true
    else
        echo "📥 Downloading ijachi codebase..."
        git clone "$REPO_URL" "$TARGET_DIR"
    fi
fi

# 2. Setup Virtualenv
if [ ! -d "$TARGET_DIR/.venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv "$TARGET_DIR/.venv"
fi

# 3. Upgrade pip and install package
echo "⚙️ Installing dependencies..."
"$TARGET_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$TARGET_DIR/.venv/bin/pip" install --quiet -e "$TARGET_DIR"

# 4. Symlink global shortcut executables to ~/.local/bin
echo "🔗 Registering global shortcut binaries in $BIN_DIR..."
for cmd in ijachi ijachi-code ijachi-router ijr; do
    if [ -f "$TARGET_DIR/.venv/bin/$cmd" ]; then
        ln -sf "$TARGET_DIR/.venv/bin/$cmd" "$BIN_DIR/$cmd"
        echo "   ✓ $cmd -> $BIN_DIR/$cmd"
    fi
done

# 5. Configure Shell PATH in ~/.zshrc, ~/.bashrc, ~/.profile
PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
SHELL_CONFIGS=("$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile")

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
echo "Open a new terminal tab or run 'source ~/.zshrc', then type 'ijachi'."
echo "=============================================================================="
