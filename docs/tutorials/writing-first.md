# Writing first: let the paper drive the project

Most research projects are built the other way round. You collect data,
write scripts, make figures, and at the end you sit down to write the paper
and find out what you actually have. By then the analysis has decided what
the paper can say.

This tutorial goes the other way. You write the paper first, leaving holes
where the numbers and figures go, and an AI agent builds the project that
fills them. Your attention stays on the argument, which is the part nobody
can do for you. The agent does the scaffolding, and Calkit keeps the
scaffolding honest: every number on the page comes from a pipeline stage,
and anything nobody has measured yet stays visibly outstanding rather than
quietly guessed.

## What you need

- A Calkit project with a LaTeX publication. If you don't have one, see
  [adding a LaTeX publication](adding-latex-pub-docker.md).
- An AI agent with the Calkit skills installed --- Claude Code, OpenAI
  Codex, OpenCode, or similar. See [using AI tools](../ai-tools.md).

## Step 1: Write the paper with holes in it

Write the sentence you want to be true, and mark what would make it true:

```latex
\section{Results}

% TODO: report the mean speedup over the baseline across all cases, and
% plot the distribution
Our method is faster than the baseline by \todo{}, and the improvement is
consistent across cases (Figure~\ref{fig:speedup}).

% TODO: we haven't measured power draw yet -- needs a bench session
At equal accuracy, the method draws \todo{} less power.
```

Two different holes. The first one the agent can fill from data the project
already has. The second one nothing can fill, because the measurement
hasn't been made --- and that difference is exactly what you want surfaced
rather than smoothed over.

Write the TODO in the words you would use to brief a colleague. "Report the
mean speedup over the baseline" is a brief; "add speedup" is not.

## Step 2: Ask the agent to close them

```
/calkit:build-paper-pipeline
```

The agent reads the manuscript, collects the TODOs, and tells you what it
thinks each one is asking for **before** it builds anything. Correct it
here --- a misread TODO costs a whole stage.

Then, for each one it can close, it:

1. adds a pipeline stage that computes the value and writes it to a results
   file;
2. adds a `json-to-latex` stage that turns that file into LaTeX commands;
3. replaces the hole with `\result[Speedup]`, so the number is read from
   the results file every build;
4. adds the question the sentence answers to `calkit.yaml`, with the
   answer's numbers as `{placeholders}` over `value` evidence.

The rule the skill works under is that it never types a computed number
into your manuscript. A number typed into a `.tex` file is a number nobody
can check, and it goes stale the moment a stage reruns. Everything reaches
the page through the pipeline.

## Step 3: The hole nobody can fill yet

The power-draw TODO has no data behind it. The agent won't invent a number;
it declares the measurement as a
[procedure](procedures.md) and puts it in the pipeline:

```yaml
procedures:
  measure-power:
    title: Measure power draw at equal accuracy
    description: Bench session with the meter on the supply rail.
    steps:
      - summary: Set the model to the accuracy target from results/tuning.json
      - summary: Record the steady-state power draw
        inputs:
          power_w:
            units: W
            dtype: float

pipeline:
  stages:
    measure-power:
      kind: procedure
      procedure_name: measure-power
```

Now `calkit run` walks you through the bench session when you get to it and
logs what you entered, and everything downstream waits on it. The paper
still has a hole, but the project knows about the hole, which is the
difference between an open question and an oversight.

## Step 4: Read what you got

```sh
calkit run
calkit check repro
calkit check questions
calkit describe components paper/main.tex
```

`check repro` reads the manuscript back and reports any number in it that
the pipeline already computes --- which catches a hole closed by typing
rather than by building. Those are the one thing it fails on, so it is
worth running in CI. It summarizes; run `calkit check repro -c retyped`
to see them, and `-c numbers` for the weaker list of result-like numbers
with nothing recorded behind them, most of which will not be results and
none of which fail the check.
`check questions` tells you whether the evidence behind each answer is
still there and still says what it said when the answer was written.
Whether the answer follows from it is yours to judge, which is what being
told to re-read one is for. `describe components` lists every value and figure the document
takes from the project, with the stage behind it and whether it is current
--- see [provenance](../provenance.md).

Then read the paper. This is the part that matters: the agent has made the
sentences true, but only you can decide whether they are worth saying, and
whether the result is the one you expected. A speedup of 1.02x is a
correctly computed number and probably a different paper.

## Why this order works

Writing first forces the argument to come before the analysis, which is the
order a reader experiences it in and the order that catches a weak claim
early. It also gives the agent something unambiguous to work from: a
sentence you want to be true is a much better specification than "analyze
the data."

And it keeps the audit trail intact in the direction that matters. Every
claim in the paper points at a question, every question points at evidence,
and every piece of evidence points at the stage that produced it. When a
reviewer asks where a number came from, the answer is a path through the
project rather than a memory.

## What to watch for

- **Check the TODO list the agent reads back.** Most bad outcomes start
  with a misread brief.
- **Don't let a hole get closed with a plausible number.** If the agent
  reports a TODO as blocked, that is the system working. Adding the
  measurement is your call, not its.
- **Read the stage, not just the number.** The agent writing a script that
  computes a mean is easy to check and worth checking.
- **The pipeline still owns the outputs.** An agent that runs a script and
  commits a figure has broken provenance even if the figure is right. See
  [the golden rule](../ai-tools.md#the-golden-rule-agents-create-code-the-pipeline-creates-outputs).
