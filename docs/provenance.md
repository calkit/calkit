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
    collected_by:
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

Both `collected_by` and `created_by` take a list, since work usually has
more than one person behind it, and each entry needs an email or an ORCID.
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
`collected_by` is a reason to ask exactly what the tool did, and to expect a
specific answer.

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
