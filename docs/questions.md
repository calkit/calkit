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
    answer: $y$ increases quadratically with $x$, not linearly.
    evidence:
      - kind: figure
        path: figures/x-vs-y.png
      - kind: result
        path: results/summary.json
        key: r_squared_quadratic
        value: 0.987
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

## Keeping answers honest

An answer is a claim about what the pipeline produced when the answer was
written.
The pipeline keeps the evidence current, but nothing keeps the prose
current: re-run a stage after fixing a bug or changing an environment,
and a number the answer relies on can change while the sentence stays
the same.
Calkit closes that gap deterministically.

A `result` evidence entry with a `key` points at one value inside a JSON or
YAML results file.
Recording the `value` the answer was written against, as in the example
above, lets Calkit compare it with what the file holds now:

```sh
calkit check questions
```

reports every answered question whose recorded values no longer match
(`stale`), whose evidence cannot be found or whose key does not resolve
(`error`), or whose keyed evidence has no recorded value yet
(`unrecorded`), and exits with an error if any answer is stale or broken.
The same report appears in the Questions section of `calkit status`,
and `--json` gives it in a form other tools can read.

Numbers are compared with a relative tolerance of `1e-6`, which ignores
floating-point noise from, e.g., a change of BLAS library, and nothing
else.
An entry can loosen that with its own `tolerance`, e.g., `0.01` for a
quantity the answer only quotes to two figures.
Strings, booleans, lists, and objects must match exactly.

To record values after writing or re-reading an answer:

```sh
calkit update questions -q 3        # question 3, as numbered by 'calkit list questions'
calkit update questions --all       # every answered question
```

Recording is the act of declaring an answer current, so it is done per
question deliberately rather than for everything by habit.
A stale question is not fixed by re-recording; it is fixed by reading the
answer against the new values, changing it if it no longer holds, and
_then_ recording.
The `check-questions` [agent skill](ai-tools.md) walks through exactly
that, using the check's report to know which questions to read.

Keys are looked up literally at the top level first, then split on dots
and walked into nested objects, with integers indexing lists,
so `results.case-a.score` reaches into structured output.

## Pointing at the publication

The reasoning behind an answer belongs in the publication, not in
`calkit.yaml`.
A `publication` evidence entry can say where: `section` is for the reader,
e.g., `"3.2"` or `Results`, and `label` is an anchor in the source, e.g.,
a LaTeX `\label{sec:scaling}`.
`calkit check questions` verifies the label still exists in the source of
the LaTeX stage that builds the publication, so the reference cannot rot
when the document is reorganized.
This keeps answers short: state the claim, let keyed results carry the
numbers, and let the publication carry the argument.

<!-- prettier-ignore -->
!!! note
    The evidence records here are designed to be compatible in spirit with
    the [ASTRA](https://github.com/lightcone-research/astra) analysis
    specification, whose evidence entries likewise carry a snapshot of
    the artifact they cite and a selector locating the claim within a
    document.
