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
