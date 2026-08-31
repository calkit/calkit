"""Tests for calkit.provenance."""

import os
from unittest.mock import MagicMock, patch

import pytest

from calkit.provenance import verify_or_download_url


def _make_response(content: bytes):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.iter_content = MagicMock(return_value=iter([content]))
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_verify_or_download_url_missing_file(tmp_path):
    dest = str(tmp_path / "data" / "file.csv")
    content = b"col1,col2\n1,2\n"
    with patch("requests.get", return_value=_make_response(content)):
        downloaded, sha = verify_or_download_url(
            "https://example.org/file.csv", dest
        )
    assert downloaded is True
    assert os.path.isfile(dest)
    with open(dest, "rb") as f:
        assert f.read() == content
    assert len(sha) == 64


def test_verify_or_download_url_existing_matching(tmp_path):
    content = b"col1,col2\n1,2\n"
    dest = str(tmp_path / "file.csv")
    with open(dest, "wb") as f:
        f.write(content)
    with patch("requests.get", return_value=_make_response(content)):
        downloaded, sha = verify_or_download_url(
            "https://example.org/file.csv", dest
        )
    assert downloaded is False
    with open(dest, "rb") as f:
        assert f.read() == content


def test_verify_or_download_url_existing_mismatch(tmp_path):
    dest = str(tmp_path / "file.csv")
    with open(dest, "wb") as f:
        f.write(b"old content")
    with patch("requests.get", return_value=_make_response(b"new content")):
        with pytest.raises(ValueError, match="does not match"):
            verify_or_download_url("https://example.org/file.csv", dest)
    with open(dest, "rb") as f:
        assert f.read() == b"old content"


def test_verify_or_download_url_http_error(tmp_path):
    import requests

    dest = str(tmp_path / "file.csv")
    resp = MagicMock()
    resp.raise_for_status = MagicMock(side_effect=requests.HTTPError("404"))
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    with patch("requests.get", return_value=resp):
        with pytest.raises(requests.HTTPError):
            verify_or_download_url("https://example.org/file.csv", dest)
    assert not os.path.exists(dest)


def test_verify_or_download_url_no_temp_left_on_interrupt(tmp_path):
    import requests

    dest = str(tmp_path / "file.csv")
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.iter_content = MagicMock(side_effect=requests.ConnectionError("drop"))
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    with patch("requests.get", return_value=resp):
        with pytest.raises(requests.ConnectionError):
            verify_or_download_url("https://example.org/file.csv", dest)
    assert not any(tmp_path.iterdir())


def test_verify_or_download_url_max_bytes(tmp_path):
    dest = str(tmp_path / "big.bin")
    with patch("requests.get", return_value=_make_response(b"x" * 100)):
        with pytest.raises(ValueError, match="byte limit"):
            verify_or_download_url(
                "https://example.org/big.bin", dest, max_bytes=10
            )
    assert not os.path.exists(dest)


def test_verify_or_download_url_path_is_directory(tmp_path):
    dest = str(tmp_path)
    with pytest.raises(ValueError, match="directory"):
        verify_or_download_url("https://example.org/file.csv", dest)
