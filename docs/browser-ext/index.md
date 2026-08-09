# Browser extension

The Calkit browser extension, compatible with Chrome, Edge, and more,
allows you to interact with your project from other tools:
Overleaf for syncing figures, results, and text,
GitHub for viewing artifacts stored with DVC and viewing LaTeX diffs
on PRs,
and journal and preprint webpages for saving reference information directly
to BibTeX inside your project repo.

## Signing in

From a connected website,
click the Calkit toolbar icon in the bottom right and select "Sign in."

## Overleaf

<!-- prettier-ignore -->
!!! note

    Syncing from the extension requires an Overleaf token stored in your
    Calkit account, the same as syncing from calkit.io. See
    [Overleaf integration](../overleaf.md) for how to set that up.

Opening an Overleaf project shows the Calkit button in the corner, which
turns amber when a sync would do something, so a figure that was
regenerated and never made it to Overleaf is visible without going looking
for it.
Clicking it shows the Calkit project that syncs with this one and what a
sync would do:

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

A project that lives on a different hub from the one you're signed in to is
still recognized, and the panel points you at the hub it belongs to.

When viewing a pull request, the outputs it changes appear as a card at the
bottom of the conversation, where the diff can't show them: GitHub only has
the `.dvc` pointer file, which says an output changed but nothing about how.
Each one opens on top of the pull request, showing whatever is most useful:
the project's LaTeX diff if it built one, otherwise both versions side by
side.
The overlay's other views are one click away, and the same list is in the
extension's panel.

If the project builds a **LaTeX diff** of the document against the base
branch (see [LaTeX documents](../latex.md)), that's what opens: the typeset
paper with insertions and deletions marked where they happen.

A PDF without one falls back to a **text diff**, which compares the words in
the two versions. Side by side answers "did the figures move"; the text diff
answers "did the wording change". It reads text out of the PDFs themselves,
so text that reflowed around an edit can show up as changed, and a scanned
PDF has nothing to read.

## Reference management

On a journal, publisher, or preprint page, the extension reads the page's
citation metadata and checks whether that reference is already in a collection
in your current active project.
From the panel you can import it into any `.bib` collection, and read or edit
the notes stored on it.
See [References](../references.md) for how collections and notes work.

The extension watches the major preprint servers and publishers, including
arXiv, bioRxiv, PLOS, Springer, Wiley, Elsevier, Nature, Science, MDPI,
Cambridge Core, AIP, ACS, RSC, IOP, ASME, AIAA, and Oxford.
That list will never be complete, so for anything not on it, open the Calkit
toolbar popup: it reads the page you're on directly and detects the reference
the same way.

If it isn't there you can add it, then read and edit the notes on it.
To save it under a different project, select that project from the dropdown
and add it there.

## Privacy

What the extension stores and what it sends, and to whom, is in its
[privacy policy](privacy.md).
