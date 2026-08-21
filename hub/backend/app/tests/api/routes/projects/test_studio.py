from types import SimpleNamespace
from unittest.mock import patch

import git
import yaml
from fastapi.testclient import TestClient

from app.config import settings

URL = f"{settings.API_V1_STR}/projects/o/p/figures/studio"

SCRIPT = (
    "import matplotlib.pyplot as plt\n"
    "import pandas as pd\n"
    'df = pd.read_csv("data/raw.csv")\n'
    "fig, ax = plt.subplots()\n"
    'ax.plot(df["x"], df["y"])\n'
    'fig.savefig("figures/y.png")\n'
)


def _make_repo(tmp_path, ck_info: dict, files: dict[str, str] | None = None):
    """A working clone with a bare origin, so a push has somewhere to go."""
    origin = git.Repo.init(tmp_path / "origin.git", bare=True)
    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    (tmp_path / "repo" / "calkit.yaml").write_text(yaml.safe_dump(ck_info))
    for path, content in (files or {}).items():
        full = tmp_path / "repo" / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    repo.git.add(all=True)
    repo.git.commit("-m", "Initial")
    repo.create_remote("origin", str(origin.working_dir))
    repo.git.push("origin", repo.active_branch.name)
    return repo, origin


def _post(
    client: TestClient, headers: dict[str, str], repo: git.Repo, body: dict
):
    fake_project = SimpleNamespace(owner_account_name="o", name="p")
    with (
        patch(
            "app.api.routes.projects.studio.app.projects.get_project",
            return_value=fake_project,
        ),
        patch("app.api.routes.projects.studio.get_repo", return_value=repo),
        patch(
            "app.api.routes.projects.studio.mixpanel.user_saved_studio_figure"
        ),
    ):
        return client.post(URL, json=body, headers=headers)


