# Calkit dev container

A dev container spec for working on Calkit projects,
and the image it runs, `ghcr.io/calkit/devcontainer`.
To add the spec to a project, or update it to the latest version, run:

```sh
calkit update devcontainer
```

## Files

- `base.json`: The spec, minus the VS Code extensions and settings shared
  with [`../vscode`](../vscode).
  Edit this to change the image, features, lifecycle hooks, or any setting
  that should only apply inside the container.
- `devcontainer.json`: Generated from `base.json` and `../vscode`.
  Don't edit it by hand; run `make sync-resources` instead.
  This is the file copied into projects.
- `Dockerfile`: The image, which bundles conda, uv, Pixi, and Calkit itself.
- `scripts/`: Lifecycle hook scripts, baked into the image at
  `$INIT_SCRIPTS_DIR`.

## Building the image

```sh
make devcontainer-image
```

This builds the image for the local platform and smoke tests it.
CI builds it on every pull request that touches this directory, and pushes
a multi-platform build to `ghcr.io/calkit/devcontainer` on release, pinned
to the Calkit version being released via the `CALKIT_VERSION` build arg,
tagged `latest` and `<version>`.
Image tags carry no `v` prefix, matching how the images this one builds on
are tagged, so they differ from the Git tag they're built from.

The package predates this repo, so pushing to it requires that the package's
[settings](https://github.com/orgs/calkit/packages/container/devcontainer/settings)
grant `calkit/calkit` the write role under "Manage Actions access".
The `org.opencontainers.image.source` label in the `Dockerfile` is what
links the package to this repo once that push happens.

## Testing the container itself

To open a project in a locally built image rather than the published one,
build the image as above, then point the project's
`.devcontainer/devcontainer.json` at the `calkit/devcontainer:dev` tag it
produces and run "Dev Containers: Rebuild and Reopen in Container".
