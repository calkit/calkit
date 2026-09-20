"""Tests for ``calkit.templates``."""

import calkit
from calkit.templates.latex import GITIGNORE as LATEX_GITIGNORE


def test_use_template(tmp_dir):
    calkit.templates.use_template("latex/article", "paper", title="Cool title")
    with open("paper/paper.tex") as f:
        txt = f.read()
    assert r"\title{Cool title}" in txt
    with open("paper/.gitignore") as f:
        txt = f.read()
    assert txt == LATEX_GITIGNORE


def test_get_templates():
    # The registry lists what's known, by kind, in the order to offer it.
    import pytest

    projects = calkit.templates.get_templates(kind="project")
    assert [t.ref for t in projects][0] == "calkit/example-basic"
    assert {t.kind for t in projects} == {"project"}
    # Every one says what it is, since a picker shows both
    assert all(t.title and t.description for t in projects)
    latex = calkit.templates.get_templates(kind="latex")
    assert "latex/article" in [t.ref for t in latex]
    # No kind is every kind, and nothing is listed twice
    every = calkit.templates.get_templates()
    refs = [t.ref for t in every]
    assert len(refs) == len(set(refs)) == len(projects) + len(latex)
    with pytest.raises(ValueError):
        calkit.templates.get_templates(kind="not-a-kind")


def test_project_templates_know_where_they_live():
    # A project template carries its locations, so nothing has to ask. ``calkit
    # new project --from calkit/example-r`` resolves the repo from here rather
    # than querying a hub, which is what makes it work without being logged in.
    template = calkit.templates.find_template(
        "calkit/example-r", kind="project"
    )
    assert template is not None
    assert template.git_repo_url == "https://github.com/calkit/example-r"
    assert template.loc == "https://calkit.io/calkit/example-r"
    assert template.owner == "calkit"
    # A ref names a project the way a hub does, not the way this package
    # namespaces its own templates
    assert template.ref == "calkit/example-r"
    assert calkit.templates.find_template("latex/jfm").ref == "latex/jfm"
    # Anything unregistered falls through to whatever asks next
    assert calkit.templates.find_template("someone/their-repo") is None
    assert (
        calkit.templates.find_template("calkit/example-r", kind="latex")
        is None
    )


def test_use_template_refuses_a_project_template(tmp_dir):
    # There are no files here to copy; starting one is the hub's job.
    import pytest

    with pytest.raises(NotImplementedError, match="calkit.io"):
        calkit.templates.use_template("calkit/example-r", "somewhere")