def test_post_project_studio_figure(
    client: TestClient, normal_user_token_headers: dict[str, str], tmp_path
) -> None:
    headers = normal_user_token_headers
    base = dict(
        figure_path="figures/y.png",
        title="y vs x",
        description="A line",
        script_path="scripts/plot-y.py",
        script_content=SCRIPT,
        inputs=["data/raw.csv"],
        packages=["matplotlib", "pandas"],
    )
    # No Python environment: one is created, uv by default, and everything
    # lands in a single commit that's pushed
    repo, origin = _make_repo(
        tmp_path / "a", {"datasets": [{"path": "data/raw.csv"}]}
    )
    resp = _post(client, headers, repo, base)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["stage_name"] == "plot-y"
    assert data["environment"] == "py"
    assert data["environment_created"] is True
    assert data["packages_missing"] == []
    assert data["figure"]["stage"] == "plot-y"
    ck = yaml.safe_load((tmp_path / "a" / "repo" / "calkit.yaml").read_text())
    assert ck["environments"]["py"] == {"kind": "uv", "path": "pyproject.toml"}
    stage = ck["pipeline"]["stages"]["plot-y"]
    assert stage["kind"] == "python-script"
    assert stage["script_path"] == "scripts/plot-y.py"
    assert stage["inputs"] == ["data/raw.csv"]
    assert stage["outputs"] == ["figures/y.png"]
    assert ck["figures"] == [
        {
            "path": "figures/y.png",
            "title": "y vs x",
            "description": "A line",
            "stage": "plot-y",
        }
    ]
    pyproject = (tmp_path / "a" / "repo" / "pyproject.toml").read_text()
    assert '"matplotlib",' in pyproject and '"pandas",' in pyproject
    assert (tmp_path / "a" / "repo" / "scripts" / "plot-y.py").read_text() == (
        SCRIPT
    )
    assert not repo.is_dirty(untracked_files=True)
    assert origin.head.commit.hexsha == repo.head.commit.hexsha
    assert "plot-y" in repo.head.commit.message
    # dvc.yaml is compiled in the same commit, since that's what the
    # pipeline view reads
    dvc = yaml.safe_load((tmp_path / "a" / "repo" / "dvc.yaml").read_text())
    assert "plot-y" in dvc["stages"]
    assert dvc["stages"]["plot-y"]["deps"] == ["data/raw.csv"] or (
        "data/raw.csv" in dvc["stages"]["plot-y"]["deps"]
    )
    assert "figures/y.png" in [
        o if isinstance(o, str) else o.get("path")
        for o in dvc["stages"]["plot-y"]["outs"]
    ]
    # An existing requirements-based env is reused and gains the missing
    # packages; the stage name is kept unique; an existing figure entry is
    # updated in place rather than duplicated
    repo, _ = _make_repo(
        tmp_path / "b",
        {
            "environments": {
                "main": {"kind": "uv-venv", "path": "requirements.txt"}
            },
            "pipeline": {
                "stages": {
                    "plot-y": {
                        "kind": "python-script",
                        "script_path": "scripts/other.py",
                        "environment": "main",
                        "outputs": ["figures/other.png"],
                    }
                }
            },
            "figures": [{"path": "figures/y.png", "title": "Old title"}],
        },
        files={"requirements.txt": "pandas\n", "scripts/other.py": "pass\n"},
    )
    resp = _post(client, headers, repo, base)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["stage_name"] == "plot-y-2"
    assert data["environment"] == "main"
    assert data["environment_created"] is False
    assert data["packages_missing"] == []
    assert (tmp_path / "b" / "repo" / "requirements.txt").read_text() == (
        "pandas\nmatplotlib\n"
    )
    ck = yaml.safe_load((tmp_path / "b" / "repo" / "calkit.yaml").read_text())
    assert len(ck["figures"]) == 1
    assert ck["figures"][0]["title"] == "y vs x"
    assert ck["figures"][0]["stage"] == "plot-y-2"
    assert ck["pipeline"]["stages"]["plot-y-2"]["environment"] == "main"
    # A conda env can't be amended safely, so the packages come back as
    # missing rather than being guessed into the file
    repo, _ = _make_repo(
        tmp_path / "c",
        {"environments": {"c": {"kind": "conda", "path": "environment.yml"}}},
        files={"environment.yml": "dependencies:\n  - python\n"},
    )
    resp = _post(client, headers, repo, base)
    assert resp.status_code == 200, resp.text
    assert resp.json()["packages_missing"] == ["matplotlib", "pandas"]
    # Rejections: a path that escapes, a non-image figure, a path another
    # stage already produces, an empty script
    repo, _ = _make_repo(
        tmp_path / "d",
        {
            "pipeline": {
                "stages": {
                    "taken": {
                        "kind": "python-script",
                        "script_path": "scripts/t.py",
                        "outputs": ["figures/taken.png"],
                    }
                }
            }
        },
        files={"scripts/t.py": "pass\n"},
    )
    before = repo.head.commit.hexsha
    for bad, status in [
        (dict(base, figure_path="../figures/y.png"), 422),
        (dict(base, script_path="/etc/plot.py"), 422),
        (dict(base, figure_path="figures/y.txt"), 422),
        (dict(base, figure_path="figures/taken.png"), 400),
        (dict(base, script_content="   "), 422),
        (dict(base, title=""), 422),
    ]:
        resp = _post(client, headers, repo, bad)
        assert resp.status_code == status, (bad, resp.text)
    # Nothing was committed by any of the rejected requests
    assert repo.head.commit.hexsha == before


EXAMPLE_BASIC_CK = """
owner: calkit
name: example-basic
title: Basic Calkit example
description: A basic Calkit example project.
git_repo_url: https://github.com/calkit/example-basic

dependencies:
  - docker
  - uv

questions:
  - question: How does the system respond to increasing $x$?
    hypothesis: The value of $y$ increases linearly with $x$.

environments:
  py:
    path: requirements.txt
    kind: uv-venv
    python: "3.13"
    prefix: .venv
    description: A Python virtual environment managed with uv
  tex:
    kind: docker
    image: texlive/texlive:latest-full
    description: TeX Live via Docker.

pipeline:
  stages:
    collect-data:
      kind: python-script
      script_path: scripts/collect-data.py
      environment: py
      outputs:
        - data/raw/data.csv
    analyze:
      kind: python-script
      script_path: scripts/analyze.py
      environment: py
      inputs:
        - from_stage_outputs: collect-data
      outputs:
        - figures/x-vs-y.png
        - path: results/summary.json
          storage: git
    build-paper:
      kind: latex
      target_path: paper/paper.tex
      environment: tex
      inputs:
        - paper/references.bib
      outputs:
        - paper/paper.pdf

datasets:
  - path: data/raw/data.csv
    title: Raw data
    description: This is raw $x$ and $y$ data.
    stage: collect-data

figures:
  - path: figures/x-vs-y.png
    title: x vs y
    description: A plot.
    stage: analyze

publications:
  - path: paper/paper.pdf
    kind: journal-article
    title: The paper
    description: A paper.
    stage: build-paper
"""


