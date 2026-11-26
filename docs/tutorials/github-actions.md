# Running Calkit in GitHub Actions

A project can be set up to automatically run the pipeline every time a
change is pushed, either to the main branch or on a pull request,
using GitHub Actions.
The latter allows for inspection of outputs before merging into main.

Add a Calkit GitHub Actions workflow to the project with:

```sh
calkit update github-actions
```

Note that this command can be run at any time to update to the latest
recommended workflow configuration.
The action is pinned to the version of Calkit that wrote the workflow,
so after upgrading Calkit, rerun the command to move the pin.
If the workflow has been customized, only the action's version is updated,
and everything else in it is left alone.

Inside `.github/workflows/run-calkit.yml` you'll then see something like:

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
      - name: Setup uv
        uses: astral-sh/setup-uv@v5
      - name: Install Calkit
        run: uv tool install calkit-python
      - name: Run Calkit
        uses: calkit/calkit/actions/run@main
```

This particular example installs Calkit with uv,
meaning `uv` and `uv-venv` environment types will work without any additional
configuration.
Docker is also installed by default on the `ubuntu-latest` machine.
If other environment types are used in the project,
setup steps may be necessary for those, e.g.,
[`setup-miniconda`](https://github.com/marketplace/actions/setup-miniconda)
or [`install-juliaup`](https://github.com/marketplace/actions/install-juliaup).

By default, the Calkit GitHub Action will run the pipeline and save results.
This is why the workflow needs write permissions and configures Git
credentials to act as the GitHub Actions bot.
The workflow also limits concurrency so multiple jobs don't attempt to push
to the same branch at the same time.

It's possible to configure the action to not save results, e.g., if you
just want to check that the pipeline can run without errors.
See the
[documentation](https://github.com/calkit/calkit/tree/main/actions/run)
for all available options.

<!-- TODO: needs human review -->

## Caching environments

The action caches the environments the pipeline uses, e.g., conda
environments and virtual environments, keyed by their spec and lock files,
so a run whose environments haven't changed restores them instead of
building them.
After a lock changes, they're built from scratch, then cached again.
`calkit describe env-cache` shows what's cached and the key.
This makes it cheap to use the project's own environment in other
workflows, e.g., to render a website with the version of Quarto the
environment pins, rather than installing one separately,
which may not be the version used by authors and the pipeline.
For example, a workflow that publishes a Quarto site to GitHub Pages:

```yaml
name: Publish

on:
  push:
    branches:
      - main
  workflow_dispatch:

permissions:
  contents: read
  id-token: write
  pages: write

jobs:
  publish:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      # Restores the environments, building them only if what they're
      # built from changed, and pulls or runs whatever the site shows
      - name: Run pipeline
        uses: calkit/calkit/actions/run@main
        with:
          save: "false"
      - name: Render site
        run: calkit xenv -n main -- quarto render
      - uses: actions/upload-pages-artifact@v3
        with:
          path: _site
      - id: deploy
        uses: actions/deploy-pages@v4
```

Set `cache_envs: "false"` to turn this off, e.g., if large environments that
change often would use up the repository's
[cache storage](https://docs.github.com/en/actions/reference/dependency-caching-reference#usage-limits-and-eviction-policy).
