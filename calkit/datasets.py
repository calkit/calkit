"""Functionality for working with datasets."""

from __future__ import annotations

import base64
import io
from typing import Literal

import calkit
import calkit.config

DEFAULT_ENGINE = calkit.config.read().dataframe_engine


def _get_df_lib(engine: str):
    if engine == "pandas":
        import pandas

        return pandas
    elif engine == "polars":
        import polars

        return polars
    else:
        raise ValueError("Unknown engine")


def list_datasets() -> list[dict]:
    """Read the Calkit metadata file and list out our datasets."""
    ck_info = calkit.load_calkit_info(as_pydantic=False, process_includes=True)
    return ck_info.get("datasets", [])


def read_dataset(
    path: str,
    engine: Literal["pandas", "polars"] = DEFAULT_ENGINE,
):
    """Read a dataset from a path.

    Path can include the project owner/name like

        someone/some-project:my-data-folder/data.csv

    When a project is set via the ``CALKIT_PROJECT`` environmental variable,
    we will use the API to fetch the data.
    """

    def load_from_fobj(fobj, path: str):
        """Read from a filelike object or path."""
        if path.endswith(".csv"):
            return _get_df_lib(engine).read_csv(fobj)
        elif path.endswith(".parquet"):
            return _get_df_lib(engine).read_parquet(fobj)

    project, path = calkit.project_and_path_from_path(path)
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
        elif (url := resp.get("url")) is not None:
            return load_from_fobj(url, path=path)
        else:
            raise ValueError("No content or URL returned from API")
    # Project is None, so let's just read a local file
    return load_from_fobj(path, path)
