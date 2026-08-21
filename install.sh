#!/usr/bin/env bash
# ==============================================================================
# Global One-Line Installer Script for ijachi & ijachi-code
# Works both locally and remotely via:
# curl -fsSL https://raw.githubusercontent.com/IJACHI/llm-router/main/install.sh | bash
# ==============================================================================

set -e

INSTALL_DIR="$HOME/.ijachi-app"
REPO_URL="https://github.com/IJACHI/llm-router.git"

echo "🚀 Installing ijachi & ijachi-code globally..."

# Detect optimal writable system PATH directory for instant executable access
TARGET_BIN=""
for candidate in "/opt/homebrew/bin" "/usr/local/bin" "$HOME/.local/bin"; do
    if [ -d "$candidate" ] && [ -w "$candidate" ]; then
        TARGET_BIN="$candidate"
        break
    fi
done

if [ -z "$TARGET_BIN" ]; then
    TARGET_BIN="$HOME/.local/bin"
    mkdir -p "$TARGET_BIN"
fi

# 1. Determine if running locally inside repo or via curl remote pipe
if [ -f "pyproject.toml" ] && [ -d "ijachi_router" ]; then
    TARGET_DIR="$(pwd)"
else
    TARGET_DIR="$INSTALL_DIR"
    if [ -d "$TARGET_DIR" ]; then
        echo "🔄 Updating existing installation..."
        git -C "$TARGET_DIR" pull --rebase origin main >/dev/null 2>&1 || true
    else
        echo "📥 Downloading ijachi codebase..."
        git clone "$REPO_URL" "$TARGET_DIR" >/dev/null 2>&1
    fi
fi

# 2. Setup Virtualenv
if [ ! -d "$TARGET_DIR/.venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv "$TARGET_DIR/.venv" >/dev/null 2>&1
fi

# 3. Upgrade pip and install package (suppressing warnings & cache)
echo "⚙️ Installing dependencies..."
PIP_DISABLE_PIP_VERSION_CHECK=1 "$TARGET_DIR/.venv/bin/pip" install --quiet --no-cache-dir --no-warn-script-location --upgrade pip >/dev/null 2>&1 || true
PIP_DISABLE_PIP_VERSION_CHECK=1 "$TARGET_DIR/.venv/bin/pip" install --quiet --no-cache-dir --no-warn-script-location -e "$TARGET_DIR" >/dev/null 2>&1 || true

# 4. Symlink global shortcut executables to active system PATH directory
echo "🔗 Registering global shortcut binaries in $TARGET_BIN..."
for cmd in ijachi ijachi-code ijachi-router ijr; do
    if [ -f "$TARGET_DIR/.venv/bin/$cmd" ]; then
        ln -sf "$TARGET_DIR/.venv/bin/$cmd" "$TARGET_BIN/$cmd"
        echo "   ✓ $cmd -> $TARGET_BIN/$cmd"
    fi
done

# 5. Configure Shell PATH in ~/.zshrc, ~/.bashrc, ~/.profile as fallback
PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
SHELL_CONFIGS=("$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile")

for cfg in "${SHELL_CONFIGS[@]}"; do
    if [ -f "$cfg" ]; then
        if ! grep -q "\$HOME/\.local/bin" "$cfg"; then
            echo "" >> "$cfg"
            echo "# ijachi global PATH" >> "$cfg"
            echo "$PATH_LINE" >> "$cfg"
        fi
    fi
done

echo ""
echo "=============================================================================="
echo "🎉 SUCCESS! ijachi & ijachi-code are now globally installed!"
echo "Type 'ijachi' or 'ijachi-code' in any terminal window to launch."
echo "=============================================================================="
