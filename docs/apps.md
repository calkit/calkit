# Apps

A project can define apps to let people interact with its results, e.g.,
explore a dataset or make predictions from a model,
without cloning the project or installing anything.

Apps are declared in the `apps` mapping in `calkit.yaml`,
keyed by a short name:

```yaml
apps:
  naca0012:
    kind: static-html
    path: app/index.html
    title: NACA 0012 explorer
    description: Interactively explore the simulated lift and drag.
    stage: build-app
```

The key is what identifies the app,
so it stays the same even if the app's directory is renamed,
and it becomes part of the app's URL on the
[Calkit Hub](https://calkit.io).

## The `static-html` kind

`static-html` is an app served as static files, with no backend.
The `path` names the app's HTML entrypoint rather than its directory,
and the directory holding it is what gets served,
so assets sitting beside the entrypoint resolve against it.

`stage` is optional, and names the pipeline stage that builds the app,
the same way figures and publications record where they came from.

<!-- prettier-ignore -->
!!! note

    There is no `url` field. Apps are served from the project itself, so the
    URL is derived from the project and the app's name. Embedding an app
    hosted somewhere else, e.g., on Hugging Face Spaces, is no longer
    supported.

## Building an app from a marimo notebook

The [`marimo`](pipeline/index.md#marimo) pipeline stage kind exports a
[marimo](https://marimo.io) notebook to static files that can be served as a
`static-html` app:

```yaml
pipeline:
  stages:
    build-app:
      kind: marimo
      environment: py
      notebook_path: notebook.py
      include_paths:
        - processed/all-simulated.csv
      output_path: app
```

With the default `to: html-wasm` the app runs entirely in the browser via
WebAssembly, so it stays interactive with no backend running anywhere.
With `to: html` the notebook is executed when the pipeline runs and its
output is baked into a single static HTML file,
which is not interactive but is much smaller.

Any data the app reads has to be published with it,
which is what `include_paths` is for.
Those paths are copied beneath a `public` directory in the exported app,
keeping their project-relative paths,
so notebook code that reads
`mo.notebook_location() / "public" / "processed/all-simulated.csv"`
works the same locally as it does in the browser.
They are separate from the stage's `inputs`
because publishing a file to the web should be opt-in per path
rather than inferred from the dependency graph.

<!-- prettier-ignore -->
!!! note

    Calkit doesn't ship marimo, so it must be a dependency of the
    environment the stage runs in.

Since the export writes the app's entrypoint at `output_path/index.html`,
the app is then declared as:

```yaml
apps:
  naca0012:
    kind: static-html
    path: app/index.html
    stage: build-app
```
