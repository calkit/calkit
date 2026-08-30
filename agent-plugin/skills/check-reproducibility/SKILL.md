---
name: check-reproducibility
description: Check whether a project is fully traceable, and fix what isn't,
  including numbers typed into a manuscript that no pipeline output accounts
  for. Use when the user invokes `/calkit:check-reproducibility`, asks whether
  a project is reproducible, or asks where a number in a paper came from.
---

# Check and fix reproducibility

`calkit check repro` reports what a static reading of the project can
establish: whether there is a pipeline, whether stages run in declared
environments, whether artifacts have provenance, and whether any number in
a manuscript is one nobody can trace.

## Division of labor

Deterministic, done by `calkit check repro --json` --- never re-derive by
hand:

- whether the project is a Git and DVC repo with a remote and a pipeline;
- which stages run outside a declared environment;
- which artifacts have no `stage`, `imported_from`, or `created_by`;
- which scripts no stage refers to;
- which numbers in the manuscript no results file explains
  (`untraceable_literals`).

Judgment, done here:

- whether a flagged number is really a result, or a constant, a tolerance,
  a version, or a figure width the check couldn't rule out;
- which stage should compute a value that has no stage behind it;
- whether an artifact with no provenance was made here or brought in.

## Procedure

1. Run `calkit check repro --json` and read the report.

2. **Pipeline and environment findings** come first: a value can't be made
   traceable until there is a pipeline to make it. See the
   `create-pipeline` and `add-pipeline-stage` skills.

3. **For each untraceable literal**, decide before you touch anything
   whether it is a result. The check is tuned to under-flag rather than be
   noisy, but a number in prose can still be a constant from the
   literature, a tolerance the author chose, or a quantity that belongs in
   the text as written. Say which ones you're leaving and why; do not
   rewrite a sentence to make a check pass.

   For one that is a result, the number must reach the page through the
   pipeline rather than through the author's fingers:

   ```yaml
   pipeline:
     stages:
       compute-drag:
         kind: python-script
         environment: py
         script_path: scripts/compute-drag.py
         outputs: [results/drag.json]
       drag-to-latex:
         kind: json-to-latex
         command_name: result
         inputs: [results/drag.json]
         outputs:
           - path: paper/generated-drag.tex
             storage: git
   ```

   The script writes `{"DragCoefficient": 0.42}`. The document inputs the
   generated file and refers to the value by key:

   ```latex
   \input{generated-drag}
   ...
   The drag coefficient is \result[DragCoefficient].
   ```

   `json-to-latex` generates one _keyed_ command per file, named by
   `command_name` (or the output file's stem), so the reference is
   `\result[DragCoefficient]` --- not a separate macro per key. Never write
   a raw `stages:` block with `cmd: calkit latex from-json`; the stage kind
   is what keeps `calkit.yaml` the single source of truth.

4. **Run the pipeline** (`calkit run`) and check again. Do not run the
   script yourself and paste the number in: that is the failure this whole
   check exists to catch.

5. **Report what you left.** A literal you decided was not a result is a
   judgment the user should see, not one to bury.

## Related

- `answer-todos` builds the analysis a manuscript's TODO comments ask for,
  so the value is injected from the start rather than typed and caught
  here.
- `check-questions` covers whether the project's answers still follow from
  their evidence, which is the same idea one level up.
