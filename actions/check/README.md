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
      - uses: actions/checkout@v7
      - uses: calkit/calkit/actions/check@v0.54.0
```

Referenced by a release tag, the action installs that same version of
Calkit, so a new release of Calkit can't fail the check by itself.
Referenced by a branch or commit, it installs the latest release.
Set `version` to pin another, e.g., `version: 0.54.1`.
If Calkit is already installed, e.g., by an earlier step, that one is used.

## Inputs

| Input               | Default | Description                                          |
| ------------------- | ------- | ---------------------------------------------------- |
| `version`           |         | Version of `calkit-python` to install                |
| `working_directory` | `.`     | Project directory, if not at the root of the repo    |
| `env_check`         | `false` | Check environments, creating them, before the status |

## Outputs

| Output    | Description                                           |
| --------- | ----------------------------------------------------- |
| `passed`  | `true` if the pipeline is up to date, else `false`    |
| `summary` | The Markdown job summary, listing stale stages if any |

## Limitations

Environments aren't checked, so a change to one's definition in
`calkit.yaml`, e.g., a new Docker image tag, doesn't make the stages using
it stale until it's checked, e.g., by `calkit run` or `calkit status`
locally.
Set `env_check: true` to check them here, which creates them, so the tools
they need, e.g., Conda or Docker, must be set up in earlier steps.

Outputs stored with DVC aren't pulled, so they're reported missing and the
check fails.
It's meant for projects whose outputs are stored in Git.

## Development

`calkit status --check` writes the annotation and job summary itself when
`GITHUB_ACTIONS` is set, so that's tested with the CLI.
CI runs the action on Linux, macOS, and Windows on every pull request that
touches it or the CLI, against a small project with Calkit installed from the
working tree, and installing an older release of Calkit.
