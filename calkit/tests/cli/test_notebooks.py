"""Tests for ``calkit.cli.notebooks``."""

import base64
import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

import calkit
import calkit.notebooks


def test_clean_notebook_outputs(tmp_dir):
    # Copy in a test notebook and clean it
    nb_fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "test", "pipeline.ipynb"
    )
    shutil.copy(nb_fpath, "notebook.ipynb")
    subprocess.check_call(["calkit", "nb", "clean", "notebook.ipynb"])
    # A stage depends on these bytes, so they must match across platforms
    cleaned_fpath = calkit.notebooks.get_cleaned_notebook_path(
        "notebook.ipynb"
    )
    with open(cleaned_fpath, "rb") as f:
        assert b"\r\n" not in f.read()


def test_clean_notebook_is_invariant_to_cell_ids():
    """Cleaning must not depend on whether a clean filter touched the source.

    nbstripout rewrites cell IDs to ordinals, so a notebook committed through
    that filter reaches a fresh clone with different IDs than the working tree
    it was committed from. When the cleaned copy carried them, its hash -- and
    therefore the stage depending on it -- differed between the two, leaving
    the stage stale on every clone.
    """
    executed = {
        "cells": [
            {
                "cell_type": "code",
                "id": "44539ead",
                "metadata": {},
                "execution_count": 3,
                "outputs": [{"output_type": "stream", "text": "hi"}],
                "source": ["print('hi')"],
            }
        ],
        "metadata": {"kernelspec": {"name": "python3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    stripped = copy.deepcopy(executed)
    stripped["cells"][0]["id"] = "0"
    stripped["cells"][0]["execution_count"] = None
    stripped["cells"][0]["outputs"] = []
    assert calkit.notebooks.clean_notebook(
        executed
    ) == calkit.notebooks.clean_notebook(stripped)
    # Nor whether a cell's source is one string or a list of lines, which
    # tools rewrite between, e.g., Quarto rendering with --execute
    joined = copy.deepcopy(executed)
    joined["cells"][0]["source"] = "print('hi')\nprint('bye')"
    split = copy.deepcopy(executed)
    split["cells"][0]["source"] = ["print('hi')\n", "print('bye')"]
    assert calkit.notebooks.clean_notebook(
        joined
    ) == calkit.notebooks.clean_notebook(split)


def test_execute_notebook(tmp_dir):
    subprocess.check_call(
        [
            "calkit",
            "new",
            "project",
            ".",
            "-n",
            "cool-project",
            "--title",
            "Cool project",
        ]
    )
    subprocess.check_call(
        ["calkit", "new", "uv-venv", "-n", "main", "ipykernel"]
    )
    nb_fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "test", "nb-subdir.ipynb"
    )
    os.makedirs("notebooks/results")
    shutil.copy(nb_fpath, "notebooks/main.ipynb")
    subprocess.check_call(
        ["calkit", "nb", "execute", "notebooks/main.ipynb", "-e", "main"]
    )
    assert os.path.isfile("notebooks/results/something.txt")
    os.makedirs("results")
    shutil.copy("notebooks/main.ipynb", "main.ipynb")
    subprocess.check_call(
        ["calkit", "nb", "execute", "main.ipynb", "-e", "main"]
    )
    assert os.path.isfile("results/something.txt")
    # Test we can execute with parameters
    nb_fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "test", "nb-params.ipynb"
    )
    shutil.copy(nb_fpath, "nb-params.ipynb")
    params1 = {
        "my_value": 5,
        "my_list": [1, 2, 3],
    }
    params2 = {
        "my_dict": {"something": 55.5, "else": "b"},
    }
    subprocess.check_call(
        [
            "calkit",
            "nb",
            "execute",
            "nb-params.ipynb",
            "-e",
            "main",
            "--params-json",
            json.dumps(params1),
            "--params-base64",
            base64.b64encode(json.dumps(params2).encode("utf-8")).decode(
                "utf-8"
            ),
            "--verbose",
        ]
    )
    params = params1 | params2
    with open("params-out.json") as f:
        params_out = json.load(f)
    assert params_out["my_value"] == params["my_value"]
    assert params_out["my_list"] == params["my_list"]
    assert params_out["my_dict"] == params["my_dict"]
    # Test we can execute in the pipeline with params
    pipeline = {
        "stages": {
            "nb-params": {
                "kind": "jupyter-notebook",
                "notebook_path": "nb-params.ipynb",
                "environment": "main",
                "parameters": params,
                "html_storage": None,
            }
        }
    }
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = pipeline
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "run"])
    with open("params-out.json") as f:
        params_out = json.load(f)
    assert params_out["my_value"] == params["my_value"]
    assert params_out["my_list"] == params["my_list"]
    assert params_out["my_dict"] == params["my_dict"]
    # Test we can patch in a range iteration from project parameters
    project_params = {
        "my_range": {"range": {"start": 1, "stop": 6, "step": 1}},
        "my_project_value": 77,
    }
    pipeline = {
        "stages": {
            "nb-params": {
                "kind": "jupyter-notebook",
                "notebook_path": "nb-params.ipynb",
                "environment": "main",
                "parameters": params
                | {"my_list": "{my_range}", "my_value": "{my_project_value}"},
                "html_storage": None,
            }
        }
    }
    ck_info = calkit.load_calkit_info()
    ck_info["parameters"] = project_params
    ck_info["pipeline"] = pipeline
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    os.remove("params-out.json")
    subprocess.check_call(["calkit", "run"])
    with open("params-out.json") as f:
        params_out = json.load(f)
    assert params_out["my_value"] == project_params["my_project_value"]
    assert params_out["my_list"] == list(range(1, 6))
    assert params_out["my_dict"] == params["my_dict"]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Julia env init fails on Windows GHA runners (Pkg stdlib missing)",
)
# Both install and build IJulia in the shared depot, and one precompiling it
# while the other builds it fails with "IJulia not properly installed"
@pytest.mark.xdist_group("ijulia")
@pytest.mark.needs("juliaup")
def test_execute_notebook_julia(tmp_dir):
    subprocess.check_call(
        [
            "calkit",
            "new",
            "project",
            ".",
            "-n",
            "cool-project",
            "--title",
            "Cool project",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "julia-env",
            "--name",
            "main",
            "--julia",
            "1.11",
            "IJulia",
        ]
    )
    nb_fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "test", "nb-julia.ipynb"
    )
    os.makedirs("notebooks")
    shutil.copy(nb_fpath, "notebooks/main.ipynb")
    subprocess.check_call(
        ["calkit", "nb", "execute", "-e", "main", "notebooks/main.ipynb"]
    )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Julia env init fails on Windows GHA runners (Pkg stdlib missing)",
)
# Both install and build IJulia in the shared depot, and one precompiling it
# while the other builds it fails with "IJulia not properly installed"
@pytest.mark.xdist_group("ijulia")
@pytest.mark.needs("juliaup")
def test_check_env_kernel_julia(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "julia-env",
            "--name",
            "main",
            "--julia",
            "1.11",
        ]
    )
    res = subprocess.run(
        ["calkit", "nb", "check-kernel", "-e", "main"], capture_output=True
    )
    assert res.returncode != 0
    assert (
        "IJulia is not installed in this Julia environment"
        in res.stderr.decode()
    )
    # Now let's use the auto-add-deps option
    res = subprocess.run(
        [
            "calkit",
            "nb",
            "check-kernel",
            "-e",
            "main",
            "--auto-add-deps",
        ],
        capture_output=True,
    )
    assert res.returncode == 0


