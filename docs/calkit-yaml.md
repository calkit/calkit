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

## Declaring artifacts

Figures, datasets, results, and presentations are auto-detected from the
project's files, so `calkit list figures` shows a plot under `figures/`
whether or not you've written it down.
Each entry is flagged `detected` to tell the two apart.

Declaring one in `calkit.yaml` anyway is how you say it has standalone
significance: that it's worth a title and a description, that it's one of
the things the project is *for*, rather than an incidental file that
happens to sit in the right directory.
Declaring it also makes its kind explicit rather than guessed from its
path, which several commands rely on.

Once something is declared, other projects can build on it.
Datasets can be pulled into another project with
[`calkit import dataset`](cli-reference.md), keeping a chain of reference
back to where they came from.

An artifact can also be released on its own to get its own DOI, rather than
only as part of a whole-project release:

```sh
calkit new release figures/my-fig.png --name my-fig-v1
```

The release takes its kind from the declaration when there is one, and falls
back to inferring it from the path;
if neither works, it asks you to declare the artifact or pass `--kind`.

## Results

Results are the project's findings: the things you'd point at to back up an
answer, or to summarize what the project found.
A result can be a single value, a table, a map, or any other shape a file
takes.
They're keyed by name:

```yaml
results:
  drag-vs-speed:
    path: results/drag.csv
    title: Drag versus speed
  mean-drag:
    path: results/summary.json
    key: metrics.mean
    title: Mean drag coefficient
  std-drag:
    path: results/summary.json
    key: metrics.std
```

`key` is optional, and addresses one value within an object-like file,
which is what lets several results share a file the way `mean-drag` and
`std-drag` do above.
Omit it when the result is the whole file.
`title` is optional too, since the name already identifies the result.

<!-- prettier-ignore -->
!!! note
    A result and a [dataset](datasets.md) can be the same file, because they
    answer different questions about it. A dataset is a product the project
    exports for others to use; a result is evidence for what the project
    found.

To declare one from the command line:

