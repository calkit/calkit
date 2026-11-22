"""Functionality for working with notebooks."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from calkit.models.io import (
        InputsFromStageOutputs,
        PathInput,
        PathOutput,
    )


def get_parameters_text(parameters: dict[str, Any]) -> str:
    """Parameters as text for a file name, e.g., ``t-25-cases-a,b``, with a
    hash for a long list or a dict.
    """
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
    return "-".join(f"{k}-{v}" for k, v in parameters_cleaned.items())


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
        params_txt = get_parameters_text(parameters)
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
        # NaN and infinity aren't JSON, so they're saved as nulls
        if isinstance(value, float) and value - value != 0:
            return None
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
            return to_data(float(value), what, strict)
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
        names = out.get("variable_names") or [out.get("variable_name")]
        for name in names:
            if name is not None and name not in user:
                raise NameError(
                    f"Calkit: there's no variable '{name}' after {where} to "
                    f"save as {out.get('output_path') or 'a value'}"
                )
        name = names[0]
        what = f"'{name}'"
        if name is None:
            continue
        if out["kind"] == "value":
            values = {}
            if os.path.isfile(values_path):
                with open(values_path, encoding="utf-8") as f:
                    values = json.load(f)
            for name in names:
                values[name] = to_data(user[name], f"'{name}'")
                # The values file is kept in Git, so a big array belongs in
                # a file of its own
                n_kb = len(json.dumps(values[name])) // 1000
                if n_kb > 100:
                    raise ValueError(
                        f"Calkit: can't save '{name}' after {where} as a "
                        f"value, since it's {n_kb} kB; save it as a table, "
                        "or write it to a file the stage outputs"
                    )
            os.makedirs(os.path.dirname(values_path) or ".", exist_ok=True)
            with open(values_path, "w", encoding="utf-8") as f:
                json.dump(values, f, indent=2)
        elif out["kind"] == "figure":
            save_figure(user[name], out["output_path"], what)
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
    ``.calkit/notebooks/outputs/nbs/fit.ipynb/values.json`` for
    ``nbs/fit.ipynb``, or in a folder in that named for its parameters,
    e.g., ``fit.ipynb/t-25/values.json``.
    """
    folder = ".calkit/notebooks/outputs/" + posixpath.normpath(
        notebook_path.replace("\\", "/")
    )
    if parameters:
        folder += "/" + get_parameters_text(parameters)
    return folder + "/values.json"


def get_notebook_of_values_path(path: str) -> str | None:
    """The notebook a values file was saved from, for one without
    parameters, which is how a value from it is cited.
    """
    prefix = ".calkit/notebooks/outputs/"
    path = path.replace("\\", "/")
    if not (path.startswith(prefix) and path.endswith("/values.json")):
        return None
    name = path.removeprefix(prefix).removesuffix("/values.json")
    return name if name.lower().endswith(".ipynb") else None


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
    them, with a figure's ``output_path`` relative to where the kernel runs,
    like
    ``values_path`` and ``tables_dir``. Raises a
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
        cell = out.get("cell_id")
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
        and get_stage_notebook_path(stage) == path
    ]


def get_stage_notebook_path(stage: dict) -> str:
    """The notebook a stage runs, relative to the project rather than its
    ``wdir``.
    """
    return posixpath.normpath(
        posixpath.join(
            stage.get("wdir") or "",
            Path(str(stage.get("notebook_path", ""))).as_posix(),
        )
    )


def get_stage_values_path(stage: dict, ck_info: dict | None = None) -> str:
    """Where a notebook stage saves the values its cells make, relative to
    the project: in its ``wdir``, named for the parameters it runs with,
    as resolved from the project's in ``ck_info``.
    """
    from calkit.models.iteration import expand_project_parameters
    from calkit.models.pipeline import get_resolved_notebook_parameters

    params = stage.get("parameters") or None
    if params:
        params = get_resolved_notebook_parameters(
            params,
            expand_project_parameters((ck_info or {}).get("parameters") or {}),
        )
    values_path = get_notebook_values_path(
        Path(str(stage.get("notebook_path", ""))).as_posix(), params
    )
    return posixpath.normpath(
        posixpath.join(stage.get("wdir") or "", values_path)
    )


def get_normalized_output_path(path: str) -> str:
    """A figure or table's path with forward slashes, as a document cites
    it, since TeX reads a backslash as a command.
    """
    return posixpath.normpath(path.replace("\\", "/"))


def get_value_names(output: dict) -> list[str]:
    """The variables a value output is saved from, whether it names one or
    several.
    """
    names = output.get("variable_names")
    if names is None:
        names = [output.get("variable_name")]
    return [str(n) for n in names if n is not None]


