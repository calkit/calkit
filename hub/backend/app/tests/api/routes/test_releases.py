"""Tests for app.api.routes.projects.releases endpoints.

These exercise the wiring end to end (routing, models, the new tables, and
auth) against the migrated database. The authenticated create/view/comment
happy path requires a fully seeded project + repo and is covered separately.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from app.api.routes.projects.releases import (
    _parse_arxiv_id_from_url,
    _parse_doi_from_url,
    _fetch_arxiv,
    _fetch_osf,
    _parse_osf_guid_from_url,
    _parse_release_url,
    _build_stored_release_filename,
)
from app.config import settings
from app.models import ReleaseStaleness, ReleaseUrlMetadata
from app.pipeline import StageStatus
from fastapi.testclient import TestClient


def test_get_release_view_unknown_project_returns_404(
    client: TestClient,
) -> None:
    resp = client.get(
        f"{settings.API_V1_STR}"
        "/projects/test-owner/test-project/releases/v1/view"
    )
    assert resp.status_code == 404


def test_get_release_contents_unknown_project_returns_404(
    client: TestClient,
) -> None:
    resp = client.get(
        f"{settings.API_V1_STR}"
        "/projects/test-owner/test-project/releases/v1/contents"
    )
    assert resp.status_code == 404


def test_get_release_comments_unknown_project_returns_404(
    client: TestClient,
) -> None:
    resp = client.get(
        f"{settings.API_V1_STR}"
        "/projects/test-owner/test-project/releases/v1/comments"
    )
    assert resp.status_code == 404


def test_post_release_comment_unknown_project_returns_404(
    client: TestClient,
) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}"
        "/projects/test-owner/test-project/releases/v1/comments",
        json={"comment": "hello"},
    )
    assert resp.status_code == 404


def test_create_release_share_requires_auth(client: TestClient) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}"
        "/projects/test-owner/test-project/releases/v1/shares",
        json={"permission": "comment"},
    )
    assert resp.status_code == 401


def test_list_release_shares_requires_auth(client: TestClient) -> None:
    resp = client.get(
        f"{settings.API_V1_STR}"
        "/projects/test-owner/test-project/releases/v1/shares"
    )
    assert resp.status_code == 401


def test_post_project_release_requires_auth(client: TestClient) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}/projects/test-owner/test-project/releases",
        json={"name": "v0.1"},
    )
    assert resp.status_code == 401


def test_post_external_release_requires_auth(client: TestClient) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}"
        "/projects/test-owner/test-project/releases/external",
        json={"name": "v1.0", "publisher": "arxiv"},
    )
    assert resp.status_code == 401


def test_import_github_releases_requires_auth(client: TestClient) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}"
        "/projects/test-owner/test-project/releases/import-github"
    )
    assert resp.status_code == 401


def test_create_release_github_release_requires_auth(
    client: TestClient,
) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}"
        "/projects/test-owner/test-project/releases/v1/github"
    )
    assert resp.status_code == 401


def test_resolve_release_comment_requires_auth(client: TestClient) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}"
        "/projects/test-owner/test-project/releases/v1/comments/"
        f"{uuid.uuid4()}/resolve",
        json={"resolved": True},
    )
    assert resp.status_code == 401


def test_parse_release_url_requires_auth(client: TestClient) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}"
        "/projects/test-owner/test-project/releases/parse-url",
        json={"url": "https://arxiv.org/abs/1706.03762"},
    )
    assert resp.status_code == 401


def test_arxiv_id_from_url() -> None:
    assert (
        _parse_arxiv_id_from_url("https://arxiv.org/abs/1706.03762")
        == "1706.03762"
    )
    assert _parse_arxiv_id_from_url("https://arxiv.org/pdf/2401.12345v2") == (
        "2401.12345v2"
    )
    assert _parse_arxiv_id_from_url("arXiv:2401.12345") == "2401.12345"
    assert _parse_arxiv_id_from_url(
        "https://arxiv.org/abs/math.GT/0309136"
    ) == ("math.GT/0309136")
    # Not arXiv -- a DOI URL must not be misread as an arXiv id.
    assert (
        _parse_arxiv_id_from_url("https://doi.org/10.1038/nature12373") is None
    )


def test_doi_from_url() -> None:
    assert _parse_doi_from_url("https://doi.org/10.1038/nature12373") == (
        "10.1038/nature12373"
    )
    assert (
        _parse_doi_from_url("10.5281/zenodo.3509134")
        == "10.5281/zenodo.3509134"
    )
    # Trailing punctuation from a paste is trimmed.
    assert (
        _parse_doi_from_url("(10.1038/nature12373).") == "10.1038/nature12373"
    )
    # A Zenodo record page URL has no DOI but the DOI is derivable.
    assert _parse_doi_from_url("https://zenodo.org/records/3509134") == (
        "10.5281/zenodo.3509134"
    )
    assert _parse_doi_from_url("https://example.com/whatever") is None


def test_osf_guid_from_url() -> None:
    assert _parse_osf_guid_from_url("https://osf.io/ab3cd/") == "ab3cd"
    assert _parse_osf_guid_from_url(
        "https://osf.io/ab3cd/files/osfstorage"
    ) == ("ab3cd")
    assert _parse_osf_guid_from_url("http://osf.io/AB3CD") == "ab3cd"
    # App routes are not project guids.
    assert _parse_osf_guid_from_url("https://osf.io/dashboard") is None
    assert _parse_osf_guid_from_url("https://example.com/ab3cd") is None


def test_fetch_osf_registration_derives_doi() -> None:
    payload = {
        "data": {
            "id": "ab3cd",
            "type": "registrations",
            "attributes": {
                "title": "My Registered Study",
                "description": "  A study.  ",
                "date_registered": "2026-02-03T12:00:00.000000Z",
            },
            "links": {"html": "https://osf.io/ab3cd/"},
        }
    }
    with patch(
        "app.api.routes.projects.releases.requests.get",
        return_value=SimpleNamespace(status_code=200, json=lambda: payload),
    ):
        meta = _fetch_osf("ab3cd")
    assert meta is not None
    assert meta.publisher == "osf"
    assert meta.title == "My Registered Study"
    assert meta.doi == "10.17605/OSF.IO/AB3CD"
    assert meta.url == "https://osf.io/ab3cd/"
    assert meta.date == "2026-02-03"
    assert meta.description == "A study."


def test_fetch_osf_project_has_no_doi() -> None:
    payload = {
        "data": {
            "id": "ab3cd",
            "type": "nodes",
            "attributes": {
                "title": "My Project",
                "date_created": "2025-11-09T08:00:00.000000Z",
            },
        }
    }
    with patch(
        "app.api.routes.projects.releases.requests.get",
        return_value=SimpleNamespace(status_code=200, json=lambda: payload),
    ):
        meta = _fetch_osf("ab3cd")
    assert meta is not None
    assert meta.doi is None
    assert meta.date == "2025-11-09"


def test_parse_release_url_unrecognized_returns_none() -> None:
    # No DOI or arXiv id present, so no network call is made.
    assert _parse_release_url("https://example.com/some/page") is None


def test_fetch_arxiv_falls_back_to_datacite_on_timeout() -> None:
    """When arXiv's API times out, resolve the minted DOI via DataCite."""
    datacite = ReleaseUrlMetadata(
        publisher="arXiv",
        title="Some Paper",
        doi="10.48550/ARXIV.2606.23755",
        url="http://arxiv.org/abs/2606.23755",
        date="2026",
    )
    with (
        patch(
            "app.api.routes.projects.releases._fetch_arxiv_atom",
            side_effect=requests.exceptions.ReadTimeout("slow"),
        ),
        patch(
            "app.api.routes.projects.releases._fetch_doi",
            return_value=datacite,
        ) as fetch_doi,
    ):
        meta = _fetch_arxiv("2606.23755v2")
    fetch_doi.assert_called_once_with("10.48550/arXiv.2606.23755")
    assert meta is not None
    assert meta.title == "Some Paper"
    # arXiv identity is normalized regardless of the source that answered.
    assert meta.publisher == "arxiv"
    assert meta.url == "https://arxiv.org/abs/2606.23755v2"


