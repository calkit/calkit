"""Tests for ``cli.new``."""

import os
import subprocess

import pytest

import calkit


def test_new_foreach_stage(tmp_dir):
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["dvc", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "foreach-stage",
            "-n",
            "stage1",
            "--cmd",
            "echo {var} > {var}.txt",
            "--out",
            "{var}.txt",
            "one",
            "two",
            "three",
        ]
    )
    subprocess.check_call(["calkit", "run"])
    assert os.path.isfile("one.txt")
    # Add another stage that depends on one of these outputs
    subprocess.check_call(
        [
            "calkit",
            "new",
            "foreach-stage",
            "-n",
            "stage2",
            "--cmd",
            "cat {var}.txt > {var}-2.txt",
            "--out",
            "{var}-2.txt",
            "--dep",
            "{var}.txt",
            "one",
            "two",
            "three",
        ]
    )
    subprocess.check_call(["calkit", "run"])
    assert os.path.isfile("two-2.txt")


def test_new_figure(tmp_dir):
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["dvc", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "figure",
            "--title",
            "This is a cool figure",
            "--description",
            "This is a cool description",
            "myfigure.png",
        ]
    )
    ck_info = calkit.load_calkit_info()
    assert "myfigure.png" in [fig["path"] for fig in ck_info["figures"]]
    # Check that we won't overwrite a figure
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(
            [
                "calkit",
                "new",
                "figure",
                "--title",
                "This is a cool figure",
                "--description",
                "This is a cool description",
                "myfigure.png",
            ]
        )
    # Check that we can create a stage
    subprocess.check_call(
        [
            "calkit",
            "new",
            "figure",
            "--title",
            "This is a cool figure 2",
            "myfigure2.png",
            "--stage",
            "create-figure",
            "--cmd",
            "python plot.py",
            "--dep",
            "plot.py",
            "--dep",
            "data.csv",
        ]
    )
    pipeline = calkit.dvc.read_pipeline()
    stage = pipeline["stages"]["create-figure"]
    assert stage["cmd"] == "python plot.py"
    assert set(stage["deps"]) == set(["plot.py", "data.csv"])
    assert stage["outs"] == ["myfigure2.png"]
    # Test that we can use outs from stage
    subprocess.check_call(
        [
            "calkit",
            "new",
            "figure",
            "myfigure3.png",
            "--title",
            "This is a cool figure 3",
            "--stage",
            "create-figure3",
            "--cmd",
            "python plot.py",
            "--deps-from-stage-outs",
            "create-figure",
        ]
    )
    pipeline = calkit.dvc.read_pipeline()
    assert pipeline["stages"]["create-figure3"]["deps"] == ["myfigure2.png"]
