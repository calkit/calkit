"""Tests for the ``invenio`` module."""

import os
import re

import calkit


def test_get_base_url():
    assert (
        calkit.invenio.get_base_url("zenodo")
        == "https://sandbox.zenodo.org/api"
    )


def test_get_token():
    token = calkit.invenio.get_token("zenodo")
    assert isinstance(token, str)


def test_extract_doi():
    extract_doi = calkit.invenio.extract_doi
    # DOI under pids (e.g. publish response or reserved draft)
    assert (
        extract_doi({"pids": {"doi": {"identifier": "10.5281/zenodo.1"}}})
        == "10.5281/zenodo.1"
    )
    # DOI at the top level
    assert extract_doi({"doi": "10.5281/zenodo.2"}) == "10.5281/zenodo.2"
    # DOI under metadata
    assert (
        extract_doi({"metadata": {"doi": "10.5281/zenodo.3"}})
        == "10.5281/zenodo.3"
    )
    # Empty pids (publish response without a reserved DOI) returns None
    assert extract_doi({"pids": {}}) is None
    assert extract_doi({"pids": {"doi": {}}}) is None
    assert extract_doi({}) is None


def test_request_retries(monkeypatch):
    import requests
    from requests.exceptions import HTTPError

    class MockResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.text = "boom"

        def json(self):
            return {"message": "boom"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(calkit.invenio.time, "sleep", lambda seconds: None)
    calls = []

    def make_func(responses):
        def func(url, **kwargs):
            calls.append(kwargs.get("timeout"))
            result = responses[min(len(calls) - 1, len(responses) - 1)]
            if isinstance(result, Exception):
                raise result
            return MockResponse(result)

        return func

    # A gateway timeout on an idempotent request is retried until it works,
    # and every attempt carries a timeout so nothing can hang forever
    monkeypatch.setattr(requests, "put", make_func([504, 504, 200]))
    calkit.invenio.put("/x", auth=False, as_json=False)
    assert len(calls) == 3
    assert all(t == calkit.invenio.get_timeout() for t in calls)
    # Connection errors are retried the same way
    calls.clear()
    monkeypatch.setattr(
        requests, "get", make_func([requests.ConnectionError(), 200])
    )
    calkit.invenio.get("/x", auth=False, as_json=False)
    assert len(calls) == 2
    # Retries eventually give up rather than looping forever
    calls.clear()
    monkeypatch.setattr(requests, "get", make_func([503]))
    try:
        calkit.invenio.get("/x", auth=False, as_json=False)
        raise AssertionError("Expected an HTTPError")
    except HTTPError:
        pass
    assert len(calls) == calkit.invenio.MAX_ATTEMPTS
    # A POST isn't retried, since the far end may have acted on it, and the
    # error says so
    calls.clear()
    monkeypatch.setattr(requests, "post", make_func([504]))
    try:
        calkit.invenio.post("/x", auth=False, as_json=False)
        raise AssertionError("Expected an HTTPError")
    except HTTPError as e:
        assert "not retried automatically" in str(e)
    assert len(calls) == 1
    # An explicit timeout from the caller is left alone
    calls.clear()
    monkeypatch.setattr(requests, "get", make_func([200]))
    calkit.invenio.get("/x", auth=False, as_json=False, timeout=5)
    assert calls == [5]


def test_get_timeout(monkeypatch):
    assert calkit.invenio.get_timeout() == (
        calkit.invenio.CONNECT_TIMEOUT,
        calkit.invenio.READ_TIMEOUT,
    )
    monkeypatch.setenv("CALKIT_INVENIO_TIMEOUT", "12")
    assert calkit.invenio.get_timeout() == (
        calkit.invenio.CONNECT_TIMEOUT,
        12.0,
    )


def _mock_service(monkeypatch, httpserver):
    monkeypatch.setenv(
        "CALKIT_INVENIO_BASE_URL_ZENODO", httpserver.url_for("").rstrip("/")
    )
    monkeypatch.setenv("ZENODO_TOKEN", "test-token")
    monkeypatch.setattr(calkit.invenio.time, "sleep", lambda seconds: None)
    # Small parts so a small file still goes up in several of them
    monkeypatch.setattr(calkit.invenio, "MULTIPART_PART_SIZE", 1024)


def test_upload_file_multipart(tmp_path, monkeypatch, httpserver):
    import json

    from werkzeug import Response

    _mock_service(monkeypatch, httpserver)
    content = os.urandom(2500)
    fpath = tmp_path / "archive.zip"
    fpath.write_bytes(content)
    received = {}
    commits = []

    def init(request):
        entry = json.loads(request.data)[0]
        transfer = entry["transfer"]
        assert transfer["type"] == "M"
        assert transfer["parts"] == 3
        assert entry["size"] == 2500
        parts = [
            {"part": n, "url": httpserver.url_for(f"/s3/part{n}")}
            for n in range(1, transfer["parts"] + 1)
        ]
        return Response(
            json.dumps(
                {
                    "entries": [
                        {"key": "README.md", "transfer": {"type": "L"}},
                        {
                            "key": entry["key"],
                            "transfer": transfer,
                            "links": {"parts": parts},
                        },
                    ]
                }
            ),
            content_type="application/json",
        )

    failed_once = []

    def part(request):
        n = int(request.path.removeprefix("/s3/part"))
        # Storage hiccups on one part, which is sent again
        if n == 2 and not failed_once:
            failed_once.append(n)
            return Response("busy", status=503)
        # The part URL is presigned, so it carries no API token
        assert "access_token" not in request.args
        received[n] = request.data
        return Response("", status=200)

    def commit(request):
        commits.append(request.path)
        return Response("{}", content_type="application/json")

    httpserver.expect_request(
        "/records/abc/draft/files", method="POST"
    ).respond_with_handler(init)
    httpserver.expect_request(
        re.compile(r"^/s3/part\d+$"), method="PUT"
    ).respond_with_handler(part)
    httpserver.expect_request(
        "/records/abc/draft/files/archive.zip/commit", method="POST"
    ).respond_with_handler(commit)
    progress = []
    calkit.invenio.upload_file(
        "abc", str(fpath), progress=lambda done, total: progress.append(done)
    )
    assert b"".join(received[n] for n in sorted(received)) == content
    assert [len(received[n]) for n in sorted(received)] == [1024, 1024, 452]
    assert commits == ["/records/abc/draft/files/archive.zip/commit"]
    assert progress == [0, 1024, 2048, 2500]


def test_upload_file_single(tmp_path, monkeypatch, httpserver):
    import json

    from werkzeug import Response

    _mock_service(monkeypatch, httpserver)
    content = os.urandom(2500)
    fpath = tmp_path / "archive.zip"
    fpath.write_bytes(content)
    inits = []
    bodies = []

    def init(request):
        entry = json.loads(request.data)[0]
        inits.append(entry)
        # A server without multipart support refuses the transfer type
        if "transfer" in entry:
            return Response(
                json.dumps({"message": "Invalid transfer type"}),
                status=400,
                content_type="application/json",
            )
        return Response('{"entries": []}', content_type="application/json")

    def content_put(request):
        bodies.append(request.get_data())
        # A gateway timeout the first time means the whole file goes again
        if len(bodies) == 1:
            return Response("", status=504)
        return Response("", status=200)

    httpserver.expect_request(
        "/records/abc/draft/files", method="POST"
    ).respond_with_handler(init)
    httpserver.expect_request(
        "/records/abc/draft/files/archive.zip/content", method="PUT"
    ).respond_with_handler(content_put)
    httpserver.expect_request(
        "/records/abc/draft/files/archive.zip/commit", method="POST"
    ).respond_with_json({})
    progress = []
    calkit.invenio.upload_file(
        "abc", str(fpath), progress=lambda done, total: progress.append(done)
    )
    assert [("transfer" in e) for e in inits] == [True, False]
    assert bodies == [content, content]
    assert progress[-1] == 2500


def test_get_part_size(monkeypatch):
    mib = 1024 * 1024
    part = calkit.invenio.MULTIPART_PART_SIZE
    assert calkit.invenio.get_part_size(10 * mib) == part
    # A file too big for the part limit at the default size gets bigger parts
    huge = part * calkit.invenio.MULTIPART_MAX_PARTS * 3
    size = calkit.invenio.get_part_size(huge)
    assert size % mib == 0
    assert -(-huge // size) <= calkit.invenio.MULTIPART_MAX_PARTS
