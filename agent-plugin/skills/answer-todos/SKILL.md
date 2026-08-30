---
name: answer-todos
description: Build the analysis a paper's TODO comments ask for, as pipeline
  stages, and keep the project's questions and answers matching the paper.
  Use when the user invokes `/calkit:answer-todos`, leaves TODO comments in a
  manuscript for an agent to address, or asks to work backwards from the
  writing to the project behind it.
---

# Answer the paper's TODOs

The writing is the human's job. Deciding what the paper claims, and whether
a claim is worth making, is what nobody else can do for them. Everything
under a claim -- the stage that computes the number, the figure that shows
it, the question it answers -- is scaffolding, and scaffolding is what this
skill builds.

The user writes a sentence with a hole in it and marks the hole:

```latex
% TODO: report the mean speedup over the baseline, and plot the
% distribution across cases
Our method is faster than the baseline by \todo{}.
```

You fill the hole by building the project behind it, not by writing a
number into the sentence.

## The rule that makes this safe

**Never type a computed value into the manuscript.** A number you typed is
a number nobody can check, and it goes stale the moment a stage reruns. The
number reaches the page through the pipeline: a stage computes it and
writes it to a results file, a `json-to-latex` stage turns that file into
LaTeX commands, and the manuscript says `\result[Speedup]`. The same
applies to figures (`\ckfigure{...}` over a pipeline output) and to the
answers in `calkit.yaml` (`{name}` placeholders over `value` evidence).

If you find yourself about to write `2.4x` into a `.tex` file, stop: that
is the hole, not the fix. The `check-reproducibility` skill covers finding
and fixing a typed literal that is already in a manuscript; this one is
about not putting one there.

See the `conventions` skill for `calkit.yaml` structure and stage kinds,
`add-pipeline-stage` for adding one stage, and `create-pipeline` for
building a pipeline from scratch.

## Procedure

1. **Read the manuscript and collect the TODOs.** Look for `% TODO`,
   `\todo{}`, `\TODO`, and prose that asserts something with no number or
   figure behind it. Quote each one back to the user with what you think it
   is asking for, grouped into: needs a computation, needs a figure, needs
   data the project does not have, and needs a decision only they can make.
   Do not start building until they have confirmed the list --- a
   misunderstood TODO costs a whole stage.

2. **Say what is missing before you build.** For each TODO, name the inputs
   it needs. If the project already has them, say which stage produces
   them. If it does not, that TODO is blocked, and the honest answer is to
   say so rather than to invent data. Blocked TODOs come in two kinds:

   - **Data nobody has collected yet.** This is a manual step, not a
     missing script. Add a `procedure` stage (see below) and tell the user
     the pipeline now knows the step is outstanding.
   - **Data that exists somewhere else.** Ask where. Declare it with
     `imported_from` so the provenance chain reaches back past the project.

3. **Build a stage per computation.** One stage, one question. Prefer a
   script over a notebook, since a script diffs cleanly and reruns
   headlessly. Write the results to a JSON file under `results/` with keys
   named the way the paper will refer to them.

4. **Inject, don't copy.** Add a `json-to-latex` stage over the results
   file and reference the values from the manuscript with the generated
   command. Add `\usepackage[provenance]{calkit}` and set `provenance: true`
   on the `latex` stage so every injected value is marked and the build
   writes a provenance record. Replace the TODO with the sentence the user
   wrote, now with `\result[...]` where the hole was.

5. **Make the question match the paper.** A claim in the paper is an answer
   to a question. Add or update the entry under `questions` in
   `calkit.yaml`: the `question` as the paper poses it, the `answer` as the
   paper states it with `{name}` placeholders where numbers go, and
   `evidence` naming the results file and key, the figure, and the
   publication section that carries the argument. Run
   `calkit check questions` and fix what it reports.

6. **Run the pipeline, then check your own work.** Run `calkit run`, then
   `calkit check repro`, which reads the manuscript back and reports any
   number in it that is not traceable to a pipeline output. A finding there
   is a hole you closed by typing rather than by building, so go back to
   step 3 for it. Show the user the rendered sentences
   (`calkit list questions`) and the built document. Never commit a derived
   output yourself, and never edit a results file by hand.

## Data a person has to collect

Some TODOs cannot be closed by any amount of code, because the measurement
has not been made. Do not leave that as a comment in the manuscript, where
nothing tracks it. Declare the procedure and make it a stage, so the
pipeline knows the step is outstanding and everything downstream waits on
it:

```yaml
procedures:
  measure-rig:
    title: Measure the rig
    description: Read the temperature off the display at each setting.
    steps:
      - summary: Turn on the machine
        wait_after_s: 5
      - summary: Record the temperature
        inputs:
          temperature:
            units: C
            dtype: float

pipeline:
  stages:
    collect-data:
      kind: procedure
      procedure_name: measure-rig
    plot-data:
      kind: python-script
      environment: py
      script_path: scripts/plot-data.py
      inputs:
        - from_stage_outputs: collect-data
      outputs:
        - figures/temperature.png
```

`calkit run` walks the person through the steps and logs each one to
`.calkit/procedure-runs/measure-rig/`, which the next stage reads like any
other input. Write the procedure's steps in the words someone at the bench
would need, not in the words a program would; you are writing for a person
holding a thermometer.

## What to hand back

Say what you built, what you did not, and why:

- the stages you added and what each computes;
- the values and figures now injected, and where they land in the text;
- the questions you added or changed, and what `calkit check questions`
  says;
- **every TODO you could not close**, with what is missing. This is the
  most useful part of the report. A TODO left open because the data does
  not exist is a finding; a TODO closed with a plausible-looking number is
  a fabrication.
