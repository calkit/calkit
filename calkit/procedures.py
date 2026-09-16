"""Functionality for working with procedures."""

import os

import calkit
from calkit.models.core import Procedure, ProcedureEntry, ProcedureFile


def load(name: str, wdir: str = ".", ck_info: dict | None = None) -> Procedure:
    """Load a procedure by name, reading it from its file if it has one.

    An entry under ``procedures`` is either the procedure itself or a
    ``path`` to the YAML or JSON file holding it, and whichever it is,
    what comes back here is the full ``Procedure``, so nothing downstream
    needs to know the difference.
    """
    from pydantic import TypeAdapter

    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir, read_only=True)
    procs = ck_info.get("procedures", {})
    if name not in procs:
        raise KeyError(f"'{name}' is not defined as a procedure")
    entry: ProcedureFile | Procedure = TypeAdapter(
        ProcedureEntry
    ).validate_python(procs[name])
    if isinstance(entry, Procedure):
        return entry
    return load_file(entry, wdir=wdir)


def definition_paths(
    name: str, wdir: str = ".", ck_info: dict | None = None
) -> list[str]:
    """The files that define a procedure, relative to the project root.

    Always ``calkit.yaml``, which names it, plus the file holding it when
    it is kept in one. This is what has to be committed for a run to be a
    record of carrying out an agreed procedure rather than one someone was
    editing at the time.
    """
    from pydantic import TypeAdapter

    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir, read_only=True)
    paths = ["calkit.yaml"]
    entry = (ck_info.get("procedures") or {}).get(name)
    if entry is not None:
        try:
            validated = TypeAdapter(ProcedureEntry).validate_python(entry)
        except Exception:
            return paths
        if isinstance(validated, ProcedureFile):
            paths.append(validated.path)
    return paths


def load_file(entry: ProcedureFile, wdir: str = ".") -> Procedure:
    """Read the procedure a ``ProcedureFile`` entry points at."""
    fpath = os.path.join(wdir, entry.path)
    if not os.path.isfile(fpath):
        raise FileNotFoundError(f"Procedure file {entry.path} does not exist")
    # YAML is a superset of JSON, so one loader reads either; the
    # extension is checked only so a typo doesn't get parsed as YAML
    if os.path.splitext(entry.path)[1].lower() not in [
        ".yaml",
        ".yml",
        ".json",
    ]:
        raise ValueError(
            f"Procedure file {entry.path} must be a YAML or JSON file"
        )
    with open(fpath, encoding="utf-8") as f:
        data = calkit.ryaml.load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"Procedure file {entry.path} must hold a single procedure"
        )
    return Procedure.model_validate(data)
