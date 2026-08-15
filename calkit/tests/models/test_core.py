"""Tests for ``calkit.models.core``."""

import pytest
from pydantic import ValidationError

from calkit.models.core import (
    ProjectInfo,
    Publication,
    Question,
    ShowcaseApp,
    ShowcaseFigure,
    StaticHtmlApp,
)


def test_publication_kind_no_longer_allows_presentation():
    # Presentations are a separate top-level concept now.
    with pytest.raises(ValidationError):
        Publication(path="p.pdf", title="P", kind="presentation")
    # A normal kind still validates.
    Publication(path="p.pdf", title="P", kind="journal-article")


def test_project_info_has_results_and_presentations():
    info = ProjectInfo.model_validate(
        {
            "results": [{"path": "results/metrics.json", "title": "Metrics"}],
            "presentations": [{"path": "slides/talk.pdf", "title": "Talk"}],
        }
    )
    assert info.results[0].path == "results/metrics.json"
    assert info.presentations[0].path == "slides/talk.pdf"


def test_project_info_hub():
    # Not declaring a hub is valid and means the default (calkit.io)
    info = ProjectInfo.model_validate({"title": "T"})
    assert info.hub is None
    # A declared hub is a full base URL and round-trips
    info = ProjectInfo.model_validate({"hub": "https://calkit.io"})
    assert info.hub == "https://calkit.io"
    assert info.model_dump()["hub"] == "https://calkit.io"


def test_question_accepts_publication_evidence():
    q = Question.model_validate(
        {
            "question": "Does the paper support this?",
            "answer": "Yes.",
            "evidence": [
                {"kind": "publication", "path": "paper/paper.pdf"},
                {
                    "kind": "publication",
                    "path": "paper/supplement.pdf",
                    "explanation": "See Table 1.",
                },
            ],
        }
    )
    assert q.evidence is not None
    assert q.evidence[0].kind == "publication"
    assert q.evidence[0].path == "paper/paper.pdf"
    assert q.evidence[1].explanation == "See Table 1."


def test_apps():
    info = ProjectInfo.model_validate(
        {
            "apps": {
                "naca0012": {
                    "kind": "static-html",
                    "path": "app/index.html",
                    "title": "NACA 0012 explorer",
                    "stage": "build-app",
                }
            },
            "showcase": [{"app": "naca0012"}, {"figure": "figures/clcd.json"}],
        }
    )
    app = info.apps["naca0012"]
    assert isinstance(app, StaticHtmlApp)
    # The path names the HTML file, and its parent is the serving root
    assert app.path == "app/index.html"
    assert app.serve_dir == "app"
    assert app.stage == "build-app"
    # An app at the repo root serves from there rather than blowing up
    assert StaticHtmlApp(path="index.html").serve_dir == "."
    # The path names the entrypoint file, so anything that isn't one leaves
    # nothing to serve and no root to serve it from
    for bad in [".", "", "app", "app/", "/tmp/x.html", "../x.html"]:
        with pytest.raises(ValidationError):
            StaticHtmlApp(path=bad)
    # Apps can be showcased by key, alongside the existing entry kinds
    assert info.showcase is not None
    assert isinstance(info.showcase[0], ShowcaseApp)
    assert info.showcase[0].app == "naca0012"
    assert isinstance(info.showcase[1], ShowcaseFigure)
    # Apps are served from the project, so there is no URL to point
    # elsewhere and nothing embeds an arbitrary one
    with pytest.raises(ValidationError):
        StaticHtmlApp.model_validate(
            {"path": "app/index.html", "url": "https://example.com"}
        )
    with pytest.raises(ValidationError):
        ProjectInfo.model_validate(
            {"apps": {"legacy": {"kind": "external", "url": "https://x.io"}}}
        )
