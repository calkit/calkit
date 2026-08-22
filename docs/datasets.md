# Datasets

If your research project produces a dataset,
you can indicate it as such to make it easy for others to reuse in their
own project.
These are listed in the `datasets` section of the project's `calkit.yaml` file.

A dataset is identified by its path in the project repo,
and this path can be a folder.
For example:

```yaml
# In calkit.yaml
datasets:
  - path: data/raw-data.csv
    title: Raw data
    description: This is the raw data.
```

The purpose of the datasets section is to list those that might be useful
to others in their project and to note which were not produced as part of
yours, i.e., they were imported from elsewhere.

## Importing or reusing a dataset from another project

A dataset can be imported with the CLI like:

```sh
calkit import dataset {owner_name}/{project_name}/{path} {local_path}
```

If this dataset is tracked with DVC,
a new DVC remote will be created to pull it into your project.
For datasets on the Calkit hub,
this means the data will not be duplicated there.

## Declaring an imported dataset

If you imported a dataset yourself from a web URL, DOI, or a Git repo,
say so like:

```yaml
datasets:
  # From a website
  - path: data/from-elsewhere.csv
    imported_from:
      url: https://website.org/data/something.csv
      date: 2021-01-01 # Optional
  # From a DOI, e.g., Figshare or Zenodo
  - path: data/from-archive.csv
    imported_from:
      doi: 10.5281/zenodo.1234567
  # From a Git repo
  - path: data/from-git.csv
    imported_from:
      git:
        repo_url: https://github.com/someone/something.git
        path: data/their-dataset-name.csv
        rev: 4031e49efbea3be3b6b10e66f30d7cff6dfc60cc
```

## Declaring a dataset you collected yourself

If you manually collected a dataset, i.e., it is a primary artifact,
that should be declared explicitly like:

```yaml
datasets:
  - path: data/raw.csv
    collected_by:
      email: me@myorg.edu
      orcid: 0000-0002-1825-0097 # Optional
```

`collected_by` can be a list, since data is usually collected by more than
one person, and each entry carries its own identifiers:

```yaml
datasets:
  - path: data/raw.csv
    collected_by:
      - email: me@myorg.edu
        orcid: 0000-0002-1825-0097
      - orcid: 0000-0001-5109-3700
      - email: acolleague@elsewhere.edu
        name: A Colleague
```

Each person needs an email or an ORCID, or both. A name on its own doesn't
say which of the several people with that name this is, so credit rests on
something resolvable. An ORCID is the better of the two, since it identifies
someone beyond this one project, and it's stored as the full
`https://orcid.org/...` URL whether you write it that way or not. Its last
character is a check digit, so a mistyped one is refused rather than
recorded.

A DOI can be written bare, as `doi:10.5281/zenodo.1234567`, or as the
`https://doi.org/...` URL; it's stored bare. A `collected_by` and an
`imported_from` on the same dataset is an error, since data is either
something you produced or something you got.

## Entering data by hand

Some data is typed in rather than downloaded: readings off an instrument, a
tally, a table copied out of a paper. On the hub, the dataset dialog's
"I'll type it in now" option opens a small grid for exactly this. Paste a
block from a spreadsheet to fill many cells at once. Saving writes a CSV at
the path you choose, tracks it with DVC, and records you as its collector,
so it gets the same provenance as any other primary data:

```yaml
datasets:
  - path: data/readings.csv
    title: Bench readings
    description: Voltage and current at each load step, 2026-08-20
    collected_by:
      - email: me@myorg.edu
```

Treat it the way you would a lab notebook page. If the grid was a stand-in
while real data was on its way, replace the file rather than leaving the
placeholder declared as collected data.

For attributing files that aren't datasets, and for disclosing generative
AI, see [provenance](provenance.md).
