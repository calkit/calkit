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

The [`marimo-html-wasm`](pipeline/index.md#marimo-html-wasm) pipeline stage
kind exports a [marimo](https://marimo.io) notebook to static files that can
be served as a `static-html` app.
The app runs entirely in the browser via WebAssembly,
so it stays interactive with no backend running anywhere:

```yaml
pipeline:
  stages:
    app:
      kind: marimo-html-wasm
      environment: py
      notebook_path: notebook.py
      layout_path: layouts/notebook.grid.json
      show_code: true
      include_paths:
        - processed/all-simulated.csv
        - figures/*-umag.png
      output_dir: app
      output_storage: dvc
```

marimo's export commands differ enough from each other that each gets its
own stage kind, rather than one kind with a format option whose other
fields only apply to some of its values.

Set `mode: edit` to ship an editable notebook rather than a read-only app.
Since code is always visible when editing, `show_code` only applies to the
default `mode: run`.

Because an exported app is large, `output_storage` defaults to `dvc`.

### Publishing the data an app reads

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
Each one is a dependency too,
reduced to its longest non-glob parent,
so a pattern like `figures/*-umag.png` depends on `figures`.
A pattern that starts with a glob is rejected,
since it leaves no directory to depend on.

<!-- prettier-ignore -->
!!! note

    marimo's own export is not self-contained: it requires this `public`
    directory to already sit next to the notebook, and copies only that
    directory into the output. Assembling it is the stage's main job, and it
    happens in a build directory under `.calkit/local` rather than in place,
    so nothing is generated in the project tree.

### Dependencies

A marimo notebook needs an inline
[PEP 723](https://peps.python.org/pep-0723/) block declaring what to install
in the browser, or the app fails on its first third-party import.
The stage generates one into its build copy from what the notebook actually
imports, resolved to distribution names in the stage's environment,
so the notebook in the project carries no second dependency spec.
A block written by hand is left alone.

Only packages installed from PyPI at load time are pinned to the version
the stage environment resolved.
Anything Pyodide ships is a binary build whose version the runtime fixes,
so pinning it would record a version that never runs.

<!-- prettier-ignore -->
!!! note

    Calkit doesn't ship marimo, so it must be a dependency of the
    environment the stage runs in. The stage runs
    `calkit nb export-marimo-wasm` in that environment; wrapping the export
    this way keeps the command recorded in `dvc.lock` stable as marimo's own
    flags change.

### Declaring the app

The export writes the app's entrypoint at `output_dir/index.html`,
so the app is then declared as:

```yaml
apps:
  naca0012:
    kind: static-html
    path: app/index.html
    stage: app
```
