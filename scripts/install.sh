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

# uv's tool directory may not be on this process's PATH yet, and on Git Bash
# it's a Windows path, whose drive letter's colon would split PATH
bin_dir="$(uv tool dir --bin)"
if command -v cygpath >/dev/null 2>&1; then bin_dir="$(cygpath -u "$bin_dir")"; fi
PATH="$bin_dir:$PATH"
export PATH

# Completion is installed per command name, so the `ck` alias gets it too.
# Typer installs it for the shell it's run from, which would be sh when this
# script is piped to it, so it's run from the user's own shell instead.
echo "Installing shell completion"
for cmd in calkit ck; do
    if ! "${SHELL:-sh}" -c "$cmd --install-completion"; then
        echo "⚠️ Failed to install shell completion for '$cmd'; run '$cmd --install-completion' manually"
    else
        echo "✅ Shell completion installed for '$cmd'"
    fi
done

echo "✅ Success! 🚀"
