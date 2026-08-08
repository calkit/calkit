# Calkit browser extension

A Chrome extension (Manifest V3) for working with Calkit projects from the
sites where the work actually happens: GitHub, Overleaf, and journal and
preprint pages.

## What it does

### Overleaf

On an Overleaf project page, a panel shows the Calkit project that syncs with
it and, most importantly, **which figures are out of date on Overleaf**:

- Figures whose content differs from the copy in the Calkit project are
  listed first, so it's obvious when the paper is showing an old plot.
- A figure produced by a pipeline stage that is itself stale is flagged, so
  you know to run the pipeline before syncing rather than syncing a stale
  figure into the paper.
- Overleaf edits that haven't come back into the project yet are counted.
- **Sync now** runs the same bidirectional sync as `calkit overleaf sync`.

If the Overleaf project isn't linked yet, the panel can search your projects
and either check an existing link or import the Overleaf project into one as a
new publication.

**Attach to new project** covers the case where the code, data, and figures
already live in a GitHub repo. Turn on "Exists on GitHub", type the repo name,
and pick the folder the document should occupy inside the project. That
creates the Calkit project around the existing repo and imports the Overleaf
document into it in one go, after which the document is a pipeline stage whose
figures can be checked for staleness and synced. The Calkit GitHub app has to
be installed for the repo.

Finding the linked project doesn't require having synced before: the hub reads
each project's `calkit.yaml` through the GitHub API, active project first,
indexing what it finds so later lookups are a single query.

### GitHub

A **Calkit** button in the corner of a repository page says whether the repo is
a Calkit project before you click it. It reads the repo's `calkit.yaml` first,
since that file names the hub the project belongs to, so a project on another
instance is recognised rather than looking like it isn't one; a private repo,
which won't serve that file anonymously, falls back to asking your hub.

From there you can open the project on its hub, or connect a repo that isn't a
project yet. For a connected project the extension **adds its DVC-tracked
files to GitHub's own file listing**, badged as DVC, since GitHub can only show
the `.dvc` pointer files. Clicking one opens it: image preview or download,
straight from the project's DVC storage.

### References

On a journal, publisher, or preprint page, the extension reads the page's
citation metadata (Highwire Press and Dublin Core tags, the same ones Zotero
relies on) and tells you whether that reference is already in a collection in
one of your projects. From there you can:

- Import it into any `.bib` collection in a project.
- Read and edit the notes attached to it, which are stored in the BibTeX
  `comment` field, and pushed to Zotero for collections linked to it.

The project checked is the **active project**, which the panel names in a
dropdown at the top: changing it there switches the active project outright,
so what was checked and what an import lands in can't drift apart, and the
next paper starts where this one left off.

One project rather than a list is deliberate: it suits a thesis-scale
monorepo, and it's also what keeps the lookup fast, since each project has to
be read on the server to search its collections.

The content script runs on the major preprint servers and publishers (arXiv,
bioRxiv, PLOS, Springer, Wiley, Elsevier, Nature, Science, MDPI, Cambridge
Core, AIP, ACS, RSC, IOP, ASME, AIAA, Oxford, and others). Publishers that
spread journals across subdomains are matched with a wildcard host, so
`agupubs.onlinelibrary.wiley.com` and `collections.plos.org` are covered by
the same entry as their parents.

That list can't ever be complete, and every host on it is a permission the
user has to grant, so it stays limited to sites worth injecting into. The
popup does the same detection on **any** page through `activeTab`, which is
the general answer for everything else.

## Installing during development

```sh
npm install
npm run build
```

Then, in Chrome, open `chrome://extensions`, turn on **Developer mode**, click
**Load unpacked**, and select the `dist` directory.

## Signing in

The extension uses the hub's device authorization flow, the same one
`calkit hub login` uses. Click **Sign in** in the popup, approve the request in
the tab that opens, and the extension stores a short-lived access token plus a
refresh token in `chrome.storage.local`, scoped to the hub it came from.

Nothing else ever sees the token: every API call runs in the service worker,
which the content scripts drive through a fixed set of named operations rather
than a general "fetch this URL" proxy.

## Image previews and object storage

Panels live in the host page's DOM, so the page's content security policy
decides what they can load, and sites like GitHub don't allow images from
object storage. Previews are therefore fetched in the service worker and
handed to the panel as data URLs, which every page allows.

That fetch needs the storage host in `host_permissions`. The manifest lists
Google Cloud Storage and S3, which covers the hosted instances. A hub using
some other storage, e.g. MinIO, needs its host added; without it the preview
is dropped and the download link still works.

## Settings

The options page holds two settings.

**Hub** selects between calkit.io, the staging instance, a local development
instance, and a self-hosted one. Changing it applies immediately, and the
page then shows whether you're signed in to the newly selected hub, since
credentials are stored per hub and switching generally means signing in
again.

A hub serves its API from the `api` subdomain of the host serving its web
app, so a self-hosted hub is configured with its URL alone:
`https://calkit.example.edu` implies `https://api.calkit.example.edu`. Chrome
prompts for access to that host when the hub is applied. This matches
`calkit.hub.api_url_from_hub_url` in the Python package; see the
[self-hosting docs](../docs/hub/self-hosting.md).

**Active project** is the project being worked on, remembered per hub.
Reference lookups check its collections, and importing a reference defaults to
it. It can also be switched from the popup.

Project pickers list only projects you can **write** to
(`GET /projects?min_access_level=write`), since every action they offer
writes. The GitHub panel is the exception: it resolves a repo at read
access, because browsing the DVC artifacts behind a public project you
don't own is the point of it.

## Layout

```
public/manifest.json   Extension manifest
popup.html             Toolbar popup page, built to dist/popup.html
options.html           Options page, built to dist/options.html
src/background/        Service worker: auth, API calls, message routing
src/content/           One content script per site (github, overleaf,
                       references)
src/core/              Hub config, storage, API client, page detection, UI
src/popup/             Popup script and shared page styles
src/options/           Options script
```

Both pages are built to the root of `dist` rather than to a path under
`src/`, so they load from `chrome-extension://<id>/options.html`. Content
blockers match on request paths and some of their filter lists catch generic
source-tree paths, which is enough to break an extension page with
`ERR_BLOCKED_BY_CLIENT`.

## Development

```sh
npm run check    # Type-check
npm test         # Unit tests for URL and citation-metadata parsing
npm run format   # Prettier
npm run build    # Type-check, then build into dist/
```

Content scripts are bundled one at a time as IIFEs (see
`scripts/build-content.mjs`), because Chrome runs them as classic scripts,
which can't be ES modules or be code-split.

## Backend requirements

The Overleaf and reference features need hub API endpoints added alongside
this extension:

- `GET /overleaf-links` resolves an Overleaf project ID to the Calkit projects
  that sync with it.
- `GET /projects/{owner}/{project}/overleaf-syncs/status` reports what a sync
  would do without doing it.
- `GET /projects?github_repo=owner/repo` looks a project up by its GitHub repo.
- `GET /user/references/search` finds a reference across named projects.
