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

- **Decided:** tag prefixes reuse the existing scheme: `hub/v0.1.5` alongside
  `v0.42.0` for the package and `vscode-ext/v0.1.5`.
- **Decided:** directory name is `hub/`. The earlier worry about the directory
  name matching the tag prefix turned out to be theoretical: calkit-python
  already has both a `vscode-ext/` directory and `vscode-ext/v*` tags, and
  `git log`/`git checkout` on those tags resolve fine without `--`. Git only
  raises the ambiguity error when an argument matches both a ref and an
  existing path, and a tag name always ends in `/vX.Y.Z`, which never exists
  as a path.

Use `git subtree add --prefix=<dir>` to preserve history and blame. Open PRs
will not survive the move and need re-creating; issues transfer individually.

## Release workflows

The existing prefix scheme is deny-by-default, which is the right property.
`publish.yml` guards with `!contains(github.event.release.tag_name, '/')`, so
any new prefix is automatically excluded from PyPI without touching that
workflow. `publish-vscode-ext.yml` opts in with
`startsWith(..., 'vscode-ext/v')`.

**Done:** `deploy-production.yml` now guards with
`startsWith(github.event.release.tag_name, 'hub/v')` (workflow_dispatch is
still allowed through for rollbacks). `deploy-staging.yml` needs no guard: it
fires on push to main, not on releases, and in the workspace monorepo a
CLI-only push genuinely changes the backend, so redeploying staging on every
main push is correct rather than wasteful.

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
- **Done:** `docs.yml` now has `paths: [docs/**, mkdocs.yml]` (on the
  `merge-hub` branch in calkit-python). Safe to filter since it is a
  push-triggered deploy, not a required PR check.
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
- **Done:** the CLI group is `calkit hub` with `cloud` kept as an alias via
  the existing `name="hub|cloud"` convention, and the ~30 "Calkit Cloud"
  strings in the package now say "Calkit" or "the hub". The docs pages still
  need their pass.
- **Done:** `calkit/cloud.py` moved to `calkit/hub.py`, with a module alias
  left at the old path (it assigns ``sys.modules`` so both names are the
  same module object).

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

**Sequencing constraint (softer than earlier versions of this doc
claimed):** `ProjectInfo` does not set `extra="forbid"` — verified
empirically, unknown keys validate fine — so old CLIs silently ignore a
`hub:` key rather than failing `calkit check`. The field should still land
and release in calkit-python before the backend writes it, so that up-to-date
CLIs can actually use it, but nothing breaks in the interim. The field now
exists on the `merge-hub` branch.

### How the CLI should use it

- **Done:** provenance plus a mismatch warning. `calkit push` and `calkit
  pull` warn when the project declares a hub other than the one env-based
  resolution is targeting; the env stays the source of truth, so nothing
  breaks. `calkit hub` subcommands additionally default to the wdir
  project's declared hub when `CALKIT_ENV` is unset, and accept `--hub`
  for the built-in instances.
- **Later:** discovery, so `hub` is actionable for arbitrary instances. Note
  the web and API URLs are not related by a derivable convention: production is
  calkit.io and api.calkit.io (a prefix), but dev is localhost:5173 and
  api.localhost (not a prefix). String manipulation breaks precisely in dev. A
  well-known document served by the hub (e.g., `/.well-known/calkit` returning
  its API URL) solves it once for any topology, including serving API and web
  on one origin.

## Per-hub CLI config

**Done.** The env key generalized to a hub key exactly as planned:
`get_hub()` resolves `CALKIT_HUB` (a hub URL; environment names are
deployment-internal vocabulary the CLI's hub surfaces don't accept) falling
back to `CALKIT_ENV`, then the `default_hub` config value, and
`get_env_suffix()` keys off it, so `CALKIT_ENV=staging` and existing config
files keep working while `calkit config --hub other-calkit.io set token` is
the general form. Hub
keys are slugified before becoming filenames, keyring service names, or env
var prefixes (`localhost:5173` cannot appear in a Windows filename, and CI
runs windows-latest). DVC remote naming was left alone per the original
reasoning: the remote stays `calkit` and the project's declared `hub` will
supply the endpoint. `get_base_url()` now raises for a hub whose API URL it
doesn't know (rather than silently sending its credentials to production),
with `CALKIT_CLOUD_BASE_URL` as the manual override until well-known-URL
discovery exists.

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

1. ~~Add the cross-version CI job (calkit from git main, cloud backend
   tests).~~ Skipped as a standalone step: it only paid off in the
   window before the merge, and the merge is happening now. Its purpose is
   served by the post-merge CI running backend tests against the workspace.
2. ~~Settle the directory name and add the release tag guards.~~ Done:
   directory `hub/`, tags `hub/v*`, production deploy guarded, staging needs
   no guard.
