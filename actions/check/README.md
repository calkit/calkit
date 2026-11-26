# Calkit check GitHub Action

<!-- TODO: needs human review -->

A GitHub Action to fail a workflow, e.g., on a pull request, when a Calkit
project's pipeline is stale, i.e., its committed outputs don't match its
inputs.
It names the stale stages and what changed for each in an error annotation
and the job summary, along with the fix: run `calkit run` and commit.

It runs `calkit status --category pipeline --no-env-check --check`, so no
environments are created and it stays fast.
Use the [run action](../run) instead to run the pipeline in CI.

## Usage

```yaml
name: Check pipeline

on:
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: calkit/calkit/actions/check@v0.54.0
```

Referenced by a release tag, the action installs that same version of
Calkit, so a new release of Calkit can't fail the check by itself.
Referenced by a branch or commit, it installs the latest release.
Set `version` to pin another, e.g., `version: 0.54.1`.
If Calkit is already installed, e.g., by an earlier step, that one is used.

Outputs stored with DVC aren't pulled, so they're reported missing and the
check fails.
It's meant for projects whose outputs are stored in Git.

## Development

CI runs the action against a small project on every pull request that
touches it or the CLI, with Calkit installed from the working tree first.