def test_fetch_arxiv_minimal_when_all_unreachable() -> None:
    """If both arXiv and DataCite are unreachable, derive URL + DOI offline."""
    with (
        patch(
            "app.api.routes.projects.releases._fetch_arxiv_atom",
            side_effect=requests.exceptions.ConnectTimeout("down"),
        ),
        patch(
            "app.api.routes.projects.releases._fetch_doi",
            side_effect=requests.exceptions.ConnectTimeout("down"),
        ),
    ):
        meta = _fetch_arxiv("2606.23755")
    assert meta is not None
    assert meta.title is None
    assert meta.publisher == "arxiv"
    assert meta.doi == "10.48550/arXiv.2606.23755"
    assert meta.url == "https://arxiv.org/abs/2606.23755"


def test_stored_release_filename() -> None:
    # {project}-{stem}-{name}{ext}, matching calkit new release --internal.
    assert (
        _build_stored_release_filename("myproj", "figures/plot.png", "v1.0")
        == "myproj-plot-v1.0.png"
    )
    # No extension is handled.
    assert (
        _build_stored_release_filename("p", "paper/manuscript", "rev2")
        == "p-manuscript-rev2"
    )


def test_validate_release_name_accepts_and_rejects_git_tags() -> None:
    from app.models.releases import validate_release_name

    for ok in ["v1.0", "v0.1.2", "release-1", "2026.06", "feature/x"]:
        assert validate_release_name(ok) == ok
    # Leading/trailing whitespace is stripped.
    assert validate_release_name("  v1.0  ") == "v1.0"
    for bad in [
        "v 1.0",
        "has space",
        "v1..0",
        "-lead",
        "end.",
        ".start",
        "a.lock",
        "tag~1",
        "@",
        "x//y",
        "a\\b",
        "q?",
    ]:
        with pytest.raises(ValueError):
            validate_release_name(bad)