def get_value_output_with_names(output: dict, names: list[str]) -> dict:
    """A value output saving these variables, named as ``variable_name``
    if there's one, and ``variable_names`` if there are several.
    """
    new = {
        k: v
        for k, v in output.items()
        if k not in ("variable_name", "variable_names")
    }
    if len(names) == 1:
        new["variable_name"] = names[0]
    else:
        new["variable_names"] = names
    return new


def get_cell_outputs_with(outputs: list[dict], new: dict) -> list[dict]:
    """A stage's cell outputs with one added: values join the others saved
    after the same cell, and move from wherever else they're saved, and a
    figure or table replaces one saved to the same path.
    """
    if new.get("kind") == "value":
        names = get_value_names(new)
        out = []
        merged = False
        for existing in outputs:
            if existing.get("kind") != "value":
                out.append(existing)
                continue
            rest = [n for n in get_value_names(existing) if n not in names]
            if existing.get("cell_id") == new.get("cell_id") and not merged:
                out.append(get_value_output_with_names(existing, rest + names))
                merged = True
            elif rest:
                out.append(get_value_output_with_names(existing, rest))
        if not merged:
            out.append(new)
        return out
    path = get_normalized_output_path(str(new.get("output_path")))
    replaced = False
    out = []
    for existing in outputs:
        if existing.get("kind") != "value" and (
            get_normalized_output_path(str(existing.get("output_path")))
            == path
        ):
            if not replaced:
                out.append(new)
                replaced = True
            continue
        out.append(existing)
    if not replaced:
        out.append(new)
    return out


def get_cell_outputs_without(
    outputs: list[dict],
    variable_name: str | None = None,
    output_path: str | None = None,
    cell_id: str | None = None,
) -> list[dict]:
    """A stage's cell outputs without a value by its variable's name, a
    figure or table at a path, or anything after a cell.
    """
    out = []
    for o in outputs:
        if cell_id is not None and o.get("cell_id") == cell_id:
            continue
        if (
            output_path is not None
            and o.get("kind") != "value"
            and get_normalized_output_path(str(o.get("output_path")))
            == get_normalized_output_path(output_path)
        ):
            continue
        if variable_name is not None and o.get("kind") == "value":
            names = get_value_names(o)
            if variable_name in names:
                rest = [n for n in names if n != variable_name]
                if rest:
                    out.append(get_value_output_with_names(o, rest))
                continue
        out.append(o)
    return out


def get_cell_output_citation(
    output: dict, stage: dict, ck_info: dict | None = None
) -> str | None:
    """The calkit.sty command a document shows a cell output with, or None
    for a table that isn't LaTeX, which needs a stage to typeset it. A
    value's output names one variable, as ``describe_cell_outputs`` gives
    them.

    A value is cited by its notebook, unless the stage's parameters or
    ``wdir`` put its values file somewhere else, which is then cited.
    """
    kind = output.get("kind")
    if kind == "value":
        notebook_path = get_stage_notebook_path(stage)
        source = get_stage_values_path(stage, ck_info)
        if source == get_notebook_values_path(notebook_path):
            source = notebook_path
        return f"\\ckvalue{{{source}}}{{{output['variable_name']}}}"
    path = posixpath.normpath(
        posixpath.join(stage.get("wdir") or "", str(output.get("output_path")))
    )
    if kind == "figure":
        return f"\\ckfigure{{{path}}}"
    if kind == "table" and path.lower().endswith(".tex"):
        return f"\\cktable{{{path}}}"
    return None


def describe_cell_outputs(
    stage_name: str,
    stage: dict,
    nb: dict | None,
    values: dict | None = None,
    ck_info: dict | None = None,
) -> list[dict]:
    """A stage's cell outputs as editors show them, one for each value even
    if saved with others: what each saves, the cell it's after and that
    cell's position, how a document cites it, and for a value, what the
    last run saved, from ``values``.
    """
    ids = get_cell_ids(nb) if nb is not None else []
    described = []
    for output in stage.get("cell_outputs") or []:
        singles = (
            [
                get_value_output_with_names(output, [name])
                for name in get_value_names(output)
            ]
            if output.get("kind") == "value"
            else [output]
        )
        for single in singles:
            cell_id = single.get("cell_id")
            name = single.get("variable_name")
            item = {
                "stage": stage_name,
                "kind": single.get("kind"),
                "cell_id": cell_id,
                "cell_index": ids.index(cell_id) if cell_id in ids else None,
                "variable_name": name,
                "output_path": single.get("output_path"),
                "format": single.get("format"),
                "citation": get_cell_output_citation(single, stage, ck_info),
            }
            if item["kind"] == "value" and values is not None:
                if name in values:
                    item["saved_value"] = values[name]
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
        # Quarto saves what a notebook makes its own way
        path = Path(notebook_path).as_posix()
        stages = (ck_info.get("pipeline") or {}).get("stages") or {}
        for name, s in stages.items():
            if (
                isinstance(s, dict)
                and s.get("kind") == "quarto"
                and posixpath.normpath(
                    posixpath.join(
                        s.get("wdir") or "", str(s.get("target_path", ""))
                    )
                )
                == path
            ):
                raise ValueError(
                    f"{notebook_path} is rendered by Quarto stage '{name}', "
                    "which can't save cell outputs; use Quarto's embed "
                    "shortcode or inline code instead"
                )
        raise ValueError(
            f"{notebook_path} isn't in the pipeline yet; add it first, e.g., "
            f"with 'calkit xr {notebook_path}'"
        )
    if len(names) > 1:
        raise ValueError(
            f"{notebook_path} is run by stages {', '.join(names)}; name one"
        )
    return names[0]