@pytest.mark.xdist_group("texlive")
def test_check_env_kernel_composed(
    tmp_dir: pathlib.Path,
    texlive_user_home: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jupyter_client.blocking.client import BlockingKernelClient
    from jupyter_client.manager import start_new_kernel

    from calkit.environments import texlive

    def check_kernel() -> tuple[str, dict]:
        out = subprocess.check_output(
            ["calkit", "nb", "check-kernel", "-e", "main", "--json"]
        )
        result = json.loads(out)
        kernel_name = result["kernel_name"]
        spec_fpath = os.path.join(
            "jupyter-data", "kernels", kernel_name.lower(), "kernel.json"
        )
        with open(spec_fpath) as f:
            spec = json.load(f)
        # The environment's Python, for an editor to tell it from others
        assert result["python"] == spec["argv"][0]
        return kernel_name, spec.get("env", {})

    monkeypatch.setenv("CALKIT_USER_HOME", texlive_user_home)
    monkeypatch.setenv("JUPYTER_DATA_DIR", os.path.abspath("jupyter-data"))
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        ["calkit", "new", "uv-venv", "-n", "main", "ipykernel"]
    )
    # Without 'with', the kernel's spec doesn't touch PATH
    _, env_vars = check_kernel()
    assert "PATH" not in env_vars
    assert "FONTCONFIG_FILE" not in env_vars
    # With it, the spec puts TeX Live's programs ahead of the PATH of
    # whatever starts the kernel
    ck_info = calkit.load_calkit_info()
    ck_info["environments"]["tex"] = {"kind": "texlive"}
    ck_info["environments"]["main"]["with"] = ["tex"]
    calkit.save_calkit_info(ck_info)
    kernel_name, env_vars = check_kernel()
    envs = ck_info["environments"]
    view_dir = texlive.check("tex", envs["tex"])
    bin_dir = os.path.join(view_dir, "bin", texlive.get_platform())
    assert env_vars["PATH"] == bin_dir + os.pathsep + "${PATH}"
    composed = calkit.environments.get_composed_env_vars(
        "main", envs["main"], envs
    )
    assert composed is not None
    for name in ["FONTCONFIG_FILE", "MPLCONFIGDIR"]:
        assert env_vars[name] == composed[name]
    # What the project sets is left to whatever starts the kernel, since the
    # spec's values would override it
    ck_info["env_vars"] = {"MPLCONFIGDIR": "mplconfig"}
    calkit.save_calkit_info(ck_info)
    kernel_name, env_vars = check_kernel()
    assert "MPLCONFIGDIR" not in env_vars
    assert env_vars["FONTCONFIG_FILE"] == composed["FONTCONFIG_FILE"]
    # Jupyter fills in the PATH it was started with
    path = os.environ["PATH"]
    monkeypatch.setenv("PATH", os.defpath)
    monkeypatch.setenv("MPLCONFIGDIR", "/project/mplconfig")
    km, kc = start_new_kernel(kernel_name=kernel_name)
    assert isinstance(kc, BlockingKernelClient)
    try:
        kc.execute_interactive(
            "import json, os, shutil\n"
            "with open('kernel-env.json', 'w') as f:\n"
            "    json.dump([os.environ['PATH'], shutil.which('kpsewhich'),\n"
            "        os.environ['MPLCONFIGDIR']], f)",
            timeout=60,
        )
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=True)
    monkeypatch.setenv("PATH", path)
    monkeypatch.delenv("MPLCONFIGDIR")
    with open("kernel-env.json") as f:
        kernel_path, kpsewhich_fpath, mplconfig_dir = json.load(f)
    assert kernel_path == bin_dir + os.pathsep + os.defpath
    assert os.path.dirname(kpsewhich_fpath) == bin_dir
    assert mplconfig_dir == "/project/mplconfig"
    # Nor does the spec touch a PATH the project sets, e.g., in .env
    with open(".env", "w") as f:
        f.write(f"PATH={path}\n")
    _, env_vars = check_kernel()
    assert "PATH" not in env_vars
    assert env_vars["FONTCONFIG_FILE"] == composed["FONTCONFIG_FILE"]
    # Taking it out of 'with' takes it out of the spec
    ck_info["environments"]["main"].pop("with")
    calkit.save_calkit_info(ck_info)
    _, env_vars = check_kernel()
    assert "FONTCONFIG_FILE" not in env_vars


