# Quickstart

<!-- prettier-ignore -->
!!! note
    `ck` is an abbreviated alias for the `calkit` executable.
    All `calkit` commands can be run as `ck` instead, e.g., `ck save -am "..."`.

This walks through a small but complete project: a question, the data
collected to answer it, a figure and a number computed from that data,
and a paper that shows both.
It takes about a minute, and the point isn't the example's findings.
It's that from here on, changing anything upstream tells you what
downstream is now out of date, and one command brings it all back into
line.

## Create a project

```sh
calkit new project my-research \
    --title "My research" \
    --template calkit/example-basic
```

This gives you a working project rather than an empty one, so there is
something to run before there is something to write.

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
    answer: $y$ increases quadratically with $x$, not linearly.
    evidence:
      - kind: figure
        path: figures/x-vs-y.png
      - kind: result
        path: results/summary.json
        key: r_squared_quadratic
```

The answer names the files that back it up.
Those files are produced by the pipeline, so the claim and the evidence
for it can't drift apart: if the data changes, the figure and the number
are stale, and so is the answer that rests on them.

This is the part worth copying into your own work.
Writing the question down first makes it obvious what evidence you owe.

## Run it

```sh
cd my-research
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
them changed.
Nothing else is, because nothing else depends on it yet in a way that
has been invalidated.

```sh
calkit run
```

Only what needed to run runs again, and the paper is rebuilt with the
new figure and the new numbers in it.
That loop, edit and run, is the whole working rhythm.
The document is never out of step with the analysis, because it can't
be.

## Save it

```sh
calkit save -am "Tweak the fit"
```

This stages, commits, and pushes in one step, sending code to Git and
data and outputs to DVC storage, so you don't have to decide which goes
where.

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
