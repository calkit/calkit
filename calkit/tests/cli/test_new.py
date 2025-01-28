"""Tests for ``cli.new``."""

import os
import subprocess

import git
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
            "--description",
            "This is the description.",
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
            "--description",
            "This is the description.",
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


def test_new_publication(tmp_dir):
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["dvc", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "publication",
            "my-paper",
            "--template",
            "latex/article",
            "--kind",
            "journal-article",
            "--title",
            "This is a cool title",
            "--description",
            "This is a cool description.",
            "--stage",
            "build-latex-article",
            "--environment",
            "my-latex-env",
        ]
    )
    ck_info = calkit.load_calkit_info()
    print(ck_info)
    assert ck_info["environments"]["my-latex-env"] == {
        "_include": ".calkit/environments/my-latex-env.yaml"
    }
    assert ck_info["publications"][0]["path"] == "my-paper/paper.pdf"
    with open("dvc.yaml") as f:
        dvc_pipeline = calkit.ryaml.load(f)
    print(dvc_pipeline)
    stage = dvc_pipeline["stages"]["build-latex-article"]
    assert stage["cmd"] == (
        "calkit xenv -n my-latex-env -- "
        "latexmk -cd -interaction=nonstopmode -pdf my-paper/paper.tex"
    )


def test_new_uv_venv(tmp_dir):
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["dvc", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "my-uv-venv",
            "pandas>=2.0",
            "matplotlib",
        ]
    )
    ck_info = calkit.load_calkit_info(as_pydantic=True)
    envs = ck_info.environments
    env = envs["my-uv-venv"]
    assert env.path == "requirements.txt"
    assert env.prefix == ".venv"
    assert env.kind == "uv-venv"
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "my-uv-venv2",
            "--path",
            "requirements-2.txt",
            "--prefix",
            ".venv2",
            "pandas>=2.0",
            "matplotlib",
        ]
    )
    ck_info = calkit.load_calkit_info(as_pydantic=True)
    envs = ck_info.environments
    env = envs["my-uv-venv2"]
    assert env.path == "requirements-2.txt"
    assert env.prefix == ".venv2"
    assert env.kind == "uv-venv"


def test_new_project(tmp_dir):
    subprocess.check_call(["touch", "some-existing-file.txt"])
    subprocess.check_call(
        ["calkit", "new", "project", ".", "--title", "My new project"]
    )
    repo = git.Repo()
    assert "some-existing-file.txt" in repo.untracked_files
    assert repo.git.ls_files("calkit.yaml")
    assert repo.git.ls_files("README.md")
    assert not repo.git.ls_files("some-other-file.txt")
    assert repo.git.ls_files(".devcontainer")
    ck_info = calkit.load_calkit_info()
    assert ck_info["title"] == "My new project"
