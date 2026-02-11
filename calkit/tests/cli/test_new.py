"""Tests for ``cli.new``."""

import os
import subprocess

import git
import pytest

import calkit
from calkit.environments import get_env_lock_fpath


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


def test_new_uv_env(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-env",
            "--name",
            "my-uv-env",
            "--python",
            "3.13",
            "requests",
        ]
    )
    ck_info = calkit.load_calkit_info()
    env = ck_info["environments"]["my-uv-env"]
    assert env["path"] == ".calkit/envs/my-uv-env/pyproject.toml"
    assert env["prefix"] == ".calkit/envs/my-uv-env/.venv"
    # Test one in the root of the project
    # TODO: We should make one at the root first if there isn't one, then
    # move into subdirs?
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-env",
            "--name",
            "main",
            "--path",
            "pyproject.toml",
            "--python",
            "3.13",
            "requests",
        ]
    )
    ck_info = calkit.load_calkit_info()
    env = ck_info["environments"]["main"]
    assert env["path"] == "pyproject.toml"
    assert env["prefix"] == ".venv"


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


def test_new_conda_env(tmp_dir):
    with open("environment.yml", "w") as f:
        calkit.ryaml.dump(
            {
                "dependencies": ["python", "requests"],
                "name": "whatever",
                "channels": ["conda-forge"],
            },
            f,
        )
    subprocess.check_call(
        ["calkit", "new", "project", ".", "--name", "test", "--title", "Test"]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "--path",
            "environment.yml",
            "--name",
            "e1",
            "--no-check",
        ]
    )
    with open("environment.yml") as f:
        env = calkit.ryaml.load(f)
    assert env["name"] == "test-e1"
    assert env["dependencies"] == ["python", "requests"]


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
            "--no-check",
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
        "calkit latex build paper.tex --environment tex"
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
            "--no-check",
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
    env_lock_fpath = get_env_lock_fpath(
        calkit.load_calkit_info()["environments"]["py"], "py", for_dvc=True
    )
    assert set(pipeline["stages"]["run-script"]["deps"]) == set(
        ["script.py", env_lock_fpath]
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
            "--no-check",
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
        "calkit latex build -e tex --no-check paper.tex"
    )
    ck_info = calkit.load_calkit_info()
    env = ck_info["environments"]["tex"]
    env_lock_fpath = get_env_lock_fpath(env, "tex", for_dvc=True)
    assert set(pipeline["stages"]["build-paper"]["deps"]) == set(
        ["paper.tex", env_lock_fpath]
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
            "--no-check",
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
    env_lock_fpath = get_env_lock_fpath(
        calkit.load_calkit_info()["environments"]["matlab1"],
        "matlab1",
        for_dvc=True,
    )
    assert set(pipeline["stages"]["run-script1"]["deps"]) == set(
        ["scripts/script.m", env_lock_fpath]
    )
    assert pipeline["stages"]["run-script1"]["outs"] == [
        "results/output.txt",
        "results/output2.txt",
    ]


def test_new_julia_env(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        ["calkit", "new", "julia-env", "--name", "j1", "WaterLily"]
    )
    assert os.path.isfile("Project.toml")
    assert os.path.isfile("Manifest.toml")
    subprocess.check_call(
        [
            "calkit",
            "new",
            "julia-env",
            "--name",
            "j2",
            "--julia",
            "1.10",
            "Revise",
            "--path",
            "envs/my-env/Project.toml",
        ]
    )
    assert os.path.isfile("envs/my-env/Project.toml")
    assert os.path.isfile("envs/my-env/Manifest.toml")


def test_new_release(tmp_dir):
    subprocess.check_call(
        [
            "calkit",
            "new",
            "project",
            ".",
            "--title",
            "Test project",
            "--name",
            "test-project",
        ]
    )
    subprocess.check_call(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/calkit/test-project.git",
        ]
    )
    # TODO: Add project description?
    # Add authors
    authors = [
        {
            "first_name": "Alice",
            "last_name": "Smith",
            "affiliation": "SomeU",
            "orcid": "0000-0001-2345-6789",
        },
        {
            "first_name": "Bob",
            "last_name": "Jones",
            "affiliation": None,
            "orcid": None,
        },
    ]
    ck_info = calkit.load_calkit_info()
    ck_info["authors"] = authors
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    # Add a default license
    subprocess.check_call(
        [
            "calkit",
            "update",
            "license",
            "--copyright-holder",
            "Some Person",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "release",
            "--name",
            "v0.1.0",
            "--description",
            "First release.",
            "--draft",
            "--no-github",
            "--verbose",
        ]
    )
    ck_info = calkit.load_calkit_info()
    assert "v0.1.0" in ck_info["releases"]
    release = ck_info["releases"]["v0.1.0"]
    assert release["doi"] is not None
    # TODO: Test that the GitHub link is in the related works
    # Test that we can update this release
    # Side note: This is revealing some design weirdness where we're grouping
    # functionality under verbs and not the type of resource they act on
    # This leads to a more English-like CLI, but we may want to organize the
    # logic by resource type
    subprocess.check_call(
        ["calkit", "update", "release", "--name", "v0.1.0", "--reupload"]
    )
    # TODO: Check that the files were actually updated, not just that there
    # were not errors
    # TODO: Check that the git rev of the release was updated
    # Test publishing the release
    subprocess.check_call(
        [
            "calkit",
            "update",
            "release",
            "--latest",
            "--publish",
            "--no-github",
            "--no-push-tags",
        ]
    )
    # Check Git tags for the release name
    git_tags = git.Repo().tags
    assert "v0.1.0" in [tag.name for tag in git_tags]
    # Check the license is correct
    # TODO: It seems like we can't use multiple license IDs with the API
    record_id = release["record_id"]
    record = calkit.invenio.get(f"/records/{record_id}")
    metadata = record["metadata"]
    print(metadata)
    assert metadata["license"] == {"id": "cc-by-4.0"}
    related = metadata["related_identifiers"]
    assert related[0]["identifier"] == "https://github.com/calkit/test-project"
    # TODO: Test that we can delete the release
    # This will fail if it's not a draft
    # subprocess.check_call(
    #     ["calkit", "update", "release", "--name", "v0.1.0", "--delete"]
    # )
