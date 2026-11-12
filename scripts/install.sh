#!/usr/bin/env sh
# Install Calkit with uv (installing the latter if it isn't yet)
#
# Options, passed with `curl -LsSf install.calkit.org | sh -s -- <options>`:
#   --link                 Also link this machine to the hub, which connects
#                          its workspaces to the hub
#                          (or set CALKIT_INSTALL_LINK=1)
#   --no-shell-completion  Skip installing shell completion

LINK="${CALKIT_INSTALL_LINK:-0}"
COMPLETION=1
for arg in "$@"; do
    case "$arg" in
        --link) LINK=1 ;;
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

# uv's tool directory may not be on this process's PATH yet, and on Git Bash
# it's a Windows path, whose drive letter's colon would split PATH
bin_dir="$(uv tool dir --bin)"
if command -v cygpath >/dev/null 2>&1; then bin_dir="$(cygpath -u "$bin_dir")"; fi
PATH="$bin_dir:$PATH"
export PATH

# Completion is installed per command name, so the `ck` alias gets it too.
# Typer installs it for the shell it's run from, which would be sh when this
# script is piped to it, so it's run from the user's own shell instead, with a
# command after it so that shell can't exec it and drop out of the way.
if [ "$COMPLETION" = 1 ]; then
    echo "Installing shell completion"
    for cmd in calkit ck; do
        if ! "${SHELL:-sh}" -c "$cmd --install-completion && true"; then
            echo "⚠️ Failed to install shell completion for '$cmd'; run '$cmd --install-completion' manually"
        else
            echo "✅ Shell completion installed for '$cmd'"
        fi
    done
fi

if [ "$LINK" = 1 ]; then
    echo "Linking this machine to the hub"
    # When piped into sh, this script is sh's input, so logging in to the hub
    # needs the terminal's
    if (exec </dev/tty) 2>/dev/null; then
        calkit hub link install </dev/tty
    else
        calkit hub link install
    fi
    if [ $? -ne 0 ]; then
        echo "❌ Failed to link this machine; run 'calkit hub link install' to try again"
        exit 1
    fi
fi

echo "✅ Success! 🚀"
