"""Tests for ``calkit.pipeline``."""

import pytest

import calkit.pipeline


def test_to_dvc():
    # Test typical proper usage
    ck_info = {
        "environments": {
            "py": {
                "kind": "venv",
                "path": "requirements.txt",
                "prefix": ".venv",
            }
        },
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "environment": "my-env",
                    "script_path": "something/my-cool-script.py",
                    "outputs": [
                        "my-output.out",
                        {
                            "path": "something/else.pickle",
                            "storage": "git",
                            "delete_before_run": False,
                        },
                    ],
                }
            }
        },
    }
    stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    stage = stages["get-data"]
    assert stage["outs"][0] == "my-output.out"
    stage = stages["_check-env-py"]
    assert stage["deps"] == ["requirements.txt"]
    assert stage["cmd"] == "calkit check environment --name py"
    assert stage["desc"].startswith("Automatically generated")
    out = stage["outs"][0]
    out_path = list(out.keys())[0]
    assert out_path == ".calkit/env-locks/py.txt"
    assert not out[out_path]["cache"]
    # TODO: Test other stage types
    # Test when user forgets to add an environment
    ck_info = {
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "script_path": "something/my-cool-script.py",
                    "outputs": [
                        "my-output.out",
                    ],
                }
            }
        }
    }
    with pytest.raises(ValueError):
        calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    # Test that we can define inputs from stage outputs
    ck_info = {
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "environment": "something",
                    "script_path": "something/my-cool-script.py",
                    "outputs": [
                        "my-output.out",
                    ],
                },
                "process-data": {
                    "kind": "python-script",
                    "script_path": "something.py",
                    "environment": "py",
                    "inputs": [
                        {"from_stage_outputs": "get-data"},
                        "something.else.txt",
                    ],
                },
            }
        }
    }
    dvc_stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    print(dvc_stages)
    assert "my-output.out" in dvc_stages["process-data"]["deps"]
    assert "something.else.txt" in dvc_stages["process-data"]["deps"]
    # Test a complex pipeline with iterations and parameters
    ck_info = {
        "parameters": {
            "param1": [{"range": {"start": 5, "stop": 23, "step": 2}}],
            "param2": ["s", "m", "l"],
            "param3": [
                {"range": {"start": 0.1, "stop": 1.1, "step": 0.11}},
                55,
                "something",
            ],
        },
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "environment": "something",
                    "script_path": "something/my-cool-script.py",
                    "args": ["{my_parameter}"],
                    "outputs": [
                        "my-output.out",
                    ],
                    "iterate_over": [
                        {"arg_name": "my_parameter", "values": [1, 2, 3.5]}
                    ],
                },
                "process-data": {
                    "kind": "python-script",
                    "script_path": "something.py",
                    "args": ["--something", "{param_a}"],
                    "environment": "py",
                    "inputs": ["my-input-{param_a}"],
                    "outputs": ["out-{param_a}.txt"],
                    "iterate_over": [
                        {
                            "arg_name": "param_a",
                            "values": [{"parameter": "param3"}],
                        }
                    ],
                },
            }
        },
    }
    dvc_stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    matrix = dvc_stages["process-data"]["matrix"]
    assert matrix["param_a"][0] == 0.1
    assert 55 in matrix["param_a"]
    assert "something" in matrix["param_a"]
    outs = dvc_stages["process-data"]["outs"]
    assert outs[0] == "out-${item.param_a}.txt"
    print(dvc_stages)


def test_to_dvc_from_matrix_outs():
    # Test that we can define inputs from matrix stage outputs
    ck_info = {
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "environment": "something",
                    "script_path": "something/my-cool-script.py",
                    "iterate_over": [
                        {"arg_name": "var1", "values": [1, 2, 3]},
                        {"arg_name": "var2", "values": ["a", "b", "c"]},
                    ],
                    "outputs": [
                        "out-{var1}-{var2}.out",
                    ],
                },
                "process-data": {
                    "kind": "python-script",
                    "script_path": "something.py",
                    "environment": "py",
                    "inputs": [
                        {"from_stage_outputs": "get-data"},
                        "something.else.txt",
                    ],
                },
            }
        }
    }
    dvc_stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    print(dvc_stages)
    for var1 in [1, 2, 3]:
        for var2 in ["a", "b", "c"]:
            assert (
                f"out-{var1}-{var2}.out" in dvc_stages["process-data"]["deps"]
            )
    assert "something.else.txt" in dvc_stages["process-data"]["deps"]


def test_to_dvc_notebook_stage():
    # Test we can create a notebook stage properly, which involves a cleaning
    # stage to use as a DVC dependency
    nb_path = "something/my-cool-notebook.ipynb"
    ck_info = {
        "pipeline": {
            "stages": {
                "notebook-1": {
                    "kind": "jupyter-notebook",
                    "environment": "something",
                    "notebook_path": nb_path,
                    "outputs": [
                        "figures/fig1.png",
                    ],
                    "html_storage": "dvc",
                    "cleaned_ipynb_storage": "git",
                    "executed_ipynb_storage": None,
                },
            }
        }
    }
    dvc_stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    print(dvc_stages)
    clean_stage = dvc_stages["_clean-nb-notebook-1"]
    assert clean_stage["cmd"] == f'calkit nb clean "{nb_path}"'
    assert clean_stage["desc"].startswith("Automatically generated")
    stage = dvc_stages["notebook-1"]
    assert "--to html" in stage["cmd"]
    found_html = False
    for out in stage["outs"]:
        if not isinstance(out, dict):
            continue
        p = list(out.keys())[0]
        if p.endswith(".html"):
            found_html = True
            assert out[p]["cache"]
    assert found_html
