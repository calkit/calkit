"""Tests for app.api.routes.projects.core endpoints."""

import base64
import uuid
from types import SimpleNamespace
from unittest.mock import ANY, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import users, zotero
from app.api.routes.projects.core import (
    _normalize_artifact_file_path,
    get_project_comments,
)
from app.config import settings
from app.core import ryaml
from app.models import Project, UserCreate
from app.models.core import ContentsItem, UserProjectAccess
from app.projects import CkInfoAndOuts
from app.tests import authentication_token_from_email, create_random_user


def test_get_project_contents_forwards_ref(client: TestClient) -> None:
    fake_project = SimpleNamespace()
    fake_repo = SimpleNamespace()
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ) as mock_get_project,
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ) as mock_get_repo,
        patch(
            "app.api.routes.projects.core.app.projects.get_contents_from_repo",
            return_value={
                "name": "README.md",
                "path": "README.md",
                "type": "file",
                "size": 12,
                "in_repo": True,
                "content": "hello world\n",
                "dir_items": None,
            },
        ) as mock_get_contents,
    ):
        response = client.get(
            (
                f"{settings.API_V1_STR}/projects/test-owner/test-project/contents"
                "?path=README.md&ref=v1.2.3"
            )
        )
    assert response.status_code == 200
    assert response.json()["path"] == "README.md"
    mock_get_project.assert_called_once_with(
        owner_name="test-owner",
        project_name="test-project",
        session=ANY,
        current_user=None,
        min_access_level="read",
    )
    # The API route must forward the selected ref to repo/content helpers
    assert mock_get_repo.call_count == 1
    repo_call = mock_get_repo.call_args.kwargs
    assert repo_call["project"] is fake_project
    assert repo_call["user"] is None
    assert repo_call["session"] is not None
    assert repo_call["ttl"] is not None
    assert repo_call["ref"] == "v1.2.3"
    # The ref must also be forwarded to get_contents_from_repo so it reads
    # the file tree at the requested snapshot, not the current HEAD
    assert mock_get_contents.call_count == 1
    contents_call = mock_get_contents.call_args.kwargs
    assert contents_call["project"] is fake_project
    assert contents_call["repo"] is fake_repo
    assert contents_call["path"] == "README.md"
    assert contents_call["ref"] == "v1.2.3"


def test_get_project_content_paths_merges_git_and_dvc(
    client: TestClient,
) -> None:
    fake_project = SimpleNamespace()
    fake_repo = SimpleNamespace(
        git=SimpleNamespace(
            ls_files=lambda: (
                "README.md\nfigs/plot.png.dvc\n.dvc/config\nscripts/run.py"
            )
        )
    )
    dvc_outs = {"figs/plot.png": {"type": "file"}, "data": {"type": "dir"}}
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.app.projects.get_repo_tree_for_ref",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.api.routes.projects.core.app.projects"
            ".get_ck_info_and_dvc_outs_from_tree",
            return_value=CkInfoAndOuts({}, dvc_outs, {}, {}),
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}"
            "/projects/test-owner/test-project/contents-paths"
        )
    assert response.status_code == 200
    paths = response.json()
    # DVC output's real path is included; its .dvc pointer is dropped.
    assert "figs/plot.png" in paths
    assert "figs/plot.png.dvc" not in paths
    # .dvc internals and DVC dir outputs are excluded; plain git files kept.
    assert ".dvc/config" not in paths
    assert "data" not in paths
    assert "README.md" in paths
    assert "scripts/run.py" in paths
    # Sorted for stable display.
    assert paths == sorted(paths)


def test_get_project_file_history_endpoint(client: TestClient) -> None:
    fake_project = SimpleNamespace()
    fake_repo = SimpleNamespace()
    fake_history = [
        {
            "hash": "abc" * 13 + "abcd",
            "short_hash": "abc1234",
            "message": "Update figure\n",
            "author": "Test User",
            "author_email": "test@example.com",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "committed_date": 1735689600,
            "parent_hashes": [],
            "summary": "Update figure",
        }
    ]
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ),
        patch(
            "app.api.routes.projects.core.get_file_history",
            return_value=fake_history,
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project"
            "/git/file-history?path=figures/my-figure.png"
        )
    assert response.status_code == 200
    # Endpoint should proxy through the git history payload unchanged
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["short_hash"] == "abc1234"


def test_get_project_file_history_rejects_absolute_path(
    client: TestClient,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/projects/test-owner/test-project"
        "/git/file-history?path=/etc/passwd"
    )
    assert response.status_code == 400


def test_get_project_file_history_rejects_traversal(
    client: TestClient,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/projects/test-owner/test-project"
        "/git/file-history?path=../secrets.txt"
    )
    assert response.status_code == 400


def test_project_routes_are_case_insensitive(client: TestClient) -> None:
    fake_project = SimpleNamespace(is_public=True)
    fake_repo = SimpleNamespace()
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ) as mock_get_project,
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_contents_from_repo",
            return_value={
                "name": "README.md",
                "path": "README.md",
                "type": "file",
                "size": 12,
                "in_repo": True,
                "content": "hello world\n",
                "dir_items": None,
            },
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/MyOrg/My-Project/contents"
            "?path=README.md"
        )
    assert response.status_code == 200
    mock_get_project.assert_called_once_with(
        owner_name="MyOrg",
        project_name="My-Project",
        session=ANY,
        current_user=None,
        min_access_level="read",
    )


def test_get_project_comments_uses_all_results() -> None:
    fake_project = SimpleNamespace(id="project-id")
    fake_comment = SimpleNamespace(id="comment-id")

    class ExecResult:
        def __init__(self) -> None:
            self.all_called = False

        def all(self):
            self.all_called = True
            return [fake_comment]

    class FakeSession:
        def __init__(self) -> None:
            self.exec_result = ExecResult()

        def exec(self, _query):
            return self.exec_result

    session = FakeSession()
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core._sync_github_issue_resolutions"
        ) as mock_sync,
    ):
        comments = get_project_comments(
            owner_name="test-owner",
            project_name="test-project",
            current_user=None,
            session=session,  # type: ignore
            artifact_type="publication",
            artifact_path="paper/main.pdf",
        )
    assert session.exec_result.all_called is True
    assert comments == [fake_comment]
    mock_sync.assert_called_once_with(session, [fake_comment], None)


def _make_fake_blob(path: str) -> SimpleNamespace:
    """Return a minimal git blob-like object for auto-detection tests."""
    return SimpleNamespace(type="blob", path=path)


def test_get_project_figures_paginates(client: TestClient) -> None:
    fake_project = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        owner_account_name="test-owner",
        name="test-project",
        file_locks=[],
    )
    fake_tree = SimpleNamespace()
    paths = [f"figures/fig{i}.png" for i in range(5)]
    blobs = [_make_fake_blob(p) for p in paths]
    fake_commit = SimpleNamespace()
    fake_commit.tree = SimpleNamespace(traverse=lambda: iter(blobs))
    fake_repo = SimpleNamespace()
    fake_repo.head = SimpleNamespace(commit=fake_commit)
    fake_contents = ContentsItem(
        name="fig",
        path="fig",
        type="file",
        size=0,
        in_repo=True,
        content=None,
        url=None,
        storage=None,
    )
    url = f"{settings.API_V1_STR}/projects/test-owner/test-project/figures"
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={},
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_repo_tree_for_ref",
            return_value=fake_tree,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_and_dvc_outs_from_tree",
            return_value=CkInfoAndOuts({}, {}, {}, {}),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_contents_from_tree",
            return_value=fake_contents,
        ) as mock_contents,
    ):
        first = client.get(f"{url}?limit=2&offset=0")
        # Content is resolved only for the page, not the whole project. This
        # is the property that keeps the endpoint from scaling with the
        # project's figure count.
        assert mock_contents.call_count == 2
        mock_contents.reset_mock()
        second = client.get(f"{url}?limit=2&offset=2")
        assert mock_contents.call_count == 2
        mock_contents.reset_mock()
        last = client.get(f"{url}?limit=2&offset=4")
        assert mock_contents.call_count == 1
        past_end = client.get(f"{url}?limit=2&offset=10")
        overshoot = client.get(f"{url}?limit=100&offset=0")
    # Every page reports the same total so the client can page through.
    for resp in (first, second, last, past_end, overshoot):
        assert resp.status_code == 200
        assert resp.json()["total"] == 5
    assert [f["path"] for f in first.json()["items"]] == paths[:2]
    assert [f["path"] for f in second.json()["items"]] == paths[2:4]
    assert [f["path"] for f in last.json()["items"]] == paths[4:]
    assert past_end.json()["items"] == []
    assert [f["path"] for f in overshoot.json()["items"]] == paths
    assert first.json()["limit"] == 2
    assert first.json()["offset"] == 0
    # Out-of-range paging values are rejected rather than silently clamped.
    assert client.get(f"{url}?limit=0").status_code == 422
    assert client.get(f"{url}?limit=101").status_code == 422
    assert client.get(f"{url}?offset=-1").status_code == 422


def test_get_project_figures_search_content_and_single(
    client: TestClient,
) -> None:
    fake_project = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        owner_account_name="test-owner",
        name="test-project",
        file_locks=[],
    )
    paths = [f"figures/plot{i}.png" for i in range(30)]
    paths += ["figures/nested/histogram.png"]
    blobs = [_make_fake_blob(p) for p in paths]
    fake_repo = SimpleNamespace(
        head=SimpleNamespace(
            commit=SimpleNamespace(
                tree=SimpleNamespace(traverse=lambda: iter(blobs))
            )
        )
    )
    fake_contents = ContentsItem(
        name="fig",
        path="fig",
        type="file",
        size=0,
        in_repo=True,
        content="Zm9v",
        url="https://example.com/fig.png",
        storage="git",
    )
    url = f"{settings.API_V1_STR}/projects/test-owner/test-project/figures"
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={},
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_repo_tree_for_ref",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.api.routes.projects.core.app.projects."
            "get_ck_info_and_dvc_outs_from_tree",
            return_value=CkInfoAndOuts({}, {}, {}, {}),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_contents_from_tree",
            return_value=fake_contents,
        ) as mock_contents,
    ):
        # Search spans the whole project, not just the current page: the only
        # match here is discovered well past the first page of 20.
        matched = client.get(f"{url}?q=histogram&limit=20&offset=0")
        # Matching is case-insensitive and substring-based.
        upper = client.get(f"{url}?q=HISTO&limit=20&offset=0")
        none_found = client.get(f"{url}?q=nothing-matches-this")
        # A whitespace-only query means no filter at all.
        blank = client.get(f"{url}?q=%20%20&limit=100&offset=0")
        mock_contents.reset_mock()
        # Metadata-only listings never touch object storage.
        without = client.get(f"{url}?include_content=false&limit=5")
        assert mock_contents.call_count == 0
        with_content = client.get(f"{url}?include_content=true&limit=5")
        assert mock_contents.call_count == 5
        # A single figure resolves even though it is auto-detected rather
        # than declared in calkit.yaml, and its nested path needs the route's
        # path convertor to match at all.
        found = client.get(f"{url}/figures/nested/histogram.png")
        missing = client.get(f"{url}/figures/not-a-figure.png")
    assert [f["path"] for f in matched.json()["items"]] == [
        "figures/nested/histogram.png"
    ]
    # `total` describes the filtered set so the client pages through matches.
    assert matched.json()["total"] == 1
    assert [f["path"] for f in upper.json()["items"]] == [
        "figures/nested/histogram.png"
    ]
    assert none_found.json()["items"] == []
    assert none_found.json()["total"] == 0
    assert blank.json()["total"] == len(paths)
    # Same figures in the same order either way, just without the bytes.
    assert without.status_code == 200
    assert [f["path"] for f in without.json()["items"]] == paths[:5]
    assert without.json()["total"] == len(paths)
    assert all(f["content"] is None for f in without.json()["items"])
    assert all(f["url"] is None for f in without.json()["items"])
    assert all(f["content"] == "Zm9v" for f in with_content.json()["items"])
    assert found.status_code == 200
    assert found.json()["path"] == "figures/nested/histogram.png"
    assert found.json()["content"] == "Zm9v"
    # Auto-detected figures get a title derived from their path.
    assert found.json()["title"]
    assert missing.status_code == 404


def test_get_project_figures_autodetects_deeply_nested(
    client: TestClient,
) -> None:
    """Figures inside a 'figures' dir at any depth must be auto-detected."""
    fake_project = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        owner_account_name="test-owner",
        name="test-project",
        file_locks=[],
    )
    fake_tree = SimpleNamespace()
    # Blobs that should be detected: file is inside a 'figures' directory
    # at various depths.
    detected_paths = [
        "figures/plot.png",  # direct child
        "results/figures/plot.png",  # one extra level
        "figures/something/else/55/fig.png",  # deeply nested
        "publications/paper1/figures/result.png",  # publications sub-tree
    ]
    # Blobs that must NOT be detected.
    ignored_paths = [
        "data/output.png",  # parent dir not in FIGURE_DIRS
        "plot.png",  # no parent directory at all
        ".calkit/figures/hidden.png",  # hidden directory
        "figures/plot.txt",  # unsupported extension
    ]
    blobs = [_make_fake_blob(p) for p in detected_paths + ignored_paths]
    fake_commit = SimpleNamespace()
    fake_commit.tree = SimpleNamespace(traverse=lambda: iter(blobs))
    fake_repo = SimpleNamespace()
    fake_repo.head = SimpleNamespace(commit=fake_commit)
    # fake_contents is returned by the mocked get_contents_from_tree for each
    # auto-detected figure, providing the content/url/storage fields the
    # endpoint attaches to every figure dict.
    fake_contents = ContentsItem(
        name="fig",
        path="fig",
        type="file",
        size=0,
        in_repo=True,
        content=None,
        url=None,
        storage=None,
    )
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={},
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_repo_tree_for_ref",
            return_value=fake_tree,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_and_dvc_outs_from_tree",
            return_value=CkInfoAndOuts({}, {}, {}, {}),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_contents_from_tree",
            return_value=fake_contents,
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/figures"
            "?limit=100"
        )
    assert response.status_code == 200
    returned_figures = response.json()["items"]
    returned_paths = {fig["path"] for fig in returned_figures}
    for path in detected_paths:
        assert path in returned_paths, f"Expected {path!r} to be detected"
    for path in ignored_paths:
        assert path not in returned_paths, f"Expected {path!r} to be ignored"
    # Titles must use sentence case (only first letter capitalized, not title
    # case where every word is capitalized).
    for fig in returned_figures:
        title = fig["title"]
        assert title == title[0].upper() + title[1:], (
            f"Title {title!r} is not in sentence case"
        )
        # No word after the first should be capitalized solely due to title()
        words = title.split()
        if len(words) > 1:
            assert not all(w[0].isupper() for w in words[1:] if w), (
                f"Title {title!r} appears to use title case, not sentence case"
            )


