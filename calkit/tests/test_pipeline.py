"""Tests for ``calkit.pipeline``."""

import subprocess

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
                    "environment": "py",
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
    # Test we can use parameters and iterations in notebook stages
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
                    "parameters": {
                        "param1": "{param1}",
                        "param2": "{param2}",
                        "param3": "{param3}",
                    },
                    "iterate_over": [
                        {
                            "arg_name": "param1",
                            "values": [{"parameter": "param1"}],
                        },
                        {
                            "arg_name": "param2",
                            "values": [{"parameter": "param2"}],
                        },
                        {
                            "arg_name": "param3",
                            "values": [{"parameter": "param3"}],
                        },
                    ],
                },
            }
        },
    }
    dvc_stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    print(dvc_stages)
    stage = dvc_stages["notebook-1"]
    assert stage["cmd"].startswith("calkit nb execute")
    assert "--params-base64" in stage["cmd"]
    assert stage["matrix"]["param1"][0] == 5.0
    assert "m" in stage["matrix"]["param2"]
    assert "something" in stage["matrix"]["param3"]


def test_to_dvc_list_of_list_iteration():
    # Test that we can define iteration over a list of lists
    ck_info = {
        "pipeline": {
            "stages": {
                "get-data": {
                    "kind": "python-script",
                    "environment": "something",
                    "script_path": "something/my-cool-script.py",
                    "args": ["--a1={var1}", "--a2={var2}"],
                    "iterate_over": [
                        {
                            "arg_name": ["var1", "var2"],
                            "values": [[1, "a"], [2, "b"], [3, "c"]],
                        },
                    ],
                    "outputs": [
                        "out-{var1}-{var2}.out",
                        "out2-{var1}-{var2}.out",
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
    stage = dvc_stages["get-data"]
    assert "--a1=${item._arg0.var1} --a2=${item._arg0.var2}" in stage["cmd"]
    matrix = stage["matrix"]
    assert matrix == {
        "_arg0": [
            {"var1": 1, "var2": "a"},
            {"var1": 2, "var2": "b"},
            {"var1": 3, "var2": "c"},
        ]
    }
    assert stage["outs"] == [
        "out-${item._arg0.var1}-${item._arg0.var2}.out",
        "out2-${item._arg0.var1}-${item._arg0.var2}.out",
    ]
    print(dvc_stages)
    stage2 = dvc_stages["process-data"]
    assert "out-1-a.out" in stage2["deps"]
    assert "out2-2-b.out" in stage2["deps"]


def test_remove_stage(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    # Test that we can remove a stage from the pipeline
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
                    "environment": "py",
                    "script_path": "something/my-cool-script.py",
                    "outputs": [
                        "my-output.out",
                    ],
                },
                "process-data": {
                    "kind": "python-script",
                    "script_path": "something.py",
                    "environment": "py",
                    "inputs": ["my-input.txt"],
                },
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "check", "pipeline", "-c"])
    with open("dvc.yaml", "r") as f:
        dvc_yaml = calkit.ryaml.load(f)
    assert "get-data" in dvc_yaml["stages"]
    assert "process-data" in dvc_yaml["stages"]
    # Now remove the get-data stage
    ck_info["pipeline"]["stages"].pop("get-data")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "check", "pipeline", "-c"])
    with open("dvc.yaml", "r") as f:
        dvc_yaml = calkit.ryaml.load(f)
    assert "get-data" not in dvc_yaml["stages"]
    assert "process-data" in dvc_yaml["stages"]


def test_sbatch_stage_to_dvc():
    pipeline = {
        "stages": {
            "job1": {
                "kind": "sbatch",
                "script_path": "scripts/run_job.sh",
                "environment": "slurm-env",
                "args": ["something", "else"],
                "sbatch_options": ["--time=01:00:00", "--mem=4G"],
                "inputs": ["data/input.txt"],
                "outputs": [
                    {
                        "path": "data/output.txt",
                        "storage": "git",
                        "delete_before_run": False,
                    },
                    "data/output2.txt",
                ],
            }
        }
    }
    stages = calkit.pipeline.to_dvc(
        ck_info={"pipeline": pipeline}, write=False
    )
    stage = stages["job1"]
    print(stage)
    assert stage["cmd"] == (
        "calkit slurm batch --name job1 --environment slurm-env "
        "--dep data/input.txt --out data/output2.txt "
        "-s --time=01:00:00 -s --mem=4G -- scripts/run_job.sh something else"
    )
    assert "scripts/run_job.sh" in stage["deps"]
    assert "data/input.txt" in stage["deps"]
    out = {"data/output.txt": {"cache": False, "persist": True}}
    assert out in stage["outs"]
