from fastapi.testclient import TestClient

from app.config import settings


def test_reference_item_needs_a_field(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    url = f"{settings.API_V1_STR}/projects/o/p/references/items"
    # Key and type alone would be written as an entry bibtexparser can't
    # read back, so it's refused up front rather than silently lost
    resp = client.post(
        url,
        json={"path": "references.bib", "type": "article", "key": "k2020"},
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "at least one field" in resp.json()["detail"]
    resp = client.post(
        url,
        json={
            "path": "references.bib",
            "type": "article",
            "key": "k2020",
            "fields": {"title": "   "},
        },
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 422, resp.text
    # No key is still its own message
    resp = client.post(
        url,
        json={"path": "references.bib", "type": "article", "key": " "},
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "citation key" in resp.json()["detail"]
