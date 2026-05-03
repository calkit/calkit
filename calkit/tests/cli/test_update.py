"""Tests for ``cli.update``."""

import subprocess

import pytest
from typer.testing import CliRunner

import calkit
from calkit.cli.update import update_app

runner = CliRunner()


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


def test_update_environment(tmp_dir):
    # Test we can update an environment
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        ["calkit", "new", "julia-env", "-n", "main", "--julia", "1.11"]
    )
    subprocess.check_call(
        [
            "calkit",
            "update",
            "env",
            "-n",
            "main",
            "--add",
            "IJulia",
        ]
    )


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
