"""Tests for the ``core`` module."""

import calkit


def test_find_project_dirs():
    calkit.find_project_dirs()
    assert calkit.find_project_dirs(relative=False)