def add_cell_output(
    notebook_path: str,
    output: dict,
    stage: str | None = None,
    cell_index: int | None = None,
    wdir: str | None = None,
) -> dict:
    """Add a value, figure, or table a notebook's cell makes to the outputs
    of the stage running it in ``calkit.yaml``, to be saved whenever the
    pipeline runs it, as ``get_cell_outputs_with`` adds it.

    ``output`` is as ``NotebookCellOutput`` takes it. A cell named by
    ``cell_index`` instead of its ID gets one written into the notebook,
    with the rest of its cells, if they have none. Returns the stage, the
    output as given, how a document cites each value, figure, or table it
    saves, and a warning, if any. Raises a ``ValueError`` saying what's
    wrong.
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
    if cell_index is not None and output.get("cell_id") is not None:
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
            # As Jupyter writes it, so only the IDs change
            with open(fpath, "w", encoding="utf-8", newline="\n") as f:
                json.dump(nb, f, indent=1, sort_keys=True, ensure_ascii=False)
                f.write("\n")
        output["cell_id"] = get_cell_ids(nb)[cell_index]
    elif output.get("cell_id") is not None and output[
        "cell_id"
    ] not in get_cell_ids(nb):
        raise ValueError(f"{notebook_path} has no cell {output['cell_id']}")
    try:
        new = NotebookCellOutput.model_validate(output).model_dump(
            exclude_none=True
        )
    except ValidationError as e:
        raise ValueError(get_message(e))
    stage_dict = ck_info["pipeline"]["stages"][name]
    outputs = get_cell_outputs_with(
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
        "install it with --keep-id so outputs stay on their cells"
        if has_ordinal_cell_ids(nb)
        else None
    )
    singles = (
        [get_value_output_with_names(new, [n]) for n in get_value_names(new)]
        if new["kind"] == "value"
        else [new]
    )
    citations = [
        get_cell_output_citation(single, stage_dict, ck_info)
        for single in singles
    ]
    return {
        "stage": name,
        "output": new,
        "citations": [c for c in citations if c is not None],
        "warning": warning,
    }


def remove_cell_outputs(
    notebook_path: str,
    variable_name: str | None = None,
    output_path: str | None = None,
    cell_id: str | None = None,
    stage: str | None = None,
    wdir: str | None = None,
) -> int:
    """Stop saving a value, a figure or table at a path, or everything
    saved after a cell, from a notebook, in ``calkit.yaml``.

    Returns how many values, figures, and tables were removed. Raises a
    ``ValueError`` if none match.
    """
    import calkit

    def count_saved(outputs: list[dict]) -> int:
        return sum(
            len(get_value_names(o)) if o.get("kind") == "value" else 1
            for o in outputs
        )

    notebook_path = Path(notebook_path).as_posix()
    if not any((variable_name, output_path, cell_id)):
        raise ValueError("Name a value, a figure or table's path, or a cell")
    ck_info = calkit.load_calkit_info(wdir=wdir)
    name = get_notebook_stage(ck_info, notebook_path, stage)
    stage_dict = ck_info["pipeline"]["stages"][name]
    before = [dict(o) for o in stage_dict.get("cell_outputs") or []]
    after = get_cell_outputs_without(
        before,
        variable_name=variable_name,
        output_path=output_path,
        cell_id=cell_id,
    )
    n_removed = count_saved(before) - count_saved(after)
    if not n_removed:
        raise ValueError(f"Nothing like that is saved from {notebook_path}")
    if after:
        stage_dict["cell_outputs"] = after
    else:
        del stage_dict["cell_outputs"]
    calkit.save_calkit_info(ck_info, wdir=wdir)
    return n_removed


def list_cell_outputs(
    notebook_path: str, wdir: str | None = None
) -> list[dict]:
    """What a notebook's cells save, from each stage running
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
        values_path = get_stage_values_path(stage, ck_info)
        try:
            with open(
                os.path.join(wdir or ".", values_path), encoding="utf-8"
            ) as f:
                values = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
        described += describe_cell_outputs(
            name, stage, nb, values=values, ck_info=ck_info
        )
    return described


