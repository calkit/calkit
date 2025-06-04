"""Core functionality."""

from __future__ import annotations

import base64
import csv
import glob
import json
import logging
import os
import pickle
import re
import subprocess

import requests

from calkit.models import ProjectStatus

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

from calkit.models import ProjectInfo

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
    wdir: str | None = None,
    process_includes: bool | str | list[str] = False,
) -> dict:
    """Load Calkit project information as a dictionary.

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
                        if wdir is not None:
                            include_fpath = os.path.join(wdir, include_fpath)
                        if os.path.isfile(include_fpath):
                            with open(include_fpath) as f:
                                include_data = ryaml.load(f)
                            info[kind][obj_name] |= include_data
    return info


def load_calkit_info_object(
    wdir: str | None = None,
    process_includes: bool | str | list[str] = False,
) -> ProjectInfo:
    """Load Calkit project information as a ``ProjectInfo`` object."""
    return ProjectInfo.model_validate(
        load_calkit_info(wdir=wdir, process_includes=process_includes)
    )


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


def make_readme_content(
    project_name: str, project_title: str, project_description: str | None
) -> str:
    """Create Markdown content for a Calkit project README."""
    txt = f"# {project_title}\n\n"
    if project_description is not None:
        txt += f"\n{project_description}\n"
    return txt


def check_dep_exists(
    name: str, kind: Literal["app", "env-var", "calkit-config"] = "app"
) -> bool:
    """Check that a dependency exists.

    TODO: Add version checking.
    """
    if kind == "env-var":
        return name in os.environ
    if kind == "calkit-config":
        import calkit.config

        cfg = calkit.config.read()
        return getattr(cfg, name, None) is not None
    if name == "calkit":
        return True
    cmd = [name]
    # Executables with non-conventional CLIs
    if name == "matlab":
        cmd.append("-help")
    else:
        # Fall back to simply calling ``--version``
        cmd.append("--version")
    try:
        subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except FileNotFoundError:
        return False


def check_system_deps(wdir: str | None = None) -> None:
    """Check that the dependencies declared in a project's ``calkit.yaml`` file
    exist.
    """
    ck_info = load_calkit_info(wdir=wdir)
    deps = ck_info.get("dependencies", [])
    if "git" not in deps:
        deps.append("git")
    # Infer dependencies from environment types
    for _, env in ck_info.get("environments", {}).items():
        kind = env.get("kind")
        if kind in ["docker", "uv", "conda", "pixi"] and kind not in deps:
            deps.append(kind)
        elif kind == "uv-venv" and "uv" not in deps:
            deps.append("uv")
        elif kind == "renv" and "Rscript" not in deps:
            deps.append("Rscript")
        elif kind == "matlab":
            if "docker" not in deps:
                deps.append("docker")
            deps.append({"MATLAB_LICENSE_SERVER": {"kind": "env-var"}})
    for dep in deps:
        if isinstance(dep, dict):
            keys = list(dep.keys())
            if len(keys) != 1:
                raise ValueError(f"Malformed dependency: {dep}")
            dep_name = keys[0]
            dep_kind = dep[dep_name].get("kind", "app")
        else:
            dep_name = re.split("[=<>]", dep)[0]
            dep_kind = "app"
        if not check_dep_exists(dep_name, dep_kind):
            raise ValueError(f"{dep_kind} '{dep_name}' not found")


def project_and_path_from_path(path: str) -> tuple:
    """Split a path into project and path, respecting the ``CALKIT_PROJECT``
    environmental variable if set.

    For example, a path like

        someone/some-project:some/path/to/file.png

    will return

        (someone/some-project, some/path/to/file.png)
    """
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
    return project, path


def read_file(path: str, as_bytes: bool | None = None) -> str | bytes:
    """Read file content from path, which can optionally include a project
    identifier, which if specified will indicate we should read from the API.
    """
    project, path = project_and_path_from_path(path)
    if as_bytes is None:
        _, ext = os.path.splitext(path)
        as_bytes = ext in [
            ".png",
            ".jpg",
            ".gif",
            ".jpeg",
            ".pdf",
            ".xlsx",
            ".docx",
        ]
    if project is not None:
        import calkit.cloud

        if len(project.split("/")) != 2:
            raise ValueError("Invalid project identifier (too many slashes)")
        resp = calkit.cloud.get(f"/projects/{project}/contents/{path}")
        # If the response has a content key, that is a base64 encoded string
        if (content := resp.get("content")) is not None:
            # Load the content appropriately
            content_bytes = base64.b64decode(content)
            if as_bytes:
                return content_bytes
            else:
                return content_bytes.decode()
        # If the response has a URL, we can fetch from that directly
        elif (url := resp.get("url")) is not None:
            resp2 = requests.get(url)
            resp2.raise_for_status()
            if as_bytes:
                return resp2.content
            else:
                return resp2.text
        else:
            raise ValueError("No content or URL returned from API")
    # Project is None, so let's just read a local file
    with open(path, mode="rb" if as_bytes else "r") as f:
        return f.read()


def get_size(path: str):
    """Get the size of a path in bytes.

    This differs from ``os.path.getsize`` in that it is recursive.
    """
    if os.path.isfile(path):
        return os.path.getsize(path)
    # From https://stackoverflow.com/a/1392549/2284865
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # skip if it is symbolic link
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)
    return total_size


def to_kebab_case(str) -> str:
    """Convert a string to kebab-case."""
    return re.sub(r"[-_/,\.\ ]", "-", str.lower())


def get_project_status_history(
    wdir: str | None = None, as_pydantic=True
) -> list[ProjectStatus] | list[dict]:
    statuses = []
    fpath = os.path.join(".calkit", "status.csv")
    if wdir is not None:
        fpath = os.path.join(wdir, fpath)
    if os.path.isfile(fpath):
        with open(fpath) as f:
            reader = csv.reader(f)
            next(reader, None)  # Skip header row
            for line in reader:
                ts, status, message = line
                ts = datetime.fromisoformat(ts)
                obj = ProjectStatus(
                    timestamp=ts,
                    status=status,  # type: ignore
                    message=message,
                )
                if not as_pydantic:
                    obj = obj.model_dump()
                statuses.append(obj)
    return statuses


def get_latest_project_status(wdir: str | None = None) -> ProjectStatus | None:
    statuses = get_project_status_history(wdir=wdir)
    if statuses:
        return statuses[-1]  # type: ignore


def detect_project_name(wdir: str | None = None) -> str:
    """Detect a Calkit project owner and name."""
    ck_info = load_calkit_info(wdir=wdir)
    name = ck_info.get("name")
    owner = ck_info.get("owner")
    if name is None or owner is None:
        try:
            url = Repo(path=wdir).remote().url
        except ValueError:
            raise ValueError("No Git remote set with name 'origin'")
        from_url = url.split("github.com")[-1][1:].removesuffix(".git")
        owner_name, project_name = from_url.split("/")
    if name is None:
        name = project_name
    if owner is None:
        owner = owner_name
    return f"{owner}/{name}"
