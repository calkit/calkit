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


def test_post_project_stage_from_script_or_notebook(
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
                "/projects/o/p/pipeline/stages/from-script-or-notebook",
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
    assert data["included_in"] == ["paper/paper.tex"]
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
    # A stage that already runs the script keeps what it declares, including
    # inputs that are objects carrying paths, or aren't paths at all
    stage["outputs"].append("figures/extra.png")
    stage["inputs"] = [
        {"path": "data/raw.csv"},
        {"path": "data/extra.csv"},
        {"kind": "env-var", "name": "SEED"},
    ]
    (wdir / "calkit.yaml").write_text(yaml.safe_dump(ck))
    repo.git.add("calkit.yaml")
    repo.git.commit("-m", "Declare another output and inputs")
    resp = post(script_path="scripts/plot.py", shows="figures/fit.png")
    assert resp.status_code == 200, resp.text
    assert resp.json()["inputs"] == ["data/raw.csv", "data/extra.csv"]
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage_name"] == "plot"
    assert {"figures/fit.png", "figures/extra.png"} <= set(
        resp.json()["outputs"]
    )
    # An output with the same name elsewhere isn't guessed when nothing
    # includes what's shown, since nothing could show it from there
    resp = post(script_path="scripts/plot.py", shows="results/fit.png")
    assert resp.status_code == 200, resp.text
    assert resp.json()["produces"] == "results/fit.png"
    assert resp.json()["included_in"] == []
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
    assert resp.json()["included_in"] == []
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
    # Nothing is written through a symlink that leads out of the project
    outside = tmp_path / "outside"
    outside.mkdir()
    (wdir / "linked").symlink_to(outside)
    resp = post(**{**upload, "script_path": "linked/plot.py"})
    assert resp.status_code == 422, resp.text
    assert not (outside / "plot.py").exists()
    (wdir / "linked").unlink()
    # Not a script, or not there to read
    assert post(script_path="paper/paper.tex").status_code == 422
    assert post(script_path="scripts/gone.py").status_code == 404
    assert post(script_path="../x.py").status_code == 422


def test_post_project_pipeline_stage(
    client: TestClient, normal_user_token_headers: dict[str, str], tmp_path
) -> None:
    import base64
    import hashlib

    import fsspec

    import calkit.export
    from calkit.models.pipeline import InkscapeExportStage

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

    def post(url: str = "/projects/o/p/pipeline/stages", **body):
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
            patch("app.api.routes.projects.pipeline.FILE_GIT_MAX_BYTES", 10),
        ):
            return client.post(
                url, json=body, headers=normal_user_token_headers
            )

    def ck_info() -> dict:
        return yaml.safe_load((tmp_path / "repo" / "calkit.yaml").read_text())

    def export(output: str, source: str, **kw) -> dict:
        return {
            "kind": "manual-step",
            "message": f"Export {output} from {source}",
            "inputs": [source],
            "outputs": [output],
            **kw,
        }

    # A manual export with its uploaded Photoshop file, which becomes the
    # person's, and a figure kept in Git where it already was
    psd = {
        "path": "figures/src/drawn.psd",
        "content": base64.b64encode(b"psd").decode(),
        "created_by_me": True,
    }
    stage = export(
        "paper/figures/drawn.png",
        "figures/src/drawn.psd",
        open={"app": "Photoshop", "path": "figures/src/drawn.psd"},
    )
    resp = post(name="export-drawn", stage=stage, files=[psd])
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "export-drawn"
    info = ck_info()
    assert info["pipeline"]["stages"]["export-drawn"] == {
        **stage,
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
    # Exporting a figure is up to the library: an app that can does it as
    # the pipeline runs, unless the person exports it with another
    export_url = "/projects/o/p/pipeline/stages/export"
    svg = {
        "source": "figures/src/setup.svg",
        "output": "paper/figures/setup.png",
    }
    resp = post(export_url, **svg, app="Illustrator", save=False)
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage"] == calkit.export.export_stage(
        **svg, app="Illustrator"
    )
    assert resp.json()["exported_by"] is None
    assert not resp.json()["saved"]
    resp = post(
        export_url,
        **svg,
        files=[
            {
                "path": "figures/src/setup.svg",
                "content": base64.b64encode(b"<svg/>").decode(),
                "created_by_me": True,
            }
        ],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "export-setup"
    assert resp.json()["exported_by"] == "Inkscape"
    assert resp.json()["saved"]
    assert ck_info()["pipeline"]["stages"]["export-setup"]["kind"] == (
        "inkscape-export"
    )
    assert repo.head.commit.message.strip() == (
        "Export paper/figures/setup.png from figures/src/setup.svg with "
        "Inkscape"
    )
    dvc_yaml = yaml.safe_load((tmp_path / "repo" / "dvc.yaml").read_text())
    assert dvc_yaml["stages"]["export-setup"]["cmd"] == (
        InkscapeExportStage(
            source_path="figures/src/setup.svg",
            outputs=["paper/figures/setup.png"],
        ).dvc_cmd
    )
    # Something made once isn't made twice
    resp = post(stage=stage)
    assert resp.status_code == 409, resp.text
    assert "export-drawn" in resp.json()["detail"]
    # What a person makes can't be an exported format, a file not uploaded
    # has to be there, and a stage has to be valid
    for files, stage, status in [
        (
            [{"path": "figures/src/drawn.png", "created_by_me": True}],
            export("paper/figures/big.png", "figures/src/drawn.png"),
            422,
        ),
        (
            [{"path": "figures/src/missing.psd", "created_by_me": True}],
            export("paper/figures/big.png", "figures/src/missing.psd"),
            404,
        ),
        (
            [],
            export("paper/figures/big.png", "x.svg", open={"path": "x.svg"}),
            422,
        ),
    ]:
        resp = post(stage=stage, files=files)
        assert resp.status_code == status, resp.text
    # An upload never replaces a different file
    resp = post(
        stage=export("paper/figures/big.png", "figures/src/old.psd"),
        files=[
            {
                "path": "figures/src/old.psd",
                "content": base64.b64encode(b"new").decode(),
            }
        ],
    )
    assert resp.status_code == 409, resp.text
    assert (tmp_path / "repo" / "figures/src/old.psd").read_text() == "old"
    # A big upload goes to DVC, with its object where the remote serves it,
    # and a stage without a name is named after its output, with a number
    # if that's taken
    big = b"psd" * 10
    resp = post(
        stage=export("paper/figures/big.png", "figures/src/big.psd"),
        files=[
            {
                "path": "figures/src/big.psd",
                "content": base64.b64encode(big).decode(),
            }
        ],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "big"
    assert not repo.git.ls_files("figures/src/big.psd")
    assert repo.git.ls_files("figures/src/big.psd.dvc")
    md5 = hashlib.md5(big).hexdigest()
    [key] = [k for k in store.store if k.endswith(f"{md5[:2]}/{md5[2:]}")]
    assert store.cat(key) == big
    resp = post(
        name="big", stage=export("results/big.png", "figures/src/old.psd")
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "big-2"


def test_project_pipeline_runs(
    client: TestClient, normal_user_token_headers: dict[str, str], tmp_path
) -> None:
    from git import GitCommandError

    import calkit.resources

    repo, origin = _make_repo(tmp_path, {"name": "p"})
    branch = repo.active_branch.name
    fake_project = SimpleNamespace(
        owner_account_name="o",
        name="p",
        owner_github_name="o",
        git_repo_url="https://github.com/o/p",
        github_repo="o/p",
    )
    module = "app.api.routes.projects.pipeline"
    github = SimpleNamespace(get=[], post=[])

    def respond(status: int, body: dict | None = None):
        return SimpleNamespace(
            ok=status < 400,
            status_code=status,
            reason="Nope",
            text="",
            content=b"x" if body is not None else b"",
            json=lambda: body,
        )

    def call(method: str, project=fake_project, get=None, post=None, **kw):
        with (
            patch(f"{module}.app.projects.get_project", return_value=project),
            patch(f"{module}.get_repo", return_value=repo),
            patch(f"{module}._github_token_for_repo", return_value="t"),
            patch(
                f"{module}.requests.get",
                side_effect=lambda url, **k: (
                    github.get.append((url, k)) or get or respond(200, {})
                ),
            ),
            patch(
                f"{module}.requests.post",
                side_effect=lambda url, **k: (
                    github.post.append((url, k)) or post or respond(204)
                ),
            ),
        ):
            for name, value in kw.items():
                patch(f"{module}.{name}", value).start()
            try:
                return getattr(client, method)(
                    "/projects/o/p/pipeline/runs",
                    headers=normal_user_token_headers,
                )
            finally:
                patch.stopall()

    # Without a workflow, one can still be started, which adds it
    resp = call("get")
    assert resp.status_code == 200, resp.text
    assert resp.json()["can_start"]
    assert resp.json()["github_workflow"] is None
    assert resp.json()["runs"] == []
    assert github.get == []
    # Starting adds one that only runs when started, pushes it, and then
    # starts it on the default branch
    resp = call("post")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"
    assert resp.json()["branch"] == branch
    found = calkit.resources.find_run_workflow(str(repo.working_dir))
    assert found is not None
    fname, txt = found
    assert txt == calkit.resources.render_github_actions_workflow(
        on_demand=True
    )
    assert origin.head.commit == repo.head.commit
    url, kw = github.post[-1]
    assert url.endswith(f"/repos/o/p/actions/workflows/{fname}/dispatches")
    assert kw["json"] == {"ref": branch}
    # A second start uses the workflow it has
    head = repo.head.commit
    assert call("post").status_code == 200
    assert repo.head.commit == head
    # Runs as GitHub lists them
    runs = [
        {"id": 1, "status": "queued", "conclusion": None},
        {"id": 2, "status": "in_progress", "conclusion": None},
        {"id": 3, "status": "completed", "conclusion": "success"},
        {"id": 4, "status": "completed", "conclusion": "failure"},
        {"id": 5, "status": "completed", "conclusion": "cancelled"},
        {
            "id": 6,
            "status": "completed",
            "conclusion": "timed_out",
            "run_started_at": "2026-10-31T12:00:00Z",
            "html_url": "https://github.com/o/p/actions/runs/6",
            "head_sha": "abc",
            "head_branch": "main",
            "triggering_actor": {"login": "ada"},
        },
    ]
    resp = call("get", get=respond(200, {"workflow_runs": runs}))
    body = resp.json()
    assert body["github_workflow"] == fname
    assert body["can_start"]
    assert [r["status"] for r in body["runs"]] == [
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "failed",
    ]
    assert body["runs"][-1] == {
        "where": "github-actions",
        "id": "6",
        "status": "failed",
        "started_at": "2026-10-31T12:00:00Z",
        "url": "https://github.com/o/p/actions/runs/6",
        "commit": "abc",
        "branch": "main",
        "started_by": "ada",
    }
    # GitHub being unavailable leaves no runs rather than failing
    resp = call("get", get=respond(500, {}))
    assert resp.status_code == 200
    assert resp.json()["runs"] == []
    # GitHub refusing to start it says why
    resp = call("post", post=respond(403, {"message": "No access"}))
    assert resp.status_code == 403
    assert "No access" in resp.json()["detail"]
    # A workflow that can't be started from here says so
    path = tmp_path / "repo" / ".github" / "workflows" / fname
    path.write_text(txt.replace("workflow_dispatch:", "push:"))
    resp = call("get")
    assert not resp.json()["can_start"]
    assert "workflow_dispatch" in resp.json()["cannot_start_reason"]
    assert call("post").status_code == 409
    # Without permission to push a workflow, nothing is left committed
    path.unlink()
    repo.git.add(all=True)
    repo.git.commit("-m", "Remove workflow")
    head = repo.head.commit

    def refuse(project, repo):
        raise GitCommandError(
            "git push",
            1,
            stderr="refusing to allow a GitHub App to create "
            "or update workflow without `workflows` permission",
        )

    resp = call("post", push_and_expire=refuse)
    assert resp.status_code == 403
    assert "permission" in resp.json()["detail"]
    assert repo.head.commit == head
    assert calkit.resources.find_run_workflow(str(repo.working_dir)) is None
    # A project that isn't on GitHub can't
    elsewhere = SimpleNamespace(**vars(fake_project) | {"github_repo": None})
    resp = call("get", project=elsewhere)
    assert not resp.json()["can_start"]
    assert resp.json()["cannot_start_reason"]
    assert call("post", project=elsewhere).status_code == 422

    # A run's jobs and steps, with a finished job's log less GitHub's
    # timestamps and folding markers
    def github_get(url, **kw):
        if url.endswith("/actions/runs/6/jobs"):
            return respond(
                200,
                {
                    "jobs": [
                        {
                            "id": 9,
                            "name": "Run",
                            "status": "completed",
                            "conclusion": "failure",
                            "steps": [
                                {
                                    "name": "Run Calkit",
                                    "status": "completed",
                                    "conclusion": "failure",
                                }
                            ],
                        },
                        {"id": 10, "name": "Later", "status": "in_progress"},
                    ]
                },
            )
        assert url.endswith("/actions/jobs/9/logs"), url
        return SimpleNamespace(
            ok=True,
            text=(
                "2026-11-01T02:12:43.3679898Z ##[group]Run calkit\n"
                "2026-11-01T02:12:46.5Z Error: Pipeline failed\n"
            ),
        )

    with (
        patch(f"{module}.app.projects.get_project", return_value=fake_project),
        patch(f"{module}._github_token_for_repo", return_value="t"),
        patch(f"{module}.requests.get", side_effect=github_get),
    ):
        resp = client.get(
            "/projects/o/p/pipeline/runs/6/logs",
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        jobs = resp.json()["jobs"]
        assert jobs[0]["log"] == "Run calkit\nError: Pipeline failed\n"
        assert jobs[0]["steps"] == [
            {
                "name": "Run Calkit",
                "status": "completed",
                "conclusion": "failure",
            }
        ]
        assert jobs[1]["log"] is None
        # Only a run's number names a run
        resp = client.get(
            "/projects/o/p/pipeline/runs/abc/logs",
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 422
