"""Tests for ``calkit.notebooks``."""

import base64
import json
import os
import subprocess
import tempfile

import pytest
from git.exc import InvalidGitRepositoryError

import calkit


def test_declare_notebook(tmp_dir):
    with pytest.raises(InvalidGitRepositoryError):
        calkit.declare_notebook(
            path="my-notebook.ipynb",
            stage_name="my-stage",
            environment_name="my-env",
        )
    subprocess.check_call(["calkit", "init"])
    with open("my-notebook.ipynb", "w") as f:
        f.write(
            """{
                "cells": [],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5
            }"""
        )
    # Create a dummy environment
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "environments": {
                    "my-env": {
                        "kind": "uv-venv",
                        "path": "something.txt",
                    }
                },
            },
            f,
        )
    calkit.declare_notebook(
        path="my-notebook.ipynb",
        stage_name="my-stage",
        environment_name="my-env",
        title="My Notebook",
        description="This is a test notebook",
        inputs=["data.txt"],
        outputs=[],
        always_run=False,
        html_storage=None,
        executed_ipynb_storage=None,
        cleaned_ipynb_storage=None,
    )
    ck_info = calkit.load_calkit_info()
    assert ck_info["notebooks"] == [
        {
            "path": "my-notebook.ipynb",
            "title": "My Notebook",
            "description": "This is a test notebook",
            "stage": "my-stage",
        }
    ]
    stage = ck_info["pipeline"]["stages"]["my-stage"]
    assert stage["kind"] == "jupyter-notebook"
    assert stage["notebook_path"] == "my-notebook.ipynb"
    assert stage["environment"] == "my-env"
    assert stage["inputs"] == ["data.txt"]
    assert "always_run" not in stage
    assert "outputs" not in stage
    assert stage["html_storage"] is None


def test_determine_storage(tmp_dir):
    notebook_path = "small.ipynb"
    with open(notebook_path, "w") as f:
        json.dump(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "metadata": {},
                        "source": ["print('hello')\n"],
                    }
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            },
            f,
        )
    assert calkit.notebooks.determine_storage(notebook_path) == "git"
    assert calkit.notebooks.determine_storage("missing.ipynb") == "dvc"


def test_is_marimo_notebook():
    # What marimo itself writes at the top of every notebook it generates
    generated = (
        "import marimo\n"
        "\n"
        '__generated_with = "0.19.4"\n'
        "app = marimo.App()\n"
        "\n"
        "\n"
        "@app.cell\n"
        "def _():\n"
        "    print(1)\n"
        "    return\n"
    )
    assert calkit.notebooks.is_marimo_notebook(generated)
    # Options in the constructor call, and a license banner ahead of it,
    # don't change the answer
    assert calkit.notebooks.is_marimo_notebook(
        '"""Copyright.\n\nA long banner.\n"""\n'
        "import marimo\n"
        'app = marimo.App(width="medium")\n'
    )
    # A script that merely imports or mentions marimo isn't a notebook, which
    # is the case a plain 'marimo' substring check gets wrong
    for not_a_notebook in [
        "import marimo\nprint('not a notebook')\n",
        "# Convert this to marimo someday\nprint(1)\n",
        '"""Utilities for our marimo apps."""\nimport pandas as pd\n',
        "",
    ]:
        assert not calkit.notebooks.is_marimo_notebook(not_a_notebook)


def test_get_notebook_values_path():
    path = calkit.notebooks.get_notebook_values_path("fit.ipynb")
    assert path == ".calkit/notebooks/outputs/fit.ipynb/values.json"
    assert calkit.notebooks.get_notebook_of_values_path(path) == "fit.ipynb"
    path = calkit.notebooks.get_notebook_values_path("nbs/fit.ipynb")
    assert path == ".calkit/notebooks/outputs/nbs/fit.ipynb/values.json"
    assert (
        calkit.notebooks.get_notebook_of_values_path(path) == "nbs/fit.ipynb"
    )
    # Parameters name a folder in the notebook's, which isn't how a value is
    # cited
    path = calkit.notebooks.get_notebook_values_path("fit.ipynb", {"t": 25})
    assert path == ".calkit/notebooks/outputs/fit.ipynb/t-25/values.json"
    assert calkit.notebooks.get_notebook_of_values_path(path) is None
    assert calkit.notebooks.get_notebook_values_path(".\\nbs\\fit.ipynb") == (
        ".calkit/notebooks/outputs/nbs/fit.ipynb/values.json"
    )
    assert (
        calkit.notebooks.get_notebook_of_values_path("results/v.json") is None
    )


