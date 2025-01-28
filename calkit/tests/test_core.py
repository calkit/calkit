"""Tests for the ``core`` module."""

import calkit


def test_find_project_dirs():
    calkit.find_project_dirs()
    assert calkit.find_project_dirs(relative=False)


def test_to_kebab_case():
    assert calkit.to_kebab_case("THIS IS") == "this-is"
    assert calkit.to_kebab_case("this_is_my-Project") == "this-is-my-project"
