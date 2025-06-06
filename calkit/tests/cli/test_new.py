"""Tests for ``cli.new``."""

import os
import subprocess

import git
import pytest

import calkit


def test_new_foreach_stage(tmp_dir):
    subprocess.check_call(["calkit", "init"])
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
    subprocess.check_call(["calkit", "init"])
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
    subprocess.check_call(["calkit", "init"])
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
    assert ck_info["environments"]["my-latex-env"] == dict(
        kind="docker",
        image="texlive/texlive:latest-full",
        description="TeXlive full.",
    )
    assert ck_info["publications"][0]["path"] == "my-paper/paper.pdf"
    stage = ck_info["pipeline"]["stages"]["build-latex-article"]
    assert stage["kind"] == "latex"
    assert stage["environment"] == "my-latex-env"
    assert stage["target_path"] == "my-paper/paper.tex"
    assert stage["outputs"] == ["my-paper/paper.pdf"]


def test_new_uv_venv(tmp_dir):
    subprocess.check_call(["calkit", "init"])
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
    ck_info = calkit.load_calkit_info_object()
    envs = ck_info.environments
    env = envs["my-uv-venv"]
    assert isinstance(env, calkit.models.UvVenvEnvironment)
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
    ck_info = calkit.load_calkit_info_object()
    envs = ck_info.environments
    env = envs["my-uv-venv2"]
    assert isinstance(env, calkit.models.UvVenvEnvironment)
    assert env.path == "requirements-2.txt"
    assert env.prefix == ".venv2"
    assert env.kind == "uv-venv"


def test_new_project(tmp_dir):
    subprocess.check_call(
        ["calkit", "new", "project", ".", "--title", "My new project"]
    )
    repo = git.Repo()
    assert repo.git.ls_files("calkit.yaml")
    assert repo.git.ls_files("README.md")
    assert repo.git.ls_files(".devcontainer")
    ck_info = calkit.load_calkit_info()
    assert ck_info["title"] == "My new project"


def test_new_project_existing_repo(tmp_dir):
    subprocess.check_call(["git", "init"])
    subprocess.check_call(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/someone/somerepo.git",
        ]
    )
    subprocess.check_call(
        ["calkit", "new", "project", ".", "--title", "My new project"]
    )
    repo = git.Repo()
    assert repo.git.ls_files("calkit.yaml")
    assert repo.git.ls_files("README.md")
    assert repo.git.ls_files(".devcontainer")
    ck_info = calkit.load_calkit_info()
    assert ck_info["title"] == "My new project"


def test_new_project_existing_files(tmp_dir):
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


def test_new_stage(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "docker-env",
            "--name",
            "tex",
            "--image",
            "texlive/texlive:latest-full",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "--name",
            "py",
            "requests",
        ]
    )
    with open("plot.py", "w") as f:
        f.write("print('hi')")
    with open("paper.tex", "w") as f:
        f.write("Hello")
    with open("data.csv", "w") as f:
        f.write("data")
    # Create a Python script stage
    subprocess.check_call(
        [
            "calkit",
            "new",
            "stage",
            "--name",
            "plot",
            "--kind",
            "python-script",
            "--environment",
            "py",
            "--target",
            "plot.py",
            "--dep",
            "data.csv",
            "--out",
            "plot1.png",
            "-o",
            "plot2.png",
        ]
    )
    pipeline = calkit.dvc.read_pipeline()
    assert (
        pipeline["stages"]["plot"]["cmd"]
        == "calkit xenv -n py -- python plot.py"
    )
    assert set(pipeline["stages"]["plot"]["deps"]) == set(
        ["plot.py", "data.csv", "requirements.txt"]
    )
    assert set(pipeline["stages"]["plot"]["outs"]) == set(
        ["plot1.png", "plot2.png"]
    )
    # Create a LaTeX stage
    subprocess.check_call(
        [
            "calkit",
            "new",
            "stage",
            "--name",
            "build-paper",
            "--kind",
            "latex",
            "--environment",
            "tex",
            "--target",
            "paper.tex",
            "--dep",
            "plot1.png",
            "-d",
            "plot2.png",
            "--out",
            "paper.pdf",
        ]
    )
    pipeline = calkit.dvc.read_pipeline()
    assert pipeline["stages"]["build-paper"]["cmd"] == (
        "calkit xenv -n tex -- "
        "latexmk -cd -interaction=nonstopmode -pdf paper.tex"
    )
    assert set(pipeline["stages"]["build-paper"]["deps"]) == set(
        [
            "paper.tex",
            "plot1.png",
            "plot2.png",
        ]
    )
    assert pipeline["stages"]["build-paper"]["outs"] == ["paper.pdf"]
    # Check that we can create a MATLAB script with no environment
    with open("script.m", "w") as f:
        f.write("script")
    subprocess.check_call(
        [
            "calkit",
            "new",
            "stage",
            "--name",
            "plot",
            "-f",
            "--kind",
            "matlab-script",
            "--target",
            "script.m",
            "--dep",
            "data.csv",
            "--out",
            "plot1.png",
            "-o",
            "plot2.png",
        ]
    )
    pipeline = calkit.dvc.read_pipeline()
    assert (
        pipeline["stages"]["plot"]["cmd"]
        == "matlab -noFigureWindows -batch \"run('script.m');\""
    )
    assert set(pipeline["stages"]["plot"]["deps"]) == set(
        ["script.m", "data.csv"]
    )
    assert set(pipeline["stages"]["plot"]["outs"]) == set(
        ["plot1.png", "plot2.png"]
    )
    # Check that we fail for a nonexistent target
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(
            [
                "calkit",
                "new",
                "stage",
                "--name",
                "plot",
                "-f",
                "--kind",
                "matlab-script",
                "--target",
                "script2.m",
                "--out",
                "plot1.png",
                "-o",
                "plot2.png",
            ]
        )
    # Check that we fail to create a stage with a non-existent environment
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(
            [
                "calkit",
                "new",
                "stage",
                "--name",
                "plot",
                "-f",
                "--kind",
                "python-script",
                "--target",
                "plot.py",
                "--out",
                "plot1.png",
                "-o",
                "plot2.png",
                "-e",
                "nonexistent-env",
            ]
        )


