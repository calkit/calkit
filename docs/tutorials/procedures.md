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
  - summary: Turn on the machine.
    wait_after_s: 30
  - summary: Record the temperature.
    details: >
      In the upper right hand corner of the screen you will see a temperature
      value. Record this.
    wait_after_s: 30
    inputs:
      temperature:
        name: Temperature
        units: Degrees C
        dtype: float
  - summary: Turn off the machine.
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
      - .calkit/procedure-runs/my-important-procedure
  plot-data:
    cmd: python scripts/plot-data.py
    deps:
      - .calkit/procedure-runs/my-important-procedure
    outs:
      - figures/my-plot.png
```

What if we need to run this procedure once-per-day for the duration
of an experiment?
We can add define the procedure's `start`, `end`, and `period` attributes:

```yaml
title: My important procedure
description: This is a manual procedure for setting up the experiment.
start: 2024-11-20
end: 2024-12-01
period:
  days: 1
steps:
...
```

Then we can use the `always_changed` option in the stage to ensure
DVC always runs it.

```yaml
stages:
  run-proc:
    cmd: calkit runproc my-important-procedure
    always_changed: true
    outs:
      - .calkit/procedure-runs/my-important-procedure
...
```

With the pipeline setup this way, we can go into the lab each day,
call `calkit run`,
and our procedure will automatically start, so long as the current date
falls within our specified `start` and `end`,
and it hasn't yet been run that day.
Once it's done, the data will be plotted since the run logs will
have changed, and those have been defined as a dependency for the
`plot-data` stage.

To finish up, we can call

```sh
calkit commit -am "Run the important procedure" --push
```

This will commit and push our data and the updated figure to the cloud
for backup and sharing with our collaborators.
