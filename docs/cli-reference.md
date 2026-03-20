# CLI reference

This page is auto-generated from live CLI help output. To update it, run `make sync-docs` (or `uv run python scripts/generate-cli-reference.py`).

## Top-level commands

| Command         | Description                                                                                                                                                                                           |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `init`          | Initialize the current working directory.                                                                                                                                                             |
| `clone`         | Clone or download a copy of a project.                                                                                                                                                                |
| `status`        | View status (project, version control, and/or pipeline).                                                                                                                                              |
| `diff`          | Get a unified Git and DVC diff.                                                                                                                                                                       |
| `add`           | Add paths to the repo. Code will be added to Git and data will be added to DVC. Note: This will enable the 'autostage' feature of DVC, automatically adding any .dvc files to Git when adding to DVC. |
| `commit`        | Commit a change to the repo.                                                                                                                                                                          |
| `save`          | Save paths by committing and pushing. This is essentially git/dvc add, commit, and push in one step.                                                                                                  |
| `pull`          | Pull with both Git and DVC.                                                                                                                                                                           |
| `push`          | Push with both Git and DVC.                                                                                                                                                                           |
| `sync`          | Sync the project repo by pulling and then pushing.                                                                                                                                                    |
| `ignore`        | Ignore a file, i.e., keep it out of version control.                                                                                                                                                  |
| `local-server`  | Run the local server to interact over HTTP.                                                                                                                                                           |
| `run`           | Check dependencies and run the pipeline.                                                                                                                                                              |
| `manual-step`   | Execute a manual step.                                                                                                                                                                                |
| `xenv`          | Execute a command in an environment.                                                                                                                                                                  |
| `runenv`        | Execute a command in an environment (alias for 'xenv').                                                                                                                                               |
| `xproc`         | Execute a procedure.                                                                                                                                                                                  |
| `runproc`       | Execute a procedure (alias for 'xproc').                                                                                                                                                              |
| `calc`          | Run a project's calculation.                                                                                                                                                                          |
| `set-env-var`   | Set an environmental variable for the project in its '.env' file.                                                                                                                                     |
| `upgrade`       | Upgrade Calkit.                                                                                                                                                                                       |
| `switch-branch` | Switch to a different branch.                                                                                                                                                                         |
| `dvc`           | Run a command with the DVC CLI. Useful if Calkit is installed as a tool, e.g., with `uv tool` or `pipx`, and DVC is not installed.                                                                    |
| `jupyter`       | Run a command with the Jupyter CLI.                                                                                                                                                                   |
| `map-paths`     | Map paths in a project. Currently this is done with copying. Outputs are ensured to be ignored by Git.                                                                                                |
| `xr`            | Execute a command and if successful, record in the pipeline.                                                                                                                                          |
| `config`        | Configure Calkit.                                                                                                                                                                                     |
| `new`           | Create a new Calkit object.                                                                                                                                                                           |
| `create`        | Create a new Calkit object (alias for 'new').                                                                                                                                                         |
| `nb`            | Work with Jupyter notebooks.                                                                                                                                                                          |
| `list`          | List Calkit objects.                                                                                                                                                                                  |
| `describe`      | Describe things.                                                                                                                                                                                      |
| `import`        | Import objects.                                                                                                                                                                                       |
| `office`        | Work with Microsoft Office.                                                                                                                                                                           |
| `update`        | Update objects.                                                                                                                                                                                       |
| `check`         | Check things.                                                                                                                                                                                         |
| `latex`         | Work with LaTeX.                                                                                                                                                                                      |
| `overleaf`      | Interact with Overleaf.                                                                                                                                                                               |
| `cloud`         | Interact with a Calkit Cloud.                                                                                                                                                                         |
| `slurm`         | Work with SLURM.                                                                                                                                                                                      |

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
| `uv-venv`                | Create a new uv virtual environment.                                                                                          |
| `venv`                   | Create a new Python virtual environment with venv.                                                                            |
| `pixi-env`               | Create a new pixi virtual environment.                                                                                        |
| `julia-env`              | Create a new Julia environment.                                                                                               |
| `renv`                   | Create a new R environment with renv.                                                                                         |
| `status`                 | Add a new project status to the log.                                                                                          |
| `python-script-stage`    | Add a stage to the pipeline that runs a Python script.                                                                        |
| `julia-script-stage`     | Add a stage to the pipeline that runs a Julia script.                                                                         |
| `matlab-script-stage`    | Add a stage to the pipeline that runs a MATLAB script.                                                                        |
| `latex-stage`            | Add a stage to the pipeline that compiles a LaTeX document.                                                                   |
| `jupyter-notebook-stage` | Add a stage to the pipeline that runs a Jupyter notebook.                                                                     |
| `release`                | Create a new release.                                                                                                         |

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
| `uv-venv`                | Create a new uv virtual environment.                                                                                          |
| `venv`                   | Create a new Python virtual environment with venv.                                                                            |
| `pixi-env`               | Create a new pixi virtual environment.                                                                                        |
| `julia-env`              | Create a new Julia environment.                                                                                               |
| `renv`                   | Create a new R environment with renv.                                                                                         |
| `status`                 | Add a new project status to the log.                                                                                          |
| `python-script-stage`    | Add a stage to the pipeline that runs a Python script.                                                                        |
| `julia-script-stage`     | Add a stage to the pipeline that runs a Julia script.                                                                         |
| `matlab-script-stage`    | Add a stage to the pipeline that runs a MATLAB script.                                                                        |
| `latex-stage`            | Add a stage to the pipeline that compiles a LaTeX document.                                                                   |
| `jupyter-notebook-stage` | Add a stage to the pipeline that runs a Jupyter notebook.                                                                     |
| `release`                | Create a new release.                                                                                                         |

