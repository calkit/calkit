# Checking and Ensuring Reproducibility

To check the reproducibility of a project and ensure it is fully traceable, use the `calkit check repro` command.

## Step 1: Run the Reproducibility Check

Run the following command to get a detailed JSON output of the reproducibility status:

```bash
uv run calkit check repro --json
```

This will output a JSON object containing information about the pipeline, environments, data, and hardcoded numeric literals in manuscripts.

## Step 2: Fix Pipeline and Environment Issues

If `calkit check repro` reports issues like `has_pipeline: false` or environments not being used, use the `calkit run` command or add the necessary stages to `calkit.yaml` or `dvc.yaml` (see the `create-pipeline` skill for details).

## Step 3: Fix Untraceable Literals

One of the most common reproducibility failures is a hardcoded result literal (a number in prose that was produced by a script but typed by hand, e.g., a drag coefficient `0.42`).

If the JSON output contains findings in the `untraceable_literals` list, you must fix them so they are traceable to the pipeline. The deterministic engine handles `.tex` files, but you should also fix `.qmd` or similar formats if you encounter them.

To fix an untraceable literal:

1. **Ensure the value is output by a script:** The script generating the value must save it into a JSON file (e.g., `results.json`).
2. **Create a `from-json` pipeline stage:** Add a stage that converts the JSON file into a LaTeX macro file.
   ```yaml
   stages:
     results-latex:
       cmd: calkit latex from-json results.json --output results.tex
       deps:
         - results.json
       outs:
         - results.tex
   ```
3. **Include the generated macros in the manuscript:** In the main `.tex` file, include the generated file:
   ```latex
   \input{results.tex}
   ```
4. **Replace the hardcoded literal:** Replace the hardcoded number in the text with the generated macro (e.g., `\resultsDragCoefficient`).
