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
This evidence references artifacts created by the project pipeline,
which can be seen in its declared outputs.
This allows us to trace all the way back to the primary
artifacts, e.g., raw data and code, to verify with zero ambiguity
(so long as the pipeline is not stale).
This also ties everything together and gives a structured summary
of the project's findings.

## Evidence kinds

- `figure`, `table`, and `publication` point at an artifact by path.
- `result` points at a whole results file: a set of values, a table, a
  map, whatever a stage wrote.
- `value` points at one value inside a JSON or YAML results file, by
  `key`, and can be templated into the question's text under its `name`
  (which defaults to the key).

A `result` entry with a `key` is the older way of writing a `value` entry.
It still works and is read the same way, but `calkit check questions`
reports how many are left, and new entries should use `kind: value`.

Evidence should be something the project accounts for: produced by a
pipeline stage, or declared under `figures`, `datasets`, or `publications`
with `imported_from` or `created_by`.
An entry that is neither is reported as `unattributed`, which is advice
rather than a failure---the answer may be fine, but nothing says where the
thing it rests on came from.

Keys are looked up literally at the top level first, then split on dots
and walked into nested objects, with integers indexing lists,
so `results.case-a.score` reaches into structured output.

## Numbers are read, not retyped

The value behind a `value` entry is never copied into `calkit.yaml`.
The pipeline owns it, and the question only points at it.
To quote it, put a placeholder in the `answer`, `hypothesis`, `notes`, or
an evidence `explanation`, using Python format syntax:

```yaml
answer: The closure cuts the error by about {improvement:.1f}x.
```

`calkit list questions` renders placeholders from the results files
(`--raw` shows the text as written), so a number in an answer is always
the one the pipeline produced.
A placeholder that names no evidence, or a format that its value cannot
satisfy, is an error in `calkit check questions`.

Braces are Python's format syntax, so a brace meant to stay in the text
has to be doubled: write `\frac{{a}}{{b}}`, not `\frac{a}{b}`.

## Keeping answers honest

An answer is a claim about the evidence as it was when the answer was
last edited, and Git already records when that was: the commit at which
the question's entry in `calkit.yaml` last changed.
`calkit check questions` finds that commit and asks whether any of the
question's evidence has changed since, in Git history for Git-tracked
outputs and through the hash in `dvc.lock` for DVC-tracked ones.
If it has, the question is reported as `stale`: the answer was written
against evidence that no longer exists, and someone has to read it again.

```sh
calkit check questions            # exits with an error if any answer is stale or broken
calkit check questions --json     # for tools
```

The same report appears in the Questions section of
`calkit status -c questions`. It is asked for rather than shown by default:
judging whether an answer still matches its evidence means reading
`calkit.yaml`'s history, which nothing else in `calkit status` needs.

A stale question is not fixed by re-running anything; it is fixed by
reading the rendered answer against the new evidence.
If it still holds, say so by editing the question. Any edit to it counts:
the check anchors on the commit where the question last changed, so
re-reading the answer and then touching it is what marks it current.

This is the weakest part of the mechanism, and it is being replaced. See
[issue #1606](https://github.com/calkit/calkit/issues/1606) for the design:
a review record that says what was confirmed, by whom, rather than a commit
that says something changed.

## Pointing at the publication

The reasoning behind an answer belongs in the publication, not in
`calkit.yaml`.
A `publication` evidence entry can say where: `section` is for the reader,
e.g., `"3.2"` or `Results`, and `label` is an anchor in the source, e.g.,
a LaTeX `\label{sec:scaling}`.
`calkit check questions` verifies the label still exists in the source of
the LaTeX stage that builds the publication, so the reference cannot rot
when the document is reorganized.
This keeps answers short: state the claim, let `value` evidence carry the
numbers, and let the publication carry the argument.

A question that is still open should have no `answer` at all;
`notes` is the place to say why it is open and what would settle it,
since notes make no claim and so need no evidence.

<!-- prettier-ignore -->
!!! note
    These records are designed to be compatible in spirit with the
    [ASTRA](https://github.com/lightcone-research/astra) analysis
    specification, whose evidence entries likewise cite an analysis
    artifact by identifier, note the commit it came from, and carry a
    selector locating the claim within a document.
