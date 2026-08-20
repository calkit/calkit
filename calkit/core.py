"""Core functionality."""

from __future__ import annotations

import base64
import csv
import glob
import hashlib
import json
import logging
import os
import pickle
import platform
import re
import socket
import subprocess
import sys
import threading
import uuid
import warnings
from os import PathLike

import calkit

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _timezone

    UTC = _timezone.utc

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from calkit.models import ProjectInfo, ProjectStatus

import ruamel.yaml

logger = logging.getLogger(__package__)
logger.setLevel(logging.INFO)


class _ThreadLocalYAML(threading.local):
    """Holds one configured ruamel ``YAML`` per thread.

    A ``YAML`` instance carries scanner, parser and composer state for the
    duration of a load, so two threads sharing one interleave their parses
    and corrupt each other. The symptom is not a clean failure: a perfectly
    valid file comes back as a ``ParserError`` or ``ComposerError`` pointing
    at a random line, an ``IndexError`` from the scanner, or an internal
    ``AttributeError`` that escapes the usual YAML error handling entirely.

    The CLI is single-threaded and never hit this, but the hub calls into
    ``calkit`` from a request threadpool, where concurrent reads of the same
    calkit.yaml made project pages intermittently 500 or report a project as
    having no metadata at all.
    """

    def __init__(self) -> None:
        self.yaml = ruamel.yaml.YAML()
        self.yaml.indent(mapping=2, sequence=4, offset=2)
        self.yaml.preserve_quotes = True
        self.yaml.width = 70


_yaml_local = _ThreadLocalYAML()


