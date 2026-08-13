# Calkit run GitHub Action

A GitHub Action to run a Calkit project's pipeline and optionally save results
(commit and push) to Git and DVC.

The action lives in the Calkit repo because it's a thin wrapper around a
sequence of CLI commands, and it reads `calkit list environments` output to
decide what tooling to install.
Keeping it here means a change to either is tested against the other before
release.

## Usage

Reference the action by a Calkit release tag:

```yaml
- uses: calkit/calkit/actions/run@v0.43.0
```

The easiest way to add it to a project is:

```sh
calkit update github-actions
```

which writes the workflow below to `.github/workflows/run-calkit.yml`,
pinned to the version of Calkit that wrote it.
Rerun it after upgrading Calkit to move the pin.

<!-- Do not edit the snippet below since it is automatically populated -->
<!-- snippet:example.yml:start -->

```yaml
name: Run pipeline

on:
  push:
    branches:
      - main
  pull_request:
  workflow_dispatch:

permissions:
  contents: write
  id-token: write

# Make sure we only ever run one per branch so we don't have issues pushing
# after running the pipeline
concurrency:
  group: calkit-run-${{ github.ref }}
  cancel-in-progress: false

jobs:
  main:
    name: Run
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          # For PRs, checkout the head ref to avoid detached HEAD
          ref: ${{ github.head_ref || github.ref_name }}
          token: ${{ secrets.GITHUB_TOKEN }}
      - name: Configure Git credentials
        run: |
          git config user.name github-actions[bot]
          git config user.email 41898282+github-actions[bot]@users.noreply.github.com
      # This action automatically runs necessary setup steps based on environments
      - name: Run Calkit
        uses: calkit/calkit/actions/run@main
```

<!-- snippet:example.yml:end -->

Note the permissions, concurrency, and checkout options.
The action detects required environment kinds from `calkit.yaml` and sets up
needed tooling (for example Calkit via `uv`, Julia, Pixi, Conda, R, MATLAB,
and Docker Buildx) before running.

## Configuration

If simply running the pipeline is desired, the `save` option can be set to
`false`.
Additionally, caching DVC data can be disabled with `cache_dvc: false`.
When caching is enabled, the action saves DVC cache entries using the current
branch name plus the current commit SHA.
The restore step first looks for the
most recent cache for the current branch and then falls back to the default
branch cache if the current branch cache doesn't exist yet.

## System dependencies

System dependencies like `uv`, `pixi`, `conda`, `juliaup` will be installed
automatically if missing, and if the project has an environment with the
corresponding kind.
If you'd like control over which versions are used, you can add setup steps
before the Calkit Action, and Calkit will detect and skip installation.

## Development

`example.yml` is the source for both the snippet above and the copy bundled
into the Python package at `calkit/resources/github-actions`.
After editing it, run `make sync-resources`.

CI runs the action against real example projects on every pull request that
touches this directory, with Calkit installed from the working tree first, so
the action exercises the CLI being changed rather than the last release.

## Previous home

This action was previously published from
[`calkit/run-action`](https://github.com/calkit/run-action), which is no
longer maintained.
Workflows referencing `calkit/run-action@v2` still work, but should be
updated to `calkit/calkit/actions/run@<version>`, which
`calkit update github-actions` will do in place.
