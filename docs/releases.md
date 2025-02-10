# Releasing/archiving projects and artifacts

When the project has reached an important milestone, e.g.,
a journal article is ready for submission,
a release should be created to archive the relevant artifacts
with a persistent identifier like a digital object identifier (DOI).
The archived release should then be cited in the article
so readers can follow the citation back to the project
files in order to reproduce or reuse the results.

## Integrating with Zenodo

Calkit can archive whole projects or individual artifacts to
[Zenodo](https://zenodo.org).
To enable this functionality,
you will either need to create a Zenodo personal access token (PAT) and set it
in your machine's Calkit config or as an environmental variable.

If you don't already have a Zenodo PAT,
first create one in your
[Zenodo account settings](https://zenodo.org/account/settings/applications/),
then call:

```sh
calkit config set zenodo_token {paste Zenodo token here}
```

Alternatively,
you may set your token as either the `ZENODO_TOKEN` or `CALKIT_ZENODO_TOKEN`
environmental variable.

## Creating a release of the project

To create a new release of the entire project, execute:

```sh
calkit new release --name submitted-paper
```

By default, the entire project will be released
and added to the project references.
All files except those ignored by Git/DVC will be uploaded.
A Git tag will be created and a release will be added on GitHub.
Any archived files will be indexed by their MD5 checksum in
`.calkit/archive-urls.yaml`.
A `CITATION.cff` file will also be created or updated,
to indicate to others
how to cite the project materials.

The release will also be added to the project's default
[references collection](references.md).
If none exist, one will be created at the default location (`references.bib`).

## Releasing other types of artifacts individually

To release only one artifact, e.g., a dataset or publication,
execute:

```sh
calkit new release \
    --name my-release-name \
    --type publication \
    path/to/the/publication.pdf
```
