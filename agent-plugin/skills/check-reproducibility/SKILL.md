---
name: check-reproducibility
description: Check whether a project is fully traceable, and fix what isn't,
  including numbers typed into a manuscript that no pipeline output accounts
  for. Use when the user invokes `/calkit:check-reproducibility`, asks whether
  a project is reproducible, or asks where a number in a paper came from.
---

# Check and fix reproducibility

<!-- TODO: needs human review -->

`calkit check repro` audits the project: whether there is a pipeline and
it is up to date, whether `dvc.lock` matches the recorded runs, whether
artifacts have provenance, whether any number in a manuscript is one
nobody can trace, whether citations resolve, and whether answers' evidence
holds. It separates problems, which fail it, from advice, which doesn't.

## Division of labor

Deterministic, done by `calkit check repro --json` --- never re-derive by
hand:

- whether the project is a Git and DVC repo with a pipeline, and a remote
  if anything is stored with DVC;
- which stages run outside a declared environment;
- which artifacts have no `stage`, `imported_from`, or `created_by`;
- which scripts no stage refers to;
- which Git-tracked files the pipeline hashes have line endings Git
  doesn't pin (`eol_unpinned`), so a Windows checkout hashes them
  differently and its stages read as out of date;
- which numbers in the manuscript duplicate a value the pipeline already
  computes (`retyped_values`), and which result-like numbers have nothing
  recorded behind them at all (`unattributed_numbers`).

Judgment, done here:

- whether a flagged number is really a result, or a constant, a tolerance,
  a version, or a figure width the check couldn't rule out;
- which stage should compute a value that has no stage behind it;
- whether an artifact with no provenance was made here or brought in.

## Procedure

<!-- TODO: needs human review -->

1. Run `calkit check repro --json` and read the report. The plain output
   is a summary, each countable line naming the `-c` that opens it;
   `--json` carries every finding, with the summary's lines in `summary`,
   each with `ok` true or false for a check and null for advice. The
   command exits non-zero, and `passed` is false, when any check finds a
   problem; advice, e.g., scripts no stage runs, leaves it alone. Read the
   findings, not only the exit code.

2. **Pipeline and environment findings** come first: a value can't be made
   traceable until there is a pipeline to make it. See the
   `create-pipeline` and `add-pipeline-stage` skills.

   <!-- TODO: needs human review -->

   **`eol_unpinned`** has one fix: `calkit fix line-endings`, then commit
   `.gitattributes`. It changes no committed file, only how text files are
   checked out, but it's a project-wide rule, so suggest it rather than
   doing it unasked, and say it matters for anyone on Windows.

3. **Every `retyped_values` finding is worth fixing.** Each is a number
   the pipeline already computes, typed into the document: right today and
   wrong the next time that stage runs. The finding names the results file
   and key, so the fix is mechanical: `\ckvalue{<file>}{<key>}`.

4. **`unattributed_numbers` is a list to read, not a list to fix.** Most
   numbers in a paper are not results. A quantity quoted from a reference
   (`cited` is true when the sentence carries a citation), a threshold the
   author chose, a tolerance, a count -- none of them have anything to be
   traced to, and turning them into structured values would be work for no
   gain. What the list is good for is spotting the one that _is_ a result
   and never got templated in. Say which ones you're leaving and why; never
   rewrite a sentence to make a check pass, and never invent a stage to
   compute a number somebody else measured.

   <!-- TODO: needs human review -->

   A number in a sentence citing a reference is looked for in the
   reference's PDF. Where it's found (`found`, shown as the page), it's the
   reference's number: record it with the `calkit new ref-value` command the
   check prints, giving it a short name, and replace the typed number with
   `\ckrefval{<key>}{<name>}`, `{{< ckrefval <key> <name> >}}`, or
   `<!-- ckrefval <key> <name> --><!-- /ckrefval -->`, keeping the
   citation where it is. Where it isn't (`searched`, shown as "not in"),
   the cited reference doesn't have it, which may be a misquote, a rounded
   value, or a number from somewhere else: tell the user, and don't record
   it.

   `refval_problems` (`calkit check repro -c refvals`) are values quoted
   from references that don't match the PDF, aren't recorded, or whose
   reference the document never cites. Fix what's recorded only from what
   the PDF says, never to make the check pass.

   A line ending in a `% calkit: ignore` comment, optionally with a reason,
   e.g., `% calkit: ignore, from the pump's datasheet`, is left out of both
   checks, as it is by the Overleaf extension. In Markdown, including
   Quarto documents and notebooks' Markdown cells, the comment is
   `<!-- calkit: ignore -->`. Add one only for a number the user confirms
   isn't this project's result.

   <!-- TODO: needs human review -->

   For a number that is this project's result, it must reach the page
   through the pipeline rather than through the author's fingers. A stage
   writes it to a results file:

   ```yaml
   pipeline:
     stages:
       compute-drag:
         kind: python-script
         environment: py
         script_path: scripts/compute-drag.py
         outputs: [results/drag.json]
   ```

   The script writes `{"DragCoefficient": 0.42}`. The document loads the
   `calkit` LaTeX package and reads the value from that file by its path
   in the project and its key:

   ```latex
   \usepackage{calkit}
   ...
   The drag coefficient is \ckvalue[.2f]{results/drag.json}{DragCoefficient}.
   ```

   The document's LaTeX stage depends on what it includes this way, so no
   `json-to-latex` stage or added `inputs` are needed. A `retyped_values`
   finding's `source` names the file and key to use. If the document
   already uses commands a `json-to-latex` stage generates, e.g.,
   `\result[DragCoefficient]`, they keep working, so referencing the
   existing command is fine there too. Never define a macro that holds the
   number, or edit a generated file by hand: either one is a typed value
   with extra steps.

   <!-- TODO: needs human review -->

   If a pipeline notebook computes the number, e.g., a cell prints it,
   save the variable as a cell output instead of changing the notebook:
   `calkit nb add-output <notebook> value --cell-id <id> --variable-name <name>`.
   Then cite it as `\ckvalue{<notebook>}{<name>}`.
   Use the cell that printed it, not the last one,
   since the value is saved right after that cell runs.
   See the conventions skill's section on notebook cells.

   <!-- TODO: needs human review -->

   The check also reads Markdown publications, and the documents Quarto
   and Markdown stages render, including a notebook's Markdown cells,
   reported by cell number. A Quarto document reads a value with
   `{{< ckvalue results/drag.json DragCoefficient .2f >}}`, and a Markdown
   stage's document with
   `<!-- ckvalue results/drag.json DragCoefficient .2f --><!-- /ckvalue -->`,
   which it fills in when it renders. A number that a Quarto notebook's own
   code computes can be an inline expression instead, e.g.,
   `` `{python} f"{drag:.2f}"` ``, since the code runs when it renders.

5. **Run the pipeline** (`calkit run`) and check again. Do not run the
   script yourself and paste the number in: that is the failure this whole
   check exists to catch.

6. **Report what you left.** A number you decided was not a result is a
   judgment the user should see, not one to bury.

## Related

- `build-paper-pipeline` builds the stages a manuscript's TODO comments
  ask for, so the value is injected from the start rather than typed and
  caught here.
- `check-questions` covers whether the project's answers still follow from
  their evidence, which is the same idea one level up.
