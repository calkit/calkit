# Browser extension

The Calkit browser extension brings your projects into the sites where a lot
of research work actually happens: GitHub, Overleaf, journal and preprint
pages, and Zotero.
It's a Chrome extension (Manifest V3), and its source lives in the
[`browser-ext`](https://github.com/calkit/calkit/tree/main/browser-ext)
directory of the Calkit repo.

## Installing

The extension isn't in the Chrome Web Store yet.
To run it from source:

```sh
make browser-ext
```

Then open `chrome://extensions`, turn on developer mode,
click "Load unpacked," and select the `browser-ext/dist` directory.

## Signing in

Click the Calkit toolbar icon and select "Sign in."
This uses the same device authorization flow as `calkit hub login`:
a tab opens on the hub, you approve the request, and the extension stores a
short-lived access token and a refresh token.

Every API call happens in the extension's service worker, so the token is
never handed to a script running in a web page.

If you use a staging, local, or self-hosted hub, select it in the extension's
options page first, since credentials are stored per hub.

## Settings

The options page holds two settings.

**Hub** selects which instance every surface talks to: calkit.io, staging, a
local development instance, or a self-hosted one.
Changing it applies immediately, and the page then shows whether you're
signed in to the newly selected hub, since credentials are stored per hub and
switching usually means signing in again.

A self-hosted hub is configured with its URL alone, because
[a hub serves its API from the `api` subdomain](hub/self-hosting.md) of its own
host.
Chrome prompts for access to that host when the hub is applied.

**Active project** is the project you're working on, remembered per hub.
Reference lookups check its collections, and importing a reference or a
Zotero collection defaults to it.
It can also be switched from the popup, next to any project in the list.

One project at a time is deliberate.
A thesis-scale monorepo stays easier to keep reproducible when everything
lands in the same place, and a single project is also what keeps reference
lookups fast, since each one has to be read on the server to search it.

Project pickers list only the projects you can write to, since everything
they offer writes something.
The GitHub panel is the exception, resolving a repo at read access so you
can browse the artifacts behind a public project you don't own.

## Overleaf

<!-- prettier-ignore -->
!!! note

    Syncing from the extension requires an Overleaf token stored in your
    Calkit account, the same as syncing from the hub. See
    [Overleaf integration](overleaf.md) for how to set that up.

Opening an Overleaf project shows a panel with the Calkit project that syncs
with it and what a sync would do:

- **Figures to sync**, meaning figures whose content in the project differs
  from what's currently on Overleaf. This is the case worth catching, since a
  regenerated figure that never made it to Overleaf leaves the paper showing
  old results.
- A **stale** flag on any figure whose pipeline stage is itself out of date,
  which means the figure should be regenerated with `calkit run` before it's
  worth syncing.
- Other changed files, files removed from the project, and a count of Overleaf
  edits waiting to come back.
- A **Sync now** button, which does the same thing as `calkit overleaf sync`.

If the Overleaf project isn't linked to a Calkit project yet, the panel lets
you search your projects, check whether one of them already syncs with it, or
import the Overleaf project into a project as a new publication.

Linked Overleaf projects are indexed on the hub the first time a sync or a
status check runs for them, which is what lets the extension go from an
Overleaf URL back to your project.

## GitHub

On a repository page, the Calkit button in the lower right indicates if the
current repo is a Calkit project.
If it's not, you can turn it into one.
If it is, Calkit will intersperse your DVC-tracked artifacts
in the GitHub file view with a badge showing

## References

On a journal, publisher, or preprint page, the extension reads the page's
citation metadata and checks whether that reference is already in a collection
in your current active project.
From the panel you can import it into any `.bib` collection, and read or edit
the notes stored on it.
See [References](references.md) for how collections and notes work.

## Zotero

On zotero.org, the panel imports a Zotero collection into a project as a
`.bib` collection, and syncs collections that are already linked.
This is the same import and sync the hub offers, reachable from the library
you're looking at.
