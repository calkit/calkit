# CLI reference

## Top-level commands

| Command                                       | Description                                                        |
| --------------------------------------------- | ------------------------------------------------------------------ |
| [`init`](#top-command-init)                   | Initialize the current working directory.                          |
| [`clone`](#top-command-clone)                 | Clone or download a copy of a project.                             |
| [`status`](#top-command-status)               | View status (project, version control, and/or pipeline).           |
| [`diff`](#top-command-diff)                   | Get a unified Git and DVC diff.                                    |
| [`add`](#top-command-add)                     | Add paths to the repo.                                             |
| [`commit`](#top-command-commit)               | Commit a change to the repo.                                       |
| [`save`](#top-command-save)                   | Save paths by committing and pushing.                              |
| [`pull`](#top-command-pull)                   | Pull with both Git and DVC.                                        |
| [`push`](#top-command-push)                   | Push with both Git and DVC.                                        |
| [`sync`](#top-command-sync)                   | Sync the project repo by pulling and then pushing.                 |
| [`ignore`](#top-command-ignore)               | Ignore a file, i.e., keep it out of version control.               |
| [`local-server`](#top-command-local-server)   | Run the local server to interact over HTTP.                        |
| [`run`](#top-command-run)                     | Check dependencies and run the pipeline.                           |
| [`manual-step`](#top-command-manual-step)     | Execute a manual step.                                             |
| [`xenv`](#top-command-xenv)                   | Execute a command in an environment.                               |
| [`xproc`](#top-command-xproc)                 | Execute a procedure.                                               |
| [`calc`](#top-command-calc)                   | Run a project's calculation.                                       |
| [`set-env-var`](#top-command-set-env-var)     | Set an environmental variable for the project in its '.env' file.  |
| [`upgrade`](#top-command-upgrade)             | Upgrade Calkit.                                                    |
| [`switch-branch`](#top-command-switch-branch) | Switch to a different branch.                                      |
| [`stash`](#top-command-stash)                 | Stash or restore workspace changes including dvc-zip tracked dirs. |
| [`dvc`](#top-command-dvc)                     | Run a command with the DVC CLI.                                    |
| [`jupyter`](#top-command-jupyter)             | Run a command with the Jupyter CLI.                                |
| [`map-paths`](#top-command-map-paths)         | Map paths in a project.                                            |
| [`xr`](#top-command-xr)                       | Execute a command and if successful, record in the pipeline.       |
| [`config`](#command-group-config)             | Configure Calkit.                                                  |
| [`new`](#command-group-new)                   | Create a new Calkit object.                                        |
| [`nb`](#command-group-nb)                     | Work with Jupyter notebooks.                                       |
| [`list`](#command-group-list)                 | List Calkit objects.                                               |
| [`describe`](#command-group-describe)         | Describe things.                                                   |
| [`import`](#command-group-import)             | Import objects.                                                    |
| [`office`](#command-group-office)             | Work with Microsoft Office.                                        |
| [`update`](#command-group-update)             | Update objects.                                                    |
| [`check`](#command-group-check)               | Check things.                                                      |
| [`latex`](#command-group-latex)               | Work with LaTeX.                                                   |
| [`overleaf`](#command-group-overleaf)         | Interact with Overleaf.                                            |
| [`cloud`](#command-group-cloud)               | Interact with a Calkit Cloud.                                      |
| [`slurm`](#command-group-slurm)               | Work with SLURM.                                                   |
| [`dev`](#command-group-dev)                   | Developer tools.                                                   |

## Top-level command details

<a id="top-command-init"></a>

### `calkit init`

Initialize the current working directory.

Usage:

```text
calkit init [OPTIONS]
```

Options:

| Option          | Type    | Required | Default | Description                                      |
| --------------- | ------- | -------- | ------- | ------------------------------------------------ |
| `--force`, `-f` | boolean | no       | False   | Force reinitializing DVC if already initialized. |

<a id="top-command-clone"></a>

### `calkit clone`

Clone or download a copy of a project.

Usage:

```text
calkit clone [OPTIONS] URL [LOCATION]
```

Arguments:

| Argument   | Type | Required | Default | Description                                          |
| ---------- | ---- | -------- | ------- | ---------------------------------------------------- |
| `url`      | text | yes      |         | Repo URL.                                            |
| `location` | text | no       |         | Location to clone to (default will be ./{repo_name}) |

Options:

| Option               | Type    | Required | Default | Description                                       |
| -------------------- | ------- | -------- | ------- | ------------------------------------------------- |
| `--ssh`              | boolean | no       | False   | Use SSH with Git.                                 |
| `--no-config-remote` | boolean | no       | False   | Do not automatically configure Calkit DVC remote. |
| `--no-dvc-pull`      | boolean | no       | False   | Do not pull DVC objects.                          |
| `--no-recursive`     | boolean | no       | False   | Do not recursively clone submodules.              |

<a id="top-command-status"></a>

### `calkit status`

View status (project, version control, and/or pipeline).

Usage:

```text
calkit status [OPTIONS] [TARGETS...]
```

Arguments:

| Argument  | Type | Required | Default | Description                                                                            |
| --------- | ---- | -------- | ------- | -------------------------------------------------------------------------------------- |
| `targets` | text | no       |         | Optional targets to check status for. These may be pipeline stage names or repo paths. |

Options:

| Option             | Type    | Required | Default | Description                                                                                       |
| ------------------ | ------- | -------- | ------- | ------------------------------------------------------------------------------------------------- |
| `--category`, `-c` | text    | no       |         | Status categories to show. By default, all categories are shown. Can be specified multiple times. |
| `--json`           | boolean | no       | False   | Output status as JSON.                                                                            |

<a id="top-command-diff"></a>

### `calkit diff`

Get a unified Git and DVC diff.

Usage:

```text
calkit diff [OPTIONS]
```

Options:

| Option     | Type    | Required | Default | Description                             |
| ---------- | ------- | -------- | ------- | --------------------------------------- |
| `--staged` | boolean | no       | False   | Show a diff from files staged with Git. |

<a id="top-command-add"></a>

### `calkit add`

Add paths to the repo.

Code will be added to Git and data will be added to DVC.

Note: This will enable the 'autostage' feature of DVC, automatically adding any .dvc files to Git when adding to DVC.

Usage:

```text
calkit add [OPTIONS] PATHS...
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `paths`  | text | yes      |         |             |

Options:

| Option                   | Type    | Required | Default | Description                                      |
| ------------------------ | ------- | -------- | ------- | ------------------------------------------------ |
| `-m`, `--commit-message` | text    | no       |         | Automatically commit and use this as a message.  |
| `--auto-message`, `-M`   | boolean | no       | False   | Commit with an automatically-generated message.  |
| `--no-auto-ignore`       | boolean | no       | False   | Disable auto-ignore.                             |
| `--push`                 | boolean | no       | False   | Push after committing.                           |
| `--to`, `-t`             | text    | no       |         | System with which to add (git, dvc, or dvc-zip). |

<a id="top-command-commit"></a>

### `calkit commit`

Commit a change to the repo.

Usage:

```text
calkit commit [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description                                |
| ----------------- | ------- | -------- | ------- | ------------------------------------------ |
| `--all`, `-a`     | boolean | no       | False   | Automatically stage all changed files.     |
| `--message`, `-m` | text    | no       |         | Commit message.                            |
| `--push`          | boolean | no       | False   | Push to both Git and DVC after committing. |

<a id="top-command-save"></a>

### `calkit save`

Save paths by committing and pushing.

This is essentially git/dvc add, commit, and push in one step.

Usage:

```text
calkit save [OPTIONS] [PATHS...]
```

Arguments:

| Argument | Type | Required | Default | Description                                                                                                  |
| -------- | ---- | -------- | ------- | ------------------------------------------------------------------------------------------------------------ |
| `paths`  | text | no       |         | Paths to add and commit. If not provided, will default to any changed files that have been added previously. |

Options:

| Option                 | Type    | Required | Default | Description                                            |
| ---------------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--all`, `-a`          | boolean | no       | False   | Save all, automatically handling staging and ignoring. |
| `--message`, `-m`      | text    | no       |         | Commit message.                                        |
| `--auto-message`, `-M` | boolean | no       | False   | Commit with an automatically-generated message.        |
| `--to`, `-t`           | text    | no       |         | System with which to add (git or dvc).                 |
| `--no-push`            | boolean | no       | False   | Do not push to Git and DVC after committing.           |
| `--git-push`           | text    | no       |         | Additional Git args to pass when pushing.              |
| `--dvc-push`           | text    | no       |         | Additional DVC args to pass when pushing.              |
| `--no-recursive`       | boolean | no       | False   | Do not push to submodules.                             |
| `--overleaf`, `-O`     | boolean | no       | False   | Sync with Overleaf after saving.                       |
| `--verbose`, `-v`      | boolean | no       | False   | Print verbose output.                                  |

<a id="top-command-pull"></a>

### `calkit pull`

Pull with both Git and DVC.

Usage:

```text
calkit pull [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description                                        |
| ----------------- | ------- | -------- | ------- | -------------------------------------------------- |
| `--no-check-auth` | boolean | no       | False   |                                                    |
| `--git-arg`       | text    | no       |         | Additional Git args.                               |
| `--dvc-arg`       | text    | no       |         | Additional DVC args.                               |
| `--force`, `-f`   | boolean | no       | False   | Force pull, potentially overwriting local changes. |
| `--no-recursive`  | boolean | no       | False   | Do not recursively pull from submodules.           |

<a id="top-command-push"></a>

### `calkit push`

Push with both Git and DVC.

Usage:

```text
calkit push [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description                |
| ----------------- | ------- | -------- | ------- | -------------------------- |
| `--no-check-auth` | boolean | no       | False   |                            |
| `--no-dvc`        | boolean | no       | False   |                            |
| `--no-git`        | boolean | no       | False   |                            |
| `--git-arg`       | text    | no       |         | Additional Git args.       |
| `--dvc-arg`       | text    | no       |         | Additional DVC args.       |
| `--no-recursive`  | boolean | no       | False   | Do not push to submodules. |

<a id="top-command-sync"></a>

### `calkit sync`

Sync the project repo by pulling and then pushing.

Usage:

```text
calkit sync [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description |
| ----------------- | ------- | -------- | ------- | ----------- |
| `--no-check-auth` | boolean | no       | False   |             |

<a id="top-command-ignore"></a>

### `calkit ignore`

Ignore a file, i.e., keep it out of version control.

Usage:

```text
calkit ignore [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description     |
| -------- | ---- | -------- | ------- | --------------- |
| `path`   | text | yes      |         | Path to ignore. |

Options:

| Option        | Type    | Required | Default | Description                          |
| ------------- | ------- | -------- | ------- | ------------------------------------ |
| `--no-commit` | boolean | no       | False   | Do not commit changes to .gitignore. |

<a id="top-command-local-server"></a>

### `calkit local-server`

Run the local server to interact over HTTP.

Usage:

```text
calkit local-server
```

<a id="top-command-run"></a>

### `calkit run`

Check dependencies and run the pipeline.

Usage:

```text
calkit run [OPTIONS] [TARGETS...]
```

Arguments:

| Argument  | Type | Required | Default | Description    |
| --------- | ---- | -------- | ------- | -------------- |
| `targets` | text | no       |         | Stages to run. |

Options:

| Option                  | Type    | Required | Default | Description                                                               |
| ----------------------- | ------- | -------- | ------- | ------------------------------------------------------------------------- |
| `-q`, `--quiet`         | boolean | no       | False   | Be quiet.                                                                 |
| `-v`, `--verbose`       | boolean | no       | False   | Print verbose output.                                                     |
| `-f`, `--force`         | boolean | no       | False   | Run even if stages or inputs have not changed.                            |
| `-i`, `--interactive`   | boolean | no       | False   | Ask for confirmation before running each stage.                           |
| `-s`, `--single-item`   | boolean | no       | False   | Run only a single stage without any dependents.                           |
| `-p`, `--pipeline`      | text    | no       |         |                                                                           |
| `-P`, `--all-pipelines` | boolean | no       | False   | Run all pipelines in the repo.                                            |
| `-R`, `--recursive`     | boolean | no       | False   | Run pipelines in subdirectories.                                          |
| `--downstream`          | text    | no       |         | Start from the specified stage and run all downstream.                    |
| `--force-downstream`    | boolean | no       | False   | Force downstream stages to run even if they are still up-to-date.         |
| `--pull`                | boolean | no       | False   | Try automatically pulling missing data.                                   |
| `--allow-missing`       | boolean | no       | False   | Skip stages with missing data.                                            |
| `--dry`                 | boolean | no       | False   | Only print commands that would execute.                                   |
| `--keep-going`, `-k`    | boolean | no       | False   | Continue executing, skipping stages with failed inputs from other stages. |
| `--ignore-errors`       | boolean | no       | False   | Ignore errors from stages.                                                |
| `--glob`                | boolean | no       | False   | Match stages with glob-style patterns.                                    |
| `--no-commit`           | boolean | no       | False   | Do not save to the run cache.                                             |
| `--no-run-cache`        | boolean | no       | False   | Ignore the run cache.                                                     |
| `--log`, `-l`           | boolean | no       | False   | Log the run and system information.                                       |
| `--save`, `-S`          | boolean | no       | False   | Save the project after running.                                           |
| `--save-message`, `-m`  | text    | no       |         | Commit message for saving.                                                |
| `--input`, `--dep`      | text    | no       |         | Run stages that depend on given input dependency path.                    |
| `--output`, `--out`     | text    | no       |         | Run stages that produce the given output path.                            |
| `--overleaf`, `-O`      | boolean | no       | False   | Sync with Overleaf before and after running.                              |

<a id="top-command-manual-step"></a>

### `calkit manual-step`

Execute a manual step.

Usage:

```text
calkit manual-step [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description                     |
| ----------------- | ------- | -------- | ------- | ------------------------------- |
| `--message`, `-m` | text    | yes      |         | Message to display as a prompt. |
| `--cmd`           | text    | no       |         | Command to run.                 |
| `--show-stdout`   | boolean | no       | False   | Show stdout.                    |
| `--show-stderr`   | boolean | no       | False   | Show stderr.                    |

<a id="top-command-xenv"></a>

### `calkit xenv`

Execute a command in an environment.

Usage:

```text
calkit xenv [OPTIONS] CMD...
```

Arguments:

| Argument | Type | Required | Default | Description                        |
| -------- | ---- | -------- | ------- | ---------------------------------- |
| `cmd`    | text | yes      |         | Command to run in the environment. |

Options:

| Option             | Type    | Required | Default | Description                                                                                                      |
| ------------------ | ------- | -------- | ------- | ---------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`     | text    | no       |         | Environment name in which to run. Only necessary if there are multiple in this project and path is not provided. |
| `--env-path`, `-p` | text    | no       |         | Path of spec of environment in which to run. Will be added to the project if it doesn't exist.                   |
| `--wdir`           | text    | no       |         | Working directory. By default will run current working directory.                                                |
| `--no-check`       | boolean | no       | False   | Don't check the environment is valid before running in it.                                                       |
| `--relaxed`        | boolean | no       | False   | Check the environment in a relaxed way, if applicable.                                                           |
| `--verbose`, `-v`  | boolean | no       | False   | Print verbose output.                                                                                            |

<a id="top-command-xproc"></a>

### `calkit xproc`

Execute a procedure.

Usage:

```text
calkit xproc [OPTIONS] NAME
```

Arguments:

| Argument | Type | Required | Default | Description                |
| -------- | ---- | -------- | ------- | -------------------------- |
| `name`   | text | yes      |         | The name of the procedure. |

Options:

| Option        | Type    | Required | Default | Description                      |
| ------------- | ------- | -------- | ------- | -------------------------------- |
| `--no-commit` | boolean | no       | False   | Do not commit after each action. |

<a id="top-command-calc"></a>

### `calkit calc`

Run a project's calculation.

Usage:

```text
calkit calc [OPTIONS] NAME
```

Arguments:

| Argument | Type | Required | Default | Description       |
| -------- | ---- | -------- | ------- | ----------------- |
| `name`   | text | yes      |         | Calculation name. |

Options:

| Option          | Type    | Required | Default | Description                               |
| --------------- | ------- | -------- | ------- | ----------------------------------------- |
| `--input`, `-i` | text    | no       |         | Inputs defined like x=1 (with no spaces.) |
| `--no-format`   | boolean | no       | False   | Do not format output before printing      |

<a id="top-command-set-env-var"></a>

### `calkit set-env-var`

Set an environmental variable for the project in its '.env' file.

Usage:

```text
calkit set-env-var NAME VALUE
```

Arguments:

| Argument | Type | Required | Default | Description            |
| -------- | ---- | -------- | ------- | ---------------------- |
| `name`   | text | yes      |         | Name of the variable.  |
| `value`  | text | yes      |         | Value of the variable. |

<a id="top-command-upgrade"></a>

### `calkit upgrade`

Upgrade Calkit.

Usage:

```text
calkit upgrade
```

<a id="top-command-switch-branch"></a>

### `calkit switch-branch`

Switch to a different branch.

Usage:

```text
calkit switch-branch NAME
```

Arguments:

| Argument | Type | Required | Default | Description  |
| -------- | ---- | -------- | ------- | ------------ |
| `name`   | text | yes      |         | Branch name. |

<a id="top-command-stash"></a>

### `calkit stash`

Stash or restore workspace changes including dvc-zip tracked dirs.

Without --pop: zips any modified workspace dirs into the DVC cache, then git-stashes (saving the updated .dvc files), checks out the committed DVC state, and unzips it to the workspace.

With --pop: pops the git stash (restoring the saved .dvc files), checks out the stashed DVC state, and unzips it to the workspace.

Usage:

```text
calkit stash [OPTIONS]
```

Options:

| Option  | Type    | Required | Default | Description                |
| ------- | ------- | -------- | ------- | -------------------------- |
| `--pop` | boolean | no       | False   | Pop the most recent stash. |

<a id="top-command-dvc"></a>

### `calkit dvc`

Run a command with the DVC CLI.

Useful if Calkit is installed as a tool, e.g., with `uv tool` or `pipx`, and DVC is not installed.

Usage:

```text
calkit dvc [OPTIONS]
```

<a id="top-command-jupyter"></a>

### `calkit jupyter`

Run a command with the Jupyter CLI.

Usage:

```text
calkit jupyter [OPTIONS]
```

<a id="top-command-map-paths"></a>

### `calkit map-paths`

Map paths in a project.

Currently this is done with copying. Outputs are ensured to be ignored by Git.

Usage:

```text
calkit map-paths [OPTIONS]
```

Options:

| Option                 | Type | Required | Default | Description                                                                                                                                                   |
| ---------------------- | ---- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--file-to-file`       | text | no       |         | Map a file to another file, e.g., --file-to-file 'results.tex->paper/results.tex'.                                                                            |
| `--file-to-dir`        | text | no       |         | Map a file into a directory, e.g., --file-to-dir 'results.tex->paper/results'.                                                                                |
| `--dir-to-dir-replace` | text | no       |         | Copy directory to another directory and replace it, e.g., --dir-to-dir-replace 'figures->paper/figures'.                                                      |
| `--dir-to-dir-merge`   | text | no       |         | Merge directory into another directory. This is useful for merging contents of one directory into another, e.g., --dir-to-dir-merge 'figures->paper/figures'. |

<a id="top-command-xr"></a>

### `calkit xr`

Execute a command and if successful, record in the pipeline.

Usage:

```text
calkit xr [OPTIONS] CMD...
```

Arguments:

| Argument | Type | Required | Default | Description                                                                                                                                                                                           |
| -------- | ---- | -------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cmd`    | text | yes      |         | Command to execute and record. If the first argument is a script, notebook or LaTeX file, it will be treated as a stage with that file as the target. Any command, including arguments, is supported. |

Options:

| Option                | Type    | Required | Default | Description                                                                                                   |
| --------------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------- |
| `--environment`, `-e` | text    | no       |         | Name of or path the spec file for the environment to use.                                                     |
| `--input`, `-i`       | text    | no       |         | Input paths to record.                                                                                        |
| `--output`, `-o`      | text    | no       |         | Output paths to record.                                                                                       |
| `--no-detect-io`      | boolean | no       | False   | Don't attempt to detect inputs and outputs from the command, script, or notebook.                             |
| `--stage`             | text    | no       |         | Name of the DVC stage to create for this command. If not provided, a name will be generated automatically.    |
| `--dry-run`, `-d`     | boolean | no       | False   | Print the environment and stage that would be created without modifying calkit.yaml or executing the command. |
| `--json`              | boolean | no       | False   | Print xr results as JSON.                                                                                     |
| `--force`, `-f`       | boolean | no       | False   | Force running stage even if it's up-to-date.                                                                  |
| `--verbose`, `-v`     | boolean | no       | False   | Print verbose output.                                                                                         |

## Command groups

<a id="command-group-config"></a>

### `calkit config`

Configure Calkit.

| Command                                                   | Description                                                                             |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| [`set`](#subcommand-config-set)                           | Set a value in the config.                                                              |
| [`get`](#subcommand-config-get)                           | Get and print a value from the config.                                                  |
| [`unset`](#subcommand-config-unset)                       | Unset a value in the config, returning it to default.                                   |
| [`remote`](#subcommand-config-remote)                     | Setup the Calkit cloud as the default DVC remote and store a token in the local config. |
| [`remote-auth`](#subcommand-config-remote-auth)           | Store a Calkit cloud token in the local DVC config for all Calkit remotes.              |
| [`list`](#subcommand-config-list)                         | List keys in the config.                                                                |
| [`github-ssh`](#subcommand-config-github-ssh)             | Walk through the process of adding an SSH key to GitHub.                                |
| [`github-codespace`](#subcommand-config-github-codespace) | Configure a GitHub Codespace.                                                           |

<a id="subcommand-config-set"></a>

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

<a id="subcommand-config-get"></a>

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

<a id="subcommand-config-unset"></a>

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

<a id="subcommand-config-remote"></a>

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

<a id="subcommand-config-remote-auth"></a>

#### `calkit config remote-auth`

Store a Calkit cloud token in the local DVC config for all Calkit remotes.

Usage:

```text
calkit config remote-auth
```

<a id="subcommand-config-list"></a>

#### `calkit config list`

List keys in the config.

Usage:

```text
calkit config list
```

<a id="subcommand-config-github-ssh"></a>

#### `calkit config github-ssh`

Walk through the process of adding an SSH key to GitHub.

Usage:

```text
calkit config github-ssh
```

<a id="subcommand-config-github-codespace"></a>

#### `calkit config github-codespace`

Configure a GitHub Codespace.

Typically this will simply mean we exchange a GitHub token for a Calkit token to use for pushing with DVC.

If this is run outside a Codespace, typically nothing will happen.

Usage:

```text
calkit config github-codespace
```

<a id="command-group-new"></a>

### `calkit new`

Create a new Calkit object.

| Command                                                            | Description                                                           |
| ------------------------------------------------------------------ | --------------------------------------------------------------------- |
| [`project`](#subcommand-new-project)                               | Create a new project.                                                 |
| [`figure`](#subcommand-new-figure)                                 | Create a new figure.                                                  |
| [`question`](#subcommand-new-question)                             | Add a new question.                                                   |
| [`notebook`](#subcommand-new-notebook)                             | Add a new notebook.                                                   |
| [`docker-env`](#subcommand-new-docker-env)                         | Create a new Docker environment.                                      |
| [`foreach-stage`](#subcommand-new-foreach-stage)                   | Create a new DVC 'foreach' stage.                                     |
| [`dataset`](#subcommand-new-dataset)                               | Create a new dataset.                                                 |
| [`publication`](#subcommand-new-publication)                       | Create a new publication.                                             |
| [`conda-env`](#subcommand-new-conda-env)                           | Create a new Conda environment.                                       |
| [`uv-env`](#subcommand-new-uv-env)                                 | Create a new uv project environment.                                  |
| [`slurm-env`](#subcommand-new-slurm-env)                           | Create a new SLURM environment.                                       |
| [`uv-venv`](#subcommand-new-uv-venv)                               | Create a new uv virtual environment.                                  |
| [`venv`](#subcommand-new-venv)                                     | Create a new Python virtual environment with venv.                    |
| [`pixi-env`](#subcommand-new-pixi-env)                             | Create a new pixi virtual environment.                                |
| [`julia-env`](#subcommand-new-julia-env)                           | Create a new Julia environment or add an existing one to calkit.yaml. |
| [`renv`](#subcommand-new-renv)                                     | Create a new R environment with renv.                                 |
| [`status`](#subcommand-new-status)                                 | Add a new project status to the log.                                  |
| [`python-script-stage`](#subcommand-new-python-script-stage)       | Add a stage to the pipeline that runs a Python script.                |
| [`julia-script-stage`](#subcommand-new-julia-script-stage)         | Add a stage to the pipeline that runs a Julia script.                 |
| [`matlab-script-stage`](#subcommand-new-matlab-script-stage)       | Add a stage to the pipeline that runs a MATLAB script.                |
| [`latex-stage`](#subcommand-new-latex-stage)                       | Add a stage to the pipeline that compiles a LaTeX document.           |
| [`jupyter-notebook-stage`](#subcommand-new-jupyter-notebook-stage) | Add a stage to the pipeline that runs a Jupyter notebook.             |
| [`release`](#subcommand-new-release)                               | Create a new release.                                                 |

<a id="subcommand-new-project"></a>

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

<a id="subcommand-new-figure"></a>

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

<a id="subcommand-new-question"></a>

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

<a id="subcommand-new-notebook"></a>

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

<a id="subcommand-new-docker-env"></a>

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

<a id="subcommand-new-foreach-stage"></a>

#### `calkit new foreach-stage`

Create a new DVC 'foreach' stage.

The list of values must be a simple list. For more complex objects, edit dvc.yaml directly.

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

<a id="subcommand-new-dataset"></a>

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

<a id="subcommand-new-publication"></a>

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

<a id="subcommand-new-conda-env"></a>

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

<a id="subcommand-new-uv-env"></a>

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

<a id="subcommand-new-slurm-env"></a>

#### `calkit new slurm-env`

Create a new SLURM environment.

Usage:

```text
calkit new slurm-env [OPTIONS]
```

Options:

| Option              | Type    | Required | Default   | Description                                                                                                                |
| ------------------- | ------- | -------- | --------- | -------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`      | text    | yes      |           | Environment name.                                                                                                          |
| `--host`            | text    | no       | localhost | Host where SLURM commands should run.                                                                                      |
| `--default-option`  | text    | no       |           | Default sbatch/srun option string (for example --gpus=1). Repeat for multiple options.                                     |
| `--default-setup`   | text    | no       |           | Default shell setup command to run before SLURM jobs (for example 'module load julia/1.11'). Repeat for multiple commands. |
| `--description`     | text    | no       |           | Description.                                                                                                               |
| `--overwrite`, `-f` | boolean | no       | False     | Overwrite any existing environment with this name.                                                                         |
| `--no-commit`       | boolean | no       | False     | Do not commit changes.                                                                                                     |

<a id="subcommand-new-uv-venv"></a>

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

<a id="subcommand-new-venv"></a>

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

<a id="subcommand-new-pixi-env"></a>

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

<a id="subcommand-new-julia-env"></a>

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

<a id="subcommand-new-renv"></a>

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

<a id="subcommand-new-status"></a>

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

<a id="subcommand-new-python-script-stage"></a>

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

<a id="subcommand-new-julia-script-stage"></a>

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

<a id="subcommand-new-matlab-script-stage"></a>

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

<a id="subcommand-new-latex-stage"></a>

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

<a id="subcommand-new-jupyter-notebook-stage"></a>

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

<a id="subcommand-new-release"></a>

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

<a id="command-group-nb"></a>

### `calkit nb`

Work with Jupyter notebooks.

| Command                                       | Description                                                         |
| --------------------------------------------- | ------------------------------------------------------------------- |
| [`clean`](#subcommand-nb-clean)               | Clean notebook and place a copy in the cleaned notebooks directory. |
| [`clean-all`](#subcommand-nb-clean-all)       | Clean all notebooks in the pipeline.                                |
| [`check-kernel`](#subcommand-nb-check-kernel) | Check that an environment has a registered Jupyter kernel.          |
| [`execute`](#subcommand-nb-execute)           | Execute notebook and place a copy in the relevant directory.        |

<a id="subcommand-nb-clean"></a>

#### `calkit nb clean`

Clean notebook and place a copy in the cleaned notebooks directory.

This can be useful to use as a preprocessing DVC stage to use a clean notebook as a dependency for a stage that caches and executed notebook.

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

<a id="subcommand-nb-clean-all"></a>

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

<a id="subcommand-nb-check-kernel"></a>

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

<a id="subcommand-nb-execute"></a>

#### `calkit nb execute`

Execute notebook and place a copy in the relevant directory.

This can be useful to use as a preprocessing DVC stage to use a clean notebook as a dependency for a stage that caches and executed notebook.

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

<a id="command-group-list"></a>

### `calkit list`

List Calkit objects.

| Command                                         | Description                       |
| ----------------------------------------------- | --------------------------------- |
| [`notebooks`](#subcommand-list-notebooks)       |                                   |
| [`figures`](#subcommand-list-figures)           |                                   |
| [`datasets`](#subcommand-list-datasets)         |                                   |
| [`publications`](#subcommand-list-publications) |                                   |
| [`references`](#subcommand-list-references)     |                                   |
| [`envs`](#subcommand-list-envs)                 | List environments in the project. |
| [`environments`](#subcommand-list-environments) | List environments in the project. |
| [`templates`](#subcommand-list-templates)       |                                   |
| [`procedures`](#subcommand-list-procedures)     |                                   |
| [`releases`](#subcommand-list-releases)         | List releases.                    |
| [`stages`](#subcommand-list-stages)             | List stages.                      |

<a id="subcommand-list-notebooks"></a>

#### `calkit list notebooks`

Usage:

```text
calkit list notebooks
```

<a id="subcommand-list-figures"></a>

#### `calkit list figures`

Usage:

```text
calkit list figures
```

<a id="subcommand-list-datasets"></a>

#### `calkit list datasets`

Usage:

```text
calkit list datasets
```

<a id="subcommand-list-publications"></a>

#### `calkit list publications`

Usage:

```text
calkit list publications
```

<a id="subcommand-list-references"></a>

#### `calkit list references`

Usage:

```text
calkit list references
```

<a id="subcommand-list-envs"></a>

#### `calkit list envs`

List environments in the project.

Usage:

```text
calkit list envs
```

<a id="subcommand-list-environments"></a>

#### `calkit list environments`

List environments in the project.

Usage:

```text
calkit list environments
```

<a id="subcommand-list-templates"></a>

#### `calkit list templates`

Usage:

```text
calkit list templates
```

<a id="subcommand-list-procedures"></a>

#### `calkit list procedures`

Usage:

```text
calkit list procedures
```

<a id="subcommand-list-releases"></a>

#### `calkit list releases`

List releases.

Usage:

```text
calkit list releases
```

<a id="subcommand-list-stages"></a>

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

<a id="command-group-describe"></a>

### `calkit describe`

Describe things.

| Command                                 | Description          |
| --------------------------------------- | -------------------- |
| [`system`](#subcommand-describe-system) | Describe the system. |

<a id="subcommand-describe-system"></a>

#### `calkit describe system`

Describe the system.

Usage:

```text
calkit describe system
```

<a id="command-group-import"></a>

### `calkit import`

Import objects.

| Command                                         | Description                                 |
| ----------------------------------------------- | ------------------------------------------- |
| [`dataset`](#subcommand-import-dataset)         | Import a dataset.                           |
| [`environment`](#subcommand-import-environment) | Import an environment from another project. |
| [`zenodo`](#subcommand-import-zenodo)           | Import files from a Zenodo record.          |

<a id="subcommand-import-dataset"></a>

#### `calkit import dataset`

Import a dataset.

Currently only supports datasets kept in DVC, not Git.

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

<a id="subcommand-import-environment"></a>

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

<a id="subcommand-import-zenodo"></a>

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

<a id="command-group-office"></a>

### `calkit office`

Work with Microsoft Office.

| Command                                                           | Description                                   |
| ----------------------------------------------------------------- | --------------------------------------------- |
| [`excel-chart-to-image`](#subcommand-office-excel-chart-to-image) | Extract a chart from Excel and save to image. |
| [`word-to-pdf`](#subcommand-office-word-to-pdf)                   | Convert a Word document to PDF.               |

<a id="subcommand-office-excel-chart-to-image"></a>

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

<a id="subcommand-office-word-to-pdf"></a>

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

<a id="command-group-update"></a>

### `calkit update`

Update objects.

| Command                                               | Description                                                                         |
| ----------------------------------------------------- | ----------------------------------------------------------------------------------- |
| [`devcontainer`](#subcommand-update-devcontainer)     | Update a project's devcontainer to match the latest Calkit spec.                    |
| [`license`](#subcommand-update-license)               | Update license with a reasonable default (MIT for code, CC-BY-4.0 for other files). |
| [`release`](#subcommand-update-release)               | Update a release.                                                                   |
| [`vscode-config`](#subcommand-update-vscode-config)   | Update a project's VS Code config to match the latest Calkit recommendations.       |
| [`github-actions`](#subcommand-update-github-actions) | Update a project's GitHub Actions to match the latest Calkit recommendations.       |
| [`notebook`](#subcommand-update-notebook)             | Update notebook information.                                                        |
| [`env`](#subcommand-update-env)                       | Update an environment.                                                              |
| [`environment`](#subcommand-update-environment)       | Update an environment.                                                              |

<a id="subcommand-update-devcontainer"></a>

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

<a id="subcommand-update-license"></a>

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

<a id="subcommand-update-release"></a>

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

<a id="subcommand-update-vscode-config"></a>

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

<a id="subcommand-update-github-actions"></a>

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

<a id="subcommand-update-notebook"></a>

#### `calkit update notebook`

Update notebook information.

Updates the notebook's environment association in either the 'notebooks' section or the appropriate 'pipeline' stage, depending on whether the notebook has a corresponding pipeline stage.

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

<a id="subcommand-update-env"></a>

#### `calkit update env`

Update an environment.

Currently only supports adding packages to Julia environments.

Usage:

```text
calkit update env [OPTIONS]
```

Options:

| Option         | Type | Required | Default | Description                       |
| -------------- | ---- | -------- | ------- | --------------------------------- |
| `--name`, `-n` | text | yes      |         | Name of the environment to update |
| `--add`        | text | no       |         | Add package to environment,       |

<a id="subcommand-update-environment"></a>

#### `calkit update environment`

Update an environment.

Currently only supports adding packages to Julia environments.

Usage:

```text
calkit update environment [OPTIONS]
```

Options:

| Option         | Type | Required | Default | Description                       |
| -------------- | ---- | -------- | ------- | --------------------------------- |
| `--name`, `-n` | text | yes      |         | Name of the environment to update |
| `--add`        | text | no       |         | Add package to environment,       |

<a id="command-group-check"></a>

### `calkit check`

Check things.

| Command                                          | Description                                                                                                  |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| [`repro`](#subcommand-check-repro)               | Check the reproducibility of a project.                                                                      |
| [`environment`](#subcommand-check-environment)   | Check that an environment is up-to-date.                                                                     |
| [`julia-env`](#subcommand-check-julia-env)       | Check a Julia environment and instantiate only when project, manifest, and package cache state have changed. |
| [`environments`](#subcommand-check-environments) |                                                                                                              |
| [`envs`](#subcommand-check-envs)                 | Check that all environments are up-to-date.                                                                  |
| [`renv`](#subcommand-check-renv)                 | Check an renv R environment, initializing if needed.                                                         |
| [`docker-env`](#subcommand-check-docker-env)     | Check that Docker environment is up-to-date.                                                                 |
| [`conda-env`](#subcommand-check-conda-env)       | Check a conda environment and rebuild if necessary.                                                          |
| [`venv`](#subcommand-check-venv)                 | Check a Python virtual environment (uv or virtualenv).                                                       |
| [`matlab-env`](#subcommand-check-matlab-env)     | Check a MATLAB environment matches its spec and export a JSON lock file.                                     |
| [`deps`](#subcommand-check-deps)                 | Check that a project's system-level dependencies are set up correctly.                                       |
| [`dependencies`](#subcommand-check-dependencies) | Check that a project's system-level dependencies are set up correctly.                                       |
| [`env-vars`](#subcommand-check-env-vars)         | Check that the project's required environmental variables exist.                                             |
| [`pipeline`](#subcommand-check-pipeline)         | Check that the project pipeline is defined correctly.                                                        |
| [`call`](#subcommand-check-call)                 | Check that a command succeeds and run an alternate if not.                                                   |

<a id="subcommand-check-repro"></a>

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

<a id="subcommand-check-environment"></a>

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

<a id="subcommand-check-julia-env"></a>

#### `calkit check julia-env`

Check a Julia environment and instantiate only when project, manifest, and package cache state have changed.

Usage:

```text
calkit check julia-env [OPTIONS] [ENV-PATH]
```

Arguments:

| Argument   | Type | Required | Default      | Description                      |
| ---------- | ---- | -------- | ------------ | -------------------------------- |
| `env_path` | text | no       | Project.toml | Path to Julia Project.toml file. |

Options:

| Option      | Type    | Required | Default | Description                            |
| ----------- | ------- | -------- | ------- | -------------------------------------- |
| `--julia`   | text    | no       |         | Julia version to enforce (e.g., 1.11). |
| `--verbose` | boolean | no       | False   | Print verbose output.                  |

<a id="subcommand-check-environments"></a>

#### `calkit check environments`

Usage:

```text
calkit check environments [OPTIONS]
```

Options:

| Option      | Type    | Required | Default | Description           |
| ----------- | ------- | -------- | ------- | --------------------- |
| `--verbose` | boolean | no       | False   | Print verbose output. |

<a id="subcommand-check-envs"></a>

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

<a id="subcommand-check-renv"></a>

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

<a id="subcommand-check-docker-env"></a>

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

<a id="subcommand-check-conda-env"></a>

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

<a id="subcommand-check-venv"></a>

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

<a id="subcommand-check-matlab-env"></a>

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

<a id="subcommand-check-deps"></a>

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

<a id="subcommand-check-dependencies"></a>

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

<a id="subcommand-check-env-vars"></a>

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

<a id="subcommand-check-pipeline"></a>

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

<a id="subcommand-check-call"></a>

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

<a id="command-group-latex"></a>

### `calkit latex`

Work with LaTeX.

| Command                                    | Description                                   |
| ------------------------------------------ | --------------------------------------------- |
| [`from-json`](#subcommand-latex-from-json) | Convert a JSON file to LaTeX.                 |
| [`build`](#subcommand-latex-build)         | Build a PDF of a LaTeX document with latexmk. |

<a id="subcommand-latex-from-json"></a>

#### `calkit latex from-json`

Convert a JSON file to LaTeX.

This is useful for referencing calculated values in LaTeX documents.

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

<a id="subcommand-latex-build"></a>

#### `calkit latex build`

Build a PDF of a LaTeX document with latexmk.

If a Calkit environment is not specified, latexmk will be run in the system environment if available. If not available, a TeX Live Docker container will be used.

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

<a id="command-group-overleaf"></a>

### `calkit overleaf`

Interact with Overleaf.

| Command                                 | Description                                                    |
| --------------------------------------- | -------------------------------------------------------------- |
| [`import`](#subcommand-overleaf-import) | Import a publication from an Overleaf project.                 |
| [`sync`](#subcommand-overleaf-sync)     | Sync folders with Overleaf.                                    |
| [`status`](#subcommand-overleaf-status) | Check the status of folders synced with Overleaf in a project. |

<a id="subcommand-overleaf-import"></a>

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

<a id="subcommand-overleaf-sync"></a>

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

<a id="subcommand-overleaf-status"></a>

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

<a id="command-group-cloud"></a>

### `calkit cloud`

Interact with a Calkit Cloud.

| Command                        | Description                        |
| ------------------------------ | ---------------------------------- |
| [`get`](#subcommand-cloud-get) | Get a resource from the Cloud API. |

<a id="subcommand-cloud-get"></a>

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

<a id="command-group-slurm"></a>

### `calkit slurm`

Work with SLURM.

| Command                              | Description                                              |
| ------------------------------------ | -------------------------------------------------------- |
| [`batch`](#subcommand-slurm-batch)   | Submit a SLURM batch job for the project.                |
| [`queue`](#subcommand-slurm-queue)   | List SLURM jobs submitted via Calkit.                    |
| [`cancel`](#subcommand-slurm-cancel) | Cancel SLURM jobs by their name in the project.          |
| [`logs`](#subcommand-slurm-logs)     | Get the logs for a SLURM job by its name in the project. |

<a id="subcommand-slurm-batch"></a>

#### `calkit slurm batch`

Submit a SLURM batch job for the project.

Duplicates are not allowed, so if one is already running or queued with the same name, we'll wait for it to finish. The only exception is if the dependencies have changed, in which case any queued or running jobs will be canceled and a new one submitted.

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

| Option                  | Type    | Required | Default | Description                                                                                                                              |
| ----------------------- | ------- | -------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`          | text    | yes      |         | Job name.                                                                                                                                |
| `--environment`, `-e`   | text    | yes      |         | Calkit (slurm) environment to use for the job.                                                                                           |
| `--dep`, `-d`           | text    | no       |         | Additional dependencies to track, which if changed signify a job is invalid.                                                             |
| `--out`, `-o`           | text    | no       |         | Non-persistent output files or directories produced by the job, which will be deleted before submitting a new job.                       |
| `--sbatch-option`, `-s` | text    | no       |         | Additional options to pass to sbatch (no spaces allowed).                                                                                |
| `--setup`               | text    | no       |         | Shell setup command to run before launching the target (repeat for multiple commands). Will ignore environment's default setup commands. |
| `--log-path`            | text    | no       |         | Output log path.                                                                                                                         |
| `--command`             | boolean | no       |         | Whether the target is a command instead of a script.                                                                                     |

<a id="subcommand-slurm-queue"></a>

#### `calkit slurm queue`

List SLURM jobs submitted via Calkit.

Usage:

```text
calkit slurm queue
```

<a id="subcommand-slurm-cancel"></a>

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

<a id="subcommand-slurm-logs"></a>

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

<a id="command-group-dev"></a>

### `calkit dev`

Developer tools.

| Command                              | Description                                     |
| ------------------------------------ | ----------------------------------------------- |
| [`python`](#subcommand-dev-python)   | Start an Python shell in Calkit's environment.  |
| [`ipython`](#subcommand-dev-ipython) | Start an IPython shell in Calkit's environment. |

<a id="subcommand-dev-python"></a>

#### `calkit dev python`

Start an Python shell in Calkit's environment.

Usage:

```text
calkit dev python [OPTIONS]
```

<a id="subcommand-dev-ipython"></a>

#### `calkit dev ipython`

Start an IPython shell in Calkit's environment.

Usage:

```text
calkit dev ipython [OPTIONS]
```
