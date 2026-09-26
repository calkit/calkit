#!/usr/bin/env bash

set -euo pipefail

if [ $# -gt 1 ]; then
  echo "usage: $0 [version]" >&2
  exit 1
fi

# Files where the image tag is defined
FILES=(
  calkit/latex.py
  calkit/resources/devcontainer/devcontainer.json
  calkit/resources/vscode/settings.json
  docs/pipeline/index.md
  docs/tutorials/existing-project.md
  hub/frontend/src/lib/environments.ts
)

if [ $# -eq 0 ]; then
  grep -Eho 'ghcr\.io/calkit/latex:[0-9]+\.[0-9]+\.[0-9]+' "${FILES[@]}" \
    | sed 's|.*:||' \
    | sort -u
  exit 0
fi

VERSION=${1#v}

# BSD sed takes its backup suffix as the argument to -i, GNU sed doesn't
if sed --version >/dev/null 2>&1; then
  sed -i -E \
    "s|ghcr\.io/calkit/latex:[0-9]+\.[0-9]+\.[0-9]+|ghcr.io/calkit/latex:${VERSION}|g" \
    "${FILES[@]}"
else
  sed -i '' -E \
    "s|ghcr\.io/calkit/latex:[0-9]+\.[0-9]+\.[0-9]+|ghcr.io/calkit/latex:${VERSION}|g" \
    "${FILES[@]}"
fi
