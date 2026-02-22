"""Tests for ``calkit.environments``."""

import json
import os
import shutil
import subprocess

import calkit.environments


def test_check_all_in_pipeline(tmp_dir):
    ck_info = {
        "environments": {
            "py1": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.13",
                "prefix": ".venv",
            },
        },
        "pipeline": {
            "stages": {
                "run-thing": {
                    "kind": "python-script",
                    "script_path": "scripts/run-thing.py",
                    "environment": "py1",
                }
            },
        },
    }
    with open("requirements.txt", "w") as f:
        f.write("requests\n")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    res = calkit.environments.check_all_in_pipeline()
    print(res)
    assert res["py1"]["success"]
    res = calkit.environments.check_all_in_pipeline()
    print(res)
    assert res["py1"]["success"]
    assert res["py1"]["cached"]
    res = calkit.environments.check_all_in_pipeline(force=True)
    print(res)
    assert res["py1"]["success"]
    assert not res["py1"].get("cached")
    # Check that if we update requirements.txt, the environment check is no
    # longer cached
    with open("requirements.txt", "w") as f:
        f.write("requests\n")
        f.write("polars\n")
    res = calkit.environments.check_all_in_pipeline()
    print(res)
    assert res["py1"]["success"]
    assert not res["py1"].get("cached")
    # Check that if we delete the env lock file, the environment check is no
    # longer cached
    env_lock_fpath = calkit.environments.get_env_lock_fpath(
        env=ck_info["environments"]["py1"], env_name="py1"
    )
    assert env_lock_fpath is not None
    assert os.path.exists(env_lock_fpath)
    os.remove(env_lock_fpath)
    res = calkit.environments.check_all_in_pipeline()
    print(res)
    assert res["py1"]["success"]
    assert not res["py1"].get("cached")
    # Now make sure the env is rechecked if we delete the prefix
    env_prefix = ck_info["environments"]["py1"].get("prefix")
    assert env_prefix is not None
    shutil.rmtree(env_prefix)
    res = calkit.environments.check_all_in_pipeline()
    print(res)
    assert res["py1"]["success"]
    assert not res["py1"].get("cached")
    res = calkit.environments.check_all_in_pipeline()
    print(res)
    assert res["py1"]["success"]
    assert res["py1"]["cached"]


