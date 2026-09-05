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

| Written as                          | Recorded as                               |
| ----------------------------------- | ----------------------------------------- |
| A GitHub or GitLab link to a file   | `git_repo_url`, with `git_ref` and `path` |
| Any other URL                       | `url`                                     |
| A DOI, bare or as a `doi.org` link  | `doi`                                     |
| `someone/some-project/path/to/file` | `project`                                 |

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
      git_repo_url: https://github.com/myorg/setups.git
      path: setups/setup.sh
      git_ref: main
```

The copy is committed here rather than fetched on demand, so the project
stays self-contained and a pipeline stage can depend on the file like any
other input.

To pick up later changes:

```sh
calkit sync import scripts/setup.sh
```

That takes the latest of whatever the entry follows---its `git_ref` if it
names one, and the repo's default branch otherwise---and records the
commit it lands on in the lock file.
So `git_ref` is the question and the recorded commit is the answer:
reading the answer back would make refreshing a no-op.

`--git-ref` changes what an entry follows, from then on rather than just
this once:

```sh
calkit sync import scripts/setup.sh --git-ref v1.2
```

A `git_ref` naming a commit rather than a branch is a fixed point, so an
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
it, and the `git_ref` to follow. What a fetch resolved to goes in
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

To pin an import, write the commit hash as its `git_ref`. A commit is a thing
to follow that happens never to move, so no separate field is needed and
`calkit.yaml` stays a statement of intent.

The recorded checksum is what makes a local edit visible. Refreshing a
file that has been changed since it was fetched would discard that work,
so it is reported and refused until `--force` says otherwise:

```sh
calkit sync import scripts/setup.sh
# Error: 'scripts/setup.sh' has been edited since it was imported ...
```

An entry written before this split carries its `git_rev` in
`calkit.yaml`.
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
   claim dressed as a citation, so `git_rev` must be a commit hash rather
   than a
   branch or tag
3. **A URL**, optionally with the date it was retrieved
4. **An attestation** that someone collected or created it, when there's
   genuinely nothing to point at

## Documents

A paper is where provenance is easiest to lose. A number is copied from a
results file into a sentence, a figure is dropped into a float, and from
then on nothing connects the document to the pipeline that produced them.
Calkit's `json-to-latex` and `questions-to-latex` stages inject that
content instead of copying it, and `calkit.sty` marks each injection so
that a reader of the TeX source or the PDF can see it came from elsewhere
in the project and follow the trail.

Set `provenance: true` on a `latex` stage:

```yaml
pipeline:
  stages:
    paper-numbers-to-latex:
      kind: json-to-latex
      command_name: result
      inputs: [results/paper-numbers.json]
      outputs:
        - path: paper/generated-numbers.tex
          storage: git
    questions-to-latex:
      kind: questions-to-latex
      inputs: [results/findings.json]
      outputs:
        - path: paper/generated-questions.tex
          storage: git
    build-paper:
      kind: latex
      target_path: paper/main.tex
      provenance: true
      inputs: [paper/generated-numbers.tex, paper/generated-questions.tex]
