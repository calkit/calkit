# The pipeline

The pipeline
defines and ties together the processes that produce
the project's important assets or artifacts, such as datasets,
figures, tables, and publications.
It is saved in the `pipeline` section of the `calkit.yaml` file,
and is compiled to a [DVC](https://dvc.org) pipeline (saved in `dvc.yaml`)
when `calkit run` is called.

A pipeline is composed of stages,
each of which has a specific type or "kind."
Each stage must specify the environment in which it runs to ensure it's
reproducible.
Calkit will automatically generate an "environment lock file"
at the start of a run
and can therefore automatically detect if an environment has changed,
and the affected stages need to be rerun.
Stages can also define `inputs` and `outputs`,
and you can decide how you'd like outputs to be stored, i.e., with Git or DVC.

Any stages that have not changed since they were last run will be skipped,
since their results will have been cached.

In the `calkit.yaml` file, you can define a `pipeline`
(and `environments`) like:

```yaml
# Define environments
environments:
  main:
    kind: uv-venv
    path: requirements.txt
    python: "3.13"
  texlive:
    kind: docker
    image: texlive/texlive:latest-full

# Define the pipeline
pipeline:
  stages:
    collect-data:
      kind: python-script
      script_path: scripts/collect-data.py
      environment: main
      outputs:
        - data/raw.csv
        - path: data/meta.json
          storage: git
          delete_before_run: false
    process-data:
      kind: jupyter-notebook
      notebook_path: notebooks/process.ipynb
      environment: main
      inputs:
        - data/raw.csv
      outputs:
        - data/processed.csv
        - figures/fig1.png
    build-paper:
      kind: latex
      target_path: paper/paper.tex
      environment: texlive
      inputs:
        - figures/fig1.png
        - references.bib
```

## Inputs and outputs

Every stage can declare the paths it reads with `inputs`
and the paths it writes with `outputs`.
Together these are what let Calkit decide whether a stage is up-to-date:
a stage reruns when one of its inputs changes,
and its outputs are what get cached, stored, and handed to downstream stages.

Both accept either a plain path,
which is the common case,
or an object when you need to say more about it:

```yaml
outputs:
  - data/processed.csv # Plain path, stored with DVC
  - path: data/meta.json
    storage: git
    delete_before_run: false
```

### Where outputs are stored

An output's `storage` decides which system tracks it:

| Value     | Meaning                                                                                                                                                                                  |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dvc`     | Track with DVC. The default, and the right choice for most data and figures.                                                                                                             |
| `git`     | Track with Git, for small text files worth reading in a diff.                                                                                                                            |
| `dvc-zip` | Zip the directory and track the archive with DVC, for directories of many small files. See [large folders of many small files](../version-control.md#large-folders-of-many-small-files). |
| null      | Leave the path untracked, i.e., produced but neither committed nor cached.                                                                                                               |

By default an output is removed before the stage runs,
so each run starts from a clean slate
rather than building on the previous run's file.
Set `delete_before_run: false` for an output the stage appends to
or updates in place;
this maps to DVC's `persist`.

### Depending on another stage's outputs

Instead of repeating paths, an input can name a stage
and pick up whatever that stage produces:

```yaml
inputs:
  - from_stage_outputs: collect-data
```

The full set of properties for each of these objects is listed under
[nested parameter types](#nested-parameter-types).

## Stage types and unique attributes

All stage declarations require a `kind` and an `environment`,
and can specify `inputs` and `outputs`.
The different kinds of stages and their unique attributes are listed below.
For more details, see `calkit.models.pipeline`.

### `python-script`

- `script_path`
- `args` (list, optional)

### `shell-command`

- `command`
- `shell` (optional, e.g., `bash`, `sh`, `zsh`; default: `bash`)

### `shell-script`

- `script_path`
- `shell` (optional, e.g., `bash`, `sh`, `zsh`; default: `bash`)
- `args` (list, optional)

### `matlab-script`

- `script_path`

### `latex`

- `target_path`

### `docker-command`

- `command`

### `r-script`

- `script_path`
- `args` (list, optional)

### `julia-script`

- `script_path`
- `args`

### `julia-command`

- `command`

### `markdown`

- `target_path`

A stage sourced from a Markdown file's annotated code blocks;
see [Runnable Markdown](markdown.md).

## Iteration

### Over a list of values

```yaml
pipeline:
  stages:
    my-iter-stage:
      kind: python-script
      script_path: scripts/my-script.py
      args:
        - "--model={var}"
      iterate_over:
        - arg_name: var
          values:
            - some-model
            - some-other-model
      inputs:
        - data/raw
      outputs:
        - models/{var}.h5
```

### Over a table (or list of lists)

```yaml
pipeline:
  stages:
    my-iter-stage:
      kind: python-script
      script_path: scripts/my-script.py
      args:
        - "--model={var1}"
        - "--n_estimators={var2}"
      iterate_over:
        - arg_name: [var1, var2]
          values:
            - [some-model, 5]
            - [some-other-model, 7]
      inputs:
        - data/raw
      outputs:
        - models/{var1}-{var2}.h5
```

### Over ranges of numbers

```yaml
pipeline:
  stages:
    my-iter-stage:
      kind: python-script
      script_path: scripts/my-script.py
      args:
        - "--thresh={thresh}"
      iterate_over:
        - arg_name: thresh
          values:
            - range:
                start: 0
                stop: 20
                step: 0.5
            - range:
                start: 30
                stop: 35
                step: 1
            - 41
      inputs:
        - data/raw
      outputs:
        - results/{thresh}.csv
```

## Automatic stage and environment detection

The `calkit xr` command, which stands for "execute and record,"
can be used to automatically generate pipeline stages and environments from
scripts (Python, MATLAB, Julia, R, and shell),
notebooks, LaTeX source files, or shell commands.

For example, if you have a Python script in `scripts/run.py`, you can
call:

```sh
calkit xr scripts/run.py
```

Calkit will attempt to detect which environment in which this script should run,
creating one if necessary (it can also be specified with the `-e` flag.)
Calkit will then try to detect inputs and outputs
and attempt to run the stage it created.
If successful, it will be added to the pipeline and kept reproducible from
that point onwards.
That is, calling `calkit run` again will detect if the script, environment,
or any input files have changed, and rerun if so.

### What commands work best with `xr`

`xr` works best when your command has a clear executable and arguments,
or when the first argument is a recognized file type (for example `.py`,
`.ipynb`, `.tex`, `.jl`, `.R`, `.m`, `.sh`).

For Docker commands:

- `docker run` commands are supported.
- For some CLI-style images (for example Mermaid CLI), Calkit converts the
  command into a `command` stage and configures Docker `entrypoint` mode.
- For other images, Calkit keeps a `shell-command` stage, infers a Docker
  environment from the image, and stores the inner command (the command run
  inside the container) as the stage command.

### What I/O `xr` can usually detect

I/O detection is heuristic and depends on stage kind.
It is strongest for:

- Python/R/Julia scripts with common file read/write APIs.
- Notebooks with straightforward file reads/writes.
- LaTeX includes and bibliography references.
- Shell commands that use redirection (`<`, `>`, `>>`) and common
  file operations (for example `cp` and `mv`).

For Docker shell commands, I/O detection is applied to the inner command
inside `docker run`, not the outer Docker wrapper.

I/O detection is less reliable when paths are dynamic (constructed at runtime,
read from environment variables, generated in loops, or hidden behind custom
wrappers).

When needed, provide explicit paths with:

- `--input` (repeatable)
- `--output` (repeatable)
- `--no-detect-io` to disable automatic detection completely

### How environment detection works

At a high level, `xr` chooses environments in this order:

1. Use `--environment` if provided.
2. Reuse an existing matching stage environment when possible.
3. Infer from stage language and dependencies:
   - Python: typically `pyproject.toml`, `requirements.txt`, `environment.yml`,
     or a generated Python environment spec.
   - R: typically `DESCRIPTION` or a generated `renv` spec.
   - Julia: typically `Project.toml` or a generated Julia project spec.
   - LaTeX: typically a Docker LaTeX environment.
4. For shell commands:
   - `docker run ...` can infer a Docker environment from the image.
   - non-Docker shell commands default to `_system` unless explicitly set.

If you want to inspect what `xr` would do without changing project files,
use the `--dry-run` option.

<!-- AUTO-GENERATED: PIPELINE-STAGE-KINDS:START -->

## Pipeline stage kind reference

Stage definitions belong in `pipeline.stages` in `calkit.yaml`.

Common stage parameters:

| Parameter           | Type                                             | Required | Default   | Description                                                                                                                                                                                                                                                                                                           |
| ------------------- | ------------------------------------------------ | -------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `environment`       | str                                              | yes      |           | Name of the environment in which to run this stage.                                                                                                                                                                                                                                                                   |
| `wdir`              | str \| None                                      | no       | null      | Working directory in which to run, relative to the project root. Note that all other paths in the stage are relative to this.                                                                                                                                                                                         |
| `inputs`            | list[str \| PathInput \| InputsFromStageOutputs] | no       |           | Paths this stage depends on, which trigger a rerun when they change. Normally plain path strings; an object carrying a 'path' is also accepted.                                                                                                                                                                       |
| `outputs`           | list[str \| PathOutput]                          | no       |           | Paths this stage produces.                                                                                                                                                                                                                                                                                            |
| `always_run`        | bool                                             | no       | False     | Run this stage every time the pipeline is run, even if nothing has changed.                                                                                                                                                                                                                                           |
| `iterate_over`      | list[StageIteration] \| None                     | no       | null      | Arguments over which to run this stage multiple times.                                                                                                                                                                                                                                                                |
| `description`       | str \| None                                      | no       | null      | A description of what this stage does.                                                                                                                                                                                                                                                                                |
| `frozen`            | bool                                             | no       | False     | Never rerun this stage, treating its outputs as up-to-date.                                                                                                                                                                                                                                                           |
| `scheduler`         | StageSchedulerOptions \| None                    | no       | null      | Options for running this stage on a job scheduler (SLURM or PBS).                                                                                                                                                                                                                                                     |
| `setup`             | list[str] \| None                                | no       | null      | Commands run before this stage's own command, in the same shell as the command, so a variable they set or a function they define is in scope for it, exported or not. Combined with the environment's 'default_setup' as 'env_default_setup' says. Only for environments that have one: 'system', 'slurm', and 'pbs'. |
| `env_default_setup` | Literal['ignore', 'replace', 'merge']            | no       | 'replace' | How to combine 'setup' with the environment's 'default_setup'. 'replace' (default) runs the environment's only when the stage names none of its own; 'merge' runs the environment's first, then the stage's; 'ignore' never runs the environment's.                                                                   |
| `slurm`             | StageSchedulerOptions \| None                    | no       | null      | Deprecated name for 'scheduler'; set 'scheduler' instead.                                                                                                                                                                                                                                                             |

Parameters whose type is a named object, like `PathOutput`, are described under [nested parameter types](#nested-parameter-types).

### `command`

Model class: `CommandStage`

| Kind-specific parameter | Type | Required | Default | Description                        |
| ----------------------- | ---- | -------- | ------- | ---------------------------------- |
| `command`               | str  | yes      |         | Command to run in the environment. |

### `docker-command`

Model class: `DockerCommandStage`

| Kind-specific parameter | Type | Required | Default | Description                                           |
| ----------------------- | ---- | -------- | ------- | ----------------------------------------------------- |
| `command`               | str  | yes      |         | Full command to run, including the 'docker run' call. |

### `json-to-latex`

Model class: `JsonToLatexStage`

| Kind-specific parameter | Type                   | Required | Default    | Description                                         |
| ----------------------- | ---------------------- | -------- | ---------- | --------------------------------------------------- |
| `environment`           | str                    | no       | '\_system' | Name of the environment in which to run this stage. |
| `command_name`          | str \| None            | no       | null       | Name of the LaTeX command to define for each value. |
| `format`                | dict[str, str] \| None | no       | null       | Format strings for values, keyed by their JSON key. |

### `julia-command`

Model class: `JuliaCommandStage`

| Kind-specific parameter | Type | Required | Default | Description           |
| ----------------------- | ---- | -------- | ------- | --------------------- |
| `command`               | str  | yes      |         | Julia command to run. |

### `julia-script`

Model class: `JuliaScriptStage`

| Kind-specific parameter | Type      | Required | Default | Description                      |
| ----------------------- | --------- | -------- | ------- | -------------------------------- |
| `script_path`           | str       | yes      |         | Path to the Julia script to run. |
| `args`                  | list[str] | no       |         | Arguments passed to the script.  |

### `jupyter-notebook`

Model class: `JupyterNotebookStage`

A stage that runs a Jupyter notebook.

Notebooks need to be cleaned of outputs so they can be used as DVC
dependencies. The `status` and `run` commands handle this
automatically.

| Kind-specific parameter  | Type                                         | Required | Default | Description                                                                                                  |
| ------------------------ | -------------------------------------------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------ |
| `notebook_path`          | str                                          | yes      |         | Path to the notebook to execute.                                                                             |
| `cleaned_ipynb_storage`  | Literal['git', 'dvc'] \| None                | no       | null    | Where to store the output-stripped notebook.                                                                 |
| `executed_ipynb_storage` | Literal['git', 'dvc'] \| None                | no       | 'dvc'   | Where to store the executed notebook.                                                                        |
| `html_storage`           | Literal['git', 'dvc'] \| None                | no       | 'dvc'   | Where to store the executed notebook as HTML.                                                                |
| `parameters`             | dict[str, Any]                               | no       |         | Parameters injected into the notebook. A value like '{name}' is filled in from the project-level parameters. |
| `language`               | Literal['python', 'matlab', 'julia'] \| None | no       | null    | The notebook's language. Detected automatically if unset.                                                    |

### `latex`

Model class: `LatexStage`

| Kind-specific parameter | Type                          | Required | Default | Description                                                                                                                                       |
| ----------------------- | ----------------------------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `target_path`           | str                           | yes      |         | Path to the .tex file to compile.                                                                                                                 |
| `output_dir`            | str \| None                   | no       | null    | Directory for latexmk output. Defaults to compiling in place, alongside the target.                                                               |
| `aux_dir`               | str \| None                   | no       | null    | Directory for latexmk auxiliary files.                                                                                                            |
| `latexmkrc_path`        | str \| None                   | no       | null    | Path to a latexmkrc file to use.                                                                                                                  |
| `pdf_storage`           | Literal['git', 'dvc'] \| None | no       | 'dvc'   | Where to store the resulting PDF.                                                                                                                 |
| `diffs`                 | list[str \| list[str]]        | no       |         | Comparisons to keep for this document, each a pair of revisions. A bare string is shorthand for comparing that revision against the working tree. |
| `diff_pdf_storage`      | Literal['git', 'dvc'] \| None | no       | 'dvc'   | Where to store the resulting diff PDFs.                                                                                                           |
| `verbose`               | bool                          | no       | False   | Show full latexmk output.                                                                                                                         |
| `force`                 | bool                          | no       | False   | Keep compiling despite errors (latexmk -f).                                                                                                       |
| `synctex`               | bool                          | no       | True    | Generate SyncTeX data for editor/PDF navigation.                                                                                                  |
| `latexmk_args`          | list[str]                     | no       |         | Extra arguments passed straight through to latexmk, for control Calkit does not model.                                                            |

### `map-paths`

Model class: `MapPathsStage`

| Kind-specific parameter | Type                                                                      | Required | Default    | Description                                         |
| ----------------------- | ------------------------------------------------------------------------- | -------- | ---------- | --------------------------------------------------- |
| `environment`           | str                                                                       | no       | '\_system' | Name of the environment in which to run this stage. |
| `paths`                 | list[CopyFileToFile \| CopyFileToDir \| DirToDirMerge \| DirToDirReplace] | yes      |            | Copy operations to perform.                         |

### `marimo-html-wasm`

Model class: `MarimoHtmlWasmStage`

A stage that exports a marimo notebook to a WebAssembly app.

The app runs entirely in the browser via Pyodide, so it can be served
as static files with no backend.

marimo's export commands differ enough from each other that each gets
its own stage kind and CLI command, rather than one kind with a format
option whose other fields only apply to some of its values.

marimo's own export is not self-contained: it requires the data an app
reads to already sit in a `public` directory next to the notebook, and
copies only that directory into the output. Assembling that is this
stage's main job, and it happens in a build directory rather than
in place, so nothing is generated in the project tree. Paths in `include_paths` are
copied beneath `public` at their project-relative paths, so notebook
code that reads `mo.notebook_location() / "public" / "data.csv"` works
the same locally as it does in the browser.

`include_paths` is deliberately separate from `inputs` because these
files are published to the web, which should be opt-in per path rather
than inferred from the dependency graph. They are dependencies too.

| Kind-specific parameter | Type                          | Required | Default | Description                                                                                                  |
| ----------------------- | ----------------------------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------ |
| `notebook_path`         | str                           | yes      |         | Path to the marimo notebook to export.                                                                       |
| `layout_path`           | str \| None                   | no       | null    | Path to the notebook's layout file, if it has one.                                                           |
| `mode`                  | Literal['run', 'edit']        | no       | 'run'   | Whether the app runs its cells or opens as an editable notebook.                                             |
| `show_code`             | bool                          | no       | False   | Show the notebook's code in the app.                                                                         |
| `include_paths`         | list[str]                     | no       |         | Paths published with the app, readable from the notebook at 'public/<path>'. These are dependencies as well. |
| `output_dir`            | str                           | yes      |         | Directory into which the app is exported.                                                                    |
| `output_storage`        | Literal['git', 'dvc'] \| None | no       | 'dvc'   | Where to store the exported app.                                                                             |
| `validate_notebook`     | bool                          | no       | True    | Run the notebook before exporting, to catch one that would fail in the browser.                              |

### `markdown`

Model class: `MarkdownStage`

A stage sourced from a Markdown file's annotated code blocks.

This stands in for however many stages the file declares. It is
replaced by them at compile time (see
`calkit.markdown.expand_ck_info`), so nothing downstream needs to
know Markdown was involved.

`inputs`, `always_run`, `frozen`, and `scheduler` apply to
every stage the file declares. A file can't iterate or declare
outputs as a whole, since those belong to the individual stages in
it, and its stages always run in the project root, where the scripts
extracted from it are written.

| Kind-specific parameter | Type | Required | Default    | Description                                                      |
| ----------------------- | ---- | -------- | ---------- | ---------------------------------------------------------------- |
| `environment`           | str  | no       | '\_system' | Environment used by blocks that don't name one.                  |
| `wdir`                  | None | no       | null       | Not supported; a Markdown file's stages run in the project root. |
| `outputs`               | None | no       | null       | Not supported; declare outputs on the file's blocks.             |
| `iterate_over`          | None | no       | null       | Not supported; markdown stages can't iterate.                    |
| `target_path`           | str  | yes      |            | Path to the Markdown file.                                       |

### `matlab-command`

Model class: `MatlabCommandStage`

| Kind-specific parameter | Type | Required | Default | Description            |
| ----------------------- | ---- | -------- | ------- | ---------------------- |
| `command`               | str  | yes      |         | MATLAB command to run. |

### `matlab-script`

Model class: `MatlabScriptStage`

| Kind-specific parameter | Type        | Required | Default | Description                                      |
| ----------------------- | ----------- | -------- | ------- | ------------------------------------------------ |
| `script_path`           | str         | yes      |         | Path to the MATLAB script to run.                |
| `matlab_path`           | str \| None | no       | null    | Directory added to the MATLAB path, recursively. |

### `python-script`

Model class: `PythonScriptStage`

| Kind-specific parameter | Type      | Required | Default | Description                       |
| ----------------------- | --------- | -------- | ------- | --------------------------------- |
| `script_path`           | str       | yes      |         | Path to the Python script to run. |
| `args`                  | list[str] | no       |         | Arguments passed to the script.   |

### `quarto`

Model class: `QuartoStage`

A stage that renders a Quarto document.

Calkit controls only what belongs on the CLI: which environment to
render in, the target document, and (optionally) the output format and
extra `quarto render` arguments. The output format(s) and any other
rendering behavior are left to the document/`_quarto.yml` metadata, so
there is no redundancy between the pipeline definition and the doc.

Outputs are declared explicitly via `outputs` rather than parsed out
of the Quarto document, since a document can emit multiple formats to
arbitrary paths. As with other stages, plain string outputs are
DVC-cached by default; use a `PathOutput` to store an output with Git
instead.

| Kind-specific parameter | Type        | Required | Default | Description                                                                                        |
| ----------------------- | ----------- | -------- | ------- | -------------------------------------------------------------------------------------------------- |
| `target_path`           | str         | yes      |         | Path to the Quarto document to render.                                                             |
| `to`                    | str \| None | no       | null    | Output format, passed to 'quarto render --to'. Defaults to what the document's metadata specifies. |
| `args`                  | list[str]   | no       |         | Extra arguments passed to 'quarto render'.                                                         |

### `r-script`

Model class: `RScriptStage`

| Kind-specific parameter | Type      | Required | Default | Description                     |
| ----------------------- | --------- | -------- | ------- | ------------------------------- |
| `script_path`           | str       | yes      |         | Path to the R script to run.    |
| `args`                  | list[str] | no       |         | Arguments passed to the script. |

### `sbatch`

Model class: `SBatchStage`

| Kind-specific parameter | Type                          | Required | Default | Description                         |
| ----------------------- | ----------------------------- | -------- | ------- | ----------------------------------- |
| `script_path`           | str                           | yes      |         | Path to the script to submit.       |
| `args`                  | list[str]                     | no       |         | Arguments passed to the script.     |
| `sbatch_options`        | list[str]                     | no       |         | Options passed to sbatch.           |
| `log_path`              | str \| None                   | no       | null    | Path at which to write the job log. |
| `log_storage`           | Literal['git', 'dvc'] \| None | no       | 'git'   | Where to store the job log.         |

### `shell-command`

Model class: `ShellCommandStage`

| Kind-specific parameter | Type                         | Required | Default | Description                        |
| ----------------------- | ---------------------------- | -------- | ------- | ---------------------------------- |
| `command`               | str                          | yes      |         | Shell command to run.              |
| `shell`                 | Literal['sh', 'bash', 'zsh'] | no       | 'bash'  | Shell in which to run the command. |

### `shell-script`

Model class: `ShellScriptStage`

| Kind-specific parameter | Type                         | Required | Default | Description                       |
| ----------------------- | ---------------------------- | -------- | ------- | --------------------------------- |
| `script_path`           | str                          | yes      |         | Path to the shell script to run.  |
| `args`                  | list[str]                    | no       |         | Arguments passed to the script.   |
| `shell`                 | Literal['sh', 'bash', 'zsh'] | no       | 'bash'  | Shell in which to run the script. |

### `word-to-pdf`

Model class: `WordToPdfStage`

| Kind-specific parameter | Type | Required | Default    | Description                                         |
| ----------------------- | ---- | -------- | ---------- | --------------------------------------------------- |
| `environment`           | str  | no       | '\_system' | Name of the environment in which to run this stage. |
| `word_doc_path`         | str  | yes      |            | Path to the Word document to convert.               |

### Nested parameter types

Some parameters above take objects rather than plain values. The properties of each are described below.

#### `PathInput`

An input written as an object carrying a path.

Prefer a plain path string. This exists so a stage keeps working when an
output is copied verbatim into another stage's `inputs`, which is how
entries like `{path: ..., storage: ...}` show up in the wild. Only
`path` is used: an input is a dependency wherever it happens to be
stored, so the other keys are carried along and ignored.

Extra keys are allowed deliberately, both to tolerate whatever came along
with a copied output and to leave room for object inputs that aren't
paths at all, e.g., a database table. They are kept rather than dropped,
since a stage rewritten back to calkit.yaml (see
`Pipeline.convert_sbatch_stages`) would otherwise silently lose them.

| Parameter | Type | Required | Default | Description                          |
| --------- | ---- | -------- | ------- | ------------------------------------ |
| `path`    | str  | yes      |         | Path to the input file or directory. |

#### `InputsFromStageOutputs`

| Parameter            | Type | Required | Default | Description                                           |
| -------------------- | ---- | -------- | ------- | ----------------------------------------------------- |
| `from_stage_outputs` | str  | yes      |         | Name of a stage whose outputs are inputs to this one. |

#### `PathOutput`

| Parameter           | Type                                     | Required | Default | Description                                                 |
| ------------------- | ---------------------------------------- | -------- | ------- | ----------------------------------------------------------- |
| `path`              | str                                      | yes      |         | Path to the output file or directory.                       |
| `storage`           | Literal['git', 'dvc', 'dvc-zip'] \| None | no       | 'dvc'   | Where to store this output. Use null to leave it untracked. |
| `delete_before_run` | bool                                     | no       | True    | Delete this output before the stage runs.                   |

#### `StageIteration`

A model for the `iterate_over` key in a stage definition.

If `arg_name` is a list, `values` also must be a list of lists with
each sublist the length of `arg_name`.

| Parameter  | Type                                                                                           | Required | Default | Description                                                                  |
| ---------- | ---------------------------------------------------------------------------------------------- | -------- | ------- | ---------------------------------------------------------------------------- |
| `arg_name` | str \| list[str]                                                                               | yes      |         | Name(s) of the argument(s) to substitute into the stage's command and paths. |
| `values`   | list[int \| float \| str \| RangeIteration \| ParameterIteration \| list[int \| float \| str]] | yes      |         | Values over which to iterate.                                                |

#### `StageSchedulerOptions`

Parameters for running a stage on a job scheduler (SLURM or PBS).

The environment-level `default_options` are applied by `calkit
scheduler batch` at submission time, in the mode `env_default_options`
names: `replace` (the default) uses them only when the stage names
none of its own, `merge` puts them before the stage's, and `ignore`
never applies them.

`setup` and `env_default_setup` were once written here too. They
belong to the stage, not to the scheduler: a stage on a `system`
environment has setup commands and no scheduler at all. They are still
accepted here and hoisted onto the stage when it loads.

| Parameter             | Type                                  | Required | Default   | Description                                                                                                                                    |
| --------------------- | ------------------------------------- | -------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `options`             | list[str] \| None                     | no       | null      | Options passed to the scheduler at submission.                                                                                                 |
| `setup`               | list[str] \| None                     | no       | null      | Deprecated; set 'setup' on the stage itself. Setup commands are not a scheduler concept, and a stage on a 'system' environment needs them too. |
| `env_default_options` | Literal['ignore', 'replace', 'merge'] | no       | 'replace' | How to combine 'options' with the environment's default_options.                                                                               |
| `env_default_setup`   | Literal['ignore', 'replace', 'merge'] | no       | 'replace' | Deprecated; set 'env_default_setup' on the stage itself, alongside its 'setup'.                                                                |
| `log_path`            | str \| None                           | no       | null      | Path at which to write the job log.                                                                                                            |
| `log_storage`         | Literal['git', 'dvc'] \| None         | no       | 'git'     | Where to store the job log.                                                                                                                    |

#### `CopyFileToFile`

Copy a single file to a single destination path.

| Parameter | Type                    | Required | Default        | Description                            |
| --------- | ----------------------- | -------- | -------------- | -------------------------------------- |
| `kind`    | Literal['file-to-file'] | no       | 'file-to-file' | Copy one file to one destination path. |
| `src`     | str                     | yes      |                | Path to the file to copy.              |
| `dest`    | str                     | yes      |                | Path to which the file is copied.      |

#### `CopyFileToDir`

Copy a single file into a directory, keeping its name.

| Parameter | Type                   | Required | Default       | Description                                          |
| --------- | ---------------------- | -------- | ------------- | ---------------------------------------------------- |
| `kind`    | Literal['file-to-dir'] | no       | 'file-to-dir' | Copy one file into a destination directory.          |
| `src`     | str                    | yes      |               | Path to the file to copy.                            |
| `dest`    | str                    | yes      |               | Path to the directory into which the file is copied. |

#### `DirToDirMerge`

Copy a directory's contents into another, keeping what's there.

| Parameter | Type                        | Required | Default            | Description                                  |
| --------- | --------------------------- | -------- | ------------------ | -------------------------------------------- |
| `kind`    | Literal['dir-to-dir-merge'] | no       | 'dir-to-dir-merge' | Merge one directory's contents into another. |
| `src`     | str                         | yes      |                    | Path to the directory to copy from.          |
| `dest`    | str                         | yes      |                    | Path to the directory to copy into.          |

#### `DirToDirReplace`

Replace a directory with the contents of another.

| Parameter | Type                          | Required | Default              | Description                                               |
| --------- | ----------------------------- | -------- | -------------------- | --------------------------------------------------------- |
| `kind`    | Literal['dir-to-dir-replace'] | no       | 'dir-to-dir-replace' | Replace the destination directory entirely.               |
| `src`     | str                           | yes      |                      | Path to the directory to copy from.                       |
| `dest`    | str                           | yes      |                      | Path to the directory to replace, which is deleted first. |

#### `RangeIteration`

| Parameter | Type                 | Required | Default | Description                                |
| --------- | -------------------- | -------- | ------- | ------------------------------------------ |
| `range`   | RangeIterationParams | yes      |         | Bounds of the range over which to iterate. |

#### `ParameterIteration`

| Parameter   | Type | Required | Default | Description                                                       |
| ----------- | ---- | -------- | ------- | ----------------------------------------------------------------- |
| `parameter` | str  | yes      |         | Name of a project parameter whose list of values to iterate over. |

#### `RangeIterationParams`

| Parameter | Type         | Required | Default | Description                                    |
| --------- | ------------ | -------- | ------- | ---------------------------------------------- |
| `start`   | int \| float | yes      |         | First value in the range, which is included.   |
| `stop`    | int \| float | yes      |         | Value at which to stop, which is not included. |
| `step`    | int \| float | no       | 1       | Amount by which to increment each value.       |

<!-- AUTO-GENERATED: PIPELINE-STAGE-KINDS:END -->
