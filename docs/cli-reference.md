# CLI reference

## Top-level commands

| Command         | Description                                                                                                                                                                                                                                                                                                                                                                                     |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `init`          | Initialize the current working directory.                                                                                                                                                                                                                                                                                                                                                       |
| `clone`         | Clone or download a copy of a project.                                                                                                                                                                                                                                                                                                                                                          |
| `status`        | View status (project, version control, and/or pipeline).                                                                                                                                                                                                                                                                                                                                        |
| `diff`          | Get a unified Git and DVC diff.                                                                                                                                                                                                                                                                                                                                                                 |
| `add`           | Add paths to the repo. Code will be added to Git and data will be added to DVC. Note: This will enable the 'autostage' feature of DVC, automatically adding any .dvc files to Git when adding to DVC.                                                                                                                                                                                           |
| `commit`        | Commit a change to the repo.                                                                                                                                                                                                                                                                                                                                                                    |
| `save`          | Save paths by committing and pushing. This is essentially git/dvc add, commit, and push in one step.                                                                                                                                                                                                                                                                                            |
| `pull`          | Pull with both Git and DVC.                                                                                                                                                                                                                                                                                                                                                                     |
| `push`          | Push with both Git and DVC.                                                                                                                                                                                                                                                                                                                                                                     |
| `sync`          | Sync the project repo by pulling and then pushing.                                                                                                                                                                                                                                                                                                                                              |
| `ignore`        | Ignore a file, i.e., keep it out of version control.                                                                                                                                                                                                                                                                                                                                            |
| `local-server`  | Run the local server to interact over HTTP.                                                                                                                                                                                                                                                                                                                                                     |
| `run`           | Check dependencies and run the pipeline.                                                                                                                                                                                                                                                                                                                                                        |
| `manual-step`   | Execute a manual step.                                                                                                                                                                                                                                                                                                                                                                          |
| `xenv`          | Execute a command in an environment.                                                                                                                                                                                                                                                                                                                                                            |
| `runenv`        | Execute a command in an environment (alias for 'xenv').                                                                                                                                                                                                                                                                                                                                         |
| `xproc`         | Execute a procedure.                                                                                                                                                                                                                                                                                                                                                                            |
| `runproc`       | Execute a procedure (alias for 'xproc').                                                                                                                                                                                                                                                                                                                                                        |
| `calc`          | Run a project's calculation.                                                                                                                                                                                                                                                                                                                                                                    |
| `set-env-var`   | Set an environmental variable for the project in its '.env' file.                                                                                                                                                                                                                                                                                                                               |
| `upgrade`       | Upgrade Calkit.                                                                                                                                                                                                                                                                                                                                                                                 |
| `switch-branch` | Switch to a different branch.                                                                                                                                                                                                                                                                                                                                                                   |
| `stash`         | Stash or restore workspace changes including dvc-zip tracked dirs. Without --pop: zips any modified workspace dirs into the DVC cache, then git-stashes (saving the updated .dvc files), checks out the committed DVC state, and unzips it to the workspace. With --pop: pops the git stash (restoring the saved .dvc files), checks out the stashed DVC state, and unzips it to the workspace. |
| `dvc`           | Run a command with the DVC CLI. Useful if Calkit is installed as a tool, e.g., with `uv tool` or `pipx`, and DVC is not installed.                                                                                                                                                                                                                                                              |
| `jupyter`       | Run a command with the Jupyter CLI.                                                                                                                                                                                                                                                                                                                                                             |
| `map-paths`     | Map paths in a project. Currently this is done with copying. Outputs are ensured to be ignored by Git.                                                                                                                                                                                                                                                                                          |
| `xr`            | Execute a command and if successful, record in the pipeline.                                                                                                                                                                                                                                                                                                                                    |
| `config`        | Configure Calkit.                                                                                                                                                                                                                                                                                                                                                                               |
| `new`           | Create a new Calkit object.                                                                                                                                                                                                                                                                                                                                                                     |
| `create`        | Create a new Calkit object (alias for 'new').                                                                                                                                                                                                                                                                                                                                                   |
| `nb`            | Work with Jupyter notebooks.                                                                                                                                                                                                                                                                                                                                                                    |
| `list`          | List Calkit objects.                                                                                                                                                                                                                                                                                                                                                                            |
| `describe`      | Describe things.                                                                                                                                                                                                                                                                                                                                                                                |
| `import`        | Import objects.                                                                                                                                                                                                                                                                                                                                                                                 |
| `office`        | Work with Microsoft Office.                                                                                                                                                                                                                                                                                                                                                                     |
| `update`        | Update objects.                                                                                                                                                                                                                                                                                                                                                                                 |
| `check`         | Check things.                                                                                                                                                                                                                                                                                                                                                                                   |
| `latex`         | Work with LaTeX.                                                                                                                                                                                                                                                                                                                                                                                |
| `overleaf`      | Interact with Overleaf.                                                                                                                                                                                                                                                                                                                                                                         |
| `cloud`         | Interact with a Calkit Cloud.                                                                                                                                                                                                                                                                                                                                                                   |
| `slurm`         | Work with SLURM.                                                                                                                                                                                                                                                                                                                                                                                |

## Command groups

### `calkit config`

Configure Calkit.

| Command             | Description                                                                                                                                                                                                 |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `set`               | Set a value in the config.                                                                                                                                                                                  |
| `get`               | Get and print a value from the config.                                                                                                                                                                      |
| `unset`             | Unset a value in the config, returning it to default.                                                                                                                                                       |
| `remote`            | Setup the Calkit cloud as the default DVC remote and store a token in the local config.                                                                                                                     |
| `setup-remote`      | Alias for 'remote'.                                                                                                                                                                                         |
| `remote-auth`       | Store a Calkit cloud token in the local DVC config for all Calkit remotes.                                                                                                                                  |
| `setup-remote-auth` | Alias for 'remote-auth'.                                                                                                                                                                                    |
| `list`              | List keys in the config.                                                                                                                                                                                    |
| `github-ssh`        | Walk through the process of adding an SSH key to GitHub.                                                                                                                                                    |
| `github-codespace`  | Configure a GitHub Codespace. Typically this will simply mean we exchange a GitHub token for a Calkit token to use for pushing with DVC. If this is run outside a Codespace, typically nothing will happen. |

#### `calkit config set`

Set a value in the config.

Usage:

```text
calkit config set KEY VALUE
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `key`    | text | yes      |         |             |
| `value`  | text | yes      |         |             |

#### `calkit config get`

Get and print a value from the config.

Usage:

```text
calkit config get KEY
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `key`    | text | yes      |         |             |

#### `calkit config unset`

Unset a value in the config, returning it to default.

Usage:

