from fastapi.testclient import TestClient


def test_uploaded_figure_needs_attestation(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    url = "/projects/o/p/figures"
    # A file with no stage and nobody named to stand behind it is refused
    # before anything is touched
    resp = client.post(
        url,
        data={"path": "figures/a.png", "title": "A", "description": "B"},
        files={"file": ("a.png", b"\x89PNG", "image/png")},
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "created_by" in resp.json()["detail"]
    # Declaring a stage alongside a file is the pre-existing refusal
    resp = client.post(
        url,
        data={
            "path": "figures/a.png",
            "title": "A",
            "description": "B",
            "stage": "plot",
            "created_by": "me@example.org",
        },
        files={"file": ("a.png", b"\x89PNG", "image/png")},
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 400, resp.text
