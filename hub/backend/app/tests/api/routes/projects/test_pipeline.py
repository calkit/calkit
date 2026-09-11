from types import SimpleNamespace
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

from app.tests.api.routes.projects.test_figures import _make_repo

URL = "/projects/o/p/pipeline/map-paths"


def _call(
    client: TestClient,
    headers: dict[str, str],
    repo,
    body: dict | None = None,
    params: dict | None = None,
):
    fake_project = SimpleNamespace(owner_account_name="o", name="p")
    with (
        patch(
            "app.api.routes.projects.pipeline.app.projects.get_project",
            return_value=fake_project,
        ),
        patch("app.api.routes.projects.pipeline.get_repo", return_value=repo),
        patch(
            "app.api.routes.projects.pipeline.app.projects"
            ".dvc_outputs_from_tree",
            return_value={"data/big.h5": {"md5": "abc"}},
        ),
    ):
        if body is not None:
            return client.post(URL, json=body, headers=headers)
        return client.delete(URL, params=params, headers=headers)


def _post(client: TestClient, headers: dict[str, str], repo, body: dict):
    return _call(client, headers, repo, body=body)


def test_post_project_map_paths(
    client: TestClient, normal_user_token_headers: dict[str, str], tmp_path
) -> None:
    repo, origin = _make_repo(
        tmp_path,
        {
            "environments": {
                "tex": {"kind": "docker", "image": "texlive/texlive"}
            },
            "pipeline": {
                "stages": {
                    "build-paper": {
                        "kind": "latex",
                        "target_path": "paper/paper.tex",
                        "environment": "tex",
                    }
                }
            },
        },
        files={
            "paper/paper.tex": "\\documentclass{article}\n",
            "figures/plot.png": "png",
            "figures/other.png": "png",
            "scripts/plot.py": "print(1)\n",
        },
    )
    # A file and a directory, kinds worked out from what they are; the
    # stage is named for the paper's directory and the publication's stage
    # now reads the copies
    resp = _post(
        client,
        normal_user_token_headers,
        repo,
        dict(
            paths=[
                {"src": "figures/plot.png", "dest": "paper/figures/plot.png"},
                {"src": "scripts", "dest": "paper/scripts"},
            ],
            target_stage="build-paper",
        ),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name"] == "map-paths-paper"
    ck = yaml.safe_load((tmp_path / "repo" / "calkit.yaml").read_text())
    stage = ck["pipeline"]["stages"]["map-paths-paper"]
    assert stage["kind"] == "map-paths"
    assert stage["paths"] == [
        {
            "kind": "file-to-file",
            "src": "figures/plot.png",
            "dest": "paper/figures/plot.png",
        },
        {
            "kind": "dir-to-dir-merge",
            "src": "scripts",
            "dest": "paper/scripts",
        },
    ]
    assert ck["pipeline"]["stages"]["build-paper"]["inputs"] == [
        {"from_stage_outputs": "map-paths-paper"}
    ]
    dvc = yaml.safe_load((tmp_path / "repo" / "dvc.yaml").read_text())
    assert "map-paths-paper" in dvc["stages"]
    assert "paper/figures/plot.png" in dvc["stages"]["build-paper"]["deps"]
    assert origin.head.commit.hexsha == repo.head.commit.hexsha
    # Adding to the same stage extends it; a repeat is not duplicated, the
    # target's link isn't either, and a DVC-tracked file counts as present
    resp = _post(
        client,
        normal_user_token_headers,
        repo,
        dict(
            paths=[
                {"src": "figures/plot.png", "dest": "paper/figures/plot.png"},
                {"src": "figures/other.png", "dest": "paper/figures/"},
                {"src": "data/big.h5", "dest": "paper/data/big.h5"},
            ],
            target_stage="build-paper",
        ),
    )
    assert resp.status_code == 200, resp.text
    ck = yaml.safe_load((tmp_path / "repo" / "calkit.yaml").read_text())
    paths = ck["pipeline"]["stages"]["map-paths-paper"]["paths"]
    assert [p["src"] for p in paths] == [
        "figures/plot.png",
        "scripts",
        "figures/other.png",
        "data/big.h5",
    ]
    assert paths[2] == {
        "kind": "file-to-dir",
        "src": "figures/other.png",
        "dest": "paper/figures",
    }
    assert len(ck["pipeline"]["stages"]["build-paper"]["inputs"]) == 1
    # What isn't in the project, a copy onto itself, a kind that doesn't
    # match, a missing target, and a stage of another kind are refused
    for body, status in [
        (dict(paths=[{"src": "nope.png", "dest": "paper/nope.png"}]), 404),
        (dict(paths=[{"src": "scripts", "dest": "scripts"}]), 422),
        (
            dict(
                paths=[
                    {
                        "src": "scripts",
                        "dest": "paper/s",
                        "kind": "file-to-file",
                    }
                ]
            ),
            422,
        ),
        (
            dict(
                paths=[{"src": "scripts", "dest": "paper/s"}],
                target_stage="missing",
            ),
            404,
        ),
        (
            dict(
                paths=[{"src": "scripts", "dest": "paper/s"}],
                stage_name="build-paper",
            ),
            409,
        ),
    ]:
        resp = _post(client, normal_user_token_headers, repo, body)
        assert resp.status_code == status, (body, resp.text)


def test_map_paths_on_dvc_only_pipeline_and_removal(
    client: TestClient, normal_user_token_headers: dict[str, str], tmp_path
) -> None:
    # An older project defines its pipeline in dvc.yaml alone; the copies
    # become deps of the stage there, since nothing compiles it
    dvc_yaml = {
        "stages": {
            "build-paper": {
                "cmd": "latexmk paper/paper.tex",
                "deps": ["paper/paper.tex"],
                "outs": ["paper/paper.pdf"],
            }
        }
    }
    repo, origin = _make_repo(
        tmp_path,
        {
            "publications": [
                {"path": "paper/paper.pdf", "stage": "build-paper"}
            ]
        },
        files={
            "dvc.yaml": yaml.safe_dump(dvc_yaml),
            "paper/paper.tex": "\\documentclass{article}\n",
            "figures/plot.png": "png",
            "figures/other.png": "png",
        },
    )
    for name in ["plot", "other"]:
        resp = _post(
            client,
            normal_user_token_headers,
            repo,
            dict(
                paths=[
                    {
                        "src": f"figures/{name}.png",
                        "dest": f"paper/figures/{name}.png",
                    }
                ],
                target_stage="build-paper",
            ),
        )
        assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "map-paths-paper"
    dvc = yaml.safe_load((tmp_path / "repo" / "dvc.yaml").read_text())
    assert dvc["stages"]["build-paper"]["deps"] == [
        "paper/paper.tex",
        "paper/figures/plot.png",
        "paper/figures/other.png",
    ]
    assert "map-paths-paper" in dvc["stages"]
    ck = yaml.safe_load((tmp_path / "repo" / "calkit.yaml").read_text())
    assert "build-paper" not in ck["pipeline"]["stages"]
    # Removing one copy drops it from the stage and the target's deps
    resp = _call(
        client,
        normal_user_token_headers,
        repo,
        params=dict(
            stage_name="map-paths-paper",
            src="figures/plot.png",
            dest="paper/figures/plot.png",
            target_stage="build-paper",
        ),
    )
    assert resp.status_code == 200, resp.text
    assert "other.png" in resp.json()["yaml"]
    dvc = yaml.safe_load((tmp_path / "repo" / "dvc.yaml").read_text())
    assert dvc["stages"]["build-paper"]["deps"] == [
        "paper/paper.tex",
        "paper/figures/other.png",
    ]
    # Removing the last one removes the stage and its link everywhere;
    # removing what isn't there is a 404
    resp = _call(
        client,
        normal_user_token_headers,
        repo,
        params=dict(
            stage_name="map-paths-paper",
            src="figures/other.png",
            dest="paper/figures/other.png",
            target_stage="build-paper",
        ),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["yaml"] == ""
    ck = yaml.safe_load((tmp_path / "repo" / "calkit.yaml").read_text())
    assert "map-paths-paper" not in ck["pipeline"]["stages"]
    dvc = yaml.safe_load((tmp_path / "repo" / "dvc.yaml").read_text())
    assert "map-paths-paper" not in dvc["stages"]
    assert dvc["stages"]["build-paper"]["deps"] == ["paper/paper.tex"]
    assert origin.head.commit.hexsha == repo.head.commit.hexsha
    resp = _call(
        client,
        normal_user_token_headers,
        repo,
        params=dict(stage_name="map-paths-paper", src="x", dest="y"),
    )
    assert resp.status_code == 404