def test_cell_ids():
    nb = {
        "nbformat": 4,
        "nbformat_minor": 4,
        "cells": [{"cell_type": "code", "source": ""} for _ in range(3)],
    }
    assert calkit.notebooks.get_cell_ids(nb) == [None, None, None]
    assert calkit.notebooks.ensure_cell_ids(nb)
    ids = calkit.notebooks.get_cell_ids(nb)
    assert all(ids) and len(set(ids)) == 3
    assert nb["nbformat_minor"] == 5
    assert not calkit.notebooks.ensure_cell_ids(nb)
    assert not calkit.notebooks.has_ordinal_cell_ids(nb)
    # What nbstripout writes without --keep-id
    for i, cell in enumerate(nb["cells"]):
        cell["id"] = str(i)
    assert calkit.notebooks.has_ordinal_cell_ids(nb)


def test_capture_cells():
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {"cell_type": "code", "id": "a", "source": "x = 1"},
            {"cell_type": "markdown", "id": "b", "source": "# Hi"},
            {"cell_type": "code", "id": "c", "source": "x = 2"},
        ],
    }
    outputs = [
        {"kind": "value", "cell_id": "c", "variable_name": "x"},
        {"kind": "value", "variable_name": "y"},
        {
            "kind": "figure",
            "cell_id": "a",
            "variable_name": "fig",
            "output_path": "../f.png",
        },
        {"kind": "value", "cell_id": "a", "variable_name": "z"},
    ]
    captured = calkit.notebooks.add_capture_cells(nb, outputs, "v.json", "t")
    sources = [c["source"] for c in captured["cells"]]
    # The helper first, then one after each cell with outputs, in order, and
    # one at the end for those with no cell
    assert sources[0] == calkit.notebooks.CAPTURE_HELPER
    assert sources[1] == "x = 1"
    assert sources[2].startswith("_calkit_save_cell_outputs('cell a', ")
    assert '[[2, {"kind": "figure", "cell_id": "a"' in sources[2]
    assert (
        '[3, {"kind": "value", "cell_id": "a", "variable_name": "z"}]'
        in (sources[2])
    )
    assert sources[3:5] == ["# Hi", "x = 2"]
    assert (
        '[[0, {"kind": "value", "cell_id": "c", "variable_name": "x"}]]'
        in (sources[5])
    )
    assert sources[6].startswith("_calkit_save_cell_outputs('the last cell'")
    assert "'v.json', 't')" in sources[6]
    assert len({c["id"] for c in captured["cells"]}) == 7
    # The notebook given isn't changed, and the added cells come out again
    assert len(nb["cells"]) == 3
    assert calkit.notebooks.remove_capture_cells(captured) == nb
    with pytest.raises(ValueError, match="no cell zz"):
        calkit.notebooks.add_capture_cells(
            nb,
            [{"kind": "value", "cell_id": "zz", "variable_name": "x"}],
            "v.json",
            "t",
        )
    # The helper saves values, figures, and tables in the kernel, failing
    # with what to do about anything it can't
    namespace: dict = {}
    exec(calkit.notebooks.CAPTURE_HELPER, namespace)
    save = namespace["_calkit_save_cell_outputs"]
    namespace.update(
        k=0.25,
        rates={"25C": 0.031, 35: (1, 2), "45C": float("nan")},
        rows=[{"T": 25, "k": 0.031}, {"T": 35, "k": 0.062}],
        cols={"T": [25, 35], "k": [0.031, 0.062]},
        grid=[["T", "k"], [25, 0.031]],
        bad=object(),
        big=list(range(30_000)),
    )
    with tempfile.TemporaryDirectory() as tmp:
        values = os.path.join(tmp, "v", "values.json")
        tables = os.path.join(tmp, "tables")
        save(
            "cell a",
            [
                [0, {"kind": "value", "variable_name": "k"}],
                [1, {"kind": "value", "variable_name": "rates"}],
                [2, {"kind": "table", "variable_name": "rows"}],
                [3, {"kind": "table", "variable_name": "cols"}],
                [4, {"kind": "table", "variable_name": "grid"}],
            ],
            values,
            tables,
        )
        with open(values) as f:
            assert json.load(f) == {
                "k": 0.25,
                "rates": {"25C": 0.031, "35": [1, 2], "45C": None},
            }
        expected = {
            "columns": ["T", "k"],
            "index": None,
            "index_name": None,
            "data": [[25, 0.031], [35, 0.062]],
        }
        for i in (2, 3):
            with open(os.path.join(tables, f"{i}.json")) as f:
                assert json.load(f) == expected
        with open(os.path.join(tables, "4.json")) as f:
            assert json.load(f)["data"] == [[25, 0.031]]
        failures = [
            (
                {"kind": "value", "variable_name": "missing"},
                NameError,
                "no variable 'missing'",
            ),
            (
                {"kind": "value", "variable_name": "bad"},
                TypeError,
                "since it's a object",
            ),
            ({"kind": "table", "variable_name": "k"}, TypeError, "as a table"),
            ({"kind": "value", "variable_name": "big"}, ValueError, "kB"),
            (
                {
                    "kind": "figure",
                    "variable_name": "k",
                    "output_path": "f.png",
                },
                TypeError,
                "as a figure",
            ),
        ]
        for out, error, message in failures:
            with pytest.raises(error, match=message):
                save("cell a", [[0, out]], values, tables)


