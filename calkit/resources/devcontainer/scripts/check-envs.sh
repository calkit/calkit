#!/usr/bin/env bash

# Run `calkit check envs` fully detached from the lifecycle hook that invoked
# it, so the dev container/Codespace gets marked ready immediately. Setting up
# environments can involve multi-GB image pulls (texlive, for example), which
# would otherwise leave the user staring at a spinner for many minutes.
#
# Progress is logged to $HOME/.cache/check-envs.log.

CACHE_DIR="$HOME/.cache"
mkdir -p "$CACHE_DIR"
LOGFILE="$CACHE_DIR/check-envs.log"

# How long to wait for the Docker daemon to become accessible, in seconds
MAX_WAIT=300

if [ "${1:-}" != "--worker" ]; then
    : > "$LOGFILE"
    # Prefer setsid to fully detach; fall back to nohup if it's unavailable
    if command -v setsid > /dev/null 2>&1; then
        setsid bash "$0" --worker > /dev/null 2>&1 < /dev/null &
    else
        nohup bash "$0" --worker > /dev/null 2>&1 < /dev/null &
    fi
    echo "Started environment check in the background (PID: $!)"
    echo "Progress is being logged to $LOGFILE"
    exit 0
fi

# Everything below here runs in the detached background process

log() {
    printf '[%s] %s\n' "$(date +%Y-%m-%dT%H:%M:%S%z)" "$*" >> "$LOGFILE"
}

log "Waiting up to ${MAX_WAIT}s for the Docker daemon"
COUNT=0
until docker info > /dev/null 2>&1; do
    COUNT=$((COUNT + 1))
    if [ "$COUNT" -ge "$MAX_WAIT" ]; then
        log "ERROR: Docker daemon not accessible after ${MAX_WAIT}s; skipping environment check"
        exit 1
    fi
    sleep 1
done
log "Docker daemon is up after ${COUNT}s"

# shellcheck disable=SC1091
. /opt/conda/bin/activate 2> /dev/null || true

log "Running: calkit check envs"
calkit check envs >> "$LOGFILE" 2>&1
EXIT_CODE=$?
if [ "$EXIT_CODE" -eq 0 ]; then
    log "Environment check completed successfully"
else
    log "Environment check failed with exit code ${EXIT_CODE}"
fi
