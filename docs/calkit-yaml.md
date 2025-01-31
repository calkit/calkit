# The `calkit.yaml` file

The `calkit.yaml` file serves as a small "database"
for the project's important metadata, which includes its:

- Global or system-level dependencies
  (applications, libraries, environmental variables)
- Questions the project seeks to answer
- Environments
- [Datasets](datasets.md)
- Figures
- Publications (journal articles, conference papers, presentations, posters)
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
shown on the project homepage on the Calkit Cloud web app.
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
