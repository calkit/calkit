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

## Generating and storing an Overleaf token

In order for Calkit to interact with Overleaf,
you'll need to set a token in the config.
To do this,
visit the
[Overleaf user settings page](https://www.overleaf.com/user/settings)
and scroll down to the
"Your Git authentication tokens" section.
Generate a token, copy it, and then set it in your Calkit config with:

```sh
calkit config set overleaf_token {paste your token here}
```

## Importing an Overleaf project

To import an Overleaf project as a Calkit publication,
use the `calkit import overleaf` command.
For example:

```sh
calkit overleaf import \
    https://www.overleaf.com/project/68000059d42b134573cb2e35 \
    paper
```

This command will link a local project folder, in this case `paper`,
to the Overleaf project,
and always push the `paper/figures` folder, i.e.,
the figures will be one-way synced,
whereas any other files will be synced bidirectionally.

If necessary, this command will also
create a TeXlive Docker [environment](environments.md)
and a build stage in the [pipeline](pipeline/index.md),
which will build and cache the PDF upon calling `calkit run`.

## Syncing an Overleaf project

To sync a publication linked to an Overleaf project, simply call:

```sh
calkit overleaf sync
```

After syncing, you'll probably want to ensure the local PDF is up-to-date
by calling `calkit run`, and if anything has changed,
commit and push those changes to the hub with
`calkit save -am "Run pipeline"`.

For a version that takes care of the surrounding steps for you, see
[guided syncing](#guided-syncing-push-and-pull) below.

### Checks before syncing

An Overleaf project has no branches, so whatever is synced there is what
every collaborator sees and writes against.
Two situations make that misleading, and Calkit refuses to sync in both:

1. **The pipeline is out-of-date.**
   Syncing would send figures or results that don't match the code that
   supposedly produced them.
   Run `calkit run` first, or pass `--allow-stale` to sync anyway, e.g., to
   push preliminary results from a long simulation you're still debugging.
2. **The current branch is missing commits from the default branch.**
   Syncing from there can take collaborators backwards, quietly reverting
   writing that has already landed.
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

Both accept the same paths as `sync`, and `--yes`/`-y` answers every prompt
so they can run unattended, e.g., in CI.

The same checks apply wherever a sync happens, including
`calkit save --overleaf` and the sync at the end of `calkit run --overleaf`.
The sync at the _start_ of `calkit run --overleaf` is exempt, since running
the pipeline is what's about to make it current.

### A clean working tree is required

Syncing requires the synced folder to have no uncommitted changes.
If there are any (staged or unstaged), Calkit raises an error like:

```
Uncommitted changes found in {wdir}.
Commit or stash them before syncing with Overleaf,
or use --auto-commit/-a to automatically commit them.
```

This is because incoming Overleaf edits are applied to the synced path with
`git am`, which operates on commits and refuses to run against a dirty working
tree.
Requiring a clean tree also keeps the sync recoverable: the commit you were on
before the sync is a clean checkpoint, so Calkit can cleanly reset back to it
(e.g., for [`--no-commit`](#syncing-without-committing-no-commit)) or abort a
failed patch without entangling or losing your in-progress edits.

To let Calkit commit your local changes for you before syncing instead of
erroring, pass `--auto-commit`/`-a`:

```sh
calkit overleaf sync --auto-commit
```

### What gets synced

Calkit only syncs **stored** files, i.e., files that are tracked by Git or
stored with DVC.
These are synced bidirectionally, except for files under `push_paths`
(see [importing](#importing-an-overleaf-project)), which are pushed to
Overleaf one-way only.

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
leaving it alone. Run the pipeline and sync again, or merge the two by hand.
```

Running the pipeline before syncing (which is
[the default](#checks-before-syncing)) keeps this from coming up, since the
copy then matches its source.

Everything else is treated as ignored and is never pushed to, pulled from,
or deleted from Overleaf.
In particular, this includes:

- Files ignored by Git (e.g., via `.gitignore`) that are not stored by DVC
  and are not produced by the pipeline.
- Pipeline outputs with `storage: null` that aren't materialized in the
  document's folder, such as LaTeX build artifacts (`.aux`, aux PDFs, etc.).
  These are tracked by the pipeline but not stored, so Calkit leaves them
  alone on both sides.

A file is only deleted from Overleaf when a previously-synced stored file
is genuinely removed from the project (deleted from Git and DVC).
A file that merely disappears from disk because it hasn't been pulled, or
that became an ignored/`storage: null` output, is left in place on Overleaf.

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
