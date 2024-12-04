"""Core functionality."""

from __future__ import annotations

import glob
import json
import logging
import os
import pickle

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _timezone

    UTC = _timezone.utc

from datetime import datetime

from typing import Literal

import ruamel.yaml
from git import Repo
from git.exc import InvalidGitRepositoryError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__package__)

ryaml = ruamel.yaml.YAML()
ryaml.indent(mapping=2, sequence=4, offset=2)
ryaml.preserve_quotes = True
ryaml.width = 70


def find_project_dirs(relative=False, max_depth=3) -> list[str]:
    """Find all Calkit project directories."""
    if relative:
        start = ""
    else:
        start = os.path.expanduser("~")
    res = []
    for i in range(max_depth):
        pattern = os.path.join(start, *["*"] * (i + 1), "calkit.yaml")
        res += glob.glob(pattern)
        # Check GitHub documents for users who use GitHub Desktop
        pattern = os.path.join(
            start, "*", "GitHub", *["*"] * (i + 1), "calkit.yaml"
        )
        res += glob.glob(pattern)
    final_res = []
    for ck_fpath in res:
        path = os.path.dirname(ck_fpath)
        # Make sure this path is a Git repo
        try:
            Repo(path)
        except InvalidGitRepositoryError:
            continue
        final_res.append(path)
    return final_res


def load_calkit_info(
    wdir=None, process_includes: bool | str | list[str] = False
) -> dict:
    """Load Calkit project information.

    Parameters
    ----------
    wdir : str
        Working directory. Defaults to current working directory.
    process_includes: bool, string or list of strings
        Whether or not to process any '_include' keys for a given kind of
        object. If a string is passed, only process includes for that kind.
        Similarly, if a list of strings is passed, only process those kinds.
        If True, process all default kinds.
    """
    info = {}
    fpath = "calkit.yaml"
    if wdir is not None:
        fpath = os.path.join(wdir, fpath)
    if os.path.isfile(fpath):
        with open(fpath) as f:
            info = ryaml.load(f)
    # Check for any includes, i.e., entities with an _include key, for which
    # we should merge in another file
    default_includes_enabled = ["environments", "procedures"]
    if process_includes:
        if isinstance(process_includes, bool):
            includes_enabled = default_includes_enabled
        elif isinstance(process_includes, str):
            includes_enabled = [process_includes]
        elif isinstance(process_includes, list):
            includes_enabled = process_includes
        for kind in includes_enabled:
            if kind in info:
                for obj_name, obj in info[kind].items():
                    if "_include" in obj:
                        include_fpath = obj.pop("_include")
                        with open(include_fpath) as f:
                            include_data = ryaml.load(f)
                        info[kind][obj_name] |= include_data
    return info


def utcnow(remove_tz=True) -> datetime:
    """Return now in UTC, optionally stripping timezone information."""
    dt = datetime.now(UTC)
    if remove_tz:
        dt = dt.replace(tzinfo=None)
    return dt


NOTEBOOK_STAGE_OUT_FORMATS = ["pickle", "parquet", "json", "yaml", "csv"]


def get_notebook_stage_dir(stage_name: str) -> str:
    return os.path.join(".calkit", "notebook-stages", stage_name)


def get_notebook_stage_script_path(stage_name: str) -> str:
    return os.path.join(get_notebook_stage_dir(stage_name), "script.py")


def get_notebook_stage_out_dir(stage_name: str) -> str:
    return os.path.join(get_notebook_stage_dir(stage_name), "outs")


def get_notebook_stage_out_path(
    stage_name: str,
    out_name: str,
    fmt: Literal["pickle", "parquet", "json", "yaml", "csv"] = "pickle",
) -> str:
    if fmt not in NOTEBOOK_STAGE_OUT_FORMATS:
        raise ValueError(f"Invalid output format '{fmt}'")
    return os.path.join(
        get_notebook_stage_out_dir(stage_name), f"{out_name}.{fmt}"
    )


def load_notebook_stage_out(
    stage_name: str,
    out_name: str,
    fmt: Literal["pickle", "parquet", "json", "yaml", "csv"] = "pickle",
    engine: Literal["pandas", "polars"] | None = None,
):
    fpath = get_notebook_stage_out_path(stage_name, out_name, fmt=fmt)
    if fmt in ["pickle", "json", "yaml"] and engine is not None:
        raise ValueError(
            f"Engine '{engine}' not compatible with format '{fmt}'"
        )
    if fmt == "pickle":
        with open(fpath, "rb") as f:
            return pickle.load(f)
    elif fmt == "yaml":
        with open(fpath) as f:
            return ryaml.load(f)
    elif fmt == "json":
        with open(fpath) as f:
            return json.load(f)
    elif fmt == "csv" and engine == "pandas":
        import pandas as pd

        return pd.read_csv(fpath)
    elif fmt == "csv" and engine == "polars":
        import polars as pl

        return pl.read_csv(fpath)
    elif fmt == "parquet" and engine == "pandas":
        import pandas as pd

        return pd.read_parquet(fpath)
    elif fmt == "parquet" and engine == "polars":
        import polars as pl

        return pl.read_parquet(fpath)
    raise ValueError(f"Unsupported format '{fmt}' for engine '{engine}'")


def save_notebook_stage_out(
    obj,
    stage_name: str,
    out_name: str,
    fmt: Literal["pickle", "parquet", "json", "yaml", "csv"] = "pickle",
    engine: Literal["pandas", "polars"] | None = None,
):
    fpath = get_notebook_stage_out_path(stage_name, out_name, fmt=fmt)
    dirname = os.path.dirname(fpath)
    os.makedirs(dirname, exist_ok=True)
    if fmt in ["pickle", "json", "yaml"] and engine is not None:
        raise ValueError(
            f"Engine '{engine}' not compatible with format '{fmt}'"
        )
    if fmt == "pickle":
        with open(fpath, "wb") as f:
            pickle.dump(obj, f)
    elif fmt == "json":
        with open(fpath, "w") as f:
            json.dump(obj, f)
    elif fmt == "yaml":
        with open(fpath, "w") as f:
            ryaml.dump(obj, f)
    elif fmt == "csv" and engine == "pandas":
        obj.to_csv(fpath)
    elif fmt == "parquet" and engine == "pandas":
        obj.to_parquet(fpath)
    elif fmt == "csv" and engine == "polars":
        obj.write_csv(fpath)
    elif fmt == "parquet" and engine == "polars":
        obj.write_parquet(fpath)
    else:
        raise ValueError(f"Unsupported format '{fmt}' for engine '{engine}'")
