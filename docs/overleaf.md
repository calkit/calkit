# Overleaf integration

[Overleaf](https://overleaf.com) is a cloud-based web application designed for
collaborating on LaTeX documents.
It helps lower the barrier to entry as users don't need to
get their local machine
or a [GitHub Codespace](tutorials/latex-codespaces.md)
set up with Git, Docker, LaTeX, etc.

One downside to using Overleaf is that it is intended only for writing,
not general computing, e.g., data processing or figure generation,
so it encourages treating writing as a separate phase or project.
Any figures or tables created from automated scripts
typically need to be manually uploaded to update the Overleaf document,
which introduces complexity and a potential source of
non-reproducibility, e.g.,
if this manual figure copying process is mistakenly omitted.
It also makes it difficult to work offline.

With Calkit it's possible to link an Overleaf project to a publication
so you can use Overleaf for collaborating on the writing,
without losing the ability to work more holistically on the project.
Calkit can sync bidirectionally with Overleaf,
ensuring edits propagate both directions,
so users who prefer to work locally can do so.
Calkit can also ensure files like figures are always sent from
the local project (where they are generated) up to Overleaf,
so the PDF output looks the same in either system.

## Connecting to Overleaf

Calkit can connect to Overleaf in one of two ways:
with a Git token, which requires Overleaf Premium,
or with your browser's sign-in session, which works with any Overleaf account.
If both are set, Calkit uses the token.

### With Overleaf Premium

Visit the
[Overleaf user settings page](https://www.overleaf.com/user/settings)
and scroll down to the
"Your Git authentication tokens" section.
Generate a token, copy it, and then set it in your Calkit config with:

```sh
calkit config set overleaf_token {paste your token here}
```

### Without Overleaf Premium

Sign in to [overleaf.com](https://www.overleaf.com) in your browser,
then copy the value of its `overleaf_session2` cookie:
open the browser's developer tools,
go to Application > Cookies (Chrome, Edge) or Storage > Cookies (Firefox),
select `https://www.overleaf.com`,
and copy the value in the `overleaf_session2` row.
Then run:

```sh
calkit overleaf login
```

and paste it when prompted.
Calkit checks the session with Overleaf before storing it in your Calkit
config.

<!-- prettier-ignore -->
!!! warning "A session gives full access to your Overleaf account"
    A Git token can only read and write projects,
    but a session can do anything you can do while signed in to Overleaf.
    Treat it like a password and don't share it.

A session keeps working until you sign out of Overleaf in that browser or it
expires.
When Overleaf rejects it, Calkit asks for a new one,
so copy the cookie again after signing back in.
If a Git token stops working, e.g., because Premium has ended,
Calkit uses the session instead, if one is set.

Syncing works the same way with either,
except for how edits made on Overleaf show up in the project's history:
with a token, each Overleaf edit keeps its author and time,
while with a session, all the edits since the last sync arrive together,
credited to whoever ran the sync.

## Importing an Overleaf project

To import an Overleaf project,
use the `calkit overleaf import` command.
For example:

```sh
calkit overleaf import \
    https://www.overleaf.com/project/68000059d42b134573cb2e35 \
    paper \
    --push-path figures
```

This command will link a local project folder, in this case `paper`,
to the Overleaf project,
and always push the `paper/figures` folder, i.e.,
the figures will be one-way synced,
whereas any other files will be synced bidirectionally.
Push paths are relative to the publication folder,
and multiple can be specified.

If necessary, this command will also
create a TeXlive Docker [environment](environments.md)
and a build stage in the [pipeline](pipeline/index.md),
which will build and cache the PDF upon calling `calkit run`.

If the document already exists in your project and the Overleaf project is
empty, add `--push-only` so the local files are pushed up to Overleaf
instead of the other way around.
This also works with `calkit overleaf sync`.

## Syncing an Overleaf project

To sync a publication linked to an Overleaf project, simply call:

```sh
calkit overleaf sync
```

This will sync every publication linked to an Overleaf project.
If there is more than one and you only want to sync a single publication,
pass its path, e.g.:

```sh
calkit overleaf sync paper
```

A sync:

1. Commits [edits you've made](#uncommitted-changes) to the synced folder.
2. Brings in edits made on Overleaf and sends yours up.
3. Rebuilds each document that changed on either side,
   saves the new PDF to the project, and pushes the project.

Only the document's own build stage is run,
not the stages it depends on, which could take a long time.
To run those too, pass `--upstream`.
To only sync the source files without rebuilding, pass `--no-build`.
If the rebuild fails, Calkit warns and still saves and pushes the sync,
so you can fix the build and call `calkit run` afterward.

For a version that takes care of the surrounding steps for you, see
[guided syncing](#guided-syncing-push-and-pull) below.

### Checking status

To see what a sync would do before doing it, call:

```sh
calkit overleaf status
```

This will pull from Overleaf and print the files that only exist in one of
the two projects, and those that differ between them,
which is a good way to check if a collaborator has been editing there.
It doesn't change the project or the Overleaf document.

### Checks before syncing

An Overleaf project has no branches, so whatever is synced there is what
every collaborator sees and writes against.
Two situations make that misleading, and Calkit refuses to sync in both:

1. **The pipeline is out-of-date for the document.**
   Syncing would send figures or results that don't match the code that
   supposedly produced them.
   Only stages the document's build depends on,
   or that write into the synced folder, count.
   Out-of-date stages elsewhere in the project don't stop a sync,
   and neither does the document's own build stage,
   since the document is rebuilt after syncing.
   Run `calkit run` first, or pass `--allow-stale` to sync anyway, e.g., to
   push preliminary results from a long simulation you're still debugging.
2. **The current branch is missing commits from the default branch.**
   Syncing from there can take collaborators backwards, quietly reverting
   writing that has already been incorporated.
   Pull, merge, or rebase first, or pass `--any-branch` to sync anyway.

Note that the second check is about content, not branch names.
Working on a branch is fine as long as it contains everything already on the
default branch, so a branch cut from the tip of `main` syncs happily,
while a local `main` that's behind the remote does not.
This matters when `main` is protected: pulling from Overleaf creates commits,
so it can't happen on a branch you can't commit to.
Create a branch from the tip of `main` and sync from there.

### Guided syncing (`push` and `pull`)

`calkit overleaf push` and `calkit overleaf pull` wrap `sync` with the
steps that surround it, so a collaborator doesn't have to remember the order.

To send the project's current figures and text to Overleaf:

```sh
calkit overleaf push
```

This pulls the latest Git and DVC data, checks the pipeline is up-to-date
(offering to run it if it isn't), then pushes to Overleaf without pulling
anything back.

To bring collaborators' writing back into the project:

```sh
calkit overleaf pull
```

This does the same preparation, shows what has changed on Overleaf and asks
you to confirm, syncs in both directions, then offers to run the pipeline and
save the result.
If the default branch is protected, pass `--branch`/`-b` to create or switch
to a branch first:

```sh
calkit overleaf pull -b overleaf-updates
```

Both accept the same paths as `sync`, and `--yes`/`-y` answers yes to every
prompt so they can run unattended, e.g., in CI.
The one exception is retrying a failed `calkit pull`, which would otherwise
loop forever with nobody there to stop it; that is retried a few times and
then gives up.

The same checks apply wherever a sync happens, including
`calkit save --overleaf` and the sync at the end of `calkit run --overleaf`.
The sync at the _start_ of `calkit run --overleaf` is exempt, since running
the pipeline is what's about to make it current.

### Uncommitted changes

Edits you've made to files in the synced folder are committed before
syncing, with a message like "Update paper before Overleaf sync",
so they're sent up to Overleaf.
New files in the folder are only synced once they're
[stored](#what-gets-synced) in the project,
e.g., with `calkit save`.

Changes elsewhere in the project,
including uncommitted edits to `calkit.yaml`,
are left as they are:
they aren't committed with the sync and don't stop it.

With [`--no-commit`](#syncing-without-committing-no-commit),
Calkit doesn't commit anything for you,
so the synced folder needs to have no uncommitted changes.

### What gets synced

Calkit only syncs **stored** files, i.e., files that are tracked by Git or
stored with DVC.
These are synced bidirectionally, except for files under `push_paths`
(see [importing](#importing-an-overleaf-project)), which are pushed to
Overleaf one-way only.

A push path says the project is the source of truth for those files,
so if one has been edited on Overleaf since the last sync,
Calkit stops rather than overwriting it:

```
These files were changed on Overleaf but are push-only, so this sync would
overwrite them: figures/photo.txt. Copy the changes into the project if you
want to keep them, or sync with --force to overwrite them.
```

Nothing regenerates such a file, so unlike a pipeline output,
the only other copy would be in the Overleaf project's history.
Once you've copied anything worth keeping into the project,
sync with `--force`/`-f` to overwrite what's there.

Anything the pipeline produces is pushed one-way, however it's stored.
Overleaf needs those files to compile the document, but an edit made to one
of them there can't come back: the next run would overwrite it, so it
belongs in whatever the stage builds the file from.
This covers a `json-to-latex` stage's `.tex` and the copies a `map-paths`
stage puts in the document's folder, such as a `references.bib` or class
file shared between papers.
Those copies are pushed even though they're gitignored, since without them
Overleaf can't compile.
If one of them is edited on Overleaf, `calkit overleaf sync` says which
files it's about to overwrite.

Everything else is treated as ignored and is never pushed to, pulled from,
or deleted from Overleaf.
In particular, this includes:

- Files ignored by Git (e.g., via `.gitignore`) that are not stored by DVC
  and are not produced by the pipeline.
- Pipeline outputs with `storage: null` that aren't copies put in the
  document's folder by a `map-paths` stage,
  such as LaTeX build artifacts (`.aux`, aux PDFs, etc.).
  These are tracked by the pipeline but not stored, so Calkit leaves them
  alone on both sides.

A file is only deleted from Overleaf when a previously-synced stored file
is genuinely removed from the project (deleted from Git and DVC).
A file that merely disappears from disk because it hasn't been pulled, or
that became an ignored/`storage: null` output, is left in place on Overleaf.

#### Edits to `map-paths` copies

A `map-paths` copy is the one generated file whose edits have somewhere to
go: the file the stage copies it from.
So when a collaborator adds a reference to `references.bib` on Overleaf, and
that file is copied into the document's folder from a shared location,
Calkit writes the change back to the shared file:

```
Applying Overleaf's change to references.bib to pubs/shared/references.bib,
which it's copied from
Run the pipeline to rebuild from the updated source(s)
```

The shared file is committed along with the rest of the sync, and the next
`calkit run` rebuilds every copy from it, so the change reaches the other
publications that share it too.

This only applies when the source is authored.
If a `map-paths` stage copies from a file that another stage generates, an
edit made to the copy on Overleaf has nowhere to survive, so Calkit reports
it as overwritten instead.

Calkit also won't overwrite a source that has changes of its own, i.e., one
that no longer matches the copy the last run made from it.
That means both sides changed, and picking one would throw the other away,
so it says so and leaves both alone:

```
Warning: references.bib was changed on Overleaf, but
pubs/shared/references.bib, which it's copied from, has changes of its own;
leaving both alone, so Overleaf keeps its version. Run the pipeline and sync
again, or merge the two by hand.
```

Note that such a file is also left out of what gets pushed, so the edit
stays on Overleaf until you merge it.
Pushing the local copy would overwrite the very edit Calkit just declined to
pull.

Running the pipeline before syncing (which is
[the default](#checks-before-syncing)) keeps this from coming up, since the
copy then matches its source.

### Syncing without committing (`--no-commit`)

By default, `calkit overleaf sync` creates a commit in your project repo
recording the synced changes.
If you'd rather review the incoming Overleaf changes before committing them
yourself, use:

```sh
calkit overleaf sync --no-commit
```

With `--no-commit`:

- Changes from Overleaf are still pulled into your working tree, but they are
  left **staged** (in the Git index) instead of committed, so you can inspect,
  amend, or commit them however you like.
- No "Sync ... with Overleaf project" commit is created in the project repo.
- Overleaf itself is **always** committed and pushed; `--no-commit` only
  affects the project repo.

**Why it leaves changes staged rather than simply not touching Git:**
Calkit pulls Overleaf edits by turning them into a patch and applying it with
`git am`, which inherently creates commits (a mailbox patch can't be applied
without committing).
So pulling always advances the project repo's `HEAD`.
To honor `--no-commit`, Calkit then runs `git reset --soft` back to the commit
the repo was at before the sync.
A soft reset rewinds `HEAD` but keeps every change in the index, so the pulled
Overleaf edits end up staged and ready for you to commit, exactly as if you'd
made them yourself.

<!-- prettier-ignore -->
!!! note "`--no-commit` discards Overleaf commit authorship"
    A normal sync preserves the original author, date, and message of each
    Overleaf-side commit (Calkit applies them with `git am`, which keeps that
    metadata).
    Because `--no-commit` rewinds those commits and leaves only their net
    changes staged, committing them yourself collapses everything into a
    single commit authored by **you**--the per-commit Overleaf authorship
    and history are not retained.
    Omit `--no-commit` (the default) if preserving Overleaf editors'
    authorship matters to you.
    This doesn't apply when
    [syncing with a browser session](#without-overleaf-premium),
    which doesn't keep Overleaf authorship either way.

## Example

You can view an example project that uses Overleaf integration on
[GitHub](https://github.com/calkit/example-overleaf)
and the [Calkit hub](https://calkit.io/calkit/example-overleaf).
This project syncs the document text bidirectionally,
and pushes figures up to Overleaf.

## Merge conflicts

If the same lines are changed in a file in both the main project and the
Overleaf project a "merge conflict" will occur.
In this case,
the text will need to be merged together manually.
[VS Code](https://code.visualstudio.com/) has a built-in merge conflict
resolution tool, but there are many to choose from.

In the file, e.g., `paper.tex`, you'll see something like:

```tex
<<<<<<< HEAD
I made this edit locally. It's pretty great.
=======
I made this edit on Overleaf. It's great.
>>>>>>> <commit-id-of-patch>
```

After merging the two chunks together and deleting the lines that start with
`<<<<<<<`, `>>>>>>>`, or `=======`,
mark the conflict as resolved and sync again with:

```sh
calkit overleaf sync --resolve
```
