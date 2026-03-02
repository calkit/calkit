"""Tests for the Calkit filesystem implementation."""

import pytest

from calkit import fs


def test_parse_path_simple():
    """Test parsing a simple path without explicit domain."""
    owner, project, file_path = fs._parse_path("ck://owner/project/file.txt")
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"


def test_parse_path_simple_no_file():
    """Test parsing path with just owner/project."""
    owner, project, file_path = fs._parse_path("ck://owner/project")
    assert owner == "owner"
    assert project == "project"
    assert file_path == ""


def test_parse_path_nested_file():
    """Test parsing path with nested file structure."""
    owner, project, file_path = fs._parse_path(
        "ck://owner/project/data/nested/file.txt"
    )
    assert owner == "owner"
    assert project == "project"
    assert file_path == "data/nested/file.txt"


def test_parse_path_explicit_domain():
    """Test parsing path with explicit domain."""
    owner, project, file_path = fs._parse_path(
        "ck://calkit.io/owner/project/file.txt"
    )
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"


def test_parse_path_staging_domain():
    """Test parsing path with staging domain."""
    owner, project, file_path = fs._parse_path(
        "ck://staging.calkit.io/owner/project/file.txt"
    )
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"


def test_parse_path_localhost_domain():
    """Test parsing path with localhost domain."""
    owner, project, file_path = fs._parse_path(
        "ck://localhost:8000/owner/project/file.txt"
    )
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"


def test_parse_path_protocol_stripped():
    """Test parsing protocol-stripped path."""
    owner, project, file_path = fs._parse_path("owner/project/file.txt")
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"


def test_parse_path_protocol_stripped_localhost():
    """Test parsing protocol-stripped path with localhost."""
    owner, project, file_path = fs._parse_path(
        "localhost:8000/owner/project/file.txt"
    )
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"


def test_parse_path_invalid_no_project():
    """Test that invalid paths raise ValueError."""
    with pytest.raises(ValueError, match="Invalid path format"):
        fs._parse_path("ck://owner")


def test_parse_path_invalid_empty():
    """Test that empty path raises ValueError."""
    with pytest.raises(ValueError, match="Invalid path format"):
        fs._parse_path("ck://")
