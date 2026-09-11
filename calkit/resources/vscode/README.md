# VS Code config

Recommended VS Code settings and extensions for Calkit projects.
To add these to a project, or update them to the latest version, run:

```sh
calkit update vscode-config
```

This writes `.vscode/settings.json` and `.vscode/extensions.json`,
and commits them.

These files are also the source for the dev container's
`customizations.vscode` section, so a project gets the same editor setup
whether it's opened locally or in a container.
After editing them, run `make sync-resources` to regenerate
[`../devcontainer/devcontainer.json`](../devcontainer/devcontainer.json).

Settings that only make sense inside the container,
like the color theme and Python terminal activation,
live in [`../devcontainer/base.json`](../devcontainer/base.json) instead,
since these settings go into a user's project and shouldn't override
their own preferences.
