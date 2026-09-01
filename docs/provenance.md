# Provenance

Provenance is the record of where something came from: who made it, what it
was made from, and how. A reader deciding whether to trust a figure is really
asking a chain of these questions, and the answer has to hold at every link
or the chain doesn't hold at all.

## The pipeline answers most of this for you

If a stage produced a file, its provenance is already written down. The stage
names the command that ran, the inputs it read, and the environment it ran
in, and `calkit run` records what actually happened in `dvc.lock`. Nothing
further is needed, and nothing should be written twice.

The gap is everything that arrives some other way:

- data somebody measured or typed in
- a file downloaded from a website or an archive
- a photograph of the apparatus
- a diagram drawn by hand, or by a generative AI tool
- a script or config a colleague sent over

These sit at the bottom of the chain. Every automated check above them
passes, because there is nothing to check, and that is exactly what makes
them easy to overlook: the project looks fully reproducible right up until
someone asks where the raw numbers came from.

## Data

A dataset records how it entered the project. See
[datasets](datasets.md#declaring-an-imported-dataset) for the full set of
forms, in short:

```yaml
datasets:
  # Collected for this project
  - path: data/raw.csv
    created_by:
      email: me@myorg.edu
      orcid: 0000-0002-1825-0097
  # Obtained from elsewhere
  - path: data/published.csv
    imported_from:
      doi: 10.5281/zenodo.1234567
```

## Everything else

Most files are neither a dataset nor a figure nor a paper. Those go in
`misc`, which takes the same `imported_from` forms plus who made it:

```yaml
misc:
  - path: img/test-rig.jpg
    title: Photo of the test rig
    created_by:
      email: me@myorg.edu
  - path: cfg/solver.toml
    imported_from:
      url: https://someone.org/solver.toml
      date: 2026-01-02
```

Scripts count. A figure resting on a script nobody will claim has just as
little behind it as one resting on data nobody collected.

### Bringing a file in from elsewhere

`calkit import path` copies a file into the project and writes the entry
for you, which is the usual way one of these gets recorded. A link copied
out of the browser is enough:

```sh
calkit import path \
  https://github.com/myorg/setups/blob/main/setups/setup.sh \
  scripts/setup.sh
```

A GitHub or GitLab link to a file is read as the Git source it actually
is, rather than as an HTML page that happens to contain the file: the
repo, the branch, and the path within it all come out of the URL.
A link that names no revision, including one written out by hand as
`https://github.com/myorg/setups/setups/setup.sh`, takes the default
branch.
An SSH clone URL works the same way, since that is the thing most often
copied out of a forge:

```sh
calkit import path git@github.com:myorg/setups/setups/setup.sh \
  scripts/setup.sh --git-ref main
```

The repo is taken to be the first two segments after the host, which is
right for GitHub and for GitLab projects outside nested groups. For
anything else---or for a repo Calkit can't read a URL for at all---name
the repo outright:

```sh
calkit import path setups/setup.sh scripts/setup.sh \
  --git-repo https://github.com/myorg/setups.git --git-ref main
```

A branch whose name contains a slash, like `feature/foo`, needs no special
handling: a URL doesn't say where such a branch ends and the path begins,
so the split is checked against the repo when the file is fetched and
corrected if the guess was wrong. `--git-ref` still overrides it.

Other addresses work too, and are read as what they are:

| Written as                          | Recorded as                  |
| ----------------------------------- | ---------------------------- |
| A GitHub or GitLab link to a file   | `git`, with `ref` and `path` |
| Any other URL                       | `url`                        |
| A DOI, bare or as a `doi.org` link  | `doi`                        |
| `someone/some-project/path/to/file` | `project`                    |

A DOI is recognized rather than downloaded, since it resolves to a
landing page: saving that HTML and calling it the data is the mistake
worth refusing. Use
[`calkit import zenodo`](cli-reference.md) for a Zenodo record.

It lands in `misc` unless `--kind` says otherwise, and the entry records
the commit the file actually came from, even when a branch was named:

```yaml
misc:
  - path: scripts/setup.sh
    imported_from:
      git:
        repo_url: https://github.com/myorg/setups.git
        path: setups/setup.sh
        ref: main
```

The copy is committed here rather than fetched on demand, so the project
stays self-contained and a pipeline stage can depend on the file like any
other input.

To pick up later changes:

```sh
calkit sync import scripts/setup.sh
```

That takes the latest of whatever the entry follows---its `ref` if it
names one, and the repo's default branch otherwise---and records the
commit it lands on in `rev`.
So `ref` is the question and `rev` is the answer: reading the answer back
would make refreshing a no-op.

`--git-ref` changes what an entry follows, from then on rather than just
this once:

```sh
calkit sync import scripts/setup.sh --git-ref v1.2
```

A `ref` naming a commit rather than a branch is a fixed point, so an
import pinned that way---including one taken from a link to a file at a
particular commit---stays where it is when refreshed.

Either way this is a one-way copy from the source, not a merge: local
changes to the file are discarded. An import is a claim about where the
bytes came from, and an edit that survived would make that claim false.
If the file needs to differ here, it isn't imported---drop the
`imported_from` and record who changed it instead.

To see everything a project took from elsewhere, whichever list it was
recorded in:

```sh
calkit list imports
```

And to refresh all of them at once:

```sh
calkit sync import --all
```

An entry that can't be refreshed in place---a dataset tracked by DVC, or a
record named only by a DOI---is reported and skipped rather than stopping
the rest, as is one whose source can't be reached, since a repo being down
shouldn't leave every other import stale. The command exits non-zero when
anything was skipped, so a script notices.

## What goes where

`calkit.yaml` records what a person declared---the repo, the path within
it, and the `ref` to follow. What a fetch resolved to goes in
`.calkit/imports.json`, keyed by path:

```json
{
  "scripts/setup.sh": {
    "fetched": "2026-08-31T23:14:21+00:00",
    "rev": "4fadbcf62125c19c9cbf31de60831f656ffe5d4e",
    "hash": "sha256:9f2b..."
  }
}
```

That file is committed, so everyone cloning the project gets the same
bytes, the way they do from `dvc.lock`. Everything Calkit keeps under
`.calkit` is managed by Calkit---read and write it through the CLI, the
web app, or the extension rather than by hand.

To pin an import, write the commit hash as its `ref`. A commit is a thing
to follow that happens never to move, so no separate field is needed and
`calkit.yaml` stays a statement of intent.

The recorded checksum is what makes a local edit visible. Refreshing a
file that has been changed since it was fetched would discard that work,
so it is reported and refused until `--force` says otherwise:

```sh
calkit sync import scripts/setup.sh
# Error: 'scripts/setup.sh' has been edited since it was imported ...
```

An entry written before this split carries its `rev` in `calkit.yaml`.
It is still read, and refreshing the import moves it across, so nothing
has to be migrated by hand.

`created_by` is the same key for all of them, whether the work was
collecting data, drawing a diagram, or taking a photograph, and it takes a
list, since work usually has more than one person behind it. Each entry
needs an email or an ORCID.
A name on its own doesn't say which of the several people with that name
this is, so credit rests on something resolvable.

## Figures

Most figures come out of a pipeline stage, which already says how they were
made. A figure that doesn't -- a schematic drawn by hand, a diagram laid out
with a generative AI tool -- has no stage to point at, so it takes
attribution the same way `misc` does:

```yaml
figures:
  - path: figures/cp-curve.png
    title: Power coefficient
    stage: plot-cp # Made by the pipeline; nothing more to record
  - path: figures/schematic.png
    title: Apparatus schematic
    created_by:
      email: me@myorg.edu
```

A figure obtained from elsewhere takes the same `imported_from` forms a
dataset does, and publications do too; `created_by` and `imported_from`
can't both be set on one entry.

### Drafting a figure in the browser

The hub's figure studio runs Python in the browser, so a plot can be
iterated on before anything is installed. A run there proves nothing about
reproducibility, and the studio doesn't pretend otherwise: nothing is
recorded until you save, and saving commits the script, declares a
`python-script` stage that reads the data and writes the figure, and creates
a Python environment for the stage if the project has none. From then on the
figure is a pipeline output like any other, and the real provenance is the
stage's next run on a real environment, not the preview you saw in the
browser.

## Disclosing generative AI

If a generative AI tool helped produce a figure or a `misc` artifact, the
person who used it says so with `with_ai`:

```yaml
figures:
  - path: figures/schematic.png
    created_by:
      email: me@myorg.edu
      with_ai: Claude Opus 5 # Can be a list too
```

The disclosure sits inside the person rather than beside them, so it can't
exist without someone answering for it. A model can't be responsible for a
file; `created_by` says who was, and `with_ai` says what they used. With
several authors, it also records which of them used the tool:

```yaml
misc:
  - path: figures/composite.drawio
    created_by:
      - email: me@myorg.edu
        with_ai: Claude Opus 5
      - orcid: 0000-0001-5109-3700
```

The point isn't that generative AI is disqualifying. It's that whether its
use was appropriate depends entirely on what the file is, and a reader can
only make that call if they're told. A schematic laid out by a model is
usually unremarkable.

### On a dataset, it's a question to answer

`with_ai` can be recorded anywhere a person can, datasets included. That is
deliberate: a rule against writing it down doesn't stop anyone using a
model, it only stops readers finding out.

But it should read as a flag rather than a footnote. A schematic laid out
with a model is usually unremarkable. Data is not. A dataset is either
measured, or obtained from somewhere, or computed by the pipeline from
things that were, and a model produced none of those: there is no
measurement behind it and no derivation to check. Seeing `with_ai` on
a dataset's `created_by` is a reason to ask exactly what the tool did, and
to expect a specific answer.

Often the honest answer moves the record somewhere better. If a model
generated the data itself -- synthetic training data, say -- then a pipeline
stage made it, and the stage records the command, the inputs, and the
environment, which is a far stronger account than any disclosure written by
hand. If the model only transcribed handwritten sheets or reshaped a file,
say so in the dataset's `description`, where the reader is already looking.

## What a declaration is worth

Everything on this page is hand-written into `calkit.yaml`, and writing
something down doesn't make it so. A declaration is the weakest link in a
provenance chain: nothing verifies it.

That's not an argument against recording it, since the alternative is
recording nothing. But it does mean an origin a reader can go and fetch
beats an attestation whenever one exists. Prefer, in order:

1. **A DOI**, which resolves and is citable
2. **A Git repo at a specific commit**, which names exact bytes. A repo and
   path with no revision names whatever is there today, which is a mutable
   claim dressed as a citation, so `rev` must be a commit hash rather than a
   branch or tag
3. **A URL**, optionally with the date it was retrieved
4. **An attestation** that someone collected or created it, when there's
   genuinely nothing to point at
