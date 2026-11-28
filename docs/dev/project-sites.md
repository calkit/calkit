# Project websites

<!-- prettier-ignore -->
!!! note
    This document was written by Anthropic's Claude Code.

<!-- TODO: needs human review -->

How a Calkit project could get a public website on GitHub Pages,
in three phases, and what not to build. Nothing here is implemented.

- Issues: calkit/calkit#1405, calkit/calkit#855, calkit/calkit#1746
  (websites), calkit/calkit#478 (MyST), calkit/calkit#1415 and
  calkit/calkit#1445 (figures), calkit/calkit#1394, calkit/calkit#1144,
  calkit/calkit#1702, calkit/calkit#1749 (compute), calkit/calkit#1265
- Drafts: calkit/calkit#2228 (`calkit show provenance`),
  calkit/calkit#2201 and calkit/calkit#2203 (provenance in Quarto and MyST)

## Why

A project's public face is its README and its hub page.
Many want the publication of the future to be a website, not a PDF,
and a Calkit project holds everything a publication is made of, and more,
so a facade on it should be quick to build.
GitHub Pages is the natural host, but its setup is confusing:

- There are two sources, a branch or GitHub Actions,
  and most tools' docs, e.g., Quarto's, still describe the branch.
- Pages is enabled in settings, which a workflow's `GITHUB_TOKEN` can't
  change; `actions/configure-pages` can only enable it with another token.
- Deploying needs `pages: write` and `id-token: write`,
  and the `github-pages` environment only allows the default branch,
  so a deploy on a tag fails with "Tag ... is not allowed to deploy".
- A project site is under `/<repo>/`, or `/` with a custom domain, which
  breaks generators that need a base path, e.g., MyST's `BASE_URL`.
- The site is public even for a private repo, which needs a paid plan.

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
  hub serves it at `/projects/{owner}/{project}/apps/{name}` at any commit:
  calkit/calkit#1405's "Website tab", for a site stored in Git or DVC.
  `marimo-html-wasm` builds browser-only apps, i.e., its WASM.
