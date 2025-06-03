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
