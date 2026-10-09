"""Tests for comments on a LaTeX document's PDF, kept in its source."""

import os
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import git
from fastapi.testclient import TestClient

import calkit.latex
from app import pdftext
from app.core import ryaml

URL = "/projects/o/p/latex-comments"
FIXTURES = Path(__file__).parents[7] / "test" / "latex-comments"
MODULE = "app.api.routes.projects.latex_comments"


def test_latex_comments(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    # A paper built by a latex stage, with a thread in an input already,
    # and a bare origin standing in for the remote
    origin = git.Repo.init(tmp_path / "origin.git", bare=True)
    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    paper = tmp_path / "repo" / "paper"
    os.makedirs(paper)
    for name in ["main.tex", "intro.tex", "main.pdf"]:
        shutil.copy(FIXTURES / name, paper / name)
    ck_info = {
        "pipeline": {
            "stages": {
                "build-paper": {
                    "kind": "latex",
                    "target_path": "paper/main.tex",
                    "environment": "tex",
                }
            }
        }
    }
    with open(tmp_path / "repo" / "calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add(all=True)
    repo.git.commit("-m", "Initial")
    repo.create_remote("origin", str(origin.working_dir))
    branch = repo.active_branch.name
    repo.git.push("origin", branch)
    repo.git.fetch("origin")
    first_rev = repo.head.commit.hexsha
    project = SimpleNamespace(
        id=uuid.uuid4(),
        name="p",
        owner_account=SimpleNamespace(name="o"),
        owner_github_name="o",
        git_repo_url="https://example.com/o/p",
        github_repo=None,
        current_user_access="write",
    )

    def origin_file(path: str, ref: str = branch) -> str:
        return origin.git.show(f"{ref}:{path}", strip_newline_in_stdout=False)

    with (
        patch(f"{MODULE}.app.projects.get_project", return_value=project),
        patch(f"{MODULE}.get_repo", return_value=repo),
    ):
        # The threads in the source are placed on the PDF
        resp = client.get(
            URL,
            params={"path": "paper/main.pdf"},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["source"] == "paper/main.tex"
        assert data["branch"] == branch and data["can_comment"]
        (thread,) = data["threads"]
        assert (
            thread["key"] == "0a1b2c3d" and thread["path"] == "paper/intro.tex"
        )
        assert thread["highlight"] == "turbine wakes"
        assert thread["position"]["pageNumber"] == 1
        assert thread["messages"][0]["author"] == "A. Reviewer"
        # A PDF no latex stage builds has no source to comment in
        resp = client.get(
            URL,
            params={"path": "other.pdf"},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 404
        # Commenting on the second "the wake recovers" in a paragraph, as
        # selected in a viewer, writes a thread above that paragraph
        layout = pdftext.PdfLayout((paper / "main.pdf").read_bytes())
        hits = layout.find("the wake recovers")
        position = layout.position(*hits[1])
        resp = client.post(
            URL,
            json={
                "path": "paper/main.pdf",
                "comment": "How quickly?",
                "highlight": {
                    "position": position,
                    "content": {"text": "the wake\nrecovers"},
                },
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        new = next(
            t
            for t in data["threads"]
            if t["messages"][0]["text"] == "How quickly?"
        )
        assert new["highlight"] == "the wake recovers"
        assert new["position"] == position
        assert data["rev"] != first_rev
        main = origin_file("paper/main.tex").split("\n")
        (tc,) = calkit.latex.parse_comments(main)
        assert (tc.highlight, tc.highlight_occ) == ("the wake recovers", 1)
        assert main[tc.lineno - 1 + tc.nlines].startswith("The model fits")
        assert tc.entries[0].email and tc.id == new["id"]
        # It's a commit on the branch, authored by the commenter, and the
        # rest of the file is untouched
        commit = origin.commit(branch)
        assert commit.parents[0].hexsha == first_rev
        assert commit.message.strip() == "Comment on paper/main.pdf"
        assert commit.author.email == tc.entries[0].email
        assert (
            "\n".join(
                line
                for i, line in enumerate(main)
                if not (tc.lineno - 1 <= i < tc.lineno - 1 + tc.nlines)
            )
            == (FIXTURES / "main.tex").read_text()
        )
        # Replying and resolving work from what's being viewed, even after
        # someone else moved the branch on, e.g., from the CLI
        other = git.Repo.clone_from(origin.working_dir, tmp_path / "other")
        with other.config_writer() as cw:
            cw.set_value("user", "name", "Other")
            cw.set_value("user", "email", "other@example.com")
        with open(tmp_path / "other" / "paper" / "main.tex", "a") as f:
            f.write("% An unrelated edit\n")
        other.git.commit("-am", "Edit elsewhere")
        other.git.push("origin", branch)
        for path, json in [
            ("/replies", {"key": "0a1b2c3d", "body": "Arrays of them."}),
            ("", {"key": "0a1b2c3d", "resolved": True}),
        ]:
            send = client.post if path else client.patch
            resp = send(
                URL + path,
                json={"path": "paper/main.pdf", **json},
                headers=normal_user_token_headers,
            )
            assert resp.status_code == 200, resp.text
        thread = next(
            t for t in resp.json()["threads"] if t["key"] == "0a1b2c3d"
        )
        assert thread["resolved"]
        assert [m["text"] for m in thread["messages"]] == [
            "Which turbines?",
            "Arrays of them.",
        ]
        assert origin_file("paper/main.tex").endswith("% An unrelated edit\n")
        assert "resolved=true" in origin_file("paper/intro.tex")
        # A comment without a selection is on the whole document, at the
        # top of its body
        resp = client.post(
            URL,
            json={"path": "paper/main.pdf", "comment": "Nice paper."},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        main = origin_file("paper/main.tex").split("\n")
        tc = calkit.latex.parse_comments(main)[0]
        assert tc.text == "Nice paper." and tc.highlight is None
        assert main[tc.lineno - 1 + tc.nlines] == "\\section{Introduction}"
        # Deleting takes the thread out of the source
        resp = client.delete(
            URL,
            params={"path": "paper/main.pdf", "key": new["id"]},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert "How quickly?" not in origin_file("paper/main.tex")
        assert new["id"] not in [t["id"] for t in resp.json()["threads"]]
        # A commit, unlike a branch, can't take a comment, so it goes on a
        # branch from it, leaving the branch being viewed alone
        tip = origin.commit(branch).hexsha
        resp = client.post(
            URL,
            json={
                "path": "paper/main.pdf",
                "ref": first_rev,
                "comment": "From the first draft.",
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["branch"] is None
        review_branches = [
            h.name
            for h in origin.heads
            if h.name.startswith("calkit/comments/")
        ]
        assert len(review_branches) == 1
        assert review_branches[0].endswith(first_rev[:7])
        assert origin.commit(review_branches[0]).parents[0].hexsha == first_rev
        assert origin.commit(branch).hexsha == tip
        # A thread whose GitHub issue was closed is resolved in the source
        # when it's next read
        other.git.pull("origin", branch)
        intro = origin_file("paper/intro.tex")
        with open(tmp_path / "other" / "paper" / "intro.tex", "w") as f:
            f.write(
                intro.replace(" resolved=true", "").replace(
                    "% COMMENT id=0a1b2c3d",
                    "% COMMENT id=0a1b2c3d issue=https://github.com/o/p/issues/7",
                )
            )
        other.git.commit("-am", "Link an issue")
        other.git.push("origin", branch)
        # What getting the repo does, which is patched out here
        repo.git.fetch("origin")
        closed = SimpleNamespace(ok=True, json=lambda: {"state": "closed"})
        with (
            patch(f"{MODULE}.requests.get", return_value=closed),
            patch(f"{MODULE}._github_token_for_repo", return_value=None),
        ):
            resp = client.get(
                URL,
                params={"path": "paper/main.pdf"},
                headers=normal_user_token_headers,
            )
        assert resp.status_code == 200, resp.text
        thread = next(
            t for t in resp.json()["threads"] if t["key"] == "0a1b2c3d"
        )
        assert thread["resolved"]
        assert "resolved=true" in origin_file("paper/intro.tex")
        assert "closed on GitHub" in origin.commit(branch).message
