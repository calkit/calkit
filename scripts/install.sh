#!/usr/bin/env sh
# Install Calkit with uv (installing the latter if it isn't yet)

# Check if uv is installed
if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    if [ $? -ne 0 ]; then
        echo "❌ Failed to install uv; Please install it manually"
        exit 1
    fi
    [ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env"
    echo "✅ uv installed successfully"
else
    echo "✅ uv is already installed"
fi

# Install Calkit using uv
echo "Installing Calkit"
if ! uv tool install --upgrade calkit-python --python=3.14; then
    echo "❌ Failed to install Calkit; Please check your uv installation"
    exit 1
fi

echo "Installing shell completion"
if ! calkit --install-completion; then
    echo "⚠️  Failed to install shell completion; run 'calkit --install-completion' manually"
else
    echo "✅ Shell completion installed"
fi

echo "✅ Success! 🚀"
