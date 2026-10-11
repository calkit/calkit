#!/usr/bin/env sh
# Install Calkit with uv (installing the latter if it isn't yet)
#
# Options, passed with `curl -LsSf install.calkit.org | sh -s -- <options>`:
#   --operator             Also install the Calkit Operator, which lets the hub
#                          use this machine (or set CALKIT_INSTALL_OPERATOR=1)
#   --no-shell-completion  Skip installing shell completion

OPERATOR="${CALKIT_INSTALL_OPERATOR:-0}"
COMPLETION=1
for arg in "$@"; do
    case "$arg" in
        --operator) OPERATOR=1 ;;
        --no-shell-completion) COMPLETION=0 ;;
        *) echo "⚠️ Ignoring unknown option '$arg'" ;;
    esac
done

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

# Where uv put the executables, which may not be on this shell's PATH yet
BIN="$(uv tool dir --bin)"

# Completion is installed per command name, so the `ck` alias gets it too
if [ "$COMPLETION" = 1 ]; then
    echo "Installing shell completion"
    for cmd in calkit ck; do
        if ! "$BIN/$cmd" --install-completion; then
            echo "⚠️ Failed to install shell completion for '$cmd'; run '$cmd --install-completion' manually"
        else
            echo "✅ Shell completion installed for '$cmd'"
        fi
    done
fi

if [ "$OPERATOR" = 1 ]; then
    echo "Installing the Calkit Operator"
    # When piped into sh, this script is sh's input, so logging in to the hub
    # needs the terminal's
    if (exec </dev/tty) 2>/dev/null; then
        "$BIN/calkit" operator install </dev/tty
    else
        "$BIN/calkit" operator install
    fi
    if [ $? -ne 0 ]; then
        echo "❌ Failed to install the Operator; run 'calkit operator install' to try again"
        exit 1
    fi
fi

echo "✅ Success! 🚀"
