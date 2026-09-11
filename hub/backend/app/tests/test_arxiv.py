"""Tests for ``app.arxiv``."""

from app import arxiv


def test_is_id() -> None:
    assert arxiv.is_id("2301.01234")
    assert arxiv.is_id("2301.01234v2")
    assert arxiv.is_id("math.GT/0309136")
    # A DOI or a URL is not an ID; the PDF proxy relies on this to keep from
    # fetching arbitrary hosts.
    assert not arxiv.is_id("10.1038/nature12373")
    assert not arxiv.is_id("https://arxiv.org/abs/2301.01234")
    assert not arxiv.is_id("../../etc/passwd")
    assert not arxiv.is_id("")


def test_id_from_bib_attrs_eprint() -> None:
    """arXiv's own BibTeX export puts the ID in ``eprint``."""
    assert (
        arxiv.id_from_bib_attrs(
            {
                "eprint": "1706.03762",
                "archivePrefix": "arXiv",
                "primaryClass": "cs.CL",
            }
        )
        == "1706.03762"
    )
    # A preprint on another server also uses ``eprint``, so the archive
    # matters
    assert (
        arxiv.id_from_bib_attrs(
            {"eprint": "2021.01.01.425001", "archivePrefix": "bioRxiv"}
        )
        is None
    )


def test_id_from_bib_attrs_url() -> None:
    """Zotero writes the abs page into ``url``."""
    assert (
        arxiv.id_from_bib_attrs({"url": "https://arxiv.org/abs/2301.01234v3"})
        == "2301.01234v3"
    )
    assert (
        arxiv.id_from_bib_attrs({"note": "arXiv:math.GT/0309136"})
        == "math.GT/0309136"
    )
    # A URL that isn't arXiv's must not be mined for anything ID-shaped
    assert (
        arxiv.id_from_bib_attrs({"url": "https://example.com/2301.01234"})
        is None
    )


def test_id_from_bib_attrs_doi() -> None:
    """A publisher's entry may carry only the minted DOI."""
    assert (
        arxiv.id_from_bib_attrs({"doi": "10.48550/arXiv.2606.23755"})
        == "2606.23755"
    )
    assert arxiv.id_from_bib_attrs({"doi": "10.1038/nature12373"}) is None


def test_id_from_bib_attrs_absent() -> None:
    assert arxiv.id_from_bib_attrs({}) is None
    assert (
        arxiv.id_from_bib_attrs({"title": "A paper", "year": "2026"}) is None
    )