def test_env_from_name_or_path(tmp_dir):
    # Test with typical venvs
    with open("requirements.txt", "w") as f:
        f.write("requests")
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="requirements.txt"
    )
    assert res.name == "main"
    assert res.env["path"] == "requirements.txt"
    assert not res.exists
    assert res.env["prefix"] == ".venv"
    res = calkit.environments.env_from_name_or_path(
        name_or_path="requirements.txt"
    )
    assert res.name == "main"
    assert res.env["path"] == "requirements.txt"
    assert not res.exists
    # Test a venv in a subdirectory
    os.makedirs("envs")
    os.makedirs("envs/myenv")
    with open("envs/myenv/requirements.txt", "w") as f:
        f.write("requests")
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="envs/myenv/requirements.txt"
    )
    assert res.name == "myenv"
    assert res.env["prefix"] == "envs/myenv/.venv"
    # Test with a conda env
    with open("environment.yml", "w") as f:
        calkit.ryaml.dump({"name": "myenv", "dependencies": ["pandas"]}, f)
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="environment.yml"
    )
    assert res.name == "myenv"
    assert res.env["path"] == "environment.yml"
    assert not res.exists
    # Test with a uv project env
    subprocess.check_call(["uv", "init", "--bare"])
    subprocess.check_call(["uv", "add", "requests"])
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="pyproject.toml"
    )
    assert res.name == "main"
    assert res.env["path"] == "pyproject.toml"
    assert not res.exists
    # Test that we don't overwrite an existing name
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "environments": {
                    "main": {"kind": "uv-venv", "path": "requirements.txt"}
                }
            },
            f,
        )
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="pyproject.toml"
    )
    assert res.name == "uv1"
    assert res.env["path"] == "pyproject.toml"
    assert not res.exists
    # Now, what if we put the environment in a subdirectory
    os.makedirs("envs/uvsubdir")
    subprocess.check_call(
        [
            "uv",
            "init",
            "--bare",
            "--directory",
            "envs/uvsubdir",
            "--no-workspace",
        ]
    )
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="envs/uvsubdir/pyproject.toml"
    )
    assert res.name == "uvsubdir"
    assert res.env["path"] == "envs/uvsubdir/pyproject.toml"
    assert res.env["kind"] == "uv"
    assert not res.exists
    # Check when the subdirectory name conflicts with an existing name
    os.makedirs("envs/main")
    subprocess.check_call(
        [
            "uv",
            "init",
            "--bare",
            "--directory",
            "envs/main",
            "--no-workspace",
        ]
    )
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="envs/main/pyproject.toml"
    )
    assert res.name == "main-uv"
    assert res.env["path"] == "envs/main/pyproject.toml"
    assert res.env["kind"] == "uv"
    assert not res.exists
    # Test with a Julia env
    os.makedirs("juliaenv")
    with open("juliaenv/Project.toml", "w") as f:
        f.write("doesn't need to work")
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="juliaenv/Project.toml"
    )
    assert res.name == "juliaenv"
    assert res.env["path"] == "juliaenv/Project.toml"
    assert res.env["kind"] == "julia"
    assert not res.exists
    # Test with a Dockerfile
    with open("Dockerfile", "w") as f:
        f.write("FROM python:3.9-slim")
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="Dockerfile"
    )
    assert res.name == "docker1"
    assert res.env["path"] == "Dockerfile"
    assert res.env["kind"] == "docker"
    # Test with a pixi env
    with open("pixi.toml", "w") as f:
        f.write("doesn't need to work")
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="pixi.toml"
    )
    assert res.name == "pixi1"
    assert res.env["path"] == "pixi.toml"


def test_detect_default_env(tmp_dir):
    # First start with only a single env spec file
    with open("requirements.txt", "w") as f:
        f.write("requests")
    res = calkit.environments.detect_default_env()
    assert res is not None
    assert res.name == "main"
    assert res.env["path"] == "requirements.txt"
    # Now add a second env spec file--should not detect a default env anymore
    with open("environment.yml", "w") as f:
        calkit.ryaml.dump({"name": "myenv", "dependencies": ["pandas"]}, f)
    res = calkit.environments.detect_default_env()
    assert res is None


