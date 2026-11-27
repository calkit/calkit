#!/usr/bin/env bash
# Install the pinned tools and build all three projects from shared/.
# A record of how round 1's projects were built, not a pipeline stage:
# it needs the network and writes the projects and tools into this
# folder, which Git ignores.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
bash "$HERE/install-openresearch.sh"
bash "$HERE/install-astra.sh"
bash "$HERE/build-calkit.sh"
bash "$HERE/build-astra.sh"
bash "$HERE/build-openresearch.sh"
