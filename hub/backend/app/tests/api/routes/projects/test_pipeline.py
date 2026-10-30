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
    fake_project = SimpleNamespace(
        owner_account_name="o",
        name="p",
        owner_github_name="o",
        git_repo_url="https://github.com/o/p",
    )
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


def test_post_project_stage_from_script(
    client: TestClient, normal_user_token_headers: dict[str, str], tmp_path
) -> None:
    import base64

    paper = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\includegraphics[width=\\linewidth]{figures/fit}\n"
        "\\end{document}\n"
    )
    repo, origin = _make_repo(
        tmp_path,
        {
            "name": "p",
            "overleaf_sync": {
                "paper": {"url": "https://www.overleaf.com/project/abc"}
            },
        },
        files={
            "paper/paper.tex": paper,
            "paper/figures/fit.png": "png",
            "paper/figures/drawn.png": "png",
            "scripts/old.py": "print(1)\n",
        },
    )
    script = (
        "import matplotlib.pyplot as plt\n"
        "import pandas as pd\n"
        "df = pd.read_csv('data/raw.csv')\n"
        "fig, ax = plt.subplots()\n"
        "fig.savefig('figures/fit.png')\n"
    )
    fake_project = SimpleNamespace(
        owner_account_name="o",
        name="p",
        owner_github_name="o",
        git_repo_url="https://github.com/o/p",
    )

    def post(**body):
        with (
            patch(
                "app.api.routes.projects.pipeline.app.projects.get_project",
                return_value=fake_project,
            ),
            patch(
                "app.api.routes.projects.pipeline.get_repo", return_value=repo
            ),
            patch(
                "app.api.routes.projects.pipeline.app.projects"
                ".dvc_outputs_from_tree",
                return_value={},
            ),
        ):
            return client.post(
                "/projects/o/p/pipeline/stages/from-script",
                json=body,
                headers=normal_user_token_headers,
            )

    upload = dict(
        script_path="scripts/plot.py",
        content=base64.b64encode(script.encode()).decode(),
        shows="paper/figures/fit.png",
    )
    # Read, not saved: what it imports, opens, and writes, and that the
    # paper will show its figure from there, with nothing left in the clone
    resp = post(**upload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert not data["saved"]
    assert data["stage_name"] == "plot"
    assert data["environment_is_new"]
    assert set(data["dependencies"]) == {"matplotlib", "pandas"}
    assert data["inputs"] == ["data/raw.csv"]
    assert data["outputs"] == ["figures/fit.png"]
    # Nothing has the data the script reads
    assert data["missing_inputs"] == ["data/raw.csv"]
    assert data["produces"] == "figures/fit.png"
    assert data["cited_in"] == ["paper/paper.tex"]
    assert data["git_repo_url"] == "https://github.com/o/p"
    wdir = tmp_path / "repo"
    assert not (wdir / "scripts" / "plot.py").exists()
    assert not repo.is_dirty(untracked_files=True)
    assert repo.git.worktree("list").count("\n") == 0
    # Saved: the script, its environment, the stage, and the paper citing
    # the figure where it's made, pushed
    resp = post(**upload, save=True)
    assert resp.status_code == 200, resp.text
    assert resp.json()["saved"]
    ck = yaml.safe_load((wdir / "calkit.yaml").read_text())
    stage = ck["pipeline"]["stages"]["plot"]
    assert stage["script_path"] == "scripts/plot.py"
    assert stage["environment"] in ck["environments"]
    assert set(ck["pipeline"]["stages"]) == {"plot"}
    assert (wdir / "paper" / "paper.tex").read_text() == (
        "\\documentclass{article}\n"
        "\\usepackage{calkit}\n"
        "\\begin{document}\n"
        "\\ckfigure[width=\\linewidth]{figures/fit.png}\n"
        "\\end{document}\n"
    )
    assert (wdir / "scripts" / "plot.py").read_text() == script
    assert (wdir / data["environment_spec_path"]).is_file()
    assert "plot" in yaml.safe_load((wdir / "dvc.yaml").read_text())["stages"]
    assert not repo.is_dirty(untracked_files=True)
    assert origin.head.commit.hexsha == repo.head.commit.hexsha
    # A stage that already runs the script keeps what it declares
    ck["pipeline"]["stages"]["plot"]["outputs"].append("figures/extra.png")
    (wdir / "calkit.yaml").write_text(yaml.safe_dump(ck))
    repo.git.add("calkit.yaml")
    repo.git.commit("-m", "Declare another output")
    resp = post(script_path="scripts/plot.py", shows="figures/fit.png")
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage_name"] == "plot"
    assert {"figures/fit.png", "figures/extra.png"} <= set(
        resp.json()["outputs"]
    )
    # An upload never replaces a different file already there
    resp = post(**{**upload, "script_path": "scripts/old.py"})
    assert resp.status_code == 409, resp.text
    assert (wdir / "scripts" / "old.py").read_text() == "print(1)\n"
    # A script already in the project is read where it is, and when it
    # isn't found writing what the paper shows, its stage writes it there
    resp = post(script_path="scripts/old.py", shows="paper/figures/drawn.png")
    assert resp.status_code == 200, resp.text
    assert resp.json()["produces"] == "paper/figures/drawn.png"
    assert "paper/figures/drawn.png" in resp.json()["outputs"]
    assert resp.json()["cited_in"] == []
    resp = post(
        script_path="scripts/old.py",
        shows="paper/figures/drawn.png",
        save=True,
    )
    assert resp.status_code == 200, resp.text
    ck = yaml.safe_load((wdir / "calkit.yaml").read_text())
    assert {"path": "paper/figures/drawn.png", "storage": "git"} in ck[
        "pipeline"
    ]["stages"][resp.json()["stage_name"]]["outputs"]
    resp = post(script_path="scripts/old.py", produces="figures/x.png")
    assert resp.status_code == 422
    # Shown from elsewhere only when a document includes it
    resp = post(
        script_path="scripts/plot.py",
        shows="paper/figures/drawn.png",
        produces="figures/fit.png",
    )
    assert resp.status_code == 422, resp.text
    # Not a script, or not there to read
    assert post(script_path="paper/paper.tex").status_code == 422
    assert post(script_path="scripts/gone.py").status_code == 404
    assert post(script_path="../x.py").status_code == 422


def test_post_project_manual_export(
    client: TestClient, normal_user_token_headers: dict[str, str], tmp_path
) -> None:
    import base64
    import hashlib

    import fsspec

    repo, origin = _make_repo(
        tmp_path,
        {"name": "p"},
        files={
            "paper/figures/drawn.png": "png",
            "paper/figures/big.png": "png",
            "figures/src/old.psd": "old",
        },
    )
    fake_project = SimpleNamespace(
        owner_account_name="o",
        name="p",
        owner_github_name="o",
        git_repo_url="https://github.com/o/p",
    )
    store = fsspec.filesystem("memory")

    def post(**body):
        with (
            patch(
                "app.api.routes.projects.pipeline.app.projects.get_project",
                return_value=fake_project,
            ),
            patch(
                "app.api.routes.projects.pipeline.get_repo", return_value=repo
            ),
            patch(
                "app.api.routes.projects.pipeline.get_object_fs",
                return_value=store,
            ),
            patch("app.api.routes.projects.pipeline.SOURCE_GIT_MAX_BYTES", 10),
        ):
            return client.post(
                "/projects/o/p/pipeline/stages/manual-export",
                json=body,
                headers=normal_user_token_headers,
            )

    def ck_info() -> dict:
        return yaml.safe_load((tmp_path / "repo" / "calkit.yaml").read_text())

    # An uploaded Photoshop file becomes the person's, and a manual stage
    # exports the figure from it, kept in Git where it already was
    resp = post(
        path="paper/figures/drawn.png",
        source_path="figures/src/drawn.psd",
        content=base64.b64encode(b"psd").decode(),
        app="Photoshop",
    )
    assert resp.status_code == 200, resp.text
    message = (
        "In Photoshop, export paper/figures/drawn.png from "
        "figures/src/drawn.psd"
    )
    assert resp.json()["stage_name"] == "export-drawn"
    assert resp.json()["message"] == message
    info = ck_info()
    assert info["pipeline"]["stages"]["export-drawn"] == {
        "kind": "manual-step",
        "message": message,
        "source_path": "figures/src/drawn.psd",
        "outputs": [{"path": "paper/figures/drawn.png", "storage": "git"}],
    }
    [entry] = info["misc"]
    assert entry["path"] == "figures/src/drawn.psd"
    assert entry["created_by"][0]["email"]
    assert repo.git.ls_files("figures/src/drawn.psd")
    dvc_yaml = yaml.safe_load((tmp_path / "repo" / "dvc.yaml").read_text())
    assert dvc_yaml["stages"]["export-drawn"]["cmd"].startswith(
        "calkit manual-step"
    )
    assert origin.head.commit.hexsha == repo.head.commit.hexsha
    # Something made once isn't made twice
    resp = post(
        path="paper/figures/drawn.png",
        source_path="figures/src/drawn.psd",
    )
    assert resp.status_code == 409, resp.text
    assert "export-drawn" in resp.json()["detail"]
    # A source has to be something a person makes, and has to be there
    for source, status in [
        ("figures/src/drawn.png", 422),
        ("figures/src/missing.psd", 404),
    ]:
        resp = post(path="paper/figures/big.png", source_path=source)
        assert resp.status_code == status, resp.text
    # An upload never replaces a different file
    resp = post(
        path="paper/figures/big.png",
        source_path="figures/src/old.psd",
        content=base64.b64encode(b"new").decode(),
    )
    assert resp.status_code == 409, resp.text
    assert (tmp_path / "repo" / "figures/src/old.psd").read_text() == "old"
    # A big source goes to DVC, with its object where the remote serves it
    big = b"psd" * 10
    resp = post(
        path="paper/figures/big.png",
        source_path="figures/src/big.psd",
        content=base64.b64encode(big).decode(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == (
        "Export paper/figures/big.png from figures/src/big.psd"
    )
    assert not repo.git.ls_files("figures/src/big.psd")
    assert repo.git.ls_files("figures/src/big.psd.dvc")
    md5 = hashlib.md5(big).hexdigest()
    [key] = [k for k in store.store if k.endswith(f"{md5[:2]}/{md5[2:]}")]
    assert store.cat(key) == big
