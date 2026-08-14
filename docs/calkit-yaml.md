# The `calkit.yaml` file

The `calkit.yaml` file serves as a small "database"
for the project's important metadata, which includes its:

- Global or system-level [dependencies](dependencies.md) or requirements
  (applications, environmental variables, or other configuration steps)
- [Questions](questions.md) the project seeks to answer
- [Environments](environments.md)
- [The pipeline](pipeline/index.md)
- [Datasets](datasets.md)
- Figures
- Publications (journal articles, conference papers, and theses)
- Presentations (slides and posters)
- [Procedures](tutorials/procedures.md)
- [References](references.md)
- Subprojects (smaller projects executed as part of the main project)
- Calculations (ways to make predictions with the results)
- App (a way to allow users to interact with the results)

Objects can be imported from other projects,
which produces a chain of reference to allow tracking reuse
and reduce redundant storage.

## Showcase

The project showcase is a list of elements that best represent the project,
shown on the project homepage on the hub.
For example:

```yaml
showcase:
  - text: Here is some text.
  - figure: figures/my-figure.png
  - text: There is a figure above.
  - markdown: "### This is a Markdown heading"
  - publication: paper/paper.pdf
```

[This project](https://calkit.io/petebachant/strava-analysis)
has a showcase that includes Plotly figures saved as JSON,
which render interactively.

## Schema, validation, and autocompletion

Calkit publishes a [JSON Schema](https://json-schema.org/) describing
`calkit.yaml` at
[docs.calkit.org/schemas/calkit.json](https://docs.calkit.org/schemas/calkit.json).
Editors use it to flag mistakes as you type---misspelled keys, missing
required fields, invalid environment or stage kinds---and to autocomplete
keys and values with inline documentation.

Projects created with `calkit init` or `calkit new project` get a schema
reference on the first line of their `calkit.yaml`:

```yaml
# yaml-language-server: $schema=https://docs.calkit.org/schemas/calkit.json
```

To add it to an existing project, paste that line at the top of the file.
Calkit preserves it when it updates the file.

<!-- prettier-ignore -->
!!! note
    In VS Code this requires the
    [YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml),
    which is installed automatically along with the
    [Calkit extension](https://marketplace.visualstudio.com/items?itemName=calkit.calkit-vscode).
    The Calkit extension also bundles a copy of the schema and applies it to
    every `calkit.yaml`, so the comment above is not strictly necessary if
    you're working in VS Code. The comment takes precedence when present,
    which keeps the file validating the same way for collaborators using
    other editors.

To generate a copy of the schema matching your installed version of Calkit,
e.g., to check the file in CI or point an editor at it directly, run:

```sh
calkit schema -o calkit-schema.json
```
