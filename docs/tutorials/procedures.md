# Defining and executing procedures

Not everything can be automated... yet.
Sometimes we need to perform manual procedures as part of a research
protocol.
To help make this easier,
it's possible to define and execute procedures with Calkit.
This will allow you to define it ahead of time and not need to waste
time, e.g., during an experiment, figuring out what step you're on.

## Defining

The `Procedure` model in `calkit.models` shows the structure of a procedure.
For example, we might define a procedure with 3 steps like:

```yaml
title: My important procedure
description: This is a manual procedure for setting up the experiment.
steps:
  - summary: Turn on the machine
    wait_after_s: 10
  - summary: Record the temperature
    details: >
      In the upper right hand corner of the screen you will see a temperature
      value. Record this.
    wait_after_s: 5
    inputs:
      temperature:
        units: Degrees C
        dtype: float
  - summary: Turn off the machine
    details: Press the power button.
```

We can save this anywhere, but to follow convention we will save to
`.calkit/procedures/my-important-procedure.yaml`.

In `calkit.yaml`, we can add to the `procedures` object like:

```yaml
procedures:
  my-important-procedure:
    _include: .calkit/procedures/my-important-procedure.yaml
```

Here we use an `_include` key to reference the other file to help keep
`calkit.yaml` easier to read.

## Executing

If we run `calkit runproc my-important-procedure` from the command line,
our procedure will start.

After confirming we've completed the first step,
Calkit is going to wait 30 seconds before asking us to perform the next
step.

## Logging

As we run through the procedure, Calkit will be logging each step
and committing to the Git repo.

These logs will be saved as CSV files with paths like
`.calkit/procedure-runs/{procedure_name}/{start_date_time}.csv`.
The CSV file will have columns indicating what step number was performed,
when it was started, when it was finished, and will have a column
for each input defined, if applicable.

These logs can be read later for further analysis and/or visualization.

## Executing as part of the pipeline

Let's imagine we want to execute a procedure to collect some data
and then generate a plot of that data.
We can define this in our DVC pipeline so we know if/when the procedure
has been run, and if the plot need to be remade.

```yaml
stages:
  run-proc:
    cmd: calkit runproc my-important-procedure
    outs:
      - .calkit/procedure-runs/my-important-procedure:
          cache: false # Track this in Git, not DVC
          persist: true # Don't delete existing outputs
  plot-data:
    cmd: python scripts/plot-data.py
    deps:
      - .calkit/procedure-runs/my-important-procedure
    outs:
      - figures/my-plot.png
```

With this pipeline, when we execute `calkit run`,
if our procedure has never been executed, it will be kicked off.
After that, our `plot-data` stage will execute.
If we want to run the procedure again, we can use the `-f` flag to force
it to be called, even though we already data present in
`.calkit/procedure-runs/my-important-procedure`.
After that, our `plot-data` stage will run since the procedure log folder
was defined as its input.
So again, with one command we can ensure all of our inputs and outputs are
consistent.
