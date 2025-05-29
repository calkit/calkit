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
                            "store_with": "git",
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
