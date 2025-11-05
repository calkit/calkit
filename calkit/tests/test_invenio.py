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
