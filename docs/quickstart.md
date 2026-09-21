# Quickstart

<!-- prettier-ignore -->
!!! note
    `ck` is an abbreviated alias for the `calkit` executable.
    All `calkit` commands can be run as `ck` instead, e.g., `ck save -am "..."`.

Calkit is a system for answering questions with calculations, then
writing about them.
This walks through a small but complete project shaped that way: a
question, the data collected to answer it, a figure and a number computed
from that data, and a paper that shows both.
It takes about a minute, and the point isn't the example's findings.
It's that from here on, changing anything upstream tells you what
downstream is now out of date, and one command brings it all back into
line.

## Create a project

```sh
calkit new project phd \
    --title "PhD research" \
    --template calkit/example-basic
```

This gives you a working project rather than an empty one, so there is
something to run before there is something to write.

The title is easy to change later but the name isn't, so keep the name
general.
A project can hold more than one investigation, so a single one for a
thesis, with a question and a paper per study in it, is a perfectly good
way to work.

Add `--hub` to also create it on [a Calkit hub](hub/index.md), which is
how projects get backed up and shared.
It needs an account, and can be set up later, so leave it off for now if
you just want to see the thing work.

## Look at the question

Open `calkit.yaml`.
Near the top is what this project is for:

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
```

The answer names the files that back it up, and `{r2}` is read out of one
of them rather than typed in:

```sh
calkit list questions
```

```
1. question: How does the system respond to increasing $x$?
    hypothesis: The value of $y$ increases linearly with $x$.
    answer: $y$ increases quadratically with $x$, not linearly
      ($R^2 = 0.985$ for the quadratic fit).
    evidence:
      - kind: figure
        path: figures/x-vs-y.png
      - kind: value
        path: results/summary.json
        key: r_squared_quadratic
        name: r2
```

Those files are produced by the pipeline, so the claim and the evidence
for it can't drift apart: if the data changes, the figure and the number
are stale, and so is the answer that rests on them.

This is the part worth copying into your own work.
Writing the question down first makes it obvious what evidence you owe,
and the rest of the project exists to produce it.

## Run it

```sh
cd phd
calkit run
```

```
💻 Getting system information
🔗 Checking system-level requirements
📦 Checking environments
🔀 Compiling DVC pipeline
Running stage 'collect-data':
Running stage 'analyze':
Running stage 'figs-to-paper':
Running stage 'results-to-tex':
Running stage 'build-paper':
Pipeline completed successfully ✅
```

Five stages ran: data was collected, analyzed into a figure and a
results file, the figure was copied into the paper's folder, the results
were turned into LaTeX, and the paper was compiled.
You now have `paper/main.pdf`.

Calkit created the Python environment and pulled the TeX image itself.
If something it needs isn't installed, Docker most often, it says so,
shows you the command, and offers to run it:

```
App 'docker' is not installed.
  brew install --cask docker
Run this to install 'docker'? [Y/n]
```

You can ask for that check at any time with `calkit check reqs`.

## Change something

Edit `scripts/analyze.py`, then ask what that affected:

```sh
calkit status
```

```
--------------------------- Questions ----------------------------
1 question, 1 with stale evidence
Run 'calkit check questions' for detail.

---------------------------- Pipeline ----------------------------
Stale stages:
        analyze:
          stale outputs:
            figures/x-vs-y.png
            results/summary.json
          modified inputs:
            scripts/analyze.py
```

The figure and the results file are stale because the script that makes
them changed, and the answer is stale because it rests on them:

```sh
calkit check questions
```

```
1. [stale] How does the system respond to increasing $x$?
     figure figures/x-vs-y.png [stale] -- stage 'analyze' is out of date; run the pipeline
     value results/summary.json:r_squared_quadratic [stale] -- stage 'analyze' is out of date; run the pipeline

Questions answered: 1/1
Answers backed by current evidence: 0/1 ❌
```

That's the whole idea: editing a script put the project's answer in
doubt, and it said so, without anyone remembering to check.

```sh
calkit run
```

Only what needed to run runs again, the paper is rebuilt with the new
figure and the new numbers in it, and the answer is backed by current
evidence again.
That loop, edit and run, is the whole working rhythm.
The document is never out of step with the analysis, because it can't
be.

## Save it

```sh
calkit save -am "Tweak the fit"
```

This stages and commits in one step, sending code to Git and data and
outputs to DVC storage, so you don't have to decide which goes where.

The project so far is on your machine and nowhere else, so there's
nothing to push to yet, and Calkit offers to fix that:

```
This project isn't connected to a hub, so there's nowhere to push its
code and data.
Connect it now? [Y/n]
```

Saying yes creates the project on a [hub](hub/index.md), which backs it
up, holds the data and outputs that are too big for Git, and is how
other people get to it.
From then on `calkit save` pushes everything where it belongs, and a
collaborator can clone the project and run `calkit run` to reproduce it.

Saying no is fine too: the commit is already made, and
`calkit update hub` connects the project whenever you want.

## Where to go next

Add your own data and a script to process it with
[`calkit xr`](pipeline/index.md), which runs a command and records it as
a pipeline stage.
To bring an existing project into Calkit instead of starting from a
template, see
[the tutorial on existing projects](tutorials/existing-project.md).

A project grows by adding questions.
`questions` is a list, and each entry names its own evidence, so a
second study is another entry and the stages that answer it rather than
a second project.

## With an AI coding agent

Simply tell the [AI agent](ai-tools.md):

> Turn this folder into a Calkit project

or

> Create me a new Calkit project for investigating...
