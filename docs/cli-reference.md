# CLI reference

<!-- prettier-ignore -->
!!! note
    `ck` is an abbreviated alias for the `calkit` executable.
    All `calkit` commands can be run as `ck` instead, e.g., `ck save -am "..."`.

## Top-level commands

| Command                                          | Description                                                                                                  |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| [`init`](#top-command-init)                      | Initialize the current working directory.                                                                    |
| [`clone`](#top-command-clone)                    | Clone or download a copy of a project.                                                                       |
| [`status\|st`](#top-command-status-st)           | View status (project, version control, and/or pipeline).                                                     |
| [`diff`](#top-command-diff)                      | Get a unified Git and DVC diff.                                                                              |
| [`add`](#top-command-add)                        | Add paths to the repo.                                                                                       |
| [`commit`](#top-command-commit)                  | Commit a change to the repo.                                                                                 |
| [`save\|sv`](#top-command-save-sv)               | Save paths by committing and pushing.                                                                        |
| [`pull`](#top-command-pull)                      | Pull with both Git and DVC.                                                                                  |
| [`push`](#top-command-push)                      | Push to Git, DVC, and any Docker registries.                                                                 |
| [`ignore`](#top-command-ignore)                  | Ignore a file, i.e., keep it out of version control.                                                         |
| [`local-server`](#top-command-local-server)      | Run the local server to interact over HTTP.                                                                  |
| [`run`](#top-command-run)                        | Check requirements and run the pipeline.                                                                     |
| [`manual-step`](#top-command-manual-step)        | Execute a manual step.                                                                                       |
| [`xenv\|runenv`](#top-command-xenv-runenv)       | Execute a command in an environment.                                                                         |
| [`install`](#top-command-install)                | Install a registered native dependency (e.g., pixi, uv) via its upstream installer for the current platform. |
| [`xproc\|runproc`](#top-command-xproc-runproc)   | Execute a procedure.                                                                                         |
| [`calc`](#top-command-calc)                      | Run a project's calculation.                                                                                 |
| [`set-env-var`](#top-command-set-env-var)        | Set an environmental variable for the project in its '.env' file.                                            |
| [`upgrade`](#top-command-upgrade)                | Upgrade Calkit.                                                                                              |
| [`switch-branch`](#top-command-switch-branch)    | Switch to a different branch.                                                                                |
| [`stash`](#top-command-stash)                    | Stash or restore workspace changes including dvc-zip tracked dirs.                                           |
| [`dvc`](#top-command-dvc)                        | Run a command with the DVC CLI.                                                                              |
| [`jupyter`](#top-command-jupyter)                | Run a command with the Jupyter CLI.                                                                          |
| [`map-paths`](#top-command-map-paths)            | Map paths in a project.                                                                                      |
| [`xr`](#top-command-xr)                          | Execute a command and if successful, record in the pipeline.                                                 |
| [`config`](#command-group-config)                | Configure Calkit.                                                                                            |
| [`new\|create`](#command-group-new-create)       | Create a new Calkit object.                                                                                  |
| [`delete\|rm`](#command-group-delete-rm)         | Delete a Calkit object.                                                                                      |
| [`notebooks\|nb`](#command-group-notebooks-nb)   | Work with computational notebooks.                                                                           |
| [`list\|ls`](#command-group-list-ls)             | List Calkit objects.                                                                                         |
| [`describe\|desc`](#command-group-describe-desc) | Describe things.                                                                                             |
| [`import`](#command-group-import)                | Import objects.                                                                                              |
| [`office`](#command-group-office)                | Work with Microsoft Office.                                                                                  |
| [`update`](#command-group-update)                | Update objects.                                                                                              |
| [`check`](#command-group-check)                  | Check things.                                                                                                |
| [`latex\|tex`](#command-group-latex-tex)         | Work with LaTeX.                                                                                             |
| [`overleaf\|ol`](#command-group-overleaf-ol)     | Interact with Overleaf.                                                                                      |
| [`hub\|cloud`](#command-group-hub-cloud)         | Interact with a Calkit hub.                                                                                  |
| [`scheduler\|sch`](#command-group-scheduler-sch) | Work with a job scheduler (SLURM or PBS).                                                                    |
| [`dev`](#command-group-dev)                      | Developer tools.                                                                                             |
| [`sync`](#command-group-sync)                    | Sync with external systems.                                                                                  |

## Top-level command details

<a id="top-command-init"></a>

### `calkit init`

Initialize the current working directory.

Usage:

```text
calkit init [OPTIONS]
```

Options:

| Option          | Type    | Required | Default | Description                                               |
| --------------- | ------- | -------- | ------- | --------------------------------------------------------- |
| `--force`, `-f` | boolean | no       | False   | Re-initialize even if the project is already initialized. |
| `--no-commit`   | boolean | no       | False   | Stage the initial files rather than committing them.      |

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
| `url`      | str  | yes      |         | Repo URL.                                            |
| `location` | str  | no       |         | Location to clone to (default will be ./{repo_name}) |

Options:

| Option               | Type    | Required | Default | Description                                       |
| -------------------- | ------- | -------- | ------- | ------------------------------------------------- |
| `--ssh`              | boolean | no       | False   | Use SSH with Git.                                 |
| `--no-config-remote` | boolean | no       | False   | Do not automatically configure Calkit DVC remote. |
| `--no-dvc-pull`      | boolean | no       | False   | Do not pull DVC objects.                          |
| `--no-recursive`     | boolean | no       | False   | Do not recursively clone submodules.              |

<a id="top-command-status-st"></a>

### `calkit status|st`

View status (project, version control, and/or pipeline).

Usage:

```text
calkit status|st [OPTIONS] [TARGETS...]
```

Arguments:

| Argument  | Type | Required | Default | Description                                                                            |
| --------- | ---- | -------- | ------- | -------------------------------------------------------------------------------------- |
| `targets` | str  | no       |         | Optional targets to check status for. These may be pipeline stage names or repo paths. |

Options:

| Option             | Type    | Required | Default | Description                                                                                                                  |
| ------------------ | ------- | -------- | ------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `--category`, `-c` | str     | no       |         | Status categories to show. By default, all categories are shown. Can be specified multiple times.                            |
| `--no-env-check`   | boolean | no       | False   | Skip environment checks. Note that this may produce an inaccurate pipeline status if materialized environments have changed. |
| `--json`           | boolean | no       | False   | Output status as JSON.                                                                                                       |

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
| `paths`  | str  | yes      |         |             |

Options:

| Option                   | Type    | Required | Default | Description                                          |
| ------------------------ | ------- | -------- | ------- | ---------------------------------------------------- |
| `-m`, `--commit-message` | str     | no       |         | Automatically commit and use this as a message.      |
| `--auto-message`, `-M`   | boolean | no       | False   | Commit with an automatically-generated message.      |
| `--no-auto-ignore`       | boolean | no       | False   | Disable auto-ignore.                                 |
| `--push`                 | boolean | no       | False   | Push after committing.                               |
| `--to`, `-t`             | str     | no       |         | System with which to add (git, dvc, or dvc-zip).     |
| `--dry-run`, `--dry`     | boolean | no       | False   | Show what would be added without actually adding it. |

<a id="top-command-commit"></a>

### `calkit commit`

Commit a change to the repo.

Usage:

```text
calkit commit [OPTIONS] [PATHS...]
```

Arguments:

| Argument | Type | Required | Default | Description                                                                                          |
| -------- | ---- | -------- | ------- | ---------------------------------------------------------------------------------------------------- |
| `paths`  | str  | no       |         | Paths to commit. If not provided, will default to any changed files that have been added previously. |

Options:

| Option                        | Type    | Required | Default | Description                                |
| ----------------------------- | ------- | -------- | ------- | ------------------------------------------ |
| `--all`, `-a`                 | boolean | no       | False   | Automatically stage all changed files.     |
| `--message`, `-m`             | str     | no       |         | Commit message.                            |
| `--auto-commit-message`, `-M` | boolean | no       | False   | Automatically generate a commit message.   |
| `--push`                      | boolean | no       | False   | Push to both Git and DVC after committing. |
| `--verbose`                   | boolean | no       | False   | Print verbose output.                      |

<a id="top-command-save-sv"></a>

### `calkit save|sv`

Save paths by committing and pushing.

This is essentially git/dvc add, commit, and push in one step.

Usage:

```text
calkit save|sv [OPTIONS] [PATHS...]
```

Arguments:

| Argument | Type | Required | Default | Description                                                                                                  |
| -------- | ---- | -------- | ------- | ------------------------------------------------------------------------------------------------------------ |
| `paths`  | str  | no       |         | Paths to add and commit. If not provided, will default to any changed files that have been added previously. |

Options:

| Option                 | Type    | Required | Default | Description                                            |
| ---------------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--all`, `-a`          | boolean | no       | False   | Save all, automatically handling staging and ignoring. |
| `--message`, `-m`      | str     | no       |         | Commit message.                                        |
| `--auto-message`, `-M` | boolean | no       | False   | Commit with an automatically-generated message.        |
| `--to`, `-t`           | str     | no       |         | System with which to add (git or dvc).                 |
| `--no-push`            | boolean | no       | False   | Do not push to Git and DVC after committing.           |
| `--git-push`           | str     | no       |         | Additional Git args to pass when pushing.              |
| `--dvc-push`           | str     | no       |         | Additional DVC args to pass when pushing.              |
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
| `--no-dvc`        | boolean | no       | False   | Do not pull from DVC.                              |
| `--no-git`        | boolean | no       | False   | Do not pull from Git.                              |
| `--git-arg`       | str     | no       |         | Additional Git args.                               |
| `--dvc-arg`       | str     | no       |         | Additional DVC args.                               |
| `--force`, `-f`   | boolean | no       | False   | Force pull, potentially overwriting local changes. |
| `--no-recursive`  | boolean | no       | False   | Do not recursively pull from submodules.           |

<a id="top-command-push"></a>

### `calkit push`

Push to Git, DVC, and any Docker registries.

Usage:

```text
calkit push [OPTIONS] [TARGETS...]
```

Arguments:

| Argument  | Type | Required | Default | Description                                                      |
| --------- | ---- | -------- | ------- | ---------------------------------------------------------------- |
| `targets` | str  | no       |         | What to push: 'git', 'dvc', 'docker', or 'all'. Defaults to all. |

Options:

| Option            | Type    | Required | Default | Description                                    |
| ----------------- | ------- | -------- | ------- | ---------------------------------------------- |
| `--no-check-auth` | boolean | no       | False   | Do not check DVC remote authentication.        |
| `--no-dvc`        | boolean | no       | False   | Do not push to DVC remotes.                    |
| `--no-git`        | boolean | no       | False   | Do not push to Git remote.                     |
| `--git-arg`       | str     | no       |         | Additional Git args.                           |
| `--dvc-arg`       | str     | no       |         | Additional DVC args.                           |
| `--no-docker`     | boolean | no       | False   | Do not push Docker images to their registries. |
| `--no-recursive`  | boolean | no       | False   | Do not push to submodules.                     |

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
| `path`   | str  | yes      |         | Path to ignore. |

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

Check requirements and run the pipeline.

Usage:

```text
calkit run [OPTIONS] [TARGETS...]
```

Arguments:

| Argument  | Type | Required | Default | Description    |
| --------- | ---- | -------- | ------- | -------------- |
| `targets` | str  | no       |         | Stages to run. |

Options:

| Option                   | Type    | Required | Default | Description                                                                                  |
| ------------------------ | ------- | -------- | ------- | -------------------------------------------------------------------------------------------- |
| `-q`, `--quiet`          | boolean | no       | False   | Be quiet.                                                                                    |
| `-v`, `--verbose`        | boolean | no       | False   | Print verbose output.                                                                        |
| `-f`, `--force`          | boolean | no       | False   | Run even if stages or inputs have not changed.                                               |
| `-i`, `--interactive`    | boolean | no       | False   | Ask for confirmation before running each stage.                                              |
| `-s`, `--single-item`    | boolean | no       | False   | Run only a single stage without any dependents.                                              |
| `-p`, `--pipeline`       | str     | no       |         |                                                                                              |
| `-P`, `--all-pipelines`  | boolean | no       | False   | Run all pipelines in the repo.                                                               |
| `-R`, `--recursive`      | boolean | no       | False   | Run pipelines in subdirectories.                                                             |
| `--downstream`           | str     | no       |         | Start from the specified stage and run all downstream.                                       |
| `--force-downstream`     | boolean | no       | False   | Force downstream stages to run even if they are still up-to-date.                            |
| `--pull`                 | boolean | no       | False   | Try automatically pulling missing data.                                                      |
| `--allow-missing`        | boolean | no       | False   | Skip stages with missing data.                                                               |
| `--dry`, `--dry-run`     | boolean | no       | False   | Only print commands that would execute.                                                      |
| `--keep-going`, `-k`     | boolean | no       | False   | Continue executing, skipping stages with failed inputs from other stages.                    |
| `--ignore-errors`        | boolean | no       | False   | Ignore errors from stages.                                                                   |
| `--glob`                 | boolean | no       | False   | Match stages with glob-style patterns.                                                       |
| `--no-commit`            | boolean | no       | False   | Do not save to the run cache.                                                                |
| `--no-run-cache`         | boolean | no       | False   | Ignore the run cache.                                                                        |
| `--log`, `-l`            | boolean | no       | False   | Log the run and system information.                                                          |
| `--save`, `-S`           | boolean | no       | False   | Save the project after running.                                                              |
| `--save-message`, `-m`   | str     | no       |         | Commit message for saving.                                                                   |
| `--input`, `--dep`       | str     | no       |         | Run stages that depend on given input dependency path.                                       |
| `--output`, `--out`      | str     | no       |         | Run stages that produce the given output path.                                               |
| `--overleaf`, `-O`       | boolean | no       | False   | Sync with Overleaf before and after running.                                                 |
| `--no-push`              | boolean | no       | False   | Do not push to Git and DVC after saving.                                                     |
| `--mock-scheduler`, `-K` | boolean | no       | False   | Run job-scheduler (SLURM/PBS) stages locally instead of submitting them to a real scheduler. |

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
| `--message`, `-m` | str     | yes      |         | Message to display as a prompt. |
| `--cmd`           | str     | no       |         | Command to run.                 |
| `--show-stdout`   | boolean | no       | False   | Show stdout.                    |
| `--show-stderr`   | boolean | no       | False   | Show stderr.                    |

<a id="top-command-xenv-runenv"></a>

### `calkit xenv|runenv`

Execute a command in an environment.

Usage:

```text
calkit xenv|runenv [OPTIONS] CMD...
```

Arguments:

| Argument | Type | Required | Default | Description                        |
| -------- | ---- | -------- | ------- | ---------------------------------- |
| `cmd`    | str  | yes      |         | Command to run in the environment. |

Options:

| Option             | Type    | Required | Default | Description                                                                                                                                                                                                                         |
| ------------------ | ------- | -------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`     | str     | no       |         | Environment name in which to run. Only necessary if there are multiple in this project and path is not provided.                                                                                                                    |
| `--env-path`, `-p` | str     | no       |         | Path of spec of environment in which to run. Will be added to the project if it doesn't exist.                                                                                                                                      |
| `--wdir`           | str     | no       |         | Working directory. By default will run current working directory.                                                                                                                                                                   |
| `--no-check`       | boolean | no       | False   | Don't check the environment is valid before running in it.                                                                                                                                                                          |
| `--relaxed`        | boolean | no       | False   | Check the environment in a relaxed way, if applicable.                                                                                                                                                                              |
| `--setup`          | str     | no       |         | Shell command to run before the command, in the same shell (repeat for multiple). A pipeline stage gets these from its own 'setup' and its environment's 'default_setup', already combined when the pipeline is compiled.           |
| `--setup-file`     | str     | no       |         | Path to a JSON list of setup commands, used instead of --setup. This is what a compiled pipeline stage carries, since a path survives being parsed by cmd.exe on Windows and by a POSIX shell elsewhere, and quoted commands don't. |
| `--verbose`, `-v`  | boolean | no       | False   | Print verbose output.                                                                                                                                                                                                               |

<a id="top-command-install"></a>

### `calkit install`

Install a registered native dependency (e.g., pixi, uv) via its upstream installer for the current platform.

Usage:

```text
calkit install [OPTIONS] NAME
```

Arguments:

| Argument | Type | Required | Default | Description                              |
| -------- | ---- | -------- | ------- | ---------------------------------------- |
| `name`   | str  | yes      |         | The app to install (e.g., 'pixi', 'uv'). |

Options:

| Option        | Type    | Required | Default | Description                                           |
| ------------- | ------- | -------- | ------- | ----------------------------------------------------- |
| `--yes`, `-y` | boolean | no       | False   | Skip the confirmation prompt and install immediately. |

<a id="top-command-xproc-runproc"></a>

### `calkit xproc|runproc`

Execute a procedure.

Usage:

```text
calkit xproc|runproc [OPTIONS] NAME
```

Arguments:

| Argument | Type | Required | Default | Description                |
| -------- | ---- | -------- | ------- | -------------------------- |
| `name`   | str  | yes      |         | The name of the procedure. |

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
| `name`   | str  | yes      |         | Calculation name. |

Options:

| Option          | Type    | Required | Default | Description                               |
| --------------- | ------- | -------- | ------- | ----------------------------------------- |
| `--input`, `-i` | str     | no       |         | Inputs defined like x=1 (with no spaces.) |
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
| `name`   | str  | yes      |         | Name of the variable.  |
| `value`  | str  | yes      |         | Value of the variable. |

<a id="top-command-upgrade"></a>

### `calkit upgrade`

Upgrade Calkit.

Usage:

```text
calkit upgrade [OPTIONS]
```

Options:

| Option     | Type    | Required | Default | Description                   |
| ---------- | ------- | -------- | ------- | ----------------------------- |
| `--skills` | boolean | no       | False   | Upgrade agent skills as well. |

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
| `name`   | str  | yes      |         | Branch name. |

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
| `--file-to-file`       | str  | no       |         | Map a file to another file, e.g., --file-to-file 'results.tex->paper/results.tex'.                                                                            |
| `--file-to-dir`        | str  | no       |         | Map a file into a directory, e.g., --file-to-dir 'results.tex->paper/results'.                                                                                |
| `--dir-to-dir-replace` | str  | no       |         | Copy directory to another directory and replace it, e.g., --dir-to-dir-replace 'figures->paper/figures'.                                                      |
| `--dir-to-dir-merge`   | str  | no       |         | Merge directory into another directory. This is useful for merging contents of one directory into another, e.g., --dir-to-dir-merge 'figures->paper/figures'. |

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
| `cmd`    | str  | yes      |         | Command to execute and record. If the first argument is a script, notebook or LaTeX file, it will be treated as a stage with that file as the target. Any command, including arguments, is supported. |

Options:

| Option                | Type    | Required | Default | Description                                                                                                                                                                                                                                                                                                     |
| --------------------- | ------- | -------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--environment`, `-e` | str     | no       |         | Name of or path the spec file for the environment to use.                                                                                                                                                                                                                                                       |
| `--input`, `-i`       | str     | no       |         | Input paths to record.                                                                                                                                                                                                                                                                                          |
| `--output`, `-o`      | str     | no       |         | Output paths to record.                                                                                                                                                                                                                                                                                         |
| `--no-detect-io`      | boolean | no       | False   | Don't attempt to detect inputs and outputs from the command, script, or notebook.                                                                                                                                                                                                                               |
| `--stage`             | str     | no       |         | Name of the DVC stage to create for this command. If not provided, a name will be generated automatically.                                                                                                                                                                                                      |
| `--dry-run`, `-d`     | boolean | no       | False   | Print the environment and stage that would be created without modifying calkit.yaml or executing the command.                                                                                                                                                                                                   |
| `--no-record`         | boolean | no       | False   | Execute without recording: run as usual, then restore calkit.yaml, dvc.yaml and .dvc and remove derived files, keeping only what the run produced (annotations, injected output, stage outputs) and the run log. Useful for checking that a Markdown file is runnable in a project that isn't a Calkit project. |
| `--json`              | boolean | no       | False   | Print xr results as JSON.                                                                                                                                                                                                                                                                                       |
| `--force`, `-f`       | boolean | no       | False   | Force running stage even if it's up-to-date.                                                                                                                                                                                                                                                                    |
| `--verbose`, `-v`     | boolean | no       | False   | Print verbose output.                                                                                                                                                                                                                                                                                           |

## Command groups

<a id="command-group-config"></a>

### `calkit config`

Configure Calkit.

| Command                                                   | Description                                                                            |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| [`set`](#subcommand-config-set)                           | Set a value in the config.                                                             |
| [`get`](#subcommand-config-get)                           | Get and print a value from the config.                                                 |
| [`unset`](#subcommand-config-unset)                       | Unset a value in the config, returning it to default.                                  |
| [`remote`](#subcommand-config-remote)                     | Set up the Calkit hub as the default DVC remote and store a token in the local config. |
| [`remote-auth`](#subcommand-config-remote-auth)           | Store a Calkit hub token in the local DVC config for all Calkit remotes.               |
| [`list`](#subcommand-config-list)                         | List keys in the config.                                                               |
| [`github-ssh`](#subcommand-config-github-ssh)             | Walk through the process of adding an SSH key to GitHub.                               |
| [`github-codespace`](#subcommand-config-github-codespace) | Configure a GitHub Codespace.                                                          |

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
| `key`    | str  | yes      |         |             |
| `value`  | str  | yes      |         |             |

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
| `key`    | str  | yes      |         |             |

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
| `key`    | str  | yes      |         |             |

<a id="subcommand-config-remote"></a>

#### `calkit config remote`

Set up the Calkit hub as the default DVC remote and store a token in the local config.

Usage:

```text
calkit config remote [OPTIONS]
```

Options:

| Option        | Type    | Required | Default | Description                                                         |
| ------------- | ------- | -------- | ------- | ------------------------------------------------------------------- |
| `--http`      | boolean | no       | False   | Use the legacy HTTP URL for the Calkit DVC remote instead of ck://. |
| `--no-commit` | boolean | no       | False   | Do not commit changes to DVC config.                                |

<a id="subcommand-config-remote-auth"></a>

#### `calkit config remote-auth`

Store a Calkit hub token in the local DVC config for all Calkit remotes.

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

<a id="command-group-new-create"></a>

### `calkit new|create`

Create a new Calkit object.

| Command                                                                   | Description                                                           |
| ------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| [`project`](#subcommand-new-create-project)                               | Create a new project.                                                 |
| [`figure\|fig`](#subcommand-new-create-figure-fig)                        | Create a new figure.                                                  |
| [`result`](#subcommand-new-create-result)                                 | Declare a new result.                                                 |
| [`presentation\|pres`](#subcommand-new-create-presentation-pres)          | Declare a new presentation.                                           |
| [`question`](#subcommand-new-create-question)                             | Add a new question.                                                   |
| [`notebook\|nb`](#subcommand-new-create-notebook-nb)                      | Add a new notebook.                                                   |
| [`docker-env`](#subcommand-new-create-docker-env)                         | Create a new Docker environment.                                      |
| [`foreach-stage`](#subcommand-new-create-foreach-stage)                   | Create a new DVC 'foreach' stage.                                     |
| [`dataset`](#subcommand-new-create-dataset)                               | Create a new dataset.                                                 |
| [`publication\|pub`](#subcommand-new-create-publication-pub)              | Create a new publication.                                             |
| [`conda-env`](#subcommand-new-create-conda-env)                           | Create a new Conda environment.                                       |
| [`uv-env`](#subcommand-new-create-uv-env)                                 | Create a new uv project environment.                                  |
| [`slurm-env`](#subcommand-new-create-slurm-env)                           | Create a new SLURM environment.                                       |
| [`pbs-env`](#subcommand-new-create-pbs-env)                               | Create a new PBS environment.                                         |
| [`uv-venv`](#subcommand-new-create-uv-venv)                               | Create a new uv virtual environment.                                  |
| [`venv`](#subcommand-new-create-venv)                                     | Create a new Python virtual environment with venv.                    |
| [`pixi-env`](#subcommand-new-create-pixi-env)                             | Create a new pixi virtual environment.                                |
| [`julia-env`](#subcommand-new-create-julia-env)                           | Create a new Julia environment or add an existing one to calkit.yaml. |
| [`renv`](#subcommand-new-create-renv)                                     | Create a new R environment with renv.                                 |
| [`nix-env`](#subcommand-new-create-nix-env)                               | Create a new Nix flake-based environment.                             |
| [`status`](#subcommand-new-create-status)                                 | Add a new project status to the log.                                  |
| [`python-script-stage`](#subcommand-new-create-python-script-stage)       | Add a stage to the pipeline that runs a Python script.                |
| [`julia-script-stage`](#subcommand-new-create-julia-script-stage)         | Add a stage to the pipeline that runs a Julia script.                 |
| [`matlab-script-stage`](#subcommand-new-create-matlab-script-stage)       | Add a stage to the pipeline that runs a MATLAB script.                |
| [`latex-stage`](#subcommand-new-create-latex-stage)                       | Add a stage to the pipeline that compiles a LaTeX document.           |
| [`jupyter-notebook-stage`](#subcommand-new-create-jupyter-notebook-stage) | Add a stage to the pipeline that runs a Jupyter notebook.             |
| [`release`](#subcommand-new-create-release)                               | Create a new release.                                                 |

<a id="subcommand-new-create-project"></a>

#### `calkit new|create project`

Create a new project.

Usage:

```text
calkit new|create project [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description                  |
| -------- | ---- | -------- | ------- | ---------------------------- |
| `path`   | str  | yes      |         | Where to create the project. |

Options:

| Option              | Type    | Required | Default | Description                                                                                                                                                                                                 |
| ------------------- | ------- | -------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`      | str     | no       |         | Project name. Will be inferred as kebab-cased directory name if not provided.                                                                                                                               |
| `--title`           | str     | no       |         | Project title.                                                                                                                                                                                              |
| `--description`     | str     | no       |         | Project description.                                                                                                                                                                                        |
| `--hub`, `--cloud`  | str     | no       |         | Create this project on a Calkit hub (and GitHub). Optionally takes a hub URL; bare --hub (or the special value 'default') uses the default_hub config value, else calkit.io. --cloud is a deprecated alias. |
| `--public`          | boolean | no       | False   | Create as a public project if --hub is selected.                                                                                                                                                            |
| `--git-url`         | str     | no       |         | Git repo URL. Usually https://github.com/{your_name}/{project_name}.                                                                                                                                        |
| `--template`, `-t`  | str     | no       |         | Template from which to derive the project, e.g., 'calkit/example-basic'.                                                                                                                                    |
| `--no-commit`       | boolean | no       |         | Do not commit changes to Git.                                                                                                                                                                               |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite project if one already exists.                                                                                                                                                                    |
| `--verbose`         | boolean | no       | False   | Print verbose output.                                                                                                                                                                                       |

<a id="subcommand-new-create-figure-fig"></a>

#### `calkit new|create figure|fig`

Create a new figure.

Usage:

```text
calkit new|create figure|fig [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `path`   | str  | yes      |         |             |

Options:

| Option                   | Type    | Required | Default | Description                                                                               |
| ------------------------ | ------- | -------- | ------- | ----------------------------------------------------------------------------------------- |
| `--title`                | str     | yes      |         |                                                                                           |
| `--description`          | str     | yes      |         |                                                                                           |
| `--stage`                | str     | no       |         | Name of the pipeline stage that generates this figure.                                    |
| `--cmd`                  | str     | no       |         | Command to add to the stage, if specified.                                                |
| `--dep`                  | str     | no       |         | Path to stage dependency.                                                                 |
| `--out`                  | str     | no       |         | Path to stage output. Figure path will be added automatically.                            |
| `--deps-from-stage-outs` | str     | no       |         | Stage name from which to add outputs as dependencies.                                     |
| `--created-by-email`     | str     | no       |         | Email of whoever made this figure, for one drawn by hand rather than produced by a stage. |
| `--created-by-orcid`     | str     | no       |         | ORCID of whoever made this figure.                                                        |
| `--created-with-ai`      | str     | no       |         | Generative AI tool they used, e.g. 'Claude Opus 5'. Repeat for several.                   |
| `--no-commit`            | boolean | no       | False   |                                                                                           |
| `--overwrite`, `-f`      | boolean | no       | False   | Overwrite existing figure if one exists.                                                  |

<a id="subcommand-new-create-result"></a>

#### `calkit new|create result`

Declare a new result.

Usage:

```text
calkit new|create result [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `path`   | str  | yes      |         |             |

Options:

| Option              | Type    | Required | Default | Description                                                                                    |
| ------------------- | ------- | -------- | ------- | ---------------------------------------------------------------------------------------------- |
| `--name`            | str     | no       |         | Short handle for referring to this result, which stays stable if the file is renamed.          |
| `--title`           | str     | no       |         |                                                                                                |
| `--key`             | str     | no       |         | Path to the value within the file, e.g., 'metrics.mean'. Omit if the whole file is the result. |
| `--description`     | str     | no       |         |                                                                                                |
| `--stage`           | str     | no       |         | Name of the pipeline stage that generates this result.                                         |
| `--no-commit`       | boolean | no       | False   |                                                                                                |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite existing result if one exists.                                                       |

<a id="subcommand-new-create-presentation-pres"></a>

#### `calkit new|create presentation|pres`

Declare a new presentation.

Usage:

```text
calkit new|create presentation|pres [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `path`   | str  | yes      |         |             |

Options:

| Option              | Type    | Required | Default | Description                                                  |
| ------------------- | ------- | -------- | ------- | ------------------------------------------------------------ |
| `--title`           | str     | yes      |         |                                                              |
| `--description`     | str     | no       |         |                                                              |
| `--kind`            | str     | no       |         | Kind of presentation, either 'slides' or 'poster'.           |
| `--stage`           | str     | no       |         | Name of the pipeline stage that generates this presentation. |
| `--no-commit`       | boolean | no       | False   |                                                              |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite existing presentation if one exists.               |

<a id="subcommand-new-create-question"></a>

#### `calkit new|create question`

Add a new question.

Usage:

```text
calkit new|create question [OPTIONS] QUESTION
```

Arguments:

| Argument   | Type | Required | Default | Description |
| ---------- | ---- | -------- | ------- | ----------- |
| `question` | str  | yes      |         |             |

Options:

| Option     | Type    | Required | Default | Description |
| ---------- | ------- | -------- | ------- | ----------- |
| `--commit` | boolean | no       | False   |             |

<a id="subcommand-new-create-notebook-nb"></a>

#### `calkit new|create notebook|nb`

Add a new notebook.

Usage:

```text
calkit new|create notebook|nb [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description              |
| -------- | ---- | -------- | ------- | ------------------------ |
| `path`   | str  | yes      |         | Notebook path (relative) |

Options:

| Option          | Type    | Required | Default | Description                                         |
| --------------- | ------- | -------- | ------- | --------------------------------------------------- |
| `--title`       | str     | yes      |         |                                                     |
| `--description` | str     | no       |         |                                                     |
| `--stage`       | str     | no       |         | Name of the pipeline stage that runs this notebook. |
| `--commit`      | boolean | no       | False   |                                                     |

<a id="subcommand-new-create-docker-env"></a>

#### `calkit new|create docker-env`

Create a new Docker environment.

Usage:

```text
calkit new|create docker-env [OPTIONS]
```

Options:

| Option              | Type    | Required | Default | Description                                                                                                                                                                                            |
| ------------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--name`, `-n`      | str     | yes      |         | Environment name.                                                                                                                                                                                      |
| `--image`           | str     | no       |         | Image identifier. Should be unique and descriptive. Will default to environment name if not specified.                                                                                                 |
| `--from`            | str     | no       |         | Base image, e.g., 'ubuntu', if creating a Dockerfile.                                                                                                                                                  |
| `--path`            | str     | no       |         | Dockerfile path. Will default to 'Dockerfile' if --from is specified.                                                                                                                                  |
| `--add-layer`       | str     | no       |         | Add a layer (options: miniforge, foampy, uv, julia).                                                                                                                                                   |
| `--env-var`         | str     | no       |         | Environment variables to set in the container.                                                                                                                                                         |
| `--gpus`            | str     | no       |         |                                                                                                                                                                                                        |
| `--arg`             | str     | no       |         | Arguments to use when running container.                                                                                                                                                               |
| `--input`, `--dep`  | str     | no       |         | Path to a file that gets added to the container, so editing it rebuilds the image.                                                                                                                     |
| `--wdir`            | str     | no       | /work   | Working directory.                                                                                                                                                                                     |
| `--command-mode`    | str     | no       | shell   | How to execute commands in the container: 'shell' runs shell -c, 'entrypoint' passes args directly to the image entrypoint.                                                                            |
| `--user`            | str     | no       |         | User account to use to run the container.                                                                                                                                                              |
| `--platform`        | str     | no       |         | Platform to pull and run the image as, e.g., 'linux/amd64'.                                                                                                                                            |
| `--registry`        | str     | no       |         | Registry prefix to push built images to and pull them from instead of rebuilding, e.g., 'ghcr.io/someone/some-project', or 'ghcr.io' for the project's own namespace in the GitHub Container Registry. |
| `--platform-build`  | str     | no       |         | Platform to build the image for, as opposed to --platform, which is the one it's pulled and run as. Repeat for a multi-platform image, which requires a registry.                                      |
| `--port`            | str     | no       |         | Ports to expose in the container, e.g., '8080:80'. Can be specified multiple times.                                                                                                                    |
| `--description`     | str     | no       |         | Description.                                                                                                                                                                                           |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite any existing environment with this name.                                                                                                                                                     |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                                                                                                                                                                 |
| `--no-check`        | boolean | no       | False   | Do not check environment is up-to-date after creation.                                                                                                                                                 |

<a id="subcommand-new-create-foreach-stage"></a>

#### `calkit new|create foreach-stage`

Create a new DVC 'foreach' stage.

The list of values must be a simple list. For more complex objects, edit dvc.yaml directly.

Usage:

```text
calkit new|create foreach-stage [OPTIONS] VALS...
```

Arguments:

| Argument | Type | Required | Default | Description            |
| -------- | ---- | -------- | ------- | ---------------------- |
| `vals`   | str  | yes      |         | Values to iterate over |

Options:

| Option              | Type    | Required | Default | Description                                              |
| ------------------- | ------- | -------- | ------- | -------------------------------------------------------- |
| `--cmd`             | str     | yes      |         | Command to run. Can include {var} to fill with variable. |
| `--name`, `-n`      | str     | yes      |         | Stage name.                                              |
| `--dep`             | str     | no       |         | Path to add as a dependency.                             |
| `--out`             | str     | no       |         | Path to add as an output.                                |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite stage if one already exists.                   |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                   |

<a id="subcommand-new-create-dataset"></a>

#### `calkit new|create dataset`

Create a new dataset.

Usage:

```text
calkit new|create dataset [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `path`   | str  | yes      |         |             |

Options:

| Option                   | Type    | Required | Default | Description                                                                                                       |
| ------------------------ | ------- | -------- | ------- | ----------------------------------------------------------------------------------------------------------------- |
| `--title`                | str     | yes      |         |                                                                                                                   |
| `--description`          | str     | yes      |         |                                                                                                                   |
| `--stage`                | str     | no       |         | Name of the pipeline stage that generates this dataset.                                                           |
| `--cmd`                  | str     | no       |         | Command to add to the stage, if specified.                                                                        |
| `--dep`                  | str     | no       |         | Path to stage dependency.                                                                                         |
| `--out`                  | str     | no       |         | Path to stage output. Dataset path will be added automatically.                                                   |
| `--deps-from-stage-outs` | str     | no       |         | Stage name from which to add outputs as dependencies.                                                             |
| `--created-by-email`     | str     | no       |         | Email of whoever collected this data for the project, which marks it as primary rather than imported or computed. |
| `--created-by-orcid`     | str     | no       |         | ORCID of whoever collected this data.                                                                             |
| `--created-with-ai`      | str     | no       |         | Generative AI tool they used, e.g. 'Claude Opus 5'. Repeat for several.                                           |
| `--no-commit`            | boolean | no       | False   |                                                                                                                   |
| `--overwrite`, `-f`      | boolean | no       | False   | Overwrite existing dataset if one exists.                                                                         |

<a id="subcommand-new-create-publication-pub"></a>

#### `calkit new|create publication|pub`

Create a new publication.

Usage:

```text
calkit new|create publication|pub [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description                                                               |
| -------- | ---- | -------- | ------- | ------------------------------------------------------------------------- |
| `path`   | str  | yes      |         | Path for the publication. If using a template, this could be a directory. |

Options:

| Option                   | Type    | Required | Default | Description                                                                            |
| ------------------------ | ------- | -------- | ------- | -------------------------------------------------------------------------------------- |
| `--title`                | str     | yes      |         | The title of the publication.                                                          |
| `--kind`                 | str     | yes      |         | Kind of the publication, e.g., 'journal-article'.                                      |
| `--description`          | str     | no       |         | A description of the publication.                                                      |
| `--stage`                | str     | no       |         | Name of the pipeline stage to build the output file.                                   |
| `--dep`                  | str     | no       |         | Path to stage dependency.                                                              |
| `--deps-from-stage-outs` | str     | no       |         | Stage name from which to add outputs as dependencies.                                  |
| `--template`, `-t`       | str     | no       |         | Template with which to create the source files. Should be in the format {type}/{name}. |
| `--environment`          | str     | no       |         | Name of the build environment to create, if desired.                                   |
| `--no-commit`            | boolean | no       | False   | Do not commit resulting changes to the repo.                                           |
| `--overwrite`, `-f`      | boolean | no       | False   | Overwrite existing objects if they already exist.                                      |

<a id="subcommand-new-create-conda-env"></a>

#### `calkit new|create conda-env`

Create a new Conda environment.

Usage:

```text
calkit new|create conda-env [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | str  | no       |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default         | Description                                                                                                                                                                                     |
| ------------------- | ------- | -------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`      | str     | yes      |                 | Environment name.                                                                                                                                                                               |
| `--conda-name`      | str     | no       |                 | Name to use in the Conda environment file, if desired. Will be automatically generated if not provided. Note that these should be unique since Conda environments are a system-wide collection. |
| `--path`            | str     | no       | environment.yml | Environment YAML file path.                                                                                                                                                                     |
| `--pip`             | str     | no       |                 | Packages to install with pip.                                                                                                                                                                   |
| `--prefix`          | str     | no       |                 | Prefix for environment location.                                                                                                                                                                |
| `--description`     | str     | no       |                 | Description.                                                                                                                                                                                    |
| `--overwrite`, `-f` | boolean | no       | False           | Overwrite any existing environment with this name.                                                                                                                                              |
| `--no-commit`       | boolean | no       | False           | Do not commit changes.                                                                                                                                                                          |
| `--no-check`        | boolean | no       | False           | Do not check environment is up-to-date after creation.                                                                                                                                          |

<a id="subcommand-new-create-uv-env"></a>

#### `calkit new|create uv-env`

Create a new uv project environment.

Usage:

```text
calkit new|create uv-env [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | str  | no       |         | Packages to include in the environment. |

Options:

| Option           | Type    | Required | Default | Description                                            |
| ---------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--name`, `-n`   | str     | no       | main    | Environment name.                                      |
| `--path`         | str     | no       |         | Environment file path. Must end with 'pyproject.toml'. |
| `--python`, `-p` | str     | no       |         | Python version.                                        |
| `--no-check`     | boolean | no       | False   | Do not check environment is up-to-date after creation. |
| `--no-commit`    | boolean | no       | False   | Do not commit changes.                                 |

<a id="subcommand-new-create-slurm-env"></a>

#### `calkit new|create slurm-env`

Create a new SLURM environment.

Usage:

```text
calkit new|create slurm-env [OPTIONS]
```

Options:

| Option                  | Type    | Required | Default   | Description                                                                                                                                                                                                             |
| ----------------------- | ------- | -------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`          | str     | yes      |           | Environment name.                                                                                                                                                                                                       |
| `--host`                | str     | no       | localhost | Host where SLURM commands should run.                                                                                                                                                                                   |
| `--default-option`      | str     | no       |           | Default sbatch/srun option string (for example --gpus=1). Repeat for multiple options.                                                                                                                                  |
| `--default-setup`       | str     | no       |           | Default shell setup command to run before SLURM jobs (for example 'module load julia/1.11'). Repeat for multiple commands.                                                                                              |
| `--max-concurrent-jobs` | int     | no       |           | Maximum number of this project's jobs allowed in the queue at once, or 0 for no limit. Submissions beyond this wait for a slot, so an iterated stage does not take over a shared cluster's queue. Unlimited by default. |
| `--description`         | str     | no       |           | Description.                                                                                                                                                                                                            |
| `--overwrite`, `-f`     | boolean | no       | False     | Overwrite any existing environment with this name.                                                                                                                                                                      |
| `--no-commit`           | boolean | no       | False     | Do not commit changes.                                                                                                                                                                                                  |

<a id="subcommand-new-create-pbs-env"></a>

#### `calkit new|create pbs-env`

Create a new PBS environment.

Usage:

```text
calkit new|create pbs-env [OPTIONS]
```

Options:

| Option                  | Type    | Required | Default   | Description                                                                                                                                                                                                             |
| ----------------------- | ------- | -------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`          | str     | yes      |           | Environment name.                                                                                                                                                                                                       |
| `--host`                | str     | no       | localhost | Host where PBS commands should run.                                                                                                                                                                                     |
| `--default-option`      | str     | no       |           | Default qsub option string (for example --default-option=-l --default-option=walltime=01:00:00). Repeat for multiple options.                                                                                           |
| `--default-setup`       | str     | no       |           | Default shell setup command to run before PBS jobs (for example 'module load julia/1.11'). Repeat for multiple commands.                                                                                                |
| `--max-concurrent-jobs` | int     | no       |           | Maximum number of this project's jobs allowed in the queue at once, or 0 for no limit. Submissions beyond this wait for a slot, so an iterated stage does not take over a shared cluster's queue. Unlimited by default. |
| `--description`         | str     | no       |           | Description.                                                                                                                                                                                                            |
| `--overwrite`, `-f`     | boolean | no       | False     | Overwrite any existing environment with this name.                                                                                                                                                                      |
| `--no-commit`           | boolean | no       | False     | Do not commit changes.                                                                                                                                                                                                  |

<a id="subcommand-new-create-uv-venv"></a>

#### `calkit new|create uv-venv`

Create a new uv virtual environment.

Usage:

```text
calkit new|create uv-venv [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | str  | no       |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default          | Description                                                                                                  |
| ------------------- | ------- | -------- | ---------------- | ------------------------------------------------------------------------------------------------------------ |
| `--name`, `-n`      | str     | yes      |                  | Environment name.                                                                                            |
| `--path`            | str     | no       | requirements.txt | Path for requirements file.                                                                                  |
| `--prefix`          | str     | no       |                  | Prefix for environment location (defaults to .venv, or .calkit/envs/<name>/.venv if .venv is already taken). |
| `--python`, `-p`    | str     | no       |                  | Python version.                                                                                              |
| `--description`     | str     | no       |                  | Description.                                                                                                 |
| `--overwrite`, `-f` | boolean | no       | False            | Overwrite any existing environment with this name.                                                           |
| `--no-commit`       | boolean | no       | False            | Do not commit changes.                                                                                       |
| `--no-check`        | boolean | no       | False            | Do not check environment is up-to-date after creation.                                                       |

<a id="subcommand-new-create-venv"></a>

#### `calkit new|create venv`

Create a new Python virtual environment with venv.

Usage:

```text
calkit new|create venv [OPTIONS] PACKAGES...
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | str  | yes      |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default          | Description                                                                                                  |
| ------------------- | ------- | -------- | ---------------- | ------------------------------------------------------------------------------------------------------------ |
| `--name`, `-n`      | str     | yes      |                  | Environment name.                                                                                            |
| `--path`            | str     | no       | requirements.txt | Path for requirements file.                                                                                  |
| `--prefix`          | str     | no       |                  | Prefix for environment location (defaults to .venv, or .calkit/envs/<name>/.venv if .venv is already taken). |
| `--description`     | str     | no       |                  | Description.                                                                                                 |
| `--overwrite`, `-f` | boolean | no       | False            | Overwrite any existing environment with this name.                                                           |
| `--no-commit`       | boolean | no       | False            | Do not commit changes.                                                                                       |
| `--no-check`        | boolean | no       | False            | Do not check environment is up-to-date after creation.                                                       |

<a id="subcommand-new-create-pixi-env"></a>

#### `calkit new|create pixi-env`

Create a new pixi virtual environment.

Usage:

```text
calkit new|create pixi-env [OPTIONS] PACKAGES...
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | str  | yes      |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default | Description                                            |
| ------------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--name`, `-n`      | str     | yes      |         | Environment name.                                      |
| `--pip`             | str     | no       |         | Packages to install with pip.                          |
| `--description`     | str     | no       |         | Description.                                           |
| `--platform`, `-p`  | str     | no       |         | Platform.                                              |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite any existing environment with this name.     |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                 |
| `--no-check`        | boolean | no       | False   | Do not check environment is up-to-date after creation. |

<a id="subcommand-new-create-julia-env"></a>

#### `calkit new|create julia-env`

Create a new Julia environment or add an existing one to calkit.yaml.

Usage:

```text
calkit new|create julia-env [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                                      |
| ---------- | ---- | -------- | ------- | ------------------------------------------------ |
| `packages` | str  | no       |         | Optional packages to include in the environment. |

Options:

| Option              | Type    | Required | Default | Description                                            |
| ------------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--name`, `-n`      | str     | no       | main    | Environment name.                                      |
| `--path`            | str     | no       |         | Path for Project.toml file.                            |
| `--description`     | str     | no       |         | Description.                                           |
| `--julia`, `-j`     | str     | no       |         | Julia version. Auto-detected if not supplied.          |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite any existing environment with this name.     |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                 |
| `--no-check`        | boolean | no       | False   | Do not check environment is up-to-date after creation. |

<a id="subcommand-new-create-renv"></a>

#### `calkit new|create renv`

Create a new R environment with renv.

Usage:

```text
calkit new|create renv [OPTIONS] [PACKAGES...]
```

Arguments:

| Argument   | Type | Required | Default | Description                             |
| ---------- | ---- | -------- | ------- | --------------------------------------- |
| `packages` | str  | no       |         | Packages to include in the environment. |

Options:

| Option              | Type    | Required | Default | Description                                            |
| ------------------- | ------- | -------- | ------- | ------------------------------------------------------ |
| `--name`, `-n`      | str     | no       | main    | Environment name.                                      |
| `--path`            | str     | no       |         | Environment file path. Must end with 'DESCRIPTION'.    |
| `--r-version`, `-r` | str     | no       |         | R version.                                             |
| `--description`     | str     | no       |         | Description.                                           |
| `--overwrite`, `-f` | boolean | no       | False   | Overwrite any existing environment with this name.     |
| `--no-check`        | boolean | no       | False   | Do not check environment is up-to-date after creation. |
| `--no-commit`       | boolean | no       | False   | Do not commit changes.                                 |

<a id="subcommand-new-create-nix-env"></a>

#### `calkit new|create nix-env`

Create a new Nix flake-based environment.

Usage:

```text
calkit new|create nix-env [OPTIONS] PACKAGES...
```

Arguments:

| Argument   | Type | Required | Default | Description                                            |
| ---------- | ---- | -------- | ------- | ------------------------------------------------------ |
| `packages` | str  | yes      |         | Nixpkgs packages to include in the dev shell (e.g. R). |

Options:

| Option              | Type    | Required | Default                             | Description                                           |
| ------------------- | ------- | -------- | ----------------------------------- | ----------------------------------------------------- |
| `--name`, `-n`      | str     | yes      |                                     | Environment name.                                     |
| `--path`            | str     | no       |                                     | Flake file path. Must end with 'flake.nix'.           |
| `--nixpkgs-url`     | str     | no       | github:NixOS/nixpkgs/nixos-unstable | Flake input URL for nixpkgs.                          |
| `--description`     | str     | no       |                                     | Description.                                          |
| `--overwrite`, `-f` | boolean | no       | False                               | Overwrite any existing environment with this name.    |
| `--no-check`        | boolean | no       | False                               | Do not run 'nix flake lock' after creating the flake. |
| `--no-commit`       | boolean | no       | False                               | Do not commit changes.                                |

<a id="subcommand-new-create-status"></a>

#### `calkit new|create status`

Add a new project status to the log.

Usage:

```text
calkit new|create status [OPTIONS] STATUS
```

Arguments:

| Argument | Type                                    | Required | Default | Description                    |
| -------- | --------------------------------------- | -------- | ------- | ------------------------------ |
| `status` | choice(in-progress, on-hold, completed) | yes      |         | Current status of the project. |

Options:

| Option            | Type    | Required | Default | Description                              |
| ----------------- | ------- | -------- | ------- | ---------------------------------------- |
| `--message`, `-m` | str     | no       |         | Optional message describing the status.  |
| `--no-commit`     | boolean | no       | False   | Do not commit changes to the status log. |

<a id="subcommand-new-create-python-script-stage"></a>

#### `calkit new|create python-script-stage`

Add a stage to the pipeline that runs a Python script.

Usage:

```text
calkit new|create python-script-stage [OPTIONS]
```

Options:

| Option                         | Type      | Required | Default | Description                                                                                                    |
| ------------------------------ | --------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | str       | yes      |         | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | str       | yes      |         | Environment to use to run the stage.                                                                           |
| `--script-path`, `-s`          | str       | yes      |         | Path to script.                                                                                                |
| `--arg`                        | str       | no       |         | Argument to pass to the script.                                                                                |
| `--input`, `-i`                | str       | no       |         | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | str       | no       |         | A path that is produced by the stage.                                                                          |
| `--out-git`                    | str       | no       |         | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | str       | no       |         | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | str       | no       |         | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | str       | no       |         | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | str       | no       |         | An output that should not be stored in version control, and should not be deleted before running.              |
| `--iter`                       | <str str> | no       |         | Iterate over an argument with a comma-separated list, e.g., --iter-arg var_name val1,val2,val3.                |
| `--overwrite`, `--force`, `-f` | boolean   | no       | False   | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean   | no       | False   | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean   | no       | False   | Do not commit changes to Git.                                                                                  |

<a id="subcommand-new-create-julia-script-stage"></a>

#### `calkit new|create julia-script-stage`

Add a stage to the pipeline that runs a Julia script.

Usage:

```text
calkit new|create julia-script-stage [OPTIONS]
```

Options:

| Option                         | Type      | Required | Default | Description                                                                                                    |
| ------------------------------ | --------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | str       | yes      |         | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | str       | yes      |         | Environment to use to run the stage.                                                                           |
| `--script-path`, `-s`          | str       | yes      |         | Path to script.                                                                                                |
| `--input`, `-i`                | str       | no       |         | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | str       | no       |         | A path that is produced by the stage.                                                                          |
| `--out-git`                    | str       | no       |         | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | str       | no       |         | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | str       | no       |         | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | str       | no       |         | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | str       | no       |         | An output that should not be stored in version control, and should not be deleted before running.              |
| `--iter`                       | <str str> | no       |         | Iterate over an argument with a comma-separated list, e.g., --iter-arg var_name val1,val2,val3.                |
| `--overwrite`, `--force`, `-f` | boolean   | no       | False   | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean   | no       | False   | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean   | no       | False   | Do not commit changes to Git.                                                                                  |

<a id="subcommand-new-create-matlab-script-stage"></a>

#### `calkit new|create matlab-script-stage`

Add a stage to the pipeline that runs a MATLAB script.

Usage:

```text
calkit new|create matlab-script-stage [OPTIONS]
```

Options:

| Option                         | Type    | Required | Default | Description                                                                                                    |
| ------------------------------ | ------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | str     | yes      |         | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | str     | yes      |         | Environment to use to run the stage.                                                                           |
| `--script-path`, `-s`          | str     | yes      |         | Path to script.                                                                                                |
| `--input`, `-i`                | str     | no       |         | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | str     | no       |         | A path that is produced by the stage.                                                                          |
| `--out-git`                    | str     | no       |         | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | str     | no       |         | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | str     | no       |         | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | str     | no       |         | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | str     | no       |         | An output that should not be stored in version control, and should not be deleted before running.              |
| `--overwrite`, `--force`, `-f` | boolean | no       | False   | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean | no       | False   | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean | no       | False   | Do not commit changes to Git.                                                                                  |

<a id="subcommand-new-create-latex-stage"></a>

#### `calkit new|create latex-stage`

Add a stage to the pipeline that compiles a LaTeX document.

Usage:

```text
calkit new|create latex-stage [OPTIONS]
```

Options:

| Option                         | Type    | Required | Default | Description                                                                                                    |
| ------------------------------ | ------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | str     | yes      |         | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | str     | yes      |         | Environment to use to run the stage.                                                                           |
| `--target`                     | str     | yes      |         | Target .tex file path.                                                                                         |
| `--output-dir`                 | str     | no       |         | Directory for the compiled PDF (passed to latexmk as -outdir). Ignored when a latexmkrc is provided.           |
| `--aux-dir`                    | str     | no       |         | Directory for auxiliary files (passed to latexmk as -auxdir). Ignored when a latexmkrc is provided.            |
| `--latexmkrc`                  | str     | no       |         | Path to a latexmkrc file for compilation.                                                                      |
| `--latexmk-arg`                | str     | no       |         | Extra argument passed through to latexmk. Repeat the option to pass more than one.                             |
| `--input`, `-i`                | str     | no       |         | A path on which the stage depends.                                                                             |
| `--no-detect-inputs`           | boolean | no       | False   | Don't add the class, style, bibliography, and figure files the document reads as inputs.                       |
| `--output`, `-o`               | str     | no       |         | A path that is produced by the stage.                                                                          |
| `--out-git`                    | str     | no       |         | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | str     | no       |         | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | str     | no       |         | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | str     | no       |         | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | str     | no       |         | An output that should not be stored in version control, and should not be deleted before running.              |
| `--overwrite`, `--force`, `-f` | boolean | no       | False   | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean | no       | False   | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean | no       | False   | Do not commit changes to Git.                                                                                  |

<a id="subcommand-new-create-jupyter-notebook-stage"></a>

#### `calkit new|create jupyter-notebook-stage`

Add a stage to the pipeline that runs a Jupyter notebook.

Usage:

```text
calkit new|create jupyter-notebook-stage [OPTIONS]
```

Options:

| Option                         | Type                   | Required | Default | Description                                                                                                    |
| ------------------------------ | ---------------------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`                 | str                    | yes      |         | Stage name, typically kebab-case.                                                                              |
| `--environment`, `-e`          | str                    | yes      |         | Environment to use to run the stage.                                                                           |
| `--notebook-path`              | str                    | yes      |         | Path to notebook.                                                                                              |
| `--input`, `-i`                | str                    | no       |         | A path on which the stage depends.                                                                             |
| `--output`, `-o`               | str                    | no       |         | A path that is produced by the stage.                                                                          |
| `--out-git`                    | str                    | no       |         | An output that should be stored with Git instead of DVC.                                                       |
| `--out-git-no-delete`          | str                    | no       |         | An output that should be tracked with Git instead of DVC, and also should not be deleted before running stage. |
| `--out-no-delete`              | str                    | no       |         | An output that should not be deleted before running.                                                           |
| `--out-no-store`               | str                    | no       |         | An output that should not be stored in version control.                                                        |
| `--out-no-store-no-delete`     | str                    | no       |         | An output that should not be stored in version control, and should not be deleted before running.              |
| `--html-storage`               | choice(git, dvc, None) | no       | dvc     | In what system to store the HTML output of the notebook.                                                       |
| `--cleaned-ipynb-storage`      | choice(git, dvc, None) | no       | git     | In what system to store the cleaned ipynb output of the notebook.                                              |
| `--executed-ipynb-storage`     | choice(git, dvc, None) | no       | dvc     | In what system to store the executed ipynb output of the notebook.                                             |
| `--overwrite`, `--force`, `-f` | boolean                | no       | False   | Overwrite an existing stage with this name if necessary.                                                       |
| `--no-check`                   | boolean                | no       | False   | Do not check if the target, deps, environment, etc., exist.                                                    |
| `--no-commit`                  | boolean                | no       | False   | Do not commit changes to Git.                                                                                  |

<a id="subcommand-new-create-release"></a>

#### `calkit new|create release`

Create a new release.

Usage:

```text
calkit new|create release [OPTIONS] [PATH]
```

Arguments:

| Argument | Type | Required | Default | Description                                     |
| -------- | ---- | -------- | ------- | ----------------------------------------------- |
| `path`   | str  | no       | .       | The path to release; '.' for a project release. |

Options:

| Option                    | Type    | Required | Default | Description                                                                                                                                                                               |
| ------------------------- | ------- | -------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`            | str     | yes      |         | A name for the release, typically kebab-case or a semantic version. Will be used for the Git tag and GitHub release title.                                                                |
| `--kind`                  | str     | no       |         | What kind of release to create. Will attempt to infer from path if not provided.                                                                                                          |
| `--description`, `--desc` | str     | no       |         | A description of the release. Will be auto-generated if not provided.                                                                                                                     |
| `--date`                  | str     | no       |         | Release date. Will default to today.                                                                                                                                                      |
| `--no-docker-images`      | boolean | no       | False   | Do not archive the project's Docker images in the release.                                                                                                                                |
| `--dry-run`               | boolean | no       | False   | Only print actions that would be taken but don't take them.                                                                                                                               |
| `--no-commit`             | boolean | no       | False   | Do not commit changes to Git repo.                                                                                                                                                        |
| `--no-push`               | boolean | no       | False   | Do not push to Git remote.                                                                                                                                                                |
| `--internal`              | boolean | no       | False   | Create an internal release that is not published to an archival service. Still creates a Git tag and release record in calkit.yaml, but does not upload files or create a GitHub release. |
| `--no-github`             | boolean | no       | False   | Do not create a GitHub release.                                                                                                                                                           |
| `--to`                    | str     | no       | zenodo  | Archival service to use for external releases (zenodo or caltechdata); ignored for --internal releases.                                                                                   |
| `--draft`                 | boolean | no       | False   | Create draft record with reserved DOI but do not publish.                                                                                                                                 |
| `--license`               | str     | no       |         | License ID (from https://spdx.org/licenses). Multiple can be specified. Will try to infer from LICENSE file, if present.                                                                  |
| `--verbose`, `-v`         | boolean | no       | False   | Print verbose output.                                                                                                                                                                     |

<a id="command-group-delete-rm"></a>

### `calkit delete|rm`

Delete a Calkit object.

| Command                                      | Description                             |
| -------------------------------------------- | --------------------------------------- |
| [`question`](#subcommand-delete-rm-question) | Remove a question by its 1-based index. |

<a id="subcommand-delete-rm-question"></a>

#### `calkit delete|rm question`

Remove a question by its 1-based index.

Usage:

```text
calkit delete|rm question INDEX
```

Arguments:

| Argument | Type | Required | Default | Description                                                            |
| -------- | ---- | -------- | ------- | ---------------------------------------------------------------------- |
| `index`  | int  | yes      |         | 1-based index of the question to remove (see `calkit list questions`). |

<a id="command-group-notebooks-nb"></a>

### `calkit notebooks|nb`

Work with computational notebooks.

| Command                                                             | Description                                                         |
| ------------------------------------------------------------------- | ------------------------------------------------------------------- |
| [`clean`](#subcommand-notebooks-nb-clean)                           | Clean notebook and place a copy in the cleaned notebooks directory. |
| [`clean-all`](#subcommand-notebooks-nb-clean-all)                   | Clean all notebooks in the pipeline.                                |
| [`check-kernel`](#subcommand-notebooks-nb-check-kernel)             | Check that an environment has a registered Jupyter kernel.          |
| [`execute`](#subcommand-notebooks-nb-execute)                       | Execute notebook and place a copy in the relevant directory.        |
| [`export-marimo-wasm`](#subcommand-notebooks-nb-export-marimo-wasm) | Export a marimo notebook to a WebAssembly app.                      |

<a id="subcommand-notebooks-nb-clean"></a>

#### `calkit notebooks|nb clean`

Clean notebook and place a copy in the cleaned notebooks directory.

This can be useful to use as a preprocessing DVC stage to use a clean notebook as a dependency for a stage that caches and executed notebook.

Usage:

```text
calkit notebooks|nb clean [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `path`   | str  | yes      |         |             |

Options:

| Option          | Type    | Required | Default | Description          |
| --------------- | ------- | -------- | ------- | -------------------- |
| `--quiet`, `-q` | boolean | no       | False   | Do not print output. |

<a id="subcommand-notebooks-nb-clean-all"></a>

#### `calkit notebooks|nb clean-all`

Clean all notebooks in the pipeline.

Usage:

```text
calkit notebooks|nb clean-all [OPTIONS]
```

Options:

| Option          | Type    | Required | Default | Description          |
| --------------- | ------- | -------- | ------- | -------------------- |
| `--quiet`, `-q` | boolean | no       | False   | Do not print output. |

<a id="subcommand-notebooks-nb-check-kernel"></a>

#### `calkit notebooks|nb check-kernel`

Check that an environment has a registered Jupyter kernel.

Usage:

```text
calkit notebooks|nb check-kernel [OPTIONS]
```

Options:

| Option                         | Type    | Required | Default | Description                                                                              |
| ------------------------------ | ------- | -------- | ------- | ---------------------------------------------------------------------------------------- |
| `--environment`, `--env`, `-e` | str     | yes      |         | Environment name in which to run the notebook.                                           |
| `--no-check`                   | boolean | no       | False   | Do not check environment before executing.                                               |
| `--language`, `-l`             | str     | no       |         | Notebook language; if 'matlab', MATLAB kernel must be available in environment.          |
| `--verbose`, `-v`              | boolean | no       | False   | Print verbose output.                                                                    |
| `--json`                       | boolean | no       | False   | Output result as JSON.                                                                   |
| `--auto-add-deps`              | boolean | no       | False   | Automatically install missing kernel dependencies (e.g., IJulia for Julia environments). |

<a id="subcommand-notebooks-nb-execute"></a>

#### `calkit notebooks|nb execute`

Execute notebook and place a copy in the relevant directory.

This can be useful to use as a preprocessing DVC stage to use a clean notebook as a dependency for a stage that caches and executed notebook.

Usage:

```text
calkit notebooks|nb execute [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `path`   | str  | yes      |         |             |

Options:

| Option                  | Type    | Required | Default  | Description                                                                     |
| ----------------------- | ------- | -------- | -------- | ------------------------------------------------------------------------------- |
| `--environment`, `-e`   | str     | no       |          | Name or path to the spec of the environment in which to run the notebook.       |
| `--to`                  | str     | no       | notebook | Output format ('html' or 'notebook').                                           |
| `--no-check`            | boolean | no       | False    | Do not check environment before executing.                                      |
| `--param`, `-p`         | str     | no       |          | Parameter to pass to the notebook in key=value format.                          |
| `--params-json`, `-j`   | str     | no       |          | JSON string to parse as parameters to pass to the notebook.                     |
| `--params-base64`, `-b` | str     | no       |          | Base64-encoded JSON string to parse as parameters to pass to the notebook.      |
| `--language`, `-l`      | str     | no       |          | Notebook language; if 'matlab', MATLAB kernel must be available in environment. |
| `--no-replace`          | boolean | no       | False    | Do not replace notebook outputs from executed version.                          |
| `--verbose`, `-v`       | boolean | no       | False    | Print verbose output.                                                           |

<a id="subcommand-notebooks-nb-export-marimo-wasm"></a>

#### `calkit notebooks|nb export-marimo-wasm`

Export a marimo notebook to a WebAssembly app.

Usage:

```text
calkit notebooks|nb export-marimo-wasm [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description    |
| -------- | ---- | -------- | ------- | -------------- |
| `path`   | str  | yes      |         | Notebook path. |

Options:

| Option                | Type    | Required | Default | Description                                                                                                             |
| --------------------- | ------- | -------- | ------- | ----------------------------------------------------------------------------------------------------------------------- |
| `-o`, `--output`      | str     | yes      |         | Output path for the app.                                                                                                |
| `--environment`, `-e` | str     | no       |         | Name or path to the spec of the environment in which to export the notebook; must include marimo.                       |
| `--mode`              | str     | no       | run     | Whether the app is read-only ('run') or editable.                                                                       |
| `--show-code`         | boolean | no       | False   | Show notebook code in the app.                                                                                          |
| `--layout`            | str     | no       |         | Path to the layout file named in the notebook's marimo.App(layout_file=...) call.                                       |
| `--include`           | str     | no       |         | Path to publish with the app, copied beneath 'public' at its project-relative path. May be a glob, and may be repeated. |
| `--no-validate`       | boolean | no       | False   | Skip executing the notebook to check it works before exporting.                                                         |
| `--no-check`          | boolean | no       | False   | Do not check environment before exporting.                                                                              |
| `--verbose`, `-v`     | boolean | no       | False   | Print verbose output.                                                                                                   |

<a id="command-group-list-ls"></a>

### `calkit list|ls`

List Calkit objects.

| Command                                                         | Description                                                                                    |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| [`notebooks\|nb`](#subcommand-list-ls-notebooks-nb)             | List notebooks in the project.                                                                 |
| [`figures\|figs`](#subcommand-list-ls-figures-figs)             | List figures in the project.                                                                   |
| [`datasets`](#subcommand-list-ls-datasets)                      | List datasets in the project.                                                                  |
| [`results`](#subcommand-list-ls-results)                        | List results in the project.                                                                   |
| [`presentations\|pres`](#subcommand-list-ls-presentations-pres) | List presentations in the project.                                                             |
| [`questions`](#subcommand-list-ls-questions)                    | List the project's questions (1-indexed).                                                      |
| [`publications\|pubs`](#subcommand-list-ls-publications-pubs)   | List publications in the project.                                                              |
| [`misc`](#subcommand-list-ls-misc)                              | List misc artifacts in the project, i.e., attributed paths that aren't one of the typed kinds. |
| [`references\|refs`](#subcommand-list-ls-references-refs)       | List reference collections in the project.                                                     |
| [`environments\|envs`](#subcommand-list-ls-environments-envs)   | List environments in the project.                                                              |
| [`templates`](#subcommand-list-ls-templates)                    | List all available Calkit templates.                                                           |
| [`installers`](#subcommand-list-ls-installers)                  | List apps with a registered native installer.                                                  |
| [`procedures`](#subcommand-list-ls-procedures)                  | List procedures in the current project.                                                        |
| [`releases`](#subcommand-list-ls-releases)                      | List releases.                                                                                 |
| [`stages`](#subcommand-list-ls-stages)                          | List pipeline stages.                                                                          |
| [`remotes`](#subcommand-list-ls-remotes)                        | List Git and DVC remotes.                                                                      |
| [`imports`](#subcommand-list-ls-imports)                        | List everything in the project that was imported from elsewhere.                               |

<a id="subcommand-list-ls-notebooks-nb"></a>

#### `calkit list|ls notebooks|nb`

List notebooks in the project.

Usage:

```text
calkit list|ls notebooks|nb [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description            |
| -------- | ------- | -------- | ------- | ---------------------- |
| `--json` | boolean | no       | False   | Output result as JSON. |

<a id="subcommand-list-ls-figures-figs"></a>

#### `calkit list|ls figures|figs`

List figures in the project.

Usage:

```text
calkit list|ls figures|figs [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description                                                     |
| ----------------- | ------- | -------- | ------- | --------------------------------------------------------------- |
| `--json`          | boolean | no       | False   | Output result as JSON.                                          |
| `--declared-only` | boolean | no       | False   | Only list figures declared in calkit.yaml; skip auto-detection. |

<a id="subcommand-list-ls-datasets"></a>

#### `calkit list|ls datasets`

List datasets in the project.

Usage:

```text
calkit list|ls datasets [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description                                                      |
| ----------------- | ------- | -------- | ------- | ---------------------------------------------------------------- |
| `--json`          | boolean | no       | False   | Output result as JSON.                                           |
| `--declared-only` | boolean | no       | False   | Only list datasets declared in calkit.yaml; skip auto-detection. |

<a id="subcommand-list-ls-results"></a>

#### `calkit list|ls results`

List results in the project.

Usage:

```text
calkit list|ls results [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description                                                     |
| ----------------- | ------- | -------- | ------- | --------------------------------------------------------------- |
| `--json`          | boolean | no       | False   | Output result as JSON.                                          |
| `--declared-only` | boolean | no       | False   | Only list results declared in calkit.yaml; skip auto-detection. |

<a id="subcommand-list-ls-presentations-pres"></a>

#### `calkit list|ls presentations|pres`

List presentations in the project.

Usage:

```text
calkit list|ls presentations|pres [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description                                                           |
| ----------------- | ------- | -------- | ------- | --------------------------------------------------------------------- |
| `--json`          | boolean | no       | False   | Output result as JSON.                                                |
| `--declared-only` | boolean | no       | False   | Only list presentations declared in calkit.yaml; skip auto-detection. |

<a id="subcommand-list-ls-questions"></a>

#### `calkit list|ls questions`

List the project's questions (1-indexed).

Placeholders in the text, such as `{improvement:.1f}`, are filled from the question's value evidence, so numbers shown are read from the results files rather than retyped into `calkit.yaml`.

Usage:

```text
calkit list|ls questions [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description                                                                                    |
| -------- | ------- | -------- | ------- | ---------------------------------------------------------------------------------------------- |
| `--json` | boolean | no       | False   | Output result as JSON.                                                                         |
| `--raw`  | boolean | no       | False   | Show the text as written, with its {name} placeholders, instead of rendered from the evidence. |

<a id="subcommand-list-ls-publications-pubs"></a>

#### `calkit list|ls publications|pubs`

List publications in the project.

Usage:

```text
calkit list|ls publications|pubs [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description            |
| -------- | ------- | -------- | ------- | ---------------------- |
| `--json` | boolean | no       | False   | Output result as JSON. |

<a id="subcommand-list-ls-misc"></a>

#### `calkit list|ls misc`

List misc artifacts in the project, i.e., attributed paths that aren't one of the typed kinds.

Usage:

```text
calkit list|ls misc [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description            |
| -------- | ------- | -------- | ------- | ---------------------- |
| `--json` | boolean | no       | False   | Output result as JSON. |

<a id="subcommand-list-ls-references-refs"></a>

#### `calkit list|ls references|refs`

List reference collections in the project.

Usage:

```text
calkit list|ls references|refs [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description            |
| -------- | ------- | -------- | ------- | ---------------------- |
| `--json` | boolean | no       | False   | Output result as JSON. |

<a id="subcommand-list-ls-environments-envs"></a>

#### `calkit list|ls environments|envs`

List environments in the project.

Usage:

```text
calkit list|ls environments|envs [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description            |
| -------- | ------- | -------- | ------- | ---------------------- |
| `--json` | boolean | no       | False   | Output result as JSON. |

<a id="subcommand-list-ls-templates"></a>

#### `calkit list|ls templates`

List all available Calkit templates.

Usage:

```text
calkit list|ls templates [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description            |
| -------- | ------- | -------- | ------- | ---------------------- |
| `--json` | boolean | no       | False   | Output result as JSON. |

<a id="subcommand-list-ls-installers"></a>

#### `calkit list|ls installers`

List apps with a registered native installer.

These can be declared as `kind: app` dependencies in `calkit.yaml` and Calkit will offer to install them via `calkit install <name>` or automatically during `calkit run` on an interactive TTY.

Usage:

```text
calkit list|ls installers [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description            |
| -------- | ------- | -------- | ------- | ---------------------- |
| `--json` | boolean | no       | False   | Output result as JSON. |

<a id="subcommand-list-ls-procedures"></a>

#### `calkit list|ls procedures`

List procedures in the current project.

Usage:

```text
calkit list|ls procedures [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description            |
| -------- | ------- | -------- | ------- | ---------------------- |
| `--json` | boolean | no       | False   | Output result as JSON. |

<a id="subcommand-list-ls-releases"></a>

#### `calkit list|ls releases`

List releases.

Usage:

```text
calkit list|ls releases [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description            |
| -------- | ------- | -------- | ------- | ---------------------- |
| `--json` | boolean | no       | False   | Output result as JSON. |

<a id="subcommand-list-ls-stages"></a>

#### `calkit list|ls stages`

List pipeline stages.

Usage:

```text
calkit list|ls stages [OPTIONS]
```

Options:

| Option         | Type    | Required | Default | Description             |
| -------------- | ------- | -------- | ------- | ----------------------- |
| `--kind`, `-k` | str     | no       |         | Filter stages by kind.  |
| `--stale`      | boolean | no       | False   | Show only stale stages. |
| `--json`       | boolean | no       | False   | Output result as JSON.  |

<a id="subcommand-list-ls-remotes"></a>

#### `calkit list|ls remotes`

List Git and DVC remotes.

Usage:

```text
calkit list|ls remotes [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description            |
| -------- | ------- | -------- | ------- | ---------------------- |
| `--json` | boolean | no       | False   | Output result as JSON. |

<a id="subcommand-list-ls-imports"></a>

#### `calkit list|ls imports`

List everything in the project that was imported from elsewhere.

Walks every artifact kind, so an import shows up here whichever list it was recorded in. Entries are annotated with the kind they came from and a one-line description of the source, since where a file came from is the question being asked and it's spelled differently for a Git repo, a project, a URL, and a DOI.

What each import resolved to -- the commit, the checksum, when it was fetched -- is read from '.calkit/imports.json' and shown under 'locked', so both halves of the record are in one listing.

Usage:

```text
calkit list|ls imports [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description            |
| -------- | ------- | -------- | ------- | ---------------------- |
| `--json` | boolean | no       | False   | Output result as JSON. |

<a id="command-group-describe-desc"></a>

### `calkit describe|desc`

Describe things.

| Command                                                             | Description                                                        |
| ------------------------------------------------------------------- | ------------------------------------------------------------------ |
| [`system`](#subcommand-describe-desc-system)                        | Describe the system.                                               |
| [`environment\|env`](#subcommand-describe-desc-environment-env)     | Describe a single environment, including spec and lock file paths. |
| [`environments\|envs`](#subcommand-describe-desc-environments-envs) | Describe all environments, including spec and lock file paths.     |
| [`schema`](#subcommand-describe-desc-schema)                        | Print the JSON schema for calkit.yaml.                             |

<a id="subcommand-describe-desc-system"></a>

#### `calkit describe|desc system`

Describe the system.

Usage:

```text
calkit describe|desc system [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description            |
| -------- | ------- | -------- | ------- | ---------------------- |
| `--json` | boolean | no       | False   | Output result as JSON. |

<a id="subcommand-describe-desc-environment-env"></a>

#### `calkit describe|desc environment|env`

Describe a single environment, including spec and lock file paths.

Usage:

```text
calkit describe|desc environment|env [OPTIONS]
```

Options:

| Option         | Type    | Required | Default | Description            |
| -------------- | ------- | -------- | ------- | ---------------------- |
| `--name`, `-n` | str     | yes      |         | Environment name.      |
| `--json`       | boolean | no       | False   | Output result as JSON. |

<a id="subcommand-describe-desc-environments-envs"></a>

#### `calkit describe|desc environments|envs`

Describe all environments, including spec and lock file paths.

Usage:

```text
calkit describe|desc environments|envs [OPTIONS]
```

Options:

| Option   | Type    | Required | Default | Description            |
| -------- | ------- | -------- | ------- | ---------------------- |
| `--json` | boolean | no       | False   | Output result as JSON. |

<a id="subcommand-describe-desc-schema"></a>

#### `calkit describe|desc schema`

Print the JSON schema for calkit.yaml.

Editors can use this to validate and autocomplete the file. See https://docs.calkit.org/calkit-yaml for how to set that up.

Usage:

```text
calkit describe|desc schema [OPTIONS]
```

Options:

| Option           | Type | Required | Default | Description                                               |
| ---------------- | ---- | -------- | ------- | --------------------------------------------------------- |
| `--output`, `-o` | str  | no       |         | Path at which to write the schema instead of printing it. |

<a id="command-group-import"></a>

### `calkit import`

Import objects.

| Command                                         | Description                                                 |
| ----------------------------------------------- | ----------------------------------------------------------- |
| [`dataset`](#subcommand-import-dataset)         | Import a dataset.                                           |
| [`path`](#subcommand-import-path)               | Import a file from elsewhere, recording where it came from. |
| [`environment`](#subcommand-import-environment) | Import an environment from another project.                 |
| [`zenodo`](#subcommand-import-zenodo)           | Import files from a Zenodo record.                          |

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
| `src_path`  | str  | yes      |         | Location of dataset, including project owner and name, e.g., someone/some-project/data/some-data.csv |
| `dest_path` | str  | no       |         | Output path at which to save.                                                                        |

Options:

| Option              | Type    | Required | Default | Description                                                                     |
| ------------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------- |
| `--filter-paths`    | str     | no       |         | Filter paths in target dataset if it's a folder.                                |
| `--no-commit`       | boolean | no       | False   | Do not commit changes to repo.                                                  |
| `--no-dvc-pull`     | boolean | no       | False   | Do not pull imported dataset with DVC.                                          |
| `--overwrite`, `-f` | boolean | no       | False   | Force adding the dataset even if it already exists.                             |
| `--http`            | boolean | no       | False   | Use the legacy HTTP URL for the imported project's DVC remote instead of ck://. |

<a id="subcommand-import-path"></a>

#### `calkit import path`

Import a file from elsewhere, recording where it came from.

For a script or config maintained outside this project, e.g., a site setup script shared between projects. The copy is committed here, so the project stays self-contained and the pipeline can depend on it; the entry records the source so it can be refreshed with 'calkit sync import' and so the file isn't one whose origin nobody knows.

Usage:

```text
calkit import path [OPTIONS] SRC-PATH [DEST-PATH]
```

Arguments:

| Argument    | Type | Required | Default | Description                                                                                                                                                                                                                                              |
| ----------- | ---- | -------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src_path`  | str  | yes      |         | Where to get the file: a URL, including a GitHub or GitLab link to a file, an SSH clone URL like git@github.com:owner/repo/path, a DOI, a Calkit project path like someone/some-project/scripts/setup.sh, or a path inside the repo named by --git-repo. |
| `dest_path` | str  | no       |         | Path at which to save it in this project. Defaults to the path within the source project for a Calkit project source, and to the file's name for a Git repo, a URL, or anything else that has no project-relative path.                                  |

Options:

| Option              | Type    | Required | Default | Description                                                                                                                                                                                                                           |
| ------------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--kind`            | str     | no       | misc    | What kind of artifact this is: 'dataset', 'figure', 'publication', or 'misc' (default), which is where a path that isn't one of the typed artifacts belongs.                                                                          |
| `--git-repo`        | str     | no       |         | Clone URL of a Git repo to take the file from, for a repo that isn't a Calkit project.                                                                                                                                                |
| `--git-ref`         | str     | no       |         | Branch, tag, or commit to follow, recorded so 'calkit sync import' knows where to look next time, and overriding one read out of the URL. Needed for a URL whose branch name contains a slash. Defaults to the repo's default branch. |
| `--title`           | str     | no       |         | Title for the entry.                                                                                                                                                                                                                  |
| `--description`     | str     | no       |         | Description for the entry.                                                                                                                                                                                                            |
| `--overwrite`, `-f` | boolean | no       | False   | Replace an existing file or entry at this path.                                                                                                                                                                                       |
| `--no-commit`       | boolean | no       | False   | Do not commit changes to repo.                                                                                                                                                                                                        |

<a id="subcommand-import-environment"></a>

#### `calkit import environment`

Import an environment from another project.

Usage:

```text
calkit import environment [OPTIONS] SRC
```

Arguments:

| Argument | Type | Required | Default | Description                                                                                                         |
| -------- | ---- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------- |
| `src`    | str  | yes      |         | Environment location and name, e.g., someone/some-project:env-name. If not present, the Calkit API will be queried. |

Options:

| Option              | Type    | Required | Default | Description                                         |
| ------------------- | ------- | -------- | ------- | --------------------------------------------------- |
| `--path`            | str     | no       |         | Output path at which to save.                       |
| `--name`, `-n`      | str     | no       |         | Name to use in the destination project.             |
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
| `src`      | str  | yes      |         | Source URL or DOI.                                      |
| `dest_dir` | str  | yes      |         | Destination folder. Will be created if it doesn't exist |

Options:

| Option            | Type    | Required | Default | Description                                                                          |
| ----------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------ |
| `--kind`, `-k`    | str     | no       |         | What kind of artifact is being imported, e.g., a figure, dataset, publication.       |
| `--name-like`     | str     | no       |         | Filter for file names like this. Glob patterns accepted.                             |
| `--name-not-like` | str     | no       |         | Exclude names matching pattern.                                                      |
| `--storage`       | str     | no       |         | Storage backend to use (Git or DVC). If not specified, will be chosen based on size. |
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
| `input_fpath`  | str  | yes      |         | Input Excel file path.  |
| `output_fpath` | str  | yes      |         | Output image file path. |

Options:

| Option          | Type | Required | Default | Description        |
| --------------- | ---- | -------- | ------- | ------------------ |
| `--sheet`       | int  | no       | 1       | Sheet in workbook. |
| `--chart-index` | int  | no       | 0       | Chart index.       |

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
| `input_fpath` | str  | yes      |         | Input Word document file path. |

Options:

| Option           | Type | Required | Default | Description                                                                          |
| ---------------- | ---- | -------- | ------- | ------------------------------------------------------------------------------------ |
| `-o`, `--output` | str  | no       |         | Output file path. If not specified, will be the same as input with a .pdf extension. |

<a id="command-group-update"></a>

### `calkit update`

Update objects.

| Command                                               | Description                                                                          |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------ |
| [`devcontainer`](#subcommand-update-devcontainer)     | Update a project's devcontainer to match this version of Calkit's spec.              |
| [`license`](#subcommand-update-license)               | Update license with a reasonable default (MIT for code, CC-BY-4.0 for other files).  |
| [`release`](#subcommand-update-release)               | Update a release.                                                                    |
| [`vscode-config`](#subcommand-update-vscode-config)   | Update a project's VS Code config to match this version of Calkit's recommendations. |
| [`github-actions`](#subcommand-update-github-actions) | Update a project's GitHub Actions to match this version of Calkit's recommendations. |
| [`notebook`](#subcommand-update-notebook)             | Update notebook information.                                                         |
| [`agent-skills`](#subcommand-update-agent-skills)     | Copy packaged Calkit agent skills to `~/.agents/skills`.                             |
| [`uv-env`](#subcommand-update-uv-env)                 | Update a uv environment.                                                             |
| [`pixi-env`](#subcommand-update-pixi-env)             | Update a pixi environment.                                                           |
| [`julia-env`](#subcommand-update-julia-env)           | Update a Julia environment.                                                          |
| [`conda-env`](#subcommand-update-conda-env)           | Update a conda environment spec file.                                                |
| [`docker-env`](#subcommand-update-docker-env)         | Update a docker environment.                                                         |
| [`slurm-env`](#subcommand-update-slurm-env)           | Update a SLURM environment.                                                          |
| [`env`](#subcommand-update-env)                       | Update an environment.                                                               |
| [`environment`](#subcommand-update-environment)       | Update an environment.                                                               |
| [`stage`](#subcommand-update-stage)                   | Update a pipeline stage in calkit.yaml.                                              |
| [`figure`](#subcommand-update-figure)                 | Update a figure entry in calkit.yaml.                                                |
| [`dataset`](#subcommand-update-dataset)               | Update a dataset entry in calkit.yaml.                                               |

<a id="subcommand-update-devcontainer"></a>

#### `calkit update devcontainer`

Update a project's devcontainer to match this version of Calkit's spec.

Usage:

```text
calkit update devcontainer [OPTIONS]
```

Options:

| Option        | Type    | Required | Default | Description                                                       |
| ------------- | ------- | -------- | ------- | ----------------------------------------------------------------- |
| `--wdir`      | str     | no       |         | Working directory. By default will run current working directory. |
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
| `--copyright-holder`, `-c` | str     | yes      |         | Copyright holder, e.g., your full name.             |
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
| `--name`, `-n`   | str     | no       |         | Release name.                              |
| `--latest`       | boolean | no       | False   | Update latest release.                     |
| `--delete`       | boolean | no       | False   | Delete release.                            |
| `--publish`      | boolean | no       | False   | Publish the release.                       |
| `--reupload`     | boolean | no       | False   | Reupload files.                            |
| `--no-github`    | boolean | no       | False   | Do not create a release on GitHub.         |
| `--no-push-tags` | boolean | no       | False   | Do not push Git tags to remote repository. |

<a id="subcommand-update-vscode-config"></a>

#### `calkit update vscode-config`

Update a project's VS Code config to match this version of Calkit's recommendations.

Usage:

```text
calkit update vscode-config [OPTIONS]
```

Options:

| Option        | Type    | Required | Default | Description                                                       |
| ------------- | ------- | -------- | ------- | ----------------------------------------------------------------- |
| `--wdir`      | str     | no       |         | Working directory. By default will run current working directory. |
| `--no-commit` | boolean | no       | False   | Do not create a Git commit for the updated VS Code config.        |

<a id="subcommand-update-github-actions"></a>

#### `calkit update github-actions`

Update a project's GitHub Actions to match this version of Calkit's recommendations.

An existing workflow that runs the Calkit action is updated in place, pinning the action to this version of Calkit, so this is safe to rerun after upgrading.

Usage:

```text
calkit update github-actions [OPTIONS]
```

Options:

| Option        | Type    | Required | Default | Description                                                       |
| ------------- | ------- | -------- | ------- | ----------------------------------------------------------------- |
| `--wdir`      | str     | no       |         | Working directory. By default will run current working directory. |
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
| `notebook_path` | str  | yes      |         | Path to the notebook file (relative to workspace) |

Options:

| Option      | Type    | Required | Default | Description                                     |
| ----------- | ------- | -------- | ------- | ----------------------------------------------- |
| `--set-env` | str     | no       |         | Environment name to associate with the notebook |
| `--json`    | boolean | no       | False   | Output result as JSON.                          |

<a id="subcommand-update-agent-skills"></a>

#### `calkit update agent-skills`

Copy packaged Calkit agent skills to `~/.agents/skills`.

Usage:

```text
calkit update agent-skills [OPTIONS]
```

Options:

| Option          | Type    | Required | Default | Description                    |
| --------------- | ------- | -------- | ------- | ------------------------------ |
| `--quiet`, `-q` | boolean | no       | False   | Suppress non-essential output. |

<a id="subcommand-update-uv-env"></a>

#### `calkit update uv-env`

Update a uv environment.

Usage:

```text
calkit update uv-env [OPTIONS]
```

Options:

| Option             | Type    | Required | Default | Description                                             |
| ------------------ | ------- | -------- | ------- | ------------------------------------------------------- |
| `--name`, `-n`     | str     | yes      |         | Environment name.                                       |
| `--add`            | str     | no       |         | Add a package.                                          |
| `--remove`, `--rm` | str     | no       |         | Remove a package.                                       |
| `--no-check`       | boolean | no       | False   | Skip checking (syncing) the environment after updating. |

<a id="subcommand-update-pixi-env"></a>

#### `calkit update pixi-env`

Update a pixi environment.

Usage:

```text
calkit update pixi-env [OPTIONS]
```

Options:

| Option                     | Type    | Required | Default | Description                                             |
| -------------------------- | ------- | -------- | ------- | ------------------------------------------------------- |
| `--name`, `-n`             | str     | yes      |         | Environment name.                                       |
| `--add`                    | str     | no       |         | Add a conda package.                                    |
| `--remove`, `--rm`         | str     | no       |         | Remove a conda package.                                 |
| `--add-pip`                | str     | no       |         | Add a PyPI package.                                     |
| `--remove-pip`, `--rm-pip` | str     | no       |         | Remove a PyPI package.                                  |
| `--no-check`               | boolean | no       | False   | Skip checking (syncing) the environment after updating. |

<a id="subcommand-update-julia-env"></a>

#### `calkit update julia-env`

Update a Julia environment.

Usage:

```text
calkit update julia-env [OPTIONS]
```

Options:

| Option             | Type    | Required | Default | Description                                             |
| ------------------ | ------- | -------- | ------- | ------------------------------------------------------- |
| `--name`, `-n`     | str     | yes      |         | Environment name.                                       |
| `--add`            | str     | no       |         | Add a package.                                          |
| `--remove`, `--rm` | str     | no       |         | Remove a package.                                       |
| `--no-check`       | boolean | no       | False   | Skip checking (syncing) the environment after updating. |

<a id="subcommand-update-conda-env"></a>

#### `calkit update conda-env`

Update a conda environment spec file.

Usage:

```text
calkit update conda-env [OPTIONS]
```

Options:

| Option                     | Type    | Required | Default | Description                                             |
| -------------------------- | ------- | -------- | ------- | ------------------------------------------------------- |
| `--name`, `-n`             | str     | yes      |         | Environment name.                                       |
| `--add`                    | str     | no       |         | Add a conda package.                                    |
| `--remove`, `--rm`         | str     | no       |         | Remove a conda package.                                 |
| `--add-pip`                | str     | no       |         | Add a pip package.                                      |
| `--remove-pip`, `--rm-pip` | str     | no       |         | Remove a pip package.                                   |
| `--no-check`               | boolean | no       | False   | Skip checking (syncing) the environment after updating. |

<a id="subcommand-update-docker-env"></a>

#### `calkit update docker-env`

Update a docker environment.

Usage:

```text
calkit update docker-env [OPTIONS]
```

Options:

| Option         | Type    | Required | Default | Description                                                                                                                                                          |
| -------------- | ------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n` | str     | yes      |         | Environment name.                                                                                                                                                    |
| `--image`      | str     | no       |         | Docker image name/tag.                                                                                                                                               |
| `--registry`   | str     | no       |         | Registry prefix to push images to and pull them from, or 'ghcr.io' for the project's own namespace in the GitHub Container Registry, or 'none' to keep images local. |
| `--lock`       | boolean | no       | False   | Rebuild or repull the image and write fresh lock files for every architecture.                                                                                       |

<a id="subcommand-update-slurm-env"></a>

#### `calkit update slurm-env`

Update a SLURM environment.

Usage:

```text
calkit update slurm-env [OPTIONS]
```

Options:

| Option                  | Type | Required | Default | Description                                                                                   |
| ----------------------- | ---- | -------- | ------- | --------------------------------------------------------------------------------------------- |
| `--name`, `-n`          | str  | yes      |         | Environment name.                                                                             |
| `--host`                | str  | no       |         | SLURM host.                                                                                   |
| `--add-default-option`  | str  | no       |         | Add a default sbatch option.                                                                  |
| `--rm-default-option`   | str  | no       |         | Remove a default sbatch option.                                                               |
| `--set-default-options` | str  | no       |         | Replace default options list.                                                                 |
| `--add-default-setup`   | str  | no       |         | Add a default setup command.                                                                  |
| `--rm-default-setup`    | str  | no       |         | Remove a default setup command.                                                               |
| `--set-default-setup`   | str  | no       |         | Replace default setup list.                                                                   |
| `--max-concurrent-jobs` | int  | no       |         | Maximum number of this project's jobs allowed in the queue at once, or 0 to remove the limit. |

<a id="subcommand-update-env"></a>

#### `calkit update env`

Update an environment.

Currently supports adding packages to Julia and Nix (flake) envs.

Usage:

```text
calkit update env [OPTIONS]
```

Options:

| Option                   | Type | Required | Default | Description                                                               |
| ------------------------ | ---- | -------- | ------- | ------------------------------------------------------------------------- |
| `--name`, `-n`           | str  | yes      |         | Name of the environment to update                                         |
| `--add`, `--add-package` | str  | no       |         | Package to add to the environment. Repeat the flag for multiple packages. |

<a id="subcommand-update-environment"></a>

#### `calkit update environment`

Update an environment.

Currently supports adding packages to Julia and Nix (flake) envs.

Usage:

```text
calkit update environment [OPTIONS]
```

Options:

| Option                   | Type | Required | Default | Description                                                               |
| ------------------------ | ---- | -------- | ------- | ------------------------------------------------------------------------- |
| `--name`, `-n`           | str  | yes      |         | Name of the environment to update                                         |
| `--add`, `--add-package` | str  | no       |         | Package to add to the environment. Repeat the flag for multiple packages. |

<a id="subcommand-update-stage"></a>

#### `calkit update stage`

Update a pipeline stage in calkit.yaml.

Usage:

```text
calkit update stage [OPTIONS] NAME
```

Arguments:

| Argument | Type | Required | Default | Description |
| -------- | ---- | -------- | ------- | ----------- |
| `name`   | str  | yes      |         | Stage name. |

Options:

| Option                | Type | Required | Default | Description                                         |
| --------------------- | ---- | -------- | ------- | --------------------------------------------------- |
| `--environment`, `-e` | str  | no       |         | Set environment.                                    |
| `--add-input`         | str  | no       |         | Add an input path.                                  |
| `--rm-input`          | str  | no       |         | Remove an input path.                               |
| `--set-inputs`        | str  | no       |         | Replace the inputs list.                            |
| `--set-outputs`       | str  | no       |         | Replace DVC outputs list (paths only, storage=dvc). |
| `--set-outputs-git`   | str  | no       |         | Replace Git-tracked outputs list.                   |
| `--add-output`        | str  | no       |         | Add a DVC-tracked output path.                      |
| `--rm-output`         | str  | no       |         | Remove an output path.                              |

<a id="subcommand-update-figure"></a>

#### `calkit update figure`

Update a figure entry in calkit.yaml.

Usage:

```text
calkit update figure [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description              |
| -------- | ---- | -------- | ------- | ------------------------ |
| `path`   | str  | yes      |         | Path to the figure file. |

Options:

| Option                | Type | Required | Default | Description                                                                                                                                                                           |
| --------------------- | ---- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--imported-from`     | str  | no       |         | Where this came from, as a URL, a DOI, a Git clone URL, a Calkit project path, or, failing all of those, a description in words. Which one it is is worked out from how it's written. |
| `--imported-from-url` | str  | no       |         | URL the figure was imported from.                                                                                                                                                     |
| `--stage`             | str  | no       |         | Name of the pipeline stage that produces this figure.                                                                                                                                 |

<a id="subcommand-update-dataset"></a>

#### `calkit update dataset`

Update a dataset entry in calkit.yaml.

Usage:

```text
calkit update dataset [OPTIONS] PATH
```

Arguments:

| Argument | Type | Required | Default | Description               |
| -------- | ---- | -------- | ------- | ------------------------- |
| `path`   | str  | yes      |         | Path to the dataset file. |

Options:

| Option                     | Type     | Required | Default | Description                                                                                                                                                                           |
| -------------------------- | -------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--imported-from`          | str      | no       |         | Where this came from, as a URL, a DOI, a Git clone URL, a Calkit project path, or, failing all of those, a description in words. Which one it is is worked out from how it's written. |
| `--imported-from-url`      | str      | no       |         | URL the dataset was imported from.                                                                                                                                                    |
| `--imported-from-doi`      | str      | no       |         | DOI the dataset was imported from, e.g. 10.5281/zenodo.1.                                                                                                                             |
| `--imported-from-git-url`  | str      | no       |         | Clone URL of the Git repo the dataset was imported from.                                                                                                                              |
| `--imported-from-git-ref`  | str      | no       |         | Branch, tag, or commit to follow, e.g. 'main'. The commit it resolves to is recorded in .calkit/imports.json by 'calkit sync import', not here.                                       |
| `--imported-from-git-path` | str      | no       |         | Path within that repo, if it isn't the whole thing.                                                                                                                                   |
| `--imported-from-date`     | datetime | no       |         | Date it was downloaded, as YYYY-MM-DD.                                                                                                                                                |
| `--stage`                  | str      | no       |         | Name of the pipeline stage that produces this dataset.                                                                                                                                |

<a id="command-group-check"></a>

### `calkit check`

Check things.

| Command                                                     | Description                                                                                                  |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| [`repro`](#subcommand-check-repro)                          | Check the reproducibility of a project.                                                                      |
| [`environment`](#subcommand-check-environment)              | Check that an environment is up-to-date.                                                                     |
| [`julia-env`](#subcommand-check-julia-env)                  | Check a Julia environment and instantiate only when project, manifest, and package cache state have changed. |
| [`environments`](#subcommand-check-environments)            |                                                                                                              |
| [`envs`](#subcommand-check-envs)                            | Check that all environments are up-to-date.                                                                  |
| [`renv`](#subcommand-check-renv)                            | Check an renv R environment, initializing if needed.                                                         |
| [`docker-env`](#subcommand-check-docker-env)                | Check that Docker environment is up-to-date.                                                                 |
| [`conda-env`](#subcommand-check-conda-env)                  | Check a conda environment and rebuild if necessary.                                                          |
| [`venv`](#subcommand-check-venv)                            | Check a Python virtual environment (uv or virtualenv).                                                       |
| [`matlab-env`](#subcommand-check-matlab-env)                | Check a MATLAB environment matches its spec and export a JSON lock file.                                     |
| [`reqs\|requirements`](#subcommand-check-reqs-requirements) | Check that a project's system-level requirements are met.                                                    |
| [`env-vars`](#subcommand-check-env-vars)                    | Check that the project's required environmental variables exist.                                             |
| [`pipeline`](#subcommand-check-pipeline)                    | Check that the project pipeline is defined correctly.                                                        |
| [`call`](#subcommand-check-call)                            | Check that a command succeeds and run an alternate if not.                                                   |
| [`questions`](#subcommand-check-questions)                  | Check that answered questions are consistent with their evidence.                                            |

<a id="subcommand-check-repro"></a>

#### `calkit check repro`

Check the reproducibility of a project.

Reports one line per check. Where a line counts something, ask for that category to see what it counted, e.g., 'calkit check repro -c retyped' for values in a manuscript the pipeline already computes.

Exits with an error when the project types out a value its own pipeline computes, which is a defect rather than a matter of taste. Everything else here is advice and does not affect the exit code.

Usage:

```text
calkit check repro [OPTIONS]
```

Options:

| Option             | Type    | Required | Default | Description                                                                                        |
| ------------------ | ------- | -------- | ------- | -------------------------------------------------------------------------------------------------- |
| `--wdir`           | str     | no       | .       | Project working directory.                                                                         |
| `--category`, `-c` | str     | no       |         | Show the findings behind one summary line instead of the summary. Can be specified multiple times. |
| `--json`           | boolean | no       | False   | Output result as JSON.                                                                             |

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
| `--name`, `-n` | str     | yes      |         | Name of the environment to check. |
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
| `env_path` | str  | no       | Project.toml | Path to Julia Project.toml file. |

Options:

| Option      | Type    | Required | Default | Description                            |
| ----------- | ------- | -------- | ------- | -------------------------------------- |
| `--julia`   | str     | no       |         | Julia version to enforce (e.g., 1.11). |
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
| `env_path` | str  | yes      |         | Path to DESCRIPTION file or renv environment directory. |

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
| `tag`    | str  | yes      |         | Image tag.  |

Options:

| Option             | Type    | Required | Default | Description                                                                                                                                                       |
| ------------------ | ------- | -------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-i`, `--input`    | str     | no       |         | Path to input Dockerfile, if applicable.                                                                                                                          |
| `--output`, `-o`   | str     | no       |         | Path to which existing environment should be exported. If not specified, will have the same filename with '-lock' appended to it, keeping the same extension.     |
| `--input`          | str     | no       |         | Alternative lock file input paths to read.                                                                                                                        |
| `--input-delete`   | str     | no       |         | Alternative lock input file paths to read and remove (i.e., legacy paths).                                                                                        |
| `--platform`       | str     | no       |         | Platform to pull and run the image as, e.g., 'linux/amd64'. Also used when building, unless --platform-build says otherwise.                                      |
| `--user`           | str     | no       |         | Which user to run the container as.                                                                                                                               |
| `--wdir`           | str     | no       |         | Working directory inside the container.                                                                                                                           |
| `--dep`, `-d`      | str     | no       |         | Declare an explicit dependency for this Docker image.                                                                                                             |
| `--env-var`, `-e`  | str     | no       |         | Declare an explicit environment variable for the container.                                                                                                       |
| `--port`, `-p`     | str     | no       |         | Declare an explicit port for the container.                                                                                                                       |
| `--gpus`, `-g`     | str     | no       |         | Declare an explicit GPU requirement for the container.                                                                                                            |
| `--arg`, `-a`      | str     | no       |         | Declare an explicit run argument for the container.                                                                                                               |
| `--platform-build` | str     | no       |         | Platform to build the image for, as opposed to --platform, which is the one it's pulled and run as. Repeat for a multi-platform image, which requires a registry. |
| `--registry`       | str     | no       |         | Registry prefix to push built images to and pull them from, e.g., 'ghcr.io/someone/some-project', or 'none' to disable.                                           |
| `--lock-arch`      | str     | no       |         | Architecture to write an additional lock file for, alongside this machine's, e.g., 'amd64'.                                                                       |
| `--quiet`, `-q`    | boolean | no       | False   | Be quiet.                                                                                                                                                         |

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
| `--file`, `-f`   | str     | no       | environment.yml | Path to conda environment YAML file.                                                                                                                          |
| `--output`, `-o` | str     | no       |                 | Path to which existing environment should be exported. If not specified, will have the same filename with '-lock' appended to it, keeping the same extension. |
| `--input`        | str     | no       |                 | Alternative lock file input paths.                                                                                                                            |
| `--input-delete` | str     | no       |                 | Alternative lock file input paths to delete after use.                                                                                                        |
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
| `path`   | str  | no       | requirements.txt | Path to requirements file. |

Options:

| Option           | Type    | Required | Default | Description                                                                                                                                                   |
| ---------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--prefix`       | str     | no       | .venv   | Prefix.                                                                                                                                                       |
| `--output`, `-o` | str     | no       |         | Path to which existing environment should be exported. If not specified, will have the same filename with '-lock' appended to it, keeping the same extension. |
| `--input`        | str     | no       |         | Alternative lock file input paths.                                                                                                                            |
| `--input-delete` | str     | no       |         | Alternative lock file input paths to delete after use.                                                                                                        |
| `--wdir`         | str     | no       |         | Working directory. Defaults to current working directory.                                                                                                     |
| `--uv`           | boolean | no       | True    | Use uv.                                                                                                                                                       |
| `--python`       | str     | no       |         | Python version to specify if using uv.                                                                                                                        |
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
| `--name`, `-n`   | str  | yes      |         | Environment name in calkit.yaml. |
| `--output`, `-o` | str  | yes      |         |                                  |

<a id="subcommand-check-reqs-requirements"></a>

#### `calkit check reqs|requirements`

Check that a project's system-level requirements are met.

Usage:

```text
calkit check reqs|requirements [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description                                                                                             |
| ----------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------------------------- |
| `--verbose`, `-v` | boolean | no       | False   | Print verbose output                                                                                    |
| `--no-cache`      | boolean | no       | False   | Re-probe every setup requirement, ignoring (and clearing) the cache at .calkit/local/dep-checks.sqlite. |

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
| `cmd`    | str  | yes      |         | Command to check. |

Options:

| Option       | Type | Required | Default | Description                          |
| ------------ | ---- | -------- | ------- | ------------------------------------ |
| `--if-error` | str  | yes      |         | Command to run if there is an error. |

<a id="subcommand-check-questions"></a>

#### `calkit check questions`

Check that answered questions are consistent with their evidence.

A question is stale if any of its evidence changed after the commit that last edited the question, in Git history for Git-tracked outputs or in dvc.lock for DVC-tracked ones. Evidence paths must exist, value keys must resolve, every placeholder in the text must render, and a publication label must still be present in the LaTeX source. Exits with an error if any answered question is stale or broken.

Usage:

```text
calkit check questions [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description                                                                         |
| ----------------- | ------- | -------- | ------- | ----------------------------------------------------------------------------------- |
| `--wdir`          | str     | no       | .       | Project working directory.                                                          |
| `--verbose`, `-v` | boolean | no       | False   | List every answered question and its evidence, not only the ones needing attention. |
| `--json`          | boolean | no       | False   | Output the report as JSON.                                                          |

<a id="command-group-latex-tex"></a>

### `calkit latex|tex`

Work with LaTeX.

| Command                                        | Description                                           |
| ---------------------------------------------- | ----------------------------------------------------- |
| [`from-json`](#subcommand-latex-tex-from-json) | Convert a JSON file to LaTeX.                         |
| [`build`](#subcommand-latex-tex-build)         | Build a PDF of a LaTeX document with latexmk.         |
| [`diff`](#subcommand-latex-tex-diff)           | Build a PDF showing what changed in a LaTeX document. |

<a id="subcommand-latex-tex-from-json"></a>

#### `calkit latex|tex from-json`

Convert a JSON file to LaTeX.

This is useful for referencing calculated values in LaTeX documents.

Usage:

```text
calkit latex|tex from-json [OPTIONS] INPUT-FPATHS...
```

Arguments:

| Argument       | Type | Required | Default | Description              |
| -------------- | ---- | -------- | ------- | ------------------------ |
| `input_fpaths` | str  | yes      |         | Input JSON file path(s). |

Options:

| Option           | Type | Required | Default | Description                                                                                                                     |
| ---------------- | ---- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `--output`, `-o` | str  | yes      |         | Output LaTeX file path(s).                                                                                                      |
| `--command`      | str  | no       |         | Command name to use in LaTeX output.                                                                                            |
| `--key`          | str  | no       |         | Key to expose, dotted to reach into nested output, e.g., 'cases.a.cp'. Repeatable. Without any, every top-level key is exposed. |
| `--format-json`  | str  | no       |         | Additional JSON input to use for formatting. Can be used to add extra keys with simple expressions, etc.                        |

<a id="subcommand-latex-tex-build"></a>

#### `calkit latex|tex build`

Build a PDF of a LaTeX document with latexmk.

If a Calkit environment is not specified, latexmk will be run in the system environment if available. If not available, a TeX Live Docker container will be used.

Usage:

```text
calkit latex|tex build [OPTIONS] TEX-FILE
```

Arguments:

| Argument   | Type | Required | Default | Description               |
| ---------- | ---- | -------- | ------- | ------------------------- |
| `tex_file` | str  | yes      |         | The .tex file to compile. |

Options:

| Option               | Type    | Required | Default | Description                                                                                      |
| -------------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------------------ |
| `--env`, `-e`        | str     | no       |         | Environment in which to run latexmk, if applicable.                                              |
| `--no-check`         | boolean | no       | False   | Don't check the environment is valid before running latexmk.                                     |
| `--latexmk-rc`, `-r` | str     | no       |         | Path to a latexmkrc file to use for compilation.                                                 |
| `--output-dir`       | str     | no       |         | Directory for the compiled PDF, relative to the current directory. Passed to latexmk as -outdir. |
| `--aux-dir`          | str     | no       |         | Directory for auxiliary files, relative to the current directory. Passed to latexmk as -auxdir.  |
| `--latexmk-arg`      | str     | no       |         | Extra argument to pass through to latexmk. Repeat the option to pass more than one.              |
| `--no-synctex`       | boolean | no       | False   | Don't generate synctex file for source-to-pdf mapping.                                           |
| `--force`, `-f`      | boolean | no       | False   | Force latexmk to recompile all files, even if they are up to date.                               |
| `--verbose`, `-v`    | boolean | no       | False   | Print verbose output.                                                                            |

<a id="subcommand-latex-tex-diff"></a>

#### `calkit latex|tex diff`

Build a PDF showing what changed in a LaTeX document.

Two revisions that turn out to be the same is a result rather than an error: the marked-up document comes out unmarked, which is what "this branch hasn't changed the paper" looks like. A pipeline shouldn't fail depending on which branch it runs from.

Marks up one revision of a document against another with latexdiff, so additions and deletions are visible where they happen rather than as a list of files that changed. A `.dvc` pointer in a pull request says a paper was rebuilt; this says what it now reads.

With the default `--to`, the newer side is the working tree, so the marked-up document is built with the current figures and bibliography and what's marked is what changed in the text.

Usage:

```text
calkit latex|tex diff [OPTIONS] TEX-FILE
```

Arguments:

| Argument   | Type | Required | Default | Description               |
| ---------- | ---- | -------- | ------- | ------------------------- |
| `tex_file` | str  | yes      |         | The .tex file to compare. |

Options:

| Option            | Type    | Required | Default | Description                                                                                                                                                                                      |
| ----------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--from`          | str     | no       |         | Older revision, whose removed text is struck through. Defaults to the merge base with the default branch.                                                                                        |
| `--to`            | str     | no       |         | Newer revision, whose additions are marked. Defaults to the working tree.                                                                                                                        |
| `--env`, `-e`     | str     | no       |         | Environment in which to run latexdiff and latexmk.                                                                                                                                               |
| `--output`, `-o`  | str     | no       |         | Where to write the diff PDF. Defaults to a path under .calkit/latex-diffs, keeping it with the project's other derived files.                                                                    |
| `--output-dir`    | str     | no       |         | Directory to write the diff into, keeping the document's own path inside it. Lets a pipeline name the location after the revisions as written while passing resolved commits to --from and --to. |
| `--force`, `-f`   | boolean | no       | False   | Rebuild even if this comparison can't have changed and has already been built.                                                                                                                   |
| `--keep-tex`      | boolean | no       | False   | Keep the generated diff .tex file for inspection.                                                                                                                                                |
| `--no-check`      | boolean | no       | False   | Don't check the environment is valid before running.                                                                                                                                             |
| `--verbose`, `-v` | boolean | no       | False   | Print verbose output.                                                                                                                                                                            |

<a id="command-group-overleaf-ol"></a>

### `calkit overleaf|ol`

Interact with Overleaf.

| Command                                           | Description                                                    |
| ------------------------------------------------- | -------------------------------------------------------------- |
| [`import`](#subcommand-overleaf-ol-import)        | Import a publication from an Overleaf project.                 |
| [`sync`](#subcommand-overleaf-ol-sync)            | Sync folders with Overleaf.                                    |
| [`status\|st`](#subcommand-overleaf-ol-status-st) | Check the status of folders synced with Overleaf in a project. |
| [`push`](#subcommand-overleaf-ol-push)            | Get the project's latest figures and text onto Overleaf.       |
| [`pull`](#subcommand-overleaf-ol-pull)            | Bring collaborators' Overleaf writing back into the project.   |

<a id="subcommand-overleaf-ol-import"></a>

#### `calkit overleaf|ol import`

Import a publication from an Overleaf project.

Usage:

```text
calkit overleaf|ol import [OPTIONS] SRC-URL DEST-DIR
```

Arguments:

| Argument   | Type | Required | Default | Description                                                                    |
| ---------- | ---- | -------- | ------- | ------------------------------------------------------------------------------ |
| `src_url`  | str  | yes      |         | Overleaf project URL, e.g., https://www.overleaf.com/project/6800005973cb2e35. |
| `dest_dir` | str  | yes      |         | Directory at which to save in the project, e.g., 'paper'.                      |

Options:

| Option                | Type    | Required | Default | Description                                                                                                                |
| --------------------- | ------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------------------- |
| `--title`, `-t`       | str     | no       |         | Title of the publication.                                                                                                  |
| `--target`, `-T`      | str     | no       |         | Target TeX file path inside Overleaf project.                                                                              |
| `--description`, `-d` | str     | no       |         | Description of the publication.                                                                                            |
| `--kind`              | str     | no       |         | What of the publication this is, e.g., 'journal-article'.                                                                  |
| `--push-path`, `-p`   | str     | no       |         | Paths to push to the Overleaf project, e.g., 'figures'. Note that these are relative to the publication working directory. |
| `--no-commit`         | boolean | no       | False   | Do not commit changes to repo.                                                                                             |
| `--overwrite`, `-f`   | boolean | no       | False   | Force adding the publication even if it already exists.                                                                    |
| `--push-only`, `-P`   | boolean | no       | False   | Push local files to Overleaf without pulling. Useful when initializing a new Overleaf project from local files.            |

<a id="subcommand-overleaf-ol-sync"></a>

#### `calkit overleaf|ol sync`

Sync folders with Overleaf.

Usage:

```text
calkit overleaf|ol sync [OPTIONS] [PATHS...]
```

Arguments:

| Argument | Type | Required | Default | Description                                                                                                      |
| -------- | ---- | -------- | ------- | ---------------------------------------------------------------------------------------------------------------- |
| `paths`  | str  | no       |         | Paths to sync with Overleaf, e.g., 'paper/paper.pdf'. If not provided, all Overleaf publications will be synced. |

Options:

| Option                | Type    | Required | Default | Description                                                                                                                                                                                                                              |
| --------------------- | ------- | -------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--no-commit`         | boolean | no       | False   | Do not create a commit in the project repo for this sync. Changes pulled from Overleaf are still applied, but are left staged so you can review or commit them yourself. Changes are always committed and pushed to Overleaf regardless. |
| `--auto-commit`, `-a` | boolean | no       | False   | Automatically commit changes to the project repo if a synced folder has changes.                                                                                                                                                         |
| `--no-push`           | boolean | no       | False   | Do not push the changes to the main project remote. Changes will always be pushed to Overleaf.                                                                                                                                           |
| `--verbose`           | boolean | no       | False   | Enable verbose output.                                                                                                                                                                                                                   |
| `--resolve`, `-r`     | boolean | no       | False   | Mark merge conflicts as resolved before committing.                                                                                                                                                                                      |
| `--push-only`, `-P`   | boolean | no       | False   | Only push local files to Overleaf without pulling from Overleaf. Useful when initializing a new Overleaf project from local files.                                                                                                       |
| `--allow-stale`       | boolean | no       | False   | Sync even if the pipeline is out-of-date, which can send stale figures or results to Overleaf.                                                                                                                                           |
| `--any-branch`        | boolean | no       | False   | Sync even if the current branch is missing commits from the default branch.                                                                                                                                                              |
| `--force`, `-f`       | boolean | no       | False   | Overwrite changes made on Overleaf to push-only paths, which the project is meant to be the source of truth for.                                                                                                                         |

<a id="subcommand-overleaf-ol-status-st"></a>

#### `calkit overleaf|ol status|st`

Check the status of folders synced with Overleaf in a project.

Usage:

```text
calkit overleaf|ol status|st [PATHS...]
```

Arguments:

| Argument | Type | Required | Default | Description                                                                                     |
| -------- | ---- | -------- | ------- | ----------------------------------------------------------------------------------------------- |
| `paths`  | str  | no       |         | Paths synced with Overleaf, e.g., 'paper'. If not provided, all Overleaf syncs will be checked. |

<a id="subcommand-overleaf-ol-push"></a>

#### `calkit overleaf|ol push`

Get the project's latest figures and text onto Overleaf.

Pulls the latest data, ensures the pipeline is up-to-date, then pushes to Overleaf without pulling anything back, so collaborators see current results before they write against them.

Usage:

```text
calkit overleaf|ol push [OPTIONS] [PATHS...]
```

Arguments:

| Argument | Type | Required | Default | Description                                                                                          |
| -------- | ---- | -------- | ------- | ---------------------------------------------------------------------------------------------------- |
| `paths`  | str  | no       |         | Paths to push to Overleaf, e.g., 'paper'. If not provided, all Overleaf publications will be pushed. |

Options:

| Option           | Type    | Required | Default | Description                                                                                                      |
| ---------------- | ------- | -------- | ------- | ---------------------------------------------------------------------------------------------------------------- |
| `--branch`, `-b` | str     | no       |         | Switch to (or create) this branch before pushing.                                                                |
| `--yes`, `-y`    | boolean | no       | False   | Answer yes to all prompts, e.g., to run non-interactively.                                                       |
| `--no-pull`      | boolean | no       | False   | Do not pull from Git and DVC beforehand.                                                                         |
| `--allow-stale`  | boolean | no       | False   | Push even if the pipeline is out-of-date.                                                                        |
| `--any-branch`   | boolean | no       | False   | Push even if the current branch is missing commits from the default branch.                                      |
| `--force`, `-f`  | boolean | no       | False   | Overwrite changes made on Overleaf to push-only paths, which the project is meant to be the source of truth for. |
| `--verbose`      | boolean | no       | False   | Enable verbose output.                                                                                           |

<a id="subcommand-overleaf-ol-pull"></a>

#### `calkit overleaf|ol pull`

Bring collaborators' Overleaf writing back into the project.

Syncs in both directions, since Overleaf needs current figures to be worth writing against, then rebuilds the document from whatever came back and saves it.

Usage:

```text
calkit overleaf|ol pull [OPTIONS] [PATHS...]
```

Arguments:

| Argument | Type | Required | Default | Description                                                                                            |
| -------- | ---- | -------- | ------- | ------------------------------------------------------------------------------------------------------ |
| `paths`  | str  | no       |         | Paths to pull from Overleaf, e.g., 'paper'. If not provided, all Overleaf publications will be pulled. |

Options:

| Option           | Type    | Required | Default | Description                                                                                                                                 |
| ---------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `--branch`, `-b` | str     | no       |         | Switch to (or create) this branch before pulling. Useful when the default branch is protected, since pulling from Overleaf creates commits. |
| `--yes`, `-y`    | boolean | no       | False   | Answer yes to all prompts, e.g., to run non-interactively.                                                                                  |
| `--no-pull`      | boolean | no       | False   | Do not pull from Git and DVC beforehand.                                                                                                    |
| `--no-run`       | boolean | no       | False   | Do not run the pipeline after pulling.                                                                                                      |
| `--allow-stale`  | boolean | no       | False   | Pull even if the pipeline is out-of-date.                                                                                                   |
| `--any-branch`   | boolean | no       | False   | Pull even if the current branch is missing commits from the default branch.                                                                 |
| `--force`, `-f`  | boolean | no       | False   | Overwrite changes made on Overleaf to push-only paths, which the project is meant to be the source of truth for.                            |
| `--verbose`      | boolean | no       | False   | Enable verbose output.                                                                                                                      |

<a id="command-group-hub-cloud"></a>

### `calkit hub|cloud`

Interact with a Calkit hub.

| Command                                  | Description                             |
| ---------------------------------------- | --------------------------------------- |
| [`get`](#subcommand-hub-cloud-get)       | Get a resource from the hub API.        |
| [`login`](#subcommand-hub-cloud-login)   | Log in to a Calkit hub.                 |
| [`config`](#subcommand-hub-cloud-config) | Work with per-hub credentials (tokens). |

<a id="subcommand-hub-cloud-get"></a>

#### `calkit hub|cloud get`

Get a resource from the hub API.

Usage:

```text
calkit hub|cloud get [OPTIONS] ENDPOINT
```

Arguments:

| Argument   | Type | Required | Default | Description  |
| ---------- | ---- | -------- | ------- | ------------ |
| `endpoint` | str  | yes      |         | API endpoint |

Options:

| Option  | Type | Required | Default | Description                                                                                                                              |
| ------- | ---- | -------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `--hub` | str  | no       |         | URL of the hub to target, e.g., https://staging.calkit.io. Defaults to the working directory project's hub, if declared, else calkit.io. |

<a id="subcommand-hub-cloud-login"></a>

#### `calkit hub|cloud login`

Log in to a Calkit hub.

First try a GET request to the /user endpoint to check if the user is already logged in. If not, perform OAuth device flow.

Usage:

```text
calkit hub|cloud login [OPTIONS]
```

Options:

| Option          | Type    | Required | Default | Description                                                                                                                              |
| --------------- | ------- | -------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `--hub`         | str     | no       |         | URL of the hub to target, e.g., https://staging.calkit.io. Defaults to the working directory project's hub, if declared, else calkit.io. |
| `--force`, `-f` | boolean | no       | False   | Force logging in again even if already authenticated. Will store a new token in your local config.                                       |

<a id="subcommand-hub-cloud-config"></a>

#### `calkit hub|cloud config`

Work with per-hub credentials (tokens).

Usage:

```text
calkit hub|cloud config COMMAND [ARGS]...
```

<a id="command-group-scheduler-sch"></a>

### `calkit scheduler|sch`

Work with a job scheduler (SLURM or PBS).

| Command                                         | Description                                                       |
| ----------------------------------------------- | ----------------------------------------------------------------- |
| [`batch`](#subcommand-scheduler-sch-batch)      | Submit a batch job through the scheduler associated with the env. |
| [`queue\|q`](#subcommand-scheduler-sch-queue-q) | List scheduler jobs submitted via Calkit (across SLURM and PBS).  |
| [`cancel`](#subcommand-scheduler-sch-cancel)    | Cancel scheduler jobs by their name in the project.               |
| [`logs`](#subcommand-scheduler-sch-logs)        | Get the logs for scheduler jobs by their name in the project.     |

<a id="subcommand-scheduler-sch-batch"></a>

#### `calkit scheduler|sch batch`

Submit a batch job through the scheduler associated with the env.

Duplicates are not allowed, so if one is already running or queued with the same name, we'll wait for it to finish. The only exception is if the dependencies have changed, in which case any queued or running jobs will be canceled and a new one submitted.

If the environment sets `max_concurrent_jobs`, submission waits until this project has fewer than that many jobs queued or running, so an iterated stage does not put all of its jobs into a shared cluster's queue at once.

Usage:

```text
calkit scheduler|sch batch [OPTIONS] TARGET [ARGS...]
```

Arguments:

| Argument | Type | Required | Default | Description                                                                  |
| -------- | ---- | -------- | ------- | ---------------------------------------------------------------------------- |
| `target` | str  | yes      |         | The target to run. This can be a shell script or an executable.              |
| `args`   | str  | no       |         | Arguments for the target command, passed to the job script after the target. |

Options:

| Option                  | Type                           | Required | Default | Description                                                                                                                                                                                                                                                                             |
| ----------------------- | ------------------------------ | -------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--name`, `-n`          | str                            | yes      |         | Job name.                                                                                                                                                                                                                                                                               |
| `--environment`, `-e`   | str                            | yes      |         | Calkit (scheduler) environment to use for the job.                                                                                                                                                                                                                                      |
| `--dep`, `-d`           | str                            | no       |         | Additional dependencies to track, which if changed signify a job is invalid.                                                                                                                                                                                                            |
| `--out`, `-o`           | str                            | no       |         | Non-persistent output files or directories produced by the job, which will be deleted before submitting a new job.                                                                                                                                                                      |
| `--option`, `-s`        | str                            | no       |         | Additional options to pass to the scheduler submit command (no spaces allowed).                                                                                                                                                                                                         |
| `--setup`               | str                            | no       |         | Shell setup command to run before launching the target (repeat for multiple commands).                                                                                                                                                                                                  |
| `--log-path`            | str                            | no       |         | Output log path.                                                                                                                                                                                                                                                                        |
| `--command`             | boolean                        | no       |         | Whether the target is a command instead of a script.                                                                                                                                                                                                                                    |
| `--env-default-options` | choice(ignore, replace, merge) | no       | replace | How to apply the environment's default scheduler options: 'replace' (default) uses env defaults only when no options were provided here; 'merge' prepends env defaults (the scheduler's last-occurrence wins, so explicit options still override); 'ignore' never applies env defaults. |
| `--env-default-setup`   | choice(ignore, replace, merge) | no       | replace | How to apply the environment's default setup commands: 'replace' (default) uses env defaults only when no setup commands were provided here; 'merge' prepends env defaults; 'ignore' never applies env defaults.                                                                        |

<a id="subcommand-scheduler-sch-queue-q"></a>

#### `calkit scheduler|sch queue|q`

List scheduler jobs submitted via Calkit (across SLURM and PBS).

Usage:

```text
calkit scheduler|sch queue|q
```

<a id="subcommand-scheduler-sch-cancel"></a>

#### `calkit scheduler|sch cancel`

Cancel scheduler jobs by their name in the project.

Usage:

```text
calkit scheduler|sch cancel NAMES...
```

Arguments:

| Argument | Type | Required | Default | Description              |
| -------- | ---- | -------- | ------- | ------------------------ |
| `names`  | str  | yes      |         | Names of jobs to cancel. |

<a id="subcommand-scheduler-sch-logs"></a>

#### `calkit scheduler|sch logs`

Get the logs for scheduler jobs by their name in the project.

If no names are given, every tracked job's log is shown.

Usage:

```text
calkit scheduler|sch logs [OPTIONS] [NAMES...]
```

Arguments:

| Argument | Type | Required | Default | Description                        |
| -------- | ---- | -------- | ------- | ---------------------------------- |
| `names`  | str  | no       |         | Names of the jobs to get logs for. |

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

<a id="command-group-sync"></a>

### `calkit sync`

Sync with external systems.

| Command                                 | Description                                          |
| --------------------------------------- | ---------------------------------------------------- |
| [`git`](#subcommand-sync-git)           | Sync the Git repository by pulling and then pushing. |
| [`dvc`](#subcommand-sync-dvc)           | Sync the DVC repository by pulling and then pushing. |
| [`all`](#subcommand-sync-all)           | Sync all registered systems.                         |
| [`import`](#subcommand-sync-import)     | Pull an imported file from where it came from.       |
| [`overleaf`](#subcommand-sync-overleaf) | Sync folders with Overleaf.                          |

<a id="subcommand-sync-git"></a>

#### `calkit sync git`

Sync the Git repository by pulling and then pushing.

Usage:

```text
calkit sync git [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description |
| ----------------- | ------- | -------- | ------- | ----------- |
| `--no-check-auth` | boolean | no       | False   |             |

<a id="subcommand-sync-dvc"></a>

#### `calkit sync dvc`

Sync the DVC repository by pulling and then pushing.

Usage:

```text
calkit sync dvc [OPTIONS]
```

Options:

| Option            | Type    | Required | Default | Description |
| ----------------- | ------- | -------- | ------- | ----------- |
| `--no-check-auth` | boolean | no       | False   |             |

<a id="subcommand-sync-all"></a>

#### `calkit sync all`

Sync all registered systems.

Usage:

```text
calkit sync all
```

<a id="subcommand-sync-import"></a>

#### `calkit sync import`

Pull an imported file from where it came from.

For a Git source this takes the latest on whatever the entry follows, which is its 'ref' if it names one and the repo's default branch otherwise, and records the commit it lands on. '--git-ref' changes what it follows, from then on and not just this once, so switching to a tag pins the import to that tag rather than quietly reverting to the default branch next time.

This is a one-way copy from the source, not a merge. An import records that a file came from somewhere else, so a local edit that survived a refresh would make the entry a lie about what is on disk -- but losing that edit silently would be worse, so a file that differs from what was last fetched is reported and left alone until '--force' says otherwise. The checksum recorded in '.calkit/imports.json' is what makes the edit visible.

What the fetch resolves to -- the commit, the checksum, the time -- is written to '.calkit/imports.json' rather than to 'calkit.yaml', which keeps only what a person declared. To pin an import, write the commit hash as its 'ref'. An entry written before that split carries its 'rev' in 'calkit.yaml'; refreshing it moves that across, so nothing has to be migrated by hand.

With '--all', every imported object is refreshed instead, whichever list it was recorded in, and they are committed together. One that can't be refreshed in place -- a dataset tracked by DVC, or a record named only by a DOI -- is reported and skipped rather than stopping the rest, and so is one whose source can't be reached, since a repo being down shouldn't leave every other import stale. Naming a single object that can't be refreshed is still an error, since that is what was asked for. With '--all' the command exits non-zero if anything was skipped.

Only imported paths for now, since that is the only kind of object an import records. An imported environment has no path of its own, so when 'calkit import environment' is finished this is where refreshing it belongs.

Usage:

```text
calkit sync import [OPTIONS] [PATH]
```

Arguments:

| Argument | Type | Required | Default | Description                                              |
| -------- | ---- | -------- | ------- | -------------------------------------------------------- |
| `path`   | str  | no       |         | Path of the imported object to refresh. Omit with --all. |

Options:

| Option          | Type    | Required | Default | Description                                                                                                                              |
| --------------- | ------- | -------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `--all`         | boolean | no       | False   | Refresh every imported object in the project, across all artifact kinds. Ones that can't be refreshed in place are reported and skipped. |
| `--git-ref`     | str     | no       |         | Branch, tag, or commit to follow from now on, for a file imported from a Git repo. Recorded, so later refreshes keep using it.           |
| `--force`, `-f` | boolean | no       | False   | Overwrite even if the file has been edited since it was imported.                                                                        |
| `--no-commit`   | boolean | no       | False   | Do not commit changes to repo.                                                                                                           |

<a id="subcommand-sync-overleaf"></a>

#### `calkit sync overleaf`

Sync folders with Overleaf.

Usage:

```text
calkit sync overleaf [OPTIONS] [PATHS...]
```

Arguments:

| Argument | Type | Required | Default | Description                                                                                                      |
| -------- | ---- | -------- | ------- | ---------------------------------------------------------------------------------------------------------------- |
| `paths`  | str  | no       |         | Paths to sync with Overleaf, e.g., 'paper/paper.pdf'. If not provided, all Overleaf publications will be synced. |

Options:

| Option                | Type    | Required | Default | Description                                                                                                                                                                                                                              |
| --------------------- | ------- | -------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--no-commit`         | boolean | no       | False   | Do not create a commit in the project repo for this sync. Changes pulled from Overleaf are still applied, but are left staged so you can review or commit them yourself. Changes are always committed and pushed to Overleaf regardless. |
| `--auto-commit`, `-a` | boolean | no       | False   | Automatically commit changes to the project repo if a synced folder has changes.                                                                                                                                                         |
| `--no-push`           | boolean | no       | False   | Do not push the changes to the main project remote. Changes will always be pushed to Overleaf.                                                                                                                                           |
| `--verbose`           | boolean | no       | False   | Enable verbose output.                                                                                                                                                                                                                   |
| `--resolve`, `-r`     | boolean | no       | False   | Mark merge conflicts as resolved before committing.                                                                                                                                                                                      |
| `--push-only`, `-P`   | boolean | no       | False   | Only push local files to Overleaf without pulling from Overleaf. Useful when initializing a new Overleaf project from local files.                                                                                                       |
| `--allow-stale`       | boolean | no       | False   | Sync even if the pipeline is out-of-date, which can send stale figures or results to Overleaf.                                                                                                                                           |
| `--any-branch`        | boolean | no       | False   | Sync even if the current branch is missing commits from the default branch.                                                                                                                                                              |
| `--force`, `-f`       | boolean | no       | False   | Overwrite changes made on Overleaf to push-only paths, which the project is meant to be the source of truth for.                                                                                                                         |