class _ThreadLocalYAMLProxy:
    """Forwards to the calling thread's ``YAML``.

    Keeps ``ryaml`` usable as the module-level object it has always been,
    so no call site has to know about any of this.
    """

    def __getattr__(self, name: str) -> Any:
        return getattr(_yaml_local.yaml, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(_yaml_local.yaml, name, value)

    def dump(self, data: Any, stream: Any = None, **kwargs: Any) -> Any:
        """Dump YAML, dropping the space ruamel leaves before a fold.

        When wrapping a long value, ruamel writes the space that separates
        two words and then breaks the line, leaving it at the end. The
        space is redundant---a line break in a plain scalar already reads
        as one---but every whitespace-trimming tool strips it and Calkit
        writes it back, so the two take turns rewriting the same file.

        It is not redundant in a block scalar, where trailing spaces are
        content. Rather than trying to tell the cases apart while
        emitting, the cleaned text is parsed back and only used if it
        still means the same thing.
        """
        import io

        yaml = _yaml_local.yaml
        if stream is None:
            return yaml.dump(data, stream, **kwargs)
        buf = io.StringIO()
        yaml.dump(data, buf, **kwargs)
        text = buf.getvalue()
        if " \n" in text:
            cleaned = "".join(
                line.rstrip() + "\n" for line in text.splitlines()
            )
            try:
                if yaml.load(cleaned) == yaml.load(text):
                    text = cleaned
            except Exception:
                pass
        stream.write(text)
        return None


ryaml = _ThreadLocalYAMLProxy()

try:
    # libyaml-backed loader, many times faster than the pure-Python one.
    # PyYAML ships prebuilt wheels with libyaml on every platform we target,
    # so this is the normal path; the fallback keeps a source install or an
    # exotic build working, just slower.
    from yaml import CSafeLoader as _YamlLoader
except ImportError:  # pragma: no cover - depends on the libyaml build
    from yaml import SafeLoader as _YamlLoader


def _load_yaml_readonly(stream: Any) -> Any:
    """Parse YAML with the C loader, for data we never write back."""
    import yaml

    return yaml.load(stream, Loader=_YamlLoader)


# Constants for version control auto-ignore
AUTO_IGNORE_SUFFIXES = [
    ".DS_Store",
    ".env",
    ".pyc",
    ".synctex.gz",
    ".auxlock",
    ".ipynb_checkpoints",
]
AUTO_IGNORE_PATHS = [os.path.join(".dvc", "config.local")]
AUTO_IGNORE_PREFIXES = [
    ".venv",
    "__pycache__",
    ".ipynb_checkpoints",
    ".calkit/overleaf/",
]
# Constants for version control auto-add to DVC
DVC_EXTENSIONS = [
    ".png",
    ".jpeg",
    ".jpg",
    ".gif",
    ".h5",
    ".parquet",
    ".pickle",
    ".mp4",
    ".avi",
    ".webm",
    ".pdf",
    ".xlsx",
    ".docx",
    ".pptx",
    ".xls",
    ".doc",
    ".ppt",
    ".nc",
    ".nc4",
    ".zarr",
]
DVC_SIZE_THRESH_BYTES = 5_000_000


def echo(message: str) -> None:
    """Print a message safely, replacing unencodable characters
    (e.g., emoji).
    """
    import typer

    enc = sys.stdout.encoding or "utf-8"
    typer.echo(message.encode(enc, errors="replace").decode(enc))


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
            calkit.git.get_repo(path)
        except calkit.git.InvalidGitRepositoryError:
            continue
        final_res.append(path)
    return final_res


def load_calkit_info(
    wdir: str | PathLike | None = None,
    read_only: bool = False,
) -> dict:
    """Load Calkit project information as a dictionary.

    Parameters
    ----------
    wdir : str
        Working directory. Defaults to current working directory.
    read_only: bool
        Parse with the C-backed loader instead of ruamel's round-trip
        parser, which is roughly 15x faster (~5 ms versus ~78 ms on a 42 KB
        calkit.yaml). Key order is preserved either way, since the loader
        builds plain dicts and those keep insertion order. What is lost is
        everything a faithful rewrite needs: comments, quoting style and
        anchors. Only pass True when the result will not be written back.
    """
    from ruamel.yaml.comments import CommentedMap

    info: dict = {}
    txt = ""
    fpath = "calkit.yaml"
    if wdir is not None:
        fpath = os.path.join(wdir, fpath)
    if os.path.isfile(fpath):
        # Always read as UTF-8; on Windows the default open() encoding is
        # cp1252, which mangles non-ASCII content (e.g., Greek letters).
        with open(fpath, encoding="utf-8") as f:
            txt = f.read()
        info = _load_yaml_readonly(txt) if read_only else ryaml.load(txt)
    if info is None:
        # A file holding nothing but comments parses as None, and returning a
        # plain dict here would drop them the next time it's written back.
        # That's the file ``calkit init`` creates: only the schema modeline,
        # which would then vanish on the project's first ``calkit new``.
        info = CommentedMap()
        comment = "\n".join(
            line.lstrip().removeprefix("#").strip()
            for line in txt.splitlines()
            if line.lstrip().startswith("#")
        )
        if comment and not read_only:
            info.yaml_set_start_comment(comment)
    return info


def save_calkit_info(
    info: dict,
    wdir: str | PathLike | None = None,
) -> None:
    """Save Calkit project information to ``calkit.yaml``."""
    fpath = "calkit.yaml"
    if wdir is not None:
        fpath = os.path.join(wdir, fpath)
    # Always write as UTF-8; on Windows the default open() encoding is cp1252,
    # which mangles non-ASCII content (e.g., Greek letters) into mojibake.
    with open(fpath, "w", encoding="utf-8") as f:
        ryaml.dump(info, f)


def load_calkit_info_object(wdir: str | None = None) -> ProjectInfo:
    """Load Calkit project information as a ``ProjectInfo`` object."""
    from calkit.models import ProjectInfo

    return ProjectInfo.model_validate(load_calkit_info(wdir=wdir))


def utcnow(remove_tz=True) -> datetime:
    """Return now in UTC, optionally stripping timezone information."""
    dt = datetime.now(UTC)
    if remove_tz:
        dt = dt.replace(tzinfo=None)
    return dt


LOCAL_DIR = ".calkit/local"


def ensure_local_dir(wdir: str | None = None) -> str:
    """Ensure the gitignored ``.calkit/local`` directory exists; return it.

    Everything under ``.calkit/local`` is private to the machine and kept out
    of version control via a ``*`` .gitignore.
    """
    base = os.path.join(wdir, LOCAL_DIR) if wdir else LOCAL_DIR
    os.makedirs(base, exist_ok=True)
    gitignore = os.path.join(base, ".gitignore")
    if not os.path.isfile(gitignore):
        with open(gitignore, "w") as f:
            f.write("*\n")
    return base


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
    name: str,
    kind: Literal["app", "env-var", "calkit-config"] = "app",
    system_info: dict | None = None,
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
    if system_info is not None and system_info.get(f"{name}_version"):
        return True
    # Conda and mamba are frequently installed but not on the PATH (most
    # commonly on Windows), so search their typical install locations
    # rather than relying on the bare name being directly executable.
    if name in ("conda", "mamba"):
        from calkit.conda import find_conda_exe, find_mamba_exe

        exe = find_conda_exe() if name == "conda" else find_mamba_exe()
        return exe is not None
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


def system_property_requirement_kinds() -> dict[str, str]:
    """Requirement kinds that name a machine property, and their info keys.

    These constrain something about the machine rather than requiring a
    thing to be present, so they carry no name: ``cpu-count`` is the whole
    identity of the entry. The values are the keys
    :func:`get_system_info` reports them under.
    """
    from typing import get_args

    from calkit.environments import SYSTEM_LOCK_PROPERTIES
    from calkit.models.core import SystemNumberProperty, SystemValueProperty

    props = list(get_args(SystemNumberProperty)) + list(
        get_args(SystemValueProperty)
    )
    return {prop: SYSTEM_LOCK_PROPERTIES[prop] for prop in props}


def _numeric_property_kinds() -> tuple[str, ...]:
    from typing import get_args

    from calkit.models.core import SystemNumberProperty

    return get_args(SystemNumberProperty)


# Whether the old key's deprecation has already been mentioned. Reading
# the requirements happens several times in one command -- the preflight
# check, the env-var resolution, the environment build -- and a project is
# only asked to rename the key once, not once per reader.
_warned_deprecated_dependencies_key = False


def get_requirements(ck_info: dict) -> list:
    """Read a project's requirements, honoring the old key name.

    ``dependencies`` was renamed to ``requirements`` once the list grew to
    hold things that can't be depended on so much as demanded -- a CPU
    count, an amount of memory. The old key still works, and says so once,
    since a rename nobody is told about is one nobody makes. A project that
    sets both has said the same thing twice in two places that can drift
    apart, so that is reported rather than merged.
    """
    global _warned_deprecated_dependencies_key
    reqs = ck_info.get("requirements")
    deps = ck_info.get("dependencies")
    if reqs and deps:
        raise ValueError(
            "Both 'requirements' and 'dependencies' are set in calkit.yaml; "
            "'dependencies' is the old name for the same key, so merge them "
            "into 'requirements'"
        )
    if deps and not _warned_deprecated_dependencies_key:
        from calkit.cli import warn

        _warned_deprecated_dependencies_key = True
        # Written for whoever has to act on it rather than raised as a
        # UserWarning, whose file-and-line formatting reads as a defect in
        # Calkit instead of a line to change in their own project
        warn(
            "The 'dependencies' key in calkit.yaml is deprecated; rename it "
            "to 'requirements', which is what it's called now that it also "
            "holds constraints on the machine itself.",
            err=True,
        )
    return list(reqs or deps or [])


def _normalize_requirement(req) -> dict:
    """Normalize a calkit.yaml requirement entry into a ``{kind, ...}`` dict.

    Accepts every form supported by ``check_requirements`` so callers that
    need access to extra fields (``check_command``, ``min``, etc.) don't
    have to re-parse:

    - plain string (treated as an app name, version specifiers split off)
    - ``{name: {kind: ..., ...attrs}}`` single-key form
    - ``{name, kind, ...attrs}`` flat form

    ``name`` is the identity of an ``app`` or ``env-var``, so it is
    required there. A ``setup`` requirement may omit it, since a single
    anonymous setup step is common and forcing users to invent a name adds
    friction; a stable one is synthesized from a short hash of
    ``check_command``. A machine-property requirement has no name at all --
    ``kind: cpu-count`` already says everything there is to say about which
    property it constrains -- so the kind is used as the name in messages.
    """
    dep = req
    if isinstance(dep, str):
        # Split on the first version operator so a string like
        # ``calkit>=0.38`` produces both a clean name and a version spec
        # the caller can validate.
        m = re.match(r"^([A-Za-z0-9_.\-]+)(.*)$", dep.strip())
        if m is None:
            raise ValueError(f"Malformed requirement: {dep}")
        out: dict = {"name": m.group(1), "kind": "app"}
        spec = m.group(2).strip()
        if spec:
            out["version_spec"] = spec
        return out
    if not isinstance(dep, dict):
        raise ValueError(f"Malformed requirement: {dep}")
    keys = list(dep.keys())
    # Flat form with explicit kind: only requires ``name`` for kinds where
    # name is the identity (app, env-var). Setup requirements may omit it,
    # and property requirements have none to give.
    if "kind" in keys:
        out = dict(dep)
        if "name" not in out:
            kind = out["kind"]
            if kind in system_property_requirement_kinds():
                out["name"] = kind
            elif kind == "setup":
                check_command = out.get("check_command", "")
                short = hashlib.sha1(
                    check_command.encode("utf-8")
                ).hexdigest()[:8]
                out["name"] = f"setup-{short}"
            else:
                raise ValueError(f"Requirement missing required 'name': {dep}")
        return out
    if "name" in keys:
        out = dict(dep)
        out.setdefault("kind", "app")
        return out
    if len(keys) != 1:
        raise ValueError(f"Malformed requirement: {dep}")
    # Single-key form: {name: {kind: ..., ...}}
    name = keys[0]
    attrs = dep[name] or {}
    if not isinstance(attrs, dict):
        raise ValueError(f"Malformed requirement: {dep}")
    out = dict(attrs)
    out["name"] = name
    out.setdefault("kind", "app")
    return out


def check_property_requirement(
    req: dict, system_info: dict, described_as: str = "this machine"
) -> None:
    """Check one machine-property requirement against a machine.

    ``system_info`` is what :func:`get_system_info` reports, either from
    here or from the far end of an SSH connection, so the same constraints
    can be checked wherever the stage will actually run. ``described_as``
    names that machine in any error, since "2 CPUs are required, this has
    1" is a different problem depending on which machine "this" is.

    Raises ``ValueError`` describing what was asked for and what was found.
    A property the machine can't report is an error too, rather than a
    silent pass: an unanswerable question isn't a satisfied one.
    """
    from packaging.specifiers import SpecifierSet
    from packaging.version import InvalidVersion, Version

    prop = req["kind"]
    key = system_property_requirement_kinds()[prop]
    value = system_info.get(key)
    if value is None:
        raise ValueError(
            f"Requirement on '{prop}' can't be checked because "
            f"{described_as} doesn't report it"
        )
    # Numeric properties are bounded; everything else is matched or
    # compared as a version.
    if prop in _numeric_property_kinds():
        minimum = req.get("min")
        maximum = req.get("max")
        if minimum is None and maximum is None:
            raise ValueError(
                f"Requirement on '{prop}' needs a 'min' or a 'max'; to "
                "depend on its value rather than constrain it, add it to "
                "the environment's 'lock'"
            )
        if minimum is not None and value < minimum:
            raise ValueError(
                f"{described_as} has {prop} {_fmt_prop(value)}, but at least "
                f"{_fmt_prop(minimum)} is required"
            )
        if maximum is not None and value > maximum:
            raise ValueError(
                f"{described_as} has {prop} {_fmt_prop(value)}, but at most "
                f"{_fmt_prop(maximum)} is required"
            )
        return
    equals = req.get("equals")
    spec = req.get("version_spec")
    if equals is None and spec is None:
        raise ValueError(
            f"Requirement on '{prop}' needs an 'equals' or a 'version_spec'; "
            "to depend on its value rather than constrain it, add it to the "
            "environment's 'lock'"
        )
    if equals is not None:
        allowed = [equals] if isinstance(equals, str) else list(equals)
        # Matched case-insensitively because the same machine is 'Darwin'
        # or 'darwin' depending on who is writing it down, and nobody means
        # those to be different answers.
        if str(value).lower() not in [str(a).lower() for a in allowed]:
            wanted = " or ".join(f"'{a}'" for a in allowed)
            raise ValueError(
                f"{described_as} has {prop} '{value}', but {wanted} is "
                "required"
            )
    if spec is not None:
        try:
            spec_set = SpecifierSet(
                spec if spec[0] in "<>=!~" else f"=={spec}"
            )
        except Exception as e:
            raise ValueError(f"Invalid version_spec '{spec}' for {prop}: {e}")
        try:
            parsed = Version(str(value))
        except InvalidVersion:
            raise ValueError(
                f"{described_as} reports {prop} '{value}', which can't be "
                f"read as a version to compare against '{spec}'"
            )
        if parsed not in spec_set:
            raise ValueError(
                f"{described_as} has {prop} '{value}', but '{spec}' is "
                "required"
            )


def _fmt_prop(value: float) -> str:
    """Format a numeric property so whole numbers don't read as floats."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def extract_version(text: str) -> str | None:
    """Pull a comparable version out of what a tool prints for ``--version``.

    Tools answer that question in their own way -- 'git version 2.39.5',
    'uv 0.4.18 (a1b2c3d)' -- so the number has to be found rather than
    read off. The first dotted number is it in every case we've seen; a
    build hash that follows is not part of what a specifier compares.
    """
    m = re.search(r"\d+(?:\.\d+)+|\d+", text or "")
    return m.group(0) if m else None


def check_app_version(
    name: str,
    spec: str,
    system_info: dict | None = None,
    described_as: str = "this machine",
    probe_locally: bool = True,
) -> None:
    """Check an installed app against a version specifier.

    ``system_info`` supplies versions for the tools a system description
    already collects; anything else is asked directly, unless the machine
    in question isn't this one, which is what ``probe_locally=False``
    says. Reading a local version to check a remote requirement would
    answer a different question than the one asked.

    A version that can't be read is reported rather than treated as a
    failure: plenty of tools don't answer ``--version`` in any parseable
    way, and refusing to run because we couldn't read one would make the
    field unusable for them. Saying so keeps it from looking checked.
    """
    from packaging.specifiers import SpecifierSet
    from packaging.version import InvalidVersion, Version

    raw = (system_info or {}).get(f"{name}_version")
    if raw is None and probe_locally:
        raw = get_dep_version(name)
    found = extract_version(raw) if raw else None
    if found is None:
        print(
            f"Warning: could not read {name}'s version on {described_as}, so "
            f"'{spec}' was not checked"
        )
        return
    spec_str = spec if spec[0] in "<>=!~" else f"=={spec}"
    try:
        spec_set = SpecifierSet(spec_str)
    except Exception as e:
        raise ValueError(f"Invalid version_spec '{spec}' for app {name}: {e}")
    try:
        parsed = Version(found)
    except InvalidVersion:
        print(
            f"Warning: {name} reports version '{found}' on {described_as}, "
            f"which can't be compared against '{spec}'"
        )
        return
    if parsed not in spec_set:
        raise ValueError(
            f"app '{name}' is version {found} on {described_as}, but "
            f"'{spec_str}' is required"
        )


def check_requirements(
    ck_info: dict | None = None,
    wdir: str | None = None,
    system_info: dict | None = None,
    interactive: bool | None = None,
    use_cache: bool = True,
    requirements: list | None = None,
    described_as: str = "this machine",
) -> None:
    """Check that a project's declared requirements are satisfied.

    With no ``requirements`` given, the project's own list is checked,
    which describes the host -- the built-in ``_system`` environment. A
    ``system`` environment passes its own list here instead, for the
    machine it names.

    ``setup`` requirements are verified via
    :func:`calkit.dependencies.check_setup_dep`, which runs the
    ``check_command`` and -- on an interactive TTY -- optionally runs the
    declared ``setup_command`` after asking the user. Non-interactive
    failures abort with the fix-it command printed for the user to run.
    """
    if requirements is not None:
        # An environment's own list is checked exactly as declared: it
        # describes a machine that runs stages, which is a smaller claim
        # than being where the project lives.
        deps = list(requirements)
    else:
        if ck_info is None:
            ck_info = load_calkit_info(wdir=wdir)
        deps = get_requirements(ck_info)
        # Git is how a project exists at all, so the host needs it whether
        # or not anyone wrote it down.
        if "git" not in deps:
            deps.append("git")
    # Resolve TTY interactivity once so a single per-call answer drives
    # every prompt (env-var, app installer, setup step).
    if interactive is None:
        from calkit.dependencies import _is_interactive

        interactive = _is_interactive()
    # Process in dependency order: machine properties first, since a
    # machine that is too small to run the project at all should say so
    # before we start installing things on it, then env-vars (some
    # installers and setup commands read from them), then apps (env
    # managers like pixi / uv need to exist before setup steps that run
    # inside an env), then setup steps last. The setup-step
    # ``check_command`` typically wraps ``calkit xenv``, which validates
    # its own environment, so we don't need a separate env-check phase.
    property_kinds = system_property_requirement_kinds()
    buckets: dict[str, list[dict]] = {
        "_property": [],
        "env-var": [],
        "app": [],
        "setup": [],
    }
    for raw_dep in deps:
        dep = _normalize_requirement(raw_dep)
        kind = dep["kind"]
        if kind in property_kinds:
            buckets["_property"].append(dep)
        elif kind not in buckets:
            # Unknown / legacy kinds (e.g., ``calkit-config``) fall through
            # to ``check_dep_exists`` in original order so we don't change
            # behavior for them silently.
            buckets.setdefault("_other", []).append(dep)
        else:
            buckets[kind].append(dep)
    if buckets["_property"]:
        # Read the machine only when something asks about it; describing a
        # system shells out for a version from every package manager it can
        # find, which is not a cost to pay for a project that has no
        # property requirements at all.
        info = system_info if system_info is not None else get_system_info()
        for dep in buckets["_property"]:
            check_property_requirement(dep, info, described_as=described_as)
    for dep in buckets["env-var"]:
        dep_name = dep["name"]
        if dep_name in os.environ:
            continue
        # On a TTY, prompt the user and persist to .env so the very next
        # ``calkit run`` works without a separate setup step. Non-TTY
        # (CI) falls through to the legacy "not found" abort.
        if interactive:
            from calkit.dependencies import prompt_and_store_env_var

            print(f"Missing env var '{dep_name}'")
            value = prompt_and_store_env_var(
                dep_name, default=dep.get("default")
            )
            if value is not None:
                continue
        raise ValueError(f"env-var '{dep_name}' not found")
    for dep in buckets["app"]:
        dep_name = dep["name"]
        # The ``calkit`` app is always satisfied by the running process,
        # but a declared ``version_spec`` (e.g. ``calkit>=0.38``) is
        # checked against the installed version so projects can pin a
        # minimum CLI without writing a custom setup step.
        if dep_name == "calkit":
            spec = dep.get("version_spec")
            if spec:
                from calkit.dependencies import check_calkit_version

                check_calkit_version(spec)
            continue
        spec = dep.get("version_spec")
        if check_dep_exists(dep_name, "app", system_info=system_info):
            if spec:
                check_app_version(
                    dep_name,
                    spec,
                    system_info=system_info,
                    described_as=described_as,
                )
            continue
        # Offer the registered native installer when we have one.
        from calkit import install as _install

        if _install.get_installer(dep_name) is not None:
            print(f"App '{dep_name}' is not installed.")
            if _install.prompt_and_install(
                dep_name, interactive=interactive
            ) and check_dep_exists(dep_name, "app", system_info=system_info):
                if spec:
                    check_app_version(
                        dep_name,
                        spec,
                        system_info=system_info,
                        described_as=described_as,
                    )
                continue
        raise ValueError(f"app '{dep_name}' not found on {described_as}")
    for dep in buckets.get("_other", []):
        dep_name = dep["name"]
        dep_kind = dep["kind"]
        if not check_dep_exists(dep_name, dep_kind, system_info=system_info):
            raise ValueError(f"{dep_kind} '{dep_name}' not found")
    for dep in buckets["setup"]:
        from calkit.dependencies import check_setup_dep

        ok = check_setup_dep(
            dep,
            interactive=interactive,
            use_cache=use_cache,
            wdir=wdir,
        )
        if not ok:
            raise ValueError(
                f"setup requirement '{dep['name']}' is not satisfied"
            )


# Pre-rename names, kept so existing callers keep working.
check_system_deps = check_requirements
_normalize_dep = _normalize_requirement


def get_env_var_dep_names(ck_info: dict | None = None) -> list[str]:
    """Get a list of all environment variable names used in the project."""
    if ck_info is None:
        ck_info = load_calkit_info()
    env_vars = []
    for dep in get_requirements(ck_info):
        # Delegate shape-parsing to ``_normalize_requirement`` so this stays
        # in lockstep with ``check_requirements`` -- string entries,
        # single-key dicts, flat dicts, and nameless setup steps all flow
        # through one path.
        normalized = _normalize_requirement(dep)
        if normalized["kind"] == "env-var":
            env_vars.append(normalized["name"])
    return env_vars


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
        import calkit.hub

        if len(project.split("/")) != 2:
            raise ValueError("Invalid project identifier (too many slashes)")
        resp = calkit.hub.get(f"/projects/{project}/contents/{path}")
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
            import requests

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


def get_project_status_history(wdir: str | None = None, as_pydantic=True):
    from calkit.models import ProjectStatus

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


def detect_project_name(
    wdir: str | None = None, prepend_owner: bool = True
) -> str:
    """Detect a Calkit project owner and name.

    If ``prepend_owner`` is False, fall back to working directory name if
    there is no Git repo or name specified in ``calkit.yaml``.
    """
    ck_info = load_calkit_info(wdir=wdir)
    name = ck_info.get("name")
    if name is not None and not prepend_owner:
        return name
    owner = ck_info.get("owner")
    if name is None or owner is None:
        try:
            url = calkit.git.get_repo(wdir).remote().url
        except (ValueError, calkit.git.InvalidGitRepositoryError):
            if name is not None and not prepend_owner:
                return name
            if not prepend_owner:
                if wdir is None:
                    wdir = os.getcwd()
                return os.path.basename(os.path.abspath(wdir))
            raise ValueError("No Git remote set with name 'origin'")
        from_url = url.split("github.com")[-1][1:].removesuffix(".git")
        owner_name, project_name = from_url.split("/")
    if name is None:
        name = project_name
    if owner is None:
        owner = owner_name
    if prepend_owner:
        return f"{owner}/{name}"
    return name


def detect_project_github_url(wdir: str | None = None) -> str | None:
    """Detect the GitHub URL for the current project."""
    try:
        url = calkit.git.get_repo(wdir).remote().url
    except ValueError:
        warnings.warn("No Git remote set with name 'origin'")
        return None
    if "github.com" not in url:
        warnings.warn("Git remote is not a GitHub URL")
        return None
    url = url.removesuffix(".git")
    if url.startswith("git@github.com:"):
        url = url.replace("git@github.com:", "https://github.com/")
    return url


def get_dep_version(dep_name: str) -> str | None:
    """Get the version of a system-level dependency."""
    try:
        cmd = [dep_name, "--version"]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception:
        return None


# Where each platform records an identifier for the machine itself, as
# opposed to a name for it. Documentation for the error paths and the docs
# below; the readers are selected by ``platform.system()``, not by this.
MACHINE_ID_SOURCES = {
    "Darwin": "IOPlatformUUID (ioreg)",
    "Linux": "/etc/machine-id",
    "Windows": r"HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid",
}


def _read_darwin_machine_id() -> str | None:
    try:
        out = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
    return match.group(1).strip() if match else None


def _read_linux_machine_id() -> str | None:
    # The dbus copy predates systemd's and is still the only one on systems
    # without it. Both hold the same value where both exist.
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path) as f:
                value = f.read().strip()
        except OSError:
            continue
        if value:
            return value
    return None


def _read_windows_machine_id() -> str | None:
    # Guarded on sys.platform rather than caught as an ImportError so type
    # checkers on other platforms know the body doesn't apply to them;
    # winreg is always there on the one platform that reaches it
    if sys.platform != "win32":
        return None
    import winreg

    try:
        # Explicitly the 64-bit view, so a 32-bit Python doesn't get
        # redirected to a different key and report a different machine
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
    except OSError:
        return None
    return str(value).strip() or None


def _read_platform_machine_id() -> str | None:
    readers = {
        "Darwin": _read_darwin_machine_id,
        "Linux": _read_linux_machine_id,
        "Windows": _read_windows_machine_id,
    }
    reader = readers.get(platform.system())
    return reader() if reader is not None else None


def normalize_machine_id(machine_id: str | None) -> str | None:
    """Reduce a machine ID to what is worth comparing.

    Platforms write the same kind of identifier differently -- macOS in
    uppercase with dashes, systemd in lowercase without -- and users paste
    back whichever form they were shown. Case and dashes carry no
    information here, so they don't get to decide whether two IDs match.
    """
    if not machine_id:
        return None
    return machine_id.strip().lower().replace("-", "") or None


def machine_ids_match(a: str | None, b: str | None) -> bool:
    """Whether two machine IDs name the same machine.

    An unknown ID matches nothing, including another unknown one: not
    knowing which machine this is is never evidence that it's the one
    being asked about.
    """
    norm_a = normalize_machine_id(a)
    return norm_a is not None and norm_a == normalize_machine_id(b)


def get_machine_id() -> str | None:
    """A stable identifier for the machine we're running on, if there is one.

    Hostnames are the obvious way to say "this machine" and the worst way
    to mean it: they get renamed, they differ between what the machine
    calls itself and what DNS calls it, and two machines on different
    networks can share one. Pinning results to a particular machine, or
    recognizing that we're already on it, needs something that outlives all
    of that.

    Read from the platform (see ``MACHINE_ID_SOURCES``) rather than
    generated by Calkit, so there's nothing to bootstrap on a new machine,
    nothing lost by clearing Calkit's own config, and no way for two
    machines to end up sharing an ID by restoring one's dotfiles onto the
    other. ``machine_id`` in the Calkit config overrides it, for a machine
    that was rebuilt but should still count as the same one, and for
    platforms that supply nothing.

    Returns None where no identifier can be read. Callers must treat that
    as "unknown", never as "different from the one I was given".
    """
    from calkit.config import read as read_config

    try:
        configured = read_config().machine_id
    except Exception:
        # An unreadable config shouldn't make the machine unidentifiable
        configured = None
    if configured and configured.strip():
        return configured.strip()
    return _read_platform_machine_id()


def get_system_info() -> dict:
    """Get information about the system on which we're currently running."""
    import psutil

    os_name = platform.system()
    system_info = {
        "os": os_name,
        "os_version": platform.release(),
        "python_version": platform.python_version(),
        "calkit_version": calkit.__version__,
        "calkit_git_rev": None,
        "hostname": socket.gethostname(),
        "machine_id": get_machine_id(),
        "processor": platform.processor(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_implementation": platform.python_implementation(),
        "python_compiler": platform.python_compiler(),
        "memory_gb": psutil.virtual_memory().total / (1024**3),
        "cpu_count": os.cpu_count(),
    }
    node_id = uuid.getnode()
    # The multicast bit is the 40th bit from the right (0-indexed)
    # This corresponds to the least significant bit of the first octet
    # A standard unicast MAC address has this bit as 0
    # A randomly generated node ID by uuid.getnode() will have this bit as 1
    is_random_fallback = bool(node_id & 0x010000000000)
    if is_random_fallback:
        node_id = None
    system_info["node_id"] = node_id
    # See if we can detect Calkit Git rev
    try:
        repo = calkit.git.get_repo(os.path.dirname(calkit.__file__))
        system_info["calkit_git_rev"] = repo.head.commit.hexsha
    except Exception:
        pass
    # Get versions of important foundational dependencies
    for dep in [
        "git",
        "docker",
        "conda",
        "mamba",
        "uv",
        "pixi",
        "Rscript",
        "juliaup",
        "julia",
    ]:
        system_info[f"{dep}_version"] = get_dep_version(dep)
    # OS-specific app versions
    if os_name == "Darwin":
        for dep in ["brew", "port"]:
            system_info[f"{dep}_version"] = get_dep_version(dep)
    elif os_name == "Linux":
        for dep in ["apt", "yum"]:
            system_info[f"{dep}_version"] = get_dep_version(dep)
    elif os_name == "Windows":
        for dep in ["choco", "winget"]:
            system_info[f"{dep}_version"] = get_dep_version(dep)
    system_info_str = json.dumps(system_info, sort_keys=True).encode()
    system_info["id"] = hashlib.sha1(system_info_str).hexdigest()
    return system_info


def get_md5(path: str, exclude_files: list[str] | None = None) -> str:
    if os.path.isdir(path):
        # See https://github.com/calkit/calkit/issues/346
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning)
            import checksumdir
        return checksumdir.dirhash(path, excluded_files=exclude_files)
    hasher = hashlib.md5()
    with open(path, "rb") as f:
        # Read the file in chunks to avoid memory issues with large files
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def set_env_vars(ck_info: dict, cli: bool = True) -> None:
    """Set environmental variables according to the values read from
    ``calkit.yaml``.

    TODO: This should also handle ``dotenv``.
    """
    env_vars = ck_info.get("env_vars", {})
    if not isinstance(env_vars, dict):
        msg = (
            "Environmental variables in Calkit project info must be a "
            "map/dictionary"
        )
        if cli:
            from calkit.cli import raise_error

            raise_error(msg)
        else:
            raise ValueError(msg)
    for k, v in env_vars.items():
        os.environ[str(k)] = str(v)
