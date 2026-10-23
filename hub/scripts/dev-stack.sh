#!/usr/bin/env bash
# Run docker compose for this worktree's dev stack.
#
# Each worktree gets its own Compose project, so its database, migrations,
# and DVC data stay separate from other branches'. The name is kept as
# COMPOSE_PROJECT_NAME in hub/.env, where plain docker compose commands pick
# it up too, and defaults to the worktree's directory name, so the checkout
# named calkit keeps the original calkit stack. Stacks share ports, so only
# one runs at a time.
set -euo pipefail
hub_dir=$(cd "$(dirname "$0")/.." && pwd)
env_file="$hub_dir/.env"
# A new worktree has no .env, since it's gitignored, so start from the main
# checkout's, without its stack name
if [ ! -f "$env_file" ]; then
  main_env="$(dirname "$(git -C "$hub_dir" rev-parse --path-format=absolute --git-common-dir)")/hub/.env"
  if [ ! -f "$main_env" ]; then
    echo "No $env_file; create one from the hub's .env template" >&2
    exit 1
  fi
  echo "Copying $main_env to $env_file" >&2
  grep -v '^COMPOSE_PROJECT_NAME=' "$main_env" >"$env_file" || true
fi
name=$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' "$env_file" | tail -n 1)
if [ -z "$name" ]; then
  name=$(basename "$(dirname "$hub_dir")" | tr '[:upper:]' '[:lower:]' |
    tr -c 'a-z0-9_\n-' '-')
  case $name in calkit*) ;; *) name="calkit-$name" ;; esac
  printf '\n# This worktree'"'"'s dev stack (see scripts/dev-stack.sh)\nCOMPOSE_PROJECT_NAME=%s\n' \
    "$name" >>"$env_file"
fi
export COMPOSE_PROJECT_NAME=$name
# A stack by this name from another directory would have its containers
# recreated from this one's source and its database migrated by this branch
owner=$(docker ps -a --filter "label=com.docker.compose.project=$name" \
  --format '{{.Label "com.docker.compose.project.working_dir"}}' | head -n 1)
if [ -n "$owner" ] && [ "$owner" != "$hub_dir" ]; then
  echo "The '$name' stack belongs to $owner." >&2
  echo "Set COMPOSE_PROJECT_NAME in $env_file to use your own." >&2
  exit 1
fi
# Another worktree's stack holds the ports, so starting this one would fail
# partway
case ${1:-} in
up | run | start | restart)
  others=$(docker ps --filter "label=com.docker.compose.service=backend" \
    --format '{{.Label "com.docker.compose.project"}} {{.Label "com.docker.compose.project.working_dir"}}' |
    awk -v n="$name" '$1 != n && $2 ~ /\/hub$/')
  if [ -n "$others" ]; then
    echo "Another hub stack is running; stop it first:" >&2
    echo "$others" | while read -r project dir; do
      echo "    docker compose -p $project stop    # from $dir" >&2
    done
    exit 1
  fi
  ;;
esac
# --profile objects runs the bundled MinIO; profiles can only be activated
# from the command line or COMPOSE_PROFILES, never from a compose file, and
# keeping it out of .env keeps it out of containers
exec docker compose --profile objects \
  -f "$hub_dir/docker-compose.yml" \
  -f "$hub_dir/docker-compose.override.yml" "$@"