```sh
calkit new result results/summary.json --key metrics.mean --name mean-drag
```

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
calkit describe schema -o calkit-schema.json
```

## Reference

Every key that can appear at the top level of `calkit.yaml`, generated from
the same models as the schema above.
Keys linking to another page are described in more detail there;
the properties that go inside pipeline stages are covered under
[the pipeline](pipeline/index.md), and those for environments under
[environments](environments.md).

<!-- AUTO-GENERATED: CALKIT-YAML-KEYS:START -->

| Key                                     | Type                                                                                                                                            | Required | Description                                                                                                                                                                                                                                                                                                                                                                |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$schema`                               | str                                                                                                                                             | no       | URL of the JSON schema describing this file.                                                                                                                                                                                                                                                                                                                               |
| `title`                                 | str                                                                                                                                             | no       | A human-readable title for the project.                                                                                                                                                                                                                                                                                                                                    |
| `owner`                                 | str                                                                                                                                             | no       | The account name that owns the project on Calkit.                                                                                                                                                                                                                                                                                                                          |
| `description`                           | str                                                                                                                                             | no       | A short description of the project.                                                                                                                                                                                                                                                                                                                                        |
| `name`                                  | str                                                                                                                                             | no       | The project's name on Calkit, e.g., 'my-project'.                                                                                                                                                                                                                                                                                                                          |
| `hub`                                   | str                                                                                                                                             | no       | Base URL of the Calkit Hub on which the project is shared, backed up, and collaborated on, e.g., 'calkit.io'. The scheme can be omitted, in which case https is inferred, or http for a local host. Each project belongs to at most one hub, which makes 'ck://' paths resolvable against a known instance. Projects with no hub set are assumed to belong to 'calkit.io'. |
| `git_repo_url`                          | str                                                                                                                                             | no       | URL of the project's Git repository.                                                                                                                                                                                                                                                                                                                                       |
| `derived_from`                          | DerivedFromProject                                                                                                                              | no       | The project this one was created as a copy of.                                                                                                                                                                                                                                                                                                                             |
| [`questions`](questions.md)             | list[str \| Question]                                                                                                                           | no       | Questions the project seeks to answer.                                                                                                                                                                                                                                                                                                                                     |
| [`dependencies`](dependencies.md)       | list[str \| Dependency \| dict[str, DependencyAttrs]]                                                                                           | no       | System-level dependencies: applications that must be on PATH, environmental variables, or per-machine setup steps.                                                                                                                                                                                                                                                         |
| `parameters`                            | dict[str, int \| float \| str \| list[int \| float \| str \| RangeIteration]]                                                                   | no       | Project-level parameters, which can be referenced from pipeline stages.                                                                                                                                                                                                                                                                                                    |
| [`pipeline`](pipeline/index.md)         | Pipeline                                                                                                                                        | no       | The project's reproducible pipeline.                                                                                                                                                                                                                                                                                                                                       |
| [`datasets`](datasets.md)               | list[Dataset]                                                                                                                                   | no       | The project's datasets.                                                                                                                                                                                                                                                                                                                                                    |
| `figures`                               | list[Figure]                                                                                                                                    | no       | The project's figures.                                                                                                                                                                                                                                                                                                                                                     |
| `results`                               | dict[str, Result]                                                                                                                               | no       | The project's findings, keyed by name. Each refers to a file, or to part of one.                                                                                                                                                                                                                                                                                           |
| `publications`                          | list[Publication]                                                                                                                               | no       | The project's papers, reports, and proposals.                                                                                                                                                                                                                                                                                                                              |
| `presentations`                         | list[Presentation]                                                                                                                              | no       | The project's slides and posters.                                                                                                                                                                                                                                                                                                                                          |
| [`references`](references.md)           | list[ReferenceCollection]                                                                                                                       | no       | The project's bibliographies.                                                                                                                                                                                                                                                                                                                                              |
| [`environments`](environments.md)       | dict[str, Environment]                                                                                                                          | no       | Environments in which pipeline stages are run, keyed by name.                                                                                                                                                                                                                                                                                                              |
| `software`                              | list[Software]                                                                                                                                  | no       | Software created as part of the project.                                                                                                                                                                                                                                                                                                                                   |
| `notebooks`                             | list[Notebook]                                                                                                                                  | no       | The project's Jupyter notebooks.                                                                                                                                                                                                                                                                                                                                           |
| [`procedures`](tutorials/procedures.md) | dict[str, Procedure]                                                                                                                            | no       | Procedures, typically executed by a human, keyed by name.                                                                                                                                                                                                                                                                                                                  |
| [`releases`](releases.md)               | dict[str, Release]                                                                                                                              | no       | Published or archived snapshots, keyed by name.                                                                                                                                                                                                                                                                                                                            |
| `showcase`                              | list[ShowcaseFigure \| ShowcaseText \| ShowcaseMarkdown \| ShowcaseMarkdownFile \| ShowcaseYamlFile \| ShowcaseNotebook \| ShowcasePublication] | no       | Elements that best represent the project, shown on its project homepage on Calkit.                                                                                                                                                                                                                                                                                         |
| `subprojects`                           | list[Subproject]                                                                                                                                | no       | Smaller projects executed as part of this one.                                                                                                                                                                                                                                                                                                                             |
| `calculations`                          | dict[str, Formula \| Linear \| LookupTable]                                                                                                     | no       | Calculations that can be run with 'calkit calc run'.                                                                                                                                                                                                                                                                                                                       |
| `env_vars`                              | dict[str, str]                                                                                                                                  | no       | Environmental variables set when running project commands.                                                                                                                                                                                                                                                                                                                 |
| `overleaf_sync`                         | dict[str, OverleafSync]                                                                                                                         | no       | Overleaf sync configuration, keyed by the path of the synced directory.                                                                                                                                                                                                                                                                                                    |

<!-- AUTO-GENERATED: CALKIT-YAML-KEYS:END -->
