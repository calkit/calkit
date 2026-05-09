# Agent instructions for working on Calkit

## Repo structure

- The main Python package/CLI lives in `calkit`
- The JupyterLab extension lives in `src`
- The VS Code extension lives in `vscode-ext`

## Working

See `CONTRIBUTING.md` for tool usage, style guidelines, etc.

To run tests, use `uv run pytest`.

To sync the docs and format all the code, run `make format`.

Wrap prose at natural breakpoints in phrases or punctuation to keep max
line length below 80 characters.

Agents should never make commits to Git.

Prefer tests that include multiple scenarios to comprehensively test
a feature in one function over many different test functions.

For prose, only use one space after punctuation.