### `calkit nb`

Work with Jupyter notebooks.

| Command        | Description                                                                                                                                                                                                       |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `clean`        | Clean notebook and place a copy in the cleaned notebooks directory. This can be useful to use as a preprocessing DVC stage to use a clean notebook as a dependency for a stage that caches and executed notebook. |
| `clean-all`    | Clean all notebooks in the pipeline.                                                                                                                                                                              |
| `check-kernel` | Check that an environment has a registered Jupyter kernel.                                                                                                                                                        |
| `execute`      | Execute notebook and place a copy in the relevant directory. This can be useful to use as a preprocessing DVC stage to use a clean notebook as a dependency for a stage that caches and executed notebook.        |
| `exec`         | Alias for 'execute'.                                                                                                                                                                                              |

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

### `calkit describe`

Describe things.

| Command  | Description          |
| -------- | -------------------- |
| `system` | Describe the system. |

### `calkit import`

Import objects.

| Command       | Description                                                              |
| ------------- | ------------------------------------------------------------------------ |
| `dataset`     | Import a dataset. Currently only supports datasets kept in DVC, not Git. |
| `environment` | Import an environment from another project.                              |
| `zenodo`      | Import files from a Zenodo record.                                       |

### `calkit office`

Work with Microsoft Office.

| Command                | Description                                   |
| ---------------------- | --------------------------------------------- |
| `excel-chart-to-image` | Extract a chart from Excel and save to image. |
| `word-to-pdf`          | Convert a Word document to PDF.               |

### `calkit update`

Update objects.

| Command          | Description                                                                         |
| ---------------- | ----------------------------------------------------------------------------------- |
| `devcontainer`   | Update a project's devcontainer to match the latest Calkit spec.                    |
| `license`        | Update license with a reasonable default (MIT for code, CC-BY-4.0 for other files). |
| `release`        | Update a release.                                                                   |
| `vscode-config`  | Update a project's VS Code config to match the latest Calkit recommendations.       |
| `github-actions` | Update a project's GitHub Actions to match the latest Calkit recommendations.       |

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

### `calkit latex`

Work with LaTeX.

| Command     | Description                                                                                                                                                                                                     |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `from-json` | Convert a JSON file to LaTeX. This is useful for referencing calculated values in LaTeX documents.                                                                                                              |
| `build`     | Build a PDF of a LaTeX document with latexmk. If a Calkit environment is not specified, latexmk will be run in the system environment if available. If not available, a TeX Live Docker container will be used. |

### `calkit overleaf`

Interact with Overleaf.

| Command  | Description                                                    |
| -------- | -------------------------------------------------------------- |
| `import` | Import a publication from an Overleaf project.                 |
| `sync`   | Sync folders with Overleaf.                                    |
| `status` | Check the status of folders synced with Overleaf in a project. |

### `calkit cloud`

Interact with a Calkit Cloud.

| Command | Description                        |
| ------- | ---------------------------------- |
| `get`   | Get a resource from the Cloud API. |

### `calkit slurm`

Work with SLURM.

| Command  | Description                                                                                                                                                                                                                                                                                               |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `batch`  | Submit a SLURM batch job for the project. Duplicates are not allowed, so if one is already running or queued with the same name, we'll wait for it to finish. The only exception is if the dependencies have changed, in which case any queued or running jobs will be cancelled and a new one submitted. |
| `queue`  | List SLURM jobs submitted via Calkit.                                                                                                                                                                                                                                                                     |
| `cancel` | Cancel SLURM jobs by their name in the project.                                                                                                                                                                                                                                                           |
| `logs`   | Get the logs for a SLURM job by its name in the project.                                                                                                                                                                                                                                                  |
