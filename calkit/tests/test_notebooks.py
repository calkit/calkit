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
    assert path == ".calkit/notebooks/outputs/fit/values.json"
    assert calkit.notebooks.get_notebook_of_values_path(path) == "fit.ipynb"
    path = calkit.notebooks.get_notebook_values_path("nbs/fit.ipynb")
    assert path == ".calkit/notebooks/outputs/nbs/fit/values.json"
    assert (
        calkit.notebooks.get_notebook_of_values_path(path) == "nbs/fit.ipynb"
    )
    # Parameters are in the name, as for the executed copy
    path = calkit.notebooks.get_notebook_values_path("fit.ipynb", {"t": 25})
    assert path == ".calkit/notebooks/outputs/fit-t-25/values.json"
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
        {"cell": "c", "value": "x"},
        {"value": "y"},
        {
            "cell": "a",
            "figure": "f.png",
            "variable": "fig",
            "path": "../f.png",
        },
        {"cell": "a", "value": "z"},
    ]
    captured = calkit.notebooks.add_capture_cells(nb, outputs, "v.json", "t")
    sources = [c["source"] for c in captured["cells"]]
    # The helper first, then one after each cell with outputs, in order, and
    # one at the end for those with no cell
    assert sources[0] == calkit.notebooks.CAPTURE_HELPER
    assert sources[1] == "x = 1"
    assert sources[2].startswith("_calkit_save_cell_outputs('cell a', ")
    assert '[[2, {"cell": "a", "figure": "f.png"' in sources[2]
    assert '[3, {"cell": "a", "value": "z"}]' in sources[2]
    assert sources[3:5] == ["# Hi", "x = 2"]
    assert '[[0, {"cell": "c", "value": "x"}]]' in sources[5]
    assert sources[6].startswith("_calkit_save_cell_outputs('the last cell'")
    assert "'v.json', 't')" in sources[6]
    assert len({c["id"] for c in captured["cells"]}) == 7
    # The notebook given isn't changed, and the added cells come out again
    assert len(nb["cells"]) == 3
    assert calkit.notebooks.remove_capture_cells(captured) == nb
    with pytest.raises(ValueError, match="no cell zz"):
        calkit.notebooks.add_capture_cells(
            nb, [{"cell": "zz", "value": "x"}], "v.json", "t"
        )
    # The helper saves values, figures, and tables in the kernel, failing
    # with what to do about anything it can't
    namespace: dict = {}
    exec(calkit.notebooks.CAPTURE_HELPER, namespace)
    save = namespace["_calkit_save_cell_outputs"]
    namespace.update(
        k=0.25,
        rates={"25C": 0.031, 35: (1, 2)},
        rows=[{"T": 25, "k": 0.031}, {"T": 35, "k": 0.062}],
        cols={"T": [25, 35], "k": [0.031, 0.062]},
        grid=[["T", "k"], [25, 0.031]],
        bad=object(),
    )
    with tempfile.TemporaryDirectory() as tmp:
        values = os.path.join(tmp, "v", "values.json")
        tables = os.path.join(tmp, "tables")
        save(
            "cell a",
            [
                [0, {"value": "k"}],
                [1, {"value": "rates"}],
                [2, {"table": "t.tex", "variable": "rows"}],
                [3, {"table": "t.tex", "variable": "cols"}],
                [4, {"table": "t.tex", "variable": "grid"}],
            ],
            values,
            tables,
        )
        with open(values) as f:
            assert json.load(f) == {
                "k": 0.25,
                "rates": {"25C": 0.031, "35": [1, 2]},
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
            ({"value": "missing"}, NameError, "no variable 'missing'"),
            ({"value": "bad"}, TypeError, "since it's a object"),
            ({"table": "t.tex", "variable": "k"}, TypeError, "as a table"),
            (
                {"figure": "f.png", "variable": "k", "path": "f.png"},
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
    outputs = [
        {"cell": "a", "value": "k"},
        {"cell": "b", "figure": "f.png"},
        {"cell": "b", "table": "t.tex", "variable": "df"},
    ]
    # Marking something again moves it, and a path takes over from another
    # output saved to it
    marked = calkit.notebooks.with_cell_output(
        outputs, {"cell": "c", "value": "k"}
    )
    assert marked[0] == {"cell": "c", "value": "k"}
    assert len(marked) == 3
    marked = calkit.notebooks.with_cell_output(
        outputs, {"cell": "c", "figure": "t.tex", "variable": "fig"}
    )
    assert [o.get("figure") or o.get("table") for o in marked] == [
        None,
        "f.png",
        "t.tex",
    ]
    assert marked[2]["cell"] == "c"
    assert calkit.notebooks.with_cell_output(outputs, {"value": "j"})[-1] == {
        "value": "j"
    }
    assert (
        calkit.notebooks.without_cell_outputs(outputs, value="k")
        == outputs[1:]
    )
    assert (
        calkit.notebooks.without_cell_outputs(outputs, path="t.tex")
        == (outputs[:2])
    )
    assert (
        calkit.notebooks.without_cell_outputs(outputs, cell="b")
        == (outputs[:1])
    )
    stage = {
        "notebook_path": "fit.ipynb",
        "cell_outputs": outputs
        + [
            {"cell": "gone", "table": "t.csv", "variable": "df"},
            {"value": "j"},
        ],
    }
    nb = {"cells": [{"id": "a"}, {"id": "x"}, {"id": "b"}]}
    described = calkit.notebooks.describe_cell_outputs(
        "fit", stage, nb, values={"k": 0.25}
    )
    assert described[0] == {
        "stage": "fit",
        "kind": "value",
        "name": "k",
        "cell": "a",
        "cell_index": 0,
        "variable": None,
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
        r"\ckvalue{.calkit/notebooks/outputs/fit-t-25/values.json}{k}"
    )
    assert described[0]["cell_index"] is None
