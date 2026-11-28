# Project websites

<!-- prettier-ignore -->
!!! note
    This document was written by Anthropic's Claude Code.

<!-- TODO: needs human review -->

How a Calkit project could get a public website on GitHub Pages,
in three phases, and what not to build. Nothing here is implemented.

- Issues: calkit/calkit#1405, calkit/calkit#855, calkit/calkit#1746
  (websites), calkit/calkit#478 (MyST), calkit/calkit#1415,
  calkit/calkit#1445, and calkit/calkit#1394, calkit/calkit#1144,
  calkit/calkit#1702, calkit/calkit#1749 (compute)

## Why

A project's public face is its README and its hub page.
Many want the publication of the future to be a website, not a PDF,
and a Calkit project holds everything a publication is made of, and more,
so a facade on it should be quick to build.
GitHub Pages is the natural host, but its setup is confusing:
there are two sources, a branch or Actions, and most tools' docs still
describe the branch; Pages must be enabled before a workflow can deploy,
and tags allowed to deploy; the base path is `/<repo>/`, or `/` with a custom
domain or an `<owner>.github.io` repo; and the site is public even for a
private repo, which needs a paid plan.

## Where we are

**Pete's earlier thinking.** calkit/calkit#1405 lists the options:
change the hub's view for finished projects; a container, which needs
serving; a static site, maybe with WASM for computations; or a Pages site
built from the project in the pipeline, pushed to a branch, and also served
from a hub "Website" tab. calkit/calkit#855 asks for the hub project view as
a portable, read-only static site, for decentralization and archival,
noting a Jupyter Book thesis starter kit gives a PDF, "but what about all
the other important stuff like datasets, models, figures, notebooks,
reusability?" calkit/calkit#1746, a duplicate, wants the hub page as the site.

**What exists on `main`:**

- `apps` declares a `static-html` app and the stage that builds it, and the
  hub shows it at `/{owner}/{project}/apps/{name}` at any commit:
  calkit/calkit#1405's "Website tab", for a site stored in Git or DVC.
  `marimo-html-wasm` builds browser-only apps, i.e., its WASM.
