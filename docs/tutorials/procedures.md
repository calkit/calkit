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
    repeat: 2
    wait_after_s: 30
    inputs:
      temperature:
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

## Executing as part of the pipeline

TODO
