# Agent instructions for working on Calkit

## Repo structure

- The main Python package/CLI lives in `calkit`
- The JupyterLab extension lives in `src`
- The VS Code extension lives in `vscode-ext`

## Working

See `CONTRIBUTING.md` for tool usage, style guidelines, etc.

To run tests, use `uv run pytest`.

To sync the docs and format all the code, run `make format`.

Before finishing a change, type-check it. The CLI gate is mypy
(`uv run mypy <changed files>`, or `make check` for the full suite), and the
VS Code editor uses Pylance (Pyright). Keep new code clean under both, and do
not introduce new type errors.

Wrap prose at natural breakpoints in phrases or punctuation to keep max
line length below 80 characters.

Agents should never make commits to Git.

Prefer tests that include multiple scenarios to comprehensively test
a feature in one function over many different test functions.

Do not write docstrings in test functions.

For prose, only use one space after punctuation.

Don't overzealously split up functions just because they're long.
Functions should usually be used ~3 times before abstracting.
Otherwise, split up long ones into logical sections with comments.
The only exception here is if splitting up a function makes it easier to
write meaningful unit tests.