def test_get_cell_image():
    png = base64.b64encode(b"png bytes").decode()
    nb = {
        "cells": [
            {
                "id": "a",
                "outputs": [
                    {"output_type": "stream", "text": "hi"},
                    {"data": {"image/png": png, "text/plain": "<Figure>"}},
                    {"data": {"image/svg+xml": ["<svg>", "</svg>"]}},
                ],
            },
            {"id": "b", "outputs": [{"data": {"image/png": png}}] * 2},
            {"id": "c", "outputs": []},
        ]
    }
    assert calkit.notebooks.get_cell_image(nb, "a", ".png") == b"png bytes"
    assert calkit.notebooks.get_cell_image(nb, "a", ".SVG") == b"<svg></svg>"
    with pytest.raises(ValueError, match="it shows image/png, image/svg"):
        calkit.notebooks.get_cell_image(nb, "a", ".jpg")
    with pytest.raises(ValueError, match="shows 2 images"):
        calkit.notebooks.get_cell_image(nb, "b", ".png")
    with pytest.raises(ValueError, match="name the figure's variable"):
        calkit.notebooks.get_cell_image(nb, "c", ".png")
    with pytest.raises(ValueError, match="no cell d"):
        calkit.notebooks.get_cell_image(nb, "d", ".png")


def test_cell_output_marks():
    ck_info = {
        "pipeline": {
            "stages": {
                "fit": {
                    "kind": "jupyter-notebook",
                    "notebook_path": "fit.ipynb",
                },
                "fit-2": {
                    "kind": "jupyter-notebook",
                    "notebook_path": "./fit.ipynb",
                },
                "other": {"kind": "python-script", "script_path": "fit.ipynb"},
            }
        }
    }
    assert calkit.notebooks.find_notebook_stages(ck_info, "fit.ipynb") == [
        "fit",
        "fit-2",
    ]
    assert calkit.notebooks.find_notebook_stages({}, "fit.ipynb") == []
    value = {"kind": "value", "cell_id": "a", "variable_name": "k"}
    figure = {"kind": "figure", "cell_id": "b", "output_path": "f.png"}
    table = {
        "kind": "table",
        "cell_id": "b",
        "variable_name": "df",
        "output_path": "t.tex",
    }
    outputs = [value, figure, table]
    # A value saved again after another cell moves there, and a path takes
    # over from another output saved to it
    moved = value | {"cell_id": "c"}
    marked = calkit.notebooks.get_cell_outputs_with(outputs, moved)
    assert marked == [figure, table, moved]
    replacing = {
        "kind": "figure",
        "cell_id": "c",
        "variable_name": "fig",
        "output_path": "t.tex",
    }
    marked = calkit.notebooks.get_cell_outputs_with(outputs, replacing)
    assert marked == [value, figure, replacing]
    added = {"kind": "value", "variable_name": "j"}
    assert calkit.notebooks.get_cell_outputs_with(outputs, added)[-1] == added
    # Values saved after the same cell are kept together
    joined = calkit.notebooks.get_cell_outputs_with(
        outputs, {"kind": "value", "cell_id": "a", "variable_name": "j"}
    )
    assert joined[0] == {
        "kind": "value",
        "cell_id": "a",
        "variable_names": ["k", "j"],
    }
    without = calkit.notebooks.get_cell_outputs_without
    assert without(joined, variable_name="k")[0] == {
        "kind": "value",
        "cell_id": "a",
        "variable_name": "j",
    }
    assert without(outputs, variable_name="k") == [figure, table]
    assert without(outputs, variable_name="df") == outputs
    assert without(outputs, output_path="t.tex") == [value, figure]
    assert without(outputs, cell_id="b") == [value]
    stage = {
        "notebook_path": "fit.ipynb",
        "cell_outputs": outputs
        + [
            {
                "kind": "table",
                "cell_id": "gone",
                "variable_name": "df",
                "output_path": "t.csv",
            },
            added,
        ],
    }
    nb = {"cells": [{"id": "a"}, {"id": "x"}, {"id": "b"}]}
    described = calkit.notebooks.describe_cell_outputs(
        "fit", stage, nb, values={"k": 0.25}
    )
    assert described[0] == {
        "stage": "fit",
        "kind": "value",
        "cell_id": "a",
        "cell_index": 0,
        "variable_name": "k",
        "output_path": None,
        "format": None,
        "citation": r"\ckvalue{fit.ipynb}{k}",
        "saved_value": 0.25,
    }
    assert [d["cell_index"] for d in described] == [0, 2, 2, None, None]
    assert [d["citation"] for d in described[1:]] == [
        r"\ckfigure{f.png}",
        r"\cktable{t.tex}",
        None,
        r"\ckvalue{fit.ipynb}{j}",
    ]
    assert "saved_value" not in described[4]
    # A parameterized notebook's values are cited by their file
    stage["parameters"] = {"t": 25}
    described = calkit.notebooks.describe_cell_outputs("fit", stage, None)
    assert described[0]["citation"] == (
        r"\ckvalue{.calkit/notebooks/outputs/fit.ipynb/t-25/values.json}{k}"
    )
    assert described[0]["cell_index"] is None
    # Including one the project's parameters fill in, as the pipeline does
    stage["parameters"] = {"t": "{temp}"}
    described = calkit.notebooks.describe_cell_outputs(
        "fit", stage, None, ck_info={"parameters": {"temp": 35}}
    )
    assert described[0]["citation"] == (
        r"\ckvalue{.calkit/notebooks/outputs/fit.ipynb/t-35/values.json}{k}"
    )
    # A stage's wdir is part of every path cited, and of the notebook's
    in_sub = {"kind": "jupyter-notebook", "wdir": "sub"} | {
        k: v for k, v in stage.items() if k != "parameters"
    }
    assert calkit.notebooks.find_notebook_stages(
        {"pipeline": {"stages": {"sub": in_sub}}}, "sub/fit.ipynb"
    ) == ["sub"]
    assert calkit.notebooks.get_stage_values_path(in_sub) == (
        "sub/.calkit/notebooks/outputs/fit.ipynb/values.json"
    )
    described = calkit.notebooks.describe_cell_outputs("sub", in_sub, None)
    assert [d["citation"] for d in described[:2]] == [
        r"\ckvalue{sub/.calkit/notebooks/outputs/fit.ipynb/values.json}{k}",
        r"\ckfigure{sub/f.png}",
    ]