def test_new_python_script_stage(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    with open("script.py", "w") as f:
        f.write("print('Hello, world!')")
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "--name",
            "py",
            "--python",
            "3.13",
            "requests",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "python-script-stage",
            "--name",
            "run-script",
            "--script-path",
            "script.py",
            "--environment",
            "py",
            "--output",
            "output.txt",
        ]
    )
    subprocess.check_call(["calkit", "check", "pipeline", "--compile"])
    pipeline = calkit.dvc.read_pipeline()
    assert pipeline["stages"]["run-script"]["cmd"] == (
        "calkit xenv -n py --no-check -- python script.py"
    )
    assert set(pipeline["stages"]["run-script"]["deps"]) == set(
        ["script.py", ".calkit/env-locks/py.txt"]
    )
    assert pipeline["stages"]["run-script"]["outs"] == ["output.txt"]
    subprocess.check_call(
        [
            "calkit",
            "new",
            "python-script-stage",
            "--name",
            "run-script-2",
            "--script-path",
            "script2.py",
            "--arg",
            "{name}",
            "--environment",
            "py",
            "--output",
            "output-{name}.txt",
            "--iter",
            "name",
            "bob,joe,sally",
        ]
    )
    subprocess.check_call(["calkit", "check", "pipeline", "--compile"])
    pipeline = calkit.dvc.read_pipeline()
    assert pipeline["stages"]["run-script-2"]["cmd"] == (
        "calkit xenv -n py --no-check -- python script2.py ${item.name}"
    )
    assert pipeline["stages"]["run-script-2"]["outs"] == [
        "output-${item.name}.txt"
    ]
    assert pipeline["stages"]["run-script-2"]["matrix"]["name"] == [
        "bob",
        "joe",
        "sally",
    ]


def test_new_latex_stage(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    with open("paper.tex", "w") as f:
        f.write("Hello, world!")
    subprocess.check_call(
        [
            "calkit",
            "new",
            "docker-env",
            "--name",
            "tex",
            "--image",
            "texlive/texlive:latest-full",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "latex-stage",
            "--name",
            "build-paper",
            "--target",
            "paper.tex",
            "--environment",
            "tex",
            "--output",
            "paper.pdf",
        ]
    )
    subprocess.check_call(["calkit", "check", "pipeline", "--compile"])
    pipeline = calkit.dvc.read_pipeline()
    assert pipeline["stages"]["build-paper"]["cmd"] == (
        "calkit xenv -n tex --no-check -- "
        "latexmk -cd -interaction=nonstopmode -pdf paper.tex"
    )
    assert set(pipeline["stages"]["build-paper"]["deps"]) == set(
        ["paper.tex", ".calkit/env-locks/tex.json"]
    )
    assert pipeline["stages"]["build-paper"]["outs"] == ["paper.pdf"]


def test_new_matlab_script_stage(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    os.makedirs("scripts")
    with open("scripts/script.m", "w") as f:
        f.write("disp('Hello, world!')")
    subprocess.check_call(
        [
            "calkit",
            "new",
            "docker-env",
            "--name",
            "matlab1",
            "--image",
            "mathworks/matlab:latest",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "matlab-script-stage",
            "--name",
            "run-script1",
            "-e",
            "matlab1",
            "--script-path",
            "scripts/script.m",
            "--output",
            "results/output.txt",
            "--output",
            "results/output2.txt",
        ]
    )
    subprocess.check_call(["calkit", "check", "pipeline", "--compile"])
    pipeline = calkit.dvc.read_pipeline()
    assert pipeline["stages"]["run-script1"]["cmd"] == (
        "calkit xenv -n matlab1 --no-check -- \"run('scripts/script.m');\""
    )
    assert set(pipeline["stages"]["run-script1"]["deps"]) == set(
        ["scripts/script.m", ".calkit/env-locks/matlab1.json"]
    )
    assert pipeline["stages"]["run-script1"]["outs"] == [
        "results/output.txt",
        "results/output2.txt",
    ]
