"""Tests for ``cli.update``."""

import json
import os
import subprocess
import sys

import pytest
from typer.testing import CliRunner

import calkit
import calkit.resources
from calkit.cli.update import update_app

runner = CliRunner()


def test_update_project_config(tmp_dir, monkeypatch):
    # These all write bundled resources, so none should touch the network
    def fail(*args, **kwargs):
        raise AssertionError("Should not make any HTTP requests")

    import requests

    monkeypatch.setattr(requests, "get", fail)
    subprocess.check_call(["calkit", "init"])
    result = runner.invoke(update_app, ["devcontainer"])
    assert result.exit_code == 0
    with open(os.path.join(".devcontainer", "devcontainer.json")) as f:
        assert json.load(f) == calkit.resources.load_json(
            "devcontainer", calkit.resources.DEVCONTAINER_FNAME
        )
    result = runner.invoke(update_app, ["vscode-config"])
    assert result.exit_code == 0
    for fname in calkit.resources.VSCODE_FNAMES:
        with open(os.path.join(".vscode", fname)) as f:
            assert json.load(f) == calkit.resources.load_json("vscode", fname)
    result = runner.invoke(update_app, ["github-actions"])
    assert result.exit_code == 0
    with open(os.path.join(".github", "workflows", "run-calkit.yml")) as f:
        assert f.read() == calkit.resources.render_github_actions_workflow()
    repo = calkit.git.get_repo()
    assert repo.git.ls_files(".devcontainer")
    assert repo.git.ls_files(".vscode")
    assert repo.git.ls_files(".github")
    assert not repo.git.status("--porcelain")
    # All three should be safe to rerun
    assert runner.invoke(update_app, ["devcontainer"]).exit_code == 0
    assert runner.invoke(update_app, ["vscode-config"]).exit_code == 0
    assert runner.invoke(update_app, ["github-actions"]).exit_code == 0
    assert not repo.git.status("--porcelain")


def test_update_github_actions(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    workflow_dir = os.path.join(".github", "workflows")
    ref = calkit.resources.get_action_ref()
    # A project that mentions Calkit in an unrelated workflow should get its
    # own, and that workflow should be left alone
    os.makedirs(workflow_dir, exist_ok=True)
    other_fpath = os.path.join(workflow_dir, "docs.yml")
    other_txt = "name: Docs\njobs:\n  main:\n    steps:\n      - run: calkit\n"
    with open(other_fpath, "w") as f:
        f.write(other_txt)
    assert runner.invoke(update_app, ["github-actions"]).exit_code == 0
    with open(other_fpath) as f:
        assert f.read() == other_txt
    out_fpath = os.path.join(workflow_dir, "run-calkit.yml")
    with open(out_fpath) as f:
        assert f.read() == calkit.resources.render_github_actions_workflow()
    # A workflow written by an older version of Calkit, which is still the
    # example, should be replaced outright so it picks up any other changes
    # to it, wherever it lives
    os.remove(out_fpath)
    old_fpath = os.path.join(workflow_dir, "run.yml")
    with open(old_fpath, "w") as f:
        f.write(
            calkit.resources.render_github_actions_workflow(version="0.1.0")
        )
    assert runner.invoke(update_app, ["github-actions"]).exit_code == 0
    assert not os.path.isfile(out_fpath)
    with open(old_fpath) as f:
        assert f.read() == calkit.resources.render_github_actions_workflow()
    # A customized workflow, here one still pointing at the action's previous
    # home, should only have its action ref updated
    custom_txt = (
        "name: Run pipeline\n"
        "jobs:\n"
        "  main:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: calkit/run-action@v2\n"
        "        with:\n"
        "          extra-args: --no-check\n"
        "      - run: echo custom\n"
    )
    with open(old_fpath, "w") as f:
        f.write(custom_txt)
    assert runner.invoke(update_app, ["github-actions"]).exit_code == 0
    with open(old_fpath) as f:
        updated_txt = f.read()
    assert updated_txt == custom_txt.replace("calkit/run-action@v2", ref)
    # Rerunning should be a no-op, and shouldn't leave anything uncommitted
    repo = calkit.git.get_repo()
    repo.git.add(".github")
    repo.git.commit(["-m", "Add workflows"])
    assert runner.invoke(update_app, ["github-actions"]).exit_code == 0
    with open(old_fpath) as f:
        assert f.read() == updated_txt
    assert not repo.git.status("--porcelain")


def test_update_uv_env(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-env",
            "-n",
            "myenv",
            "--python",
            "3.13",
            "--no-check",
            "requests",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "update",
            "uv-env",
            "-n",
            "myenv",
            "--add",
            "numpy",
            "--no-check",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "update",
            "uv-env",
            "-n",
            "myenv",
            "--rm",
            "numpy",
            "--no-check",
        ]
    )


