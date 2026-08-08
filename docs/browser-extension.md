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

After connecting things all together. You can now easily sync between them.
The Overleaf document will become a Calkit pipeline stage with explicit
inputs for the figures, allowing them to be checked for staleness,
synced, and easily built offline and pushed back up to the web.

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

When viewing a pull request, if new outputs tracked with DVC have been
created and pushed, you can view them, optionally viewing the version
present on the base branch to compare side-by-side.

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

If it's not present you can add it, then view/edit noted on the item.
If you'd like to add it to a different project, you can select a different
active project from the dropdown and add it there.

## TODO

Delete this list before merging!

- [x] When hovering over a DVC tracked file on GitHub, I see my profile
      popup. This should link us to the all files page on Calkit.
      The extension panel also has no way to go "back" from viewing the
      file in the panel.
- [x] GitHub PR workflow.
- [x] Images, PDFs, and Plotly figures should be able to be viewed as modals
      on GitHub when they are DVC tracked. Maybe even notebook HTML.
      (Images render in the panel; everything else opens in the extension's
      own viewer page, since GitHub's content security policy forbids the
      frames and objects a PDF or notebook needs. Plotly links to the hub
      rather than shipping the library.)
- [x] Private repos: the PR view reads its refs from the GitHub API
      unauthenticated, so it can't see them. Route through the hub, which
      holds a token.
      (`GET /projects/{owner}/{project}/github-pulls/{number}` returns the
      head and base refs. The extension no longer asks GitHub for anything
      directly, so its GitHub host permission is gone.)
- [x] "Changed" in the PR view compares file size, the only comparable the
      contents listing carries. Exposing the DVC md5 would make it exact.
      (The contents listing now carries the DVC md5, and the comparison
      uses it, falling back to size only where a hash is missing.)
- [x] When an item is in a Zotero collection, disable the add to collection
      button unless the user changes to a hub, project, collection where it
      doesn't exist. That is, don't allow duplicates.
- [x] Should work on arvix html pages like https://arxiv.org/html/2608.06314v1.
      (Also /pdf/ URLs, which resolve to the same paper.)
- [x] Show spinner while overleaf sync status is being fetched.
- [x] Saving on overleaf should trigger a sync status refresh.
      (Listens for an explicit save, then re-checks once Overleaf has had a
      moment to write it.)
- [x] Overleaf project that needs syncing should show as yellow on calkit
      extension button to draw attention.
- [x] Add some sort of build/deploy pipeline for the browser extension.
      (`browser-ext/vX.Y.Z` tags build, test, stamp the version into the
      manifest, and attach a store-ready zip to the release. Uploading to
      the Chrome Web Store is still manual, pending store credentials.)
- [x] On cambridge.org/core papers, their feedback thing is on top of the
      calkit extension button.
      (The launcher lifts above it. There's no way to detect another site's
      floating widget, so the hosts known to collide are listed in
      `launcherPosition`, which is easy to extend.)
- [x] Arxiv html page doesn't pick up metadata even though it's in a ref
      collection on Calkit. Just shows Untitled and the arxiv number.
      (Two causes. The rendered HTML at `/html/` publishes no citation meta
      tags at all, unlike the `/abs/` page, so the title, authors, and year
      are now read from the paper's own title block. And the collection
      lookup only recognized an arXiv entry by its `eprint` field, so an
      entry written with just an arxiv.org URL or an arXiv DOI never
      matched.)
- [ ] Publish to CWS, perhaps with https://github.com/marketplace/actions/publish-chrome-extension-to-chrome-web-store.
- [ ] Only https artifact URLs can be viewed -- what about an exception for localhost ones?
- [ ] GitHub PR view should be more integrated, not just in the bottom right.
      We can actually put content into the main body, e.g., a little button
      at the bottom allowing us to view the artifact, optionally
      side-by-side with base branch.
- [ ] When switching hubs, if not logged in, we can't go back and switch to
      a different hub.
