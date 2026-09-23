# Quickstart

<!-- prettier-ignore -->
!!! note
    `ck` is an abbreviated alias for the `calkit` executable.
    All `calkit` commands can be run as `ck` instead, e.g., `ck save -am "..."`.

Research projects exist to answer questions.
We collect data,
analyze it,
make figures and compute numbers,
and then write about what we found.
In this quickstart we'll create a small project shaped this way,
with a question, the data to answer it,
a figure and a number computed from that data,
and a paper that includes both.
The findings don't matter here.
What matters is that when something upstream changes,
Calkit will tell you what's out of date downstream,
and one command will bring everything back up to date.

## Create a project

```sh
calkit new project phd \
    --title "PhD research" \
    --template calkit/example-basic
```

This creates a project from a template,
so we have something to run right away.

The title can be changed later, but the name is more difficult to change,
so it's a good idea to keep the name general.
A single project can hold multiple investigations,
e.g., a grad student might use one project for their entire PhD,
with a question and a paper for each study.

Add the `--hub` flag to also create the project on
[a Calkit hub](hub/index.md) for backup and sharing.
This requires an account,
but can be set up later,
so we'll leave it off for now.

## Look at the question

Open up `calkit.yaml`.
Near the top you'll see the project's research question:

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

The answer lists the evidence that supports it,
and `{r2}` is read from one of those files rather than typed in by hand.
We can see the rendered answer with:

```sh
calkit list questions
```

```
1. question: How does the system respond to increasing $x$?
    hypothesis: The value of $y$ increases linearly with $x$.
    answer: $y$ increases quadratically with $x$, not linearly ($R^2 = 0.985$ for the quadratic fit).
    evidence:
      - kind: figure
        path: figures/x-vs-y.png
      - kind: value
        path: results/summary.json
        key: r_squared_quadratic
        name: r2
```

The evidence files are produced by the pipeline,
so if the data changes,
the figure and number become stale,
and so does the answer that depends on them.

We recommend writing questions down first in your own projects as well.
It makes clear what evidence you need to produce,
and everything else in the project exists to produce it.

## Run the pipeline

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

The pipeline has five stages:
collect the data,
analyze it to produce a figure and a results file,
copy the figure into the paper folder,
convert the results to LaTeX,
and compile the paper.
You should now have a `paper/main.pdf` file.

Calkit created the Python environment and pulled the LaTeX Docker image
automatically.
If something it needs isn't installed, e.g., Docker,
it will show you the command to install it and offer to run it:

```
App 'docker' is not installed.
  brew install --cask docker
Run this to install 'docker'? [Y/n]
```

You can also run this check on its own with `calkit check reqs`.

## Make a change

Next, make an edit to `scripts/analyze.py` and check the project status:

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

The figure and results file are stale because the script that produces
them changed,
and the answer is stale because its evidence is.
We can see more detail with:

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

So, editing the script made the project's answer out of date,
and Calkit told us so without us needing to remember to check.
To bring everything back up to date, run the pipeline again:

```sh
calkit run
```

Only the stages affected by the change will rerun.
The paper is rebuilt with the new figure and numbers,
and the answer is backed by current evidence again.
This edit-and-run loop is the main way of working in a Calkit project,
and it keeps the paper in sync with the analysis.

## Save the project

```sh
calkit save -am "Tweak the fit"
```

This adds and commits all changes in one step,
putting code in Git and data and outputs in DVC,
so you don't need to decide which goes where.

At this point the project only exists on your machine,
so there's nowhere to push to.
Calkit will offer to set that up:

```
This project isn't connected to a hub, so there's nowhere to push its
code and data.
Connect it now? [Y/n]
```

Answering yes creates the project on a [hub](hub/index.md),
which backs it up,
stores data and outputs that are too big for Git,
and makes it available to collaborators.
After that, `calkit save` will push everything to the right place,
and a collaborator can clone the project and reproduce it with
`calkit run`.

Answering no is fine too.
The commit has already been made,
and the project can be connected later with `calkit update hub`.

## Next steps

Add your own data and a script to process it with
[`calkit xr`](pipeline/index.md),
which executes a command and records it as a pipeline stage.
To use Calkit with an existing project rather than a template, see
[the tutorial on existing projects](tutorials/existing-project.md).

As the research goes on, add more questions.
Each entry in `questions` lists its own evidence,
so a new study can be a new question and the stages that answer it,
rather than a new project.

## With an AI coding agent

Simply tell the [AI agent](ai-tools.md):

> Turn this folder into a Calkit project

or

> Create me a new Calkit project for investigating...
