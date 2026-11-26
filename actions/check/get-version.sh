#!/usr/bin/env bash
# Print the calkit-python version matching the release tag this action is
# referenced by, or nothing if it isn't referenced by one, e.g., by a branch.
# The ref is in the path the action is checked out at, e.g.,
# .../_actions/calkit/calkit/v0.54.0/actions/check
set -euo pipefail
action_path="${1//\\//}"
ref=$(basename "$(dirname "$(dirname "$action_path")")")
if [[ "$ref" =~ ^v[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+)?(\.post[0-9]+)?(\.dev[0-9]+)?$ ]]; then
  echo "${ref#v}"
fi