```text
calkit config unset KEY
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `key`    | text | yes      |         |             |

#### `calkit config remote`

Setup the Calkit cloud as the default DVC remote and store a token in the local config.

Usage:

```text
calkit config remote [OPTIONS]
```

Options:

| Option        | Type    | Required | Default | Description                                  |
| ------------- | ------- | -------- | ------- | -------------------------------------------- |
| `--ck`        | boolean | no       | False   | Use a ck:// URL for the 'calkit' DVC remote. |
| `--no-commit` | boolean | no       | False   | Do not commit changes to DVC config.         |

#### `calkit config setup-remote`

Alias for 'remote'.

Usage:

```text
calkit config setup-remote [OPTIONS]
```

Options:

| Option        | Type    | Required | Default | Description                                  |
| ------------- | ------- | -------- | ------- | -------------------------------------------- |
| `--ck`        | boolean | no       | False   | Use a ck:// URL for the 'calkit' DVC remote. |
| `--no-commit` | boolean | no       | False   | Do not commit changes to DVC config.         |

#### `calkit config remote-auth`

Store a Calkit cloud token in the local DVC config for all Calkit remotes.

Usage:

```text
calkit config remote-auth
```

#### `calkit config setup-remote-auth`

Alias for 'remote-auth'.

Usage:

```text
calkit config setup-remote-auth
```

#### `calkit config list`

List keys in the config.

Usage:

```text
calkit config list
```

#### `calkit config github-ssh`

Walk through the process of adding an SSH key to GitHub.

Usage:

```text
calkit config github-ssh
```

#### `calkit config github-codespace`

Configure a GitHub Codespace. Typically this will simply mean we exchange a GitHub token for a Calkit token to use for pushing with DVC. If this is run outside a Codespace, typically nothing will happen.

Usage:

```text
calkit config github-codespace
```

### `calkit new`

Create a new Calkit object.

| Command                  | Description                                                                                                                   |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `project`                | Create a new project.                                                                                                         |
| `figure`                 | Create a new figure.                                                                                                          |
| `question`               | Add a new question.                                                                                                           |
| `notebook`               | Add a new notebook.                                                                                                           |
| `docker-env`             | Create a new Docker environment.                                                                                              |
| `foreach-stage`          | Create a new DVC 'foreach' stage. The list of values must be a simple list. For more complex objects, edit dvc.yaml directly. |
| `dataset`                | Create a new dataset.                                                                                                         |
| `publication`            | Create a new publication.                                                                                                     |
| `conda-env`              | Create a new Conda environment.                                                                                               |
| `uv-env`                 | Create a new uv project environment.                                                                                          |
| `slurm-env`              | Create a new SLURM environment.                                                                                               |
| `uv-venv`                | Create a new uv virtual environment.                                                                                          |
| `venv`                   | Create a new Python virtual environment with venv.                                                                            |
| `pixi-env`               | Create a new pixi virtual environment.                                                                                        |
| `julia-env`              | Create a new Julia environment or add an existing one to calkit.yaml.                                                         |
| `renv`                   | Create a new R environment with renv.                                                                                         |
| `status`                 | Add a new project status to the log.                                                                                          |
| `python-script-stage`    | Add a stage to the pipeline that runs a Python script.                                                                        |
| `julia-script-stage`     | Add a stage to the pipeline that runs a Julia script.                                                                         |
| `matlab-script-stage`    | Add a stage to the pipeline that runs a MATLAB script.                                                                        |
| `latex-stage`            | Add a stage to the pipeline that compiles a LaTeX document.                                                                   |
| `jupyter-notebook-stage` | Add a stage to the pipeline that runs a Jupyter notebook.                                                                     |
| `release`                | Create a new release.                                                                                                         |

#### `calkit new project`

Create a new project.

Usage:

```text
calkit new project [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description                  |
| -------- | ---- | -------- | ------- | ---------------------------- |
| `path`   | text | yes      |         | Where to create the project. |

Options:

| Option              | Type    | Required | Default | Description                                                                   |
| ------------------- | ------- | -------- | ------- | ----------------------------------------------------------------------------- |
| `--name`, `-n`      | text    | no       |         | Project name. Will be inferred as kebab-cased directory name if not provided. |
| `--title`           | text    | no       |         | Project title.                                                                |
| `--description`     | text    | no       |         | Project description.                                                          |
| `--cloud`           | boolean | no       | False   | Create this project in the cloud (Calkit and GitHub.)                         |
| `--public`          | boolean | no       | False   | Create as a public project if --cloud is selected.                            |
| `--git-url`         | text    | no       |         | Git repo URL. Usually https://github.com/{your_name}/{project_name}.          |
| `--template`, `-t`  | text    | no       |         | Template from which to derive the project, e.g., 'calkit/example-basic'.      |
| `--no-commit`       | boolean | no       |         | Do not commit changes to Git.                                                 |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite project if one already exists.                                      |

#### `calkit new figure`

Create a new figure.

Usage:

```text
calkit new figure [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `path`   | text | yes      |         |             |

Options:

| Option                   | Type    | Required | Default | Description                                                    |
| ------------------------ | ------- | -------- | ------- | -------------------------------------------------------------- |
| `--title`                | text    | yes      |         |                                                                |
| `--description`          | text    | yes      |         |                                                                |
| `--stage`                | text    | no       |         | Name of the pipeline stage that generates this figure.         |
| `--cmd`                  | text    | no       |         | Command to add to the stage, if specified.                     |
| `--dep`                  | text    | no       |         | Path to stage dependency.                                      |
| `--out`                  | text    | no       |         | Path to stage output. Figure path will be added automatically. |
| `--deps-from-stage-outs` | text    | no       |         | Stage name from which to add outputs as dependencies.          |
| `--no-commit`            | boolean | no       | False   |                                                                |
| `--overwrite`, `-f`      | boolean | no       | False   | Overwrite existing figure if one exists.                       |

#### `calkit new question`

Add a new question.

Usage:

```text
calkit new question [OPTIONS] QUESTION
```

Arguments:

| Argument   | Type | Required | Default | Description |
| ---------- | ---- | -------- | ------- | ----------- |
| `question` | text | yes      |         |             |

Options:

| Option     | Type    | Required | Default | Description |
| ---------- | ------- | -------- | ------- | ----------- |
| `--commit` | boolean | no       | False   |             |

#### `calkit new notebook`

Add a new notebook.

Usage:

```text
calkit new notebook [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description              |
| -------- | ---- | -------- | ------- | ------------------------ |
| `path`   | text | yes      |         | Notebook path (relative) |

Options:

| Option          | Type    | Required | Default | Description                                         |
| --------------- | ------- | -------- | ------- | --------------------------------------------------- |
| `--title`       | text    | yes      |         |                                                     |
| `--description` | text    | no       |         |                                                     |
| `--stage`       | text    | no       |         | Name of the pipeline stage that runs this notebook. |
| `--commit`      | boolean | no       | False   |                                                     |

#### `calkit new docker-env`

Create a new Docker environment.

Usage:

```text
calkit new docker-env [OPTIONS]
```

Options:

| Option              | Type    | Required | Default | Description                                                                                                                 |
| ------------------- | ------- | -------- | ------- | --------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`      | text    | yes      |         | Environment name.                                                                                                           |
| `--image`           | text    | no       |         | Image identifier. Should be unique and descriptive. Will default to environment name if not specified.                      |
| `--from`            | text    | no       |         | Base image, e.g., 'ubuntu', if creating a Dockerfile.                                                                       |
| `--path`            | text    | no       |         | Dockerfile path. Will default to 'Dockerfile' if --from is specified.                                                       |
| `--add-layer`       | text    | no       |         | Add a layer (options: miniforge, foampy, uv, julia).                                                                        |
| `--env-var`         | text    | no       |         | Environment variables to set in the container.                                                                              |
| `--gpus`            | text    | no       |         |                                                                                                                             |
| `--arg`             | text    | no       |         | Arguments to use when running container.                                                                                    |
| `--dep`             | text    | no       |         | Path to add as a dependency, i.e., a file that gets added to the container.                                                 |
| `--wdir`            | text    | no       | /work   | Working directory.                                                                                                          |
| `--command-mode`    | text    | no       | shell   | How to execute commands in the container: 'shell' runs shell -c, 'entrypoint' passes args directly to the image entrypoint. |
| `--user`            | text    | no       |         | User account to use to run the container.                                                                                   |
| `--platform`        | text    | no       |         | Which platform(s) to build for.                                                                                             |
| `--port`            | text    | no       |         | Ports to expose in the container, e.g., '8080:80'. Can be specified multiple times.                                         |
| `--description`     | text    | no       |         | Description.                                                                                                                |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite any existing environment with this name.                                                                          |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                                                                                      |
| `--no-check`        | boolean | no       | False   | Do not check environment is up-to-date after creation.                                                                      |

#### `calkit new foreach-stage`

Create a new DVC 'foreach' stage. The list of values must be a simple list. For more complex objects, edit dvc.yaml directly.

Usage:

```text
calkit new foreach-stage [OPTIONS] VALS...
```

Arguments:

| Argument | Type | Required | Default | Description            |
| -------- | ---- | -------- | ------- | ---------------------- |
| `vals`   | text | yes      |         | Values to iterate over |

Options:

| Option              | Type    | Required | Default | Description                                              |
| ------------------- | ------- | -------- | ------- | -------------------------------------------------------- |
| `--cmd`             | text    | yes      |         | Command to run. Can include {var} to fill with variable. |
| `--name`, `-n`      | text    | yes      |         | Stage name.                                              |
| `--dep`             | text    | no       |         | Path to add as a dependency.                             |
| `--out`             | text    | no       |         | Path to add as an output.                                |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite stage if one already exists.                   |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                   |

#### `calkit new dataset`

Create a new dataset.

Usage:

```text
calkit new dataset [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `path`   | text | yes      |         |             |

Options:

| Option                   | Type    | Required | Default | Description                                                     |
| ------------------------ | ------- | -------- | ------- | --------------------------------------------------------------- |
| `--title`                | text    | yes      |         |                                                                 |
| `--description`          | text    | yes      |         |                                                                 |
| `--stage`                | text    | no       |         | Name of the pipeline stage that generates this dataset.         |
| `--cmd`                  | text    | no       |         | Command to add to the stage, if specified.                      |
| `--dep`                  | text    | no       |         | Path to stage dependency.                                       |
| `--out`                  | text    | no       |         | Path to stage output. Dataset path will be added automatically. |
| `--deps-from-stage-outs` | text    | no       |         | Stage name from which to add outputs as dependencies.           |
| `--no-commit`            | boolean | no       | False   |                                                                 |
| `--overwrite`, `-f`      | boolean | no       | False   | Overwrite existing dataset if one exists.                       |

#### `calkit new publication`

Create a new publication.

Usage:

```text
calkit new publication [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description                                                               |
| -------- | ---- | -------- | ------- | ------------------------------------------------------------------------- |
| `path`   | text | yes      |         | Path for the publication. If using a template, this could be a directory. |

Options:

| Option                   | Type    | Required | Default | Description                                                                            |
| ------------------------ | ------- | -------- | ------- | -------------------------------------------------------------------------------------- |
| `--title`                | text    | yes      |         | The title of the publication.                                                          |
| `--description`          | text    | yes      |         | A description of the publication.                                                      |
| `--kind`                 | text    | yes      |         | Kind of the publication, e.g., 'journal-article'.                                      |
| `--stage`                | text    | no       |         | Name of the pipeline stage to build the output file.                                   |
| `--dep`                  | text    | no       |         | Path to stage dependency.                                                              |
| `--deps-from-stage-outs` | text    | no       |         | Stage name from which to add outputs as dependencies.                                  |
| `--template`, `-t`       | text    | no       |         | Template with which to create the source files. Should be in the format {type}/{name}. |
| `--environment`          | text    | no       |         | Name of the build environment to create, if desired.                                   |
| `--no-commit`            | boolean | no       | False   | Do not commit resulting changes to the repo.                                           |
| `--overwrite`, `-f`      | boolean | no       | False   | Overwrite existing objects if they already exist.                                      |

#### `calkit new conda-env`

Create a new Conda environment.

Usage:

```text
calkit new conda-env [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | text | no       |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default         | Description                                                                                                                                                                                     |
| ------------------- | ------- | -------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`      | text    | yes      |                 | Environment name.                                                                                                                                                                               |
| `--conda-name`      | text    | no       |                 | Name to use in the Conda environment file, if desired. Will be automatically generated if not provided. Note that these should be unique since Conda environments are a system-wide collection. |
| `--path`            | text    | no       | environment.yml | Environment YAML file path.                                                                                                                                                                     |
| `--pip`             | text    | no       |                 | Packages to install with pip.                                                                                                                                                                   |
| `--prefix`          | text    | no       |                 | Prefix for environment location.                                                                                                                                                                |
| `--description`     | text    | no       |                 | Description.                                                                                                                                                                                    |
| `--overwrite`, `-f` | boolean | no       | False           | Overwrite any existing environment with this name.                                                                                                                                              |
| `--no-commit`       | boolean | no       | False           | Do not commit changes.                                                                                                                                                                          |
| `--no-check`        | boolean | no       | False           | Do not check environment is up-to-date after creation.                                                                                                                                          |

#### `calkit new uv-env`

Create a new uv project environment.

Usage:

```text
calkit new uv-env [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | text | no       |         | Packages to include in the environment. |

Options:

| Option           | Type    | Required | Default | Description                                            |
| ---------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--name`, `-n`   | text    | no       | main    | Environment name.                                      |
| `--path`         | text    | no       |         | Environment file path. Must end with 'pyproject.toml'. |
| `--python`, `-p` | text    | no       |         | Python version.                                        |
| `--no-check`     | boolean | no       | False   | Do not check environment is up-to-date after creation. |
| `--no-commit`    | boolean | no       | False   | Do not commit changes.                                 |

#### `calkit new slurm-env`

Create a new SLURM environment.

Usage:

```text
calkit new slurm-env [OPTIONS]
```

Options:

| Option              | Type    | Required | Default   | Description                                                                            |
| ------------------- | ------- | -------- | --------- | -------------------------------------------------------------------------------------- |
| `--name`, `-n`      | text    | yes      |           | Environment name.                                                                      |
| `--host`            | text    | no       | localhost | Host where SLURM commands should run.                                                  |
| `--default-option`  | text    | no       |           | Default sbatch/srun option string (for example --gpus=1). Repeat for multiple options. |
| `--description`     | text    | no       |           | Description.                                                                           |
| `--overwrite`, `-f` | boolean | no       | False     | Overwrite any existing environment with this name.                                     |
| `--no-commit`       | boolean | no       | False     | Do not commit changes.                                                                 |

#### `calkit new uv-venv`

Create a new uv virtual environment.

Usage:

```text
calkit new uv-venv [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | text | no       |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default          | Description                                            |
| ------------------- | ------- | -------- | ---------------- | ------------------------------------------------------ |
| `--name`, `-n`      | text    | yes      |                  | Environment name.                                      |
| `--path`            | text    | no       | requirements.txt | Path for requirements file.                            |
| `--prefix`          | text    | no       | .venv            | Prefix for environment location.                       |
| `--python`, `-p`    | text    | no       | 3.14             | Python version.                                        |
| `--description`     | text    | no       |                  | Description.                                           |
| `--overwrite`, `-f` | boolean | no       | False            | Overwrite any existing environment with this name.     |
| `--no-commit`       | boolean | no       | False            | Do not commit changes.                                 |
| `--no-check`        | boolean | no       | False            | Do not check environment is up-to-date after creation. |

#### `calkit new venv`

Create a new Python virtual environment with venv.

Usage:

```text
calkit new venv [OPTIONS] PACKAGES...
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | text | yes      |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default          | Description                                            |
| ------------------- | ------- | -------- | ---------------- | ------------------------------------------------------ |
| `--name`, `-n`      | text    | yes      |                  | Environment name.                                      |
| `--path`            | text    | no       | requirements.txt | Path for requirements file.                            |
| `--prefix`          | text    | no       | .venv            | Prefix for environment location.                       |
| `--description`     | text    | no       |                  | Description.                                           |
| `--overwrite`, `-f` | boolean | no       | False            | Overwrite any existing environment with this name.     |
| `--no-commit`       | boolean | no       | False            | Do not commit changes.                                 |
| `--no-check`        | boolean | no       | False            | Do not check environment is up-to-date after creation. |

#### `calkit new pixi-env`

Create a new pixi virtual environment.

Usage:

```text
calkit new pixi-env [OPTIONS] PACKAGES...
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | text | yes      |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default | Description                                            |
| ------------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--name`, `-n`      | text    | yes      |         | Environment name.                                      |
| `--pip`             | text    | no       |         | Packages to install with pip.                          |
| `--description`     | text    | no       |         | Description.                                           |
| `--platform`, `-p`  | text    | no       |         | Platform.                                              |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite any existing environment with this name.     |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                 |
| `--no-check`        | boolean | no       | False   | Do not check environment is up-to-date after creation. |

#### `calkit new julia-env`

Create a new Julia environment or add an existing one to calkit.yaml.

Usage:

```text
calkit new julia-env [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                                      |
| ---------- | ---- | -------- | ------- | ------------------------------------------------ |
| `packages` | text | no       |         | Optional packages to include in the environment. |

Options:

| Option              | Type    | Required | Default | Description                                            |
| ------------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--name`, `-n`      | text    | no       | main    | Environment name.                                      |
| `--path`            | text    | no       |         | Path for Project.toml file.                            |
| `--description`     | text    | no       |         | Description.                                           |
| `--julia`, `-j`     | text    | no       |         | Julia version. Auto-detected if not supplied.          |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite any existing environment with this name.     |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                 |
| `--no-check`        | boolean | no       | False   | Do not check environment is up-to-date after creation. |

#### `calkit new renv`

Create a new R environment with renv.

Usage:

```text
calkit new renv [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | text | no       |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default | Description                                            |
| ------------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--name`, `-n`      | text    | no       | main    | Environment name.                                      |
| `--path`            | text    | no       |         | Environment file path. Must end with 'DESCRIPTION'.    |
| `--r-version`, `-r` | text    | no       |         | R version.                                             |
| `--description`     | text    | no       |         | Description.                                           |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite any existing environment with this name.     |
| `--no-check`        | boolean | no       | False   | Do not check environment is up-to-date after creation. |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                 |

#### `calkit new status`

Add a new project status to the log.

Usage:

```text
calkit new status [OPTIONS] STATUS
```

Arguments:

| Argument | Type                                    | Required | Default | Description                    |
| -------- | --------------------------------------- | -------- | ------- | ------------------------------ |
| `status` | choice(in-progress, on-hold, completed) | yes      |         | Current status of the project. |

Options:

| Option            | Type    | Required | Default | Description                              |
| ----------------- | ------- | -------- | ------- | ---------------------------------------- |
| `--message`, `-m` | text    | no       |         | Optional message describing the status.  |
| `--no-commit`     | boolean | no       | False   | Do not commit changes to the status log. |

#### `calkit new python-script-stage`

Add a stage to the pipeline that runs a Python script.

Usage:

```text
calkit new python-script-stage [OPTIONS]
```

Options:

| Option                         | Type        | Required | Default | Description                                                                                                    |
| ------------------------------ | ----------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | text        | yes      |         | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | text        | yes      |         | Environment to use to run the stage.                                                                           |
| `--script-path`, `-s`          | text        | yes      |         | Path to script.                                                                                                |
| `--arg`                        | text        | no       |         | Argument to pass to the script.                                                                                |
| `--input`, `-i`                | text        | no       |         | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | text        | no       |         | A path that is produced by the stage.                                                                          |
| `--out-git`                    | text        | no       |         | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | text        | no       |         | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | text        | no       |         | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | text        | no       |         | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | text        | no       |         | An output that should not be stored in version control, and should not be deleted before running.              |
| `--iter`                       | <text text> | no       |         | Iterate over an argument with a comma-separated list, e.g., --iter-arg var_name val1,val2,val3.                |
| `--overwrite`, `--force`, `-f` | boolean     | no       | False   | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean     | no       | False   | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean     | no       | False   | Do not commit changes to Git.                                                                                  |

#### `calkit new julia-script-stage`

Add a stage to the pipeline that runs a Julia script.

Usage:

```text
calkit new julia-script-stage [OPTIONS]
```

Options:

| Option                         | Type        | Required | Default | Description                                                                                                    |
| ------------------------------ | ----------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | text        | yes      |         | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | text        | yes      |         | Environment to use to run the stage.                                                                           |
| `--script-path`, `-s`          | text        | yes      |         | Path to script.                                                                                                |
| `--input`, `-i`                | text        | no       |         | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | text        | no       |         | A path that is produced by the stage.                                                                          |
| `--out-git`                    | text        | no       |         | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | text        | no       |         | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | text        | no       |         | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | text        | no       |         | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | text        | no       |         | An output that should not be stored in version control, and should not be deleted before running.              |
| `--iter`                       | <text text> | no       |         | Iterate over an argument with a comma-separated list, e.g., --iter-arg var_name val1,val2,val3.                |
| `--overwrite`, `--force`, `-f` | boolean     | no       | False   | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean     | no       | False   | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean     | no       | False   | Do not commit changes to Git.                                                                                  |

#### `calkit new matlab-script-stage`

Add a stage to the pipeline that runs a MATLAB script.

Usage:

```text
calkit new matlab-script-stage [OPTIONS]
```

Options:

| Option                         | Type    | Required | Default | Description                                                                                                    |
| ------------------------------ | ------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | text    | yes      |         | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | text    | yes      |         | Environment to use to run the stage.                                                                           |
| `--script-path`, `-s`          | text    | yes      |         | Path to script.                                                                                                |
| `--input`, `-i`                | text    | no       |         | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | text    | no       |         | A path that is produced by the stage.                                                                          |
| `--out-git`                    | text    | no       |         | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | text    | no       |         | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | text    | no       |         | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | text    | no       |         | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | text    | no       |         | An output that should not be stored in version control, and should not be deleted before running.              |
| `--overwrite`, `--force`, `-f` | boolean | no       | False   | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean | no       | False   | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean | no       | False   | Do not commit changes to Git.                                                                                  |

#### `calkit new latex-stage`

Add a stage to the pipeline that compiles a LaTeX document.

Usage:

```text
calkit new latex-stage [OPTIONS]
```

Options:

| Option                         | Type    | Required | Default | Description                                                                                                    |
| ------------------------------ | ------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | text    | yes      |         | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | text    | yes      |         | Environment to use to run the stage.                                                                           |
| `--target`                     | text    | yes      |         | Target .tex file path.                                                                                         |
| `--input`, `-i`                | text    | no       |         | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | text    | no       |         | A path that is produced by the stage.                                                                          |
| `--out-git`                    | text    | no       |         | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | text    | no       |         | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | text    | no       |         | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | text    | no       |         | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | text    | no       |         | An output that should not be stored in version control, and should not be deleted before running.              |
| `--overwrite`, `--force`, `-f` | boolean | no       | False   | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean | no       | False   | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean | no       | False   | Do not commit changes to Git.                                                                                  |

#### `calkit new jupyter-notebook-stage`

Add a stage to the pipeline that runs a Jupyter notebook.

Usage:

```text
calkit new jupyter-notebook-stage [OPTIONS]
```

Options:

| Option                         | Type                   | Required | Default             | Description                                                                                                    |
| ------------------------------ | ---------------------- | -------- | ------------------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | text                   | yes      |                     | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | text                   | yes      |                     | Environment to use to run the stage.                                                                           |
| `--notebook-path`              | text                   | yes      |                     | Path to notebook.                                                                                              |
| `--input`, `-i`                | text                   | no       |                     | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | text                   | no       |                     | A path that is produced by the stage.                                                                          |
| `--out-git`                    | text                   | no       |                     | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | text                   | no       |                     | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | text                   | no       |                     | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | text                   | no       |                     | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | text                   | no       |                     | An output that should not be stored in version control, and should not be deleted before running.              |
| `--html-storage`               | choice(git, dvc, None) | no       | NotebookStorage.dvc | In what system to store the HTML output of the notebook.                                                       |
| `--cleaned-ipynb-storage`      | choice(git, dvc, None) | no       | NotebookStorage.git | In what system to store the cleaned ipynb output of the notebook.                                              |
| `--executed-ipynb-storage`     | choice(git, dvc, None) | no       | NotebookStorage.dvc | In what system to store the executed ipynb output of the notebook.                                             |
| `--overwrite`, `--force`, `-f` | boolean                | no       | False               | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean                | no       | False               | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean                | no       | False               | Do not commit changes to Git.                                                                                  |

#### `calkit new release`

Create a new release.

Usage:

```text
calkit new release [OPTIONS] [PATH]
```

Arguments:

| Argument | Type | Required | Default | Description                                     |
| -------- | ---- | -------- | ------- | ----------------------------------------------- |
| `path`   | text | no       | .       | The path to release; '.' for a project release. |

Options:

| Option                    | Type    | Required | Default | Description                                                                                                                |
| ------------------------- | ------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`            | text    | yes      |         | A name for the release, typically kebab-case or a semantic version. Will be used for the Git tag and GitHub release title. |
| `--kind`                  | text    | no       | project | What kind of release to create.                                                                                            |
| `--description`, `--desc` | text    | no       |         | A description of the release. Will be auto-generated if not provided.                                                      |
| `--date`                  | text    | no       |         | Release date. Will default to today.                                                                                       |
| `--dry-run`               | boolean | no       | False   | Only print actions that would be taken but don't take them.                                                                |
| `--no-commit`             | boolean | no       | False   | Do not commit changes to Git repo.                                                                                         |
| `--no-push`               | boolean | no       | False   | Do not push to Git remote.                                                                                                 |
| `--no-github`             | boolean | no       | False   | Do not create a GitHub release.                                                                                            |
| `--to`                    | text    | no       | zenodo  | Archival service to use (zenodo or caltechdata).                                                                           |
| `--draft`                 | boolean | no       | False   | Create draft record with reserved DOI but do not publish.                                                                  |
| `--license`               | text    | no       |         | License ID (from https://spdx.org/licenses). Multiple can be specified. Will try to infer from LICENSE file, if present.   |
| `--verbose`, `-v`         | boolean | no       | False   | Print verbose output.                                                                                                      |

### `calkit create`

Create a new Calkit object (alias for 'new').

| Command                  | Description                                                                                                                   |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `project`                | Create a new project.                                                                                                         |
| `figure`                 | Create a new figure.                                                                                                          |
| `question`               | Add a new question.                                                                                                           |
| `notebook`               | Add a new notebook.                                                                                                           |
| `docker-env`             | Create a new Docker environment.                                                                                              |
| `foreach-stage`          | Create a new DVC 'foreach' stage. The list of values must be a simple list. For more complex objects, edit dvc.yaml directly. |
| `dataset`                | Create a new dataset.                                                                                                         |
| `publication`            | Create a new publication.                                                                                                     |
| `conda-env`              | Create a new Conda environment.                                                                                               |
| `uv-env`                 | Create a new uv project environment.                                                                                          |
| `slurm-env`              | Create a new SLURM environment.                                                                                               |
| `uv-venv`                | Create a new uv virtual environment.                                                                                          |
| `venv`                   | Create a new Python virtual environment with venv.                                                                            |
| `pixi-env`               | Create a new pixi virtual environment.                                                                                        |
| `julia-env`              | Create a new Julia environment or add an existing one to calkit.yaml.                                                         |
| `renv`                   | Create a new R environment with renv.                                                                                         |
| `status`                 | Add a new project status to the log.                                                                                          |
| `python-script-stage`    | Add a stage to the pipeline that runs a Python script.                                                                        |
| `julia-script-stage`     | Add a stage to the pipeline that runs a Julia script.                                                                         |
| `matlab-script-stage`    | Add a stage to the pipeline that runs a MATLAB script.                                                                        |
| `latex-stage`            | Add a stage to the pipeline that compiles a LaTeX document.                                                                   |
| `jupyter-notebook-stage` | Add a stage to the pipeline that runs a Jupyter notebook.                                                                     |
| `release`                | Create a new release.                                                                                                         |

#### `calkit create project`

Create a new project.

Usage:

```text
calkit create project [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description                  |
| -------- | ---- | -------- | ------- | ---------------------------- |
| `path`   | text | yes      |         | Where to create the project. |

Options:

| Option              | Type    | Required | Default | Description                                                                   |
| ------------------- | ------- | -------- | ------- | ----------------------------------------------------------------------------- |
| `--name`, `-n`      | text    | no       |         | Project name. Will be inferred as kebab-cased directory name if not provided. |
| `--title`           | text    | no       |         | Project title.                                                                |
| `--description`     | text    | no       |         | Project description.                                                          |
| `--cloud`           | boolean | no       | False   | Create this project in the cloud (Calkit and GitHub.)                         |
| `--public`          | boolean | no       | False   | Create as a public project if --cloud is selected.                            |
| `--git-url`         | text    | no       |         | Git repo URL. Usually https://github.com/{your_name}/{project_name}.          |
| `--template`, `-t`  | text    | no       |         | Template from which to derive the project, e.g., 'calkit/example-basic'.      |
| `--no-commit`       | boolean | no       |         | Do not commit changes to Git.                                                 |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite project if one already exists.                                      |

#### `calkit create figure`

Create a new figure.

Usage:

```text
calkit create figure [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `path`   | text | yes      |         |             |

Options:

| Option                   | Type    | Required | Default | Description                                                    |
| ------------------------ | ------- | -------- | ------- | -------------------------------------------------------------- |
| `--title`                | text    | yes      |         |                                                                |
| `--description`          | text    | yes      |         |                                                                |
| `--stage`                | text    | no       |         | Name of the pipeline stage that generates this figure.         |
| `--cmd`                  | text    | no       |         | Command to add to the stage, if specified.                     |
| `--dep`                  | text    | no       |         | Path to stage dependency.                                      |
| `--out`                  | text    | no       |         | Path to stage output. Figure path will be added automatically. |
| `--deps-from-stage-outs` | text    | no       |         | Stage name from which to add outputs as dependencies.          |
| `--no-commit`            | boolean | no       | False   |                                                                |
| `--overwrite`, `-f`      | boolean | no       | False   | Overwrite existing figure if one exists.                       |

#### `calkit create question`

Add a new question.

Usage:

```text
calkit create question [OPTIONS] QUESTION
```

Arguments:

| Argument   | Type | Required | Default | Description |
| ---------- | ---- | -------- | ------- | ----------- |
| `question` | text | yes      |         |             |

Options:

| Option     | Type    | Required | Default | Description |
| ---------- | ------- | -------- | ------- | ----------- |
| `--commit` | boolean | no       | False   |             |

#### `calkit create notebook`

Add a new notebook.

Usage:

```text
calkit create notebook [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description              |
| -------- | ---- | -------- | ------- | ------------------------ |
| `path`   | text | yes      |         | Notebook path (relative) |

Options:

| Option          | Type    | Required | Default | Description                                         |
| --------------- | ------- | -------- | ------- | --------------------------------------------------- |
| `--title`       | text    | yes      |         |                                                     |
| `--description` | text    | no       |         |                                                     |
| `--stage`       | text    | no       |         | Name of the pipeline stage that runs this notebook. |
| `--commit`      | boolean | no       | False   |                                                     |

#### `calkit create docker-env`

Create a new Docker environment.

Usage:

```text
calkit create docker-env [OPTIONS]
```

Options:

| Option              | Type    | Required | Default | Description                                                                                                                 |
| ------------------- | ------- | -------- | ------- | --------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`      | text    | yes      |         | Environment name.                                                                                                           |
| `--image`           | text    | no       |         | Image identifier. Should be unique and descriptive. Will default to environment name if not specified.                      |
| `--from`            | text    | no       |         | Base image, e.g., 'ubuntu', if creating a Dockerfile.                                                                       |
| `--path`            | text    | no       |         | Dockerfile path. Will default to 'Dockerfile' if --from is specified.                                                       |
| `--add-layer`       | text    | no       |         | Add a layer (options: miniforge, foampy, uv, julia).                                                                        |
| `--env-var`         | text    | no       |         | Environment variables to set in the container.                                                                              |
| `--gpus`            | text    | no       |         |                                                                                                                             |
| `--arg`             | text    | no       |         | Arguments to use when running container.                                                                                    |
| `--dep`             | text    | no       |         | Path to add as a dependency, i.e., a file that gets added to the container.                                                 |
| `--wdir`            | text    | no       | /work   | Working directory.                                                                                                          |
| `--command-mode`    | text    | no       | shell   | How to execute commands in the container: 'shell' runs shell -c, 'entrypoint' passes args directly to the image entrypoint. |
| `--user`            | text    | no       |         | User account to use to run the container.                                                                                   |
| `--platform`        | text    | no       |         | Which platform(s) to build for.                                                                                             |
| `--port`            | text    | no       |         | Ports to expose in the container, e.g., '8080:80'. Can be specified multiple times.                                         |
| `--description`     | text    | no       |         | Description.                                                                                                                |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite any existing environment with this name.                                                                          |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                                                                                      |
| `--no-check`        | boolean | no       | False   | Do not check environment is up-to-date after creation.                                                                      |

#### `calkit create foreach-stage`

Create a new DVC 'foreach' stage. The list of values must be a simple list. For more complex objects, edit dvc.yaml directly.

Usage:

```text
calkit create foreach-stage [OPTIONS] VALS...
```

Arguments:

| Argument | Type | Required | Default | Description            |
| -------- | ---- | -------- | ------- | ---------------------- |
| `vals`   | text | yes      |         | Values to iterate over |

Options:

| Option              | Type    | Required | Default | Description                                              |
| ------------------- | ------- | -------- | ------- | -------------------------------------------------------- |
| `--cmd`             | text    | yes      |         | Command to run. Can include {var} to fill with variable. |
| `--name`, `-n`      | text    | yes      |         | Stage name.                                              |
| `--dep`             | text    | no       |         | Path to add as a dependency.                             |
| `--out`             | text    | no       |         | Path to add as an output.                                |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite stage if one already exists.                   |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                   |

#### `calkit create dataset`

Create a new dataset.

Usage:

```text
calkit create dataset [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `path`   | text | yes      |         |             |

Options:

| Option                   | Type    | Required | Default | Description                                                     |
| ------------------------ | ------- | -------- | ------- | --------------------------------------------------------------- |
| `--title`                | text    | yes      |         |                                                                 |
| `--description`          | text    | yes      |         |                                                                 |
| `--stage`                | text    | no       |         | Name of the pipeline stage that generates this dataset.         |
| `--cmd`                  | text    | no       |         | Command to add to the stage, if specified.                      |
| `--dep`                  | text    | no       |         | Path to stage dependency.                                       |
| `--out`                  | text    | no       |         | Path to stage output. Dataset path will be added automatically. |
| `--deps-from-stage-outs` | text    | no       |         | Stage name from which to add outputs as dependencies.           |
| `--no-commit`            | boolean | no       | False   |                                                                 |
| `--overwrite`, `-f`      | boolean | no       | False   | Overwrite existing dataset if one exists.                       |

#### `calkit create publication`

Create a new publication.

Usage:

```text
calkit create publication [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description                                                               |
| -------- | ---- | -------- | ------- | ------------------------------------------------------------------------- |
| `path`   | text | yes      |         | Path for the publication. If using a template, this could be a directory. |

Options:

| Option                   | Type    | Required | Default | Description                                                                            |
| ------------------------ | ------- | -------- | ------- | -------------------------------------------------------------------------------------- |
| `--title`                | text    | yes      |         | The title of the publication.                                                          |
| `--description`          | text    | yes      |         | A description of the publication.                                                      |
| `--kind`                 | text    | yes      |         | Kind of the publication, e.g., 'journal-article'.                                      |
| `--stage`                | text    | no       |         | Name of the pipeline stage to build the output file.                                   |
| `--dep`                  | text    | no       |         | Path to stage dependency.                                                              |
| `--deps-from-stage-outs` | text    | no       |         | Stage name from which to add outputs as dependencies.                                  |
| `--template`, `-t`       | text    | no       |         | Template with which to create the source files. Should be in the format {type}/{name}. |
| `--environment`          | text    | no       |         | Name of the build environment to create, if desired.                                   |
| `--no-commit`            | boolean | no       | False   | Do not commit resulting changes to the repo.                                           |
| `--overwrite`, `-f`      | boolean | no       | False   | Overwrite existing objects if they already exist.                                      |

#### `calkit create conda-env`

Create a new Conda environment.

Usage:

```text
calkit create conda-env [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | text | no       |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default         | Description                                                                                                                                                                                     |
| ------------------- | ------- | -------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`      | text    | yes      |                 | Environment name.                                                                                                                                                                               |
| `--conda-name`      | text    | no       |                 | Name to use in the Conda environment file, if desired. Will be automatically generated if not provided. Note that these should be unique since Conda environments are a system-wide collection. |
| `--path`            | text    | no       | environment.yml | Environment YAML file path.                                                                                                                                                                     |
| `--pip`             | text    | no       |                 | Packages to install with pip.                                                                                                                                                                   |
| `--prefix`          | text    | no       |                 | Prefix for environment location.                                                                                                                                                                |
| `--description`     | text    | no       |                 | Description.                                                                                                                                                                                    |
| `--overwrite`, `-f` | boolean | no       | False           | Overwrite any existing environment with this name.                                                                                                                                              |
| `--no-commit`       | boolean | no       | False           | Do not commit changes.                                                                                                                                                                          |
| `--no-check`        | boolean | no       | False           | Do not check environment is up-to-date after creation.                                                                                                                                          |

#### `calkit create uv-env`

Create a new uv project environment.

Usage:

```text
calkit create uv-env [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | text | no       |         | Packages to include in the environment. |

Options:

| Option           | Type    | Required | Default | Description                                            |
| ---------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--name`, `-n`   | text    | no       | main    | Environment name.                                      |
| `--path`         | text    | no       |         | Environment file path. Must end with 'pyproject.toml'. |
| `--python`, `-p` | text    | no       |         | Python version.                                        |
| `--no-check`     | boolean | no       | False   | Do not check environment is up-to-date after creation. |
| `--no-commit`    | boolean | no       | False   | Do not commit changes.                                 |

#### `calkit create slurm-env`

Create a new SLURM environment.

Usage:

```text
calkit create slurm-env [OPTIONS]
```

Options:

| Option              | Type    | Required | Default   | Description                                                                            |
| ------------------- | ------- | -------- | --------- | -------------------------------------------------------------------------------------- |
| `--name`, `-n`      | text    | yes      |           | Environment name.                                                                      |
| `--host`            | text    | no       | localhost | Host where SLURM commands should run.                                                  |
| `--default-option`  | text    | no       |           | Default sbatch/srun option string (for example --gpus=1). Repeat for multiple options. |
| `--description`     | text    | no       |           | Description.                                                                           |
| `--overwrite`, `-f` | boolean | no       | False     | Overwrite any existing environment with this name.                                     |
| `--no-commit`       | boolean | no       | False     | Do not commit changes.                                                                 |

#### `calkit create uv-venv`

Create a new uv virtual environment.

Usage:

```text
calkit create uv-venv [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | text | no       |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default          | Description                                            |
| ------------------- | ------- | -------- | ---------------- | ------------------------------------------------------ |
| `--name`, `-n`      | text    | yes      |                  | Environment name.                                      |
| `--path`            | text    | no       | requirements.txt | Path for requirements file.                            |
| `--prefix`          | text    | no       | .venv            | Prefix for environment location.                       |
| `--python`, `-p`    | text    | no       | 3.14             | Python version.                                        |
| `--description`     | text    | no       |                  | Description.                                           |
| `--overwrite`, `-f` | boolean | no       | False            | Overwrite any existing environment with this name.     |
| `--no-commit`       | boolean | no       | False            | Do not commit changes.                                 |
| `--no-check`        | boolean | no       | False            | Do not check environment is up-to-date after creation. |

#### `calkit create venv`

Create a new Python virtual environment with venv.

Usage:

```text
calkit create venv [OPTIONS] PACKAGES...
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | text | yes      |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default          | Description                                            |
| ------------------- | ------- | -------- | ---------------- | ------------------------------------------------------ |
| `--name`, `-n`      | text    | yes      |                  | Environment name.                                      |
| `--path`            | text    | no       | requirements.txt | Path for requirements file.                            |
| `--prefix`          | text    | no       | .venv            | Prefix for environment location.                       |
| `--description`     | text    | no       |                  | Description.                                           |
| `--overwrite`, `-f` | boolean | no       | False            | Overwrite any existing environment with this name.     |
| `--no-commit`       | boolean | no       | False            | Do not commit changes.                                 |
| `--no-check`        | boolean | no       | False            | Do not check environment is up-to-date after creation. |

#### `calkit create pixi-env`

Create a new pixi virtual environment.

Usage:

```text
calkit create pixi-env [OPTIONS] PACKAGES...
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | text | yes      |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default | Description                                            |
| ------------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--name`, `-n`      | text    | yes      |         | Environment name.                                      |
| `--pip`             | text    | no       |         | Packages to install with pip.                          |
| `--description`     | text    | no       |         | Description.                                           |
| `--platform`, `-p`  | text    | no       |         | Platform.                                              |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite any existing environment with this name.     |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                 |
| `--no-check`        | boolean | no       | False   | Do not check environment is up-to-date after creation. |

#### `calkit create julia-env`

Create a new Julia environment or add an existing one to calkit.yaml.

Usage:

```text
calkit create julia-env [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                                      |
| ---------- | ---- | -------- | ------- | ------------------------------------------------ |
| `packages` | text | no       |         | Optional packages to include in the environment. |

Options:

| Option              | Type    | Required | Default | Description                                            |
| ------------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--name`, `-n`      | text    | no       | main    | Environment name.                                      |
| `--path`            | text    | no       |         | Path for Project.toml file.                            |
| `--description`     | text    | no       |         | Description.                                           |
| `--julia`, `-j`     | text    | no       |         | Julia version. Auto-detected if not supplied.          |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite any existing environment with this name.     |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                 |
| `--no-check`        | boolean | no       | False   | Do not check environment is up-to-date after creation. |

#### `calkit create renv`

Create a new R environment with renv.

Usage:

```text
calkit create renv [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | text | no       |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default | Description                                            |
| ------------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--name`, `-n`      | text    | no       | main    | Environment name.                                      |
| `--path`            | text    | no       |         | Environment file path. Must end with 'DESCRIPTION'.    |
| `--r-version`, `-r` | text    | no       |         | R version.                                             |
| `--description`     | text    | no       |         | Description.                                           |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite any existing environment with this name.     |
| `--no-check`        | boolean | no       | False   | Do not check environment is up-to-date after creation. |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                 |

#### `calkit create status`

Add a new project status to the log.

Usage:

```text
calkit create status [OPTIONS] STATUS
```

Arguments:

| Argument | Type                                    | Required | Default | Description                    |
| -------- | --------------------------------------- | -------- | ------- | ------------------------------ |
| `status` | choice(in-progress, on-hold, completed) | yes      |         | Current status of the project. |

Options:

| Option            | Type    | Required | Default | Description                              |
| ----------------- | ------- | -------- | ------- | ---------------------------------------- |
| `--message`, `-m` | text    | no       |         | Optional message describing the status.  |
| `--no-commit`     | boolean | no       | False   | Do not commit changes to the status log. |

#### `calkit create python-script-stage`

Add a stage to the pipeline that runs a Python script.

Usage:

```text
calkit create python-script-stage [OPTIONS]
```

Options:

| Option                         | Type        | Required | Default | Description                                                                                                    |
| ------------------------------ | ----------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | text        | yes      |         | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | text        | yes      |         | Environment to use to run the stage.                                                                           |
| `--script-path`, `-s`          | text        | yes      |         | Path to script.                                                                                                |
| `--arg`                        | text        | no       |         | Argument to pass to the script.                                                                                |
| `--input`, `-i`                | text        | no       |         | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | text        | no       |         | A path that is produced by the stage.                                                                          |
| `--out-git`                    | text        | no       |         | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | text        | no       |         | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | text        | no       |         | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | text        | no       |         | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | text        | no       |         | An output that should not be stored in version control, and should not be deleted before running.              |
| `--iter`                       | <text text> | no       |         | Iterate over an argument with a comma-separated list, e.g., --iter-arg var_name val1,val2,val3.                |
| `--overwrite`, `--force`, `-f` | boolean     | no       | False   | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean     | no       | False   | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean     | no       | False   | Do not commit changes to Git.                                                                                  |

#### `calkit create julia-script-stage`

Add a stage to the pipeline that runs a Julia script.

Usage:

```text
calkit create julia-script-stage [OPTIONS]
```

Options:

| Option                         | Type        | Required | Default | Description                                                                                                    |
| ------------------------------ | ----------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | text        | yes      |         | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | text        | yes      |         | Environment to use to run the stage.                                                                           |
| `--script-path`, `-s`          | text        | yes      |         | Path to script.                                                                                                |
| `--input`, `-i`                | text        | no       |         | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | text        | no       |         | A path that is produced by the stage.                                                                          |
| `--out-git`                    | text        | no       |         | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | text        | no       |         | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | text        | no       |         | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | text        | no       |         | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | text        | no       |         | An output that should not be stored in version control, and should not be deleted before running.              |
| `--iter`                       | <text text> | no       |         | Iterate over an argument with a comma-separated list, e.g., --iter-arg var_name val1,val2,val3.                |
| `--overwrite`, `--force`, `-f` | boolean     | no       | False   | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean     | no       | False   | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean     | no       | False   | Do not commit changes to Git.                                                                                  |

#### `calkit create matlab-script-stage`

Add a stage to the pipeline that runs a MATLAB script.

Usage:

```text
calkit create matlab-script-stage [OPTIONS]
```

Options:

| Option                         | Type    | Required | Default | Description                                                                                                    |
| ------------------------------ | ------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | text    | yes      |         | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | text    | yes      |         | Environment to use to run the stage.                                                                           |
| `--script-path`, `-s`          | text    | yes      |         | Path to script.                                                                                                |
| `--input`, `-i`                | text    | no       |         | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | text    | no       |         | A path that is produced by the stage.                                                                          |
| `--out-git`                    | text    | no       |         | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | text    | no       |         | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | text    | no       |         | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | text    | no       |         | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | text    | no       |         | An output that should not be stored in version control, and should not be deleted before running.              |
| `--overwrite`, `--force`, `-f` | boolean | no       | False   | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean | no       | False   | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean | no       | False   | Do not commit changes to Git.                                                                                  |

#### `calkit create latex-stage`

Add a stage to the pipeline that compiles a LaTeX document.

Usage:

```text
calkit create latex-stage [OPTIONS]
```

Options:

| Option                         | Type    | Required | Default | Description                                                                                                    |
| ------------------------------ | ------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | text    | yes      |         | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | text    | yes      |         | Environment to use to run the stage.                                                                           |
| `--target`                     | text    | yes      |         | Target .tex file path.                                                                                         |
| `--input`, `-i`                | text    | no       |         | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | text    | no       |         | A path that is produced by the stage.                                                                          |
| `--out-git`                    | text    | no       |         | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | text    | no       |         | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | text    | no       |         | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | text    | no       |         | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | text    | no       |         | An output that should not be stored in version control, and should not be deleted before running.              |
| `--overwrite`, `--force`, `-f` | boolean | no       | False   | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean | no       | False   | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean | no       | False   | Do not commit changes to Git.                                                                                  |

#### `calkit create jupyter-notebook-stage`

Add a stage to the pipeline that runs a Jupyter notebook.

Usage:

```text
calkit create jupyter-notebook-stage [OPTIONS]
```

Options:

| Option                         | Type                   | Required | Default             | Description                                                                                                    |
| ------------------------------ | ---------------------- | -------- | ------------------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | text                   | yes      |                     | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | text                   | yes      |                     | Environment to use to run the stage.                                                                           |
| `--notebook-path`              | text                   | yes      |                     | Path to notebook.                                                                                              |
| `--input`, `-i`                | text                   | no       |                     | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | text                   | no       |                     | A path that is produced by the stage.                                                                          |
| `--out-git`                    | text                   | no       |                     | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | text                   | no       |                     | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | text                   | no       |                     | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | text                   | no       |                     | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | text                   | no       |                     | An output that should not be stored in version control, and should not be deleted before running.              |
| `--html-storage`               | choice(git, dvc, None) | no       | NotebookStorage.dvc | In what system to store the HTML output of the notebook.                                                       |
| `--cleaned-ipynb-storage`      | choice(git, dvc, None) | no       | NotebookStorage.git | In what system to store the cleaned ipynb output of the notebook.                                              |
| `--executed-ipynb-storage`     | choice(git, dvc, None) | no       | NotebookStorage.dvc | In what system to store the executed ipynb output of the notebook.                                             |
| `--overwrite`, `--force`, `-f` | boolean                | no       | False               | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean                | no       | False               | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean                | no       | False               | Do not commit changes to Git.                                                                                  |

#### `calkit create release`

Create a new release.

Usage:

```text
calkit create release [OPTIONS] [PATH]
```

Arguments:

| Argument | Type | Required | Default | Description                                     |
| -------- | ---- | -------- | ------- | ----------------------------------------------- |
| `path`   | text | no       | .       | The path to release; '.' for a project release. |

Options:

| Option                    | Type    | Required | Default | Description                                                                                                                |
| ------------------------- | ------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`            | text    | yes      |         | A name for the release, typically kebab-case or a semantic version. Will be used for the Git tag and GitHub release title. |
| `--kind`                  | text    | no       | project | What kind of release to create.                                                                                            |
| `--description`, `--desc` | text    | no       |         | A description of the release. Will be auto-generated if not provided.                                                      |
| `--date`                  | text    | no       |         | Release date. Will default to today.                                                                                       |
| `--dry-run`               | boolean | no       | False   | Only print actions that would be taken but don't take them.                                                                |
| `--no-commit`             | boolean | no       | False   | Do not commit changes to Git repo.                                                                                         |
| `--no-push`               | boolean | no       | False   | Do not push to Git remote.                                                                                                 |
| `--no-github`             | boolean | no       | False   | Do not create a GitHub release.                                                                                            |
| `--to`                    | text    | no       | zenodo  | Archival service to use (zenodo or caltechdata).                                                                           |
| `--draft`                 | boolean | no       | False   | Create draft record with reserved DOI but do not publish.                                                                  |
| `--license`               | text    | no       |         | License ID (from https://spdx.org/licenses). Multiple can be specified. Will try to infer from LICENSE file, if present.   |
| `--verbose`, `-v`         | boolean | no       | False   | Print verbose output.                                                                                                      |

### `calkit nb`

Work with Jupyter notebooks.

| Command        | Description                                                                                                                                                                                                       |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `clean`        | Clean notebook and place a copy in the cleaned notebooks directory. This can be useful to use as a preprocessing DVC stage to use a clean notebook as a dependency for a stage that caches and executed notebook. |
| `clean-all`    | Clean all notebooks in the pipeline.                                                                                                                                                                              |
| `check-kernel` | Check that an environment has a registered Jupyter kernel.                                                                                                                                                        |
| `execute`      | Execute notebook and place a copy in the relevant directory. This can be useful to use as a preprocessing DVC stage to use a clean notebook as a dependency for a stage that caches and executed notebook.        |
| `exec`         | Alias for 'execute'.                                                                                                                                                                                              |

#### `calkit nb clean`

Clean notebook and place a copy in the cleaned notebooks directory. This can be useful to use as a preprocessing DVC stage to use a clean notebook as a dependency for a stage that caches and executed notebook.

Usage:

```text
calkit nb clean [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `path`   | text | yes      |         |             |

Options:

| Option          | Type    | Required | Default | Description          |
| --------------- | ------- | -------- | ------- | -------------------- |
| `--quiet`, `-q` | boolean | no       | False   | Do not print output. |

#### `calkit nb clean-all`

Clean all notebooks in the pipeline.

Usage:

```text
calkit nb clean-all [OPTIONS]
```

Options:

| Option          | Type    | Required | Default | Description          |
| --------------- | ------- | -------- | ------- | -------------------- |
| `--quiet`, `-q` | boolean | no       | False   | Do not print output. |

#### `calkit nb check-kernel`

Check that an environment has a registered Jupyter kernel.

Usage:

```text
calkit nb check-kernel [OPTIONS]
```

Options:

| Option                         | Type    | Required | Default | Description                                                                              |
| ------------------------------ | ------- | -------- | ------- | ---------------------------------------------------------------------------------------- |
| `--environment`, `--env`, `-e` | text    | yes      |         | Environment name in which to run the notebook.                                           |
| `--no-check`                   | boolean | no       | False   | Do not check environment before executing.                                               |
| `--language`, `-l`             | text    | no       |         | Notebook language; if 'matlab', MATLAB kernel must be available in environment.          |
| `--verbose`, `-v`              | boolean | no       | False   | Print verbose output.                                                                    |
| `--json`                       | boolean | no       | False   | Output result as JSON.                                                                   |
| `--auto-add-deps`              | boolean | no       | False   | Automatically install missing kernel dependencies (e.g., IJulia for Julia environments). |

#### `calkit nb execute`

Execute notebook and place a copy in the relevant directory. This can be useful to use as a preprocessing DVC stage to use a clean notebook as a dependency for a stage that caches and executed notebook.

Usage:

```text
calkit nb execute [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `path`   | text | yes      |         |             |

Options:

| Option                  | Type    | Required | Default  | Description                                                                     |
| ----------------------- | ------- | -------- | -------- | ------------------------------------------------------------------------------- |
| `--environment`, `-e`   | text    | no       |          | Name or path to the spec of the environment in which to run the notebook.       |
| `--to`                  | text    | no       | notebook | Output format ('html' or 'notebook').                                           |
| `--no-check`            | boolean | no       | False    | Do not check environment before executing.                                      |
| `--param`, `-p`         | text    | no       |          | Parameter to pass to the notebook in key=value format.                          |
| `--params-json`, `-j`   | text    | no       |          | JSON string to parse as parameters to pass to the notebook.                     |
| `--params-base64`, `-b` | text    | no       |          | Base64-encoded JSON string to parse as parameters to pass to the notebook.      |
| `--language`, `-l`      | text    | no       |          | Notebook language; if 'matlab', MATLAB kernel must be available in environment. |
| `--no-replace`          | boolean | no       | False    | Do not replace notebook outputs from executed version.                          |
| `--verbose`, `-v`       | boolean | no       | False    | Print verbose output.                                                           |

#### `calkit nb exec`

Alias for 'execute'.

Usage:

```text
calkit nb exec [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `path`   | text | yes      |         |             |

Options:

| Option                  | Type    | Required | Default  | Description                                                                     |
| ----------------------- | ------- | -------- | -------- | ------------------------------------------------------------------------------- |
| `--environment`, `-e`   | text    | no       |          | Name or path to the spec of the environment in which to run the notebook.       |
| `--to`                  | text    | no       | notebook | Output format ('html' or 'notebook').                                           |
| `--no-check`            | boolean | no       | False    | Do not check environment before executing.                                      |
| `--param`, `-p`         | text    | no       |          | Parameter to pass to the notebook in key=value format.                          |
| `--params-json`, `-j`   | text    | no       |          | JSON string to parse as parameters to pass to the notebook.                     |
| `--params-base64`, `-b` | text    | no       |          | Base64-encoded JSON string to parse as parameters to pass to the notebook.      |
| `--language`, `-l`      | text    | no       |          | Notebook language; if 'matlab', MATLAB kernel must be available in environment. |
| `--no-replace`          | boolean | no       | False    | Do not replace notebook outputs from executed version.                          |
| `--verbose`, `-v`       | boolean | no       | False    | Print verbose output.                                                           |

### `calkit list`

List Calkit objects.

| Command        | Description                       |
| -------------- | --------------------------------- |
| `notebooks`    |                                   |
| `figures`      |                                   |
| `datasets`     |                                   |
| `publications` |                                   |
| `references`   |                                   |
| `envs`         | List environments in the project. |
| `environments` | List environments in the project. |
| `templates`    |                                   |
| `procedures`   |                                   |
| `releases`     | List releases.                    |
| `stages`       | List stages.                      |

#### `calkit list notebooks`

Usage:

```text
calkit list notebooks
```

#### `calkit list figures`

Usage:

```text
calkit list figures
```

#### `calkit list datasets`

Usage:

```text
calkit list datasets
```

#### `calkit list publications`

Usage:

```text
calkit list publications
```

#### `calkit list references`

Usage:

```text
calkit list references
```

#### `calkit list envs`

List environments in the project.

Usage:

```text
calkit list envs
```

#### `calkit list environments`

List environments in the project.

Usage:

```text
calkit list environments
```

#### `calkit list templates`

Usage:

```text
calkit list templates
```

#### `calkit list procedures`

Usage:

```text
calkit list procedures
```

#### `calkit list releases`

List releases.

Usage:

```text
calkit list releases
```

#### `calkit list stages`

List stages.

Usage:

```text
calkit list stages [OPTIONS]
```

Options:

| Option         | Type | Required | Default | Description            |
| -------------- | ---- | -------- | ------- | ---------------------- |
| `--kind`, `-k` | text | no       |         | Filter stages by kind. |

### `calkit describe`

Describe things.

| Command  | Description          |
| -------- | -------------------- |
| `system` | Describe the system. |

#### `calkit describe system`

Describe the system.

Usage:

```text
calkit describe system
```

### `calkit import`

Import objects.

| Command       | Description                                                              |
| ------------- | ------------------------------------------------------------------------ |
| `dataset`     | Import a dataset. Currently only supports datasets kept in DVC, not Git. |
| `environment` | Import an environment from another project.                              |
| `zenodo`      | Import files from a Zenodo record.                                       |

#### `calkit import dataset`

Import a dataset. Currently only supports datasets kept in DVC, not Git.

Usage:

```text
calkit import dataset [OPTIONS] SRC-PATH [DEST-PATH]
```

Arguments:

| Argument    | Type | Required | Default | Description                                                                                          |
| ----------- | ---- | -------- | ------- | ---------------------------------------------------------------------------------------------------- |
| `src_path`  | text | yes      |         | Location of dataset, including project owner and name, e.g., someone/some-project/data/some-data.csv |
| `dest_path` | text | no       |         | Output path at which to save.                                                                        |

Options:

| Option              | Type    | Required | Default | Description                                         |
| ------------------- | ------- | -------- | ------- | --------------------------------------------------- |
| `--filter-paths`    | text    | no       |         | Filter paths in target dataset if it's a folder.    |
| `--no-commit`       | boolean | no       | False   | Do not commit changes to repo.                      |
| `--no-dvc-pull`     | boolean | no       | False   | Do not pull imported dataset with DVC.              |
| `--overwrite`, `-f` | boolean | no       | False   | Force adding the dataset even if it already exists. |

#### `calkit import environment`

Import an environment from another project.

Usage:

```text
calkit import environment [OPTIONS] SRC
```

Arguments:

| Argument | Type | Required | Default | Description                                                                                                           |
| -------- | ---- | -------- | ------- | --------------------------------------------------------------------------------------------------------------------- |
| `src`    | text | yes      |         | Environment location and name, e.g., someone/some-project:env-name. If not present, the Calkit Cloud will be queried. |

Options:

| Option              | Type    | Required | Default | Description                                         |
| ------------------- | ------- | -------- | ------- | --------------------------------------------------- |
| `--path`            | text    | no       |         | Output path at which to save.                       |
| `--name`, `-n`      | text    | no       |         | Name to use in the destination project.             |
| `--overwrite`, `-f` | boolean | no       | False   | Force adding the dataset even if it already exists. |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                              |

#### `calkit import zenodo`

Import files from a Zenodo record.

Usage:

```text
calkit import zenodo [OPTIONS] SRC DEST-DIR
```

Arguments:

| Argument   | Type | Required | Default | Description                                             |
| ---------- | ---- | -------- | ------- | ------------------------------------------------------- |
| `src`      | text | yes      |         | Source URL or DOI.                                      |
| `dest_dir` | text | yes      |         | Destination folder. Will be created if it doesn't exist |

Options:

| Option            | Type    | Required | Default | Description                                                                          |
| ----------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------ |
| `--kind`, `-k`    | text    | no       |         | What kind of artifact is being imported, e.g., a figure, dataset, publication.       |
| `--name-like`     | text    | no       |         | Filter for file names like this. Glob patterns accepted.                             |
| `--name-not-like` | text    | no       |         | Exclude names matching pattern.                                                      |
| `--storage`       | text    | no       |         | Storage backend to use (Git or DVC). If not specified, will be chosen based on size. |
| `--no-commit`     | boolean | no       | False   | Do not commit changes to project.                                                    |

### `calkit office`

Work with Microsoft Office.

| Command                | Description                                   |
| ---------------------- | --------------------------------------------- |
| `excel-chart-to-image` | Extract a chart from Excel and save to image. |
| `word-to-pdf`          | Convert a Word document to PDF.               |

#### `calkit office excel-chart-to-image`

Extract a chart from Excel and save to image.

Usage:

```text
calkit office excel-chart-to-image [OPTIONS] INPUT-FPATH OUTPUT-FPATH
```

Arguments:

| Argument       | Type | Required | Default | Description             |
| -------------- | ---- | -------- | ------- | ----------------------- |
| `input_fpath`  | text | yes      |         | Input Excel file path.  |
| `output_fpath` | text | yes      |         | Output image file path. |

Options:

| Option          | Type    | Required | Default | Description        |
| --------------- | ------- | -------- | ------- | ------------------ |
| `--sheet`       | integer | no       | 1       | Sheet in workbook. |
| `--chart-index` | integer | no       | 0       | Chart index.       |

#### `calkit office word-to-pdf`

Convert a Word document to PDF.

Usage:

```text
calkit office word-to-pdf [OPTIONS] INPUT-FPATH
```

Arguments:

| Argument      | Type | Required | Default | Description                    |
| ------------- | ---- | -------- | ------- | ------------------------------ |
| `input_fpath` | text | yes      |         | Input Word document file path. |

Options:

| Option           | Type | Required | Default | Description                                                                          |
| ---------------- | ---- | -------- | ------- | ------------------------------------------------------------------------------------ |
| `-o`, `--output` | text | no       |         | Output file path. If not specified, will be the same as input with a .pdf extension. |

### `calkit update`

Update objects.

| Command          | Description                                                                                                                                                                                                              |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `devcontainer`   | Update a project's devcontainer to match the latest Calkit spec.                                                                                                                                                         |
| `license`        | Update license with a reasonable default (MIT for code, CC-BY-4.0 for other files).                                                                                                                                      |
| `release`        | Update a release.                                                                                                                                                                                                        |
| `vscode-config`  | Update a project's VS Code config to match the latest Calkit recommendations.                                                                                                                                            |
| `github-actions` | Update a project's GitHub Actions to match the latest Calkit recommendations.                                                                                                                                            |
| `notebook`       | Update notebook information. Updates the notebook's environment association in either the 'notebooks' section or the appropriate 'pipeline' stage, depending on whether the notebook has a corresponding pipeline stage. |
| `env`            | Update an environment. Currently only supports adding packages to Julia environments.                                                                                                                                    |
| `environment`    | Update an environment. Currently only supports adding packages to Julia environments.                                                                                                                                    |

#### `calkit update devcontainer`

Update a project's devcontainer to match the latest Calkit spec.

Usage:

```text
calkit update devcontainer [OPTIONS]
```

Options:

| Option        | Type    | Required | Default | Description                                                       |
| ------------- | ------- | -------- | ------- | ----------------------------------------------------------------- |
| `--wdir`      | text    | no       |         | Working directory. By default will run current working directory. |
| `--no-commit` | boolean | no       | False   | Do not create a Git commit for the updated devcontainer.          |

#### `calkit update license`

Update license with a reasonable default (MIT for code, CC-BY-4.0 for other files).

Usage:

```text
calkit update license [OPTIONS]
```

Options:

| Option                     | Type    | Required | Default | Description                                         |
| -------------------------- | ------- | -------- | ------- | --------------------------------------------------- |
| `--copyright-holder`, `-c` | text    | yes      |         | Copyright holder, e.g., your full name.             |
| `--no-commit`              | boolean | no       | False   | Do not create a Git commit for the updated license. |

#### `calkit update release`

Update a release.

Usage:

```text
calkit update release [OPTIONS]
```

Options:

| Option           | Type    | Required | Default | Description                                |
| ---------------- | ------- | -------- | ------- | ------------------------------------------ |
| `--name`, `-n`   | text    | no       |         | Release name.                              |
| `--latest`       | boolean | no       | False   | Update latest release.                     |
| `--delete`       | boolean | no       | False   | Delete release.                            |
| `--publish`      | boolean | no       | False   | Publish the release.                       |
| `--reupload`     | boolean | no       | False   | Reupload files.                            |
| `--no-github`    | boolean | no       | False   | Do not create a release on GitHub.         |
| `--no-push-tags` | boolean | no       | False   | Do not push Git tags to remote repository. |

#### `calkit update vscode-config`

Update a project's VS Code config to match the latest Calkit recommendations.

Usage:

```text
calkit update vscode-config [OPTIONS]
```

Options:

| Option        | Type    | Required | Default | Description                                                       |
| ------------- | ------- | -------- | ------- | ----------------------------------------------------------------- |
| `--wdir`      | text    | no       |         | Working directory. By default will run current working directory. |
| `--no-commit` | boolean | no       | False   | Do not create a Git commit for the updated VS Code config.        |

#### `calkit update github-actions`

Update a project's GitHub Actions to match the latest Calkit recommendations.

Usage:

```text
calkit update github-actions [OPTIONS]
```

Options:

| Option        | Type    | Required | Default | Description                                                       |
| ------------- | ------- | -------- | ------- | ----------------------------------------------------------------- |
| `--wdir`      | text    | no       |         | Working directory. By default will run current working directory. |
| `--no-commit` | boolean | no       | False   | Do not create a Git commit for the updated GitHub Actions.        |

#### `calkit update notebook`

Update notebook information. Updates the notebook's environment association in either the 'notebooks' section or the appropriate 'pipeline' stage, depending on whether the notebook has a corresponding pipeline stage.

Usage:

```text
calkit update notebook [OPTIONS] NOTEBOOK-PATH
```

Arguments:

| Argument        | Type | Required | Default | Description                                       |
| --------------- | ---- | -------- | ------- | ------------------------------------------------- |
| `notebook_path` | text | yes      |         | Path to the notebook file (relative to workspace) |

Options:

| Option      | Type    | Required | Default | Description                                     |
| ----------- | ------- | -------- | ------- | ----------------------------------------------- |
| `--set-env` | text    | no       |         | Environment name to associate with the notebook |
| `--json`    | boolean | no       | False   | Output result as JSON.                          |

#### `calkit update env`

Update an environment. Currently only supports adding packages to Julia environments.

Usage:

```text
calkit update env [OPTIONS]
```

Options:

| Option         | Type | Required | Default | Description                       |
| -------------- | ---- | -------- | ------- | --------------------------------- |
| `--name`, `-n` | text | yes      |         | Name of the environment to update |
| `--add`        | text | no       |         | Add package to environment,       |

#### `calkit update environment`

Update an environment. Currently only supports adding packages to Julia environments.

Usage:

```text
calkit update environment [OPTIONS]
```

Options:

| Option         | Type | Required | Default | Description                       |
| -------------- | ---- | -------- | ------- | --------------------------------- |
| `--name`, `-n` | text | yes      |         | Name of the environment to update |
| `--add`        | text | no       |         | Add package to environment,       |

### `calkit check`

Check things.

| Command        | Description                                                              |
| -------------- | ------------------------------------------------------------------------ |
| `repro`        | Check the reproducibility of a project.                                  |
| `environment`  | Check that an environment is up-to-date.                                 |
| `env`          | Check that an environment is up-to-date (alias for 'environment').       |
| `environments` |                                                                          |
| `envs`         | Check that all environments are up-to-date.                              |
| `renv`         | Check an renv R environment, initializing if needed.                     |
| `docker-env`   | Check that Docker environment is up-to-date.                             |
| `conda-env`    | Check a conda environment and rebuild if necessary.                      |
| `venv`         | Check a Python virtual environment (uv or virtualenv).                   |
| `matlab-env`   | Check a MATLAB environment matches its spec and export a JSON lock file. |
| `deps`         | Check that a project's system-level dependencies are set up correctly.   |
| `dependencies` | Check that a project's system-level dependencies are set up correctly.   |
| `env-vars`     | Check that the project's required environmental variables exist.         |
| `pipeline`     | Check that the project pipeline is defined correctly.                    |
| `call`         | Check that a command succeeds and run an alternate if not.               |

#### `calkit check repro`

Check the reproducibility of a project.

Usage:

```text
calkit check repro [OPTIONS]
```

Options:

| Option   | Type | Required | Default | Description                |
| -------- | ---- | -------- | ------- | -------------------------- |
| `--wdir` | text | no       | .       | Project working directory. |

#### `calkit check environment`

Check that an environment is up-to-date.

Usage:

```text
calkit check environment [OPTIONS]
```

Options:

| Option         | Type    | Required | Default | Description                       |
| -------------- | ------- | -------- | ------- | --------------------------------- |
| `--name`, `-n` | text    | yes      |         | Name of the environment to check. |
| `--verbose`    | boolean | no       | False   | Print verbose output.             |

#### `calkit check env`

Check that an environment is up-to-date (alias for 'environment').

Usage:

```text
calkit check env [OPTIONS]
```

Options:

| Option         | Type    | Required | Default | Description                       |
| -------------- | ------- | -------- | ------- | --------------------------------- |
| `--name`, `-n` | text    | yes      |         | Name of the environment to check. |
| `--verbose`    | boolean | no       | False   | Print verbose output.             |

#### `calkit check environments`

Usage:

```text
calkit check environments [OPTIONS]
```

Options:

| Option      | Type    | Required | Default | Description           |
| ----------- | ------- | -------- | ------- | --------------------- |
| `--verbose` | boolean | no       | False   | Print verbose output. |

#### `calkit check envs`

Check that all environments are up-to-date.

Usage:

```text
calkit check envs [OPTIONS]
```

Options:

| Option      | Type    | Required | Default | Description           |
| ----------- | ------- | -------- | ------- | --------------------- |
| `--verbose` | boolean | no       | False   | Print verbose output. |

#### `calkit check renv`

Check an renv R environment, initializing if needed.

Usage:

```text
calkit check renv [OPTIONS] ENV-PATH
```

Arguments:

| Argument   | Type | Required | Default | Description                                             |
| ---------- | ---- | -------- | ------- | ------------------------------------------------------- |
| `env_path` | text | yes      |         | Path to DESCRIPTION file or renv environment directory. |

Options:

| Option      | Type    | Required | Default | Description           |
| ----------- | ------- | -------- | ------- | --------------------- |
| `--verbose` | boolean | no       | False   | Print verbose output. |

#### `calkit check docker-env`

Check that Docker environment is up-to-date.

Usage:

```text
calkit check docker-env [OPTIONS] TAG
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `tag`    | text | yes      |         | Image tag.  |

Options:

| Option            | Type    | Required | Default | Description                                                                                                                                                   |
| ----------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-i`, `--input`   | text    | no       |         | Path to input Dockerfile, if applicable.                                                                                                                      |
| `--output`, `-o`  | text    | no       |         | Path to which existing environment should be exported. If not specified, will have the same filename with '-lock' appended to it, keeping the same extension. |
| `--input`         | text    | no       |         | Alternative lock file input paths to read.                                                                                                                    |
| `--input-delete`  | text    | no       |         | Alternative lock input file paths to read and remove (i.e., legacy paths).                                                                                    |
| `--platform`      | text    | no       |         | Which platform(s) to build for.                                                                                                                               |
| `--user`          | text    | no       |         | Which user to run the container as.                                                                                                                           |
| `--wdir`          | text    | no       |         | Working directory inside the container.                                                                                                                       |
| `--dep`, `-d`     | text    | no       |         | Declare an explicit dependency for this Docker image.                                                                                                         |
| `--env-var`, `-e` | text    | no       |         | Declare an explicit environment variable for the container.                                                                                                   |
| `--port`, `-p`    | text    | no       |         | Declare an explicit port for the container.                                                                                                                   |
| `--gpus`, `-g`    | text    | no       |         | Declare an explicit GPU requirement for the container.                                                                                                        |
| `--arg`, `-a`     | text    | no       |         | Declare an explicit run argument for the container.                                                                                                           |
| `--quiet`, `-q`   | boolean | no       | False   | Be quiet.                                                                                                                                                     |

#### `calkit check conda-env`

Check a conda environment and rebuild if necessary.

Usage:

```text
calkit check conda-env [OPTIONS]
```

Options:

| Option           | Type    | Required | Default         | Description                                                                                                                                                   |
| ---------------- | ------- | -------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--file`, `-f`   | text    | no       | environment.yml | Path to conda environment YAML file.                                                                                                                          |
| `--output`, `-o` | text    | no       |                 | Path to which existing environment should be exported. If not specified, will have the same filename with '-lock' appended to it, keeping the same extension. |
| `--input`        | text    | no       |                 | Alternative lock file input paths.                                                                                                                            |
| `--input-delete` | text    | no       |                 | Alternative lock file input paths to delete after use.                                                                                                        |
| `--relaxed`      | boolean | no       | False           | Treat conda and pip dependencies as equivalent.                                                                                                               |
| `--quiet`, `-q`  | boolean | no       | False           | Be quiet.                                                                                                                                                     |

#### `calkit check venv`

Check a Python virtual environment (uv or virtualenv).

Usage:

```text
calkit check venv [OPTIONS] [PATH]
```

Arguments:

| Argument | Type | Required | Default          | Description                |
| -------- | ---- | -------- | ---------------- | -------------------------- |
| `path`   | text | no       | requirements.txt | Path to requirements file. |

Options:

| Option           | Type    | Required | Default | Description                                                                                                                                                   |
| ---------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--prefix`       | text    | no       | .venv   | Prefix.                                                                                                                                                       |
| `--output`, `-o` | text    | no       |         | Path to which existing environment should be exported. If not specified, will have the same filename with '-lock' appended to it, keeping the same extension. |
| `--input`        | text    | no       |         | Alternative lock file input paths.                                                                                                                            |
| `--input-delete` | text    | no       |         | Alternative lock file input paths to delete after use.                                                                                                        |
| `--wdir`         | text    | no       |         | Working directory. Defaults to current working directory.                                                                                                     |
| `--uv`           | boolean | no       | True    | Use uv.                                                                                                                                                       |
| `--python`       | text    | no       |         | Python version to specify if using uv.                                                                                                                        |
| `--quiet`        | boolean | no       | False   | Do not print any output                                                                                                                                       |
| `--verbose`      | boolean | no       | False   | Print verbose output.                                                                                                                                         |

#### `calkit check matlab-env`

Check a MATLAB environment matches its spec and export a JSON lock file.

Usage:

```text
calkit check matlab-env [OPTIONS]
```

Options:

| Option           | Type | Required | Default | Description                      |
| ---------------- | ---- | -------- | ------- | -------------------------------- |
| `--name`, `-n`   | text | yes      |         | Environment name in calkit.yaml. |
| `--output`, `-o` | text | yes      |         |                                  |

#### `calkit check deps`

Check that a project's system-level dependencies are set up correctly.

Usage:

```text
calkit check deps [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description          |
| ----------------- | ------- | -------- | ------- | -------------------- |
| `--verbose`, `-v` | boolean | no       | False   | Print verbose output |

#### `calkit check dependencies`

Check that a project's system-level dependencies are set up correctly.

Usage:

```text
calkit check dependencies [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description          |
| ----------------- | ------- | -------- | ------- | -------------------- |
| `--verbose`, `-v` | boolean | no       | False   | Print verbose output |

#### `calkit check env-vars`

Check that the project's required environmental variables exist.

Usage:

```text
calkit check env-vars [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description          |
| ----------------- | ------- | -------- | ------- | -------------------- |
| `--verbose`, `-v` | boolean | no       | False   | Print verbose output |

#### `calkit check pipeline`

Check that the project pipeline is defined correctly.

Usage:

```text
calkit check pipeline [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description                                                 |
| ----------------- | ------- | -------- | ------- | ----------------------------------------------------------- |
| `--compile`, `-c` | boolean | no       | False   | Compile the pipeline to DVC stages and merge into dvc.yaml. |

#### `calkit check call`

Check that a command succeeds and run an alternate if not.

Usage:

```text
calkit check call [OPTIONS] CMD
```

Arguments:

| Argument | Type | Required | Default | Description       |
| -------- | ---- | -------- | ------- | ----------------- |
| `cmd`    | text | yes      |         | Command to check. |

Options:

| Option       | Type | Required | Default | Description                          |
| ------------ | ---- | -------- | ------- | ------------------------------------ |
| `--if-error` | text | yes      |         | Command to run if there is an error. |

### `calkit latex`

Work with LaTeX.

| Command     | Description                                                                                                                                                                                                     |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `from-json` | Convert a JSON file to LaTeX. This is useful for referencing calculated values in LaTeX documents.                                                                                                              |
| `build`     | Build a PDF of a LaTeX document with latexmk. If a Calkit environment is not specified, latexmk will be run in the system environment if available. If not available, a TeX Live Docker container will be used. |

#### `calkit latex from-json`

Convert a JSON file to LaTeX. This is useful for referencing calculated values in LaTeX documents.

Usage:

```text
calkit latex from-json [OPTIONS] INPUT-FPATHS...
```

Arguments:

| Argument       | Type | Required | Default | Description              |
| -------------- | ---- | -------- | ------- | ------------------------ |
| `input_fpaths` | text | yes      |         | Input JSON file path(s). |

Options:

| Option           | Type | Required | Default | Description                                                                                              |
| ---------------- | ---- | -------- | ------- | -------------------------------------------------------------------------------------------------------- |
| `--output`, `-o` | text | yes      |         | Output LaTeX file path(s).                                                                               |
| `--command`      | text | no       |         | Command name to use in LaTeX output.                                                                     |
| `--format-json`  | text | no       |         | Additional JSON input to use for formatting. Can be used to add extra keys with simple expressions, etc. |

#### `calkit latex build`

Build a PDF of a LaTeX document with latexmk. If a Calkit environment is not specified, latexmk will be run in the system environment if available. If not available, a TeX Live Docker container will be used.

Usage:

```text
calkit latex build [OPTIONS] TEX-FILE
```

Arguments:

| Argument   | Type | Required | Default | Description               |
| ---------- | ---- | -------- | ------- | ------------------------- |
| `tex_file` | text | yes      |         | The .tex file to compile. |

Options:

| Option               | Type    | Required | Default | Description                                                        |
| -------------------- | ------- | -------- | ------- | ------------------------------------------------------------------ |
| `--env`, `-e`        | text    | no       |         | Environment in which to run latexmk, if applicable.                |
| `--no-check`         | boolean | no       | False   | Don't check the environment is valid before running latexmk.       |
| `--latexmk-rc`, `-r` | text    | no       |         | Path to a latexmkrc file to use for compilation.                   |
| `--no-synctex`       | boolean | no       | False   | Don't generate synctex file for source-to-pdf mapping.             |
| `--force`, `-f`      | boolean | no       | False   | Force latexmk to recompile all files, even if they are up to date. |
| `--verbose`, `-v`    | boolean | no       | False   | Print verbose output.                                              |

### `calkit overleaf`

Interact with Overleaf.

| Command  | Description                                                    |
| -------- | -------------------------------------------------------------- |
| `import` | Import a publication from an Overleaf project.                 |
| `sync`   | Sync folders with Overleaf.                                    |
| `status` | Check the status of folders synced with Overleaf in a project. |

#### `calkit overleaf import`

Import a publication from an Overleaf project.

Usage:

```text
calkit overleaf import [OPTIONS] SRC-URL DEST-DIR
```

Arguments:

| Argument   | Type | Required | Default | Description                                                                    |
| ---------- | ---- | -------- | ------- | ------------------------------------------------------------------------------ |
| `src_url`  | text | yes      |         | Overleaf project URL, e.g., https://www.overleaf.com/project/6800005973cb2e35. |
| `dest_dir` | text | yes      |         | Directory at which to save in the project, e.g., 'paper'.                      |

Options:

| Option                | Type    | Required | Default | Description                                                                                                                |
| --------------------- | ------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------------------- |
| `--title`, `-t`       | text    | no       |         | Title of the publication.                                                                                                  |
| `--target`, `-T`      | text    | no       |         | Target TeX file path inside Overleaf project.                                                                              |
| `--description`, `-d` | text    | no       |         | Description of the publication.                                                                                            |
| `--kind`              | text    | no       |         | What of the publication this is, e.g., 'journal-article'.                                                                  |
| `--sync-path`, `-s`   | text    | no       |         | Paths to sync from the Overleaf project, e.g., 'main.tex'. Note that multiple can be specified.                            |
| `--push-path`, `-p`   | text    | no       |         | Paths to push to the Overleaf project, e.g., 'figures'. Note that these are relative to the publication working directory. |
| `--no-commit`         | boolean | no       | False   | Do not commit changes to repo.                                                                                             |
| `--overwrite`, `-f`   | boolean | no       | False   | Force adding the publication even if it already exists.                                                                    |
| `--push-only`, `-P`   | boolean | no       | False   | Push local files to Overleaf without pulling. Useful when initializing a new Overleaf project from local files.            |

#### `calkit overleaf sync`

Sync folders with Overleaf.

Usage:

```text
calkit overleaf sync [OPTIONS] [PATHS...]
```

Arguments:

| Argument | Type | Required | Default | Description                                                                                                      |
| -------- | ---- | -------- | ------- | ---------------------------------------------------------------------------------------------------------------- |
| `paths`  | text | no       |         | Paths to sync with Overleaf, e.g., 'paper/paper.pdf'. If not provided, all Overleaf publications will be synced. |

Options:

| Option              | Type    | Required | Default | Description                                                                                                                        |
| ------------------- | ------- | -------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `--no-commit`       | boolean | no       | False   | Do not commit the changes to the project repo. Changes will always be committed to Overleaf.                                       |
| `--auto-commit`     | boolean | no       | False   | Automatically commit changes to the project repo if a synced folder has changes.                                                   |
| `--no-push`         | boolean | no       | False   | Do not push the changes to the main project remote. Changes will always be pushed to Overleaf.                                     |
| `--verbose`         | boolean | no       | False   | Enable verbose output.                                                                                                             |
| `--resolve`, `-r`   | boolean | no       | False   | Mark merge conflicts as resolved before committing.                                                                                |
| `--push-only`, `-P` | boolean | no       | False   | Only push local files to Overleaf without pulling from Overleaf. Useful when initializing a new Overleaf project from local files. |

#### `calkit overleaf status`

Check the status of folders synced with Overleaf in a project.

Usage:

```text
calkit overleaf status [PATHS...]
```

Arguments:

| Argument | Type | Required | Default | Description                                                                                     |
| -------- | ---- | -------- | ------- | ----------------------------------------------------------------------------------------------- |
| `paths`  | text | no       |         | Paths synced with Overleaf, e.g., 'paper'. If not provided, all Overleaf syncs will be checked. |

### `calkit cloud`

Interact with a Calkit Cloud.

| Command | Description                        |
| ------- | ---------------------------------- |
| `get`   | Get a resource from the Cloud API. |

#### `calkit cloud get`

Get a resource from the Cloud API.

Usage:

```text
calkit cloud get ENDPOINT
```

Arguments:

| Argument   | Type | Required | Default | Description  |
| ---------- | ---- | -------- | ------- | ------------ |
| `endpoint` | text | yes      |         | API endpoint |

### `calkit slurm`

Work with SLURM.

| Command  | Description                                                                                                                                                                                                                                                                                               |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `batch`  | Submit a SLURM batch job for the project. Duplicates are not allowed, so if one is already running or queued with the same name, we'll wait for it to finish. The only exception is if the dependencies have changed, in which case any queued or running jobs will be cancelled and a new one submitted. |
| `queue`  | List SLURM jobs submitted via Calkit.                                                                                                                                                                                                                                                                     |
| `cancel` | Cancel SLURM jobs by their name in the project.                                                                                                                                                                                                                                                           |
| `logs`   | Get the logs for a SLURM job by its name in the project.                                                                                                                                                                                                                                                  |

#### `calkit slurm batch`

Submit a SLURM batch job for the project. Duplicates are not allowed, so if one is already running or queued with the same name, we'll wait for it to finish. The only exception is if the dependencies have changed, in which case any queued or running jobs will be cancelled and a new one submitted.

Usage:

```text
calkit slurm batch [OPTIONS] TARGET [ARGS...]
```

Arguments:

| Argument | Type | Required | Default | Description                                                     |
| -------- | ---- | -------- | ------- | --------------------------------------------------------------- |
| `target` | text | yes      |         | The target to run. This can be a shell script or an executable. |
| `args`   | text | no       |         | Arguments for sbatch, the first of which should be the script.  |

Options:

| Option                  | Type    | Required | Default | Description                                                                                                        |
| ----------------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------ |
| `--name`, `-n`          | text    | yes      |         | Job name.                                                                                                          |
| `--environment`, `-e`   | text    | yes      |         | Calkit (slurm) environment to use for the job.                                                                     |
| `--dep`, `-d`           | text    | no       |         | Additional dependencies to track, which if changed signify a job is invalid.                                       |
| `--out`, `-o`           | text    | no       |         | Non-persistent output files or directories produced by the job, which will be deleted before submitting a new job. |
| `--sbatch-option`, `-s` | text    | no       |         | Additional options to pass to sbatch (no spaces allowed).                                                          |
| `--log-path`            | text    | no       |         | Output log path.                                                                                                   |
| `--command`             | boolean | no       |         | Whether the target is a command instead of a script.                                                               |

#### `calkit slurm queue`

List SLURM jobs submitted via Calkit.

Usage:

```text
calkit slurm queue
```

#### `calkit slurm cancel`

Cancel SLURM jobs by their name in the project.

Usage:

```text
calkit slurm cancel NAMES...
```

Arguments:

| Argument | Type | Required | Default | Description              |
| -------- | ---- | -------- | ------- | ------------------------ |
| `names`  | text | yes      |         | Names of jobs to cancel. |

#### `calkit slurm logs`

Get the logs for a SLURM job by its name in the project.

Usage:

```text
calkit slurm logs [OPTIONS] [NAMES...]
```

Arguments:

| Argument | Type | Required | Default | Description                        |
| -------- | ---- | -------- | ------- | ---------------------------------- |
| `names`  | text | no       |         | Names of the jobs to get logs for. |

Options:

| Option           | Type    | Required | Default | Description                         |
| ---------------- | ------- | -------- | ------- | ----------------------------------- |
| `--follow`, `-f` | boolean | no       | False   | Follow the log output like tail -f. |
