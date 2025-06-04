"""Tests for ``calkit.pipeline``."""

import pytest

import calkit.pipeline


def test_to_dvc():
    # Test typical proper usage
    ck_info = {
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
        }
    }
    stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=False)
    stage = stages["get-data"]
    assert stage["outs"][0] == "my-output.out"
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