- The hub's project page has grown toward calkit/calkit#1746, with
  questions (calkit/calkit#1845) and results with provenance
  (calkit/calkit#1861), and `calkit show question` renders answers.
- `actions/run` sets up environments, gets a Calkit token over OIDC,
  and runs; `calkit update github-actions` writes and re-pins its workflow.
  Nothing handles Pages.
- `calkit update devcontainer` writes a spec that runs in Codespaces,
  linked machines (calkit/calkit#1738) run `calkit run` for their owner,
  and `calkit new project --template` starts from a template.

**In drafts:** `get_provenance_chain` (calkit/calkit#2228) walks a path's
stages upstream with environments, locks, last runs, and freshness, and
calkit/calkit#2201 and calkit/calkit#2203 show provenance in documents.

**The motivating case** is a Quarto notebook publication template.
On a `v*` tag, `build.yml` resets a `publish` branch to `main` and runs
`_build.py`, which `git checkout`s each tag to copy its `index.ipynb` and
`_freeze/index` in as `index_v*` copies, edits `_quarto.yml` to list them,
and opens a PR into `publish`. On merge, `publish.yml` installs the latest
Quarto, renders, and pushes to `gh-pages`.

- **Not reproducible:** the Quarto version, which the environment's lock
  pins and CI ignores. Each tag's `_freeze/` keeps its outputs, but every
  version is re-rendered with today's theme and `_quarto.yml`.
- **Fragile as a stage:** checking out tags under DVC swaps `calkit.yaml`
  and `dvc.lock` mid-run, DVC can't depend on tags, it edits a source
  in place, and it takes every tag, sorted as strings, so `v10` < `v2`.

## Where we want to end up

### Phase 1: a stage builds a site, and Actions deploys it

No new `calkit.yaml` field: a site is an app the pipeline builds,
which `apps` already says, i.e.,
`site: {kind: static-html, path: _site/index.html, stage: site}`.
`calkit new pages-workflow site` writes `pages.yml`, e.g.:

```yaml
on: { push: { tags: [v*] }, workflow_dispatch: {} } # Or branches: [main]
permissions: { contents: read, pages: write, id-token: write }
concurrency: { group: pages, cancel-in-progress: false }
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 } # Only if the site reads tags
      - { id: pages, uses: actions/configure-pages@v6 }
      - uses: calkit/calkit/actions/run@v0.54.0
        env: { BASE_URL: "${{ steps.pages.outputs.base_path }}" }
        # pull_dvc only with a DVC remote, since it needs the Calkit token
        with: { save: "false", pull_dvc: "false", run_args: site }
      - uses: actions/upload-pages-artifact@v5
        with: { path: _site }
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - { id: deployment, uses: actions/deploy-pages@v5 }
```

The site builds in the locked environments from what's committed.
The command also enables Pages, once: if `GET /repos/{owner}/{repo}/pages`
is a 404, it `POST`s `build_type: workflow`. `GITHUB_TOKEN` can't, nor can
the hub's GitHub App, which has Administration write but not Pages write,
so this takes a personal token with `repo` scope or Pages write,
read from somewhere new, e.g., `gh`, or else prints the settings link.
For tag triggers it adds a `v*` tag policy to `github-pages`, whose default
rule rejects tags in practice, and it switches a branch-built site only
after asking.

**Two existing problems must be fixed first:**

- **Missing unstored outputs read as stale.** A pull restores DVC outputs,
  but nothing restores `storage: null` ones, so in a fresh checkout their
  stage is `is_stale`, even when `always_run`. `calkit status` exits 0, but
  a CI check reading `is_stale`, like the template's, fails. Such a stage
  should be "not built here" if it's `always_run` or its command and inputs
  match `dvc.lock`, and so should stages whose only missing inputs are such
  outputs, transitively. Not for `storage: git`, which also compiles to
  `cache: false`, so the check reads `calkit.yaml`, not `dvc.yaml`.
- **Workflow discovery takes the first match.** `find_run_workflows` lists
  workflows using the action by name, `calkit update github-actions` updates
  only the first, and the hub dispatches the first startable one, so with
  `pages.yml` before `run-calkit.yml`, the hub's run button would deploy.
  Discovery should prefer `run-calkit.yml`, or a marker, and the update
  should re-pin every workflow. Projects with two already hit this.

**Size:** 500 to 800 lines with tests, counting enablement, the tag policy,
detecting a branch-built site, both fixes, and a docs page.

**The template** drops `build.yml`, `publish.yml`, and its `publish` and
`gh-pages` branches, and adds a stage:

```yaml
site:
  kind: python-script
  script_path: _build.py
  environment: main
  always_run: true # It reads tags, which DVC can't depend on
  inputs: [index.ipynb, _quarto.yml, _variables.yml, _extensions, pages]
  outputs: [{ path: _site, storage: null }]
```

`_build.py` reads tags itself, with `--sort=-v:refname`, copies the Quarto
project to a build directory under `.calkit/local`, so nothing is written
in the tree, extracts each tag's files there with `git archive`, edits the
copy's `_quarto.yml`, and runs the environment's `quarto render`.
A tag manifest as a DVC dependency can't work: its hash in `dvc.lock` is
committed before the tag exists, so it never matches at a tag's commit.
The cost of `always_run` is a render per version on every local `calkit run`.
This fixes only the Quarto version: old versions are still re-rendered
with the current theme and `_quarto.yml`. Tagging stays the decision to
publish, and a required reviewer on `github-pages` can replace the PR.
This agrees with calkit/calkit#1405 on building in the pipeline,
not on pushing to a branch.

### Phase 2: a canned project site

The project's structure is the site's structure: it leads with questions,
each answer links its evidence, the evidence shows the stage, inputs, and
environment behind it, and publications cite it, with references and
datasets alongside, which calkit/calkit#855 says a starter kit leaves to its
user. A `project-site` stage kind writes it, with inputs from `calkit.yaml`:

- questions with rendered answers and their status;
- figures as a gallery (calkit/calkit#1415), with downloads named by commit
  (calkit/calkit#1445), and tables and results, each with its provenance;
- publications as PDFs, or links to their HTML apps;
- datasets, with where they're stored and how to import them,
  publishing files only when listed in `include_paths`;
- the pipeline as a DAG, environments with their locks,
  and the commit, build time, and each stage's freshness;
- `project.json`, the data it rendered, and schema.org JSON-LD,
  so Quarto or MyST sites can include it and search engines index it,
  a serverless step toward calkit/calkit#1265.

**Build it as a small Python generator,** not the hub's React app in a
static mode, calkit/calkit#855's mechanism. The hub's project pages make
about 200 `ProjectsService` calls, mix in editors, and bundle Plotly,
CodeMirror, xterm, and PDF viewers, so a static mode needs a snapshot of
those responses, a mock client, and a second build any hub change can break.
The generator shares the hub's Python data layer and duplicates only
presentation: Jinja templates, a stylesheet, and a little JavaScript in
`calkit/resources/site/`, adding Jinja2 and `markdown-it-py` as dependencies.
Users customize a stylesheet and a Markdown page first, and templates later,
since overrides make block names an API.

**Size:** 1,000 to 1,500 lines with tests, after calkit/calkit#2228.
**Risks:** drifting toward rebuilding the hub; publishing too much, since
Pages is public, so only what's declared, with a warning for private repos;
the 1 GB Pages limit; and storage, since a site in DVC costs it, while
`storage: null` leaves nothing for the hub to serve.

**Starter projects** get either phase from day one: a template for
`calkit new project --template` ships the stage, app, and workflow, and one
on `project-site` shows the structure above, empty, filling in as it grows.

### Phase 3: interactivity, honestly

A static site can't run anything, only link into compute. The links, the
copyable commands, and an optional giscus block are about 100 template lines.

- **Feedback:** a "Discuss" link per artifact opens a prefilled issue
  (`/issues/new?title=...&body=...`), which the hub shows as a discussion.
  giscus is optional, needing a public repo, its app, and Discussions;
  Quarto sites already have it.
- **Codespaces:** `https://codespaces.new/OWNER/REPO/tree/BRANCH` creates
  one, `?quickstart=1` resumes one, and the deep-link dialog adds
  `devcontainer_path=`. No parameter runs a command: `postAttachCommand` and
  the like are fixed in `devcontainer.json`, and `${localEnv:...}` reads the
  user's machine. It's billed to its creator unless an org pays: the
  zero-infrastructure version of calkit/calkit#1394.
- **"Rerun this stage"** means that link plus a copyable `calkit run <stage>`,
  or the owner running it on their own linked machines
  (calkit/calkit#1144, calkit/calkit#1702, calkit/calkit#1749).
- **In-browser compute** is the project's `marimo-html-wasm` apps, embedded.
  Binder isn't worth it: it reads neither `devcontainer.json` nor Calkit
  environments, so it needs a second spec.

## What not to build

- **`storage: {kind: git, branch: ...}`.** Storage is where a tracked output
  lives so others can get it, and publishing is GitHub's job. An Actions
  artifact needs no branch, and a branch of builds grows with every deploy.
- **A reusable workflow here.** The starter kit, and the template for its
  theme, call reusable workflows at `@main`, unseen and unpinned;
  a generated workflow on pinned actions matches `actions/run`.
- **Custom domains** are one setting; `configure-pages` gives the base path.
- **Versioned sites as a feature,** until another project needs one.

## Alternatives considered

- **Generating Quarto or MyST pages** for the canned site needs Quarto or
  Node in every project; `project.json` lets those sites include the data.
- **The thesis starter kit** in calkit/calkit#855 lacks the structure Calkit
  adds, i.e., questions, datasets, the pipeline, and provenance.
- **MySTRA** (calkit/calkit#478) is "a publication adapter, not a project
  viewer", the same split as between calkit/calkit#2201 and Phase 2.
- **showyourwork, Quarto Manuscripts, Curvenote, Jupyter Book 2, eLife's
  Executable Research Articles, Stencila, and Code Ocean** either link
  figures to code, which a provenance chain extends, render documents,
  which Phase 1 deploys as they are, or run code on hosted compute,
  which is the hub's job, not a static site's.

## Open questions for Pete

1. Is `apps` the right place to declare a site, or should it get a field?
2. Should a missing `storage: null` output stop counting as stale?
3. Should workflow discovery be fixed now, regardless of this design?
   Two workflows using the action already make the hub dispatch the first.
4. `calkit new pages-workflow`, or a flag on `calkit update github-actions`?
5. Should the hub's App request Pages write, which every install must approve?
6. Should a site default to `storage: null`, or DVC, so the hub serves it?
7. Should versioned sites from tags or releases become a Calkit feature?
8. Should `calkit new project` offer the canned site once it exists?
9. For feedback, prefilled issues by default, or giscus?