def test_find_printed_numbers():
    assert calkit.notebooks.get_cell_variables(
        "import numpy as np\n"
        "fig, ax = plt.subplots()\n"
        "k_25 = rates['25C']\n"
        "for t in temps:\n"
        "    x = 1\n"
        "with open('f') as f:\n"
        "    pass\n"
        "print(f'k = {k_25:.3f}', np.mean(z))\n"
        "%matplotlib inline\n"
        "rates"
    ) == ["k_25", "z", "rates", "f", "ax", "fig", "t"]
    # A loop printing what it goes through points to that, not to its loop
    # variables, which only hold the last item
    assert calkit.notebooks.get_cell_variables(
        "for temp, k in rates.items():\n    print(f'{temp} C: k = {k:.4f}')"
    ) == ["rates", "k", "temp"]
    assert calkit.notebooks.get_cell_variables(
        "rates = {}\nfor f in files:\n    rates[f] = fit(f)\nfig = plot()"
    ) == ["fig", "rates", "f"]
    assert calkit.notebooks.get_cell_variables("x = (") == []
    nb = {
        "cells": [
            {
                "cell_type": "code",
                "id": "a",
                "source": ["k = 0.0309\n", "print(k)"],
                "outputs": [
                    {
                        "output_type": "stream",
                        "text": ["0.0309\n", "run 2 at 25.0 C, 1e-3 off\n"],
                    }
                ],
            },
            {"cell_type": "markdown", "id": "b", "source": "0.5"},
            {
                "cell_type": "code",
                "id": "c",
                "source": "df",
                "outputs": [
                    {
                        "output_type": "execute_result",
                        "data": {"text/plain": "   T  k\n0  25  0.0309"},
                    }
                ],
            },
            {"cell_type": "code", "id": "d", "source": "x = 1", "outputs": []},
            {"cell_type": "code", "source": "y", "outputs": []},
        ]
    }
    assert calkit.notebooks.find_printed_numbers(nb) == [
        {
            "cell": "a",
            "cell_index": 0,
            "numbers": ["0.0309", "2", "25.0", "1e-3"],
            "variables": ["k"],
        },
        {
            "cell": "c",
            "cell_index": 2,
            "numbers": ["0", "25", "0.0309"],
            "variables": ["df"],
        },
    ]


