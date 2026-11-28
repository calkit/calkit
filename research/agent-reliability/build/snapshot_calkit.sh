#!/usr/bin/env bash
# Snapshot one commit of Calkit into <dest>, so trials, builds, and grading
# use a fixed Calkit while the repo moves on: its source from `git archive`,
# a venv with the dependencies that commit's uv.lock pins, a `calkit`
# wrapper in bin/, and the agent plugin in plugin/. Reads only the repo's Git
# objects, never its working tree or environment.
#
# Usage: build/snapshot_calkit.sh <rev> <dest>
# Prints the wrapper's path, for BENCH_CALKIT.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)"
SHA="$(git -C "$REPO" rev-parse --verify "$1^{commit}")"
DEST="$(mkdir -p "$2" && cd "$2" && pwd)"
unset VIRTUAL_ENV PYTHONPATH
mkdir -p "$DEST/src" "$DEST/bin" "$DEST/plugin" "$DEST/project"
git -C "$REPO" archive "$SHA" calkit | tar -x -C "$DEST/src"
git -C "$REPO" archive "$SHA" agent-plugin \
  | tar -x -C "$DEST/plugin" --strip-components 1
# The dependencies, from the commit's lock; uv needs the workspace members'
# pyproject.toml files to read it
specs=(pyproject.toml uv.lock .python-version)
for member in hub/backend/pyproject.toml; do
  if git -C "$REPO" cat-file -e "$SHA:$member" 2>/dev/null; then
    specs+=("$member")
  fi
done
git -C "$REPO" archive "$SHA" "${specs[@]}" | tar -x -C "$DEST/project"
uv sync -q --frozen --no-install-project --no-dev --project "$DEST/project"
# Calkit reads its version from package metadata, which an uninstalled
# source tree lacks; give it the one hatch-vcs would, e.g.,
# 0.53.2.dev16+g4718ca51d for 16 commits after v0.53.1
describe="$(git -C "$REPO" describe --tags --match 'v[0-9]*' --long \
  --abbrev=9 "$SHA")"
tag="${describe%-*-g*}"
tag="${tag#v}"
distance="${describe%-g*}"
distance="${distance##*-}"
if [ "$distance" = 0 ]; then
  version="$tag"
else
  next="${tag%.*}.$((${tag##*.} + 1))"
  version="$next.dev$distance+g${SHA:0:9}"
fi
dist_info="$DEST/src/calkit_python-$version.dist-info"
mkdir -p "$dist_info"
printf 'Metadata-Version: 2.1\nName: calkit-python\nVersion: %s\n' \
  "$version" > "$dist_info/METADATA"
cat > "$DEST/bin/calkit" <<EOF
#!/bin/sh
# Calkit at $SHA
PYTHONPATH="$DEST/src\${PYTHONPATH:+:\$PYTHONPATH}" exec \\
  "$DEST/project/.venv/bin/python" -c \\
  'import sys; from calkit.cli import run; sys.exit(run())' "\$@"
EOF
chmod +x "$DEST/bin/calkit"
echo "$DEST/bin/calkit"
