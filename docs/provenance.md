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

## Disclosing generative AI

If a generative AI tool helped produce a figure or a `misc` artifact, say so:

```yaml
figures:
  - path: figures/schematic.png
    created_by:
      email: me@myorg.edu
    generated_with_ai: Claude Opus 5 # Can be a list too
```

<!-- prettier-ignore -->
!!! note
    `generated_with_ai` has to name people in `created_by` as well. A model
    can't answer for a file. A reader deciding whether the use was
    appropriate needs to know who decided that it was, and disclosure that
    names no one leaves that question open.

The point isn't that generative AI is disqualifying. It's that whether its
use was appropriate depends entirely on what the file is, and a reader can
only make that call if they're told. A schematic laid out by a model is
usually unremarkable.

### Why datasets and publications can't carry this

`generated_with_ai` is deliberately available only on figures and `misc`.
Datasets and publications have no such field, and that's a statement rather
than an oversight.

A dataset is either measured, or obtained from somewhere, or computed by the
pipeline from things that were. Data a model produced is none of those: it
has no measurement behind it and no derivation to check, so a project
reporting it as a dataset would be reporting a finding that nothing
supports. If a model generated data as part of the work -- synthetic
training data, say -- then a pipeline stage made it, and the stage is the
honest record of that.

A publication is the argument the project is making. If it wasn't written by
the people whose names are on it, the problem isn't a missing disclosure
field.

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