def test_add_cell_output(tmp_path):
    nb = {
        "nbformat": 4,
        "nbformat_minor": 4,
        "metadata": {},
        "cells": [
            {"cell_type": "code", "source": "k = 1  # μs", "outputs": []},
            {"cell_type": "code", "source": "fig = 2", "outputs": []},
        ],
    }
    (tmp_path / "fit.ipynb").write_text(json.dumps(nb), encoding="utf-8")
    (tmp_path / "calkit.yaml").write_text(
        "# The pipeline\n"
        "pipeline:\n"
        "  stages:\n"
        "    fit:\n"
        "      kind: jupyter-notebook\n"
        "      notebook_path: fit.ipynb\n"
        "      environment: py\n"
    )
    wdir = str(tmp_path)
    # A cell named by position gets an ID, as do the rest
    value = {"kind": "value", "variable_name": "k"}
    marked = calkit.notebooks.add_cell_output(
        "fit.ipynb", value, cell_index=0, wdir=wdir
    )
    text = (tmp_path / "fit.ipynb").read_text(encoding="utf-8")
    assert "# μs" in text
    saved = json.loads(text)
    ids = calkit.notebooks.get_cell_ids(saved)
    assert all(ids) and saved["nbformat_minor"] == 5
    assert marked == {
        "stage": "fit",
        "output": {"kind": "value", "cell_id": ids[0], "variable_name": "k"},
        "citations": [r"\ckvalue{fit.ipynb}{k}"],
        "warning": None,
    }
    calkit.notebooks.add_cell_output(
        "fit.ipynb",
        {
            "kind": "figure",
            "cell_id": ids[1],
            "variable_name": "fig",
            "output_path": "f.pdf",
        },
        wdir=wdir,
    )
    text = (tmp_path / "calkit.yaml").read_text()
    assert text.startswith("# The pipeline\n")
    listed = calkit.notebooks.list_cell_outputs("fit.ipynb", wdir=wdir)
    assert [(m["kind"], m["cell_index"]) for m in listed] == [
        ("value", 0),
        ("figure", 1),
    ]
    on_first = value | {"cell_id": ids[0]}
    for args, kwargs, message in [
        (value | {"cell_id": "zz"}, {}, "has no cell zz"),
        (value, {"cell_index": 5}, "has 2 cells, not 6"),
        (on_first, {"cell_index": 0}, "not both"),
        (on_first, {"stage": "other"}, "doesn't run"),
        ({"kind": "value", "cell_id": ids[0]}, {}, "Name the variable"),
    ]:
        with pytest.raises(ValueError, match=message):
            calkit.notebooks.add_cell_output(
                "fit.ipynb", args, wdir=wdir, **kwargs
            )
    with pytest.raises(ValueError, match="isn't in the pipeline yet"):
        calkit.notebooks.add_cell_output("other.ipynb", value, wdir=wdir)
    # Several values at once, each cited by its own name
    added = calkit.notebooks.add_cell_output(
        "fit.ipynb",
        {"kind": "value", "cell_id": ids[0], "variable_names": ["a", "b"]},
        wdir=wdir,
    )
    assert added["citations"] == [
        r"\ckvalue{fit.ipynb}{a}",
        r"\ckvalue{fit.ipynb}{b}",
    ]
    listed = calkit.notebooks.list_cell_outputs("fit.ipynb", wdir=wdir)
    assert [m["variable_name"] for m in listed] == ["k", "a", "b", "fig"]
    remove = calkit.notebooks.remove_cell_outputs
    assert remove("fit.ipynb", cell_id=ids[1], wdir=wdir) == 1
    with pytest.raises(ValueError, match="Nothing like that"):
        remove("fit.ipynb", variable_name="z", wdir=wdir)
    assert remove("fit.ipynb", variable_name="k", wdir=wdir) == 1
    assert remove("fit.ipynb", cell_id=ids[0], wdir=wdir) == 2
    assert "cell_outputs" not in (tmp_path / "calkit.yaml").read_text()


