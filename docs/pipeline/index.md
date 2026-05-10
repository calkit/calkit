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

### `sbatch`

- `script_path`
- `args`
- `sbatch_options`

This stage type runs a script with `sbatch`, which is a common way to run
jobs on a high performance computing (HPC) cluster that uses the SLURM
job scheduler.

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

| Parameter      | Type                                | Required | Default |
| -------------- | ----------------------------------- | -------- | ------- |
| `environment`  | str                                 | yes      |         |
| `wdir`         | str \| None                         | no       | null    |
| `inputs`       | list[str \| InputsFromStageOutputs] | no       |         |
| `outputs`      | list[str \| PathOutput]             | no       |         |
| `always_run`   | bool                                | no       | False   |
| `iterate_over` | list[StageIteration] \| None        | no       | null    |
| `description`  | str \| None                         | no       | null    |
| `slurm`        | StageSchedulerOptions \| None       | no       | null    |
| `scheduler`    | StageSchedulerOptions \| None       | no       | null    |

### `command`

Model class: `CommandStage`

| Kind-specific parameter | Type | Required | Default |
| ----------------------- | ---- | -------- | ------- |
| `command`               | str  | yes      |         |

### `docker-command`

Model class: `DockerCommandStage`

| Kind-specific parameter | Type | Required | Default |
| ----------------------- | ---- | -------- | ------- |
| `command`               | str  | yes      |         |

### `json-to-latex`

Model class: `JsonToLatexStage`

| Kind-specific parameter | Type                   | Required | Default    |
| ----------------------- | ---------------------- | -------- | ---------- |
| `environment`           | str                    | no       | '\_system' |
| `command_name`          | str \| None            | no       | null       |
| `format`                | dict[str, str] \| None | no       | null       |

### `julia-command`

Model class: `JuliaCommandStage`

| Kind-specific parameter | Type | Required | Default |
| ----------------------- | ---- | -------- | ------- |
| `command`               | str  | yes      |         |

### `julia-script`

Model class: `JuliaScriptStage`

| Kind-specific parameter | Type      | Required | Default |
| ----------------------- | --------- | -------- | ------- |
| `script_path`           | str       | yes      |         |
| `args`                  | list[str] | no       |         |

### `jupyter-notebook`

Model class: `JupyterNotebookStage`

A stage that runs a Jupyter notebook.

Notebooks need to be cleaned of outputs so they can be used as DVC
dependencies. The `status` and `run` commands handle this
automatically.

| Kind-specific parameter  | Type                                         | Required | Default |
| ------------------------ | -------------------------------------------- | -------- | ------- |
| `notebook_path`          | str                                          | yes      |         |
| `cleaned_ipynb_storage`  | Literal['git', 'dvc'] \| None                | no       | null    |
| `executed_ipynb_storage` | Literal['git', 'dvc'] \| None                | no       | 'dvc'   |
| `html_storage`           | Literal['git', 'dvc'] \| None                | no       | 'dvc'   |
| `parameters`             | dict[str, Any]                               | no       |         |
| `language`               | Literal['python', 'matlab', 'julia'] \| None | no       | null    |

### `latex`

Model class: `LatexStage`

| Kind-specific parameter | Type                          | Required | Default |
| ----------------------- | ----------------------------- | -------- | ------- |
| `target_path`           | str                           | yes      |         |
| `latexmkrc_path`        | str \| None                   | no       | null    |
| `pdf_storage`           | Literal['git', 'dvc'] \| None | no       | 'dvc'   |
| `verbose`               | bool                          | no       | False   |
| `force`                 | bool                          | no       | False   |
| `synctex`               | bool                          | no       | True    |

### `map-paths`

Model class: `MapPathsStage`

| Kind-specific parameter | Type                                                                                                                                                                                                                                                                                                                                                        | Required | Default    |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ---------- |
| `environment`           | str                                                                                                                                                                                                                                                                                                                                                         | no       | '\_system' |
| `paths`                 | list[Annotated[calkit.models.pipeline.MapPathsStage.CopyFileToFile \| calkit.models.pipeline.MapPathsStage.CopyFileToDir \| calkit.models.pipeline.MapPathsStage.DirToDirMerge \| calkit.models.pipeline.MapPathsStage.DirToDirReplace, Discriminator(discriminator='kind', custom_error_type=None, custom_error_message=None, custom_error_context=None)]] | yes      |            |

### `matlab-command`

Model class: `MatlabCommandStage`

| Kind-specific parameter | Type | Required | Default |
| ----------------------- | ---- | -------- | ------- |
| `command`               | str  | yes      |         |

### `matlab-script`

Model class: `MatlabScriptStage`

| Kind-specific parameter | Type                                                                                          | Required | Default |
| ----------------------- | --------------------------------------------------------------------------------------------- | -------- | ------- |
| `script_path`           | str                                                                                           | yes      |         |
| `matlab_path`           | Annotated[str, AfterValidator(func=<function _check_path_relative_and_child_of_cwd>)] \| None | no       | null    |

### `python-script`

Model class: `PythonScriptStage`

| Kind-specific parameter | Type      | Required | Default |
| ----------------------- | --------- | -------- | ------- |
| `script_path`           | str       | yes      |         |
| `args`                  | list[str] | no       |         |

### `r-script`

Model class: `RScriptStage`

| Kind-specific parameter | Type      | Required | Default |
| ----------------------- | --------- | -------- | ------- |
| `script_path`           | str       | yes      |         |
| `args`                  | list[str] | no       |         |

### `sbatch`

Model class: `SBatchStage`

| Kind-specific parameter | Type                          | Required | Default |
| ----------------------- | ----------------------------- | -------- | ------- |
| `script_path`           | str                           | yes      |         |
| `args`                  | list[str]                     | no       |         |
| `sbatch_options`        | list[str]                     | no       |         |
| `log_path`              | str \| None                   | no       | null    |
| `log_storage`           | Literal['git', 'dvc'] \| None | no       | 'git'   |

### `shell-command`

Model class: `ShellCommandStage`

| Kind-specific parameter | Type                         | Required | Default |
| ----------------------- | ---------------------------- | -------- | ------- |
| `command`               | str                          | yes      |         |
| `shell`                 | Literal['sh', 'bash', 'zsh'] | no       | 'bash'  |

### `shell-script`

Model class: `ShellScriptStage`

| Kind-specific parameter | Type                         | Required | Default |
| ----------------------- | ---------------------------- | -------- | ------- |
| `script_path`           | str                          | yes      |         |
| `args`                  | list[str]                    | no       |         |
| `shell`                 | Literal['sh', 'bash', 'zsh'] | no       | 'bash'  |

### `word-to-pdf`

Model class: `WordToPdfStage`

| Kind-specific parameter | Type | Required | Default    |
| ----------------------- | ---- | -------- | ---------- |
| `environment`           | str  | no       | '\_system' |
| `word_doc_path`         | str  | yes      |            |

<!-- AUTO-GENERATED: PIPELINE-STAGE-KINDS:END -->
