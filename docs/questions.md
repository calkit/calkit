# Questions, hypotheses, answers, and evidence

The whole purpose of collecting and analyzing data, creating artifacts,
calculating numbers is to produce evidence to support answers to questions.
Calkit allows connecting these all together through the metadata in
`calkit.yaml`.
For example:

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
