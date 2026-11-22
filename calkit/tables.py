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
    import posixpath

    import calkit
    import calkit.detect
    import calkit.pipeline

    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    tables = calkit.pipeline.list_artifacts(
        "tables",
        ck_info=ck_info,
        wdir=wdir,
        declared_only=declared_only,
        status=status,
        pending_extensions=calkit.detect.TABLE_EXTENSIONS,
    )
    if declared_only:
        return tables
    # A table a notebook's cell is marked to make is one whatever its
    # format, e.g., LaTeX, which isn't otherwise taken for a table
    listed = {t.get("path") for t in tables}
    marked = []
    for stage in (
        (ck_info.get("pipeline") or {}).get("stages") or {}
    ).values():
        if not isinstance(stage, dict):
            continue
        for out in stage.get("cell_outputs") or []:
            if (
                not isinstance(out, dict)
                or out.get("kind") != "table"
                or not out.get("output_path")
            ):
                continue
            path = posixpath.normpath(
                posixpath.join(
                    stage.get("wdir") or "", str(out["output_path"])
                )
            )
            if path not in listed:
                marked.append({"path": path, "detected": True})
                listed.add(path)
    return tables + calkit.pipeline.annotate_artifacts(
        marked, ck_info=ck_info, wdir=wdir, status=status
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


def format_table_cell(value: Any, number_format: str | None = None) -> str:
    """A table cell's text, with a number that isn't whole formatted by
    ``number_format``, e.g., ``.3f``, or else to six significant figures.
    """
    if value is None:
        return ""
    if isinstance(value, (bool, int)):
        return str(value)
    if isinstance(value, float):
        return format(value, number_format or "g")
    if isinstance(value, list):
        return ", ".join(format_table_cell(v, number_format) for v in value)
    return str(value)


def get_latex_table(table: dict, number_format: str | None = None) -> str:
    """A table as a LaTeX ``tabular``, with the rules ``booktabs`` draws,
    or plain lines without it, and numbers aligned right.
    """
    import re

    def escape(text: str) -> str:
        replacements = {
            "\\": r"\textbackslash{}",
            "&": r"\&",
            "%": r"\%",
            "$": r"\$",
            "#": r"\#",
            "_": r"\_",
            "{": r"\{",
            "}": r"\}",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
        }
        return re.sub(
            r"[\\&%$#_{}~^]", lambda m: replacements[m.group()], text
        )

    def cell_tex(value: Any) -> str:
        text = escape(format_table_cell(value, number_format))
        # A minus sign rather than a hyphen
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"$-${text[1:]}" if text.startswith("-") else text
        return text

    columns = list(table.get("columns") or [])
    rows = [list(r) for r in table.get("data") or []]
    index = table.get("index")
    if index is not None:
        columns = [table.get("index_name") or ""] + columns
        rows = [[i] + r for i, r in zip(index, rows)]
    numeric = [
        all(
            isinstance(r[j], (int, float)) and not isinstance(r[j], bool)
            for r in rows
            if j < len(r) and r[j] is not None
        )
        and any(j < len(r) and r[j] is not None for r in rows)
        for j in range(len(columns))
    ]
    align = "".join("r" if n else "l" for n in numeric)
    lines = [
        "% Written by Calkit from a notebook's cell output",
        r"\providecommand{\toprule}{\hline}",
        r"\providecommand{\midrule}{\hline}",
        r"\providecommand{\bottomrule}{\hline}",
        rf"\begin{{tabular}}{{{align}}}",
        r"\toprule",
        " & ".join(escape(str(c)) for c in columns) + r" \\",
        r"\midrule",
    ]
    for row in rows:
        lines.append(" & ".join(cell_tex(v) for v in row) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", ""]
    return "\n".join(lines)


def get_markdown_table(table: dict, number_format: str | None = None) -> str:
    """A table as a Markdown pipe table."""

    def cell_md(value: Any) -> str:
        text = format_table_cell(value, number_format)
        return text.replace("|", r"\|").replace("\n", " ")

    columns = list(table.get("columns") or [])
    rows = [list(r) for r in table.get("data") or []]
    index = table.get("index")
    if index is not None:
        columns = [table.get("index_name") or ""] + columns
        rows = [[i] + r for i, r in zip(index, rows)]
    lines = [
        "| " + " | ".join(cell_md(c) for c in columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    lines += ["| " + " | ".join(cell_md(v) for v in r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def write_table(
    path: str, table: dict, number_format: str | None = None
) -> None:
    """Write a table, as its ``columns``, ``data`` rows, and an optional
    ``index`` and ``index_name``, in the format the path's extension says:
    LaTeX, CSV, Markdown, or JSON.
    """
    import csv
    import json

    suffix = ext(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if suffix == ".json":
        records = [dict(zip(table["columns"], r)) for r in table["data"]]
        if table.get("index") is not None:
            name = table.get("index_name") or "index"
            records = [{name: i} | r for i, r in zip(table["index"], records)]
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(records, f, indent=2)
            f.write("\n")
        return
    if suffix == ".csv":
        columns = list(table["columns"])
        rows = [list(r) for r in table["data"]]
        if table.get("index") is not None:
            columns = [table.get("index_name") or ""] + columns
            rows = [[i] + r for i, r in zip(table["index"], rows)]
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(columns)
            # Numbers in full unless formatted, since a CSV is data to read
            for row in rows:
                writer.writerow(
                    [
                        repr(v)
                        if isinstance(v, float) and number_format is None
                        else format_table_cell(v, number_format)
                        for v in row
                    ]
                )
        return
    if suffix == ".tex":
        text = get_latex_table(table, number_format)
    elif suffix == ".md":
        text = get_markdown_table(table, number_format)
    else:
        raise ValueError(f"Can't write a table as '{suffix}'")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