```

The document itself needs nothing:

```latex
\input{generated-numbers}
...
The error falls by \result[Improvement]x.
\includegraphics[width=0.7\textwidth]{../figures/dissipation.pdf}
```

What the document uses is read from its source, the same way
[`calkit describe components`](#following-a-component-back) reads it, so
an ordinary `\includegraphics` is a component like anything else. The
page each one landed on comes from the `.synctex.gz` the build already
writes, which records where TeX shipped material out rather than where it
was written, so a float that moved is reported on the page it moved to.
The values themselves come from the results files as the build read them.
No package, no special commands, no rewriting a paper that already exists.

The same file is what a viewer uses to jump from a spot in the PDF to the
line of source behind it. A build in a container records the container's
paths, which nothing outside it can open, so those are rewritten after
each build to point at the files as they actually sit. Reverse search in
[LaTeX Workshop](https://github.com/James-Yu/LaTeX-Workshop) then lands on
the real line, where the components lens takes over: from a number on the
page to the stage that computed it, without leaving the editor.

`calkit.sty` is for the one thing none of that can do: marking injected
content on the page. Load it and pass `provenance`, and every injected
value is colored so a reader can see it came from elsewhere:

```latex
\usepackage[provenance]{calkit}
```

Its `\ckfigure`, `\ckinput` and `\ckblock` also log what they typeset,
which is worth having for content no parse can see: a path a macro built,
or a figure inside a conditional. That log is folded into the record
alongside what the source says. Everything else about the package is
optional. Drop the option, or pass `final`, and the document renders as if
it were not there, so the markers cost nothing in the version that goes to
a journal.

Each build writes `<artifact>.provenance.json`: every value, figure and
text block the document took from the project, the pages it appears on,
the stage that produced it, that stage's inputs, the hash recorded in
`dvc.lock`, and, for a value, the value itself. That file is the trail in
machine-readable form, for editors, the hub, and checks. A build that
loads the package also gets `calkit.sty` installed beside the document
(commit it, so the paper builds on Overleaf and anywhere else without
Calkit) and a per-build artifact table `calkit-provenance.tex` (do not
commit it).

### What a record says

```json
{
  "$schema": "https://docs.calkit.org/schemas/provenance.json",
  "_note": "Written by 'calkit latex build --provenance'. Do not edit...",
  "artifact": "paper/main.pdf",
  "source": "paper/main.tex",
  "kind": "publication",
  "components": [ ... ]
}
```

The record is named after the **artifact** --- what the build produced and
what a reader reads --- rather than after its source, because not every
kind of artifact has a source to edit. A publication has one, and it is
where a person writes and where a position in the editor resolves, so it
is named separately as `source`. `kind` says which positional vocabulary
the components use: a publication has pages.

A component names the artifact its value came _from_, not the file it
passed through. A number reaches the page as
`results/findings.json` → `paper/generated-numbers.tex` → `paper/main.pdf`,
and the record names the results file, because that is what a reader
cares about and the generated `.tex` is plumbing.

The schema is published at
[docs.calkit.org/schemas/provenance.json](https://docs.calkit.org/schemas/provenance.json),
the same way the [`calkit.yaml` schema](calkit-yaml.md) is, so an editor
validates a record without any per-user configuration. Records are written
by the build and read by tools; nothing in one should be edited by hand,
which is what the `_note` says to anything that might try.

### Reaching one value in a big results file

Without `keys`, every top-level key in the input becomes available as
`\result[Key]`. That suits a results file written for the paper. A file
exported wholesale from an analysis is a different matter: one exported
from a MATLAB table can hold hundreds of thousands of values, and turning
all of them into LaTeX commands produces a multi-megabyte `.tex` the
document never reads.

Name what the paper uses instead, dotted to reach into nested output:

```yaml
pipeline:
  stages:
    paper-numbers-to-latex:
      kind: json-to-latex
      command_name: result
      inputs: [results/energy-flux.json]
      keys:
        - c_eps_collapse.slope
        - summary.rmse
        - stations.0.cf
```

which gives `\result[c_eps_collapse.slope]` and the rest, and nothing
else. Dotted keys are read the same way question evidence reads them: a
key that exists literally wins, so one containing dots keeps working, and
an integer part indexes into a list. A key that isn't in the input stops
the stage rather than quietly going missing from the paper.

Two more things that bite when results come out of MATLAB or NumPy. A
scalar written as a one-element array, `[3.54]`, is read as the scalar it
stands for, so it prints as `3.54` rather than with its brackets and a
numeric format applies to it. And when a stage merges several input files
that disagree about a key, the stage stops: taking whichever file was read
last would put a number in the paper that nobody could trace.

The questions commands are `\ckquestion[n]`, `\ckhypothesis[n]`,
`\ckanswer[n]`, `\cknotes[n]`, `\ckevidence[n]`, numbered as in
`calkit list questions`, and `\ckfindings` for every answered question.
A `{name}` placeholder in an answer becomes a marked value in the paper by
the same rendering `calkit list questions` uses, so the two cannot
disagree, and a publication evidence entry with a `label` becomes a
`\ref` to that section.

### Following a component back

Ask about a document and you get its components -- every place project
content lands on the page -- with what to open to change each one:

```sh
calkit describe components paper/main.pdf
```

```text
figure figures/dissipation.pdf
    ok · stage plot-dissipation · scripts/plot.py · p. 4
figure figures/schematic.png
    ok · NO PROVENANCE · p. 2
value results/paper-numbers.json:Improvement
    STALE · stage benchmark · scripts/bench.py · p. 3 · changed-since-build · 2.1 -> 2.4
