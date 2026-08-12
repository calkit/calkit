# Calkit project resources

Configuration Calkit copies into projects.
These ship with the Python package, like the templates in
[`../templates`](../templates), so the commands that install them work
offline and always match the installed version of Calkit.
See [`__init__.py`](__init__.py) for how to read them.

| Resource                       | Command                       |
| ------------------------------ | ----------------------------- |
| [`devcontainer`](devcontainer) | `calkit update devcontainer`  |
| [`vscode`](vscode)             | `calkit update vscode-config` |

The VS Code settings and extension recommendations in
[`vscode`](vscode) are the single source of truth.
The dev container spec's `customizations.vscode` section is generated from
them, so run `make sync-resources` (or `make format`) after editing either.
`calkit/tests/test_resources.py` fails if they're out of sync.
