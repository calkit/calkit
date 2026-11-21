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

    return calkit.pipeline.list_artifacts(
        "tables",
        ck_info=ck_info,
        wdir=wdir,
        declared_only=declared_only,
        status=status,
        pending_extensions=calkit.detect.TABLE_EXTENSIONS,
    )


def read_columns(
    path: str, engine: Literal["pandas", "polars"] | None = None
) -> list[str]:
    """A table's column names, reading no more of it than needed."""
    import csv

    suffix = ext(path)
    if suffix in DELIMITERS:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return next(csv.reader(f, delimiter=DELIMITERS[suffix]), [])
    return list(read_table(path, head=0, engine=engine)["columns"])


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

    def read_delimited(delimiter: str) -> dict[str, Any]:
        import csv
        import io

        if content is None:
            with open(path, newline="", encoding="utf-8-sig") as f:
                lines = list(csv.reader(f, delimiter=delimiter))
        else:
            text = content.decode("utf-8-sig", "replace")
            lines = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        if not lines:
            return {"columns": [], "rows": []}
        header, *body = lines
        # A short row is padded rather than dropped, since a table is
        # usually being read to find out what's wrong with it
        width = len(header)
        return {
            "columns": header,
            "rows": [row[:width] + [""] * (width - len(row)) for row in body],
        }

    def read_with_engine(suffix: str) -> dict[str, Any]:
        import importlib
        import tempfile

        import calkit.config

        name = engine or calkit.config.read().dataframe_engine
        try:
            lib = importlib.import_module(name)
        except ImportError as e:
            raise ImportError(
                f"Reading a {suffix} table needs {name}, which isn't "
                f"installed: {e}"
            ) from e
        reader = getattr(
            lib,
            {
                ".parquet": "read_parquet",
                ".xlsx": "read_excel",
                ".xls": "read_excel",
                ".feather": "read_ipc" if name == "polars" else "read_feather",
                ".arrow": "read_ipc" if name == "polars" else "read_feather",
            }[suffix],
        )
        if content is None:
            df = reader(path)
        else:
            # Both engines take a path for every format; a buffer only
            # works for some, so go through a file, closed before it's
            # read since Windows won't open one twice
            with tempfile.TemporaryDirectory() as tmp:
                fpath = os.path.join(tmp, "table" + suffix)
                with open(fpath, "wb") as f:
                    f.write(content)
                df = reader(fpath)
        if name == "polars":
            values = df.rows()
        else:
            values = df.itertuples(index=False, name=None)
        return {
            "columns": [str(c) for c in df.columns],
            "rows": [
                ["" if v is None else str(v) for v in row] for row in values
            ],
        }

    def select_columns(names: list[str]) -> list[str]:
        # A pattern can name a column or glob several, e.g., ``*_mod``, and
        # the same column is never shown twice
        import fnmatch

        if not columns:
            return list(names)
        selected: list[str] = []
        for pattern in columns:
            for name in names:
                if name not in selected and (
                    name == pattern or fnmatch.fnmatchcase(name, pattern)
                ):
                    selected.append(name)
        return selected

    def matches(row: dict[str, str]) -> bool:
        import re

        for f in filters or []:
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
                    f"No column named '{col}'; this table has "
                    + ", ".join(row)
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
            elif not cell.strip():
                # A missing value isn't greater or less than anything
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

    def row_indices(spec: str, n: int) -> list[int]:
        # Zero-based indices from a 1-based spec like ``1-20,35,-5,40-``
        indices: list[int] = []
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                if "-" in part:
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

    suffix = ext(path)
    if suffix in DELIMITERS:
        table = read_delimited(DELIMITERS[suffix])
    elif suffix in calkit.detect.TABLE_EXTENSIONS:
        table = read_with_engine(suffix)
    else:
        raise ValueError(f"Can't read a table from a '{suffix}' file")
    selected = select_columns(table["columns"])
    missing = [c for c in columns or [] if c not in selected and "*" not in c]
    if missing:
        raise ValueError(
            f"No column matches {', '.join(missing)}; this table has "
            + ", ".join(table["columns"])
        )
    kept = [
        row
        for row in table["rows"]
        if matches(dict(zip(table["columns"], row)))
    ]
    n_filtered = len(kept)
    if rows is not None:
        kept = [kept[i] for i in row_indices(rows, len(kept))]
    if head is not None:
        kept = kept[: max(head, 0)]
    if tail is not None:
        kept = kept[max(len(kept) - tail, 0) :]
    keep = [table["columns"].index(c) for c in selected]
    return {
        "columns": selected,
        "rows": [[row[i] for i in keep] for row in kept],
        "n_rows": len(table["rows"]),
        "n_rows_matching": n_filtered,
    }
