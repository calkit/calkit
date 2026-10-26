"""Functionality for working with the project's results.

A result is an object-like file---JSON, TOML, or YAML---whose keys are what
gets cited, the way a question's value evidence names one.
"""

from __future__ import annotations

import os
from typing import Any

# Extensions whose keys can be read, which are the ones a question's
# value evidence can cite
EXTENSIONS = (".json", ".toml", ".yaml", ".yml")


def list_results(
    ck_info: dict | None = None,
    wdir: str | None = None,
    declared_only: bool = False,
    status: bool = False,
) -> list[dict]:
    """The project's results, declared and auto-detected.

    Each entry carries its producing stage when the pipeline writes it and,
    with ``status``, whether that stage is up to date, which needs DVC and
    so costs a pipeline status check.
    """
    import calkit.detect
    import calkit.pipeline

    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    declared = [o for o in ck_info.get("results") or [] if isinstance(o, dict)]
    paths = {o.get("path") for o in declared}
    entries = [{**o, "detected": False} for o in declared]
    if not declared_only:
        found = calkit.detect.detect_project_artifacts(
            wdir=wdir, ck_info=ck_info
        )
        for path in found.get("results", []):
            if path not in paths:
                entries.append({"path": path, "detected": True})
        # Detection only finds files that exist, and a result the pipeline
        # has yet to write is still one of the project's results
        listed = {e.get("path") for e in entries}
        by_output = calkit.pipeline.stages_by_output(
            ck_info=ck_info, wdir=wdir
        )
        for path in sorted(by_output):
            if path in listed:
                continue
            if os.path.splitext(path)[1].lower() in EXTENSIONS:
                entries.append({"path": path, "detected": True})
    calkit.pipeline.annotate_artifacts(
        entries, ck_info=ck_info, wdir=wdir, status=status
    )
    entries.sort(key=lambda e: str(e.get("path")))
    return entries


def load_result(path: str, content: bytes | None = None) -> Any:
    """A result file's contents, loaded.

    Parsed by the same reader a question's value evidence uses, so what
    can be shown here and what can be cited are the same thing.
    ``content`` loads the bytes given instead of the file at ``path``,
    which is how a result is read at a Git ref.
    """
    from calkit.questions import parse_evidence_text

    suffix = os.path.splitext(path)[1].lower()
    if suffix not in EXTENSIONS:
        from calkit.detect import TABLE_EXTENSIONS

        # A tabular file is listed as a result too, but its keys are
        # columns, so it's read as a table
        hint = (
            f"; read it with 'calkit show table {path}'"
            if suffix in TABLE_EXTENSIONS
            else "; results are " + ", ".join(EXTENSIONS)
        )
        raise ValueError(f"Can't read a result from a '{suffix}' file" + hint)
    if content is None:
        with open(path, "rb") as f:
            content = f.read()
    return parse_evidence_text(content.decode("utf-8-sig", "replace"), path)


def read_result(
    path: str,
    content: bytes | None = None,
    keys: list[str] | None = None,
    depth: int | None = None,
) -> dict[str, Any]:
    """Read a result as the flat list of keys a citation would name.

    Keys are dotted paths, resolved the way a question's value evidence
    resolves them, so what's printed here is what an answer can cite.
    ``depth`` stops flattening and shows the rest of a value as JSON,
    which keeps a deeply nested file readable.
    """
    from calkit.questions import resolve_key

    data = load_result(path, content=content)
    selected: list[tuple[str, Any]] = []
    if keys:
        for key in keys:
            try:
                selected.append((key, resolve_key(data, key)))
            except KeyError:
                raise ValueError(
                    f"No key '{key}' in {path}; it has "
                    + ", ".join(k for k, _ in _flatten(data, depth=1))
                ) from None
    else:
        selected.append(("", data))
    items: list[dict] = []
    for prefix, value in selected:
        for key, leaf in _flatten(value, depth=depth):
            full = ".".join(p for p in (prefix, key) if p)
            items.append(
                {
                    "key": full or prefix,
                    "value": _format(leaf),
                    "type": type(leaf).__name__,
                }
            )
    return {"items": items, "n_keys": len(items)}


def _flatten(
    value: Any, depth: int | None = None, prefix: str = ""
) -> list[tuple[str, Any]]:
    """Dotted key and value for every leaf, deepest path last.

    A list of scalars is a leaf, since its elements are read together;
    a list of objects is indexed into, since its elements are read apart.
    """
    if depth is not None and depth <= 0:
        return [(prefix, value)]
    if isinstance(value, dict):
        out: list[tuple[str, Any]] = []
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            out += _flatten(item, None if depth is None else depth - 1, child)
        return out
    if isinstance(value, list) and any(
        isinstance(item, (dict, list)) for item in value
    ):
        out = []
        for i, item in enumerate(value):
            child = f"{prefix}.{i}" if prefix else str(i)
            out += _flatten(item, None if depth is None else depth - 1, child)
        return out
    return [(prefix, value)]


def _format(value: Any) -> str:
    import json

    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, (int, float, str)):
        return str(value)
    # A container that flattening stopped at, kept on one line
    return json.dumps(value, default=str)