def test_execute_notebook_auto_env(tmp_dir):
    # Check that we can execute a notebook but only specify the environment's
    # path, rather than its name
    nb_fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "test", "nb-subdir.ipynb"
    )
    os.makedirs("notebooks/results")
    shutil.copy(nb_fpath, "notebooks/main.ipynb")
    with open("requirements.txt", "w") as f:
        f.write("ipykernel")
    cmd = [
        "calkit",
        "nb",
        "exec",
        "-e",
        "requirements.txt",
        "notebooks/main.ipynb",
    ]
    subprocess.check_call(cmd)
    # Ensure we have an environment created
    ck_info = calkit.load_calkit_info()
    env = ck_info["environments"]["main"]
    assert env["kind"] == "uv-venv"
    # Run again--should not modify calkit.yaml this time
    subprocess.check_call(cmd)
    # Check that we can not specify the environment at all, and we'll
    # use pyproject.toml or requirements.txt
    cmd = [
        "calkit",
        "nb",
        "exec",
        "notebooks/main.ipynb",
    ]
    subprocess.check_call(cmd)
    # Add a second environment and ensure we fail to detect which to use for
    # the notebook
    os.remove("calkit.yaml")
    subprocess.check_call(["uv", "init", "--bare"])
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(cmd)
    # TODO: If successful, check we save the environment and attach it to the
    # notebook
    # TODO: Check if the notebook is saved in the project and if it
    # has an environment specified, either in the notebooks section or a
    # pipeline stage


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Docker Linux images are unavailable on windows-latest GHA runners",
)
@pytest.mark.needs("docker")
def test_execute_notebook_docker(tmp_dir):
    # A Docker environment runs the kernel inside the container, so we execute
    # with Papermill inside the container rather than registering a host kernel
    image = "calkit-nb-docker-test:latest"
    # Bake ipykernel and Papermill into the image so execution is deterministic
    with open("Dockerfile", "w") as f:
        f.write(
            "FROM python:3.10-slim\n"
            "RUN pip install --no-cache-dir ipykernel papermill\n"
            "WORKDIR /work\n"
        )
    subprocess.check_call(["docker", "build", "-t", image, "."])
    subprocess.check_call(["calkit", "init"])
    ck_info = {
        "environments": {
            "docker-env": {"kind": "docker", "image": image, "wdir": "/work"}
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    # A notebook with a 'parameters' cell so we can verify injection
    nb = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "id": "params",
                "metadata": {"tags": ["parameters"]},
                "outputs": [],
                "source": ["a = 1\n"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "id": "compute",
                "metadata": {},
                "outputs": [],
                "source": ["result = a * 10\n", "print('result =', result)\n"],
            },
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    os.makedirs("notebooks")
    with open(os.path.join("notebooks", "main.ipynb"), "w") as f:
        json.dump(nb, f)
    subprocess.check_call(
        [
            "calkit",
            "nb",
            "exec",
            "-e",
            "docker-env",
            "--no-check",
            "-p",
            "a=4",
            "notebooks/main.ipynb",
        ]
    )
    # The injected parameter should have produced result = 40 in the executed
    # notebook saved under .calkit/notebooks/executed
    exec_path = calkit.notebooks.get_executed_notebook_path(
        notebook_path="notebooks/main.ipynb",
        to="notebook",
        parameters={"a": 4},
    )
    with open(exec_path) as f:
        executed = json.load(f)
    text = "".join(
        "".join(o.get("text", []))
        for cell in executed["cells"]
        for o in cell.get("outputs", [])
        if o.get("name") == "stdout"
    )
    assert "result = 40" in text


def test_cell_outputs(tmp_dir):
    import nbformat

    subprocess.check_call(
        ["calkit", "new", "project", ".", "-n", "fits", "--title", "Fits"]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "py",
            "ipykernel",
            "matplotlib",
            "pandas",
        ]
    )
    nb = nbformat.v4.new_notebook()
    nb.cells = [
        nbformat.v4.new_code_cell(
            "import numpy as np\n"
            "import pandas as pd\n"
            "import matplotlib.pyplot as plt\n"
            "rates = {'25C': 0.0309, '35C': np.float64(0.0616)}\n"
            "k_25 = rates['25C']"
        ),
        nbformat.v4.new_markdown_cell("# Plots"),
        nbformat.v4.new_code_cell(
            "fig, ax = plt.subplots()\nax.plot([1, 2], [3, 4])"
        ),
        nbformat.v4.new_code_cell("plt.plot([1, 2], [4, 1])\nplt.show()"),
        nbformat.v4.new_code_cell(
            "df = pd.DataFrame({'T': [25, 35], 'k': [0.0309, 0.0616]})"
        ),
        nbformat.v4.new_code_cell("k_25 = 999\nlast = 'done'"),
    ]
    nbformat.write(nb, "fit.ipynb")
    ids = [c.id for c in nb.cells]
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = {
        "stages": {
            "fit": {
                "kind": "jupyter-notebook",
                "notebook_path": "fit.ipynb",
                "environment": "py",
                "html_storage": None,
            }
        }
    }
    calkit.save_calkit_info(ck_info)

    def add(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["calkit", "nb", "add-output", "fit.ipynb", *args],
            capture_output=True,
            text=True,
        )

    # Adding one says how to show each in a document
    out = add(
        "value", "--cell-id", ids[0], "--variable-name", "k_25", "--json"
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {
        "stage": "fit",
        "output": {
            "kind": "value",
            "cell_id": ids[0],
            "variable_name": "k_25",
        },
        "citations": [r"\ckvalue{fit.ipynb}{k_25}"],
        "warning": None,
    }
    table = [
        "table",
        "--cell-id",
        ids[4],
        "--variable-name",
        "df",
        "--output-path",
    ]
    for args in [
        ["value", "--cell-id", ids[0], "--variable-name", "rates"],
        ["value", "--variable-name", "last"],
        [
            "figure",
            "--cell-id",
            ids[2],
            "--variable-name",
            "fig",
            "--output-path",
            "figures/fit.pdf",
        ],
        ["figure", "--cell-index", "3", "--output-path", "figures/shown.png"],
        table + ["tables/rates.tex"],
        table + ["rates.csv"],
    ]:
        out = add(*args)
        assert out.returncode == 0, out.stderr
    assert (
        "\\cktable{tables/rates.tex}" in add(*table, "tables/rates.tex").stdout
    )
    # What can't be saved
    first = ["--cell-id", ids[0]]
    for args, message in [
        (
            ["value", "--cell-id", "nope", "--variable-name", "x"],
            "has no cell nope",
        ),
        (
            ["value", "--cell-index", "9", "--variable-name", "x"],
            "has 6 cells",
        ),
        (
            ["value", *first, "--cell-index", "0", "--variable-name", "x"],
            "both",
        ),
        (
            ["value", *first, "--variable-name", "x", "--format", ".2f"],
            "apply",
        ),
        (["plot", *first, "--variable-name", "x"], "Input should be"),
        (["figure", *first, "--output-path", "fit.pdf"], "can't be in"),
    ]:
        if "can't be in" in message:
            ck_info = calkit.load_calkit_info()
            ck_info["pipeline"]["stages"]["fit"]["outputs"] = ["fit.pdf"]
            calkit.save_calkit_info(ck_info)
            message = "so it can't be in 'outputs' too"
        out = add(*args)
        assert out.returncode != 0
        assert message in out.stderr + out.stdout
    ck_info = calkit.load_calkit_info()
    del ck_info["pipeline"]["stages"]["fit"]["outputs"]
    calkit.save_calkit_info(ck_info)
    out = subprocess.run(
        [
            "calkit",
            "nb",
            "add-output",
            "other.ipynb",
            "value",
            "--variable-name",
            "x",
        ],
        capture_output=True,
        text=True,
    )
    assert "isn't in the pipeline yet" in out.stderr + out.stdout
    subprocess.check_call(
        [
            "calkit",
            "nb",
            "remove-output",
            "fit.ipynb",
            "--output-path",
            "rates.csv",
        ]
    )
    # Values saved after the same cell are kept together
    ck_info = calkit.load_calkit_info()
    saved = ck_info["pipeline"]["stages"]["fit"]["cell_outputs"]
    assert len(saved) == 5
    assert saved[0]["variable_names"] == ["k_25", "rates"]
    # Running saves each, the value as it was right after its cell, and
    # leaves no sign of the cells that saved them
    subprocess.check_call(["calkit", "run"])
    values_path = ".calkit/notebooks/outputs/fit.ipynb/values.json"
    with open(values_path) as f:
        assert json.load(f) == {
            "k_25": 0.0309,
            "rates": {"25C": 0.0309, "35C": 0.0616},
            "last": "done",
        }
    with open("figures/fit.pdf", "rb") as f:
        assert f.read(4) == b"%PDF"
    with open("figures/shown.png", "rb") as f:
        assert f.read(4) == b"\x89PNG"
    with open("tables/rates.tex", encoding="utf-8") as f:
        assert r"25 & 0.0309 \\" in f.read()
    for path in ["fit.ipynb", ".calkit/notebooks/executed/fit.ipynb"]:
        with open(path) as f:
            sources = [c["source"] for c in json.load(f)["cells"]]
        assert len(sources) == 6
        assert not any("_calkit" in "".join(s) for s in sources)
    status = subprocess.check_output(["calkit", "status"], text=True)
    assert "fit" not in status.split("Pipeline")[-1] or "up to date" in status
    # Listing shows what was saved, by the cell it's after
    listed = json.loads(
        subprocess.check_output(
            ["calkit", "nb", "outputs", "fit.ipynb", "--json"], text=True
        )
    )
    assert [(d["kind"], d["cell_index"]) for d in listed] == [
        ("value", 0),
        ("value", 0),
        ("value", None),
        ("figure", 2),
        ("figure", 3),
        ("table", 4),
    ]
    assert listed[0]["saved_value"] == 0.0309
    # A document cites the value by the notebook, wherever it's built
    os.makedirs("paper")
    with open("paper/main.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n\\usepackage{calkit}\n"
            "\\begin{document}\n"
            "$k = \\ckvalue[.3f]{fit.ipynb}{rates.35C}$\n"
            "\\end{document}\n"
        )
    assert calkit.latex.map_ck_components("paper/main.tex") == []
    with open("paper/_calkit/values.tex") as f:
        assert "\\cksetvalue{fit.ipynb}{rates.35C}{n}{0.0616}" in f.read()
    # What couldn't be saved stops the run, saying why
    for arg, message in [
        (
            f"kind=value,cell_id={ids[2]},variable_name=nope",
            f"no variable 'nope' after cell {ids[2]}",
        ),
        (
            f"kind=value,cell_id={ids[0]},variable_name=plt",
            "since it's a module",
        ),
        (
            f"kind=figure,cell_id={ids[0]},output_path=x.png",
            f"Cell {ids[0]} shows no image/png",
        ),
        ("kind=value,cell_id=gone,variable_name=k_25", "no cell gone"),
    ]:
        out = subprocess.run(
            ["calkit", "nb", "execute", "fit.ipynb", "-e", "py", "-o", arg],
            capture_output=True,
            text=True,
        )
        assert out.returncode != 0
        assert message in out.stdout + out.stderr
        assert not os.path.isdir(".calkit/notebooks/outputs/fit.ipynb/_saving")
