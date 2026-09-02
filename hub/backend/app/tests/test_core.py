"""Tests for the ``core`` module."""

import subprocess

from app.core import read_last_line_from_csv


def test_read_last_line_from_csv(tmp_dir):
    # The identity `calkit init` commits with comes from the throwaway global
    # config the isolate_git_config fixture points git at
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        ["calkit", "new", "status", "completed", "-m", "This is the status."]
    )
    last_line = read_last_line_from_csv(".calkit/status.csv")
    assert last_line[1] == "completed"
    assert last_line[-1] == "This is the status."


def test_parse_featured_projects():
    """Slugs are normalized, deduped, and anything malformed is dropped."""
    from app.config import parse_featured_projects

    assert parse_featured_projects(None) == []
    assert parse_featured_projects("") == []
    # A comma-separated string is the environment-variable form.
    assert parse_featured_projects("calkit/example-basic,Foo/Bar") == [
        "calkit/example-basic",
        "foo/bar",
    ]
    # Surrounding whitespace and slashes are cosmetic, not part of the slug.
    assert parse_featured_projects([" calkit/example-basic ", "/a/b/"]) == [
        "calkit/example-basic",
        "a/b",
    ]
    # One bad entry drops out rather than taking the landing page with it.
    assert parse_featured_projects(["justaname", "a/b/c", "", "a/b"]) == [
        "a/b"
    ]
    # The same project listed twice is shown once.
    assert parse_featured_projects(["a/b", "A/B"]) == ["a/b"]
