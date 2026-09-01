"""Tests for the shared cache."""

import app.cache


def _reset_client(monkeypatch, client) -> None:
    monkeypatch.setattr(app.cache, "_client", client)
    monkeypatch.setattr(app.cache, "_client_ready", True)
    monkeypatch.setattr(app.cache, "_warned", False)


def test_cache_never_raises(monkeypatch):
    # Not configured: every read misses and every write is dropped, so a
    # deployment without a cache behaves like one whose cache is empty
    _reset_client(monkeypatch, None)
    assert app.cache.get_json("k") is None
    app.cache.set_json("k", {"a": 1})

    # Configured and working: values survive a round trip
    class _Store:
        def __init__(self) -> None:
            self.data: dict[str, bytes] = {}

        def get(self, key):
            return self.data.get(key)

        def set(self, key, value, ex=None):
            self.data[key] = value

        def delete(self, key):
            self.data.pop(key, None)

    store = _Store()
    _reset_client(monkeypatch, store)
    app.cache.set_json("k", {"a": [1, 2], "b": None})
    assert app.cache.get_json("k") == {"a": [1, 2], "b": None}
    assert app.cache.get_json("missing") is None

    # A value nothing can parse is dropped rather than returned or raised
    store.data["bad"] = b"not json"
    assert app.cache.get_json("bad") is None
    assert "bad" not in store.data

    # The cache being down is not the API being down
    class _Broken:
        def get(self, key):
            raise ConnectionError("cache is down")

        def set(self, key, value, ex=None):
            raise ConnectionError("cache is down")

    _reset_client(monkeypatch, _Broken())
    assert app.cache.get_json("k") is None
    app.cache.set_json("k", {"a": 1})


def test_cache_keys_are_namespaced():
    key = app.cache.make_key("stage-status", "abc123")
    assert key.startswith("ck:")
    assert key.endswith(":stage-status:abc123")
    # The environment is in the key, so two deployments sharing one cache
    # can't answer each other's reads
    assert app.cache.make_key("x") != "ck:x"


def test_parse_bib_entries_is_cached_on_its_text(monkeypatch):
    import app.api.routes.projects.core as core

    class _Store:
        def __init__(self) -> None:
            self.data: dict[str, bytes] = {}
            self.reads = 0

        def get(self, key):
            self.reads += 1
            return self.data.get(key)

        def set(self, key, value, ex=None):
            self.data[key] = value

        def delete(self, key):
            self.data.pop(key, None)

    store = _Store()
    _reset_client(monkeypatch, store)
    parses = {"n": 0}
    real_loads = core.bibtexparser.loads

    def counting_loads(text):
        parses["n"] += 1
        return real_loads(text)

    monkeypatch.setattr(core.bibtexparser, "loads", counting_loads)
    bib = "@article{a_2020, title={A}, year={2020}}"
    first = core.parse_bib_entries(bib)
    assert [e["ID"] for e in first] == ["a_2020"]
    assert parses["n"] == 1
    # The same bytes come back from the cache rather than the parser, whether
    # that is a repeat read or one of the copies of a shared .bib that a
    # multi-paper project keeps per publication
    assert core.parse_bib_entries(bib) == first
    assert parses["n"] == 1
    # Different bytes are a different entry
    core.parse_bib_entries("@book{b_2021, title={B}, year={2021}}")
    assert parses["n"] == 2
    assert len(store.data) == 2
    # With no cache configured it still parses, just every time
    _reset_client(monkeypatch, None)
    assert core.parse_bib_entries(bib) == first
    assert parses["n"] == 3
