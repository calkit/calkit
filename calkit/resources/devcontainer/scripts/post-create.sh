#!/usr/bin/env bash

TEMP_ENV=.calkit/temp/.env

set -euo pipefail

mkdir -p "$(dirname "$TEMP_ENV")"

# Read a single KEY=value pair out of the staged env file. The file lives in
# the workspace, so it's treated as untrusted input and parsed rather than
# sourced, which would execute whatever happens to be in it.
read_staged_var() {
	local key="$1" line
	[ -f "$TEMP_ENV" ] || return 0
	line=$(grep -m 1 "^${key}=" "$TEMP_ENV" 2>/dev/null) || return 0
	line="${line#"${key}="}"
	line="${line%$'\r'}"
	# Strip one layer of surrounding quotes, if present
	case "$line" in
		\"*\") line="${line#\"}" && line="${line%\"}" ;;
		\'*\') line="${line#\'}" && line="${line%\'}" ;;
	esac
	printf '%s' "$line"
}

# Prefer values staged by initializeCommand or a previous container run, then
# anything already in the environment, then the container's own calkit config
STAGED_TOKEN=$(read_staged_var CALKIT_TOKEN)
STAGED_DVC_TOKEN=$(read_staged_var CALKIT_DVC_TOKEN)

CALKIT_TOKEN=${STAGED_TOKEN:-${CALKIT_TOKEN:-}}
CALKIT_DVC_TOKEN=${STAGED_DVC_TOKEN:-${CALKIT_DVC_TOKEN:-}}

if [ -z "${CALKIT_TOKEN:-}" ]; then
	CALKIT_TOKEN=$(calkit config get token 2>/dev/null || true)
fi

if [ -z "${CALKIT_DVC_TOKEN:-}" ]; then
	CALKIT_DVC_TOKEN=$(calkit config get dvc_token 2>/dev/null || true)
fi

if [ -n "${CALKIT_TOKEN:-}" ]; then
	calkit config set token "$CALKIT_TOKEN"
fi

if [ -n "${CALKIT_DVC_TOKEN:-}" ]; then
	calkit config set dvc_token "$CALKIT_DVC_TOKEN"
fi

rm -f "$TEMP_ENV"
