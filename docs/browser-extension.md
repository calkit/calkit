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

On a repository page, a "Calkit artifacts" button resolves the repo to a
Calkit project and lists its DVC-tracked files, with the pipeline stage that
produced each one, previews for images, and links that download the content
from the project's DVC storage.
This is the piece GitHub can't show you on its own, since it only stores the
`.dvc` pointer files.

## References

On a journal, publisher, or preprint page, the extension reads the page's
citation metadata and checks whether that reference is already in a collection
in one of your projects.
From the panel you can import it into any `.bib` collection, and read or edit
the notes stored on it.
See [References](references.md) for how collections and notes work.

Which projects are checked is set in the extension's options.
The list is explicit rather than "everything you can see" because each project
is read on the server to search it, so checking all of them would be too slow
to do on every page load.
Pick the handful you're actively citing in.

## Zotero

On zotero.org, the panel imports a Zotero collection into a project as a
`.bib` collection, and syncs collections that are already linked.
This is the same import and sync the hub offers, reachable from the library
you're looking at.