def test_get_project_figures_autodetects_dvc_stored(
    client: TestClient,
) -> None:
    """Figures stored with DVC (in dvc_lock_outs) must be auto-detected."""
    fake_project = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        owner_account_name="test-owner",
        name="test-project",
        file_locks=[],
    )
    fake_tree = SimpleNamespace()
    fake_repo = SimpleNamespace()
    # Repo has no git-tracked blobs
    fake_commit = SimpleNamespace()
    fake_commit.tree = SimpleNamespace(traverse=lambda: iter([]))
    fake_repo.head = SimpleNamespace(commit=fake_commit)
    # DVC lock outs contain figure files and non-figure files
    dvc_detected_paths = [
        "figures/plot.png",
        "results/figures/result.png",
    ]
    dvc_ignored_paths = [
        "data/output.png",  # not in a figure dir
        "figures/plot.txt",  # unsupported extension
    ]
    dvc_lock_outs = {}
    for p in dvc_detected_paths + dvc_ignored_paths:
        dvc_lock_outs[p] = {"path": p, "md5": "abc123", "type": "file"}
    # Add a dir entry that must be skipped
    dvc_lock_outs["figures"] = {"path": "figures", "type": "dir"}
    fake_contents = ContentsItem(
        name="fig",
        path="fig",
        type="file",
        size=0,
        in_repo=True,
        content=None,
        url=None,
        storage=None,
    )
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={},
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_repo_tree_for_ref",
            return_value=fake_tree,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_and_dvc_outs_from_tree",
            return_value=CkInfoAndOuts({}, dvc_lock_outs, {}, {}),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_contents_from_tree",
            return_value=fake_contents,
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/figures"
            "?limit=100"
        )
    assert response.status_code == 200
    returned_figures = response.json()["items"]
    returned_paths = {fig["path"] for fig in returned_figures}
    for path in dvc_detected_paths:
        assert path in returned_paths, (
            f"Expected DVC path {path!r} to be detected"
        )
    for path in dvc_ignored_paths:
        assert path not in returned_paths, (
            f"Expected DVC path {path!r} to be ignored"
        )
    # Dir entry must not appear
    assert "figures" not in returned_paths


def test_get_project_figures_dvc_no_duplicates_with_git(
    client: TestClient,
) -> None:
    """A figure tracked in both git tree and DVC lock outs must appear once."""
    fake_project = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        owner_account_name="test-owner",
        name="test-project",
        file_locks=[],
    )
    fake_tree = SimpleNamespace()
    shared_path = "figures/shared.png"
    fake_blob = _make_fake_blob(shared_path)
    fake_commit = SimpleNamespace()
    fake_commit.tree = SimpleNamespace(traverse=lambda: iter([fake_blob]))
    fake_repo = SimpleNamespace()
    fake_repo.head = SimpleNamespace(commit=fake_commit)
    # Same path also appears in dvc_lock_outs
    dvc_lock_outs = {
        shared_path: {"path": shared_path, "md5": "abc123", "type": "file"},
    }
    fake_contents = ContentsItem(
        name="fig",
        path="fig",
        type="file",
        size=0,
        in_repo=True,
        content=None,
        url=None,
        storage=None,
    )
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={},
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_repo_tree_for_ref",
            return_value=fake_tree,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_and_dvc_outs_from_tree",
            return_value=CkInfoAndOuts({}, dvc_lock_outs, {}, {}),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_contents_from_tree",
            return_value=fake_contents,
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/figures"
            "?limit=100"
        )
    assert response.status_code == 200
    returned_figures = response.json()["items"]
    paths = [fig["path"] for fig in returned_figures]
    assert paths.count(shared_path) == 1, (
        f"Expected {shared_path!r} to appear exactly once, got {paths}"
    )


def test_get_project_figures_autodetects_dvc_pointer_files(
    client: TestClient,
) -> None:
    """Figures stored via standalone .dvc pointer files must be auto-detected.

    When a blob ending in '.dvc' is found in the git tree (e.g.
    'figures/plot.png.dvc'), the derived path ('figures/plot.png') should be
    checked and added as a figure if it passes the extension/directory filter.
    """
    fake_project = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        owner_account_name="test-owner",
        name="test-project",
        file_locks=[],
    )
    fake_tree = SimpleNamespace()
    fake_repo = SimpleNamespace()
    # Blobs that are .dvc pointer files whose derived paths are figures
    dvc_pointer_detected = [
        "figures/plot.png",
        "results/figures/result.pdf",
    ]
    # .dvc pointer files whose derived paths are NOT figures
    dvc_pointer_ignored = [
        "data/output.png",  # not in a figure dir
        "figures/data.txt",  # unsupported extension
    ]
    # Build fake blobs: use the .dvc pointer file paths
    blobs = [_make_fake_blob(p + ".dvc") for p in dvc_pointer_detected] + [
        _make_fake_blob(p + ".dvc") for p in dvc_pointer_ignored
    ]
    fake_commit = SimpleNamespace()
    fake_commit.tree = SimpleNamespace(traverse=lambda: iter(blobs))
    fake_repo.head = SimpleNamespace(commit=fake_commit)
    fake_contents = ContentsItem(
        name="fig",
        path="fig",
        type="file",
        size=0,
        in_repo=True,
        content=None,
        url=None,
        storage=None,
    )
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={},
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_repo_tree_for_ref",
            return_value=fake_tree,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_and_dvc_outs_from_tree",
            return_value=CkInfoAndOuts({}, {}, {}, {}),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_contents_from_tree",
            return_value=fake_contents,
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/figures"
            "?limit=100"
        )
    assert response.status_code == 200
    returned_figures = response.json()["items"]
    returned_paths = {fig["path"] for fig in returned_figures}
    for path in dvc_pointer_detected:
        assert path in returned_paths, (
            f"Expected .dvc-pointer-tracked figure {path!r} to be detected"
        )
    for path in dvc_pointer_ignored:
        assert path not in returned_paths, (
            f"Expected .dvc-pointer-tracked non-figure {path!r} to be ignored"
        )
    # The .dvc pointer files themselves must not appear as figures
    for path in dvc_pointer_detected + dvc_pointer_ignored:
        assert path + ".dvc" not in returned_paths, (
            f"Pointer file {path + '.dvc'!r} must not appear as a figure"
        )


def test_get_project_figures_dvc_pointer_no_duplicates_with_dvc_lock(
    client: TestClient,
) -> None:
    """A figure in both dvc_lock_outs and a .dvc pointer blob must appear once.

    If a path is already in dvc_lock_outs (pipeline output), encountering the
    corresponding .dvc blob in the git tree must not produce a duplicate.
    """
    fake_project = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        owner_account_name="test-owner",
        name="test-project",
        file_locks=[],
    )
    fake_tree = SimpleNamespace()
    shared_path = "figures/shared.png"
    # Git tree contains a .dvc pointer blob for the same figure
    fake_blob = _make_fake_blob(shared_path + ".dvc")
    fake_commit = SimpleNamespace()
    fake_commit.tree = SimpleNamespace(traverse=lambda: iter([fake_blob]))
    fake_repo = SimpleNamespace()
    fake_repo.head = SimpleNamespace(commit=fake_commit)
    # Same path also appears in dvc_lock_outs (pipeline output)
    dvc_lock_outs = {
        shared_path: {"path": shared_path, "md5": "abc123", "type": "file"},
    }
    fake_contents = ContentsItem(
        name="fig",
        path="fig",
        type="file",
        size=0,
        in_repo=True,
        content=None,
        url=None,
        storage=None,
    )
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={},
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_repo_tree_for_ref",
            return_value=fake_tree,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_and_dvc_outs_from_tree",
            return_value=CkInfoAndOuts({}, dvc_lock_outs, {}, {}),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_contents_from_tree",
            return_value=fake_contents,
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/figures"
            "?limit=100"
        )
    assert response.status_code == 200
    returned_figures = response.json()["items"]
    returned_paths = [fig["path"] for fig in returned_figures]
    assert returned_paths.count(shared_path) == 1, (
        f"Expected {shared_path!r} to appear exactly once, got {returned_paths}"
    )


def test_get_project_pipeline_reads_at_ref(client: TestClient) -> None:
    """The pipeline endpoint must read files at the requested ref.

    get_repo only fetches a ref; it never checks it out, so reading from
    the working tree would silently return the default branch's pipeline.
    The endpoint must therefore read through get_repo_tree_for_ref.
    """
    fake_project = SimpleNamespace()
    fake_repo = SimpleNamespace()

    files = {
        "dvc.yaml": "stages:\n  train:\n    cmd: python train.py\n",
    }

    class FakeTree:
        def is_file(self, path: str) -> bool:
            return path in files

        def read_text(self, path: str, encoding: str = "utf-8") -> str:
            return files[path]

    fake_tree = FakeTree()

    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ) as mock_get_repo,
        patch(
            "app.api.routes.projects.core.app.projects.get_repo_tree_for_ref",
            return_value=fake_tree,
        ) as mock_get_tree,
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={},
        ) as mock_get_ck_info,
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/pipeline"
            "?ref=some-branch"
        )

    assert response.status_code == 200
    body = response.json()
    assert "train" in body["dvc_stages"]
    # The ref must be forwarded to get_repo so the branch is fetched
    assert mock_get_repo.call_args.kwargs["ref"] == "some-branch"
    # ...and to get_repo_tree_for_ref so files are read at that snapshot
    # rather than from the live working-tree checkout
    mock_get_tree.assert_called_once_with(fake_repo, "some-branch")
    # ...and to the Calkit metadata read for the same reason
    assert mock_get_ck_info.call_args.kwargs["ref"] == "some-branch"


def test_get_project_pipeline_reports_invalid_pipeline(
    client: TestClient,
) -> None:
    fake_project = SimpleNamespace()
    fake_repo = SimpleNamespace()
    # Two stages writing overlapping outputs: valid YAML, but DVC rejects it
    # when it builds the graph. That's the user's pipeline to fix, so the
    # endpoint has to say so rather than 500.
    files = {
        "dvc.yaml": (
            "stages:\n"
            "  make-dir:\n"
            "    cmd: python a.py\n"
            "    outs:\n"
            "    - results\n"
            "  make-file:\n"
            "    cmd: python b.py\n"
            "    outs:\n"
            "    - results/out.csv\n"
        ),
    }

    class FakeTree:
        def is_file(self, path: str) -> bool:
            return path in files

        def read_text(self, path: str, encoding: str = "utf-8") -> str:
            return files[path]

    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.app.projects.get_repo_tree_for_ref",
            return_value=FakeTree(),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={},
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/pipeline"
        )
    assert response.status_code == 200
    body = response.json()
    # The reason is reported, and names the conflict so it's actionable.
    assert body["error"]
    assert "overlap" in body["error"].lower()
    # No diagram, but the declared stages still come back so the page has
    # something to show alongside the explanation.
    assert body["mermaid"] == ""
    assert set(body["dvc_stages"]) == {"make-dir", "make-file"}


class _EmptyTree:
    """A repo tree with no files (defeats auto-detection in tests)."""

    def traverse(self):
        return []


def _ref_aware_endpoint_reads_declared_at_ref(
    client: TestClient, endpoint: str, ck_key: str
) -> None:
    """Shared assertions: declared metadata + pipeline read at the ref.

    get_repo only fetches a ref, it does not check it out, so the declared
    publications/presentations list and the DVC pipeline must be read via
    the ref-aware helpers rather than the live working tree.
    """
    fake_project = SimpleNamespace(owner_account_name="o", name="p")
    fake_repo = SimpleNamespace(
        working_dir="/tmp/nonexistent",
        commit=lambda _ref: SimpleNamespace(tree=_EmptyTree()),
        head=SimpleNamespace(commit=SimpleNamespace(tree=_EmptyTree())),
    )
    declared = [{"path": f"declared/from-{ck_key}.pdf", "title": "Declared"}]

    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ) as mock_get_repo,
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={ck_key: [dict(d) for d in declared]},
        ) as mock_ck_for_ref,
        patch(
            "app.api.routes.projects.core.app.projects"
            ".get_dvc_pipeline_for_ref",
            return_value={},
        ) as mock_pipeline_for_ref,
        patch(
            "app.api.routes.projects.core.app.projects.get_repo_tree_for_ref",
            return_value=object(),
        ),
        patch(
            "app.api.routes.projects.core.app.projects"
            ".get_ck_info_and_dvc_outs_from_tree",
            return_value=CkInfoAndOuts({}, {}, {}, {}),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_contents_from_tree",
            return_value=ContentsItem(
                name="x",
                path="x",
                type="file",
                size=1,
                in_repo=True,
                content=None,
                url=None,
                storage=None,
                dir_items=None,
            ),
        ),
        patch(
            "app.api.routes.projects.core.calkit.overleaf.get_sync_info",
            return_value={},
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/"
            f"{endpoint}?ref=some-branch"
        )

    assert response.status_code == 200, response.text
    paths = [item["path"] for item in response.json()]
    assert f"declared/from-{ck_key}.pdf" in paths
    assert mock_get_repo.call_args.kwargs["ref"] == "some-branch"
    # Declared metadata and the DVC pipeline must come from the ref, not
    # the working tree
    assert mock_ck_for_ref.call_args.kwargs["ref"] == "some-branch"
    pipeline_args = mock_pipeline_for_ref.call_args
    assert (pipeline_args.args + tuple(pipeline_args.kwargs.values()))[
        -1
    ] == "some-branch"


def test_get_project_publications_reads_declared_at_ref(
    client: TestClient,
) -> None:
    _ref_aware_endpoint_reads_declared_at_ref(
        client, "publications", "publications"
    )


def test_get_project_presentations_reads_declared_at_ref(
    client: TestClient,
) -> None:
    _ref_aware_endpoint_reads_declared_at_ref(
        client, "presentations", "presentations"
    )


