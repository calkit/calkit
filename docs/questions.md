# Questions, hypotheses, answers, and evidence

The whole purpose of collecting and analyzing data, creating artifacts,
calculating numbers is to produce evidence to support answers to questions.
Calkit allows connecting these all together through the metadata in
`calkit.yaml`.

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
```

Early on in the project, we may start with a question,
then add a hypothesis, then an answer with some evidence.
This evidence references artifacts created by the project pipeline,
which can be seen in its declared outputs.
This allows us to trace back all the way back to the primary
artifacts, e.g., raw data and code, to verify with zero ambiguity
(so long as the pipeline is not stale).
