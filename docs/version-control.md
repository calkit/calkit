# Version control

Calkit is built upon
[Git](https://git-scm.com) and
[DVC](https://dvc.org) to enable keeping all project materials
in version control.
It provides a simplified interface to help reduce the number of
decisions and steps necessary to interact with the repository and
its remote storage.
The lower-level tools `git` and `dvc` can be used if desired, however.

## Commands

### `clone`

`calkit clone` will download and create a local copy of the project,
setup the default Calkit DVC remote and pull any files versioned with DVC.
The multi-step equivalent would be:

- `git clone`
- `calkit config remote`
- `dvc pull`

### `add`

`calkit add` will add a file to the repo staging area.
Calkit will determine based on its type and size if it should be tracked
with Git or DVC and act accordingly.

Options:

- `--to`, `-t`: Manually specify `git` or `dvc` as the tracking mechanism.
- `--commit-message`, `-m`: Create a commit after adding.
- `--push`: Push to the Git or DVC remote after pushing.

### `save`

`calkit save` will create a commit and push to the remotes in one step.
