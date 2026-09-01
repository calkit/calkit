# The `calkit.yaml` file

The `calkit.yaml` file serves as a small "database"
for the project's important metadata, where certain files came from,
and the relationships between various component.
It include the project's:

- Owner, name, title, description, Calkit Hub URL
- Global or system-level [requirements](requirements.md)
  (applications, environmental variables, or other configuration steps)
- [Questions](questions.md) the project seeks to answer, along with associated
  hypotheses, answers, and evidence
- [Environments](environments.md)
- [The pipeline](pipeline/index.md)
- [Datasets](datasets.md)
- Figures
- Publications (journal articles, conference papers, and theses)
- Presentations (slides and posters)
- Tables (tabular data worth referring to by name)
- [Procedures](tutorials/procedures.md)
- [References](references.md)
- Subprojects (smaller projects executed as part of the main project)
- Calculations (ways to make predictions with the results)
- App (a way to allow users to interact with the results)

Objects can be imported from other projects,
which produces a chain of reference to allow tracking reuse
and reduce redundant storage.

## Declaring artifacts

Figures, datasets, results, and presentations are auto-detected from the
project's files, so `calkit list figures` shows a plot under `figures/`
whether or not you've written it down.
Each entry is flagged `detected` to tell the two apart.

Declaring one in `calkit.yaml` anyway is how you say it has standalone
significance: that it's worth a title and a description, that it's one of
the things the project is _for_, rather than an incidental file that
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

```yaml
results:
  - path: results/drag.csv
    title: Drag versus speed
  - path: results/summary.json
    key: metrics.mean
    title: Mean drag coefficient
    name: mean-drag
  - path: results/summary.json
    key: metrics.std
```

Like the other artifacts, a result is identified by its path.
Unlike them, several results can share one file: `key` addresses a single
value within an object-like file, which is what tells the last two entries
above apart.
Omit `key` when the result is the whole file.

`name` is optional, and gives the result a short handle to refer to it by,
which stays the same if the file is later renamed.
`title` is optional too, and is only what gets displayed.

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

## Tables

A table can be cited as evidence for a question inline, just like a result:

```yaml
questions:
  - question: What are the top 20 most expensive kernels?
    evidence:
      - kind: table
        path: results/top-kernels.csv
        explanation: Top 20 GPU kernels by baseline cost.
```

Nothing has to be declared for that to work.
Declare one under `tables:` when it's worth a title and description of its
own, the same way you would a figure:

```yaml
tables:
  - path: results/top-kernels.csv
    title: Top 20 GPU kernels, baseline vs. mod
    description: Per-kernel Nsight Systems aggregates for the top 20 kernels.
```

Like the other artifacts, a table is identified by its path.

On the Calkit Hub, tables show up on the project's Tables page, where each
one can be searched, sorted, and linked to by cell.
Declaring a table isn't required to appear there: CSV, TSV, and JSON Lines
files in a `tables` or `results` directory are detected automatically, as are
LaTeX tables written to their own file, i.e., a `.tex` file in those
directories holding a bare `tabular` environment, or one wrapped in a
`standalone` document.
A paper that happens to contain a table is not detected as one, since a table
pulled out of a larger document is a fragment of that document rather than an
artifact of its own.
Declaring one only adds a title and description of your own.

Columns aren't described yet, and neither is a symbolic name for a table.
Both are expected to arrive alongside symbol metadata, which is where
per-column types and units belong.

<!-- prettier-ignore -->
!!! tip
    Which collections are keyed by name and which are lists comes down to
    one question: does anything else in the file have to *name* it?
    Environments are named by stages, stages by `from_stage_outputs`,
    procedures and calculations by the commands that run them---so those are
    maps. Nothing names a figure, dataset, publication, presentation, result,
    table, or question; they're referred to by path, or not at all, so those
    are lists.

## Showcase

The project showcase is a list of elements that best represent the project,
shown on the project's homepage.
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
Editors use it to flag mistakes as you type---invalid environment or stage
kinds, missing required fields, misspelled keys within a pipeline
stage---and to autocomplete keys and values with inline documentation.

