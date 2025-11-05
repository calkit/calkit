"""Tests for the ``dvc`` module."""

import subprocess
from pathlib import Path

import calkit


def test_get_remotes(tmp_dir):
    subprocess.call(["git", "init"])
    assert not calkit.dvc.get_remotes()
    subprocess.call(["dvc", "init"])
    assert not calkit.dvc.get_remotes()
    subprocess.call(
        [
            "dvc",
            "remote",
            "add",
            "something",
            "https://sup.com",
        ]
    )
    subprocess.call(
        [
            "dvc",
            "remote",
            "add",
            "something-very-long-remote-that-will-be-more-than-one-line",
            "https://sup.com/this/is/a/long/remote/url/so/test/this",
        ]
    )
    resp = calkit.dvc.get_remotes()
    assert resp == {
        "something": "https://sup.com",
        "something-very-long-remote-that-will-be-more-than-one-line": (
            "https://sup.com/this/is/a/long/remote/url/so/test/this"
        ),
    }


def test_get_stage_outputs_string_and_dict():
    # Create a dvc.yaml
    dvc_yaml = Path("dvc.yaml")
    content = """
stages:
  build_model:
    cmd: python train.py
    outs:
      - data/model.pkl
      - results/output.csv
      - logs/run.log:
        - cache: false
"""
    dvc_yaml.write_text(content)
    outs = calkit.dvc.get_stage_outputs("build_model")
    expected = ["data/model.pkl", "results/output.csv", "logs/run.log"]

    assert sorted(outs) == sorted(expected)
