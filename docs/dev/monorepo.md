# Monorepo, naming, and hub configuration

Working notes from the discussion about merging this repo into
[calkit/calkit](https://github.com/calkit/calkit), renaming the web app, and
teaching projects which instance they belong to.

Status labels: **Decided** means we agreed and it only needs doing.
**Leaning** means there is a recommendation but no commitment.
**Open** means it still needs a call.

## Why merge at all

**Leaning: yes, merge.**

The `ck://` incident is the motivating case. `register_ck_scheme` lives in
calkit-python, the cloud pinned `calkit-python==0.41.19`, and the failure came
from DVC memoizing its compiled config schema before registration ran. Neither
test suite could see it: calkit's tests never import `app.dvc`, and the cloud's
tests never varied the calkit version.

The layout change alone does not fix that. What fixes it is a CI job that runs
the cloud backend tests against calkit's working tree. That job could be added
today as a cron workflow installing calkit from git main, without merging
anything. The monorepo's contribution is making that job cheap and letting a
shared-code fix land in one PR instead of three (calkit fix, release, cloud
version bump).

Other benefits: shared procedures (Overleaf sync, Zotero, DVC remote config)
get tested together, and client/server contract changes become atomic.

## Layout and tags

- **Decided:** tag prefixes reuse the existing scheme, e.g., `cloud/v0.1.5` or
  `hub/v0.1.5` alongside `v0.42.0` for the package and `vscode-ext/v0.1.5`.
- **Open:** directory name. `web/` and `hub/` are both reasonable. Avoid
  making the directory name and the tag prefix identical, since git needs `--`
  to disambiguate a ref from a path in some commands. Do not name it `cloud/`
  if "cloud" is being retired as vocabulary.

Pick the directory name before the subtree merge. Renaming it afterward muddies
history for every file underneath.

Use `git subtree add --prefix=<dir>` to preserve history and blame. Open PRs
will not survive the move and need re-creating; issues transfer individually.

## Release workflows

The existing prefix scheme is deny-by-default, which is the right property.
`publish.yml` guards with `!contains(github.event.release.tag_name, '/')`, so
any new prefix is automatically excluded from PyPI without touching that
workflow. `publish-vscode-ext.yml` opts in with
`startsWith(..., 'vscode-ext/v')`.

**Must land at merge time:** both deploy workflows in this repo currently fire
on any published release. They need
`if: startsWith(github.event.release.tag_name, 'cloud/v')`, or a plain
`v0.42.0` CLI release deploys production.

Slashes in tags are safe here. `deploy-production.yml` uses the tag only for
release validation and as the `actions/checkout` ref. Compose images resolve
`${TAG-latest}`, which is not wired to the release tag. If that ever changes so
rollbacks pull immutable images, the prefix has to be stripped
(`TAG=${tag#cloud/}`), since Docker tags cannot contain a slash.

Minor annoyance already familiar from vscode-ext: a prefixed release claims the
repo's "Latest release" badge unless "Set as the latest release" is unchecked.

## CI

- Use a `changes` job that always runs and gates the real jobs, rather than
  `paths:` filters on workflows that are required checks. A required check that
  never runs sits pending forever and blocks merges.
- `docs.yml` runs `mkdocs gh-deploy` on every push to main with no path filter.
  Post-merge it needs `paths: [docs/**, mkdocs.yml]`. This one is safe to
  filter since it is a push-triggered deploy, not a required PR check.
- Both repos are public. Deploys currently only run on `release`, so fork PRs
  cannot reach the self-hosted production runner. That invariant gets easier to
  break once the package's contributor traffic lands in the same repo. Never
  add a `pull_request` trigger to anything using the production runner.

## The calkit-python dependency

**Leaning: uv workspace, with the deploy building calkit from the release tag.**

An earlier version of this document recommended keeping the backend pinned to a
published `calkit-python==X.Y.Z` and coupling only in CI. That does not survive
contact with atomic PRs. If CI runs the backend tests against the working tree
while the image installs a published version, CI is green for a combination
that is never deployed, and local dev cannot exercise an unreleased CLI change
at all. Pin-only and workspace-only are both coherent; the hybrid is not.

The reproducibility argument for pinning was imported from a multi-repo
mindset. In a monorepo the deploy already checks out `cloud/v0.1.5` and builds
from that commit, so building calkit from the same commit is exactly as
reproducible. The pin buys nothing the release tag does not already buy.

Layout:

```
pyproject.toml            # calkit-python, workspace root
uv.lock                   # covers both members
calkit/
web/backend/pyproject.toml
    [tool.uv.sources]
    calkit-python = { workspace = true }
```

What it costs:

- The backend image build context becomes the repo root (it needs `calkit/`,
  `web/backend/`, and the root `pyproject.toml` and `uv.lock`) rather than the
  backend directory. Wants a tight `.dockerignore`.
- A CLI-only change invalidates the backend image's dependency layer.
- Build step becomes `uv sync --package <backend> --frozen`.

The dev loop is the payoff. Mount the repo root instead of just the backend
directory; uv installs workspace members editable, so an edit to `calkit/` on
the host is live in the container and `fastapi run --reload` already restarts
on it. Today a CLI change cannot be tested against the backend at all without
publishing to PyPI first. Note that the `/app/.venv` anonymous volume masks
dependency changes, so `--renew-anon-volumes` is needed after either
`pyproject.toml` changes.

If the published-version property is still wanted, keep it as a check rather
than as the deploy path: `uv sync --no-sources` (or
`--no-sources-package calkit-python`) ignores `tool.uv.sources` and resolves
from the index, so "does the backend still work against the last released
calkit" is one extra CI matrix entry.

Remaining risk, which pinning never solved anyway: main can contain backend
code that depends on calkit behavior a user's installed CLI does not have yet.
That is hub/CLI API compatibility, and it wants version negotiation at the API
level, not dependency pinning.

## Docs

**Decided in principle: one site, no second docs system.**

calkit-python already has a 40 page mkdocs Material site at docs.calkit.org.
This repo has one doc (`docs/dev/database-migrations.md`) and no user-facing
docs. So this is not merging two sites, it is filling a hole. The boundary is
already leaking: `docs/cloud-integration.md`, `overleaf.md`, and `releases.md`
describe web app behavior from the CLI's point of view, maintained in the other
repo.

- Add web app pages to the existing nav. Do not build a docs renderer inside
  the React app: mkdocs-material already provides search, nav, and anchors, and
  docs need to be readable by people who have not signed up.
- Get "built in" docs via contextual deep links from app pages to docs anchors,
  plus a help affordance. Cheap, and most of the value.
- If in-app rendering is wanted later, keep it to a small curated subset of
  plain markdown. Two renderers drift on mkdocs-specific syntax (`!!! note`,
  snippets, the mermaid setup).
- The docs deploy target does not change. `gh-deploy` pushes to the gh-pages
  branch of the repo it runs in, and `docs/CNAME` pins docs.calkit.org.
- This repo's `docs/dev/` moves under the web directory and stays out of the
  mkdocs nav.
- Later idea: the cloud test workflow already boots the whole compose stack,
  which is most of what is needed to generate web app screenshots in CI rather
  than hand-capturing ones that go stale.

Once the brand collapses to "Calkit" (below), "Cloud integration" stops being a
section. Web app pages fold into task-based nav (projects, collaboration,
storage, releases), with a separate admin section for running your own hub.

## Naming

**Decided: the product is Calkit. The CLI and the web app are one thing.**

User-facing copy says "connect your GitHub repo to Calkit," not "to Calkit
Cloud" or "to Calkit Hub."

**Decided: "hub" is a common noun, not a brand.** A hub is a deployment you
talk to. This is the word needed once self-hosting exists, and there is no
other candidate. Mastodon has "instance," Matrix has "homeserver," and both
work because the product name is not doing that job.

"Cloud" is retired as vocabulary. It describes where something runs, which is
exactly the claim to stop making when someone runs it on a lab server. The
current CLI help string shows the strain: `Interact with a Calkit Cloud.`

Migration cost is low and mostly in calkit-python:

- This repo has one user-facing "Calkit Cloud" string
  (`frontend/src/routes/_layout/index.tsx:265`) and one in the backend.
- calkit-python has ~35 strings in the package and about ten docs pages,
  including `ProjectInfo` field descriptions that read "on Calkit Cloud."
- `calkit cloud` has exactly two commands, `get` and `login`. A top-level
  `calkit login` conflicts with nothing. Use the existing alias convention
  (`name="new|create"`, `name="list|ls"`) so `calkit cloud login` keeps working
  indefinitely.
- Leave `calkit/cloud.py` and `calkit.cloud.get_base_url()` alone at first.
  Module paths are internal and churning them conflicts every open branch.

**Open, and a product decision hiding in a naming decision:** whether a Calkit
project implies a hub. Today a project is fully functional offline (init,
pipeline, environments, DVC, no account). That local-first on-ramp is probably
a real share of how people try it. Recommendation: a hub is where a project is
*shared, backed up, and collaborated on*, not where it *lives*. The Git repo
remains the source of truth.

## The `hub` key in calkit.yaml

**Leaning: add `hub` to `ProjectInfo`, holding a full base URL.**

- Field name `hub`. Not `domain` (too generic, and wrong once there is a port
  or scheme), not `cloud` (retired).
- Value is a full URL with scheme: `https://calkit.io`,
  `http://localhost:5173`. The scheme genuinely differs between those, so a
  bare host forces the CLI to guess. It is also clickable wherever displayed.

**Decided: one hub per project.** The stronger reason than attribution is that
it makes `ck://` resolvable. `ck://owner/project/path` names no instance, and
`calkit/fs.py` papers over that with a per-URL `?endpoint_url=` escape hatch.
Declaring the hub once at the project level means every bare `ck://` resolves
against a known instance instead of whatever `CALKIT_ENV` the shell has. Two
hubs would mean two different blobs behind the same URL and two answers to who
can read it.

**Blocking constraint:** `ProjectInfo` sets `extra="forbid"` and is the source
of truth for the published JSON schema. If the backend writes `hub:` before
calkit-python declares the field, every newly created project fails
`calkit check` and gets flagged in editors. The field must land and release in
calkit-python first. This is exactly the cross-repo lockstep the monorepo
dissolves.

### How the CLI should use it

- **Now:** provenance plus a mismatch warning. If `hub` says calkit.io and the
  resolved API URL points at staging, warn. Existing env-based resolution stays
  the source of truth, so nothing breaks.
- **Later:** discovery, so `hub` is actionable for arbitrary instances. Note
  the web and API URLs are not related by a derivable convention: production is
  calkit.io and api.calkit.io (a prefix), but dev is localhost:5173 and
  api.localhost (not a prefix). String manipulation breaks precisely in dev. A
  well-known document served by the hub (e.g., `/.well-known/calkit` returning
  its API URL) solves it once for any topology, including serving API and web
  on one origin.

## Per-hub CLI config

**Leaning: generalize the existing env key to a hub key.**

The machinery already exists, keyed by the wrong thing:

- `get_env_suffix()` gives `~/.calkit/config.yaml` vs `config-staging.yaml`.
- `get_app_name()` namespaces the keyring service as `calkit` vs
  `calkit-staging`.

So config is already per-instance with a closed enum of three instances.
Swapping the key from env name to hub, with `production`, `staging`, and
`local` kept as built-in aliases, makes `CALKIT_ENV=staging` and existing
config files keep working while `calkit config --hub other-calkit.io set token`
becomes the general form.

Two things to watch:

- **Filenames.** `localhost:5173` cannot appear in a Windows filename, and
  calkit-python's CI runs windows-latest. Slugify the hub key before it becomes
  a path or keyring service name.
- **DVC remote names.** `make_remote_name` derives from the app name, so
  per-hub naming would produce `calkit-other-calkit.io` remotes. Skip that.
  Since one project belongs to one hub, the remote stays `calkit` and the
  project's declared `hub` supplies the endpoint, keeping `.dvc/config`
  identical across instances.

## Self-hosting

A future goal, and packaging is not the blocker. The stack assumes Traefik, a
GitHub App for repo access, Stripe, Mixpanel, Zenodo, Zotero, and object
storage. Project creation currently hard-requires a linked GitHub account,
which is a bigger obstacle than the absence of a Helm chart. A documented
compose spec plus a "bring your own GitHub App" guide gets further than a
chart. Hold the chart until someone asks.

## Done already

- The GitHub repo homepage set during project creation now uses
  `settings.frontend_host` instead of a hardcoded `https://calkit.io`
  (`backend/app/api/routes/projects/core.py`). The two "Please log in at
  calkit.io" strings in `login.py` are staging gates that deliberately point at
  production, so they were left alone.

## Suggested sequencing

1. Add the cross-version CI job (calkit from git main, cloud backend tests).
   Stands alone, no merge required, and catches the `ck://` class of bug
   before any of the rest of this happens.
2. Settle the directory name and add the release tag guards to both deploy
   workflows.
3. Subtree merge, move workflows with a `changes` gating job, move GitHub
   environments, secrets, and self-hosted runner registration.
4. Add `hub` to `ProjectInfo`, release calkit-python, then write the key from
   the backend on project creation.
5. Generalize the CLI config key from env to hub.

The workspace question is not a step of its own. It has to be settled as part
of step 3, since the Docker build context and the dev compose mounts depend on
the answer.