def get_cell_variables(source: str) -> list[str]:
    """Variables a cell prints or shows, since a printed number is likely
    one of them, those assigned there first, then what a loop printing
    them goes through, then the rest it assigns at its top level, last
    assigned first, with loop variables last, since they only hold the last
    item.
    """
    import ast

    def get_shown(node: ast.AST) -> list[str]:
        # Names whose values are shown, not functions called or modules
        # whose attributes are, e.g., k but not np in print(np.mean(k))
        skip = {
            id(n.func) for n in ast.walk(node) if isinstance(n, ast.Call)
        } | {
            id(n.value) for n in ast.walk(node) if isinstance(n, ast.Attribute)
        }
        return [
            n.id
            for n in ast.walk(node)
            if isinstance(n, ast.Name) and id(n) not in skip
        ]

    def get_names(node: ast.AST) -> list[str]:
        return [n.id for n in ast.walk(node) if isinstance(n, ast.Name)]

    def prints(node: ast.AST) -> list[str]:
        return [
            name
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id in ("print", "display")
            for name in get_shown(n)
        ]

    # IPython's magics and shell commands aren't Python
    lines = [
        "" if line.lstrip().startswith(("%", "!")) else line
        for line in source.splitlines()
    ]
    try:
        tree = ast.parse("\n".join(lines))
    except SyntaxError:
        return []
    assigned: list[str] = []
    looped: list[str] = []
    shown: list[str] = []
    iterated: list[str] = []
    for stmt in tree.body:
        targets: list[ast.AST] = []
        if isinstance(stmt, ast.Assign):
            targets = list(stmt.targets)
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
            targets = [stmt.target]
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            targets = [i.optional_vars for i in stmt.items if i.optional_vars]
        elif isinstance(stmt, (ast.For, ast.AsyncFor)):
            looped += get_names(stmt.target)
            if prints(stmt):
                # What's gone through, e.g., rates in rates.items() or
                # zip(temps, rates), but not the functions called
                called = {
                    id(n.func)
                    for n in ast.walk(stmt.iter)
                    if isinstance(n, ast.Call)
                }
                iterated += [
                    n.id
                    for n in ast.walk(stmt.iter)
                    if isinstance(n, ast.Name) and id(n) not in called
                ]
        for target in targets:
            for name in get_names(target):
                if name in assigned:
                    assigned.remove(name)
                assigned.append(name)
        shown += prints(stmt)
        if stmt is tree.body[-1] and isinstance(stmt, ast.Expr):
            shown += get_shown(stmt)
    names = list(reversed(assigned))
    loop_names = set(looped) - set(assigned)
    return list(
        dict.fromkeys(
            [n for n in names if n in shown]
            + [n for n in shown if n not in names and n not in loop_names]
            + [n for n in iterated if n not in loop_names]
            + names
            + list(reversed(looped))
        )
    )


def find_printed_numbers(nb: dict) -> list[dict]:
    """Numbers a notebook's code cells printed or showed, as text, from
    their saved outputs, which a number typed into a document may have been
    copied from, with each cell's ID and position, and the variables it
    assigns, which one of them likely holds.
    """
    import re

    number = re.compile(
        r"(?<![\w.])[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?(?![\w.])"
    )
    found = []
    for i, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") != "code" or not cell.get("id"):
            continue
        texts = []
        for out in cell.get("outputs", []):
            if out.get("output_type") == "stream":
                texts.append(out.get("text", ""))
            elif "text/plain" in (out.get("data") or {}):
                texts.append(out["data"]["text/plain"])
        text = "".join("".join(t) if isinstance(t, list) else t for t in texts)
        numbers = list(dict.fromkeys(m.group() for m in number.finditer(text)))
        if not numbers:
            continue
        source = cell.get("source", "")
        found.append(
            {
                "cell": cell["id"],
                "cell_index": i,
                "numbers": numbers,
                "variables": get_cell_variables(
                    "".join(source) if isinstance(source, list) else source
                ),
            }
        )
    return found


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
        # A cell's source may be one string or a list of lines, which tools
        # rewrite between, e.g., Quarto when rendering with --execute
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        cell["source"] = source.splitlines(keepends=True)
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
        # Quarto writes a notebook's outputs back into it when rendering it
        # with --execute, so it's depended on stripped of them too
        elif stage.get("kind") == "quarto":
            target = stage.get("target_path") or ""
            path = posixpath.normpath(
                posixpath.join(stage.get("wdir") or "", target)
            )
            args = stage.get("args") or []
            executes = "--execute" in args and "--no-execute" not in args
            if target.endswith(".ipynb") and executes and os.path.isfile(path):
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