Top-level keys and keys inside an environment are deliberately permissive:
an unknown one there validates rather than failing, so a project using a
newer or experimental feature isn't reported as broken by an older schema.
Pipeline stages are the exception, and are strict, because a misspelled key
there silently changes what runs.

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
    which is installed alongside the
    [Calkit extension](https://marketplace.visualstudio.com/items?itemName=calkit.calkit-vscode)
    and can be removed if you'd rather not have it.
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

| Key                                     | Type                                                                                                                                                           | Required | Description                                                                                                                                                                                                                                                                                                                                                                |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$schema`                               | str                                                                                                                                                            | no       | URL of the JSON schema describing this file.                                                                                                                                                                                                                                                                                                                               |
| `title`                                 | str                                                                                                                                                            | no       | A human-readable title for the project.                                                                                                                                                                                                                                                                                                                                    |
| `owner`                                 | str                                                                                                                                                            | no       | The account name that owns the project on Calkit.                                                                                                                                                                                                                                                                                                                          |
| `description`                           | str                                                                                                                                                            | no       | A short description of the project.                                                                                                                                                                                                                                                                                                                                        |
| `name`                                  | str                                                                                                                                                            | no       | The project's name on Calkit, e.g., 'my-project'.                                                                                                                                                                                                                                                                                                                          |
| `hub`                                   | str                                                                                                                                                            | no       | Base URL of the Calkit Hub on which the project is shared, backed up, and collaborated on, e.g., 'calkit.io'. The scheme can be omitted, in which case https is inferred, or http for a local host. Each project belongs to at most one hub, which makes 'ck://' paths resolvable against a known instance. Projects with no hub set are assumed to belong to 'calkit.io'. |
| `git_repo_url`                          | str                                                                                                                                                            | no       | URL of the project's Git repository.                                                                                                                                                                                                                                                                                                                                       |
| `derived_from`                          | DerivedFromProject                                                                                                                                             | no       | The project this one was created as a copy of.                                                                                                                                                                                                                                                                                                                             |
| [`questions`](questions.md)             | list[str \| Question]                                                                                                                                          | no       | Questions the project seeks to answer.                                                                                                                                                                                                                                                                                                                                     |
| [`requirements`](requirements.md)       | list[str \| SystemNumberRequirement \| SystemValueRequirement \| SetupRequirement \| Requirement \| dict[str, RequirementAttrs]]                               | no       | What must be true of the machine before the project runs: applications that must be on PATH, environmental variables, per-machine setup steps, and constraints on machine properties like CPU count. These describe the host, which is the built-in '_system' environment; a 'system' environment declares its own.                                                        |
| [`dependencies`](requirements.md)       | list[str \| SystemNumberRequirement \| SystemValueRequirement \| SetupRequirement \| Requirement \| dict[str, RequirementAttrs]]                               | no       | Deprecated alias for 'requirements', still honored so existing projects keep working. Set one or the other, not both.                                                                                                                                                                                                                                                      |
| `parameters`                            | dict[str, int \| float \| str \| list[int \| float \| str \| RangeIteration]]                                                                                  | no       | Project-level parameters, which can be referenced from pipeline stages.                                                                                                                                                                                                                                                                                                    |
| [`pipeline`](pipeline/index.md)         | Pipeline                                                                                                                                                       | no       | The project's reproducible pipeline.                                                                                                                                                                                                                                                                                                                                       |
| [`datasets`](datasets.md)               | list[Dataset]                                                                                                                                                  | no       | The project's datasets.                                                                                                                                                                                                                                                                                                                                                    |
| `figures`                               | list[Figure]                                                                                                                                                   | no       | The project's figures.                                                                                                                                                                                                                                                                                                                                                     |
| `results`                               | list[Result]                                                                                                                                                   | no       | The project's findings, each referring to a file, or to part of one.                                                                                                                                                                                                                                                                                                       |
| `publications`                          | list[Publication]                                                                                                                                              | no       | The project's papers, reports, and proposals.                                                                                                                                                                                                                                                                                                                              |
| `presentations`                         | list[Presentation]                                                                                                                                             | no       | The project's slides and posters.                                                                                                                                                                                                                                                                                                                                          |
| `tables`                                | list[Table]                                                                                                                                                    | no       | The project's tables. Only needed for tables worth a title of their own; evidence can point at one inline.                                                                                                                                                                                                                                                                 |
| [`references`](references.md)           | list[ReferenceCollection]                                                                                                                                      | no       | The project's bibliographies.                                                                                                                                                                                                                                                                                                                                              |
| [`environments`](environments.md)       | dict[str, Environment]                                                                                                                                         | no       | Environments in which pipeline stages are run, keyed by name.                                                                                                                                                                                                                                                                                                              |
| `misc`                                  | list[MiscArtifact]                                                                                                                                             | no       | Paths worth attributing that aren't one of the typed artifacts, e.g. an image someone sent over or a file produced with help from a generative AI tool.                                                                                                                                                                                                                    |
| `software`                              | list[Software]                                                                                                                                                 | no       | Software created as part of the project.                                                                                                                                                                                                                                                                                                                                   |
| `notebooks`                             | list[Notebook]                                                                                                                                                 | no       | The project's Jupyter notebooks.                                                                                                                                                                                                                                                                                                                                           |
| [`procedures`](tutorials/procedures.md) | dict[str, ProcedureFile \| Procedure]                                                                                                                          | no       | Procedures, typically executed by a human, keyed by name. Each is written inline or points at the file holding it.                                                                                                                                                                                                                                                         |
| [`releases`](releases.md)               | dict[str, Release]                                                                                                                                             | no       | Published or archived snapshots, keyed by name.                                                                                                                                                                                                                                                                                                                            |
| `apps`                                  | dict[str, StaticHtmlApp]                                                                                                                                       | no       | The project's apps, keyed by name.                                                                                                                                                                                                                                                                                                                                         |
| `showcase`                              | list[ShowcaseFigure \| ShowcaseText \| ShowcaseMarkdown \| ShowcaseMarkdownFile \| ShowcaseYamlFile \| ShowcaseNotebook \| ShowcasePublication \| ShowcaseApp] | no       | Elements that best represent the project, shown on its project homepage on Calkit.                                                                                                                                                                                                                                                                                         |
| `subprojects`                           | list[Subproject]                                                                                                                                               | no       | Smaller projects executed as part of this one.                                                                                                                                                                                                                                                                                                                             |
| `calculations`                          | dict[str, Formula \| Linear \| LookupTable]                                                                                                                    | no       | Calculations that can be run with 'calkit calc run'.                                                                                                                                                                                                                                                                                                                       |
| `env_vars`                              | dict[str, str]                                                                                                                                                 | no       | Environmental variables set when running project commands.                                                                                                                                                                                                                                                                                                                 |
| `overleaf_sync`                         | dict[str, OverleafSync]                                                                                                                                        | no       | Overleaf sync configuration, keyed by the path of the synced directory.                                                                                                                                                                                                                                                                                                    |

### Nested types

Keys above whose type is a named object, like `Figure`, hold the properties described below.

#### `DerivedFromProject`

| Parameter      | Type | Required | Default | Description |
| -------------- | ---- | -------- | ------- | ----------- |
| `project`      | str  | yes      |         |             |
| `git_repo_url` | str  | yes      |         |             |
| `git_rev`      | str  | yes      |         |             |

#### `RangeIteration`

| Parameter | Type                 | Required | Default | Description                                |
| --------- | -------------------- | -------- | ------- | ------------------------------------------ |
| `range`   | RangeIterationParams | yes      |         | Bounds of the range over which to iterate. |

#### `Figure`

A figure, usually produced by a pipeline stage.

Carries attribution for the ones that aren't: a schematic drawn by hand
or laid out with a generative AI tool has no stage to point at, and is
exactly the kind of thing a reader wants told. One obtained from
elsewhere records `imported_from` instead, like a dataset does.

| Parameter       | Type                                                                                                                 | Required | Default | Description                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --------------- | -------------------------------------------------------------------------------------------------------------------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `path`          | str                                                                                                                  | yes      |         | Path to the file, relative to the project root.                                                                                                                                                                                                                                                                                                                                                                                      |
| `title`         | str \| None                                                                                                          | no       | null    | A human-readable title.                                                                                                                                                                                                                                                                                                                                                                                                              |
| `description`   | str \| None                                                                                                          | no       | null    | A longer description.                                                                                                                                                                                                                                                                                                                                                                                                                |
| `stage`         | str \| None                                                                                                          | no       | null    | Name of the pipeline stage that produces this.                                                                                                                                                                                                                                                                                                                                                                                       |
| `created_by`    | _Person \| list[_Person] \| None                                                                                     | no       | null    | Who created this primary artifact here, e.g., collected or measured the data, drew the figure, or took the photo, rather than it being produced by the pipeline or obtained from elsewhere. A primary artifact has no upstream source to point at, so naming who produced it is the only way to tell it apart from one whose provenance was never recorded. Each person discloses the generative AI tools they used via ``with_ai``. |
| `imported_from` | _ImportedFromProject \| _ImportedFromUrl \| _ImportedFromDoi \| _ImportedFromGit \| _ImportedFromDescription \| None | no       | null    | Where this came from, if imported.                                                                                                                                                                                                                                                                                                                                                                                                   |

#### `Result`

A finding the project produced: a value, a table, a map, or a file.

Like the other artifacts, a result is identified by its path, but unlike
them several results can share one file, e.g., a mean and a standard
deviation both read out of one summary file. `key` is what tells those
apart, so the identity is really the `(path, key)` pair. Which part of
a file a result refers to is left open on purpose: other forms of
addressing can be added without reshaping what a result is.

| Parameter     | Type        | Required | Default | Description                                                                                                                                   |
| ------------- | ----------- | -------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `path`        | str         | yes      |         | Path to the file, relative to the project root.                                                                                               |
| `title`       | str \| None | no       | null    | A human-readable title.                                                                                                                       |
| `description` | str \| None | no       | null    | A longer description.                                                                                                                         |
| `stage`       | str \| None | no       | null    | Name of the pipeline stage that produces this.                                                                                                |
| `key`         | str \| None | no       | null    | Which value within the file this result refers to, e.g., 'metrics.mean'. Omit it when the result is the whole file.                           |
| `name`        | str \| None | no       | null    | A short handle for referring to this result, which stays stable if the file is renamed. Optional, since the path and key already identify it. |

#### `Publication`

A publication the project produced, or one it builds upon.

Whether it has been published is not written down but derived: a
publication of record has a DOI, so `is_published` is true exactly
when `doi` is set, and reads the same on the hub and in the CLI.

| Parameter       | Type                                                                                                                 | Required | Default | Description                                                                                         |
| --------------- | -------------------------------------------------------------------------------------------------------------------- | -------- | ------- | --------------------------------------------------------------------------------------------------- |
| `path`          | str                                                                                                                  | yes      |         | Path to the file, relative to the project root.                                                     |
| `title`         | str \| None                                                                                                          | no       | null    | A human-readable title.                                                                             |
| `description`   | str \| None                                                                                                          | no       | null    | A longer description.                                                                               |
| `stage`         | str \| None                                                                                                          | no       | null    | Name of the pipeline stage that produces this.                                                      |
| `kind`          | Literal['journal-article', 'conference-paper', 'proposal', 'report', 'blog', 'book', 'thesis', 'phd-thesis'] \| None | no       | null    |                                                                                                     |
| `doi`           | str \| None                                                                                                          | no       | null    | This publication's own DOI, once it has one. Setting it is what marks the publication as published. |
| `imported_from` | _ImportedFromProject \| _ImportedFromUrl \| _ImportedFromDoi \| _ImportedFromGit \| _ImportedFromDescription \| None | no       | null    | Where this came from, if imported.                                                                  |

#### `Presentation`

| Parameter     | Type                                | Required | Default | Description                                     |
| ------------- | ----------------------------------- | -------- | ------- | ----------------------------------------------- |
| `path`        | str                                 | yes      |         | Path to the file, relative to the project root. |
| `title`       | str \| None                         | no       | null    | A human-readable title.                         |
| `description` | str \| None                         | no       | null    | A longer description.                           |
| `stage`       | str \| None                         | no       | null    | Name of the pipeline stage that produces this.  |
| `kind`        | Literal['slides', 'poster'] \| None | no       | null    | What kind of presentation this is.              |

#### `Table`

Tabular data, whether it's the finding itself or how one is shown.

Identified by path, like the other artifacts, and cited that way.

Declaring one is optional: evidence says what it points at inline via
`kind`, so an entry here is only needed when the table is worth a title
and a description of its own.

Deliberately nothing beyond the shared artifact fields yet. A `name`,
for referring to a table symbolically, and `columns` both want to exist
eventually, but neither has anything reading it today, and columns need
per-column types and units that belong with symbol metadata rather than
being invented separately here. Both are free to add later; a field
shipped early is not free to remove.

| Parameter     | Type        | Required | Default | Description                                     |
| ------------- | ----------- | -------- | ------- | ----------------------------------------------- |
| `path`        | str         | yes      |         | Path to the file, relative to the project root. |
| `title`       | str \| None | no       | null    | A human-readable title.                         |
| `description` | str \| None | no       | null    | A longer description.                           |
| `stage`       | str \| None | no       | null    | Name of the pipeline stage that produces this.  |

#### `MiscArtifact`

A path worth attributing that isn't one of the typed artifacts.

Most files in a project are neither a dataset nor a figure nor a paper:
a photograph, a slide someone drew, a config a colleague sent over. They
still have an origin, and without somewhere to record it the honest
answer is missing rather than merely absent.

| Parameter       | Type                                                                                                                 | Required | Default | Description                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --------------- | -------------------------------------------------------------------------------------------------------------------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `path`          | str                                                                                                                  | yes      |         | Path to the file, relative to the project root.                                                                                                                                                                                                                                                                                                                                                                                      |
| `title`         | str \| None                                                                                                          | no       | null    | A human-readable title.                                                                                                                                                                                                                                                                                                                                                                                                              |
| `description`   | str \| None                                                                                                          | no       | null    | A longer description.                                                                                                                                                                                                                                                                                                                                                                                                                |
| `stage`         | str \| None                                                                                                          | no       | null    | Name of the pipeline stage that produces this.                                                                                                                                                                                                                                                                                                                                                                                       |
| `created_by`    | _Person \| list[_Person] \| None                                                                                     | no       | null    | Who created this primary artifact here, e.g., collected or measured the data, drew the figure, or took the photo, rather than it being produced by the pipeline or obtained from elsewhere. A primary artifact has no upstream source to point at, so naming who produced it is the only way to tell it apart from one whose provenance was never recorded. Each person discloses the generative AI tools they used via ``with_ai``. |
| `imported_from` | _ImportedFromProject \| _ImportedFromUrl \| _ImportedFromDoi \| _ImportedFromGit \| _ImportedFromDescription \| None | no       | null    | Where this came from, if imported.                                                                                                                                                                                                                                                                                                                                                                                                   |

#### `Software`

| Parameter     | Type | Required | Default | Description |
| ------------- | ---- | -------- | ------- | ----------- |
| `title`       | str  | yes      |         |             |
| `path`        | str  | yes      |         |             |
| `description` | str  | yes      |         |             |

#### `Notebook`

A Jupyter notebook.

Unlike the other objects, a notebook entry can be created just to record
which environment it runs in (by `calkit update notebook-env`), so
`title` is optional here.

| Parameter       | Type                                                                                                                 | Required | Default | Description                                                                                                                                                                                                                                                                                      |
| --------------- | -------------------------------------------------------------------------------------------------------------------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `path`          | str                                                                                                                  | yes      |         |                                                                                                                                                                                                                                                                                                  |
| `title`         | str \| None                                                                                                          | no       | null    |                                                                                                                                                                                                                                                                                                  |
| `description`   | str \| None                                                                                                          | no       | null    |                                                                                                                                                                                                                                                                                                  |
| `stage`         | str \| None                                                                                                          | no       | null    |                                                                                                                                                                                                                                                                                                  |
| `environment`   | str \| None                                                                                                          | no       | null    | Name of the environment in which to run this notebook, if it is not part of the pipeline.                                                                                                                                                                                                        |
| `imported_from` | _ImportedFromProject \| _ImportedFromUrl \| _ImportedFromDoi \| _ImportedFromGit \| _ImportedFromDescription \| None | no       | null    | Where this came from, if it was taken from somewhere else. Notebooks are usually written by a project's own authors, so there is no 'calkit import notebook'; this is here so an entry that does say where it came from is kept rather than dropped, and so 'calkit sync import' can refresh it. |

#### `StaticHtmlApp`

An app served as static files, with no backend.

`path` points at the HTML file itself rather than its directory, since
the kind names a file type. The containing directory is the serving root,
so sibling assets are served alongside it, and `index.html` is implied
when a directory is served.

There is no `url` field: for apps a hub serves, the URL is derived from
the project and the app's key, and a value written here could only go
stale.

| Parameter     | Type                   | Required | Default       | Description |
| ------------- | ---------------------- | -------- | ------------- | ----------- |
| `kind`        | Literal['static-html'] | no       | 'static-html' |             |
| `path`        | str                    | yes      |               |             |
| `title`       | str \| None            | no       | null          |             |
| `description` | str \| None            | no       | null          |             |
| `stage`       | str \| None            | no       | null          |             |

#### `ShowcaseFigure`

| Parameter | Type | Required | Default | Description |
| --------- | ---- | -------- | ------- | ----------- |
| `figure`  | str  | yes      |         |             |

#### `ShowcaseText`

| Parameter | Type | Required | Default | Description |
| --------- | ---- | -------- | ------- | ----------- |
| `text`    | str  | yes      |         |             |

#### `ShowcaseMarkdown`

| Parameter  | Type | Required | Default | Description |
| ---------- | ---- | -------- | ------- | ----------- |
| `markdown` | str  | yes      |         |             |

#### `ShowcaseMarkdownFile`

| Parameter       | Type | Required | Default | Description |
| --------------- | ---- | -------- | ------- | ----------- |
| `markdown_file` | str  | yes      |         |             |

#### `ShowcaseYamlFile`

| Parameter     | Type        | Required | Default | Description |
| ------------- | ----------- | -------- | ------- | ----------- |
| `yaml_file`   | str         | yes      |         |             |
| `object_name` | str \| None | no       | null    |             |

#### `ShowcaseNotebook`

| Parameter  | Type | Required | Default | Description |
| ---------- | ---- | -------- | ------- | ----------- |
| `notebook` | str  | yes      |         |             |

#### `ShowcasePublication`

| Parameter     | Type | Required | Default | Description |
| ------------- | ---- | -------- | ------- | ----------- |
| `publication` | str  | yes      |         |             |

#### `ShowcaseApp`

Show an app in the project's showcase, by its key in `apps`.

| Parameter | Type | Required | Default | Description |
| --------- | ---- | -------- | ------- | ----------- |
| `app`     | str  | yes      |         |             |

#### `Subproject`

A smaller project executed as part of this one.

| Parameter     | Type        | Required | Default | Description                                                        |
| ------------- | ----------- | -------- | ------- | ------------------------------------------------------------------ |
| `path`        | str         | yes      |         | Path to the subproject directory, relative to this project's root. |
| `description` | str \| None | no       | null    |                                                                    |

#### `Formula`

| Parameter     | Type                     | Required | Default   | Description |
| ------------- | ------------------------ | -------- | --------- | ----------- |
| `kind`        | Literal['formula']       | no       | 'formula' |             |
| `params`      | FormulaParams            | yes      |           |             |
| `name`        | str \| None              | no       | null      |             |
| `description` | str \| None              | no       | null      |             |
| `inputs`      | list[Input] \| list[str] | yes      |           |             |
| `output`      | Output \| str            | yes      |           |             |

#### `Linear`

Calculation for a simple linear relationship.

| Parameter     | Type                     | Required | Default  | Description |
| ------------- | ------------------------ | -------- | -------- | ----------- |
| `kind`        | Literal['linear']        | no       | 'linear' |             |
| `params`      | LinearParams             | yes      |          |             |
| `name`        | str \| None              | no       | null     |             |
| `description` | str \| None              | no       | null     |             |
| `inputs`      | list[Input] \| list[str] | yes      |          |             |
| `output`      | Output \| str            | yes      |          |             |

#### `LookupTable`

A 1-D lookup table.

| Parameter     | Type                     | Required | Default        | Description |
| ------------- | ------------------------ | -------- | -------------- | ----------- |
| `kind`        | Literal['lookup-table']  | no       | 'lookup-table' |             |
| `params`      | LookupTableParams        | yes      |                |             |
| `name`        | str \| None              | no       | null           |             |
| `description` | str \| None              | no       | null           |             |
| `inputs`      | list[Input] \| list[str] | yes      |                |             |
| `output`      | Output \| str            | yes      |                |             |

#### `OverleafSync`

Configuration for syncing a directory with an Overleaf project.

| Parameter    | Type              | Required | Default | Description                                       |
| ------------ | ----------------- | -------- | ------- | ------------------------------------------------- |
| `url`        | str \| None       | no       | null    | URL of the Overleaf project.                      |
| `sync_paths` | list[str] \| None | no       | null    | Paths synced in both directions with Overleaf.    |
| `push_paths` | list[str] \| None | no       | null    | Paths only pushed to Overleaf, never pulled back. |

#### `RangeIterationParams`

| Parameter | Type         | Required | Default | Description                                    |
| --------- | ------------ | -------- | ------- | ---------------------------------------------- |
| `start`   | int \| float | yes      |         | First value in the range, which is included.   |
| `stop`    | int \| float | yes      |         | Value at which to stop, which is not included. |
| `step`    | int \| float | no       | 1       | Amount by which to increment each value.       |

#### `_Person`

A person credited with producing something in the project.

Extra keys are refused rather than ignored: a mistyped `oricd`, or a
`with_ai` on something that doesn't take one, should say so instead of
vanishing and leaving the author thinking they recorded it.

| Parameter | Type                     | Required | Default | Description                                                                                                                                                                 |
| --------- | ------------------------ | -------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `email`   | str \| None              | no       | null    | Email address of the person.                                                                                                                                                |
| `name`    | str \| None              | no       | null    | Their name, if worth recording here.                                                                                                                                        |
| `with_ai` | str \| list[str] \| None | no       | null    | Generative AI tools this person used, e.g. 'Claude Opus 5'. Recorded against the person rather than the file, so a disclosure can't exist without someone answering for it. |
| `orcid`   | str \| None              | no       | null    | Their ORCID, which identifies them globally rather than only within this project. Accepted bare or as a full URL.                                                           |

#### `_ImportedFromProject`

| Parameter      | Type              | Required | Default | Description                                                                                      |
| -------------- | ----------------- | -------- | ------- | ------------------------------------------------------------------------------------------------ |
| `project`      | str               | yes      |         |                                                                                                  |
| `path`         | str \| None       | no       | null    |                                                                                                  |
| `date`         | date \| None      | no       | null    | When the data was downloaded.                                                                    |
| `git_rev`      | str \| None       | no       | null    | Deprecated; recorded in .calkit/imports.json instead, with the other things a fetch resolves to. |
| `filter_paths` | list[str] \| None | no       | null    |                                                                                                  |
| `description`  | str \| None       | no       | null    | Where it came from, in words, for whatever the other fields can't say.                           |

#### `_ImportedFromUrl`

| Parameter     | Type         | Required | Default | Description                                                                                                         |
| ------------- | ------------ | -------- | ------- | ------------------------------------------------------------------------------------------------------------------- |
| `url`         | str          | yes      |         |                                                                                                                     |
| `date`        | date \| None | no       | null    | When the data was downloaded. Optional: without it, the commit that added this entry says when, to within a commit. |
| `description` | str \| None  | no       | null    | Where it came from, in words, for whatever the other fields can't say.                                              |

#### `_ImportedFromDoi`

Data published under a DOI, which is a citation, not just a link.

Kept apart from a URL so it can be cited and resolved as a DOI rather
than being one more address that happens to start with https.

| Parameter     | Type         | Required | Default | Description                                                                                       |
| ------------- | ------------ | -------- | ------- | ------------------------------------------------------------------------------------------------- |
| `doi`         | str          | yes      |         | The DOI, e.g. 10.5281/zenodo.1234567. A https://doi.org/ or doi: prefix is accepted and stripped. |
| `date`        | date \| None | no       | null    | When the data was downloaded.                                                                     |
| `description` | str \| None  | no       | null    | Where it came from, in words, for whatever the other fields can't say.                            |

#### `_ImportedFromGit`

Data from a Git repo that isn't a Calkit project.

| Parameter     | Type         | Required | Default | Description                                                            |
| ------------- | ------------ | -------- | ------- | ---------------------------------------------------------------------- |
| `git`         | _GitSource   | yes      |         |                                                                        |
| `date`        | date \| None | no       | null    | When the data was downloaded.                                          |
| `description` | str \| None  | no       | null    | Where it came from, in words, for whatever the other fields can't say. |

#### `_ImportedFromDescription`

Data whose origin can be stated but not resolved.

Some things arrive by other means --- emailed by a person, provided
by a company, handed over on a drive. There is no URL, DOI, repo or
project to point at, and recording that in words is better than
recording nothing. Weaker provenance than the others, deliberately:
it says where something came from without saying how to get it again,
so anyone reading it knows they have a name to ask rather than an
address to fetch.

| Parameter     | Type         | Required | Default | Description                                                                                                                                        |
| ------------- | ------------ | -------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `description` | str          | yes      |         | Where it came from, in words, for an origin that can be stated but not resolved, e.g. 'Emailed by someone@example.com' or 'Provided by Acme, Inc.' |
| `date`        | date \| None | no       | null    | When the data was received.                                                                                                                        |

#### `FormulaParams`

| Parameter | Type | Required | Default | Description |
| --------- | ---- | -------- | ------- | ----------- |
| `formula` | str  | yes      |         |             |

#### `Input`

| Parameter     | Type                           | Required | Default | Description |
| ------------- | ------------------------------ | -------- | ------- | ----------- |
| `name`        | str                            | yes      |         |             |
| `description` | str \| None                    | no       | null    |             |
| `dtype`       | Literal['int', 'float', 'str'] | no       | 'float' |             |
| `min`         | int \| float \| None           | no       | null    |             |
| `max`         | int \| float \| None           | no       | null    |             |

#### `Output`

| Parameter     | Type                           | Required | Default | Description |
| ------------- | ------------------------------ | -------- | ------- | ----------- |
| `name`        | str                            | yes      |         |             |
| `description` | str \| None                    | no       | null    |             |
| `dtype`       | Literal['int', 'float', 'str'] | no       | 'float' |             |
| `template`    | str \| None                    | no       | null    |             |

#### `LinearParams`

| Parameter | Type             | Required | Default | Description |
| --------- | ---------------- | -------- | ------- | ----------- |
| `coeffs`  | dict[str, float] | yes      |         |             |
| `offset`  | float            | no       | 0.0     |             |

#### `LookupTableParams`

| Parameter  | Type                                             | Required | Default       | Description |
| ---------- | ------------------------------------------------ | -------- | ------------- | ----------- |
| `x_values` | list[float]                                      | yes      |               |             |
| `y_values` | list[float]                                      | yes      |               |             |
| `method`   | Literal['floor', 'ceil', 'round', 'interpolate'] | no       | 'interpolate' |             |

#### `_GitSource`

| Parameter  | Type        | Required | Default | Description                                                                                                                                                                                                                                                                                                                                         |
| ---------- | ----------- | -------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `repo_url` | str         | yes      |         | Clone URL of the repo the data came from.                                                                                                                                                                                                                                                                                                           |
| `rev`      | str \| None | no       | null    | Deprecated; the commit an import resolved to is recorded in .calkit/imports.json, which is committed alongside it. This file says what to follow, which a person writes; that one says where following it led, which the tool works out. Still read for entries written before the split, and moved across the next time 'calkit sync import' runs. |
| `path`     | str \| None | no       | null    | Path within that repo, if it isn't the whole thing.                                                                                                                                                                                                                                                                                                 |
| `ref`      | str \| None | no       | null    | Branch, tag, or commit to follow when refreshing this, e.g., 'main'. Optional: an entry that names none is refreshed from the repo's default branch. 'rev' still records the commit actually fetched, so the entry says both what it tracks and what it got.                                                                                        |

<!-- AUTO-GENERATED: CALKIT-YAML-KEYS:END -->