def test_post_project_studio_figure_on_template_project(
    client: TestClient, normal_user_token_headers: dict[str, str], tmp_path
) -> None:
    """The exact shape a project made from example-basic has."""
    import ruamel.yaml

    origin = git.Repo.init(tmp_path / "origin.git", bare=True)
    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    # Written with comments and blank lines, as the template keeps them, so
    # the round trip through ruamel is the real one
    (tmp_path / "repo" / "calkit.yaml").write_text(EXAMPLE_BASIC_CK)
    (tmp_path / "repo" / "requirements.txt").write_text(
        "pandas\nmatplotlib\nnumpy\n"
    )
    repo.git.add(all=True)
    repo.git.commit("-m", "Initial")
    repo.create_remote("origin", str(origin.working_dir))
    repo.git.push("origin", repo.active_branch.name)
    body = dict(
        figure_path="figures/data.png",
        title="y vs. x",
        description=None,
        script_path="scripts/plot-data.py",
        script_content=SCRIPT,
        inputs=["data/raw/data.csv"],
        packages=["matplotlib", "pandas"],
        environment=None,
    )
    resp = _post(client, normal_user_token_headers, repo, body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["environment"] == "py"
    assert data["environment_created"] is False
    assert data["packages_missing"] == []
    assert data["stage_name"] == "plot-data"
    # Nothing was added to a requirements file that already had it all
    assert (tmp_path / "repo" / "requirements.txt").read_text() == (
        "pandas\nmatplotlib\nnumpy\n"
    )
    yaml_rt = ruamel.yaml.YAML()
    ck = yaml_rt.load((tmp_path / "repo" / "calkit.yaml").read_text())
    assert ck["pipeline"]["stages"]["plot-data"]["environment"] == "py"
    assert ck["figures"][-1]["path"] == "figures/data.png"
    # The rest of the file survived the round trip
    assert ck["questions"][0]["hypothesis"].startswith("The value")
    assert ck["environments"]["tex"]["image"] == "texlive/texlive:latest-full"
    assert origin.head.commit.hexsha == repo.head.commit.hexsha


def test_post_project_studio_figure_edits_own_stage(
    client: TestClient, normal_user_token_headers: dict[str, str], tmp_path
) -> None:
    repo, origin = _make_repo(
        tmp_path,
        {
            "environments": {
                "py": {"kind": "uv-venv", "path": "requirements.txt"}
            },
            "pipeline": {
                "stages": {
                    "analyze": {
                        "kind": "python-script",
                        "script_path": "scripts/analyze.py",
                        "environment": "py",
                        "inputs": ["data/old.csv"],
                        "outputs": [
                            "figures/y.png",
                            {"path": "results/summary.json", "storage": "git"},
                        ],
                        "description": "Keep me",
                    }
                }
            },
            "figures": [
                {"path": "figures/y.png", "title": "Old", "stage": "analyze"}
            ],
        },
        files={
            "requirements.txt": "pandas\nmatplotlib\n",
            "scripts/analyze.py": "print('old')\n",
        },
    )
    body = dict(
        figure_path="figures/y.png",
        title="New title",
        script_path="scripts/analyze.py",
        script_content=SCRIPT,
        inputs=["data/raw.csv"],
        packages=["matplotlib", "pandas"],
        stage="analyze",
    )
    resp = _post(client, normal_user_token_headers, repo, body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["stage_name"] == "analyze"
    assert data["environment"] == "py"
    ck = yaml.safe_load((tmp_path / "repo" / "calkit.yaml").read_text())
    stage = ck["pipeline"]["stages"]["analyze"]
    # Script, inputs, and environment are the studio's; the rest survives
    assert stage["inputs"] == ["data/raw.csv"]
    assert stage["description"] == "Keep me"
    assert stage["outputs"] == [
        "figures/y.png",
        {"path": "results/summary.json", "storage": "git"},
    ]
    assert "plot-y" not in ck["pipeline"]["stages"]
    assert ck["figures"] == [
        {"path": "figures/y.png", "title": "New title", "stage": "analyze"}
    ]
    assert (tmp_path / "repo" / "scripts" / "analyze.py").read_text() == SCRIPT
    assert "Update stage analyze" in repo.head.commit.message
    assert origin.head.commit.hexsha == repo.head.commit.hexsha
    # Naming a stage that doesn't exist is refused
    resp = _post(
        client, normal_user_token_headers, repo, dict(body, stage="missing")
    )
    assert resp.status_code == 404, resp.text
