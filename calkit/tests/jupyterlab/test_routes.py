"""Tests for JupyterLab extension server routes."""

import json
import os
from pathlib import Path
from typing import Any

import pytest


async def test_hello(jp_fetch):
    response = await jp_fetch("calkit", "hello")
    assert response.code == 200
    payload = json.loads(response.body)
    assert payload == {
        "data": (
            "Hello, world!"
            " This is the '/calkit/hello' endpoint."
            " Try visiting me in your browser!"
        ),
    }


async def test_notebook_cell_outputs(
    jp_fetch: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nbformat
    from tornado.httpclient import HTTPResponse

    import calkit

    async def fetch(
        method: str, body: dict | None = None, **params: str
    ) -> HTTPResponse:
        kwargs: dict[str, Any] = {"params": params} if params else {}
        if body is not None:
            kwargs["body"] = json.dumps(body)
        response = await jp_fetch(
            "calkit",
            "notebook",
            "cell",
            "outputs",
            method=method,
            raise_error=False,
            **kwargs,
        )
        assert isinstance(response, HTTPResponse)
        return response

    monkeypatch.chdir(tmp_path)
    nb = nbformat.v4.new_notebook()
    nb.cells = [
        nbformat.v4.new_code_cell("k_25 = 0.0309"),
        nbformat.v4.new_code_cell("fig, ax = plt.subplots()"),
    ]
    nbformat.write(nb, "fit.ipynb")
    ids = [c.id for c in nb.cells]
    calkit.save_calkit_info(
        {
            "pipeline": {
                "stages": {
                    "fit": {
                        "kind": "jupyter-notebook",
                        "notebook_path": "fit.ipynb",
                        "environment": "py",
                    }
                }
            }
        }
    )
    # Nothing is marked yet
    response = await fetch("GET", path="fit.ipynb")
    assert response.code == 200
    assert json.loads(response.body) == []
    # Adding one says how to cite it
    value = {"kind": "value", "cell_id": ids[0], "variable_name": "k_25"}
    response = await fetch(
        "POST", body={"path": "fit.ipynb", "outputs": [value]}
    )
    assert response.code == 200
    assert json.loads(response.body) == {
        "stage": "fit",
        "outputs": [value],
        "citations": [r"\ckvalue{fit.ipynb}{k_25}"],
        "warning": None,
    }
    figure = {
        "kind": "figure",
        "variable_name": "fig",
        "output_path": "figures/fit.pdf",
    }
    response = await fetch(
        "POST",
        body={"path": "fit.ipynb", "cell_index": 1, "outputs": [figure]},
    )
    assert response.code == 200
    assert json.loads(response.body)["outputs"][0]["cell_id"] == ids[1]
    # Listing shows each by its cell, with a saved value once there's one
    os.makedirs(".calkit/notebooks/outputs/fit.ipynb")
    with open(".calkit/notebooks/outputs/fit.ipynb/values.json", "w") as f:
        json.dump({"k_25": 0.0309}, f)
    listed = json.loads((await fetch("GET", path="fit.ipynb")).body)
    assert [(m["kind"], m["cell_index"]) for m in listed] == [
        ("value", 0),
        ("figure", 1),
    ]
    assert listed[0]["saved_value"] == 0.0309
    assert listed[1]["output_path"] == "figures/fit.pdf"
    # What can't be added or removed says why
    elsewhere = value | {"cell_id": "nope"}
    for method, body, params, message in [
        ("POST", {"path": "fit.ipynb", "outputs": [elsewhere]}, {}, "no cell"),
        ("POST", {"path": "other.ipynb", "outputs": [value]}, {}, "yet"),
        ("POST", {"path": "fit.ipynb"}, {}, "must include 'outputs'"),
        ("POST", {"path": "fit.ipynb", "outputs": value}, {}, "'outputs'"),
        ("POST", {"outputs": [value]}, {}, "must include 'path'"),
        (
            "DELETE",
            None,
            {"path": "fit.ipynb", "variable_name": "no"},
            "No matching cell output",
        ),
        ("DELETE", None, {}, "must include 'path'"),
        ("GET", None, {}, "must include 'path'"),
    ]:
        response = await fetch(method, body=body, **params)
        assert response.code == 400
        assert message in json.loads(response.body)["error"]
    # Removing a figure by its path leaves the rest
    response = await fetch(
        "DELETE", path="fit.ipynb", output_path="figures/fit.pdf"
    )
    assert response.code == 200
    assert json.loads(response.body) == {"n_removed": 1}
    listed = json.loads((await fetch("GET", path="fit.ipynb")).body)
    assert [m["kind"] for m in listed] == ["value"]
    response = await fetch("DELETE", path="fit.ipynb", cell_id=ids[0])
    assert json.loads(response.body) == {"n_removed": 1}
    assert (
        "cell_outputs"
        not in (calkit.load_calkit_info()["pipeline"]["stages"]["fit"])
    )


async def test_environments(
    jp_fetch: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    import calkit
    import calkit.cli.main
    import calkit.jupyterlab.routes

    async def fetch(method: str, body: dict | None = None, **params: str):
        kwargs: dict[str, Any] = {"params": params} if params else {}
        if body is not None:
            kwargs["body"] = json.dumps(body)
        return await jp_fetch(
            "calkit",
            "environments",
            method=method,
            raise_error=False,
            **kwargs,
        )

    monkeypatch.chdir(tmp_path)
    os.makedirs("envs/py")
    with open("envs/py/pyproject.toml", "w") as f:
        f.write(
            '[project]\nname = "py"\nrequires-python = ">=3.12"\n'
            'dependencies = ["ipykernel", "pandas>=2"]\n'
        )
    calkit.save_calkit_info(
        {
            "environments": {
                "py": {"kind": "uv", "path": "envs/py/pyproject.toml"},
                "tex": {"kind": "texlive", "packages": ["siunitx"]},
            }
        }
    )
    # A uv project's packages and Python are listed, and it can run a
    # notebook
    response = await fetch("GET")
    envs = json.loads(response.body)
    assert envs["py"]["packages"] == ["ipykernel", "pandas>=2"]
    assert envs["py"]["python"] == ">=3.12"
    assert envs["tex"]["packages"] == ["siunitx"]
    response = await fetch("GET", notebook_only="1")
    assert list(json.loads(response.body)) == ["py"]
    # Editing one changes its packages with its own tools
    ran = []

    def run(cmd, **kwargs):
        ran.append((cmd, kwargs.get("cwd")))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(calkit.jupyterlab.routes.subprocess, "run", run)
    monkeypatch.setattr(calkit.cli.main, "check_environment", lambda **_: None)
    py = {"name": "py", "kind": "uv", "python": ">=3.12"}
    response = await fetch(
        "PUT",
        body={
            "existing": py | {"packages": ["ipykernel", "pandas>=2"]},
            "updated": py | {"packages": ["ipykernel", "scipy"]},
        },
    )
    assert response.code == 200, response.body
    assert ran == [
        (["uv", "remove", "pandas"], "envs/py"),
        (["uv", "add", "scipy"], "envs/py"),
    ]
    tex = {"name": "tex", "kind": "texlive"}
    response = await fetch(
        "PUT",
        body={
            "existing": tex | {"packages": ["siunitx"]},
            "updated": tex | {"packages": ["siunitx", "booktabs"]},
        },
    )
    assert response.code == 200, response.body
    env = calkit.load_calkit_info()["environments"]["tex"]
    assert env["packages"] == ["siunitx", "booktabs"]
