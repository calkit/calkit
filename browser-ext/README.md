# Calkit browser extension

A Chrome extension (Manifest V3) for working with Calkit projects from the
sites where the work actually happens: GitHub, Overleaf, journal and preprint
pages, and Zotero.

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
and either check an existing link or import the Overleaf project into a
project as a new publication.

### GitHub

On a repository page, the **Calkit artifacts** button resolves the repo to a
Calkit project and lists the DVC-tracked files near the top of the tree, with
sizes, the pipeline stage that produced each one, image previews, and download
links that point at the project's DVC storage.

### References

On a journal, publisher, or preprint page, the extension reads the page's
citation metadata (Highwire Press and Dublin Core tags, the same ones Zotero
relies on) and tells you whether that reference is already in a collection in
one of your projects. From there you can:

- Import it into any `.bib` collection in a project.
- Read and edit the notes attached to it, which are stored in the BibTeX
  `comment` field and pushed to Zotero for Zotero-linked collections.

Which projects get checked is configured in the extension's options. That list
is explicit rather than "all your projects" because each project has to be
read on the server, so an unbounded search would be too slow to run on page
load.

The extension's popup does the same detection on any page through `activeTab`,
so a site that isn't in the content script's list still works, just from the
popup rather than in the page.

### Zotero

On zotero.org, the panel imports a Zotero collection into a project as a
`.bib` collection, and syncs collections that are already linked.

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

## Choosing a hub

The options page selects between calkit.io, the staging instance, a local
development instance, and a self-hosted one. A self-hosted hub needs its API
host granted to the extension, which Chrome prompts for on first use.

## Layout

```
public/manifest.json   Extension manifest
src/background/        Service worker: auth, API calls, message routing
src/content/           One content script per site
src/core/              Hub config, storage, API client, page detection, UI
src/popup/             Toolbar popup
src/options/           Options page
```

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
