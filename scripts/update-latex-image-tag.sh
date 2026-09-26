#!/usr/bin/env bash

set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <version>" >&2
  exit 1
fi

VERSION=${1#v}

# devcontainer.json is generated from the VS Code settings, and the
# same replacement in both leaves them in sync, which
# calkit/tests/test_resources.py checks
FILES=(
  calkit/latex.py
  calkit/resources/devcontainer/devcontainer.json
  calkit/resources/vscode/settings.json
  docs/pipeline/index.md
  docs/tutorials/existing-project.md
  hub/frontend/src/lib/environments.ts
)

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