def test_detect_env_for_stage(tmp_dir):
    stage_py = {"kind": "python-script", "script_path": "script.py"}
    with open("script.py", "w") as f:
        f.write("import requests\n")
    with open("requirements.txt", "w") as f:
        f.write("requests\n")
    ck_info = {
        "environments": {
            "explicit": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.14",
                "prefix": ".venv",
            }
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_py, environment="explicit", ck_info=ck_info
    )
    assert res.name == "explicit"
    assert res.exists
    ck_info = {
        "environments": {
            "pyenv": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.14",
                "prefix": ".venv",
            }
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_py, environment=None, ck_info=ck_info
    )
    assert res.name == "pyenv"
    assert res.exists
    ck_info = {"environments": {}}
    res = calkit.environments.detect_env_for_stage(
        stage_py, environment=None, ck_info=ck_info
    )
    assert res.name == "main"
    assert res.env["path"] == "requirements.txt"
    assert not res.created_from_dependencies
    os.remove("requirements.txt")
    res = calkit.environments.detect_env_for_stage(
        stage_py, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "pyproject.toml"
    ck_info = {
        "environments": {
            "jl": {"kind": "julia", "path": "Project.toml", "julia": "1.11"}
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_py, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path is not None
    # Since this is the first Python env, use pyproject.toml
    assert res.spec_path == "pyproject.toml"
    stage_r = {"kind": "r-script", "script_path": "analysis.R"}
    with open("analysis.R", "w") as f:
        f.write("library(dplyr)\n")
    ck_info = {"environments": {}}
    res = calkit.environments.detect_env_for_stage(
        stage_r, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "DESCRIPTION"
    ck_info = {
        "environments": {
            "py": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.14",
                "prefix": ".venv",
            }
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_r, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path is not None
    assert res.spec_path == "DESCRIPTION"
    stage_jl = {"kind": "julia-script", "script_path": "analysis.jl"}
    with open("analysis.jl", "w") as f:
        f.write("using DataFrames\n")
    ck_info = {"environments": {}}
    res = calkit.environments.detect_env_for_stage(
        stage_jl, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "Project.toml"
    ck_info = {
        "environments": {
            "py": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.14",
                "prefix": ".venv",
            }
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_jl, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "Project.toml"
    notebook_py = {
        "cells": [
            {
                "cell_type": "code",
                "source": ["import pandas\n"],
            }
        ],
        "metadata": {
            "kernelspec": {
                "language": "python",
                "name": "python3",
            }
        },
    }
    with open("notebook-py.ipynb", "w") as f:
        json.dump(notebook_py, f)
    stage_nb = {
        "kind": "jupyter-notebook",
        "notebook_path": "notebook-py.ipynb",
    }
    ck_info = {"environments": {}}
    res = calkit.environments.detect_env_for_stage(
        stage_nb, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "pyproject.toml"
    assert res.spec_content is not None
    assert "ipykernel" in res.spec_content
    notebook_r = {
        "cells": [
            {
                "cell_type": "code",
                "source": ["library(ggplot2)\n"],
            }
        ],
        "metadata": {
            "kernelspec": {
                "language": "R",
                "name": "ir",
            }
        },
    }
    with open("notebook-r.ipynb", "w") as f:
        json.dump(notebook_r, f)
    stage_nb_r = {
        "kind": "jupyter-notebook",
        "notebook_path": "notebook-r.ipynb",
    }
    ck_info = {
        "environments": {
            "py": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.14",
                "prefix": ".venv",
            }
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_nb_r, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "DESCRIPTION"
    assert res.spec_content is not None
    assert "IRkernel" in res.spec_content
    notebook_jl = {
        "cells": [
            {
                "cell_type": "code",
                "source": ["using DataFrames\n"],
            }
        ],
        "metadata": {
            "kernelspec": {
                "language": "julia",
                "name": "julia-1.9",
            }
        },
    }
    with open("notebook-jl.ipynb", "w") as f:
        json.dump(notebook_jl, f)
    stage_nb_jl = {
        "kind": "jupyter-notebook",
        "notebook_path": "notebook-jl.ipynb",
    }
    ck_info = {
        "environments": {
            "py": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.14",
                "prefix": ".venv",
            }
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_nb_jl, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "Project.toml"
    assert res.spec_content is not None
    assert "IJulia" in res.spec_content
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": ["using DataFrames\n"],
            }
        ],
        "metadata": {
            "kernelspec": {
                "language": "julia",
                "name": "julia-1.9",
            }
        },
    }
    with open("notebook.ipynb", "w") as f:
        json.dump(notebook, f)
    # Create Project.toml with DataFrames (so strict check passes)
    with open("Project.toml", "w") as f:
        f.write(
            '[deps]\nDataFrames = "a93c6f00-e57d-5684-b7b6-d8193f3e46c0"\n'
        )
    ck_info = {
        "environments": {
            "juliaenv": {
                "kind": "julia",
                "path": "Project.toml",
                "julia": "1.11",
            }
        }
    }
    stage_nb_exist = {
        "kind": "jupyter-notebook",
        "notebook_path": "notebook.ipynb",
    }
    res = calkit.environments.detect_env_for_stage(
        stage_nb_exist, environment=None, ck_info=ck_info
    )
    assert res.name == "juliaenv"
    assert res.exists
    # Test that a notebook with additional dependencies does NOT reuse an
    # environment that doesn't have those dependencies
    notebook_scipy = {
        "cells": [
            {
                "cell_type": "code",
                "source": [
                    "import scipy\n",
                    "import matplotlib.pyplot as plt\n",
                ],
            }
        ],
        "metadata": {
            "kernelspec": {
                "language": "python",
                "name": "python3",
            }
        },
    }
    with open("notebook-scipy.ipynb", "w") as f:
        json.dump(notebook_scipy, f)
    # Create a pyproject.toml with only numpy (the "main"
    # environment)
    with open("pyproject.toml", "w") as f:
        f.write('[project]\nname = "main"\ndependencies = ["numpy"]\n')
    ck_info = {
        "environments": {
            "main": {
                "kind": "uv",
                "path": "pyproject.toml",
            }
        }
    }
    stage_nb_scipy = {
        "kind": "jupyter-notebook",
        "notebook_path": "notebook-scipy.ipynb",
    }
    res = calkit.environments.detect_env_for_stage(
        stage_nb_scipy, environment=None, ck_info=ck_info
    )
    # Should NOT reuse "main" since it doesn't have scipy/matplotlib
    assert res.name != "main"
    # Should create a new environment with the dependencies
    assert res.created_from_dependencies
    stage_matlab = {"kind": "matlab-script", "script_path": "calc.m"}
    ck_info = {"environments": {}}
    res = calkit.environments.detect_env_for_stage(
        stage_matlab, environment=None, ck_info=ck_info
    )
    assert res.name == "_system"
    assert res.env["kind"] == "system"
    stage_latex = {"kind": "latex", "script_path": "paper.tex"}
    res = calkit.environments.detect_env_for_stage(
        stage_latex, environment=None, ck_info={"environments": {}}
    )
    assert res.env["kind"] == "docker"
    assert res.env["image"] == "texlive/texlive:latest-full"


def test_env_from_notebook_path(tmp_dir):
    with open("pyproject.toml", "w") as f:
        f.write("doesn't need to work")
    res = calkit.environments.env_from_notebook_path("notebooks/main.ipynb")
    assert res.name == "main"
    assert res.env["path"] == "pyproject.toml"
    assert res.env["kind"] == "uv"
    assert not res.exists
    # Now add to calkit.yaml--should still work
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "environments": {
                    "main": {"kind": "uv", "path": "pyproject.toml"}
                }
            },
            f,
        )
    res = calkit.environments.env_from_notebook_path("notebooks/main.ipynb")
    assert res.name == "main"
    assert res.env["path"] == "pyproject.toml"
    assert res.env["kind"] == "uv"
    assert res.exists
    # Now add a new environment and associate it with the notebook in
    # calkit.yaml--should use that one instead
    with open("requirements.txt", "w") as f:
        f.write("requests")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "environments": {
                    "main": {"kind": "uv", "path": "pyproject.toml"},
                    "notebook-env": {
                        "kind": "venv",
                        "path": "requirements.txt",
                    },
                },
                "notebooks": [
                    {
                        "path": "notebooks/main.ipynb",
                        "environment": "notebook-env",
                    }
                ],
            },
            f,
        )
    res = calkit.environments.env_from_notebook_path("notebooks/main.ipynb")
    assert res.name == "notebook-env"
    assert res.env["path"] == "requirements.txt"
    assert res.env["kind"] == "venv"
    assert res.exists
    # Check that we can detect the environment from a notebook stage
    # TODO: Handle conflicts between notebook env and stage env
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "environments": {
                    "main": {"kind": "uv", "path": "pyproject.toml"},
                    "notebook-env": {
                        "kind": "venv",
                        "path": "requirements.txt",
                    },
                },
                "pipeline": {
                    "stages": {
                        "notebook-stage": {
                            "kind": "jupyter-notebook",
                            "notebook_path": "notebooks/main.ipynb",
                            "environment": "main",
                        }
                    }
                },
                "notebooks": [
                    {
                        "path": "notebooks/main.ipynb",
                        "environment": "notebook-env",
                    }
                ],
            },
            f,
        )
    res = calkit.environments.env_from_notebook_path("notebooks/main.ipynb")
    assert res.name == "main"
    assert res.env["path"] == "pyproject.toml"
    assert res.env["kind"] == "uv"
    assert res.exists
