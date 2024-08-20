"""Functionality for working with datasets."""

from typing import Literal, Union

import pandas as pd
import polars as pl

import calkit.config

DEFAULT_ENGINE = calkit.config.read().dataframe_engine


def list_data():
    """Read the Calkit metadata file and list out our datasets."""
    pass


def read_data(
    path: str, engine: Literal["pandas", "polars"] = DEFAULT_ENGINE
) -> Union[pd.DataFrame, pl.DataFrame]:
    """Read (tabular) data from dataset with path ``path`` and return a
    DataFrame.

    If the dataset doesn't exist locally, but is a DVC object, download it
    first.

    If the dataset path includes a user and project name, we add it to the
    project as an imported dataset?
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
