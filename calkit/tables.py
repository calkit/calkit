"""Functionality for working with the project's tables."""

from __future__ import annotations

import os
from typing import Any, Literal

# Delimited text is read with the standard library so that listing and
# showing a CSV needs no dataframe engine installed; everything else is
# read through pandas or polars.
DELIMITERS = {".csv": ",", ".tsv": "\t"}


def ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def list_tables(
    ck_info: dict | None = None,
    wdir: str | None = None,
    declared_only: bool = False,
    status: bool = False,
) -> list[dict]:
    """The project's tables, declared and auto-detected.

    Each entry carries its producing stage when the pipeline writes it and,
    with ``status``, whether that stage is up to date, which needs DVC and
    so costs a pipeline status check.
    """
    import calkit.detect
    import calkit.pipeline

    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    declared = [o for o in ck_info.get("tables") or [] if isinstance(o, dict)]
    paths = {o.get("path") for o in declared}
    entries = [{**o, "detected": False} for o in declared]
    if not declared_only:
        found = calkit.detect.detect_project_artifacts(
            wdir=wdir, ck_info=ck_info
        )
        for path in found.get("tables", []):
            if path not in paths:
                entries.append({"path": path, "detected": True})
        # Detection only finds files that exist, and a table the pipeline
        # has yet to write is still one of the project's tables
        listed = {e.get("path") for e in entries}
        by_output = calkit.pipeline.stages_by_output(
            ck_info=ck_info, wdir=wdir
        )
        for path in sorted(by_output):
            if path in listed:
                continue
            if ext(path) in calkit.detect.TABLE_EXTENSIONS:
                entries.append({"path": path, "detected": True})
    calkit.pipeline.annotate_artifacts(
        entries, ck_info=ck_info, wdir=wdir, status=status
    )
    entries.sort(key=lambda e: str(e.get("path")))
    return entries


def read_table(
    path: str,
    content: bytes | None = None,
    columns: list[str] | None = None,
    filters: list[str] | None = None,
    rows: str | None = None,
    head: int | None = None,
    tail: int | None = None,
    engine: Literal["pandas", "polars"] | None = None,
) -> dict[str, Any]:
    """Read a table, optionally selecting columns and rows.

    Returns the selected ``columns`` and ``rows`` along with how many rows
    the table holds in total, so a caller can say what it left out.
    ``content`` reads the bytes given instead of the file at ``path``,
    which is how a table is read at a Git ref.
    """
    import calkit.detect

    suffix = ext(path)
    if suffix in DELIMITERS:
        table = _read_delimited(path, content, DELIMITERS[suffix])
    elif suffix in calkit.detect.TABLE_EXTENSIONS:
        table = _read_with_engine(path, content, suffix, engine)
    else:
        raise ValueError(f"Can't read a table from a '{suffix}' file")
    selected = _select_columns(table["columns"], columns)
    missing = [c for c in columns or [] if c not in selected and "*" not in c]
    if missing:
        raise ValueError(
            f"No column matches {', '.join(missing)}; this table has "
            + ", ".join(table["columns"])
        )
    kept = [
        row
        for row in table["rows"]
        if _matches(dict(zip(table["columns"], row)), filters or [])
    ]
    n_filtered = len(kept)
    if rows is not None:
        kept = [kept[i] for i in _row_indices(rows, len(kept))]
    if head is not None:
        kept = kept[:head]
    if tail is not None:
        kept = kept[-tail:]
    keep = [table["columns"].index(c) for c in selected]
    return {
        "columns": selected,
        "rows": [[row[i] for i in keep] for row in kept],
        "n_rows": len(table["rows"]),
        "n_rows_matching": n_filtered,
    }


def _read_delimited(
    path: str, content: bytes | None, delimiter: str
) -> dict[str, Any]:
    import csv
    import io

    if content is None:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f, delimiter=delimiter))
    else:
        text = content.decode("utf-8-sig", "replace")
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        return {"columns": [], "rows": []}
    header, *body = rows
    # A short row is padded rather than dropped, since a table is usually
    # being read to find out what's wrong with it
    width = len(header)
    return {
        "columns": header,
        "rows": [row[:width] + [""] * (width - len(row)) for row in body],
    }


