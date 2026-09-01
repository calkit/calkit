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
- which numbers in the manuscript duplicate a value the pipeline already
  computes (`retyped_values`), and which result-like numbers have nothing
  recorded behind them at all (`unattributed_numbers`).

Judgment, done here:

- whether a flagged number is really a result, or a constant, a tolerance,
  a version, or a figure width the check couldn't rule out;
- which stage should compute a value that has no stage behind it;
- whether an artifact with no provenance was made here or brought in.

## Procedure

1. Run `calkit check repro --json` and read the report. The plain output
   is a summary, each countable line naming the `-c` that opens it;
   `--json` carries every finding. The command exits non-zero only for
   `retyped_values`, a value the project's own pipeline computes and the
   document typed anyway; everything else is advice and leaves the exit
   code alone. Read the findings, not the exit code.

2. **Pipeline and environment findings** come first: a value can't be made
   traceable until there is a pipeline to make it. See the
   `create-pipeline` and `add-pipeline-stage` skills.

3. **Every `retyped_values` finding is worth fixing.** Each is a number
   the pipeline already computes, typed into the document: right today and
   wrong the next time that stage runs. The finding names the results file
   and key, so the fix is mechanical.

4. **`unattributed_numbers` is a list to read, not a list to fix.** Most
   numbers in a paper are not results. A quantity quoted from a reference
   (`cited` is true when the sentence carries a citation), a threshold the
   author chose, a tolerance, a count -- none of them have anything to be
   traced to, and turning them into structured values would be work for no
   gain. What the list is good for is spotting the one that _is_ a result
   and never got templated in. Say which ones you're leaving and why; never
   rewrite a sentence to make a check pass, and never invent a stage to
   compute a number somebody else measured.

   For a number that is this project's result, it must reach the page
   through the pipeline rather than through the author's fingers:

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

5. **Run the pipeline** (`calkit run`) and check again. Do not run the
   script yourself and paste the number in: that is the failure this whole
   check exists to catch.

6. **Report what you left.** A number you decided was not a result is a
   judgment the user should see, not one to bury.

## Related

- `answer-todos` builds the analysis a manuscript's TODO comments ask for,
  so the value is injected from the start rather than typed and caught
  here.
- `check-questions` covers whether the project's answers still follow from
  their evidence, which is the same idea one level up.
