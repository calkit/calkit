"""Functionality for working with datasets.

Since the dependencies here are optional, we need to ensure this isn't imported
by default, or otherwise ensure ``import calkit`` works when the data
dependencies are not installed.
"""

from __future__ import annotations

import base64
import io
import os
from typing import Literal, Union

import pandas as pd
import polars as pl

import calkit
import calkit.config

DEFAULT_ENGINE = calkit.config.read().dataframe_engine


def list_data():
    """Read the Calkit metadata file and list out our datasets."""
    pass


def load_dataset(
    path: str,
    engine: Literal["pandas", "polars"] = DEFAULT_ENGINE,
) -> pl.DataFrame | pd.DataFrame:
    """Load a project's dataset.

    Path can include the project owner/name like

        someone/some-project:my-data-folder/data.csv

    When a project is set via the ``CALKIT_PROJECT`` environmental variable,
    we will use the API to fetch the data.
    """

    def load_from_fobj(fobj, path: str):
        """Read from a filelike object or path."""
        if path.endswith(".csv"):
            if engine == "pandas":
                return pd.read_csv(fobj)
            elif engine == "polars":
                return pl.read_csv(fobj)
        elif path.endswith(".parquet"):
            if engine == "pandas":
                return pd.read_parquet(fobj)
            elif engine == "polars":
                return pl.read_parquet(fobj)

    path_split = path.split(":")
    if len(path_split) == 2:
        project = path_split[0]
        path = path_split[1]
    elif len(path_split) == 1:
        project = None
    else:
        raise ValueError("Path has too many colons in it")
    if project is None:
        project = os.getenv("CALKIT_PROJECT")
    if project is not None:
        if len(project.split("/")) != 2:
            raise ValueError("Invalid project identifier (too many slashes)")
        resp = calkit.cloud.get(f"/projects/{project}/contents/{path}")
        # If the response has a content key, that is a base64 encoded string
        if (content := resp.get("content")) is not None:
            # Load the content appropriately
            content_bytes = base64.b64decode(content)
            return load_from_fobj(io.BytesIO(content_bytes), path=path)
        # If the response has a URL, we can fetch from that directly
        elif (url:= resp.get("url")) is not None:
            return load_from_fobj(url, path=path)
        else:
            raise ValueError("No content or URL returned from API")
    # Project is None, so let's just read a local file
    return load_from_fobj(path, path)


def read_data(
    path: str, engine: Literal["pandas", "polars"] = DEFAULT_ENGINE
) -> Union[pd.DataFrame, pl.DataFrame]:
    """Read (tabular) data from dataset with path ``path`` and return a
    DataFrame.

    If the dataset doesn't exist locally, but is a DVC object, download it
    first.

    If the dataset path includes a user and project name, we add it to the
    project as an imported dataset, and therefore DVC import it?

    For example: someuser/someproject:data/somefile.parquet

    We can run a DVC import command if it needs to be imported. We will need to
    find the Git repo and path within it? Maybe we should require an explicit
    import of the data.
    """
    pass


def write_data(
    data: Union[pd.DataFrame, pl.DataFrame],
    path: str,
    filename: str | None = None,
    commit=False,
):
    """Write ``data`` to the dataset with path ``path``.

    If the dataset path is a directory, the filename must be specified.

    If the path is not a Calkit dataset, it will be created.

    If ``commit`` is specified, create a commit for the dataset update.
    """
    pass
