#!/usr/bin/env bash

set -euo pipefail

conda init bash
# shellcheck disable=SC1091
. /opt/conda/bin/activate

# Kick off the environment check in the background so it doesn't hold up the
# container being marked ready; check-envs.sh detaches and waits for the Docker
# daemon itself
bash "${INIT_SCRIPTS_DIR:-/usr/local/share/devcontainer-init}/check-envs.sh"