3. ~~Subtree merge (`git subtree add --prefix=hub`), move workflows with a
   `changes` gating job~~, move GitHub environments, secrets, and self-hosted
   runner registration. The merge and the code side landed on the
   `merge-hub` branch: the backend is a uv workspace member building calkit
   from the working tree (the backend image builds with the repo root as
   context, pretending a version for hatch-vcs and disabling the JupyterLab
   extension build hooks), hub workflows moved to the root gated by a
   `changes` job, and the two pre-commit configs merged into one at the root
   with hub code still formatted by hub's own tools. What remains of this
   step is the GitHub settings half: move environments, secrets, and
   variables, register the self-hosted runners against calkit/calkit,
   transfer issues, and archive calkit-cloud.
4. ~~Add `hub` to `ProjectInfo`, release calkit-python, then write the key
   from the backend on project creation.~~ Done: the backend writes
   `hub: settings.frontend_host` into calkit.yaml on creation. The
   release-first ordering turned out not to be blocking (released CLIs back
   through at least 0.39.0 validate unknown ProjectInfo keys fine,
   verified empirically), though a release before the production deploy is
   still wanted so up-to-date CLIs can make use of the field.
5. ~~Generalize the CLI config key from env to hub.~~ Done.

The workspace question is not a step of its own. It has to be settled as part
of step 3, since the Docker build context and the dev compose mounts depend on
the answer.

## Manual changeover checklist

Everything the code can't do: the GitHub settings and runner moves that
remain before (and right after) merging the `merge-hub` PR. Work top to
bottom; the order matters so the first push to main has somewhere to
deploy. Delete this doc when the list is done.

### calkit/calkit repo settings

- [ ] Actions → General: set fork PR workflow approval to "Require
      approval for all outside collaborators".
- [ ] Actions → General: set default workflow permissions to read-only
      and uncheck "Allow GitHub Actions to create and approve pull
      requests". (Workflows also declare `permissions: contents: read`
      themselves, but set the default anyway.)
- [ ] Code security: enable secret scanning push protection.
- [ ] Branch protection/ruleset on `main`: require PRs, require the
      changes-gated status checks, block force pushes. This also guards
      the invariant that no self-hosted-runner workflow ever gets a
      `pull_request` trigger.

### Environments and secrets

- [ ] Create environments named `calkit.io` and `staging.calkit.io`
      (matching `environment.name` in the deploy workflows) and copy the
      secrets and variables from calkit-cloud's `production` and
      `staging` environments. Keep all deploy secrets
      environment-scoped; none belong at repo level.
- [ ] Deployment branch/tag rules: `calkit.io` allows only tags matching
      `hub/v*`; `staging.calkit.io` allows `main` plus any branches you
      actually staging-deploy.
- [ ] The one repo-level secret, `CALKIT_ZENODO_TOKEN` (used by
      `test.yml`), moves over as-is; keep it a low-privilege sandbox
      token since collaborator branches can read it.

### Self-hosted runners

On each runner machine (production, staging), from the runner directory:

```sh
./svc.sh stop && ./svc.sh uninstall
./config.sh remove --token <removal-token-from-calkit-cloud-settings>
./config.sh --url https://github.com/calkit/calkit \
  --token <registration-token-from-calkit-calkit-settings> \
  --labels production   # or: staging
./svc.sh install && ./svc.sh start
```

Tokens come from each repo's Settings → Actions → Runners, or
`gh api -X POST repos/calkit/calkit/actions/runners/registration-token`.
Keep the labels `production`/`staging`; the workflows select on those.

- [ ] Re-register the staging runner against calkit/calkit.
- [ ] Re-register the production runner against calkit/calkit.

### Merge and first deploys

- [ ] Merge the PR with a merge commit (not squash, and never "Rebase and
      merge", which would replay the ~2,200 imported commits onto main).
      The push to main should trigger a staging deploy on the newly
      registered runner.
- [ ] Tag and publish a calkit-python release (`vX.Y.Z`) so up-to-date
      CLIs know the `hub` field before hubs start writing it.
- [ ] Tag and publish the first hub release (`hub/vX.Y.Z`), unchecking
      "Set as the latest release", and confirm the production deploy runs
      and the deployments list shows `calkit.io`.

### Old repo wind-down

- [ ] Transfer open calkit-cloud issues individually; re-create any open
      PRs against calkit/calkit.
- [ ] Archive calkit-cloud. Do NOT delete or rename it: old issue links
      and the pre-monorepo history references point there.
- [ ] Remove the old local dev checkout from regular use; run the stack
      from `hub/` (or root `make dev`) only, since both resolve to the
      same Compose project name.
