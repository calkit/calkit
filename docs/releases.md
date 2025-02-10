# Releasing/archiving projects and artifacts

When the project has reached an important milestone, e.g.,
a journal article is ready for submission,
a release should be created to archive the relevant artifacts
with a persistent identifier like a digital object identifier (DOI).
The archived release should then be cited in the article
so readers can reproduce the results.

Calkit can archive whole projects or individual artifacts to
[Zenodo](https://zenodo.org).

TODO: Set token or connect account on calkit.io?

To do so, create a new release with:

```sh
calkit new release --name submitted-paper
```

By default, the entire project will be released
and added to the project references.
A Git tag will be created.
Any archived files will be indexed by their MD5 checksum in
`.calkit/archive-urls.yaml`.
A `CITATION.cff` file will also be created or updated,
to indicate to others
how to cite the project materials.

To release only one artifact, e.g., a dataset or publication,
execute:

```sh
calkit new release \
    --name my-release-name \
    --type publication \
    path/to/the/publication.pdf
```
