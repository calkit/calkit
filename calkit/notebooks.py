"""Functionality for working with notebooks."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from calkit.models.io import (
        InputsFromStageOutputs,
        PathInput,
        PathOutput,
    )


def get_executed_notebook_path(
    notebook_path: str,
    to: Literal["html", "notebook"],
    as_posix: bool = True,
    parameters: dict[str, Any] | None = None,
) -> str:
    """Return the path of an executed notebook."""
    nb_dir = os.path.dirname(notebook_path)
    nb_fname = os.path.basename(notebook_path)
    # If we have any parameters, add these to the notebook name
    if parameters:
        parameters_cleaned = {}
        for k, v in parameters.items():
            if isinstance(v, list):
                if len(v) == 0:
                    v = "empty"
                elif len(v) < 5:
                    v = ",".join(map(str, v))
                else:
                    v = hashlib.md5(
                        json.dumps(v, sort_keys=True).encode()
                    ).hexdigest()[:7]
            elif isinstance(v, dict):
                v = hashlib.md5(
                    json.dumps(v, sort_keys=True).encode()
                ).hexdigest()[:7]
            parameters_cleaned[k] = v
        params_txt = "-".join(
            f"{k}-{v}" for k, v in parameters_cleaned.items()
        )
        nb_fname = f"{nb_fname.removesuffix('.ipynb')}-{params_txt}.ipynb"
    if to == "html":
        fname_out = nb_fname.removesuffix(".ipynb") + ".html"
    else:
        fname_out = nb_fname
    subdirs = {"html": "html", "notebook": "executed"}
    p = os.path.join(".calkit", "notebooks", subdirs[to], nb_dir, fname_out)
    if as_posix:
        p = Path(p).as_posix()
    return p


CELL_OUTPUT_FIGURE_EXTS = (".png", ".pdf", ".svg", ".jpg", ".jpeg")
CELL_OUTPUT_TABLE_EXTS = (".tex", ".csv", ".md", ".json")
# The MIME type of the image a cell shows for each figure extension, for a
# figure saved without a variable
CELL_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
}
# Marks the cells Calkit adds to save cell outputs, which are taken out of
# the executed notebook again
CAPTURE_CELL_KEY = "calkit_capture"
# Defined in the kernel by the first cell Calkit adds, and called after each
# cell with outputs. It's self-contained, since the notebook's environment
# needn't have Calkit installed, and leaves a figure saved without a variable
# to be taken from the executed notebook instead
CAPTURE_HELPER = r"""
def _calkit_save_cell_outputs(where, outputs, values_path, tables_dir):
    import json
    import os

    def to_data(value, what, strict=True):
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, dict):
            return {str(k): to_data(v, what, strict) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [to_data(v, what, strict) for v in value]
        # A pandas Series or DataFrame, then NumPy arrays and scalars
        for method in ("to_dict", "tolist"):
            if callable(getattr(value, method, None)):
                return to_data(getattr(value, method)(), what, strict)
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
        if not strict:
            return str(value)
        raise TypeError(
            f"Calkit: can't save {what} after {where}, since it's a "
            f"{type(value).__name__}; save a number, string, or a list or "
            "dict of them"
        )

    def to_table(value, what):
        index = None
        index_name = None
        if callable(getattr(value, "to_frame", None)) and not hasattr(
            value, "columns"
        ):
            value = value.to_frame()
        if hasattr(value, "columns") and hasattr(value, "index"):
            split = value.to_dict(orient="split")
            columns = split["columns"]
            rows = split["data"]
            idx = value.index
            if not (
                type(idx).__name__ == "RangeIndex"
                and idx.start == 0
                and idx.step == 1
                and idx.name is None
            ):
                index = split["index"]
                index_name = idx.name
        elif hasattr(value, "columns") and callable(getattr(value, "rows", None)):
            columns = list(value.columns)
            rows = value.rows()
        elif isinstance(value, dict) and all(
            isinstance(v, (list, tuple)) or hasattr(v, "tolist")
            for v in value.values()
        ):
            columns = list(value)
            cols = [list(v) for v in value.values()]
            if len({len(c) for c in cols}) > 1:
                raise ValueError(
                    f"Calkit: can't save {what} after {where} as a table, "
                    "since its columns are different lengths"
                )
            rows = [list(r) for r in zip(*cols)]
        elif (
            isinstance(value, (list, tuple))
            and value
            and all(isinstance(r, dict) for r in value)
        ):
            columns = list(dict.fromkeys(k for r in value for k in r))
            rows = [[r.get(c) for c in columns] for r in value]
        elif (
            isinstance(value, (list, tuple))
            and value
            and all(isinstance(r, (list, tuple)) for r in value)
        ):
            columns = list(value[0])
            rows = [list(r) for r in value[1:]]
        else:
            raise TypeError(
                f"Calkit: can't save {what} after {where} as a table, since "
                f"it's a {type(value).__name__}; save a DataFrame, or a "
                "list of rows"
            )
        return {
            "columns": [str(c) for c in columns],
            "index": to_data(index, what, strict=False),
            "index_name": None if index_name is None else str(index_name),
            "data": [[to_data(c, what, strict=False) for c in r] for r in rows],
        }

    def save_figure(fig, path, what):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # A Matplotlib figure, or what's drawn on one, e.g., axes, saved
        # tight like the notebook shows it
        if not callable(getattr(fig, "savefig", None)):
            fig = getattr(fig, "figure", None) or fig
        if callable(getattr(fig, "savefig", None)):
            fig.savefig(path, bbox_inches="tight")
        elif callable(getattr(fig, "write_image", None)):
            fig.write_image(path)
        elif callable(getattr(fig, "save", None)):
            fig.save(path)
        else:
            raise TypeError(
                f"Calkit: can't save {what} after {where} as a figure, "
                f"since it's a {type(fig).__name__}; save a Matplotlib "
                "figure, or leave out the variable to save the image the "
                "cell shows"
            )

    user = globals()
    for i, out in outputs:
        name = out.get("value") or out.get("variable")
        what = f"'{name}'"
        if name is None:
            continue
        if name not in user:
            raise NameError(
                f"Calkit: there's no variable '{name}' after {where} to "
                f"save as {out.get('path') or 'a value'}"
            )
        if out.get("value"):
            values = {}
            if os.path.isfile(values_path):
                with open(values_path, encoding="utf-8") as f:
                    values = json.load(f)
            values[name] = to_data(user[name], what)
            os.makedirs(os.path.dirname(values_path) or ".", exist_ok=True)
            with open(values_path, "w", encoding="utf-8") as f:
                json.dump(values, f, indent=2)
        elif out.get("figure"):
            save_figure(user[name], out["path"], what)
        else:
            table = to_table(user[name], what)
            os.makedirs(tables_dir, exist_ok=True)
            with open(
                os.path.join(tables_dir, f"{i}.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(table, f)
"""


def get_notebook_values_path(
    notebook_path: str, parameters: dict[str, Any] | None = None
) -> str:
    """Where the values a notebook's cells make are saved, e.g.,
    ``.calkit/notebooks/outputs/analysis/values.json`` for
    ``analysis.ipynb``, with any parameters in the folder's name as for its
    executed copy.
    """
    executed = get_executed_notebook_path(
        notebook_path, to="notebook", parameters=parameters
    )
    prefix = ".calkit/notebooks/executed/"
    name = executed.removeprefix(prefix).removesuffix(".ipynb")
    return f".calkit/notebooks/outputs/{name}/values.json"


def get_notebook_of_values_path(path: str) -> str | None:
    """The notebook a values file was saved from, for one without
    parameters, which is how a value from it is cited.
    """
    prefix = ".calkit/notebooks/outputs/"
    path = path.replace("\\", "/")
    if not (path.startswith(prefix) and path.endswith("/values.json")):
        return None
    name = path.removeprefix(prefix).removesuffix("/values.json")
    return name + ".ipynb" if name else None


def get_cell_ids(nb: dict) -> list[str | None]:
    """Each cell's ID, or None for one without, e.g., in a notebook older
    than nbformat 4.5.
    """
    return [cell.get("id") for cell in nb.get("cells", [])]


def ensure_cell_ids(nb: dict) -> bool:
    """Give each cell without one an ID, as Jupyter does, upgrading an older
    notebook to nbformat 4.5, which is the first with them.

    Returns whether anything changed.
    """
    import uuid

    changed = False
    taken = {i for i in get_cell_ids(nb) if i}
    for cell in nb.get("cells", []):
        if cell.get("id"):
            continue
        new_id = uuid.uuid4().hex[:8]
        while new_id in taken:
            new_id = uuid.uuid4().hex[:8]
        taken.add(new_id)
        cell["id"] = new_id
        changed = True
    if changed and (nb.get("nbformat"), nb.get("nbformat_minor", 0)) < (4, 5):
        nb["nbformat"] = 4
        nb["nbformat_minor"] = 5
    return changed


def has_ordinal_cell_ids(nb: dict) -> bool:
    """Whether a notebook's cell IDs are numbers counting up, which is what
    nbstripout replaces them with unless given ``--keep-id``, so they change
    whenever a cell is added or removed above.
    """
    ids = get_cell_ids(nb)
    return len(ids) > 1 and ids == [str(i) for i in range(len(ids))]


def add_capture_cells(
    nb: dict,
    outputs: list[dict],
    values_path: str,
    tables_dir: str,
) -> dict:
    """A copy of a notebook with cells added to save its cell outputs, one
    after each cell some are saved after, and one at the end for values
    named without a cell.

    ``outputs`` are cell outputs as ``NotebookCellOutput.model_dump`` gives
    them, with ``path`` set to where a figure is saved, relative to where
    the kernel runs, like ``values_path`` and ``tables_dir``. Raises a
    ``ValueError`` naming a cell the notebook doesn't have.
    """
    import copy

    def make_cell(source: str, n: int) -> dict:
        return {
            "cell_type": "code",
            "id": f"calkit-capture-{n}",
            "metadata": {CAPTURE_CELL_KEY: True},
            "execution_count": None,
            "outputs": [],
            "source": source,
        }

    def make_call(where: str, items: list[tuple[int, dict]]) -> str:
        args = json.dumps([[i, o] for i, o in items])
        return (
            f"_calkit_save_cell_outputs({where!r}, "
            f"__import__('json').loads({args!r}), {values_path!r}, "
            f"{tables_dir!r})"
        )

    nb = copy.deepcopy(nb)
    ids = get_cell_ids(nb)
    by_cell: dict[str, list[tuple[int, dict]]] = {}
    at_end: list[tuple[int, dict]] = []
    for i, out in enumerate(outputs):
        cell = out.get("cell")
        if cell is None:
            at_end.append((i, out))
            continue
        if cell not in ids:
            raise ValueError(f"The notebook has no cell {cell}")
        by_cell.setdefault(cell, []).append((i, out))
    cells = [make_cell(CAPTURE_HELPER, 0)]
    for cell in nb.get("cells", []):
        cells.append(cell)
        items = by_cell.get(cell.get("id"))
        if items:
            cells.append(
                make_cell(make_call(f"cell {cell['id']}", items), len(cells))
            )
    if at_end:
        cells.append(make_cell(make_call("the last cell", at_end), len(cells)))
    nb["cells"] = cells
    if (nb.get("nbformat"), nb.get("nbformat_minor", 0)) < (4, 5):
        nb["nbformat"] = 4
        nb["nbformat_minor"] = 5
    return nb


def remove_capture_cells(nb: dict) -> dict:
    """A notebook without the cells ``add_capture_cells`` added."""
    nb = dict(nb)
    nb["cells"] = [
        cell
        for cell in nb.get("cells", [])
        if not cell.get("metadata", {}).get(CAPTURE_CELL_KEY)
    ]
    return nb


def get_cell_image(nb: dict, cell_id: str, ext: str) -> bytes:
    """The image a cell shows, as a file with the extension given, from an
    executed notebook, e.g., a plot Matplotlib drew inline.

    Raises a ``ValueError`` saying what's wrong, e.g., that it shows none,
    or more than one.
    """
    import base64

    mime = CELL_IMAGE_MIME_TYPES[ext.lower()]
    cell = next(
        (c for c in nb.get("cells", []) if c.get("id") == cell_id), None
    )
    if cell is None:
        raise ValueError(f"The notebook has no cell {cell_id}")
    images = [
        out["data"][mime]
        for out in cell.get("outputs", [])
        if mime in (out.get("data") or {})
    ]
    if not images:
        shown = sorted(
            {
                m
                for out in cell.get("outputs", [])
                for m in (out.get("data") or {})
                if m in CELL_IMAGE_MIME_TYPES.values()
            }
        )
        hint = (
            f"; it shows {', '.join(shown)}, so save it as that, or name "
            "the figure's variable"
            if shown
            else "; name the figure's variable to save it from that"
        )
        raise ValueError(f"Cell {cell_id} shows no {mime} image" + hint)
    if len(images) > 1:
        raise ValueError(
            f"Cell {cell_id} shows {len(images)} images; name the variable "
            "of the figure to save"
        )
    data: str = (
        "".join(images[0]) if isinstance(images[0], list) else images[0]
    )
    if mime == "image/svg+xml":
        return data.encode("utf-8")
    return base64.b64decode(data)


def find_notebook_stages(ck_info: dict, notebook_path: str) -> list[str]:
    """The names of the pipeline's stages that run a notebook."""
    path = Path(notebook_path).as_posix()
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    return [
        name
        for name, stage in stages.items()
        if isinstance(stage, dict)
        and stage.get("kind") == "jupyter-notebook"
        and Path(str(stage.get("notebook_path", ""))).as_posix() == path
    ]


def get_cell_output_target(output: dict) -> tuple[str, str]:
    """What a cell output saves, e.g., ``("value", "k")`` or
    ``("figure", "figures/fit.pdf")``, which is unique within a stage.
    """
    for kind in ("value", "figure", "table"):
        if output.get(kind):
            return kind, str(output[kind])
    raise ValueError(
        "A cell output needs one of 'value', 'figure', or 'table'"
    )


def with_cell_output(outputs: list[dict], new: dict) -> list[dict]:
    """A stage's cell outputs with one added, replacing one that saves the
    same thing, e.g., when a value is marked again on another cell, and
    taking a figure or table's path from another of its kind.
    """
    target = get_cell_output_target(new)
    path = new.get("figure") or new.get("table")
    replaced = False
    out = []
    for existing in outputs:
        same = get_cell_output_target(existing) == target or (
            path is not None
            and path in (existing.get("figure"), existing.get("table"))
        )
        if same:
            if not replaced:
                out.append(new)
                replaced = True
            continue
        out.append(existing)
    if not replaced:
        out.append(new)
    return out


def without_cell_outputs(
    outputs: list[dict],
    value: str | None = None,
    path: str | None = None,
    cell: str | None = None,
) -> list[dict]:
    """A stage's cell outputs without those saving a value or a figure or
    table at a path, or saved after a cell.
    """
    return [
        o
        for o in outputs
        if not (
            (value is not None and o.get("value") == value)
            or (path is not None and path in (o.get("figure"), o.get("table")))
            or (cell is not None and o.get("cell") == cell)
        )
    ]


def get_cell_output_citation(
    output: dict, notebook_path: str, parameters: dict | None = None
) -> str | None:
    """The calkit.sty command a document shows a cell output with, or None
    for a table that isn't LaTeX, which needs a stage to typeset it.
    """
    if output.get("value"):
        source = (
            get_notebook_values_path(notebook_path, parameters)
            if parameters
            else Path(notebook_path).as_posix()
        )
        return f"\\ckvalue{{{source}}}{{{output['value']}}}"
    if output.get("figure"):
        return f"\\ckfigure{{{output['figure']}}}"
    if str(output.get("table", "")).lower().endswith(".tex"):
        return f"\\cktable{{{output['table']}}}"
    return None


def describe_cell_outputs(
    stage_name: str,
    stage: dict,
    nb: dict | None,
    values: dict | None = None,
) -> list[dict]:
    """A stage's cell outputs as editors show them: what each saves, the
    cell it's after and that cell's position, how a document cites it, and
    for a value, what the last run saved, from ``values``.
    """
    ids = get_cell_ids(nb) if nb is not None else []
    params = stage.get("parameters") or None
    described = []
    for output in stage.get("cell_outputs") or []:
        kind, target = get_cell_output_target(output)
        cell = output.get("cell")
        item = {
            "stage": stage_name,
            "kind": kind,
            "name" if kind == "value" else "path": target,
            "cell": cell,
            "cell_index": ids.index(cell) if cell in ids else None,
            "variable": output.get("variable"),
            "format": output.get("format"),
            "citation": get_cell_output_citation(
                output, stage["notebook_path"], params
            ),
        }
        if kind == "value" and values is not None and target in values:
            item["saved_value"] = values[target]
        described.append(item)
    return described


def get_notebook_stage(
    ck_info: dict, notebook_path: str, stage: str | None = None
) -> str:
    """The stage running a notebook, which must be in the pipeline for its
    cells' outputs to be saved, or the one named, if it runs it.

    Raises a ``ValueError`` saying what to do if there isn't one, or there
    are several.
    """
    names = find_notebook_stages(ck_info, notebook_path)
    if stage is not None:
        if stage not in names:
            raise ValueError(f"Stage '{stage}' doesn't run {notebook_path}")
        return stage
    if not names:
        raise ValueError(
            f"{notebook_path} isn't in the pipeline yet; add it first, e.g., "
            f"with 'calkit xr {notebook_path}'"
        )
    if len(names) > 1:
        raise ValueError(
            f"{notebook_path} is run by stages {', '.join(names)}; name one"
        )
    return names[0]


def mark_cell_output(
    notebook_path: str,
    output: dict,
    stage: str | None = None,
    cell_index: int | None = None,
    wdir: str | None = None,
) -> dict:
    """Mark a value, figure, or table a notebook's cell makes, in the stage
    running it in ``calkit.yaml``, to be saved whenever the pipeline runs
    it, replacing a mark saving the same thing.

    ``output`` is as ``NotebookCellOutput`` takes it. A cell named by
    ``cell_index`` instead of its ID gets one written into the notebook,
    with the rest of its cells, if they have none. Returns the stage, the
    output as saved, how a document cites it, and a warning, if any.
    Raises a ``ValueError`` saying what's wrong.
    """
    from pydantic import ValidationError

    import calkit
    from calkit.models.pipeline import JupyterNotebookStage, NotebookCellOutput

    def get_message(e: ValidationError) -> str:
        return "; ".join(
            str(err["msg"]).removeprefix("Value error, ") for err in e.errors()
        )

    notebook_path = Path(notebook_path).as_posix()
    fpath = os.path.join(wdir or ".", notebook_path)
    output = {k: v for k, v in output.items() if v is not None}
    if cell_index is not None and output.get("cell") is not None:
        raise ValueError("Name the cell by its ID or position, not both")
    ck_info = calkit.load_calkit_info(wdir=wdir)
    name = get_notebook_stage(ck_info, notebook_path, stage)
    try:
        with open(fpath, encoding="utf-8") as f:
            nb = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Can't read {notebook_path}: {e}")
    if cell_index is not None:
        n_cells = len(nb.get("cells", []))
        if not 0 <= cell_index < n_cells:
            raise ValueError(
                f"{notebook_path} has {n_cells} cells, not {cell_index + 1}"
            )
        if ensure_cell_ids(nb):
            with open(fpath, "w", encoding="utf-8", newline="\n") as f:
                json.dump(nb, f, indent=1)
                f.write("\n")
        output["cell"] = get_cell_ids(nb)[cell_index]
    elif output.get("cell") is not None and output["cell"] not in get_cell_ids(
        nb
    ):
        raise ValueError(f"{notebook_path} has no cell {output['cell']}")
    try:
        new = NotebookCellOutput.model_validate(output).model_dump(
            exclude_none=True
        )
    except ValidationError as e:
        raise ValueError(get_message(e))
    stage_dict = ck_info["pipeline"]["stages"][name]
    outputs = with_cell_output(
        [dict(o) for o in stage_dict.get("cell_outputs") or []], new
    )
    try:
        JupyterNotebookStage.model_validate(
            dict(stage_dict) | {"cell_outputs": outputs}
        )
    except ValidationError as e:
        raise ValueError(get_message(e))
    stage_dict["cell_outputs"] = outputs
    calkit.save_calkit_info(ck_info, wdir=wdir)
    warning = (
        f"{notebook_path}'s cell IDs count up from 0, as nbstripout writes "
        "them without --keep-id, so they change when cells are added; "
        "install it with --keep-id so marks stay on their cells"
        if has_ordinal_cell_ids(nb)
        else None
    )
    return {
        "stage": name,
        "output": new,
        "citation": get_cell_output_citation(
            new, notebook_path, stage_dict.get("parameters") or None
        ),
        "warning": warning,
    }


def unmark_cell_outputs(
    notebook_path: str,
    value: str | None = None,
    path: str | None = None,
    cell: str | None = None,
    stage: str | None = None,
    wdir: str | None = None,
) -> int:
    """Stop saving a value, a figure or table at a path, or everything
    saved after a cell, from a notebook, in ``calkit.yaml``.

    Returns how many marks were removed. Raises a ``ValueError`` if none
    match.
    """
    import calkit

    notebook_path = Path(notebook_path).as_posix()
    if not any((value, path, cell)):
        raise ValueError("Name a value, a figure or table's path, or a cell")
    ck_info = calkit.load_calkit_info(wdir=wdir)
    name = get_notebook_stage(ck_info, notebook_path, stage)
    stage_dict = ck_info["pipeline"]["stages"][name]
    before = [dict(o) for o in stage_dict.get("cell_outputs") or []]
    after = without_cell_outputs(before, value=value, path=path, cell=cell)
    if len(after) == len(before):
        raise ValueError(f"Nothing like that is marked in {notebook_path}")
    if after:
        stage_dict["cell_outputs"] = after
    else:
        del stage_dict["cell_outputs"]
    calkit.save_calkit_info(ck_info, wdir=wdir)
    return len(before) - len(after)


def list_cell_outputs(
    notebook_path: str, wdir: str | None = None
) -> list[dict]:
    """What a notebook's cells are marked to make, from each stage running
    it, as ``describe_cell_outputs`` gives them, with the values the last
    run saved.
    """
    import calkit

    notebook_path = Path(notebook_path).as_posix()
    ck_info = calkit.load_calkit_info(wdir=wdir, read_only=True)
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    nb = None
    try:
        with open(
            os.path.join(wdir or ".", notebook_path), encoding="utf-8"
        ) as f:
            nb = json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    described = []
    for name in find_notebook_stages(ck_info, notebook_path):
        stage = stages[name]
        values = None
        values_path = get_notebook_values_path(
            notebook_path, parameters=stage.get("parameters") or None
        )
        try:
            with open(
                os.path.join(wdir or ".", values_path), encoding="utf-8"
            ) as f:
                values = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
        described += describe_cell_outputs(name, stage, nb, values=values)
    return described


# How much of a file to read when deciding whether it's a marimo notebook.
# marimo writes its header at the top, but a project's own license banner or
# module docstring comes first, so leave room for one.
MARIMO_DETECT_N_BYTES = 8192


def is_marimo_notebook(content: str) -> bool:
    """Determine whether some Python source is a marimo notebook.

    A marimo notebook is a Python module that constructs a ``marimo.App``,
    which is both what makes it one and what marimo itself writes at the top
    of every notebook it generates. Keyed on the constructor call rather
    than on the word 'marimo' appearing somewhere, so a script that merely
    imports or mentions marimo isn't mistaken for a notebook.
    """
    return "marimo.App(" in content


def get_cleaned_notebook_path(path: str, as_posix: bool = True) -> str:
    """Return the path of a cleaned notebook."""
    p = os.path.join(".calkit", "notebooks", "cleaned", path)
    if as_posix:
        p = Path(p).as_posix()
    return p


def clean_notebook(nb: dict) -> dict:
    """Strip a notebook's outputs, execution counts, and metadata in place.

    Cell tags survive, since they drive parameterization; everything else
    that isn't source is execution residue. The result is what a notebook
    stage depends on, so that re-running a notebook doesn't make its stage
    stale while editing a cell does.
    """
    for cell in nb.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
        # Cell IDs are editor residue, and nbstripout rewrites them to
        # ordinals. Keeping them would make the cleaned copy depend on whether
        # the source had been through a clean filter, which differs between a
        # working tree and a fresh clone of the same commit.
        cell.pop("id", None)
        # Clean metadata but keep tags
        if "tags" in cell.get("metadata", {}):
            cell["metadata"] = {"tags": cell["metadata"]["tags"]}
        else:
            cell["metadata"] = {}
    # Clean out notebook-level metadata
    nb["metadata"] = {}
    return nb


def clean_notebook_outputs(path: str):
    """Clean the outputs of a notebook and put it in the cleaned notebooks
    dir.
    """
    if os.path.isabs(path):
        raise ValueError("Path must be relative")
    fpath_out = get_cleaned_notebook_path(path)
    folder = os.path.dirname(fpath_out)
    os.makedirs(folder, exist_ok=True)
    fpath_out = os.path.abspath(fpath_out)
    with open(path, "r", encoding="utf-8") as f:
        try:
            nb = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from notebook: {e}")
    with open(fpath_out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(clean_notebook(nb), f, indent=2)


def clean_all_in_pipeline(ck_info: dict | None = None) -> list[str]:
    """Clean all notebooks in the pipeline."""
    if ck_info is None:
        import calkit

        ck_info = calkit.load_calkit_info()
    pipeline = ck_info.get("pipeline", {})
    stages = pipeline.get("stages", {})
    cleaned = []
    for _, stage in stages.items():
        if stage.get("kind") == "jupyter-notebook":
            path = stage.get("notebook_path")
            if path:
                clean_notebook_outputs(path)
                cleaned.append(path)
    return cleaned


def determine_storage(
    notebook_path: str,
    size_multiplier: float = 3.0,
) -> Literal["git", "dvc"]:
    if not os.path.exists(notebook_path):
        return "dvc"
    try:
        file_size = os.path.getsize(notebook_path)
    except OSError:
        return "dvc"
    source_bytes = 0
    try:
        with open(notebook_path, "r", encoding="utf-8") as f:
            nb = json.load(f)
        for cell in nb.get("cells", []):
            source = cell.get("source", [])
            if isinstance(source, list):
                source_bytes += len("".join(source).encode("utf-8"))
            else:
                source_bytes += len(str(source).encode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        source_bytes = file_size
    estimated_bytes = max(file_size, source_bytes) * size_multiplier
    from calkit.core import DVC_SIZE_THRESH_BYTES

    return "git" if estimated_bytes <= DVC_SIZE_THRESH_BYTES else "dvc"


def declare_notebook(
    path: str,
    stage_name: str,
    environment_name: str,
    inputs: list[str | PathInput | InputsFromStageOutputs] = [],
    outputs: list[str | PathOutput] = [],
    always_run: bool = False,
    title: str | None = None,
    description: str | None = None,
    html_storage: Literal["git", "dvc"] | None = "dvc",
    executed_ipynb_storage: Literal["git", "dvc"] | None = "dvc",
    cleaned_ipynb_storage: Literal["git", "dvc"] | None = "git",
):
    """Declare a notebook as part of the current project.

    If this function is called as part of a running pipeline, it will fail
    if anything has changed about the pipeline declaration, then prompt the
    user to rerun.
    """
    import calkit
    from calkit.models.pipeline import JupyterNotebookStage, Pipeline

    # Detect the project root directory so we ensure calkit.yaml lives there
    repo = calkit.git.get_repo()
    wdir = repo.working_dir
    if not os.path.isfile(os.path.join(wdir, path)):
        raise FileNotFoundError(
            f"Notebook '{path}' does not exist in the project directory"
        )
    pipeline_running = os.getenv("CALKIT_PIPELINE_RUNNING", "0") == "1"
    ck_info = calkit.load_calkit_info(wdir=str(wdir))
    envs = ck_info.get("environments", {})
    if environment_name not in envs:
        raise ValueError(
            f"Environment '{environment_name}' does not exist in calkit.yaml"
        )
    # TODO: Check that we are running in the correct environment
    # This could be tricky depending on what type of environment it is
    pipeline_dict = ck_info.get("pipeline", {})
    if "stages" not in pipeline_dict:
        pipeline_dict["stages"] = {}
    pipeline = Pipeline.model_validate(pipeline_dict)
    new_stage = JupyterNotebookStage(
        notebook_path=path,
        environment=environment_name,
        inputs=inputs,
        outputs=outputs,
        always_run=always_run,
        html_storage=html_storage,
        executed_ipynb_storage=executed_ipynb_storage,
        cleaned_ipynb_storage=cleaned_ipynb_storage,
    )
    stages = pipeline.stages
    must_be_rerun = False
    # Check to see if we're mutating an existing stage
    if pipeline_running and stage_name in stages:
        # If the pipeline is running, we can't change the stage
        existing_stage = stages[stage_name]
        if existing_stage != new_stage:
            must_be_rerun = True
    new_stage_dump = new_stage.model_dump()
    new_stage_dict = {
        "kind": "jupyter-notebook",
        "notebook_path": path,
        "environment": environment_name,
    }
    if inputs:
        new_stage_dict["inputs"] = new_stage_dump["inputs"]
    if outputs:
        new_stage_dict["outputs"] = new_stage_dump["outputs"]
    if always_run:
        new_stage_dict["always_run"] = always_run  # type: ignore
    new_stage_dict.update(
        {
            "html_storage": html_storage,
            "executed_ipynb_storage": executed_ipynb_storage,
            "cleaned_ipynb_storage": cleaned_ipynb_storage,
        }  # type: ignore
    )
    pipeline_dict["stages"][stage_name] = new_stage_dict
    # Update existing notebook if it exists, else append
    notebooks = ck_info.get("notebooks", [])
    updated = False
    for notebook in notebooks:
        if notebook.get("path") == path:
            notebook.update(
                {
                    "title": title,
                    "description": description,
                    "stage": stage_name,
                }
            )
            updated = True
            break
    if not updated:
        notebooks.append(
            {
                "path": path,
                "title": title,
                "description": description,
                "stage": stage_name,
            }
        )
    # Write calkit.yaml
    ck_info["pipeline"] = pipeline_dict
    ck_info["notebooks"] = notebooks
    calkit.save_calkit_info(ck_info, wdir=wdir)
    if must_be_rerun:
        raise RuntimeError(
            f"Notebook stage '{stage_name}' was modified while the pipeline "
            "was running; please run the pipeline again"
        )
    # TODO: Change to the correct working directory?