def _make_owner_with_project(
    db: Session, client: TestClient
) -> tuple[Project, dict[str, str]]:
    """Create a project owner (with GitHub) + a private project, return the
    project and the owner's auth headers.
    """
    suffix = uuid.uuid4().hex[:8]
    owner = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"owner-{suffix}@example.com",
            password="ownerpassword123",
            account_name=f"owner{suffix}",
            github_username=f"owner{suffix}",
        ),
    )
    project = Project(
        name=f"proj-{suffix}",
        title="Invite Test Project",
        git_repo_url=f"https://github.com/owner{suffix}/proj-{suffix}",
        owner_account_id=owner.account.id,
        owner_account=owner.account,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    headers = authentication_token_from_email(
        client=client, email=owner.email, db=db
    )
    return project, headers


def test_invitation_create_and_redeem_grants_access(
    client: TestClient, db: Session
) -> None:
    project, owner_headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    # A GitHub-less user has no access to the private project yet.
    ghless = create_random_user(db)
    assert ghless.account.github_name is None
    ghless_headers = authentication_token_from_email(
        client=client, email=ghless.email, db=db
    )
    r = client.get(base, headers=ghless_headers)
    assert r.status_code == 403
    # Owner creates an invite link.
    r = client.post(
        f"{base}/invitations",
        headers=owner_headers,
        json={"role": "write", "max_uses": 5},
    )
    assert r.status_code == 200, r.text
    invite = r.json()
    assert invite["role_name"] == "write"
    assert invite["token"]
    assert f"/join/{invite['token']}" in invite["url"]
    token = invite["token"]
    # The GitHub-less user redeems it and gains write membership.
    r = client.post(
        f"{settings.API_V1_STR}/project-invitations/{token}",
        headers=ghless_headers,
    )
    assert r.status_code == 200, r.text
    redeemed = r.json()
    assert redeemed["owner_name"] == owner_name
    assert redeemed["project_name"] == project.name
    assert redeemed["role_name"] == "write"
    # Access row exists with a native role and the user can now read the
    # project.
    access = db.exec(
        select(UserProjectAccess)
        .where(UserProjectAccess.project_id == project.id)
        .where(UserProjectAccess.user_id == ghless.id)
    ).first()
    assert access is not None and access.role_name == "write"
    r = client.get(base, headers=ghless_headers)
    assert r.status_code == 200


def test_invitation_create_requires_admin(
    client: TestClient, db: Session
) -> None:
    project, _ = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    # A random non-member cannot create invitations.
    other = create_random_user(db)
    other_headers = authentication_token_from_email(
        client=client, email=other.email, db=db
    )
    r = client.post(
        f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
        "/invitations",
        headers=other_headers,
        json={"role": "write"},
    )
    assert r.status_code == 403


def test_redeem_revoked_invitation_fails(
    client: TestClient, db: Session
) -> None:
    project, owner_headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    r = client.post(
        f"{base}/invitations", headers=owner_headers, json={"role": "read"}
    )
    assert r.status_code == 200
    invite = r.json()
    # Revoke it.
    r = client.delete(
        f"{base}/invitations/{invite['id']}", headers=owner_headers
    )
    assert r.status_code == 200
    # Redeeming a revoked invite is rejected.
    redeemer = create_random_user(db)
    redeemer_headers = authentication_token_from_email(
        client=client, email=redeemer.email, db=db
    )
    r = client.post(
        f"{settings.API_V1_STR}/project-invitations/{invite['token']}",
        headers=redeemer_headers,
    )
    assert r.status_code == 410


def test_get_project_results_autodetects_and_reads_ref(
    client: TestClient,
) -> None:
    """Results under a results-style dir are auto-detected, and declared
    results plus the tree are read at the requested ref."""
    fake_project = SimpleNamespace(id="00000000-0000-0000-0000-000000000002")
    detected_paths = [
        "results/summary.json",
        "results/data.csv",
        "results/deep/nested/out.parquet",
        "result/single.yaml",
        "results.json",  # top-level file named results.<ext>
    ]
    ignored_paths = [
        "data/output.csv",  # parent dir not a results dir
        "summary.json",  # no results directory and not named results.*
        ".results/hidden.json",  # hidden directory
        "results/plot.png",  # not a result extension
    ]
    blobs = [_make_fake_blob(p) for p in detected_paths + ignored_paths]
    fake_commit = SimpleNamespace(
        tree=SimpleNamespace(traverse=lambda: iter(blobs))
    )
    fake_repo = SimpleNamespace(
        commit=lambda _ref: fake_commit,
        head=SimpleNamespace(commit=fake_commit),
    )
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ) as mock_get_repo,
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={},
        ) as mock_ck_for_ref,
        patch(
            "app.api.routes.projects.core.app.projects.get_repo_tree_for_ref",
            return_value=object(),
        ),
        patch(
            "app.api.routes.projects.core.app.projects"
            ".get_ck_info_and_dvc_outs_from_tree",
            return_value=CkInfoAndOuts({}, {}, {}, {}),
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/results"
            "?ref=some-branch"
        )
    assert response.status_code == 200, response.text
    paths = {res["path"] for res in response.json()}
    for path in detected_paths:
        assert path in paths, f"Expected {path!r} to be detected"
    for path in ignored_paths:
        assert path not in paths, f"Expected {path!r} to be ignored"
    assert mock_get_repo.call_args.kwargs["ref"] == "some-branch"
    assert mock_ck_for_ref.call_args.kwargs["ref"] == "some-branch"


def test_question_text_handles_string_and_object() -> None:
    from app.api.routes.projects.core import _extract_question_text

    assert _extract_question_text("Plain question?") == "Plain question?"
    assert (
        _extract_question_text({"question": "Rich?", "hypothesis": "h"})
        == "Rich?"
    )
    assert _extract_question_text({}) == ""
    # A non-string/non-dict value (e.g. a list) yields empty text, not a repr.
    assert _extract_question_text(["a", "b"]) == ""  # type: ignore


def test_build_question_evidence_resolves_figures_and_results() -> None:
    import base64
    import json

    from app.api.routes.projects.core import _build_question_evidence
    from app.models.core import Figure, Publication, Result

    fig = Figure(path="figures/x.png", title="X")
    # Declared with the key the evidence cites: a result is identified by
    # (path, key), and this test used to assert that citing 'metrics.mean'
    # resolved to a whole-file result, which is the mislabeling that
    # fallback caused
    res = Result(
        path="results/summary.json", title="Summary", key="metrics.mean"
    )
    pub = Publication(path="paper/paper.pdf", title="Paper")
    evidence_ck = [
        {"kind": "figure", "path": "figures/x.png", "explanation": "shows x"},
        {
            "kind": "result",
            "path": "results/summary.json",
            "key": "metrics.mean",
        },
        {"kind": "publication", "path": "paper/paper.pdf"},
        {"kind": "figure", "path": "figures/missing.png"},
        {"kind": "bogus", "path": "whatever"},  # unknown kind, skipped
        "not-a-dict",  # skipped
    ]
    content = base64.b64encode(
        json.dumps({"metrics": {"mean": 3.14}}).encode()
    ).decode()
    fake_item = ContentsItem(
        name="summary.json",
        path="results/summary.json",
        type="file",
        size=1,
        in_repo=True,
        content=content,
        url=None,
        storage="git",
    )
    with patch(
        "app.api.routes.projects.core.app.projects.get_contents_from_repo",
        return_value=fake_item,
    ):
        evidence = _build_question_evidence(
            project=SimpleNamespace(),  # type: ignore
            repo=SimpleNamespace(),
            ref=None,
            evidence_ck=evidence_ck,
            figures_by_path={fig.path: fig},
            results_by_path={(res.path, res.key): res},
            tables_by_path={},
            publications_by_path={pub.path: pub},
            result_value_cache={},
        )
    assert len(evidence) == 4
    assert evidence[0].kind == "figure"
    assert evidence[0].figure is not None
    assert evidence[0].figure.path == "figures/x.png"
    assert evidence[0].explanation == "shows x"
    assert evidence[1].kind == "result"
    assert evidence[1].result is not None
    assert evidence[1].result.title == "Summary"
    assert evidence[1].key == "metrics.mean"
    # The nested key value is read from the result file and stringified.
    assert evidence[1].value == "3.14"
    assert evidence[2].kind == "publication"
    assert evidence[2].publication is not None
    assert evidence[2].publication.title == "Paper"
    # An unresolved figure path leaves the resolved figure as None.
    assert evidence[3].figure is None


def test_apply_question_update_builds_object() -> None:
    from app.api.routes.projects.core import _apply_question_update
    from app.models.core import QuestionEvidencePost, QuestionPut

    req = QuestionPut(
        question="How does x affect y?",
        hypothesis="linear",
        answer="quadratic",
        evidence=[
            QuestionEvidencePost(
                kind="figure", path="figures/x.png", explanation="shows x"
            ),
            QuestionEvidencePost(
                kind="result", path="results/summary.json", key="mean"
            ),
        ],
    )
    # A bare-string question is promoted to an object with all fields set.
    out = _apply_question_update("old question?", req)
    assert out == {
        "question": "How does x affect y?",
        "hypothesis": "linear",
        "answer": "quadratic",
        "evidence": [
            {
                "kind": "figure",
                "path": "figures/x.png",
                "explanation": "shows x",
            },
            {"kind": "result", "path": "results/summary.json", "key": "mean"},
        ],
    }


def test_apply_question_update_figure_evidence_drops_key() -> None:
    from app.api.routes.projects.core import _apply_question_update
    from app.models.core import QuestionEvidencePost, QuestionPut

    req = QuestionPut(
        evidence=[
            QuestionEvidencePost(
                kind="figure", path="figures/x.png", key="ignored"
            )
        ]
    )
    out = _apply_question_update("q?", req)
    assert isinstance(out, dict)
    assert out["evidence"] == [{"kind": "figure", "path": "figures/x.png"}]


def test_apply_question_update_collapses_to_string_when_cleared() -> None:
    from app.api.routes.projects.core import _apply_question_update
    from app.models.core import QuestionPut

    existing = {
        "question": "q?",
        "hypothesis": "h",
        "answer": "a",
        "evidence": [{"kind": "figure", "path": "x"}],
    }
    # Empty request clears hypothesis/answer/evidence and collapses to a string.
    out = _apply_question_update(existing, QuestionPut())
    assert out == "q?"


def _make_fake_repo(working_dir: str) -> SimpleNamespace:
    """A repo stand-in whose git calls are no-ops but whose working_dir is a
    real temp dir, so route file writes land somewhere we can read back.
    """
    return SimpleNamespace(
        working_dir=working_dir,
        active_branch=SimpleNamespace(name="main"),
        ignored=lambda *a, **k: [],
        git=SimpleNamespace(
            add=lambda *a, **k: None,
            commit=lambda *a, **k: None,
            push=lambda *a, **k: None,
            # Pretend the staged .bib changed, so sync commits.
            diff=lambda *a, **k: "references.bib",
        ),
    )


