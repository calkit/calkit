# Questions, hypotheses, answers, and evidence

The whole purpose of collecting and analyzing data, creating artifacts,
and calculating numbers is to produce evidence to support answers to
questions.
Calkit connects these together through the metadata in `calkit.yaml`.

Take this example:

```yaml
questions:
  - question: How does the system respond to increasing $x$?
    hypothesis: The value of $y$ increases linearly with $x$.
    answer: $y$ increases quadratically with $x$, not linearly
      ($R^2 = {r2:.3f}$ for the quadratic fit).
    evidence:
      - kind: figure
        path: figures/x-vs-y.png
      - kind: value
        path: results/summary.json
        key: r_squared_quadratic
        name: r2
      - kind: publication
        path: paper/paper.pdf
        section: "3.2"
        label: sec:scaling
```

Early on in the project, we may start with a question,
then add a hypothesis, then an answer with some evidence.
The evidence references artifacts created by the project pipeline,
so each answer can be traced back to the raw data and code behind it,
as long as the pipeline is up to date.
Together, the questions form a structured summary of the project's
findings.

## Evidence

There are a few kinds of evidence:

- `figure`, `table`, and `publication` refer to an artifact by path.
- `document` refers to a written document by path, e.g., a Markdown
  write-up, without declaring it as a publication.
- `result` refers to a whole results file.
- `value` refers to one value inside a JSON or YAML results file,
  found by its `key`.

A `result` entry with a `key` is the older way of writing a `value` entry.
It still works, but new entries should use `kind: value`.

Evidence should come from somewhere the project records.
A `value` must be in a file produced by a pipeline stage, or declared
under `datasets` with `imported_from` if another project computed it.
Otherwise it's a number someone typed in, which can't be traced or kept
up to date, so `calkit check questions` reports it as an error.
Other kinds of evidence can also be declared under `figures`, `datasets`,
or `publications` with `created_by`, e.g., for a hand-drawn schematic.
Evidence with no record at all is reported as `unattributed`, which is a
warning.

## Reading values from results

A `value` entry reads one value from a results file and gives it a name:

```yaml
evidence:
  - kind: value
    path: results/scan.json
    key: features.0.p-family-wise-all
    name: p
  - kind: value
    path: results/scan.json
    key: leading-feature
    name: leader
```

The key is looked up as written at the top level of the file first.
If it isn't there, it's split on dots and used to walk into nested
objects, with integers indexing into lists,
so `features.0.p-family-wise-all` reads a field of the first feature.

The `name` defaults to the key, so it can be left out when the key is
already a good name.
Names must be unique within a question.

## Putting numbers in the text

The value behind a `value` entry is never copied into `calkit.yaml`.
To use it in the `answer`, `hypothesis`, `notes`, or an evidence
`explanation`, write its name in braces, optionally with a Python format
spec:

```yaml
answer: The closure cuts the error by about {improvement:.1f}x.
```

`calkit list questions` shows the text with these placeholders filled in
from the results files, so the number always matches what the pipeline
produced.
Use `--raw` to see the text as written.

Braces are Python's format syntax, so a brace meant to stay in the text
has to be doubled, e.g., `\frac{{a}}{{b}}`.

## Conditional answers

Sometimes the wording of an answer depends on a value, e.g., whether a
result is significant.
In that case, the answer can be written with `if`, `elif`, and `else`
branches:

```yaml
answer:
  if p < 0.05: "{leader} predicts where staging pays (rho {rho:+.2f})."
  elif p < 0.1: There is weak evidence that {leader} predicts it.
  else: No measured feature predicts where staging pays.
```

The branches are tried in order, and the first whose condition holds is
used.
Placeholders in it are then filled in as usual.
Quote a branch that starts with a brace, since YAML would otherwise read
it as a mapping.

Conditions use the names of `value` evidence.
They can compare values, including chained comparisons like
`0.05 <= p < 0.1`, combine them with `and`, `or`, and `not`, and do
arithmetic like `n / 2 > 8`.
Function calls and attribute access aren't allowed.
Since conditions are Python expressions, the names in them must be valid
Python identifiers.
For a key like `paired-gain`, set `name` to something like `gain`.

Writing the branches before running the pipeline makes the threshold part
of the claim.
When the pipeline runs again, the answer updates to match the new result.
`calkit check questions` checks every branch, so a mistake in one that
doesn't currently apply still shows up.

## Checking questions

```sh
calkit check questions         # Exits with an error if something is wrong
calkit check questions --json  # For tools
```

Each answered question is reported with one of these statuses:

- `ok`: the evidence exists and is current.
- `stale`: a stage that produces some of the evidence is out of date, so
  the pipeline needs to be run.
- `frozen`: some of the evidence comes from a frozen stage.
  Cite a `git_ref` on the evidence to pin the version the answer is
  based on.
- `missing`: some of the evidence doesn't exist.
- `error`: a reference is broken, e.g., a key that isn't in its file,
  a placeholder or condition naming no evidence, a publication label that
  can't be found, or a value no stage computes.

`stale`, `missing`, and `error` fail the check.

The check also notes any evidence that has changed since the question was
last edited in `calkit.yaml`, according to Git history, or `dvc.lock` for
DVC-tracked files.
This doesn't fail the check, since the answer may still be correct,
but it's a sign the answer should be read again.
If it still holds, edit the question, e.g., by adding to its `notes`,
to mark it as reviewed.
This mechanism is being replaced with an explicit review record; see
[issue #1606](https://github.com/calkit/calkit/issues/1606).

Checking questions is separate from `calkit status` because it needs to
read the history of `calkit.yaml`.

## Pointing at the publication

The reasoning behind an answer belongs in the publication.
A `publication` evidence entry can point to it: `section` is for the
reader, e.g., `"3.2"` or `Results`, and `label` is a LaTeX label in the
source, e.g., `sec:scaling`.
`calkit check questions` checks that the label still exists in the source
of the LaTeX stage that builds the publication.
This keeps answers short, with the numbers coming from `value` evidence
and the argument in the publication.

When the reasoning lives in a document that isn't a publication, e.g.,
notes kept in `docs/`, cite it with `kind: document` and a `section`.
A document has to be built by a pipeline stage, usually a Markdown stage
that injects its numbers from the results, so they're checked like any
other evidence and reported stale when their stage is.
Like a value no stage computes, a document written by hand is an error,
since nothing checks what it says.

```yaml
evidence:
  - kind: document
    path: docs/notes.md
    section: Method
```

A question that is still open should have no `answer`.
Use `notes` to say why it's open and what would settle it.

<!-- prettier-ignore -->
!!! note
    These records are designed to be compatible in spirit with the
    [ASTRA](https://github.com/lightcone-research/astra) analysis
    specification, whose evidence entries likewise cite an analysis
    artifact by identifier, note the commit it came from, and carry a
    selector locating the claim within a document.