def _read_with_engine(
    path: str,
    content: bytes | None,
    suffix: str,
    engine: Literal["pandas", "polars"] | None,
) -> dict[str, Any]:
    import importlib
    import tempfile

    import calkit.config

    engine = engine or calkit.config.read().dataframe_engine
    try:
        lib = importlib.import_module(engine)
    except ImportError as e:
        raise ImportError(
            f"Reading a {suffix} table needs {engine}, which isn't "
            f"installed: {e}"
        ) from e
    reader = {
        ".parquet": "read_parquet",
        ".xlsx": "read_excel",
        ".xls": "read_excel",
        ".feather": "read_ipc" if engine == "polars" else "read_feather",
        ".arrow": "read_ipc" if engine == "polars" else "read_feather",
    }[suffix]
    if content is None:
        df = getattr(lib, reader)(path)
    else:
        # Both engines take a path for every format; a buffer only works
        # for some, so go through a file
        with tempfile.NamedTemporaryFile(suffix=suffix) as f:
            f.write(content)
            f.flush()
            df = getattr(lib, reader)(f.name)
    columns = [str(c) for c in df.columns]
    if engine == "polars":
        values = df.rows()
    else:
        values = df.itertuples(index=False, name=None)
    return {
        "columns": columns,
        "rows": [["" if v is None else str(v) for v in row] for row in values],
    }


def _select_columns(
    columns: list[str], patterns: list[str] | None
) -> list[str]:
    """The columns to show, in the order asked for.

    A pattern can name a column or glob several, e.g., ``*_mod`` for every
    column of one arm, and the same column is never shown twice.
    """
    import fnmatch

    if not patterns:
        return list(columns)
    selected: list[str] = []
    for pattern in patterns:
        for column in columns:
            if column not in selected and (
                column == pattern or fnmatch.fnmatchcase(column, pattern)
            ):
                selected.append(column)
    return selected


def _matches(row: dict[str, str], filters: list[str]) -> bool:
    import re

    for f in filters:
        m = re.match(
            r"^(?P<col>[^=<>~!]+)(?P<op>>=|<=|!=|~|=|>|<)(?P<val>.*)$", f
        )
        if m is None:
            raise ValueError(
                f"Can't read the filter '{f}'; write it as COLUMN=VALUE, "
                "COLUMN~TEXT, or COLUMN>NUMBER"
            )
        col, op, val = m.group("col"), m.group("op"), m.group("val")
        if col not in row:
            raise ValueError(
                f"No column named '{col}'; this table has " + ", ".join(row)
            )
        cell = row[col]
        if op == "~":
            if val.lower() not in cell.lower():
                return False
        elif op == "=":
            if cell != val:
                return False
        elif op == "!=":
            if cell == val:
                return False
        else:
            try:
                left, right = float(cell), float(val)
            except ValueError:
                raise ValueError(
                    f"Can't compare '{cell}' to '{val}' with {op}; "
                    f"column '{col}' isn't numeric here"
                ) from None
            if not {
                ">": left > right,
                "<": left < right,
                ">=": left >= right,
                "<=": left <= right,
            }[op]:
                return False
    return True


def _row_indices(spec: str, n: int) -> list[int]:
    """Zero-based row indices from a 1-based spec like ``1-20,35,40-``."""
    indices: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part.lstrip("-"):
                lo, _, hi = part.partition("-")
                start = int(lo) if lo.strip() else 1
                stop = int(hi) if hi.strip() else n
            else:
                start = stop = int(part)
        except ValueError:
            raise ValueError(
                f"Can't read the row spec '{part}'; write it as N, N-M, "
                "-M, or N-"
            ) from None
        indices += [i for i in range(start - 1, stop) if 0 <= i < n]
    return list(dict.fromkeys(indices))