def test_post_project_zotero_import_whole_collection(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: {},
        ),
        patch(
            "app.api.routes.projects.core.users"
            ".get_zotero_api_key_and_user_id",
            return_value=("KEY", "999"),
        ),
        patch(
            "app.api.routes.projects.core.zotero.get_collection_name",
            return_value="My Collection",
        ),
        patch(
            "app.api.routes.projects.core.zotero.get_collection_items",
            return_value=(
                [
                    {
                        "item_key": "IT1",
                        "bibtex": "@article{a, title={A}}",
                        "data": {},
                        "num_children": 0,
                    }
                ],
                4021,
            ),
        ) as mock_items,
        patch(
            "app.api.routes.projects.core.zotero.build_item_maps",
            return_value=(
                {
                    "a": {
                        "item_key": "IT1",
                        "pdf_attachment_keys": [],
                        "note_keys": [],
                    }
                },
                {},
            ),
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.post(
            f"{base}/zotero/imports",
            headers=headers,
            json={
                "library_type": "user",
                "library_id": "999",
                "collection_key": "ABCD1234",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"] == "references.bib"
    assert body["zotero"]["collection_key"] == "ABCD1234"
    assert body["zotero"]["collection_name"] == "My Collection"
    assert body["zotero"]["last_sync_version"] == 4021
    # Whole-collection mode pulls the existing collection directly.
    assert mock_items.call_args.kwargs["collection_key"] == "ABCD1234"
    assert body["zotero"]["last_synced"]
    # The .bib file was written, reformatted with indentation.
    bib_text = (tmp_path / "references.bib").read_text()
    assert "@article{a," in bib_text
    assert "  title = {A}," in bib_text
    # The item map lands in the gitignored .calkit/zotero/items.json.
    import json as _json

    items_info = _json.loads(
        (tmp_path / ".calkit" / "zotero" / "items.json").read_text()
    )
    assert items_info["references.bib"]["a"]["item_key"] == "IT1"
    # calkit.yaml just lists the path; no Zotero details leak into it.
    ck_info = ryaml.load((tmp_path / "calkit.yaml").read_text())
    assert ck_info["references"][0] == {"path": "references.bib"}
    # The entire private link + sync bookkeeping lands in sync.json.
    import json as _json

    sync_info = _json.loads(
        (tmp_path / ".calkit" / "zotero" / "sync.json").read_text()
    )["references.bib"]
    assert sync_info["library_type"] == "user"
    assert sync_info["library_id"] == "999"
    assert sync_info["collection_key"] == "ABCD1234"
    assert sync_info["collection_name"] == "My Collection"
    assert sync_info["last_sync_version"] == 4021
    assert sync_info["user_id"] == "999"
    assert sync_info["last_synced"]


def test_post_project_zotero_import_subset_creates_collection(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: {},
        ),
        patch(
            "app.api.routes.projects.core.users"
            ".get_zotero_api_key_and_user_id",
            return_value=("KEY", "999"),
        ),
        patch(
            "app.api.routes.projects.core.zotero.create_collection",
            return_value="NEWKEY01",
        ) as mock_create,
        patch(
            "app.api.routes.projects.core.zotero.add_items_to_collection",
        ) as mock_add,
        patch(
            "app.api.routes.projects.core.zotero.get_collection_items",
            return_value=(
                [
                    {
                        "item_key": "IT2",
                        "bibtex": "@book{b, title={B}}",
                        "data": {},
                        "num_children": 0,
                    }
                ],
                5000,
            ),
        ),
        patch(
            "app.api.routes.projects.core.zotero.build_item_maps",
            return_value=({}, {}),
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.post(
            f"{base}/zotero/imports",
            headers=headers,
            json={
                "library_type": "user",
                "library_id": "999",
                "item_keys": ["K1", "K2"],
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    # Subset mode creates a dedicated collection named for the project.
    expected_name = f"Calkit: {owner_name}/{project.name}"
    assert mock_create.call_args.kwargs["name"] == expected_name
    assert mock_add.call_args.kwargs["item_keys"] == ["K1", "K2"]
    assert mock_add.call_args.kwargs["collection_key"] == "NEWKEY01"
    assert body["zotero"]["collection_key"] == "NEWKEY01"
    assert body["zotero"]["collection_name"] == expected_name


def test_post_project_zotero_sync_pulls_collection(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    _write_zotero_link(tmp_path)
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: _zotero_linked_ck_info(),
        ),
        patch(
            "app.api.routes.projects.core.users"
            ".get_zotero_api_key_and_user_id",
            return_value=("KEY", "999"),
        ),
        patch(
            "app.api.routes.projects.core.zotero.get_collection_items",
            return_value=(
                [
                    {
                        "item_key": "IT1",
                        "bibtex": "@article{a, title={A2}}",
                        "data": {},
                        "num_children": 0,
                    }
                ],
                4099,
            ),
        ) as mock_items,
        patch(
            "app.api.routes.projects.core.zotero.get_deleted_item_keys",
            return_value=[],
        ),
        patch(
            "app.api.routes.projects.core.zotero.get_collection_name",
            return_value="My Collection",
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.post(
            f"{base}/zotero/syncs",
            headers=headers,
            json={"path": "references.bib"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["last_sync_version"] == 4099
    assert body["committed"] is True
    assert mock_items.call_args.kwargs["collection_key"] == "ABCD1234"
    bib_text = (tmp_path / "references.bib").read_text()
    assert "@article{a," in bib_text
    assert "  title = {A2}," in bib_text


def test_post_project_zotero_sync_requires_link(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: {"references": [{"path": "x.bib"}]},
        ),
        patch(
            "app.api.routes.projects.core.users"
            ".get_zotero_api_key_and_user_id",
            return_value=("KEY", "999"),
        ),
    ):
        r = client.post(
            f"{base}/zotero/syncs",
            headers=headers,
            json={"path": "x.bib"},
        )
    assert r.status_code == 404


def _zotero_linked_ck_info() -> dict:
    return {"references": [{"path": "references.bib"}]}


def _write_zotero_link(
    tmp_path, path: str = "references.bib", last_sync_version: int = 5
) -> None:
    """Seed the private Zotero link in .calkit/zotero/sync.json for a test."""
    zotero.write_sync_info(
        str(tmp_path),
        {
            path: {
                "library_type": "user",
                "library_id": "999",
                "collection_key": "ABCD1234",
                "collection_name": "My Collection",
                "user_id": "999",
                "last_sync_version": last_sync_version,
                "last_synced": "2020-01-01T00:00:00",
            }
        },
    )


def test_get_project_zotero_item_pdf(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    # An items map with a PDF attachment for citekey "a".
    zotero.write_items_info(
        str(tmp_path),
        {
            "references.bib": {
                "a": {
                    "item_key": "IT1",
                    "pdf_attachment_keys": ["ATT1"],
                    "note_keys": [],
                }
            }
        },
    )
    _write_zotero_link(tmp_path)
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: _zotero_linked_ck_info(),
        ),
        patch(
            "app.api.routes.projects.core.users"
            ".get_zotero_api_key_and_user_id",
            return_value=("KEY", "999"),
        ),
        patch(
            "app.api.routes.projects.core.zotero.stream_attachment",
            return_value=(iter([b"%PDF-1.4 fake"]), "application/pdf", "13"),
        ) as mock_dl,
    ):
        r = client.get(
            f"{base}/zotero/items/a/pdf?path=references.bib",
            headers=headers,
        )
        # A citekey with no PDF attachment 404s.
        r2 = client.get(
            f"{base}/zotero/items/missing/pdf?path=references.bib",
            headers=headers,
        )
        # A negative index is rejected rather than wrapping to the last one.
        r3 = client.get(
            f"{base}/zotero/items/a/pdf?path=references.bib&index=-1",
            headers=headers,
        )
    assert r.status_code == 200, r.text
    assert r.content == b"%PDF-1.4 fake"
    assert r.headers["content-type"] == "application/pdf"
    assert mock_dl.call_args.kwargs["attachment_key"] == "ATT1"
    assert r2.status_code == 404
    assert r3.status_code == 422


def test_put_project_zotero_item_notes(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    (tmp_path / "references.bib").write_text(
        "@article{a,\n  title = {A},\n}\n"
    )
    zotero.write_items_info(
        str(tmp_path),
        {
            "references.bib": {
                "a": {
                    "item_key": "IT1",
                    "pdf_attachment_keys": [],
                    "note_keys": ["N1"],
                }
            }
        },
    )
    _write_zotero_link(tmp_path)
    # Zotero currently has one note child; positional sync updates it and
    # creates a second for the extra note.
    existing_children = [
        {
            "key": "N1",
            "version": 3,
            "data": {"itemType": "note", "note": "<p>old</p>"},
        }
    ]
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: _zotero_linked_ck_info(),
        ),
        patch(
            "app.api.routes.projects.core.users"
            ".get_zotero_api_key_and_user_id",
            return_value=("KEY", "999"),
        ),
        patch(
            "app.api.routes.projects.core.zotero.update_note"
        ) as mock_update,
        patch(
            "app.api.routes.projects.core.zotero.create_note"
        ) as mock_create,
        patch(
            "app.api.routes.projects.core.zotero.get_item_children",
            return_value=existing_children,
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.put(
            f"{base}/references/items/a/notes",
            headers=headers,
            json={
                "path": "references.bib",
                "notes": [
                    {"text": "updated"},
                    {"text": "brand new"},
                ],
            },
        )
    assert r.status_code == 200, r.text
    # Both notes land in the .bib comment field, separated by a rule.
    bib_text = (tmp_path / "references.bib").read_text()
    assert "updated" in bib_text
    assert "---" in bib_text
    assert "brand new" in bib_text
    # Positional sync: the existing note is updated, the extra one created.
    assert mock_update.call_args.kwargs["note_key"] == "N1"
    assert mock_update.call_args.kwargs["html"] == "<p>updated</p>"
    assert mock_create.call_args.kwargs["html"] == "<p>brand new</p>"


def test_get_project_reference_notes_from_comment(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    (tmp_path / "references.bib").write_text(
        "@article{a,\n  comment = {first note\n\n---\n\nsecond note},\n}\n"
    )
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
    ):
        r = client.get(
            f"{base}/references/items/a/notes?path=references.bib",
            headers=headers,
        )
    assert r.status_code == 200, r.text
    notes = r.json()["notes"]
    assert [n["text"] for n in notes] == ["first note", "second note"]


def test_reference_note_highlight_round_trip(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    (tmp_path / "references.bib").write_text(
        "@article{a,\n  title = {A},\n}\n"
    )
    position = {"pageNumber": 2, "boundingRect": {"x1": 1.0, "y1": 2.0}}
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: {
                "references": [{"path": "references.bib"}]
            },
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.put(
            f"{base}/references/items/a/notes",
            headers=headers,
            json={
                "path": "references.bib",
                "notes": [
                    {
                        "text": "a note on this passage",
                        "highlight": {
                            "position": position,
                            "quote": "the highlighted text",
                        },
                    },
                    {"text": "a plain note"},
                ],
            },
        )
        assert r.status_code == 200, r.text
        # The anchor is encoded in the .bib comment as an HTML comment.
        bib_text = (tmp_path / "references.bib").read_text()
        assert "<!-- calkit-highlight:" in bib_text
        assert "> the highlighted text" in bib_text
        # Reading it back reconstructs the highlight.
        r = client.get(
            f"{base}/references/items/a/notes?path=references.bib",
            headers=headers,
        )
    assert r.status_code == 200, r.text
    notes = r.json()["notes"]
    assert notes[0]["highlight"]["position"] == position
    assert notes[0]["highlight"]["quote"] == "the highlighted text"
    assert notes[0]["text"] == "a note on this passage"
    assert notes[1]["highlight"] is None


def test_reference_notes_non_linked_use_comment_field(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    # A plain .bib with no Zotero link.
    (tmp_path / "references.bib").write_text(
        "@article{smith2020,\n  title = {A Title},\n}\n"
    )
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: {
                "references": [{"path": "references.bib"}]
            },
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        # Initially no note.
        r = client.get(
            f"{base}/references/items/smith2020/notes?path=references.bib",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["notes"] == []
        # Save a note -> written to the BibTeX comment field.
        r = client.put(
            f"{base}/references/items/smith2020/notes",
            headers=headers,
            json={
                "path": "references.bib",
                "notes": [{"text": "My private note"}],
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["notes"][0]["text"] == "My private note"
    bib_text = (tmp_path / "references.bib").read_text()
    assert "comment = {My private note}," in bib_text


def test_format_bib_indents_and_wraps() -> None:
    raw = (
        "@article{k, title={"
        + "word " * 40
        + "}, journal={Nature}, year=2020}"
    )
    out = zotero.format_bib(raw)
    assert "@article{k," in out
    assert "  journal = {Nature}," in out
    assert all(len(line) <= 80 for line in out.splitlines())


def test_latex_to_text_strips_markup_for_zotero() -> None:
    # Protective braces and escaped braces (from a Zotero round-trip) must
    # reduce to plain text, so we never push LaTeX back to Zotero.
    assert zotero.latex_to_text("{2D} {CFD} simulation") == "2D CFD simulation"
    assert (
        zotero.latex_to_text("A title for \\{{Cool}\\}") == "A title for Cool"
    )


def test_zotero_notes_to_local_reattaches_anchors() -> None:
    # A pulled Zotero note whose key has a stored anchor gets the anchor back,
    # and the blockquote mirroring the quote is stripped to avoid duplication.
    notes = [
        {
            "key": "N1",
            "html": "<blockquote><p>the quote</p></blockquote><p>body</p>",
        },
        {"key": "N2", "html": "<p>plain</p>"},
    ]
    anchors = {"N1": {"position": {"pageNumber": 1}, "quote": "the quote"}}
    result = zotero.zotero_notes_to_local(notes, anchors)
    assert result[0]["highlight"] == anchors["N1"]
    assert result[0]["text"] == "body"
    assert result[1]["highlight"] is None
    assert result[1]["text"] == "plain"


def test_apply_bibtex_fields_sends_plain_text() -> None:
    template = {"title": "", "creators": [{"creatorType": "author"}]}
    item = dict(template)
    zotero._apply_bibtex_fields(
        item, template, {"title": "{2D} {CFD}", "author": "Doe, Jane"}
    )
    assert item["title"] == "2D CFD"
    assert item["creators"] == [
        {"creatorType": "author", "firstName": "Jane", "lastName": "Doe"}
    ]


def test_apply_bibtex_fields_partial_update_keeps_creators() -> None:
    # An update that doesn't include author/editor must not wipe existing
    # creators (a partial PATCH shouldn't clobber unspecified fields).
    template = {
        "title": "",
        "date": "",
        "creators": [{"creatorType": "author"}],
    }
    item = {"creators": [{"creatorType": "author", "lastName": "Existing"}]}
    zotero._apply_bibtex_fields(item, template, {"year": "2020"})
    assert item["creators"] == [
        {"creatorType": "author", "lastName": "Existing"}
    ]
    assert item["date"] == "2020"


def test_format_bib_is_idempotent() -> None:
    # Reformatting an already-formatted .bib must not change it: no de-indenting
    # wrapped values and no flipping field order (which would churn diffs).
    raw = (
        "@article{k,\n"
        "  year = {2020},\n"
        "  title = {" + "word " * 40 + "},\n"
        "  comment = {A note.\n\nAnother note.},\n"
        "  author = {Doe, Jane and Roe, Richard},\n"
        "}\n"
    )
    once = zotero.format_bib(raw)
    twice = zotero.format_bib(once)
    assert once == twice
    # Source field order is preserved (year, title, comment, author).
    field_lines = [
        ln.split("=")[0].strip() for ln in once.splitlines() if " = {" in ln
    ]
    assert field_lines == ["year", "title", "comment", "author"]
    # The multi-line comment/note stays verbatim.
    assert "A note.\n\nAnother note." in once


def test_post_and_put_reference_item(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    # An existing entry with a note in its comment field.
    (tmp_path / "references.bib").write_text(
        "@article{old,\n  title = {Old Title},\n  comment = {my note},\n}\n"
    )
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        # Add a new entry.
        r = client.post(
            f"{base}/references/items",
            headers=headers,
            json={
                "path": "references.bib",
                "type": "book",
                "key": "smith2020",
                "fields": {"title": "A Book", "year": "2020"},
            },
        )
        assert r.status_code == 200, r.text
        text = (tmp_path / "references.bib").read_text()
        assert "@book{smith2020," in text
        assert "  title = {A Book}," in text
        # Adding a duplicate key conflicts.
        r = client.post(
            f"{base}/references/items",
            headers=headers,
            json={
                "path": "references.bib",
                "key": "smith2020",
                "fields": {"title": "Another"},
            },
        )
        assert r.status_code == 409
        # Edit the original entry, renaming its key and a field; its note
        # (comment) must survive.
        r = client.put(
            f"{base}/references/items/old",
            headers=headers,
            json={
                "path": "references.bib",
                "type": "article",
                "key": "older",
                "fields": {"title": "New Title"},
            },
        )
    assert r.status_code == 200, r.text
    text = (tmp_path / "references.bib").read_text()
    assert "@article{older," in text
    assert "  title = {New Title}," in text
    assert "comment = {my note}" in text
    assert "@article{old," not in text


def test_put_reference_item_no_change_does_not_error(
    client: TestClient, db: Session, tmp_path
) -> None:
    # Re-saving an entry with identical fields leaves the tree clean; the route
    # must skip the commit rather than 500 on an empty commit.
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    fake_repo.git.diff = lambda *a, **k: ""  # nothing staged -> no commit
    (tmp_path / "references.bib").write_text(
        "@article{same,\n  title = {Same},\n}\n"
    )
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.put(
            f"{base}/references/items/same",
            headers=headers,
            json={
                "path": "references.bib",
                "type": "article",
                "key": "same",
                "fields": {"title": "Same"},
            },
        )
    assert r.status_code == 200, r.text


def test_delete_project_reference_item(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    (tmp_path / "references.bib").write_text(
        "@article{keep,\n  title = {Keep},\n}\n\n"
        "@article{drop,\n  title = {Drop},\n}\n"
    )
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        # Deleting a missing entry 404s.
        r_missing = client.delete(
            f"{base}/references/items/nope?path=references.bib",
            headers=headers,
        )
        r = client.delete(
            f"{base}/references/items/drop?path=references.bib",
            headers=headers,
        )
    assert r_missing.status_code == 404
    assert r.status_code == 200, r.text
    text = (tmp_path / "references.bib").read_text()
    assert "@article{keep," in text
    assert "@article{drop," not in text


def test_add_reference_creates_zotero_item_when_linked(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    (tmp_path / "references.bib").write_text("")
    _write_zotero_link(tmp_path)
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: _zotero_linked_ck_info(),
        ),
        patch(
            "app.api.routes.projects.core.users"
            ".get_zotero_api_key_and_user_id",
            return_value=("KEY", "999"),
        ),
        patch(
            "app.api.routes.projects.core.zotero.create_item",
            return_value="IT_NEW",
        ) as mock_create,
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.post(
            f"{base}/references/items",
            headers=headers,
            json={
                "path": "references.bib",
                "type": "article",
                "key": "supercool2020",
                "fields": {"title": "Cool"},
            },
        )
    assert r.status_code == 200, r.text
    assert mock_create.call_args.kwargs["collection_key"] == "ABCD1234"
    # The mapping is recorded under the user's local key, which the .bib keeps.
    items = zotero.read_items_info(str(tmp_path))
    assert items["references.bib"]["supercool2020"]["item_key"] == "IT_NEW"
    assert (
        "@article{supercool2020," in (tmp_path / "references.bib").read_text()
    )


def test_delete_reference_deletes_zotero_item_when_linked(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    (tmp_path / "references.bib").write_text(
        "@article{gone,\n  title = {Gone},\n}\n"
    )
    zotero.write_items_info(
        str(tmp_path), {"references.bib": {"gone": {"item_key": "IT_GONE"}}}
    )
    _write_zotero_link(tmp_path)
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: _zotero_linked_ck_info(),
        ),
        patch(
            "app.api.routes.projects.core.users"
            ".get_zotero_api_key_and_user_id",
            return_value=("KEY", "999"),
        ),
        patch(
            "app.api.routes.projects.core.zotero.delete_item"
        ) as mock_delete,
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.delete(
            f"{base}/references/items/gone?path=references.bib",
            headers=headers,
        )
    assert r.status_code == 200, r.text
    assert mock_delete.call_args.kwargs["item_key"] == "IT_GONE"
    items = zotero.read_items_info(str(tmp_path))
    assert "gone" not in items.get("references.bib", {})


def test_zotero_sync_merges_changes_per_item(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    # A locally-keyed entry mapped to a Zotero item, plus one to be deleted.
    (tmp_path / "references.bib").write_text(
        "@article{localkey,\n  title = {Old Title},\n}\n\n"
        "@article{stale,\n  title = {To Delete},\n}\n"
    )
    zotero.write_items_info(
        str(tmp_path),
        {
            "references.bib": {
                "localkey": {"item_key": "IT1"},
                "stale": {"item_key": "IT2"},
            }
        },
    )
    _write_zotero_link(tmp_path)
    changed = [
        {
            "item_key": "IT1",
            "bibtex": "@article{zkey,\n  title = {New Title}\n}",
            "data": {},
            "num_children": 0,
        }
    ]
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: _zotero_linked_ck_info(),
        ),
        patch(
            "app.api.routes.projects.core.users"
            ".get_zotero_api_key_and_user_id",
            return_value=("KEY", "999"),
        ),
        patch(
            "app.api.routes.projects.core.zotero.get_collection_items",
            return_value=(changed, 9),
        ),
        patch(
            "app.api.routes.projects.core.zotero.get_deleted_item_keys",
            return_value=["IT2"],
        ),
        patch(
            "app.api.routes.projects.core.zotero.get_collection_name",
            return_value="My Collection",
        ),
        patch(
            "app.api.routes.projects.core.zotero.build_item_info",
            return_value=(
                {
                    "item_key": "IT1",
                    "pdf_attachment_keys": [],
                    "note_keys": [],
                },
                [],
            ),
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.post(
            f"{base}/zotero/syncs",
            headers=headers,
            json={"path": "references.bib"},
        )
    assert r.status_code == 200, r.text
    text = (tmp_path / "references.bib").read_text()
    # The changed item is updated in place under the local key (not Zotero's).
    assert "@article{localkey," in text
    assert "New Title" in text
    assert "zkey" not in text
    # The item deleted on Zotero is removed locally.
    assert "@article{stale," not in text


def test_zotero_sync_pulls_note_edits(
    client: TestClient, db: Session, tmp_path
) -> None:
    # A note edited on Zotero changes only the note child item (the parent's
    # version is untouched), so sync must still refresh the parent's notes.
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    (tmp_path / "references.bib").write_text(
        "@article{localkey,\n  title = {T},\n  comment = {Old note},\n}\n"
    )
    zotero.write_items_info(
        str(tmp_path),
        {
            "references.bib": {
                "localkey": {"item_key": "IT1", "note_keys": ["NOTE1"]}
            }
        },
    )
    _write_zotero_link(tmp_path)
    # The note carries a highlight anchor Zotero can't store, kept by note key.
    zotero.write_note_anchors(
        str(tmp_path),
        {"NOTE1": {"position": {"pageNumber": 1}, "quote": "ctx"}},
    )
    # Only the note child comes back changed (no top-level bibtex).
    changed = [
        {
            "item_key": "NOTE1",
            "bibtex": "",
            "data": {"parentItem": "IT1", "itemType": "note"},
            "num_children": 0,
        }
    ]
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: _zotero_linked_ck_info(),
        ),
        patch(
            "app.api.routes.projects.core.users"
            ".get_zotero_api_key_and_user_id",
            return_value=("KEY", "999"),
        ),
        patch(
            "app.api.routes.projects.core.zotero.get_collection_items",
            return_value=(changed, 9),
        ),
        patch(
            "app.api.routes.projects.core.zotero.get_deleted_item_keys",
            return_value=[],
        ),
        patch(
            "app.api.routes.projects.core.zotero.get_collection_name",
            return_value="My Collection",
        ),
        patch(
            "app.api.routes.projects.core.zotero.build_item_info",
            return_value=(
                {
                    "item_key": "IT1",
                    "pdf_attachment_keys": [],
                    "note_keys": ["NOTE1"],
                },
                [{"key": "NOTE1", "html": "<p>Updated note</p>"}],
            ),
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.post(
            f"{base}/zotero/syncs",
            headers=headers,
            json={"path": "references.bib"},
        )
    assert r.status_code == 200, r.text
    text = (tmp_path / "references.bib").read_text()
    assert "Updated note" in text
    assert "Old note" not in text
    # The highlight anchor survives the sync (re-attached by note key).
    assert "calkit-highlight" in text


def test_post_project_zotero_import_rejects_both_modes(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.users"
            ".get_zotero_api_key_and_user_id",
            return_value=("KEY", "999"),
        ),
    ):
        r = client.post(
            f"{base}/zotero/imports",
            headers=headers,
            json={
                "library_type": "user",
                "library_id": "999",
                "collection_key": "ABCD1234",
                "item_keys": ["K1"],
            },
        )
    assert r.status_code == 422


def test_post_project_zotero_import_conflict_then_overwrite(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    # A .bib already present on disk.
    (tmp_path / "references.bib").write_text("@article{old}\n")
    body = {
        "library_type": "user",
        "library_id": "999",
        "collection_key": "ABCD1234",
    }
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: {},
        ),
        patch(
            "app.api.routes.projects.core.users"
            ".get_zotero_api_key_and_user_id",
            return_value=("KEY", "999"),
        ),
        patch(
            "app.api.routes.projects.core.zotero.get_collection_name",
            return_value="My Collection",
        ),
        patch(
            "app.api.routes.projects.core.zotero.get_collection_items",
            return_value=(
                [
                    {
                        "item_key": "IT1",
                        "bibtex": "@article{new, title={New}}",
                        "data": {},
                        "num_children": 0,
                    }
                ],
                7,
            ),
        ) as mock_items,
        patch(
            "app.api.routes.projects.core.zotero.build_item_maps",
            return_value=({}, {}),
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        # Without overwrite, the existing file blocks the import, and we never
        # reach Zotero.
        r = client.post(f"{base}/zotero/imports", headers=headers, json=body)
        assert r.status_code == 409, r.text
        assert mock_items.call_count == 0
        # With overwrite, it replaces the file.
        r = client.post(
            f"{base}/zotero/imports",
            headers=headers,
            json={**body, "overwrite": True},
        )
    assert r.status_code == 200, r.text
    assert "@article{new," in (tmp_path / "references.bib").read_text()


def test_post_project_references_creates_collection(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: {},
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.post(
            f"{base}/references",
            headers=headers,
            json={"path": "refs/lit.bib"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["path"] == "refs/lit.bib"
    assert (tmp_path / "refs" / "lit.bib").is_file()
    ck_info = ryaml.load((tmp_path / "calkit.yaml").read_text())
    assert ck_info["references"] == [{"path": "refs/lit.bib"}]


def test_post_project_references_existing_path_conflicts(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    # A file on disk that isn't declared in calkit.yaml, alongside an empty
    # "references:" key, which parses to None. Creating over it must 409, not
    # 500 on the None.
    (tmp_path / "references.bib").write_text("@article{x}\n")
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: {"references": None},
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.post(
            f"{base}/references",
            headers=headers,
            json={"path": "references.bib"},
        )
    assert r.status_code == 409, r.text


def test_post_project_references_labels_existing_file(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    # An existing .bib file that isn't yet declared in calkit.yaml.
    (tmp_path / "references.bib").write_text("@article{x}\n")
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: {},
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.post(
            f"{base}/references",
            headers=headers,
            json={"path": "references.bib", "label_existing": True},
        )
    assert r.status_code == 200, r.text
    # The file is preserved (not blanked out) and registered.
    assert (tmp_path / "references.bib").read_text() == "@article{x}\n"
    ck_info = ryaml.load((tmp_path / "calkit.yaml").read_text())
    assert ck_info["references"] == [{"path": "references.bib"}]


def test_post_project_references_label_existing_missing_file(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: {},
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.post(
            f"{base}/references",
            headers=headers,
            json={"path": "missing.bib", "label_existing": True},
        )
    assert r.status_code == 404, r.text


def test_delete_project_references_collection(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    (tmp_path / "references.bib").write_text(
        "@article{a,\n  title = {A},\n}\n"
    )
    zotero.write_items_info(
        str(tmp_path),
        {"references.bib": {"a": {"item_key": "IT1", "note_keys": ["N1"]}}},
    )
    zotero.write_note_anchors(
        str(tmp_path), {"N1": {"position": {"pageNumber": 1}, "quote": "q"}}
    )
    _write_zotero_link(tmp_path)
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: {
                "references": [{"path": "references.bib"}]
            },
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.delete(
            f"{base}/references?path=references.bib", headers=headers
        )
    assert r.status_code == 200, r.text
    # The .bib, its calkit.yaml entry, and all Zotero state are gone.
    assert not (tmp_path / "references.bib").exists()
    ck_info = ryaml.load((tmp_path / "calkit.yaml").read_text())
    assert ck_info["references"] == []
    assert "references.bib" not in zotero.read_items_info(str(tmp_path))
    assert "references.bib" not in zotero.read_sync_info(str(tmp_path))
    assert "N1" not in zotero.read_note_anchors(str(tmp_path))


def test_delete_project_references_collection_missing(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    fake_repo = _make_fake_repo(str(tmp_path))
    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=lambda *a, **k: {"references": []},
        ),
        patch("app.api.routes.projects.core.mixpanel.track"),
    ):
        r = client.delete(f"{base}/references?path=nope.bib", headers=headers)
    assert r.status_code == 404, r.text


def _make_stage_repo(working_dir: str, dirty: bool = True) -> SimpleNamespace:
    """A repo stand-in for the pipeline stage routes.

    Like _make_fake_repo, but with the is_dirty() the stage PUT checks
    before committing.
    """
    repo = _make_fake_repo(working_dir)
    repo.is_dirty = lambda *a, **k: dirty
    return repo


def test_project_pipeline_stage_edit(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    owner_name = project.owner_account.name
    base = f"{settings.API_V1_STR}/projects/{owner_name}/{project.name}"
    stages_url = f"{base}/pipeline/stages"
    fake_repo = _make_stage_repo(str(tmp_path))
    # A paper whose class file is only discoverable by reading the source,
    # plus a style file the class itself pulls in and a figure directory
    (tmp_path / "paper").mkdir()
    (tmp_path / "paper" / "figures").mkdir()
    (tmp_path / "paper" / "figures" / "fig.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "paper" / "paper.tex").write_text(
        "\\documentclass{jfm}\n"
        "\\usepackage{graphicx}\n"
        "% \\usepackage{commented}\n"
        "\\includegraphics{figures/fig}\n"
        "\\begin{document}\\end{document}\n"
    )
    (tmp_path / "paper" / "jfm.cls").write_text("\\usepackage{upmath}\n")
    (tmp_path / "paper" / "upmath.sty").write_text("% nothing\n")
    (tmp_path / "paper" / "commented.sty").write_text("% nothing\n")
    # As written by an older Calkit: optional fields spelled out as nulls,
    # and target_path deliberately last so ordering is observable
    stage_yaml = (
        "kind: latex\n"
        "environment: tex\n"
        "wdir: null\n"
        "iterate_over: null\n"
        "always_run: false\n"
        "outputs:\n"
        "  - paper/paper.pdf\n"
        "target_path: paper/paper.tex\n"
    )
    ck_info = {"pipeline": {"stages": {"paper": ryaml.load(stage_yaml)}}}

    def fake_ck_info(*args, **kwargs) -> dict:
        return ck_info

    with (
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.get_ck_info_from_repo",
            side_effect=fake_ck_info,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            side_effect=fake_ck_info,
        ),
        # Saving recompiles dvc.yaml from the whole project, which this
        # stand-in repo can't support; the compile has its own tests
        patch("app.api.routes.projects.core.calkit.pipeline.to_dvc"),
    ):
        # Reading a stage hands it back as written: nothing reordered and
        # nothing removed, since tidying is the user's call
        r = client.get(f"{stages_url}/paper", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "paper"
        as_written = r.json()["yaml"]
        assert list(ryaml.load(as_written)) == [
            "kind",
            "environment",
            "wdir",
            "iterate_over",
            "always_run",
            "outputs",
            "target_path",
        ]
        # A stage that doesn't exist is a 404, not an empty editor
        r404 = client.get(f"{stages_url}/nope", headers=headers)
        assert r404.status_code == 404
        # Detection finds the class file and what the class itself loads,
        # skipping TeX Live packages and commented-out ones
        r = client.post(
            f"{stages_url}/paper/detect-inputs",
            headers=headers,
            json={"yaml": as_written},
        )
        assert r.status_code == 200, r.text
        assert r.json()["changed"] == [
            "paper/figures/fig.pdf",
            "paper/jfm.cls",
            "paper/upmath.sty",
        ]
        detected_yaml = r.json()["yaml"]
        # The keys that were there keep their order; inputs is appended
        assert list(ryaml.load(detected_yaml))[:7] == [
            "kind",
            "environment",
            "wdir",
            "iterate_over",
            "always_run",
            "outputs",
            "target_path",
        ]
        # Detecting again adds nothing
        r2 = client.post(
            f"{stages_url}/paper/detect-inputs",
            headers=headers,
            json={"yaml": detected_yaml},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["changed"] == []
        # A declared directory covers the figures inside it, so they are
        # not listed individually
        r3 = client.post(
            f"{stages_url}/paper/detect-inputs",
            headers=headers,
            json={
                "yaml": (
                    "kind: latex\nenvironment: tex\n"
                    "target_path: paper/paper.tex\n"
                    "inputs:\n  - paper/figures\n"
                )
            },
        )
        assert r3.status_code == 200, r3.text
        assert r3.json()["changed"] == ["paper/jfm.cls", "paper/upmath.sty"]
        # Removing defaults drops exactly the keys left at their default,
        # leaving the rest where they were
        r = client.post(
            f"{stages_url}/paper/remove-defaults",
            headers=headers,
            json={"yaml": as_written},
        )
        assert r.status_code == 200, r.text
        assert r.json()["changed"] == ["wdir", "iterate_over", "always_run"]
        assert list(ryaml.load(r.json()["yaml"])) == [
            "kind",
            "environment",
            "outputs",
            "target_path",
        ]
        # Saving writes what the user has, untouched apart from validation
        r = client.put(
            f"{stages_url}/paper",
            headers=headers,
            json={"yaml": detected_yaml, "message": "Declare the class file"},
        )
        assert r.status_code == 200, r.text
        written = ryaml.load((tmp_path / "calkit.yaml").read_text())
        saved = written["pipeline"]["stages"]["paper"]
        assert list(saved) == [
            "kind",
            "environment",
            "wdir",
            "iterate_over",
            "always_run",
            "outputs",
            "target_path",
            "inputs",
        ]
        assert saved["inputs"] == [
            "paper/figures/fig.pdf",
            "paper/jfm.cls",
            "paper/upmath.sty",
        ]
        # Bad YAML, an unknown kind, and a missing required field are all
        # rejected before anything is written
        for bad in [
            "kind: latex\n  bad indent: true\n",
            "kind: not-a-real-kind\nenvironment: tex\n",
            "kind: latex\nenvironment: tex\n",  # no target_path
        ]:
            r = client.put(
                f"{stages_url}/paper", headers=headers, json={"yaml": bad}
            )
            assert r.status_code == 422, f"{bad!r} -> {r.status_code}"
        # Detection is meaningless for a stage that isn't a document
        r = client.post(
            f"{stages_url}/paper/detect-inputs",
            headers=headers,
            json={
                "yaml": (
                    "kind: python-script\nenvironment: py\n"
                    "script_path: scripts/go.py\n"
                )
            },
        )
        assert r.status_code == 422, r.text
        # Neither wdir nor target_path may point outside the project, since
        # both come off the request body and are used to read files
        for escaping in [
            "kind: latex\nenvironment: tex\nwdir: ../..\n"
            "target_path: paper.tex\n",
            "kind: latex\nenvironment: tex\n"
            "target_path: ../../../etc/passwd\n",
        ]:
            r = client.post(
                f"{stages_url}/paper/detect-inputs",
                headers=headers,
                json={"yaml": escaping},
            )
            assert r.status_code == 422, f"{escaping!r} -> {r.status_code}"
        # A stage still using the legacy `slurm:` spelling keeps it: it is
        # renamed to `scheduler:` on load, so it isn't a default to drop, and
        # dropping it would delete the scheduler config outright
        r = client.post(
            f"{stages_url}/paper/remove-defaults",
            headers=headers,
            json={
                "yaml": (
                    "kind: shell-command\nenvironment: tex\n"
                    "command: echo hi\nwdir: null\n"
                    "slurm:\n  account: abc\n  time: '01:00:00'\n"
                )
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["changed"] == ["wdir"]
        assert "slurm" in ryaml.load(r.json()["yaml"])


def test_normalize_artifact_file_path_rejects_out_of_repo_paths() -> None:
    # A declared path is joined onto the repo's working dir and written to,
    # so anything that could resolve outside the project is refused
    assert (
        _normalize_artifact_file_path("./paper/main.pdf") == "paper/main.pdf"
    )
    assert (
        _normalize_artifact_file_path("figures//plot.png")
        == "figures/plot.png"
    )
    assert _normalize_artifact_file_path("paper/../figures/plot.png") == (
        "figures/plot.png"
    )
    for path in ["", ".", "./", "/tmp/x", "../../etc/passwd", "paper/../.."]:
        with pytest.raises(HTTPException) as exc_info:
            _normalize_artifact_file_path(path)
        assert exc_info.value.status_code == 400, path


def test_get_project_apps(client: TestClient) -> None:
    fake_project = SimpleNamespace()
    ck_info = {
        "apps": {
            "naca0012": {
                "kind": "static-html",
                "path": "app/index.html",
                "title": "NACA 0012 explorer",
                "stage": "build-app",
            },
            # A kind we don't serve shouldn't hide the ones we do
            "other": {"kind": "something-else", "path": "x/index.html"},
        }
    }
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value=ck_info,
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/apps"
        )
    assert response.status_code == 200
    apps = {a["name"]: a for a in response.json()}
    assert list(apps) == ["naca0012"]
    # The URL is ours and derived, never read from calkit.yaml
    assert apps["naca0012"]["url"] == (
        f"{settings.API_V1_STR}/projects/test-owner/test-project"
        "/apps/naca0012/serve/"
    )
    assert apps["naca0012"]["path"] == "app/index.html"
    assert apps["naca0012"]["stage"] == "build-app"
    # The old singular key named a URL hosted elsewhere for us to embed,
    # which we no longer do, so it yields nothing
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={"app": {"url": "https://old.hf.space"}},
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/apps"
        )
    assert response.status_code == 200
    assert response.json() == []
    # A project with no apps returns an empty list rather than erroring
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={},
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/apps"
        )
    assert response.status_code == 200
    assert response.json() == []


def test_get_project_apps_skips_unusable_paths(client: TestClient) -> None:
    fake_project = SimpleNamespace()
    ck_info = {
        "apps": {
            # The declared path becomes a serving root that file reads join
            # onto, so one that escapes the project is dropped rather than
            # served, and doesn't take the valid apps with it
            "escape": {"path": "../../../etc/passwd.html"},
            "absolute": {"path": "/etc/passwd.html"},
            "not-html": {"path": "app/data.csv"},
            "no-path": {"title": "Nothing to serve"},
            "good": {"path": "./app/index.html"},
        }
    }
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value=ck_info,
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/apps"
        )
    assert response.status_code == 200
    apps = response.json()
    assert [a["name"] for a in apps] == ["good"]
    # Declared paths come back normalized, the way they're keyed everywhere
    assert apps[0]["path"] == "app/index.html"


def test_serve_project_app_file(client: TestClient) -> None:
    ck_info = {"apps": {"myapp": {"path": "app/index.html"}}}
    base = f"{settings.API_V1_STR}/projects/test-owner/test-project"

    def get(path: str, is_public: bool = True):
        with (
            patch(
                "app.api.routes.projects.core.app.projects.get_project",
                return_value=SimpleNamespace(is_public=is_public),
            ),
            patch(
                "app.api.routes.projects.core.get_repo",
                return_value=SimpleNamespace(),
            ),
            patch(
                "app.api.routes.projects.core.app.projects."
                "get_ck_info_for_ref",
                return_value=ck_info,
            ),
            patch(
                "app.api.routes.projects.core.app.projects.read_app_file",
                side_effect=lambda **kwargs: (
                    f"bytes:{kwargs['rel_path']}".encode()
                ),
            ) as mock_read,
        ):
            return client.get(path, follow_redirects=False), mock_read

    # No path serves the declared entrypoint, out of its own directory
    response, mock_read = get(f"{base}/apps/myapp/serve")
    assert response.status_code == 200
    assert response.content == b"bytes:index.html"
    assert mock_read.call_args.kwargs["dir_path"] == "app"
    assert response.headers["content-type"].startswith("text/html")
    # Project-supplied bytes, so the browser doesn't get to second-guess the
    # type, and a public project's app is cacheable by anyone
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "public, max-age=300"
    # An asset resolves relative to the entrypoint's directory, and WASM has
    # to be typed exactly or the browser won't stream-compile it
    response, _ = get(f"{base}/apps/myapp/serve/assets/pyodide.wasm")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/wasm"
    # Access is gated on a read check, so a shared cache must not hold a
    # private project's app and hand it to somebody we'd have refused
    response, _ = get(f"{base}/apps/myapp/serve", is_public=False)
    assert response.headers["cache-control"] == "private, max-age=300"
    # A pinned commit can never change what it returns
    sha = "0" * 40
    response, _ = get(f"{base}/apps/myapp/{sha}/serve/index.html")
    assert response.status_code == 200
    assert response.headers["cache-control"] == (
        "public, max-age=31536000, immutable"
    )
    # Nothing may climb out of the app's directory
    for bad in ["../../../etc/passwd", "assets/../../../etc/passwd"]:
        response, _ = get(f"{base}/apps/myapp/serve/{bad}")
        assert response.status_code == 404, bad
    # An app that isn't declared isn't served
    response, _ = get(f"{base}/apps/nope/serve")
    assert response.status_code == 404


def test_get_project_notebooks_finds_marimo_notebook(
    client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import git

    import app.projects

    monkeypatch.setattr(
        app.projects, "expand_dvc_lock_outs", lambda *a, **k: {}
    )
    repo_dir = tmp_path / "repo"
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])
    # The shape petebachant/nacafoil-openfoam uses: a marimo notebook named
    # only by the pipeline, with no `notebooks` section
    (repo_dir / "calkit.yaml").write_text(
        "pipeline:\n"
        "  stages:\n"
        "    app:\n"
        "      kind: marimo-html-wasm\n"
        "      environment: py\n"
        "      notebook_path: notebook.py\n"
        "      output_dir: app\n"
        "apps:\n"
        "  naca0012:\n"
        "    kind: static-html\n"
        "    path: app/index.html\n"
        "    stage: app\n"
    )
    (repo_dir / "notebook.py").write_text(
        'import marimo\n__generated_with = "0.19.4"\napp = marimo.App()\n'
    )
    repo.git.add(["-A"])
    repo.git.commit(["-m", "Add marimo notebook"])
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=SimpleNamespace(
                owner_account_name="test-owner",
                name="test-project",
                is_public=True,
                file_locks=[],
            ),
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=repo,
        ),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/notebooks"
        )
    assert response.status_code == 200
    notebooks = response.json()
    # A .py notebook can't be found by scanning for the .ipynb extension, so
    # naming it in a stage has to be enough
    assert [nb["path"] for nb in notebooks] == ["notebook.py"]
    nb = notebooks[0]
    assert nb["stage"] == "app"
    assert nb["app"] == "naca0012"
    # There's no executed copy of a marimo notebook, so its source is shown
    assert nb["output_format"] == "source"
    assert "marimo.App()" in base64.b64decode(nb["content"]).decode()


def test_get_project_notebooks_respects_ref(
    client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import git

    import app.projects

    monkeypatch.setattr(
        app.projects, "expand_dvc_lock_outs", lambda *a, **k: {}
    )
    repo_dir = tmp_path / "repo"
    repo = git.Repo.init(repo_dir)
    repo.git.config(["user.name", "CI Test"])
    repo.git.config(["user.email", "ci-test@example.com"])
    (repo_dir / "calkit.yaml").write_text("questions:\n  - Why?\n")
    (repo_dir / "first.ipynb").write_text('{"cells": [], "nbformat": 4}')
    repo.git.add(["-A"])
    repo.git.commit(["-m", "First notebook"])
    first_sha = repo.head.commit.hexsha
    # Leave the checkout on a branch that has a second notebook, so the
    # working tree disagrees with the ref being requested
    repo.git.checkout(["-b", "other"])
    (repo_dir / "second.ipynb").write_text('{"cells": [], "nbformat": 4}')
    repo.git.add(["-A"])
    repo.git.commit(["-m", "Second notebook"])

    def get(ref: str | None):
        with (
            patch(
                "app.api.routes.projects.core.app.projects.get_project",
                return_value=SimpleNamespace(
                    owner_account_name="test-owner",
                    name="test-project",
                    is_public=True,
                    file_locks=[],
                ),
            ),
            patch("app.api.routes.projects.core.get_repo", return_value=repo),
        ):
            url = (
                f"{settings.API_V1_STR}/projects/test-owner/test-project"
                "/notebooks"
            )
            return client.get(url, params={"ref": ref} if ref else None)

    # Undeclared notebooks are scanned from the requested ref, not from
    # whatever branch the cached clone happens to be sitting on
    response = get(first_sha)
    assert response.status_code == 200
    assert [nb["path"] for nb in response.json()] == ["first.ipynb"]
    # With no ref, the checkout is the right thing to read
    response = get(None)
    assert response.status_code == 200
    assert sorted(nb["path"] for nb in response.json()) == [
        "first.ipynb",
        "second.ipynb",
    ]


def test_get_project_tables_declares_detects_and_resolves(
    client: TestClient,
) -> None:
    fake_project = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000003",
        owner_account_name="test-owner",
        name="test-project",
        file_locks=[],
    )
    ck_info = {
        "tables": [
            {
                "path": "results/top-kernels.csv",
                "title": "Top kernels",
                "description": "Per-kernel aggregates.",
            },
            {"title": "no path, skipped"},
        ],
        "questions": [
            {
                "question": "Did it get faster?",
                "evidence": [
                    {"kind": "table", "path": "data/cited.csv"},
                    {"kind": "figure", "path": "figures/x.png"},
                ],
            }
        ],
    }
    detected_paths = [
        "tables/sample-sizes.csv",
        "tables/deep/nested/counts.tsv",
        "results/events.jsonl",
        "table/one.ndjson",
        "tables/summary.tex",  # a bare tabular fragment
        "tables/standalone.tex",  # one table in its own standalone document
    ]
    ignored_paths = [
        "data/output.csv",  # not under a tables or results directory
        "tables/notes.md",  # not a tabular format
        ".tables/hidden.csv",  # hidden directory
        "tables/notes.tex",  # TeX with no tabular environment
        "tables/float.tex",  # a table float holding no tabular
        "results/paper.tex",  # a whole document that contains a table
        "paper/main.tex",  # TeX outside a tables or results directory
    ]
    # What a .tex file holds is what decides whether it's a table: a bare
    # tabular fragment or a standalone-class document is one, a paper that
    # happens to contain a table is not.
    tabular = "\\begin{tabular}{ll}a & b \\\\\\end{tabular}"
    tex_by_path = {
        "tables/summary.tex": tabular,
        "tables/standalone.tex": (
            "\\documentclass[border=2pt]{standalone}\n"
            f"\\begin{{document}}\n{tabular}\n\\end{{document}}"
        ),
        "tables/float.tex": "\\begin{table}\\includegraphics{p.pdf}"
        "\\end{table}",
        "results/paper.tex": (
            "\\documentclass{article}\n"
            f"\\begin{{document}}\n\\section{{Results}}\n{tabular}\n"
            "\\end{document}"
        ),
    }

    def _blob(path: str) -> SimpleNamespace:
        tex = tex_by_path.get(path, "\\section{Results}")
        return SimpleNamespace(
            type="blob",
            path=path,
            size=len(tex),
            data_stream=SimpleNamespace(read=lambda: tex.encode()),
        )

    blobs = [_blob(p) for p in detected_paths + ignored_paths]
    fake_commit = SimpleNamespace(
        tree=SimpleNamespace(traverse=lambda: iter(blobs))
    )
    fake_repo = SimpleNamespace(
        commit=lambda _ref: fake_commit,
        head=SimpleNamespace(commit=fake_commit),
    )
    fake_contents = ContentsItem(
        name="t.csv",
        path="t.csv",
        type="file",
        size=1,
        in_repo=True,
        content="Y29sCjEK",
        url=None,
        storage="git",
    )
    url = f"{settings.API_V1_STR}/projects/test-owner/test-project/tables"
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            return_value=fake_repo,
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value=ck_info,
        ),
        patch(
            "app.api.routes.projects.core.get_repo_tree_for_ref",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.api.routes.projects.core.app.projects"
            ".get_ck_info_and_dvc_outs_from_tree",
            return_value=CkInfoAndOuts(
                {}, {"results/dvc-tracked.csv": {"type": "file"}}, {}, {}
            ),
        ),
        patch(
            "app.api.routes.projects.core.app.projects.get_contents_from_tree",
            return_value=fake_contents,
        ) as mock_contents,
    ):
        response = client.get(url)
        resolved_calls = mock_contents.call_count
        mock_contents.reset_mock()
        metadata_only = client.get(f"{url}?include_content=false")
        assert mock_contents.call_count == 0
    assert response.status_code == 200, response.text
    tables = response.json()
    paths = [tbl["path"] for tbl in tables]
    # The tables somebody described lead, then ones only cited as evidence,
    # then auto-detected ones, so the listing opens on the annotated tables
    assert paths[0] == "results/top-kernels.csv"
    assert paths[1] == "data/cited.csv"
    assert tables[0]["description"] == "Per-kernel aggregates."
    # A table cited by a question but never declared still gets a readable
    # title rather than rendering as nothing
    assert tables[1]["title"]
    for path in detected_paths + ["results/dvc-tracked.csv"]:
        assert path in paths, f"Expected {path!r} to be detected"
    for path in ignored_paths:
        assert path not in paths, f"Expected {path!r} to be ignored"
    # Nothing is listed twice, however many ways it was found
    assert len(paths) == len(set(paths))
    assert all(tbl["content"] == "Y29sCjEK" for tbl in tables)
    assert resolved_calls == len(paths)
    # Metadata-only listings cover the same tables without touching storage
    assert [tbl["path"] for tbl in metadata_only.json()] == paths
    assert all(tbl["content"] is None for tbl in metadata_only.json())


def test_build_question_evidence_keyed_results_and_tables() -> None:
    from app.api.routes.projects.core import _build_question_evidence
    from app.models.core import Result

    # Two results share a file, told apart only by their keys
    mean = Result(
        path="results/summary.json", title="Mean", key="metrics.mean"
    )
    table = Result(path="tables/t.csv", title="Sample sizes")
    evidence_ck = [
        # A key nobody declared: better to resolve nothing than to show this
        # value under an unrelated result's title
        {
            "kind": "result",
            "path": "results/summary.json",
            "key": "metrics.p95",
        },
        # Table evidence resolves against the same map, which is why that map
        # has to be built whenever table evidence is present
        {"kind": "table", "path": "tables/t.csv"},
    ]
    with patch(
        "app.api.routes.projects.core.app.projects.get_contents_from_repo",
        return_value=None,
    ):
        evidence = _build_question_evidence(
            project=SimpleNamespace(),
            repo=SimpleNamespace(),
            ref=None,
            evidence_ck=evidence_ck,
            figures_by_path={},
            results_by_path={(mean.path, mean.key): mean},
            tables_by_path={table.path: table},
            publications_by_path={},
            result_value_cache={},
        )
    assert evidence[0].result is None
    assert evidence[1].kind == "table"
    assert evidence[1].result is not None
    assert evidence[1].result.title == "Sample sizes"


def test_declared_tables_reach_the_evidence_lookup() -> None:
    from app.api.routes.projects.core import _build_declared_tables

    # A declared table is not something _build_results knows about, and a
    # tables directory is not auto-detected as results either, so without
    # this its title and description never reach the reader
    ck_info = {
        "tables": [
            {
                "path": "tables/sample-sizes.csv",
                "title": "Sample sizes",
                "description": "How many runs per case.",
            },
            {"path": "tables/untitled.csv"},
            {"title": "no path, skipped"},
            "not-a-dict",
        ]
    }
    with patch(
        "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
        return_value=ck_info,
    ):
        tables = _build_declared_tables(
            project=SimpleNamespace(), repo=SimpleNamespace(), ref=None
        )
    assert [t.path for t in tables] == [
        "tables/sample-sizes.csv",
        "tables/untitled.csv",
    ]
    assert tables[0].title == "Sample sizes"
    assert tables[0].description == "How many runs per case."
    # One without a title still gets a readable one from its path, rather
    # than rendering as nothing
    assert tables[1].title


def test_a_table_and_a_result_at_one_path_stay_distinct() -> None:
    from app.api.routes.projects.core import _build_question_evidence
    from app.models.core import Result

    # A project can declare both at one path. They are different things
    # with different titles, so neither may decide what the other is
    # called -- which is what one shared lookup would do.
    result = Result(path="shared.csv", title="Summary statistic")
    table = Result(path="shared.csv", title="Sample sizes")
    evidence_ck = [
        {"kind": "result", "path": "shared.csv"},
        {"kind": "table", "path": "shared.csv"},
    ]
    with patch(
        "app.api.routes.projects.core.app.projects.get_contents_from_repo",
        return_value=None,
    ):
        evidence = _build_question_evidence(
            project=SimpleNamespace(),
            repo=SimpleNamespace(),
            ref=None,
            evidence_ck=evidence_ck,
            figures_by_path={},
            results_by_path={(result.path, None): result},
            tables_by_path={table.path: table},
            publications_by_path={},
            result_value_cache={},
        )
    assert evidence[0].result is not None
    assert evidence[0].result.title == "Summary statistic"
    assert evidence[1].result is not None
    assert evidence[1].result.title == "Sample sizes"


def test_evidence_citing_an_undeclared_key_resolves_to_nothing() -> None:
    from app.api.routes.projects.core import _build_question_evidence
    from app.models.core import Result

    # A result is identified by (path, key). Falling back to the whole-file
    # result would put its title on a value it says nothing about.
    whole = Result(path="results/summary.json", title="Whole file")
    with patch(
        "app.api.routes.projects.core.app.projects.get_contents_from_repo",
        return_value=None,
    ):
        evidence = _build_question_evidence(
            project=SimpleNamespace(),
            repo=SimpleNamespace(),
            ref=None,
            evidence_ck=[
                {
                    "kind": "result",
                    "path": "results/summary.json",
                    "key": "metrics.p95",
                }
            ],
            figures_by_path={},
            results_by_path={(whole.path, None): whole},
            tables_by_path={},
            publications_by_path={},
            result_value_cache={},
        )
    assert evidence[0].result is None


def test_get_featured_projects(client: TestClient, db: Session) -> None:
    """Curated order, public only, and unknown slugs skipped."""
    public_project, _ = _make_owner_with_project(db, client)
    public_project.is_public = True
    private_project, _ = _make_owner_with_project(db, client)
    private_project.is_public = False
    db.add(public_project)
    db.add(private_project)
    db.commit()
    db.refresh(public_project)
    db.refresh(private_project)
    public_slug = f"{public_project.owner_account.name}/{public_project.name}"
    private_slug = (
        f"{private_project.owner_account.name}/{private_project.name}"
    )
    # A slug for a project nobody can see, and one that doesn't exist at
    # all, both drop out rather than erroring or leaking their existence.
    with patch.object(
        settings,
        "FEATURED_PROJECTS",
        [private_slug, public_slug, "nobody/nothing"],
    ):
        response = client.get(f"{settings.API_V1_STR}/projects/featured")
    assert response.status_code == 200
    body = response.json()
    slugs = [f"{p['owner_account_name']}/{p['name']}" for p in body["data"]]
    assert slugs == [public_slug]
    assert body["count"] == 1
    # Configured order is the order returned, not creation order.
    second_public, _ = _make_owner_with_project(db, client)
    second_public.is_public = True
    db.add(second_public)
    db.commit()
    db.refresh(second_public)
    second_slug = f"{second_public.owner_account.name}/{second_public.name}"
    with patch.object(
        settings, "FEATURED_PROJECTS", [second_slug, public_slug]
    ):
        response = client.get(f"{settings.API_V1_STR}/projects/featured")
    assert [
        f"{p['owner_account_name']}/{p['name']}"
        for p in response.json()["data"]
    ] == [second_slug, public_slug]
    # An empty configuration is an empty section, not an error.
    with patch.object(settings, "FEATURED_PROJECTS", []):
        response = client.get(f"{settings.API_V1_STR}/projects/featured")
    assert response.status_code == 200
    assert response.json() == {"data": [], "count": 0}


def test_post_project_when_account_name_differs_from_github(
    client: TestClient, db: Session
) -> None:
    """A private project for yourself isn't mistaken for one for an org.

    Linking GitHub to an account created through Google or email leaves the
    Calkit account name alone, so the two names routinely differ. Deciding
    ownership from the account name sent those users down the org path,
    where creating a project for themselves failed on an org lookup.
    """
    suffix = uuid.uuid4().hex[:8]
    user = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"mismatch-{suffix}@example.com",
            password="testpassword123",
            # The two names deliberately differ, as they do after linking.
            account_name=f"account{suffix}",
            github_username=f"ghname{suffix}",
        ),
    )
    headers = authentication_token_from_email(
        client=client, email=user.email, db=db
    )
    repo = f"https://github.com/ghname{suffix}/proj-{suffix}"
    with (
        patch(
            "app.api.routes.projects.core.users.get_github_token",
            return_value="gh-token",
        ),
        patch(
            "app.api.routes.projects.core.orgs.get_org_by_github_name"
        ) as get_org,
        # A 404 from GitHub means "repo doesn't exist yet", and the create
        # that follows is where this test stops caring.
        patch(
            "app.api.routes.projects.core.requests.get",
            return_value=SimpleNamespace(
                status_code=404, json=lambda: {}, text=""
            ),
        ),
        patch(
            "app.api.routes.projects.core.requests.post",
            return_value=SimpleNamespace(
                status_code=500, json=lambda: {}, text="stop here"
            ),
        ),
    ):
        resp = client.post(
            f"{settings.API_V1_STR}/projects",
            headers=headers,
            json={
                "name": f"proj-{suffix}",
                "title": "A private project for myself",
                "is_public": False,
                "git_repo_url": repo,
            },
        )
    # The org path is never taken, so no org lookup and no "Could not fetch
    # org from GitHub". What it fails on instead is the stubbed repo create.
    get_org.assert_not_called()
    assert "org" not in resp.text.lower()


def test_post_project_dataset_provenance(
    client: TestClient, db: Session
) -> None:
    """Each way a dataset joins a project writes the right calkit.yaml."""
    project, headers = _make_owner_with_project(db, client)
    url = (
        f"{settings.API_V1_STR}/projects/{project.owner_account.name}/"
        f"{project.name}/datasets"
    )
    written: list[dict] = []

    class FakeRepo:
        working_dir = "/tmp/does-not-matter"
        git = SimpleNamespace(
            add=lambda *a, **k: None,
            commit=lambda *a, **k: None,
            push=lambda *a, **k: None,
        )
        active_branch = SimpleNamespace(name="main")

    def post(body: dict, existing_path: bool = False):
        ck_info: dict = {"datasets": list(written)}
        with (
            patch(
                "app.api.routes.projects.core.get_repo",
                return_value=FakeRepo(),
            ),
            patch(
                "app.api.routes.projects.core.app.projects."
                "get_ck_info_from_repo",
                return_value=ck_info,
            ),
            # This test is about what gets written to calkit.yaml; the
            # fetching of imports has its own test with a real repo
            patch(
                "app.api.routes.projects.core.app.imports.fetch_files",
                side_effect=lambda files, wdir, path: (path, [path]),
            ),
            patch(
                "app.api.routes.projects.core.app.imports.fetch_git_path",
                return_value="c0ffee0123456789c0ffee0123456789c0ffee01",
            ),
            patch(
                "app.api.routes.projects.core.app.imports.resolve_doi_files",
                return_value={"x.csv": "https://example.org/x.csv"},
            ),
            patch(
                "app.api.routes.projects.core.calkit.get_size",
                return_value=0,
            ),
            patch(
                "app.api.routes.projects.core.get_zip_path_map_from_repo",
                return_value={},
            ),
            patch(
                "app.api.routes.projects.core.app.projects."
                "get_repo_tree_for_ref",
                return_value=None,
            ),
            patch(
                "app.api.routes.projects.core.app.projects."
                "dvc_outputs_from_tree",
                return_value={},
            ),
            patch(
                "app.api.routes.projects.core.os.path.isfile",
                return_value=existing_path,
            ),
            patch("builtins.open", new_callable=lambda: _fake_open),
            patch("app.api.routes.projects.core.mixpanel.track"),
        ):
            resp = client.post(url, headers=headers, json=body)
        if resp.status_code == 200:
            written[:] = ck_info["datasets"]
        return resp

    import contextlib
    import io

    @contextlib.contextmanager
    def _fake_open(*args, **kwargs):
        yield io.StringIO()

    # A DOI, the most durable provenance there is.
    resp = post(
        {
            "path": "data/doi.csv",
            "imported_from": {
                "doi": "10.5281/zenodo.1",
                "date": "2026-01-02",
            },
        }
    )
    assert resp.status_code == 200, resp.text
    assert written[-1]["imported_from"] == {
        "doi": "10.5281/zenodo.1",
        "date": "2026-01-02",
    }
    # The DB shape holds this as a string, so the response carries it as
    # JSON a client can parse rather than a Python repr.
    import json

    assert (
        json.loads(resp.json()["imported_from"])
        == written[-1]["imported_from"]
    )
    # A Git repo pinned to a revision.
    resp = post(
        {
            "path": "data/repo.csv",
            "imported_from": {
                "git_repo_url": "https://github.com/a/b",
                "git_ref": "deadbeef",
                "path": "out.csv",
            },
        }
    )
    assert resp.status_code == 200, resp.text
    # What was actually fetched is what's written, whatever was asked for
    assert (
        written[-1]["imported_from"]["git_rev"]
        == "c0ffee0123456789c0ffee0123456789c0ffee01"
    )
    # No revision means the default branch's head, recorded by its commit
    resp = post(
        {
            "path": "data/head.csv",
            "imported_from": {
                "git_repo_url": "https://github.com/a/b",
                "path": "h.csv",
            },
        }
    )
    assert resp.status_code == 200, resp.text
    assert (
        written[-1]["imported_from"]["git_rev"]
        == "c0ffee0123456789c0ffee0123456789c0ffee01"
    )
    # A branch or tag moves, so it can't be what's recorded; asked for, it
    # is resolved at fetch time and the commit it pointed at is written
    resp = post(
        {
            "path": "data/branch.csv",
            "imported_from": {
                "git_repo_url": "https://github.com/a/b",
                "git_ref": "main",
            },
        }
    )
    assert resp.status_code == 200, resp.text
    assert (
        written[-1]["imported_from"]["git_rev"]
        == "c0ffee0123456789c0ffee0123456789c0ffee01"
    )
    # A plain URL.
    resp = post(
        {
            "path": "data/url.csv",
            "imported_from": {"url": "https://example.org/d.csv"},
        }
    )
    assert resp.status_code == 200, resp.text
    assert written[-1]["imported_from"] == {"url": "https://example.org/d.csv"}
    # Data created here: needs a title and description, and the path has
    # to already exist, since nothing will fetch it.
    resp = post(
        {"path": "data/mine.csv", "created_by": [{"email": "me@x.edu"}]}
    )
    assert resp.status_code == 400
    resp = post(
        {
            "path": "data/mine.csv",
            "created_by": [{"email": "me@x.edu"}],
            "title": "Mine",
            "description": "Collected in the lab",
        }
    )
    # Not tracked by Git or DVC, so there is nothing to label.
    assert resp.status_code == 400
    assert "not tracked by Git or DVC" in resp.text
    resp = post(
        {
            "path": "data/mine.csv",
            "created_by": [{"email": "me@x.edu"}],
            "title": "Mine",
            "description": "Collected in the lab",
        },
        existing_path=True,
    )
    assert resp.status_code == 200, resp.text
    # One creator reads better as a mapping than a one-item list.
    assert written[-1]["created_by"] == {"email": "me@x.edu"}
    assert "imported_from" not in written[-1]
    # Produced by a stage: doesn't exist until the pipeline runs.
    resp = post(
        {
            "path": "data/derived.csv",
            "stage": "collect",
            "title": "Derived",
            "description": "From the pipeline",
        }
    )
    assert resp.status_code == 200, resp.text
    # Two sources at once is ambiguous provenance, which is worse than none.
    resp = post(
        {
            "path": "data/ambiguous.csv",
            "imported_from": {
                "doi": "10.1/x",
                "url": "https://example.org/x",
            },
        }
    )
    assert resp.status_code == 422
    # Collected here and imported from elsewhere can't both be true.
    resp = post(
        {
            "path": "data/both.csv",
            "created_by": [{"email": "me@x.edu"}],
            "imported_from": {"doi": "10.1/x"},
        }
    )
    assert resp.status_code == 422
    # The same path twice would make the entry ambiguous.
    resp = post(
        {
            "path": "data/url.csv",
            "imported_from": {"url": "https://example.org/again.csv"},
        }
    )
    assert resp.status_code == 400


def test_extract_project_zip(tmp_path) -> None:
    """Unpacking is confined to the target directory."""
    import io
    import zipfile

    from fastapi import HTTPException

    from app.api.routes.projects.core import _extract_project_zip

    def make_zip(entries: dict[str, str]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, content in entries.items():
                z.writestr(name, content)
        return buf.getvalue()

    dest = tmp_path / "repo"
    dest.mkdir()
    _extract_project_zip(
        make_zip({"data/raw.csv": "a,b\n", "analyze.py": "print(1)\n"}),
        str(dest),
    )
    assert (dest / "data" / "raw.csv").read_text() == "a,b\n"
    assert (dest / "analyze.py").exists()
    # A zip of a project usually has one folder at the top; keeping it would
    # bury the project a level deeper than the user meant.
    nested = tmp_path / "nested"
    nested.mkdir()
    _extract_project_zip(
        make_zip({"my-project/README.md": "hi", "my-project/src/a.py": "x"}),
        str(nested),
    )
    assert (nested / "README.md").read_text() == "hi"
    assert (nested / "src" / "a.py").exists()
    assert not (nested / "my-project").exists()
    # Git's own data belongs to the repo that already exists.
    skipped = tmp_path / "skipped"
    skipped.mkdir()
    _extract_project_zip(
        make_zip({".git/config": "nope", "keep.txt": "yes"}), str(skipped)
    )
    assert not (skipped / ".git").exists()
    assert (skipped / "keep.txt").exists()
    # macOS resource forks are noise, not project files.
    mac = tmp_path / "mac"
    mac.mkdir()
    _extract_project_zip(
        make_zip({"__MACOSX/._x": "junk", "x": "real"}), str(mac)
    )
    assert not (mac / "__MACOSX").exists()
    # A zip naming a path outside the destination is refused outright: this
    # runs on our server, against a directory we control.
    escape = tmp_path / "escape"
    escape.mkdir()
    with pytest.raises(HTTPException) as excinfo:
        _extract_project_zip(
            make_zip({"../../escaped.txt": "pwned"}), str(escape)
        )
    assert excinfo.value.status_code == 400
    assert not (tmp_path.parent / "escaped.txt").exists()
    # Something that isn't a zip is a message, not a traceback.
    with pytest.raises(HTTPException) as excinfo:
        _extract_project_zip(b"not a zip at all", str(escape))
    assert excinfo.value.status_code == 400


def test_post_project_upload_validates_before_creating(
    client: TestClient, db: Session
) -> None:
    """A bad archive is refused before any project exists for it."""
    import io
    import zipfile

    suffix = uuid.uuid4().hex[:8]
    owner = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"upload-{suffix}@example.com",
            password="testpassword123",
            account_name=f"upload{suffix}",
            github_username=f"upload{suffix}",
        ),
    )
    headers = authentication_token_from_email(
        client=client, email=owner.email, db=db
    )
    url = f"{settings.API_V1_STR}/projects/upload"

    def upload(name: str, content: bytes):
        with patch(
            "app.api.routes.projects.core.post_project"
        ) as post_project:
            resp = client.post(
                url,
                headers=headers,
                data={"title": "Uploaded", "name": name},
                files={"file": (f"{name}.zip", content, "application/zip")},
            )
        return resp, post_project

    def no_project(name: str) -> bool:
        return (
            db.exec(select(Project).where(Project.name == name)).first()
            is None
        )

    # Not a zip at all.
    name = f"notzip-{suffix}"
    resp, post_project = upload(name, b"this is not a zip archive")
    assert resp.status_code == 400, resp.text
    post_project.assert_not_called()
    assert no_project(name)
    # A zip naming a path outside the project.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../../escaped.txt", "pwned")
    name = f"escape-{suffix}"
    resp, post_project = upload(name, buf.getvalue())
    assert resp.status_code == 400, resp.text
    post_project.assert_not_called()
    assert no_project(name)
    # One whose members declare more than the unpacked cap allows.
    from app.api.routes.projects import core as core_mod

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("big.bin", "x")
    name = f"bomb-{suffix}"
    with patch.object(core_mod, "MAX_PROJECT_UNPACKED_BYTES", 0):
        resp, post_project = upload(name, buf.getvalue())
    assert resp.status_code == 400, resp.text
    post_project.assert_not_called()
    assert no_project(name)


def test_get_project_environments_stays_inside_repo(
    client: TestClient, tmp_path
) -> None:
    """Spec and lock reads stay in the clone, whatever calkit.yaml says."""
    # The repo is one directory under tmp_path, so tmp_path itself is what
    # a traversal lands in.
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("not yours\n")
    (repo_dir / "pyproject.toml").write_text("[project]\n")
    (repo_dir / "uv.lock").write_text("version = 1\n")
    lock_dir = repo_dir / ".calkit" / "env-locks" / "py"
    lock_dir.mkdir(parents=True)
    (lock_dir / "linux-64.txt").write_text("numpy==2.0\n")
    # A symlink in the locks directory pointing out of the repo.
    (lock_dir / "osx-arm64.txt").symlink_to(secret)
    envs = {
        # Legitimate: spec in the repo, lock next to it.
        "main": {"kind": "uv", "path": "pyproject.toml"},
        # Legitimate directory of locks, one entry of which is a symlink out.
        "py": {"kind": "venv", "path": "requirements.txt"},
        # A Docker env named to make its lock "directory" the repo's parent.
        "../../..": {"kind": "docker", "image": "x"},
        # A spec path that is absolute and exists, plus the classic.
        "abs": {"kind": "uv", "path": str(secret)},
        "passwd": {"kind": "uv", "path": "/etc/passwd"},
        # A relative spec path climbing out of the repo.
        "climb": {"kind": "uv", "path": "../secret.txt"},
    }
    fake_project = SimpleNamespace(
        owner_account_name="o", name="p", file_locks=[]
    )
    fake_repo = SimpleNamespace(working_dir=str(repo_dir))
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch("app.api.routes.projects.core.get_repo", return_value=fake_repo),
        patch(
            "app.api.routes.projects.core.app.projects.get_ck_info_for_ref",
            return_value={"environments": envs},
        ),
    ):
        resp = client.get(f"{settings.API_V1_STR}/projects/o/p/environments")
    assert resp.status_code == 200, resp.text
    by_name = {e["name"]: e for e in resp.json()}
    assert by_name["main"]["file_content"] == "[project]\n"
    assert [lk["path"] for lk in by_name["main"]["locks"]] == ["uv.lock"]
    # Only the lock that's really in the repo is returned.
    assert [lk["path"] for lk in by_name["py"]["locks"]] == [
        ".calkit/env-locks/py/linux-64.txt"
    ]
    assert by_name["../../.."]["locks"] == []
    for name in ["abs", "passwd", "climb"]:
        assert by_name[name]["file_content"] is None, name
        assert by_name[name]["locks"] == [], name
    # Nothing anywhere in the response came from outside the clone.
    assert "not yours" not in resp.text
    assert "root:" not in resp.text


def test_push_dvc_cache_to_storage(tmp_path) -> None:
    """Every cached object is copied, directory outputs included."""
    import io as _io

    from app.api.routes.projects.core import _push_dvc_cache_to_storage

    repo_dir = tmp_path / "repo"
    cache = repo_dir / ".dvc" / "cache" / "files" / "md5"
    (cache / "ab").mkdir(parents=True)
    (cache / "cd").mkdir(parents=True)
    (cache / "ab" / "cdef0123").write_bytes(b"file contents")
    # A directory output's listing is an object too, and a pointer to it
    # dangles without this.
    (cache / "cd" / "ef456789.dir").write_bytes(b'[{"md5": "abcdef0123"}]')
    written: dict[str, bytes] = {}

    class FakeFS:
        def open(self, path, mode="rb"):
            buf = _io.BytesIO()
            original_close = buf.close

            def close():
                written[path] = buf.getvalue()
                original_close()

            buf.close = close  # type: ignore[method-assign]
            return buf

    with (
        patch(
            "app.api.routes.projects.core.get_object_fs",
            return_value=FakeFS(),
        ),
        patch("app.config.settings.ENVIRONMENT", "local"),
    ):
        count = _push_dvc_cache_to_storage(
            repo_dir=str(repo_dir),
            owner_name="someone",
            project_name="a-project",
        )
    assert count == 2
    assert sorted(p.split("/")[-2:] for p in written) == [
        ["ab", "cdef0123"],
        ["cd", "ef456789.dir"],
    ]
    assert list(written.values())[0] == b"file contents"
    # A repo with nothing in DVC has nothing to push, and that isn't an error.
    empty = tmp_path / "empty"
    empty.mkdir()
    with patch("app.api.routes.projects.core.get_object_fs") as fs:
        assert (
            _push_dvc_cache_to_storage(
                repo_dir=str(empty), owner_name="a", project_name="b"
            )
            == 0
        )
    fs.assert_not_called()
