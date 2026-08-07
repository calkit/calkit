"""Tests for app.api.routes.projects.core endpoints."""

import uuid
from types import SimpleNamespace
from unittest.mock import ANY, patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import users, zotero
from app.api.routes.projects.core import get_project_comments
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


def test_get_project_figures_autodetects_deeply_nested(
    client: TestClient,
) -> None:
    """Figures inside a 'figures' dir at any depth must be auto-detected."""
    fake_project = SimpleNamespace(id="00000000-0000-0000-0000-000000000001")
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
        )
    assert response.status_code == 200
    returned_figures = response.json()
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
    fake_project = SimpleNamespace(id="00000000-0000-0000-0000-000000000001")
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
        )
    assert response.status_code == 200
    returned_figures = response.json()
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
    fake_project = SimpleNamespace(id="00000000-0000-0000-0000-000000000001")
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
        )
    assert response.status_code == 200
    returned_figures = response.json()
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
    fake_project = SimpleNamespace(id="00000000-0000-0000-0000-000000000001")
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
        )
    assert response.status_code == 200
    returned_figures = response.json()
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
    fake_project = SimpleNamespace(id="00000000-0000-0000-0000-000000000001")
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
        )
    assert response.status_code == 200
    returned_figures = response.json()
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
    assert _extract_question_text(["a", "b"]) == ""


def test_build_question_evidence_resolves_figures_and_results() -> None:
    import base64
    import json

    from app.api.routes.projects.core import _build_question_evidence
    from app.models.core import Figure, Publication, Result

    fig = Figure(path="figures/x.png", title="X")
    res = Result(path="results/summary.json", title="Summary")
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
            project=SimpleNamespace(),
            repo=SimpleNamespace(),
            ref=None,
            evidence_ck=evidence_ck,
            figures_by_path={fig.path: fig},
            results_by_path={res.path: res},
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
            json={"path": "references.bib", "key": "smith2020"},
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
