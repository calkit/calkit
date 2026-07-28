#!/usr/bin/env bash
# Fetch the stock TeX Live filesystem bundles into frontend/public/tex/.
#
# These are large (~190 MB) and carry the various per-package TeX Live licenses,
# so they are git-ignored and pulled from the upstream busytex release at build
# time (see frontend/Dockerfile) rather than vendored. Our patched engine
# (busytex.{js,wasm}, MIT) IS committed — see public/tex/LICENSE-busytex — so it
# is not fetched here.
#
# Uses curl only (no gh/auth) against PUBLIC release assets, and skips files that
# already exist so local builds (which have the bundles on disk) are a no-op.
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)/public/tex"
mkdir -p "$DIR"

# Upstream busytex release. The .data are engine-agnostic TeX Live 2023 data,
# compatible with our patched build.
DATA_REPO="busytex/busytex"
DATA_TAG="build_wasm_4499aa69fd3cf77ad86a47287d9a5193cf5ad993_7936974349_1"
DATA_BASE="https://github.com/${DATA_REPO}/releases/download/${DATA_TAG}"

# curl's own --retry does NOT cover error 23 (write-to-destination failures),
# which show up as transient hiccups on large sequential writes in some build
# environments (e.g. Docker Desktop's overlayfs/virtiofs). Wrap curl in a bash
# retry loop and resume with -C - so a hiccup picks up where it left off instead
# of re-downloading from zero or aborting the whole build.
fetch() {
  if [ -s "$DIR/$1" ]; then echo "  = $1 (present)"; return 0; fi
  echo "  -> $1"
  local attempt=1 max=5
  while true; do
    if curl -fSL -C - --retry 3 --retry-delay 2 --retry-all-errors \
        -o "$DIR/$1" "$DATA_BASE/$1"; then
      return 0
    fi
    if [ "$attempt" -ge "$max" ]; then
      echo "  x $1 failed after $max attempts" >&2
      return 1
    fi
    echo "  ! $1 attempt $attempt/$max failed, resuming in 3s..." >&2
    attempt=$((attempt + 1))
    sleep 3
  done
}

echo "TeX Live bundles <- ${DATA_REPO}@${DATA_TAG}"
for f in \
  texlive-basic.data texlive-basic.js \
  ubuntu-texlive-latex-base.data ubuntu-texlive-latex-base.js \
  ubuntu-texlive-latex-recommended.data ubuntu-texlive-latex-recommended.js \
  ubuntu-texlive-latex-extra.data ubuntu-texlive-latex-extra.js \
  ubuntu-texlive-science.data ubuntu-texlive-science.js \
  ubuntu-texlive-fonts-recommended.data ubuntu-texlive-fonts-recommended.js
do
  fetch "$f"
done

echo "Done -> $DIR"
