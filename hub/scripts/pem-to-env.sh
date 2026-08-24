#!/usr/bin/env bash
# Convert a PEM key file into a single-line .env value, with newlines escaped
# as literal "\n". Handy for pasting a GitHub App private key into .env as
# GH_APP_PRIVATE_KEY (python-dotenv expands the \n back to real newlines on
# load).
#
# Usage:
#   scripts/pem-to-env.sh path/to/key.pem                    # -> "...\n..."
#   scripts/pem-to-env.sh path/to/key.pem GH_APP_PRIVATE_KEY # -> VAR="...\n..."
set -euo pipefail
pem="${1:?Usage: pem-to-env.sh path/to/key.pem [ENV_VAR_NAME]}"
value="$(awk 'NR>1{printf "\\n"} {printf "%s", $0}' "$pem")"
if [ "${2:-}" ]; then
  printf '%s="%s"\n' "$2" "$value"
else
  printf '"%s"\n' "$value"
fi