def test_clean_all_in_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    nb = {
        "cells": [
            {
                "cell_type": "code",
                "metadata": {},
                "execution_count": 1,
                "outputs": [{"output_type": "stream", "text": "4"}],
                "source": "print(2 + 2)",
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    os.makedirs("pub")
    for path in ["analysis.ipynb", "pub/index.ipynb", "shown.ipynb"]:
        with open(path, "w") as f:
            json.dump(nb, f)
    stages = {
        "nb": {"kind": "jupyter-notebook", "notebook_path": "analysis.ipynb"},
        # Quarto rendering a notebook with --execute writes its outputs back
        # into it, so it's cleaned too, from the stage's working directory
        "pub": {
            "kind": "quarto",
            "target_path": "index.ipynb",
            "wdir": "pub",
            "args": ["--execute"],
        },
        # Rendered from the outputs saved in it, so it isn't cleaned
        "shown": {"kind": "quarto", "target_path": "shown.ipynb"},
        "report": {"kind": "quarto", "target_path": "report.qmd"},
        "missing": {"kind": "quarto", "target_path": "gone.ipynb"},
    }
    cleaned = calkit.notebooks.clean_all_in_pipeline(
        ck_info={"pipeline": {"stages": stages}}
    )
    assert cleaned == ["analysis.ipynb", "pub/index.ipynb"]
    with open(".calkit/notebooks/cleaned/pub/index.ipynb") as f:
        assert json.load(f)["cells"][0]["outputs"] == []
