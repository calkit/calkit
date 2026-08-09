# Browser extension

The Calkit browser extension brings your projects into the sites where a lot
of research work actually happens: GitHub, Overleaf, and journal and
preprint pages.
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
Reference lookups check its collections, and importing a reference defaults
to it.
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

If you already have a GitHub repo for your code, data, figures, etc.,
you can integrate the Overleaf and GitHub projects into a Calkit project.
From Overleaf, open the Calkit extension panel and click
"attach to new project".
From there, select the switch for "exists on GitHub",
then start typing your GitHub repo name.
You'll see an option for what folder you want the Overleaf project to live
in inside the larger project.

Note: If you haven't installed the Calkit GitHub app for the repo in question,
you'll need to do that.

Once everything is connected, syncing between them is a single action.
The Overleaf document becomes a Calkit pipeline stage with explicit
inputs for the figures, so they can be checked for staleness,
synced, and built offline and pushed back up to the web.

## GitHub

On a repository page, the Calkit button in the lower right indicates if the
current repo is a Calkit project.
If it's not, you can turn it into one.
If it is, Calkit will intersperse your DVC-tracked artifacts
in the GitHub file view with a badge showing that's how it's stored.
From the Calkit extension you can also visit the project on its Calkit hub.

The button knows which state it's in before you click it.
It first reads the repo's `calkit.yaml`, if GitHub is serving one, since that
file names the hub the project belongs to.
That way a project on a hub other than the one you're signed in to is
recognized as a Calkit project rather than looking like it isn't one, and the
panel points you at the hub it actually lives on.
A private repo won't serve its `calkit.yaml` anonymously, so those fall back to
asking your hub whether it knows the repo.

When viewing a pull request, the outputs it changes appear as a card at the
bottom of the conversation, where the diff can't show them: GitHub only has
the `.dvc` pointer file, which says an output changed but nothing about how.
Each one can be viewed on top of the pull request, or compared side by side
with the version on the base branch.
The same list is in the panel, in case GitHub's markup moves out from under
the card.

A PDF also offers a **text diff**, which reads the words out of both versions
on the hub and compares them.
Side by side answers "did the figures move"; the text diff answers "did the
wording change", which is otherwise invisible when the source isn't in the
repo or the numbers come from data.
Extraction is lossy by nature -- a PDF stores glyphs at positions, not
sentences -- so ligatures, hyphenation, and layout spacing are normalized
away first, and text that reflowed around a real edit can still show up as
changed.
A scanned PDF has no text to read, and figures aren't compared this way.

## Reference management

On a journal, publisher, or preprint page, the extension reads the page's
citation metadata and checks whether that reference is already in a collection
in your current active project.
From the panel you can import it into any `.bib` collection, and read or edit
the notes stored on it.
See [References](references.md) for how collections and notes work.

The extension watches the major preprint servers and publishers, including
arXiv, bioRxiv, PLOS, Springer, Wiley, Elsevier, Nature, Science, MDPI,
Cambridge Core, AIP, ACS, RSC, IOP, ASME, AIAA, and Oxford.
That list will never be complete, so for anything not on it, open the Calkit
toolbar popup: it reads the page you're on directly and detects the reference
the same way.

If it isn't there you can add it, then read and edit the notes on it.
To save it under a different project, select that project from the dropdown
and add it there.

## Releasing

Publishing a release tagged `browser-ext/vX.Y.Z` builds and tests the
extension, stamps that version into `manifest.json` and `package.json`,
strips source maps, and attaches a store-ready zip to the release.
The version comes from the tag because the Chrome Web Store rejects an
upload whose manifest version isn't higher than the last one, and a version
kept in sync by hand eventually isn't.

The same workflow uploads to the Chrome Web Store when the
`CHROME_EXTENSION_ID` repository variable is set, using the
`CHROME_CLIENT_ID`, `CHROME_CLIENT_SECRET`, and `CHROME_REFRESH_TOKEN`
secrets (an OAuth client for the Web Store API, authorized for the
publishing account).
Until that variable exists the upload step is skipped and the release's zip
is uploaded by hand, so the workflow is useful before the listing is.
