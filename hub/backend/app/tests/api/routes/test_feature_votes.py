from fastapi.testclient import TestClient

from app.config import settings

FEATURE = "external-releases-in-app"


def test_get_feature_vote_status(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/feature-votes/{FEATURE}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["feature"] == FEATURE
    assert data["has_voted"] is False


def test_unknown_feature_404(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/feature-votes/bogus",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 404


def test_cast_feature_vote_is_idempotent(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/feature-votes/{FEATURE}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    first = r.json()
    assert first["has_voted"] is True
    assert first["count"] >= 1
    r = client.post(
        f"{settings.API_V1_STR}/feature-votes/{FEATURE}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    second = r.json()
    assert second["has_voted"] is True
    # Voting again must not increment the count.
    assert second["count"] == first["count"]


def test_remove_feature_vote(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    client.post(
        f"{settings.API_V1_STR}/feature-votes/{FEATURE}",
        headers=normal_user_token_headers,
    )
    r = client.delete(
        f"{settings.API_V1_STR}/feature-votes/{FEATURE}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    assert r.json()["has_voted"] is False
    # Removing again is a no-op, not an error.
    r = client.delete(
        f"{settings.API_V1_STR}/feature-votes/{FEATURE}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    assert r.json()["has_voted"] is False


def test_get_feature_votes_for_admin(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    base = f"{settings.API_V1_STR}/feature-votes"
    resp = client.post(
        f"{base}/local-workspace-compute", headers=normal_user_token_headers
    )
    assert resp.status_code == 200, resp.text
    # Only an admin sees the tally with names
    resp = client.get(base, headers=normal_user_token_headers)
    assert resp.status_code == 403
    resp = client.get(base, headers=superuser_token_headers)
    assert resp.status_code == 200, resp.text
    by_feature = {f["feature"]: f for f in resp.json()}
    # Every feature on offer is listed, voted for or not
    assert "external-releases-in-app" in by_feature
    votes = by_feature["local-workspace-compute"]
    assert votes["count"] >= 1
    voter = next(v for v in votes["voters"] if v["email"])
    assert set(voter) == {"email", "full_name", "account_name", "created"}
    # Unvoting takes the user off the list
    client.delete(
        f"{base}/local-workspace-compute", headers=normal_user_token_headers
    )
    resp = client.get(base, headers=superuser_token_headers)
    after = {f["feature"]: f for f in resp.json()}["local-workspace-compute"]
    assert after["count"] == votes["count"] - 1
