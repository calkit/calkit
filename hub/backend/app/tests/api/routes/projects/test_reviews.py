"""Tests for the reviewed Word document routes.

The fixtures are the ones the CLI's round trip is tested with: a paper at
``paper/`` and ``returned.docx``, that paper's export marked up in Word
with two tracked changes and a comment.
"""

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import git
from fastapi.testclient import TestClient

URL = "/projects/o/p/latex-reviews"
FIXTURES = Path(__file__).parents[7] / "test" / "docx"


def _make_repo(tmp_path):
    origin = git.Repo.init(tmp_path / "origin.git", bare=True)
    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    wdir = Path(repo.working_dir)
    (wdir / "paper").mkdir()
    for name in ["main.tex", "methods.tex"]:
        shutil.copy(FIXTURES / name, wdir / "paper" / name)
    (wdir / "calkit.yaml").write_text("")
    repo.git.add(all=True)
    repo.git.commit("-m", "Initial")
    repo.create_remote("origin", str(origin.working_dir))
    repo.git.push("origin", repo.active_branch.name)
    return repo, origin


def _patches(repo: git.Repo, stored: dict[str, bytes]):
    fake_project = SimpleNamespace(
        owner_account_name="o", name="p", updated=None
    )
    mod = "app.api.routes.projects.reviews"
    return (
        patch(f"{mod}.app.projects.get_project", return_value=fake_project),
        patch(f"{mod}.get_repo", return_value=repo),
        patch(f"{mod}.record_project_update"),
        patch(
            f"{mod}._store",
            side_effect=lambda project, md5, data: stored.__setitem__(
                md5, data
            ),
        ),
    )


def test_review_round_trip(
    client: TestClient, normal_user_token_headers: dict[str, str], tmp_path
) -> None:
    repo, origin = _make_repo(tmp_path)
    wdir = Path(repo.working_dir)
    stored: dict[str, bytes] = {}
    p1, p2, p3, p4 = _patches(repo, stored)
    with p1, p2, p3, p4:
        # Nothing yet
        resp = client.get(URL, headers=normal_user_token_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json() == []
        # A document Calkit didn't export is refused and leaves no trace
        resp = client.post(
            URL,
            files={
                "file": (
                    "foreign.docx",
                    (FIXTURES / "word-import.docx").read_bytes(),
                    "application/octet-stream",
                )
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 422, resp.text
        assert not (wdir / "reviews").exists()
        # A reviewed export lands under reviews/ in DVC and comes back
        # with what merging would do
        data = (FIXTURES / "returned.docx").read_bytes()
        resp = client.post(
            URL,
            files={
                "file": (
                    "PI comments.docx",
                    data,
                    "application/octet-stream",
                )
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        plan = resp.json()
        assert plan["path"] == "reviews/PI-comments.docx"
        assert plan["source"] == "paper/main.tex"
        assert plan["storage"] == "dvc"
        assert plan["open_edits"] == 2 and plan["open_comments"] == 1
        assert plan["last_merged"] is None
        assert [e["status"] for e in plan["edits"]] == ["pending", "pending"]
        assert (wdir / "reviews/PI-comments.docx.dvc").is_file()
        assert repo.git.log("--format=%s", "-1") == (
            "Add reviews/PI-comments.docx"
        )
        assert origin.head.commit.hexsha == repo.head.commit.hexsha
        assert list(stored.values()) == [data]
        assert "reviews/PI-comments.docx" not in repo.git.ls_files().split(
            "\n"
        )
        # It's listed, and can be filtered by source
        resp = client.get(URL, headers=normal_user_token_headers)
        assert [r["path"] for r in resp.json()] == ["reviews/PI-comments.docx"]
        resp = client.get(
            URL,
            params={"source": "paper/other.tex"},
            headers=normal_user_token_headers,
        )
        assert resp.json() == []
        # Decide: take the edit in main.tex, decline the one in
        # methods.tex, keep the comment
        main_edit = next(
            e for e in plan["edits"] if e["path"] == "paper/main.tex"
        )
        methods_edit = next(
            e for e in plan["edits"] if e["path"] == "paper/methods.tex"
        )
        resp = client.post(
            f"{URL}/reviews/PI-comments.docx/merge",
            json={
                "accept": [main_edit["key"]],
                "reject": [methods_edit["key"]],
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        result = resp.json()
        assert result["commit"] == repo.head.commit.hexsha
        assert repo.git.log("--format=%s", "-1") == (
            "Merge 1 edit and 1 comment from reviews/PI-comments.docx"
        )
        assert {
            c["key"]: c["status"] for c in result["record"]["changes"]
        } == {
            main_edit["key"]: "applied",
            methods_edit["key"]: "rejected",
        }
        assert result["review"]["open_edits"] == 0
        assert result["review"]["open_comments"] == 0
        assert result["review"]["last_merged"] is not None
        main = (wdir / "paper/main.tex").read_text()
        assert "as shown by \\citet{smith2020}" in main
        assert "%   A. Reviewer" in main
        assert "sampling frequency" in (wdir / "paper/methods.tex").read_text()
        records = list((wdir / ".calkit/latex/docx-merges").iterdir())
        assert len(records) == 1
        assert json.loads(records[0].read_text())["docx"] == (
            "reviews/PI-comments.docx"
        )
        assert not repo.is_dirty(untracked_files=True)
        # The decisions stick
        resp = client.get(
            f"{URL}/reviews/PI-comments.docx",
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert {e["key"]: e["status"] for e in resp.json()["edits"]} == {
            main_edit["key"]: "already-applied",
            methods_edit["key"]: "rejected",
        }
        # Nothing to decide means no commit
        resp = client.post(
            f"{URL}/reviews/PI-comments.docx/merge",
            json={},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["commit"] is None
        # Unknown items are refused before anything is touched
        resp = client.post(
            f"{URL}/reviews/PI-comments.docx/merge",
            json={"accept": ["ck_nope_1"]},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 422
        # The bytes are fetched from storage when the checkout lacks them
        os.remove(wdir / "reviews/PI-comments.docx")
        md5 = next(iter(stored))
        with (
            patch(
                "app.api.routes.projects.reviews.get_object_fs",
                return_value=SimpleNamespace(
                    open=lambda fpath, mode: open(tmp_path / "blob", mode)
                ),
            ),
            patch(
                "app.api.routes.projects.reviews.get_data_fpath_for_md5",
                return_value=str(tmp_path / "blob"),
            ),
        ):
            (tmp_path / "blob").write_bytes(stored[md5])
            resp = client.get(
                f"{URL}/reviews/PI-comments.docx",
                headers=normal_user_token_headers,
            )
            assert resp.status_code == 200, resp.text
            assert (wdir / "reviews/PI-comments.docx").read_bytes() == data


def test_review_paths_are_checked(
    client: TestClient, normal_user_token_headers: dict[str, str], tmp_path
) -> None:
    repo, _ = _make_repo(tmp_path)
    p1, p2, p3, p4 = _patches(repo, {})
    with p1, p2, p3, p4:
        resp = client.get(
            f"{URL}/../../etc/passwd.docx", headers=normal_user_token_headers
        )
        assert resp.status_code in (400, 404)
        resp = client.post(
            URL,
            data={"path": "reviews/notes.txt"},
            files={"file": ("notes.txt", b"hi", "text/plain")},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 400
        resp = client.get(
            f"{URL}/reviews/missing.docx", headers=normal_user_token_headers
        )
        assert resp.status_code == 404


def test_reviews_require_auth(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
