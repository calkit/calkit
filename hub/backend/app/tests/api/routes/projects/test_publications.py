"""Tests for publication routes: the Overleaf import and its components."""

import io
import os
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import git
from fastapi.testclient import TestClient

from app.core import ryaml

URL = "/projects/o/p/publications"


def _make_repo(
    tmp_path: Path, files: dict[str, bytes], ck_info: dict[str, Any]
) -> tuple[git.Repo, git.Repo]:
    """A Git repo with a local bare origin, standing in for a project's clone."""
    root = tmp_path / uuid.uuid4().hex[:8]
    origin = git.Repo.init(root / "origin.git", bare=True)
    repo = git.Repo.init(root / "repo")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    for rel_path, data in files.items():
        fpath = root / "repo" / rel_path
        os.makedirs(fpath.parent, exist_ok=True)
        fpath.write_bytes(data)
    with open(root / "repo" / "calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add(all=True)
    repo.git.commit("-m", "Initial")
    repo.create_remote("origin", str(origin.working_dir))
    repo.git.push("origin", repo.active_branch.name)
    return repo, origin


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_post_project_overleaf_publication_replace_existing(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    # A project resembling the wizard's template: a placeholder paper fed
    # by a figures copy and a results-to-LaTeX stage
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 32
    ck_info: dict[str, Any] = {
        "name": "p",
        "environments": {
            "tex": {"kind": "docker", "image": "texlive/texlive:latest-full"}
        },
        "pipeline": {
            "stages": {
                "figs-to-paper": {
                    "kind": "map-paths",
                    "paths": [
                        {
                            "kind": "dir-to-dir-replace",
                            "src": "figures",
                            "dest": "paper/figures",
                        }
                    ],
                },
                "results-to-tex": {
                    "kind": "json-to-latex",
                    "inputs": ["results/summary.json"],
                    "outputs": ["paper/results.tex"],
                },
                "build-paper": {
                    "kind": "latex",
                    "target_path": "paper/paper.tex",
                    "environment": "tex",
                    "inputs": [
                        {"from_stage_outputs": "figs-to-paper"},
                        {"from_stage_outputs": "results-to-tex"},
                        "paper/references.bib",
                    ],
                    "outputs": ["paper/paper.pdf"],
                },
            }
        },
        "publications": [
            {
                "path": "paper/paper.pdf",
                "title": "Template paper",
                "kind": "journal-article",
                "stage": "build-paper",
            }
        ],
        "references": [{"path": "paper/references.bib"}],
        "showcase": [{"publication": "paper/paper.pdf"}],
    }
    files = {
        "figures/x.png": png,
        "results/summary.json": b'{"r": 1}\n',
        "paper/paper.tex": b"\\documentclass{article}\n",
        "paper/references.bib": b"@article{old}\n",
        "paper/figures/x.png": png,
        "paper/results.tex": b"\\newcommand{\\r}{1}\n",
    }
    repo, origin = _make_repo(tmp_path, files, ck_info)
    wdir = str(repo.working_dir)
    fake_project = SimpleNamespace(
        owner_account_name="o", name="p", id=uuid.uuid4()
    )
    zip_data = _zip_bytes(
        {
            "main.tex": (
                b"\\documentclass{article}\n\\title{New paper}\n"
                b"\\begin{document}\\maketitle\\end{document}\n"
            ),
            "refs.bib": b"@article{new}\n",
        }
    )
    form = {"path": "paper", "kind": "journal-article"}
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch("app.api.routes.projects.core.get_repo", return_value=repo),
    ):
        # Without opting in, the existing folder is refused
        resp = client.post(
            f"{URL}/overleaf",
            data=form,
            files={"file": ("paper.zip", zip_data, "application/zip")},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 400, resp.text
        assert "already exists" in resp.json()["detail"]
        assert os.path.isfile(os.path.join(wdir, "paper", "paper.tex"))
        # Replacing empties the folder and rewires the paper to the feeders
        resp = client.post(
            f"{URL}/overleaf",
            data=form | {"replace_existing": "true"},
            files={"file": ("paper.zip", zip_data, "application/zip")},
            headers=normal_user_token_headers,
        )
    assert resp.status_code == 200, resp.text
    pub = resp.json()
    assert pub["path"] == "paper/main.pdf"
    assert pub["title"] == "New paper"
    assert pub["stage"] == "build-paper"
    # Old files are gone and the Overleaf ones are in their place
    for old in ["paper.tex", "references.bib", "figures/x.png", "results.tex"]:
        assert not os.path.exists(os.path.join(wdir, "paper", old)), old
    assert os.path.isfile(os.path.join(wdir, "paper", "main.tex"))
    assert os.path.isfile(os.path.join(wdir, "paper", "refs.bib"))
    tracked = repo.git.ls_files("paper").splitlines()
    assert "paper/main.tex" in tracked
    assert "paper/paper.tex" not in tracked
    assert "paper/figures/x.png" not in tracked
    assert not repo.is_dirty(untracked_files=True)
    assert origin.head.commit.hexsha == repo.head.commit.hexsha
    # The feeder files outside the folder are untouched
    assert os.path.isfile(os.path.join(wdir, "figures", "x.png"))
    with open(os.path.join(wdir, "calkit.yaml")) as f:
        ck = ryaml.load(f)
    stages = ck["pipeline"]["stages"]
    assert "figs-to-paper" in stages
    assert "results-to-tex" in stages
    assert (
        stages["figs-to-paper"]
        == ck_info["pipeline"]["stages"]["figs-to-paper"]
    )
    # The old build stage was dropped, so the default name is free again
    build = stages["build-paper"]
    assert build["kind"] == "latex"
    assert build["target_path"] == "paper/main.tex"
    assert build["environment"] == "tex"
    assert {"from_stage_outputs": "figs-to-paper"} in build["inputs"]
    assert {"from_stage_outputs": "results-to-tex"} in build["inputs"]
    plain_inputs = [i for i in build["inputs"] if isinstance(i, str)]
    assert plain_inputs == ["paper/refs.bib"]
    assert [p["path"] for p in ck["publications"]] == ["paper/main.pdf"]
    assert ck["publications"][0]["stage"] == "build-paper"
    # The old reference isn't in the Overleaf project, so it's gone
    assert ck["references"] == []
    assert ck["showcase"] == [{"publication": "paper/main.pdf"}]
    assert "overleaf_sync" not in ck
    assert "tex" in ck["environments"]
    # The compiled pipeline feeds the paper from the kept stages
    with open(os.path.join(wdir, "dvc.yaml")) as f:
        dvc_deps = ryaml.load(f)["stages"]["build-paper"]["deps"]
    assert "paper/figures" in dvc_deps
    assert "paper/results.tex" in dvc_deps
    assert "paper/refs.bib" in dvc_deps


def test_get_project_publication_components(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 32
    hand_png = b"\x89PNG\r\n\x1a\n" + b"h" * 32
    ck_info: dict[str, Any] = {
        "name": "p",
        "pipeline": {
            "stages": {
                "figs-to-paper": {
                    "kind": "map-paths",
                    "paths": [
                        {
                            "kind": "file-to-file",
                            "src": "figures/gen.png",
                            "dest": "paper/figures/gen.png",
                        },
                        {
                            "kind": "dir-to-dir-merge",
                            "src": "figures/sub",
                            "dest": "paper/figures/sub",
                        },
                    ],
                },
                "results-to-tex": {
                    "kind": "json-to-latex",
                    "inputs": ["results/summary.json"],
                    "outputs": ["paper/results.tex"],
                },
                "build-paper": {
                    "kind": "latex",
                    "target_path": "paper/paper.tex",
                    "environment": "tex",
                    # Read from outside the folder: a directory to walk,
                    # a single file, and another stage's outputs (which
                    # are in the folder, so already covered)
                    "inputs": [
                        "data/tables",
                        "data/table.csv",
                        {"from_stage_outputs": "figs-to-paper"},
                    ],
                    "outputs": ["paper/paper.pdf"],
                },
            }
        },
        "figures": [
            {"path": "figures/x.png", "title": "X"},
            {"path": "figures/gen.png", "title": "Gen"},
        ],
        "datasets": [
            {
                "path": "data/table.csv",
                "imported_from": {"url": "https://example.org/table.csv"},
            }
        ],
        "misc": [
            {
                "path": "paper/photo.jpg",
                "created_by": [{"email": "a@example.com"}],
            },
            {
                "path": "paper/logo.png",
                "imported_from": {"url": "https://example.org/logo.png"},
            },
        ],
        "publications": [
            {
                "path": "paper/paper.pdf",
                "title": "Paper",
                "kind": "journal-article",
                "stage": "build-paper",
            }
        ],
    }
    files = {
        "figures/x.png": png,
        "figures/gen.png": b"gen",
        "figures/sub/a.png": b"a",
        "results/summary.json": b"{}",
        "data/table.csv": b"a,b\n",
        "data/tables/t1.csv": b"1,2\n",
        "paper/paper.tex": b"\\documentclass{article}\n",
        "paper/refs.bib": b"@article{x}\n",
        # A copy of a figure made without a map-paths stage
        "paper/figures/x.png": png,
        "paper/figures/hand.png": hand_png,
        "paper/figures/gen.png": b"gen",
        "paper/figures/sub/a.png": b"a",
        "paper/results.tex": b"\\newcommand{\\r}{1}\n",
        "paper/photo.jpg": b"jpg",
        "paper/logo.png": b"logo",
        "paper/paper.pdf": b"%PDF",
        "paper/paper.aux": b"aux",
        "paper/main.synctex.gz": b"gz",
        "paper/.gitignore": b"*.aux\n",
        "paper/.hidden/secret.txt": b"s",
    }
    repo, _ = _make_repo(tmp_path, files, ck_info)
    fake_project = SimpleNamespace(
        owner_account_name="o", name="p", id=uuid.uuid4()
    )
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch("app.api.routes.projects.core.get_repo", return_value=repo),
    ):
        resp = client.get(
            f"{URL}/components",
            params={"path": "paper/paper.pdf"},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["folder"] == "paper"
        by_path = {item["path"]: item for item in body["items"]}
        assert sorted(by_path) == [
            "data/table.csv",
            "data/tables/t1.csv",
            "paper/figures/gen.png",
            "paper/figures/hand.png",
            "paper/figures/sub/a.png",
            "paper/figures/x.png",
            "paper/logo.png",
            "paper/paper.tex",
            "paper/photo.jpg",
            "paper/refs.bib",
            "paper/results.tex",
        ]
        assert by_path["paper/figures/gen.png"] == {
            "path": "paper/figures/gen.png",
            "kind": "produced",
            "via": "folder",
            "stage": "figs-to-paper",
            "stage_kind": "map-paths",
            "source": None,
            "matching_figure": None,
            "size": 3,
        }
        assert by_path["paper/figures/sub/a.png"]["kind"] == "produced"
        assert by_path["paper/figures/sub/a.png"]["stage"] == "figs-to-paper"
        assert by_path["paper/results.tex"]["kind"] == "produced"
        assert by_path["paper/results.tex"]["stage"] == "results-to-tex"
        assert by_path["paper/results.tex"]["stage_kind"] == "json-to-latex"
        # The build stage's inputs from outside the folder are components
        # too, classified the same way
        assert by_path["data/table.csv"]["via"] == "input"
        assert by_path["data/table.csv"]["kind"] == "imported"
        assert by_path["data/tables/t1.csv"]["via"] == "input"
        assert by_path["data/tables/t1.csv"]["kind"] == "unknown"
        assert all(
            item["via"] == "folder"
            for p, item in by_path.items()
            if p.startswith("paper/")
        )
        assert by_path["paper/photo.jpg"]["kind"] == "attested"
        assert by_path["paper/logo.png"]["kind"] == "imported"
        for authored in ["paper/paper.tex", "paper/refs.bib"]:
            assert by_path[authored]["kind"] == "authored"
            assert by_path[authored]["source"] == "git"
        assert by_path["paper/figures/x.png"]["kind"] == "unknown"
        assert (
            by_path["paper/figures/x.png"]["matching_figure"]
            == "figures/x.png"
        )
        assert by_path["paper/figures/x.png"]["size"] == len(png)
        assert by_path["paper/figures/hand.png"]["kind"] == "unknown"
        assert by_path["paper/figures/hand.png"]["matching_figure"] is None
        assert body["n_unknown"] == 3
        # A folder synced with Overleaf is where its sources are edited
        ck_info["overleaf_sync"] = {
            "paper": {"url": "https://www.overleaf.com/project/abc123"}
        }
        with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
            ryaml.dump(ck_info, f)
        resp = client.get(
            f"{URL}/components",
            params={"path": "paper/paper.pdf"},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        by_path = {item["path"]: item for item in resp.json()["items"]}
        assert by_path["paper/paper.tex"]["source"] == "overleaf"
        assert by_path["paper/figures/x.png"]["source"] is None
        # A path leaving the project is refused
        resp = client.get(
            f"{URL}/components",
            params={"path": "../paper.pdf"},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 400, resp.text
