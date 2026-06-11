"""Tests for ``calkit.models.core``."""

import pytest
from pydantic import ValidationError

from calkit.models.core import ProjectInfo, Publication


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