- The hub's project page has grown toward calkit/calkit#1746:
  anonymous views (calkit/calkit#1764), questions (calkit/calkit#1845),
  and results with provenance lookup (calkit/calkit#1861).
- Data for a site: `ProjectInfo`, `calkit show question`'s rendered answers,
  and `get_provenance_chain` (calkit/calkit#2228), which walks a path's
  stages upstream with environments, locks, last runs, and freshness.
  calkit/calkit#2201 and calkit/calkit#2203 show it under `ckfigure`,
  `cktable`, and `ckinclude` in documents.
- `actions/run` sets up environments, gets a Calkit token over OIDC,
  and runs; `calkit update github-actions` writes and re-pins its workflow.
  Nothing handles Pages.
- `calkit update devcontainer` writes a spec that runs in Codespaces,
  Operators (calkit/calkit#1738) run `calkit run` on linked machines,
  and `calkit new project --template` starts from a template.

**The motivating case** is a Quarto notebook publication template.
On a `v*` tag, `build.yml` resets a `publish` branch to `main`
and runs `_build.py`, which `git checkout`s each tag to copy its
`index.ipynb` and `_freeze/index` in as `index_v*` copies,
edits `_quarto.yml` to list them, and opens a PR into `publish`.
On merge, `publish.yml` installs the latest Quarto, renders,
and pushes to `gh-pages`.

- **Not reproducible:** the Quarto version, since `env.yml` locks one CI
  ignores. Each tag's `_freeze/` keeps its outputs, but every version is
  re-rendered with today's Quarto, theme, and `_quarto.yml`.
- **Fragile as a stage:** checking out tags under DVC swaps `calkit.yaml`
  and `dvc.lock` mid-run, DVC can't depend on tags, it edits a source
  in place, and it takes every tag, sorted as strings, so `v10` < `v2`.

## Where we want to end up

### Phase 1: a stage builds a site, and Actions deploys it

No new `calkit.yaml` field.
A site is an app the pipeline builds, which `apps` already says:
`site: {kind: static-html, path: _site/index.html, stage: site}`.
`calkit new pages-workflow site` writes `.github/workflows/pages.yml`,
pinned like `run-calkit.yml` and re-pinned by `calkit update github-actions`:

```yaml
on:
  push:
    tags: [v*] # Or branches: [main]
  workflow_dispatch:
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
        with: { save: "false", run_args: site }
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

The site builds in the locked environments from what's committed and pulled.
The command also enables Pages, once: if `GET /repos/{owner}/{repo}/pages`
is a 404, it `POST`s `build_type: workflow`, which needs `repo` scope or
Pages write, e.g., `gh`'s token. The hub's GitHub App has no Pages
permission, so with its token Calkit prints the settings link instead.
For tag triggers it adds a `v*` tag policy to `github-pages`,
and it switches a branch-built site only after asking.

It needs one fix: a missing `storage: null` output makes its stage stale
(checked with Calkit 0.53), so a fresh checkout's `calkit status` fails.
If the stage's inputs match `dvc.lock`, it should say "not built here",
the way `always_run` stages are listed without making the pipeline stale.
That also helps HPC outputs kept out of storage.

**Size:** 300 to 450 lines with tests, a workflow, and a docs page.

**The template** drops `build.yml`, `publish.yml`, and its `publish` and
`gh-pages` branches, and adds two stages:

```yaml
tags:
  kind: shell-command
  environment: _system
  always_run: true
  command: git for-each-ref 'refs/tags/v*' > .calkit/local/tags.txt
  outputs: [{ path: .calkit/local/tags.txt, storage: null }]
site:
  kind: python-script
  script_path: _build.py
  environment: main
  inputs: [.calkit/local/tags.txt, _quarto.yml, from_stage_outputs: pub]
  outputs: [{ path: _site, storage: null }]
```

`_build.py` copies the Quarto project to a build directory under
`.calkit/local`, as `marimo-html-wasm` does, so nothing is written in the
tree and no outputs need globs. There it writes each tag's files with
`git show <tag>:<path>`, sorts tags with `--sort=-v:refname`, edits the
copy's `_quarto.yml`, and runs the environment's `quarto render` into `_site`.
The tag list isn't in Git, where it would make each tag's commit stale.
Tagging stays the decision to publish, and a required reviewer on
`github-pages` can replace the PR into `publish`.
This agrees with calkit/calkit#1405 on building in the pipeline,
not on pushing to a branch.

### Phase 2: a canned project site

The project's structure is the site's structure.
A project is made by defining questions, adding references and datasets,
making figures and results with stages in environments,
and writing publications.
So the site leads with questions, each answer links its evidence,
the evidence shows the stage, inputs, and environment behind it,
and publications cite it, with references and datasets alongside:
what calkit/calkit#855 says a starter kit leaves to its user.
A `project-site` stage kind writes it, deriving its inputs from
`calkit.yaml` as `marimo-html-wasm` does:

- questions with rendered answers and their status;
- figures as a gallery (calkit/calkit#1415), with downloads named by commit
  (calkit/calkit#1445), and tables and results, each with its provenance;
- publications as PDFs, or links to their HTML apps;
- datasets, with where they're stored and how to import them,
  publishing files only when listed in `include_paths`, as marimo does;
- the pipeline as a DAG, environments with their locks,
  and the commit, build time, and each stage's freshness;
- `project.json`, the data it rendered, and schema.org JSON-LD,
  so Quarto or MyST sites can include it and search engines index it,
  a serverless step toward calkit/calkit#1265.

**Build it as a small Python generator,** not the hub's React app in a
static mode, calkit/calkit#855's mechanism. The hub's pages make about 200
`ProjectsService` calls, mix in editors, and bundle Plotly, CodeMirror,
xterm, PDF viewers, and Stripe, so a static mode needs a snapshot of those
responses, a mock client, and a second build any hub change can break.
The generator shares the hub's Python data layer and duplicates only
presentation: Jinja templates, a stylesheet, and a little JavaScript in
`calkit/resources/site/`, with `markdown-it-py`, which `rich` installs.
Users customize a stylesheet and a Markdown page first, and templates
later, since overrides make block names an API.

**Size:** 1,000 to 1,500 lines with tests, after calkit/calkit#2228.
**Risks:** drifting toward rebuilding the hub; publishing too much, since
Pages is public, so only what's declared, with a warning for private repos;
the 1 GB Pages limit; and storage, since a site in DVC costs it, while
`storage: null` leaves nothing for the hub to serve.

**Starter projects** get either phase from day one with
`calkit new project --template`, which can also enable Pages: the template
ships the stage, the app, and the workflow. A generic starter on
`project-site` shows the structure above, empty, filling in as it grows.

### Phase 3: interactivity, honestly

A static site can't run anything. It can only link into compute.

- **Feedback:** a "Discuss" link per artifact opens a prefilled issue
  (`/issues/new?title=...&body=...`), which the hub shows as a discussion.
  giscus is optional, needing a public repo, its app, and Discussions;
  Quarto sites already have it.
- **Codespaces:** `https://codespaces.new/OWNER/REPO/tree/BRANCH` creates
  one, `?quickstart=1` resumes one, and `devcontainer_path=` picks a spec.
  No parameter runs a command: `postAttachCommand` and the like are fixed in
  `devcontainer.json`, and `${localEnv:...}` reads the user's machine,
  which a link can't set. It's billed to its creator unless an org pays.
  This is the zero-infrastructure version of calkit/calkit#1394.
- **"Rerun this stage"** means that link plus a copyable `calkit run <stage>`,
  and for collaborators, the hub's pipeline page, where Operators run it
  (calkit/calkit#1144, calkit/calkit#1702, calkit/calkit#1749).
- **In-browser compute** is the project's `marimo-html-wasm` apps, embedded.
  Binder isn't worth it: it reads neither `devcontainer.json` nor Calkit
  environments, so it needs a second spec. **Size:** 100 lines of templates.

## What not to build

- **`storage: {kind: git, branch: ...}`.** Storage is where a tracked output
  lives so others can get it, and publishing is GitHub's job.
  An Actions artifact needs no branch, and a branch of builds grows with
  every deploy.
- **A static mode of the hub's frontend,** as above.
- **A reusable workflow here.** The starter kit's runs at `@main`, unseen and
  unpinned; a generated workflow on pinned actions matches `actions/run`.
- **Custom domains** are one setting; `configure-pages` gives the base path.
- **Versioned sites as a feature,** until another project needs one.

## Alternatives considered

- **Generating Quarto or MyST pages** for the canned site needs Quarto or
  Node in every project. `project.json` lets those sites include the data.
- **showyourwork** links each figure in a paper to its script and data;
  a provenance chain adds environments and freshness.
- **Quarto websites and Manuscripts, MyST, Curvenote, and Jupyter Book 2**
  render documents well, so Phase 1 deploys them as they are.
- **The thesis starter kit** in calkit/calkit#855 deploys a MyST book
  through Actions, with `BASE_URL=/<repo>` and a Typst PDF, but installs
  MyST with npm beside its Pixi pin, and points Binder at a generic repo.
  Calkit adds the structure, i.e., questions, references, datasets,
  environments, the pipeline, and publications, and provenance.
- **MySTRA,** from calkit/calkit#478, pulls outputs into MyST by reference,
  as "a publication adapter, not a project viewer", the same split as
  between calkit/calkit#2201 and Phase 2.
- **eLife's Executable Research Articles, Stencila, and Code Ocean**
  run code for readers on hosted compute someone pays for:
  the hub's and Operators' job, not a static site's.

## Open questions for Pete

1. Is `apps` the right place to declare a site, or should it get a field?
2. Should a missing `storage: null` output stop counting as stale?
3. `calkit new pages-workflow`, or a flag on `calkit update github-actions`?
4. Should the hub's GitHub App request Pages write, to enable Pages itself?
   Every installation would have to approve it.
5. Should a site default to `storage: null`, or DVC, so the hub serves it?
6. Should versioned sites from tags or releases become a Calkit feature?
7. Should `calkit new project` offer the canned site once it exists?
8. For feedback, prefilled issues by default, or giscus?
