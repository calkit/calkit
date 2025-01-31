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

## Importing or reusing a dataset from another project

A dataset can be imported with the CLI like:

```sh
calkit import dataset {owner_name}/{project_name}/{path} {local_path}
```

If this dataset is tracked with DVC,
a new DVC remote will be created to pull it into your project.
For datasets in the Calkit Cloud,
this means the data will not be duplicated there.