def test_update_conda_env(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    with open("environment.yml", "w") as f:
        calkit.ryaml.dump(
            {
                "name": "test",
                "channels": ["conda-forge"],
                "dependencies": ["python", "requests", {"pip": ["httpx"]}],
            },
            f,
        )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "-n",
            "myenv",
            "--path",
            "environment.yml",
            "--no-check",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "update",
            "conda-env",
            "-n",
            "myenv",
            "--add",
            "numpy",
            "--no-check",
        ]
    )
    with open("environment.yml") as f:
        spec = calkit.ryaml.load(f)
    conda_deps = [d for d in spec["dependencies"] if isinstance(d, str)]
    assert "numpy" in conda_deps
    subprocess.check_call(
        [
            "calkit",
            "update",
            "conda-env",
            "-n",
            "myenv",
            "--rm",
            "numpy",
            "--no-check",
        ]
    )
    with open("environment.yml") as f:
        spec = calkit.ryaml.load(f)
    conda_deps = [d for d in spec["dependencies"] if isinstance(d, str)]
    assert "numpy" not in conda_deps
    # Test pip add/remove
    subprocess.check_call(
        [
            "calkit",
            "update",
            "conda-env",
            "-n",
            "myenv",
            "--add-pip",
            "rich",
            "--no-check",
        ]
    )
    with open("environment.yml") as f:
        spec = calkit.ryaml.load(f)
    pip_dict = next(
        d for d in spec["dependencies"] if isinstance(d, dict) and "pip" in d
    )
    assert "rich" in pip_dict["pip"]
    subprocess.check_call(
        [
            "calkit",
            "update",
            "conda-env",
            "-n",
            "myenv",
            "--rm-pip",
            "rich",
            "--no-check",
        ]
    )
    with open("environment.yml") as f:
        spec = calkit.ryaml.load(f)
    pip_dict = next(
        d for d in spec["dependencies"] if isinstance(d, dict) and "pip" in d
    )
    assert "rich" not in pip_dict["pip"]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Julia env init fails on Windows GHA runners (Pkg stdlib missing)",
)
def test_update_environment(tmp_dir):
    # Test we can update an environment
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        ["calkit", "new", "julia-env", "-n", "main", "--julia", "1.11"]
    )
    # Note we add Example, the registry's trivial test package, since nothing
    # here depends on which package is added, and heavier ones cost tens of
    # seconds each to download and precompile
    subprocess.check_call(
        [
            "calkit",
            "update",
            "env",
            "-n",
            "main",
            "--add",
            "Example",
        ]
    )
    with open("Project.toml") as f:
        assert "Example" in f.read()


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "calkit.cli.update.os.path.expanduser",
        lambda p: str(tmp_path) if p == "~" else p,
    )
    return tmp_path


def test_update_agent_skills_copies_bundled_skills(fake_home):
    skills_dir = fake_home / ".agents" / "skills"
    result = runner.invoke(update_app, ["agent-skills"])
    assert result.exit_code == 0
    assert (skills_dir / "calkit-add-pipeline-stage" / "SKILL.md").exists()
    assert (skills_dir / "calkit-conventions" / "SKILL.md").exists()
    assert (skills_dir / "calkit-create-pipeline" / "SKILL.md").exists()


def test_update_agent_skills_renames_skill_name_in_frontmatter(fake_home):
    skills_dir = fake_home / ".agents" / "skills"
    result = runner.invoke(update_app, ["agent-skills"])
    assert result.exit_code == 0
    # Each installed SKILL.md should have its name updated to the calkit- prefixed folder name.
    for skill_name in (
        "calkit-conventions",
        "calkit-create-pipeline",
        "calkit-add-pipeline-stage",
    ):
        content = (skills_dir / skill_name / "SKILL.md").read_text()
        assert f"name: {skill_name}" in content


def test_update_agent_skills_preserves_custom_skill(fake_home):
    skills_dir = fake_home / ".agents" / "skills"
    custom_skill = skills_dir / "my-skill" / "SKILL.md"
    custom_skill.parent.mkdir(parents=True)
    custom_skill.write_text("# Custom\n")
    result = runner.invoke(update_app, ["agent-skills"])
    assert result.exit_code == 0
    assert custom_skill.exists()


def test_update_agent_skills_does_not_touch_home_agents_md(fake_home):
    agents_md = fake_home / "AGENTS.md"
    agents_md.write_text("# Existing\n")
    result = runner.invoke(update_app, ["agent-skills"])
    assert result.exit_code == 0
    assert agents_md.read_text() == "# Existing\n"


def test_update_agent_skills_supports_quiet_flag(fake_home):
    result = runner.invoke(update_app, ["agent-skills", "--quiet"])
    assert result.exit_code == 0


def test_update_agent_skills_can_be_run_twice(fake_home):
    skills_dir = fake_home / ".agents" / "skills"
    result1 = runner.invoke(update_app, ["agent-skills"])
    result2 = runner.invoke(update_app, ["agent-skills"])
    assert result1.exit_code == 0
    assert result2.exit_code == 0
    # Existing custom files should be preserved by copytree dirs_exist_ok.
    assert (skills_dir / "calkit-conventions" / "SKILL.md").exists()
