# Calkit project resources

Configuration Calkit copies into projects.
These ship with the Python package, like the templates in
[`../templates`](../templates), so the commands that install them work
offline and always match the installed version of Calkit.
See [`__init__.py`](__init__.py) for how to read them.

| Resource                             | Command                        |
| ------------------------------------ | ------------------------------ |
| [`devcontainer`](devcontainer)       | `calkit update devcontainer`   |
| [`vscode`](vscode)                   | `calkit update vscode-config`  |
| [`github-actions`](github-actions)   | `calkit update github-actions` |
| [`latex`](latex)                     | `calkit latex build --provenance` |

Two of these are generated, so edit the source rather than the copy here,
then run `make sync-resources` (or `make format`).
`calkit/tests/test_resources.py` fails if they're out of sync.

| Generated                            | Source                                       |
| ------------------------------------ | -------------------------------------------- |
| `devcontainer/devcontainer.json`     | `devcontainer/base.json` plus [`vscode`](vscode) |
| `github-actions/example.yml`         | [`actions/run/example.yml`](../../actions/run/example.yml), which sits next to the action it calls |

The VS Code settings and extension recommendations are the single source of
truth for the editor setup, so a project gets the same one whether or not
it's opened in a container.