```

Add `--json` for the same thing machine-readably, `--page 3` for what is
on one page of the PDF, and `--stale` for only what is known to be out of
date or missing. Give it a `--line` (and a `--column`) instead and it
answers about one place in the source, which is what an editor asks when
the cursor lands on a value or a figure:

```sh
calkit describe components paper/main.tex --line 42 --column 18
```

The source, the built PDF, and the sidecar all name the same document, so
it doesn't matter which one a tool has in hand. Without a build there is
no sidecar and no pages, but the question still has an answer: the
generated `.tex` files say which results file and key each command came
from, so the trail holds in a project that has never been built.

### Documents that reach outside their own folder

A document is meant to be a folder somebody can hand over, sync to Overleaf,
or move somewhere else. `\includegraphics{../figures/plot.png}` builds
perfectly well and quietly costs that: the folder is no longer the document.

A component the source names from outside the document's folder is reported
as such, in the listing and as a warning in the editor. The fix is a
`map-paths` stage copying it in, after which the document references it from
beside itself:

```yaml
paper-figures:
  kind: map-paths
  paths:
    - kind: file-to-file
      src: figures/plot.png
      dest: paper/figures/plot.png
```

Only a file the source points at. A value reaches the page through a
generated `.tex` inside the folder, so where its results file sits says
nothing about whether the document is self-contained.

### Components with nothing behind them

Being current is not the only thing worth knowing about a component. The
gap this page opens with -- a file that arrived some other way and had its
origin written down nowhere -- reaches the page like anything else, and
looks exactly like a figure the pipeline made. Every component carries
where its source file came from:

- **`pipeline`** -- a stage produces it, so the command, the inputs and
  the environment are already recorded. This is the only one that is
  checked rather than claimed.
- **`imported`** -- declared with `imported_from`, so a reader can go and
  fetch the original.
- **`attested`** -- declared with `created_by`, so somebody answers for it.
- **`undeclared`** -- nothing makes it, nobody claims it, and it is
  recorded as coming from nowhere. Shown as `NO PROVENANCE`.

An undeclared component is not stale and running the pipeline will not
help; it needs a line in `calkit.yaml` saying where it came from, which is
what the rest of this page is about. Flagging it here is the point: a
schematic dropped into a paper is the one thing on the page no automated
check can catch, because there is nothing to check.

A question block reads as `project`, since its words are the project's
own and there is no outside source to account for.

### Ways to be out of date

A component can be out of date in more than one way, and the ways are
unrelated. The distinction matters because the fix differs:

- **`stage-out-of-date`** -- the pipeline would rerun the stage that
  produces it. The artifact itself is behind; rebuilding the document
  first would only typeset the old one. Run the stage.
- **`changed-since-build`** -- the project has moved on since the document
  was built. The stage may be perfectly current; it is the PDF in front of
  you that is showing a number or a figure the project no longer produces.
  Rebuild the document.
- **`answer-stale`** -- for a `\ckfindings` or `\ckanswer` block, the
  evidence behind the answer changed after the answer was written, which
  is what [`calkit check questions`](questions.md) reports. Reread the
  answer. Whether it still holds is yours to say.

Values are compared value to value rather than by file hash: a results
file changing in a key the document never cites says nothing about the
page. The comparison uses the raw value, not the typeset text, so
`{ratio:.1f}` and `{ratio}` in the same document don't disagree with each
other.

The stage check is the slow part, since it asks the pipeline for its
status. Pass `--no-stage-check` to skip it -- drift between the document
and the project is still reported -- and note that a component nothing
could be checked about reads as `unknown`, never as current.

### While writing

In the VS Code extension, the same readings are reported as diagnostics, so
they reach the Problems panel and get counted: an error for content the
project no longer has, and a warning both for content out of date and for
content nothing accounts for. This is what a hover and a lens cannot do ---
both need you to already be looking at the line. A number that moved on page
nine is worth knowing about before you go looking for it.

Questions are reported there too, on the line in `calkit.yaml` that declares
them, from [`calkit check questions`](questions.md). A placeholder that fills
from nothing, or evidence that has moved since the answer was written, is
about the question rather than the paper that typesets it, so that is where it
is flagged. What is reported is what changed, not whether the answer is still
right: that is a question about the sentence, and reading it is the point of
being told. A question nobody has answered yet is work outstanding rather than
a fault, and is left alone.

### Reading a built document

The same answer follows the PDF into the hub. Open a publication and the
viewer's toolbar carries a **components** panel, which lists what the page
in view took from the project --- the value or figure, whether it is
current, and a link to the stage behind it --- so the question a paragraph
raises is answered beside the paragraph rather than in a table above the
document. Anything out of date elsewhere in the document is counted on the
panel's button, and the panel offers to go to the next page carrying it,
so a reader with no reason to open the panel is still told there is
something to look at.

The panel reads the same `<document>.provenance.json` as everything else
on this page, so it is only there for a document built with `provenance`
turned on; without a record there are no pages to attribute anything to,
and the panel says so rather than showing an empty list.
