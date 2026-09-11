"""Tests for the ``invenio`` module."""

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