def test_post_project_release_rejects_invalid_name(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}/projects/test-owner/test-project/releases",
        json={"name": "not a tag"},
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 422


def test_fetch_arxiv_not_found_returns_none() -> None:
    """A definitive not-found from the API (no network error) fails honestly."""
    with patch(
        "app.api.routes.projects.releases._fetch_arxiv_atom", return_value=None
    ):
        assert _fetch_arxiv("9999.99999") is None


def test_get_project_releases_unknown_project_returns_404(
    client: TestClient,
) -> None:
    # Listing is read-access (anonymous allowed for public projects), so an
    # unauthenticated request resolves the project first and 404s when missing.
    resp = client.get(
        f"{settings.API_V1_STR}/projects/test-owner/test-project/releases"
    )
    assert resp.status_code == 404


def test_get_project_releases_includes_calkit_yaml(
    client: TestClient,
) -> None:
    """Releases declared in calkit.yaml are surfaced to read-only viewers."""
    fake_project = SimpleNamespace(id=uuid.uuid4(), current_user_access="read")
    ck_info = {
        "releases": {
            "v0.1": {
                "kind": "project",
                "path": ".",
                "git_rev": "919e52021fa61b05546a36337638a8e8846220ac",
                "date": "2025-10-31",
                "doi": "10.22002/640bx-nbn45",
                "url": "https://doi.org/10.22002/640bx-nbn45",
            }
        }
    }
    with (
        patch(
            "app.api.routes.projects.releases.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.releases.get_repo",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.api.routes.projects.releases.app.projects.get_ck_info_for_ref",
            return_value=ck_info,
        ),
    ):
        resp = client.get(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/releases"
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    item = data[0]
    assert item["source"] == "calkit"
    assert item["name"] == "v0.1"
    # A missing ``public`` key means the release is public.
    assert item["public"] is True
    assert item["doi"] == "10.22002/640bx-nbn45"
    # Full SHA is abbreviated for display.
    assert item["git_rev_abbrev"] == "919e520"


def test_get_release_staleness_requires_auth(client: TestClient) -> None:
    resp = client.get(
        f"{settings.API_V1_STR}"
        "/projects/test-owner/test-project/releases/staleness?path=x.pdf"
    )
    assert resp.status_code == 401


def test_path_staleness_whole_project_not_gated() -> None:
    """Whole-project releases aren't evaluated for stage staleness."""
    from app.api.routes.projects import releases

    res = releases._get_pipeline_output_staleness(
        SimpleNamespace(), "abc123", ".", "o", "p"
    )
    assert res.up_to_date is True
    assert res.stage is None


def test_path_staleness_no_producing_stage_not_gated() -> None:
    """A path no pipeline stage produces can't be stale -> not gated."""
    from app.api.routes.projects import releases

    fake_tree = SimpleNamespace(
        is_file=lambda p: p == "dvc.lock",
        read_bytes=lambda p: b"stages: {}",
    )
    with (
        patch(
            "app.api.routes.projects.releases.get_repo_tree_for_ref",
            return_value=fake_tree,
        ),
        patch(
            "app.api.routes.projects.releases.find_stage_for_path",
            return_value=None,
        ),
    ):
        res = releases._get_pipeline_output_staleness(
            SimpleNamespace(), "abc123", "figs/x.png", "o", "p"
        )
    assert res.up_to_date is True
    assert res.stage is None


def test_path_staleness_stale_stage_flags_not_up_to_date() -> None:
    from app.api.routes.projects import releases

    fake_tree = SimpleNamespace(
        is_file=lambda p: True, read_bytes=lambda p: b"stages: {}"
    )
    statuses = {
        "build-paper": StageStatus(
            status="stale", modified_inputs=["paper/paper.tex"]
        )
    }
    with (
        patch(
            "app.api.routes.projects.releases.get_repo_tree_for_ref",
            return_value=fake_tree,
        ),
        patch(
            "app.api.routes.projects.releases.find_stage_for_path",
            return_value="build-paper",
        ),
        patch(
            "app.api.routes.projects.releases.compute_stage_statuses",
            return_value=statuses,
        ),
    ):
        res = releases._get_pipeline_output_staleness(
            SimpleNamespace(), "abc123", "paper/paper.pdf", "o", "p"
        )
    assert res.up_to_date is False
    assert res.status == "stale"
    assert res.stage == "build-paper"
    assert res.modified_inputs == ["paper/paper.tex"]


def test_hash_share_token_is_sha256_and_not_identity() -> None:
    """Share tokens are stored as a SHA-256 hash, never in the clear."""
    import hashlib

    from app.api.routes.projects import releases

    raw = "super-secret-token"
    hashed = releases._hash_share_token(raw)
    assert hashed == hashlib.sha256(raw.encode()).hexdigest()
    assert hashed != raw
    assert len(hashed) == 64
    # Deterministic so lookups by hash work.
    assert releases._hash_share_token(raw) == hashed


def _share_email_fixtures():
    project = SimpleNamespace(owner_account_name="test-owner", name="proj")
    release = SimpleNamespace(name="v1.0")
    token = SimpleNamespace(
        email="reviewer@example.com", permission="comment", note=None
    )
    user = SimpleNamespace(full_name="Alice", email="alice@example.com")
    return project, release, token, user


def test_send_share_email_skips_when_not_configured() -> None:
    """No SMTP config -> no send, returns False, creation still succeeds."""
    from app.api.routes.projects import releases

    project, release, token, user = _share_email_fixtures()
    with (
        patch.object(settings, "SMTP_HOST", None),
        patch("app.api.routes.projects.releases.messaging.send_email") as send,
    ):
        sent = releases._send_share_email(project, release, token, "RAW", user)
    assert sent is False
    send.assert_not_called()


def test_send_share_email_skips_without_recipient() -> None:
    """A link with no recipient email is never emailed, even if configured."""
    from app.api.routes.projects import releases

    project, release, token, user = _share_email_fixtures()
    token.email = None
    with (
        patch.object(settings, "SMTP_HOST", "smtp.example.com"),
        patch.object(settings, "EMAILS_FROM_EMAIL", "from@example.com"),
        patch("app.api.routes.projects.releases.messaging.send_email") as send,
    ):
        sent = releases._send_share_email(project, release, token, "RAW", user)
    assert sent is False
    send.assert_not_called()


def test_send_share_email_sends_link_with_token() -> None:
    """When configured, the invite is sent and embeds the token link."""
    from app.api.routes.projects import releases

    project, release, token, user = _share_email_fixtures()
    with (
        patch.object(settings, "SMTP_HOST", "smtp.example.com"),
        patch.object(settings, "EMAILS_FROM_EMAIL", "from@example.com"),
        patch("app.api.routes.projects.releases.messaging.send_email") as send,
    ):
        sent = releases._send_share_email(project, release, token, "RAW", user)
    assert sent is True
    send.assert_called_once()
    kwargs = send.call_args.kwargs
    assert kwargs["email_to"] == "reviewer@example.com"
    assert "?token=RAW" in kwargs["html_content"]
    assert "v1.0" in kwargs["html_content"]


def test_send_share_email_swallows_send_failure() -> None:
    """A transport error doesn't fail share creation -- it returns False."""
    from app.api.routes.projects import releases

    project, release, token, user = _share_email_fixtures()
    with (
        patch.object(settings, "SMTP_HOST", "smtp.example.com"),
        patch.object(settings, "EMAILS_FROM_EMAIL", "from@example.com"),
        patch(
            "app.api.routes.projects.releases.messaging.send_email",
            side_effect=RuntimeError("smtp down"),
        ),
    ):
        sent = releases._send_share_email(project, release, token, "RAW", user)
    assert sent is False


def test_post_project_release_blocks_non_reproducible(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    tmp_path,
) -> None:
    """A stale artifact is rejected with 409 unless acknowledged."""
    fake_project = SimpleNamespace(
        id=uuid.uuid4(), owner_account_name="test-owner", name="test-project"
    )

    class _FakeTree:
        def __truediv__(self, other):
            return object()

    fake_commit = SimpleNamespace(hexsha="a" * 40, tree=_FakeTree())
    # An empty working dir (no calkit.yaml) makes the re-release guard a no-op,
    # so the request reaches the staleness check this test targets.
    fake_repo = SimpleNamespace(
        commit=lambda ref: fake_commit,
        head=SimpleNamespace(commit=fake_commit),
        tags=[],
        working_dir=str(tmp_path),
    )
    stale = ReleaseStaleness(
        path="paper/paper.pdf",
        stage="build-paper",
        status="stale",
        up_to_date=False,
    )
    with (
        patch(
            "app.api.routes.projects.releases.app.projects.get_project",
            return_value=fake_project,
        ),
        patch(
            "app.api.routes.projects.releases.get_repo", return_value=fake_repo
        ),
        patch(
            "app.api.routes.projects.releases._get_pipeline_output_staleness",
            return_value=stale,
        ),
    ):
        resp = client.post(
            f"{settings.API_V1_STR}/projects/test-owner/test-project/releases",
            json={"name": "v0.1", "path": "paper/paper.pdf"},
            headers=normal_user_token_headers,
        )
    assert resp.status_code == 409
    assert "reproducible" in resp.json()["detail"].lower()
