"""Tests for ``calkit.references``."""

import io
import json
from pathlib import Path

import pytest

import calkit.references as refs

BIB = r"""
@article{real2020thing,
    author  = {Vega, Ana and Bloom, Lee},
    title   = {A Study of Something {R}eal},
    journal = {Journal of Things},
    year    = {2020},
    doi     = {10.1000/real}
}

@inproceedings{thin2021venue,
    author    = {Okafor, Chidi},
    title     = {Nested {B}races, and a Comma, in One Title},
    booktitle = {Proceedings of Machine Learning Research},
    year      = {2021}
}

@misc{tool2024software,
    author       = {{Some Laboratory}},
    title        = {ToolName: a simulation tool},
    howpublished = {\url{https://github.com/example/tool}},
    year         = {2024}
}

@misc{preprint2019arxiv,
    author        = {Rossi, Gio},
    title         = {Something Posted as a Preprint First},
    year          = {2019},
    eprint        = {1901.00001},
    archivePrefix = {arXiv}
}
"""


@pytest.fixture
def tmp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fixture to change to a temporary directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _project(tmp_path: Path, tex: str, bib: str = BIB) -> None:
    (tmp_path / "paper").mkdir(exist_ok=True)
    (tmp_path / "paper" / "main.tex").write_text(tex)
    (tmp_path / "paper" / "references.bib").write_text(bib)
    (tmp_path / "calkit.yaml").write_text(
        "pipeline:\n"
        "  stages:\n"
        "    paper:\n"
        "      kind: latex\n"
        "      target_path: paper/main.tex\n"
        "      environment: tex\n"
        "references:\n"
        "  - path: paper/references.bib\n"
    )


def test_bib_fields_and_entry_metadata(tmp_dir: Path) -> None:
    _project(tmp_dir, "\\citep{real2020thing}\n")
    collections = refs.load_collections()
    entries = collections["paper/references.bib"]
    assert set(entries) == {
        "real2020thing",
        "thin2021venue",
        "tool2024software",
        "preprint2019arxiv",
    }
    # A title with nested braces and a comma survives, which a regex over
    # the whole entry gets wrong.
    assert "Nested Braces, and a Comma" in refs.clean_tex(
        entries["thin2021venue"]["title"]
    )
    reference = refs.Reference(key="tool2024software")
    refs._fill_from_entry(reference, entries["tool2024software"])
    assert reference.url == "https://github.com/example/tool"
    assert reference.venue is None
    preprint = refs.Reference(key="preprint2019arxiv")
    refs._fill_from_entry(preprint, entries["preprint2019arxiv"])
    assert preprint.arxiv == "1901.00001"
    article = refs.Reference(key="real2020thing")
    refs._fill_from_entry(article, entries["real2020thing"])
    assert article.doi == "10.1000/real"
    assert article.first_author == "Vega"
    assert article.year == 2020
    assert article.venue == "Journal of Things"


def test_keys_come_from_the_source_not_its_comments(tmp_dir: Path) -> None:
    _project(
        tmp_dir,
        "Text \\citep{real2020thing}.\n"
        "% A note about \\citep{commented}.\n"
        "Two at once \\citep{thin2021venue,tool2024software}.\n"
        "A literal \\% then \\citet[p.~2]{preprint2019arxiv}.\n",
    )
    from calkit.latex import flatten

    keys = refs.cited_keys(flatten("paper/main.tex"))
    assert "commented" not in keys
    assert set(keys) == {
        "real2020thing",
        "thin2021venue",
        "tool2024software",
        "preprint2019arxiv",
    }
    # Each key records where it is cited, so a report can point at it.
    assert keys["real2020thing"] == ["paper/main.tex:1"]
    # biblatex's commands and multicite forms, capitalized and starred
    # ones, and a citation split across lines all count, while a command
    # that merely starts with "cite" and a macro's parameter don't
    _project(
        tmp_dir,
        "\\citestyle{authoryear}\n"
        "\\parencite{a} \\textcite*{b} \\Citep[see][]{c}\n"
        "\\citep{d,\n"
        "  e} \\autocites(all)[p.~1]{f}[2]{g}\n"
        "\\newcommand{\\mycite}[1]{\\cite{#1}} \\nocite{*}\n",
    )
    keys = refs.cited_keys(flatten("paper/main.tex"))
    assert list(keys) == ["a", "b", "c", "d", "e", "f", "g", "*"]
    assert keys["e"] == ["paper/main.tex:4"]


def test_statuses_separate_what_is_wrong_from_what_is_unknown(
    tmp_dir: Path,
) -> None:
    # A key in no collection cannot resolve, and fails the check.
    missing = refs.Reference(key="ghost")
    refs.classify(missing)
    assert missing.status == "missing-from-bib"
    assert missing.status in refs.BLOCKING
    # An identifier resolving to another work is the signature of an
    # invented citation, and also fails.
    swapped = refs.Reference(
        key="k",
        collection="refs.bib",
        title="A Study of Something Real",
        first_author="Vega",
        year=2020,
        doi="10.1000/real",
    )
    swapped.found = refs.compare(
        swapped,
        refs.Found(
            source="crossref-doi",
            doi="10.1000/real",
            title="An Entirely Different Paper About Turbines",
            year=2011,
            first_author="Nobody",
        ),
    )
    refs.classify(swapped)
    assert swapped.status == "mismatch"
    assert any("different work" in n for n in swapped.notes)
    assert swapped.status in refs.BLOCKING
    # Software has no registered record, so its absence proves nothing.
    software = refs.Reference(
        key="tool",
        collection="refs.bib",
        title="ToolName: a simulation tool",
        url="https://github.com/example/tool",
    )
    refs.classify(software)
    assert software.status == "not-checkable"
    assert software.status not in refs.BLOCKING
    # Neither does absence from a venue nobody indexes.
    thin = refs.Reference(
        key="k",
        collection="refs.bib",
        title="Hypervolume Knowledge Gradient",
        venue="Proceedings of the 40th International Conference on Machine "
        "Learning",
        year=2023,
    )
    refs.classify(thin)
    assert thin.status == "not-found"
    assert any("coverage gap" in n for n in thin.notes)
    assert thin.status not in refs.BLOCKING


def test_a_key_in_two_collections_names_the_one_that_wins(
    tmp_dir: Path,
) -> None:
    # One collection is the normal case, so the report names it rather
    # than wrapping it in a list. More than one is worth saying, because
    # which entry BibTeX uses then depends on their declared order.
    _project(tmp_dir, "\\citep{real2020thing}\n")
    (tmp_dir / "paper" / "extra.bib").write_text(
        "@misc{real2020thing, title = {A Different Entry}, year = {1999}}\n"
    )
    (tmp_dir / "calkit.yaml").write_text(
        (tmp_dir / "calkit.yaml").read_text() + "  - path: paper/extra.bib\n"
    )
    check = refs.check_references("paper/main.tex", offline=True)
    reference = check.references["real2020thing"]
    assert reference.collection == "paper/references.bib"
    assert reference.also_in == ["paper/extra.bib"]
    assert any("also defined in" in n for n in reference.notes)
    # The entry used is the winning collection's, not the other one.
    assert reference.year == 2020


def test_an_unregistered_doi_is_decisive(tmp_dir: Path) -> None:
    # The handle system registers every DOI whatever the registrar, so a
    # handle it doesn't have cannot be a real identifier. This is the one
    # unambiguous sign of an invented citation, so it fails the check,
    # unlike a work that merely isn't indexed anywhere.
    reference = refs.Reference(
        key="ghost",
        collection="refs.bib",
        title="A Paper That Was Never Written",
        year=2021,
        doi="10.9999/definitely-not-real",
        doi_registered=False,
    )
    refs.classify(reference)
    assert reference.status == "doi-not-registered"
    assert reference.status in refs.BLOCKING
    assert any("handle system" in n for n in reference.notes)
    # Unreachable is not the same answer as unregistered.
    unknown = refs.Reference(
        key="k",
        collection="refs.bib",
        title="A Real Paper Nobody Indexed",
        doi="10.1000/real",
        doi_registered=None,
    )
    refs.classify(unknown)
    assert unknown.status == "not-found"
    assert unknown.status not in refs.BLOCKING
    # A registered DOI whose record wasn't found says so differently from
    # one that couldn't be resolved at all.
    registered = refs.Reference(
        key="k",
        collection="refs.bib",
        title="A Real Paper Nobody Indexed",
        doi="10.1000/real",
        doi_registered=True,
    )
    refs.classify(registered)
    assert registered.status == "not-found"
    assert any("is registered" in n for n in registered.notes)


def test_handle_responses_map_to_an_answer(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lookup = refs.Lookup(offline=True)
    url = "https://doi.org/api/handles/10.1000/real"
    lookup.cache[url] = json.dumps({"responseCode": 1, "handle": "x"})
    assert lookup.doi_registered("10.1000/real") is True
    lookup.cache[url] = json.dumps({"responseCode": 100, "handle": "x"})
    assert lookup.doi_registered("10.1000/real") is False
    # Anything else is the service having trouble, not an answer.
    lookup.cache[url] = json.dumps({"responseCode": 2})
    assert lookup.doi_registered("10.1000/real") is None
    lookup.cache[url] = None
    assert lookup.doi_registered("10.1000/real") is None
    # No answer, e.g., without a network or when rate limited, isn't
    # cached, so the next run asks again
    import urllib.error
    from email.message import Message

    def fail(request, timeout):
        raise urllib.error.URLError("no network")

    online = refs.Lookup()
    online.cache = {"https://kept.example": "old"}
    monkeypatch.setattr("urllib.request.urlopen", fail)
    monkeypatch.setattr(refs, "REQUEST_DELAY_S", 0)
    assert online.get_text("https://down.example") is None
    assert online.unanswered == 1
    assert "https://down.example" not in online.cache

    def rate_limited(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 429, "", Message(), None
        )

    monkeypatch.setattr("urllib.request.urlopen", rate_limited)
    assert online.get_text("https://busy.example") is None
    assert "https://busy.example" not in online.cache
    # Refreshing asks again, but keeps what this run didn't need
    refreshed = refs.Lookup(refresh=True)
    refreshed.cache = {"https://kept.example": "old", "https://a.example": "x"}
    assert refreshed.get_text("https://a.example") is None
    assert refreshed.cache["https://kept.example"] == "old"
    # The cache is saved where Git ignores it
    refreshed.asked.add("https://kept.example")
    refreshed.save()
    assert (tmp_dir / ".calkit" / "local" / ".gitignore").read_text() == "*\n"
    assert (tmp_dir / refs.CACHE_PATH).is_file()
    # A record of responses reuses what it has, and keeps only what this
    # run used, so it says what a check was based on
    record = "checks/main.responses.json"
    (tmp_dir / "checks").mkdir()
    (tmp_dir / record).write_text(
        json.dumps({"https://used.example": "a", "https://stale.example": "b"})
    )

    def answer(request: object, timeout: float) -> io.BytesIO:
        return io.BytesIO(b"new")

    monkeypatch.setattr("urllib.request.urlopen", answer)
    recording = refs.Lookup(responses_path=record)
    assert recording.get_text("https://used.example") == "a"
    assert recording.get_text("https://new.example") == "new"
    assert recording.calls == 1
    recording.save()
    assert json.loads((tmp_dir / record).read_text()) == {
        "https://new.example": "new",
        "https://used.example": "a",
    }
    # Run again offline, it gives the same answers, and is written even
    # when nothing new was asked, since it's an output
    (tmp_dir / record).write_text(json.dumps({"https://used.example": "a"}))
    replay = refs.Lookup(offline=True, responses_path=record)
    assert replay.get_text("https://used.example") == "a"
    assert replay.unanswered == 0
    (tmp_dir / record).unlink()
    replay.save()
    assert json.loads((tmp_dir / record).read_text()) == {
        "https://used.example": "a"
    }


def test_comparison_forgives_only_what_it_should(tmp_dir: Path) -> None:
    # An entry citing the published version, matched to its preprint, has
    # a year that says nothing about whether the work is real.
    published = refs.Reference(
        key="k",
        title="Hyperband: A Novel Bandit-Based Approach to Hyperparameter "
        "Optimization",
        first_author="Li",
        year=2018,
    )
    found = refs.compare(
        published,
        refs.Found(
            source="openalex",
            doi="10.48550/arxiv.1603.06560",
            title="Hyperband: A Novel Bandit-Based Approach to "
            "Hyperparameter Optimization",
            year=2016,
            first_author="Li",
        ),
    )
    assert found.title_matches is True
    assert found.year_matches is None
    published.found = found
    published.collection = "refs.bib"
    refs.classify(published)
    assert published.status == "verified"
    # Two different papers in the same year by the same author do not pass.
    other = refs.Reference(
        key="k", title="A Study of Something Real", year=2020
    )
    mismatched = refs.compare(
        other,
        refs.Found(
            source="crossref",
            title="A Totally Unrelated Investigation",
            year=2020,
        ),
    )
    assert mismatched.title_matches is False
    # An accent written in TeX matches the record's Unicode one, however
    # short the surname
    accented = refs.Reference(key="k")
    refs._fill_from_entry(
        accented,
        {"author": '{\\"O}z, Ali', "doi": "https://doi.org/10.1/a\\_b"},
    )
    assert accented.doi == "10.1/a_b"
    assert refs.compare(
        accented, refs.Found(source="crossref", first_author="Öz")
    ).author_matches
    assert refs.normalize_doi("doi:10.1/X") == "10.1/X"
    assert refs.normalize_doi("  ") is None
    # A title too short to discriminate is left uncompared rather than
    # guessed at.
    short = refs.Reference(key="k", title="Wind")
    assert (
        refs.compare(
            short, refs.Found(source="crossref", title="Wind")
        ).title_matches
        is None
    )


def test_a_failed_title_search_is_not_a_disagreement(tmp_dir: Path) -> None:
    # The nearest neighbor of a query that matched nothing is discarded,
    # since reporting it accuses the entry of describing another paper.
    reference = refs.Reference(
        key="k",
        collection="refs.bib",
        title="Hypervolume Knowledge Gradient for Partial Information",
        year=2023,
    )
    lookup = refs.Lookup(offline=True)
    lookup.cache = {}
    refs.verify(reference, lookup)
    assert reference.found is None
    title = "Large Eddy Simulation of Wind Farm Wakes"

    class Stub:
        offline = False
        unanswered = 0

        def __init__(self, by_doi=None, datacite=None, by_title=None):
            self.by_doi, self.datacite, self.by_title = (
                by_doi,
                datacite,
                by_title,
            )

        def crossref_doi(self, doi):
            return self.by_doi

        def datacite_doi(self, doi):
            return self.datacite

        def doi_registered(self, doi):
            return True

        def arxiv(self, eprint):
            return None

        def crossref_title(self, title):
            return self.by_title

        def openalex_title(self, title):
            return None

    def entry():
        return refs.Reference(
            key="k",
            collection="refs.bib",
            title=title,
            first_author="Smith",
            year=2020,
            doi="10.9/wrong",
        )

    def right():
        return refs.Found(
            source="crossref",
            doi="10.9/right",
            title=title,
            year=2020,
            first_author="Smith",
        )

    # A DOI naming another work is the finding, even though a search for
    # the title finds the right one, which the report points at
    wrong = refs.Found(
        source="crossref-doi",
        doi="10.9/wrong",
        title="Soil Chemistry of an Unrelated Field Site",
        year=2001,
        first_author="Nguyen",
    )
    reference = entry()
    refs.verify(reference, Stub(by_doi=wrong, by_title=right()))  # type: ignore[arg-type]
    refs.classify(reference)
    assert reference.status == "mismatch"
    assert any("https://doi.org/10.9/right" in n for n in reference.notes)
    # A DOI Crossref doesn't have, e.g., a Zenodo one, is found in DataCite
    reference = entry()
    zenodo = right()
    zenodo.source = "datacite-doi"
    refs.verify(reference, Stub(datacite=zenodo))  # type: ignore[arg-type]
    refs.classify(reference)
    assert reference.status == "verified"
    assert reference.evidence is not None
    assert reference.evidence.source == "datacite"
    assert reference.evidence.matched_by == "doi"
    # A title that only resembles the entry's is a failed search, pointed
    # at but not a disagreement
    reference = entry()
    reference.doi = None
    near = right()
    near.title = "Large Eddy Simulation of Wind Turbine Arrays"
    refs.verify(reference, Stub(by_title=near))  # type: ignore[arg-type]
    refs.classify(reference)
    assert reference.status == "not-found"
    assert any("closest title" in n for n in reference.notes)
    # A search finding the same title in another year may have found
    # another edition, a reprint, or a review, so it's pointed at instead
    reference = entry()
    reference.doi = None
    edition = right()
    edition.year = 2011
    refs.verify(reference, Stub(by_title=edition))  # type: ignore[arg-type]
    refs.classify(reference)
    assert reference.status == "not-found"
    assert reference.evidence is None
    assert any("another edition" in n and "2011" in n for n in reference.notes)
    # A whole name in either order agrees, as OpenAlex can give one
    reference = entry()
    reference.doi = None
    named = right()
    named.first_author = "Smith Jane"
    refs.verify(reference, Stub(by_title=named))  # type: ignore[arg-type]
    refs.classify(reference)
    assert reference.status == "verified"
    # Crossref titles can carry markup, which isn't part of the title
    found = refs._from_crossref(
        {
            "title": [
                "A Proof for the Queuing Formula:\n  <i>L</i>\n  = λ <i>W</i>"
            ]
        }
    )
    assert found.title == "A Proof for the Queuing Formula: L = λ W"
    little = refs.Reference(
        key="k",
        title=refs.clean_tex(
            r"A proof for the queuing formula: {$L = \lambda W$}"
        ),
    )
    assert refs.compare(little, found).title_matches is True
    # A subtitle can be the title's second half or a short title, and an
    # issue can be printed years after the work went online
    split = refs._from_crossref(
        {
            "title": ["Graph Sparsity"],
            "subtitle": ["Methods for Very Large Networks"],
            "issued": {"date-parts": [[2015, 8, 10]]},
        }
    )
    online_first = refs._from_crossref(
        {
            "title": ["A parametric model of flow around obstacles"],
            "subtitle": ["Flow model for obstacles"],
            "issued": {"date-parts": [[2014, 12, 22]]},
            "published-print": {"date-parts": [[2016, 1]]},
            "published-online": {"date-parts": [[2014, 12, 22]]},
        }
    )
    assert online_first.alt_years == [2016]
    for found, title, year in [
        (
            split,
            "Graph sparsity: Methods for very large networks",
            2015,
        ),
        (online_first, "A parametric model of flow around obstacles", 2016),
        (online_first, "A parametric model of flow around obstacles", 2014),
    ]:
        compared = refs.compare(
            refs.Reference(key="k", title=title, year=year), found.model_copy()
        )
        assert compared.title_matches is True
        assert compared.year_matches is True
    # Neither of a record's years saves an entry a decade off
    assert (
        refs.compare(
            refs.Reference(key="k", year=2026), online_first.model_copy()
        ).year_matches
        is False
    )


def test_offline_check_reports_what_needs_no_network(tmp_dir: Path) -> None:
    _project(
        tmp_dir,
        "\\citep{real2020thing}\n\\citep{tool2024software}\n\\citep{ghost}\n",
    )
    document = refs.check_references("paper/main.tex", offline=True)
    assert document.path == "paper/main.tex"
    assert document.n_cited == 3
    by_key = document.references
    assert by_key["ghost"].status == "missing-from-bib"
    assert by_key["ghost"].collection is None
    assert by_key["real2020thing"].collection == "paper/references.bib"
    assert by_key["tool2024software"].status == "not-checkable"
    # Offline, a real entry cannot be confirmed, but it is not accused,
    # nor reported as not found, since nothing was asked
    assert by_key["real2020thing"].status == "unchecked"
    assert any("offline" in n for n in by_key["real2020thing"].notes)
    assert not document.ok
    # Nothing is written unless asked for
    assert not (tmp_dir / ".calkit").exists()
    refs.write_report(document, "report.json")
    payload = json.loads((tmp_dir / "report.json").read_text())
    assert payload["n_cited"] == 3
    # Keyed by citation key, so the key is not repeated as a field.
    assert set(payload["references"]) == {
        "real2020thing",
        "tool2024software",
        "ghost",
    }
    assert "key" not in payload["references"]["ghost"]
    # No timestamp, so the report is a function of its inputs and can be
    # checked for staleness like any other output.
    assert "checked_at" not in payload
    text = refs.format_check(document)
    assert "ghost" in text and "Defined in a bibliography: 2/3 ❌" in text
    # A document naming its bibliography uses it rather than the declared
    # collections, and one that doesn't exist is reported, not skipped
    _project(tmp_dir, "\\citep{real2020thing}\n\\bibliography{refs}\n")
    document = refs.check_references("paper/main.tex", offline=True)
    assert document.collections == ["paper/refs.bib"]
    assert document.references["real2020thing"].status == ("missing-from-bib")
    (tmp_dir / "paper" / "refs.bib").write_text(BIB)
    document = refs.check_references("paper/main.tex", offline=True)
    assert document.references["real2020thing"].status == "unchecked"
    with pytest.raises(FileNotFoundError):
        refs.check_references("typo.tex", offline=True)
    # A PDF is checked through the source a stage builds it from, with
    # paths relative to the stage's working directory, or else through the
    # one beside it
    (tmp_dir / "calkit.yaml").write_text(
        (tmp_dir / "calkit.yaml")
        .read_text()
        .replace(
            "references:\n",
            "    build:\n"
            "      kind: latex\n"
            "      wdir: paper\n"
            "      target_path: main.tex\n"
            "      output_dir: build\n"
            "      environment: tex\n"
            "references:\n",
        )
    )
    for pdf in ["paper/main.pdf", "paper/build/main.pdf"]:
        document = refs.check_references(pdf, offline=True)
        assert document.path == "paper/main.tex"
        assert set(document.references) == {"real2020thing"}
    (tmp_dir / "notes").mkdir()
    (tmp_dir / "notes" / "draft.tex").write_text("\\citep{ghost}\n")
    draft = refs.check_references("notes/draft.pdf", offline=True)
    assert draft.path == "notes/draft.tex"
    with pytest.raises(FileNotFoundError, match="No stage builds"):
        refs.check_references("other.pdf", offline=True)
    # A bibliography has every entry checked, none of them cited anywhere
    document = refs.check_references("paper/refs.bib", offline=True)
    assert document.path == "paper/refs.bib"
    assert document.collections == ["paper/refs.bib"]
    assert set(document.references) == {
        "real2020thing",
        "thin2021venue",
        "tool2024software",
        "preprint2019arxiv",
    }
    assert all(not r.cited_at for r in document.references.values())
    assert document.references["real2020thing"].collection == (
        "paper/refs.bib"
    )
    # \nocite{*} cites every entry, and \bibitem defines a key inline
    _project(
        tmp_dir,
        "\\nocite{*}\\cite{inline}\n"
        "\\begin{thebibliography}{1}\\bibitem{inline} A. Book.\n"
        "\\end{thebibliography}\n",
    )
    by_key = refs.check_references("paper/main.tex", offline=True).references
    assert set(by_key) == {
        "inline",
        "real2020thing",
        "thin2021venue",
        "tool2024software",
        "preprint2019arxiv",
    }
    assert by_key["inline"].status == "not-checkable"
    assert by_key["inline"].collection == "paper/main.tex"


def test_the_report_is_evidence_not_a_copy_of_the_collection(
    tmp_dir: Path,
) -> None:
    # Everything the entry already says stays in the .bib; what the report
    # keeps is that the work was found, and where to go and see it.
    reference = refs.Reference(
        key="k",
        collection="refs.bib",
        title="A Study of Something Real",
        first_author="Vega",
        year=2020,
        doi="10.1000/real",
    )
    reference.found = refs.compare(
        reference,
        refs.Found(
            source="crossref-doi",
            doi="10.1000/real",
            title="A Study of Something Real",
            year=2020,
            first_author="Vega",
        ),
    )
    refs.classify(reference)
    assert reference.status == "verified"
    payload = refs.compact(reference.model_dump(mode="json"))
    assert set(payload) == {"collection", "status", "evidence"}
    assert payload["evidence"] == {
        "matched_by": "doi",
        "source": "crossref",
        "url": "https://doi.org/10.1000/real",
        "agrees_on": ["title", "first-author", "year"],
    }
    # A disagreement is the one place a value is worth repeating, since
    # there the record is the finding.
    swapped = refs.Reference(
        key="k",
        collection="refs.bib",
        title="A Study of Something Real",
        first_author="Vega",
        year=2020,
        doi="10.1000/real",
    )
    swapped.found = refs.compare(
        swapped,
        refs.Found(
            source="crossref-doi",
            doi="10.1000/real",
            title="An Entirely Different Paper",
            year=2011,
            first_author="Nobody",
        ),
    )
    refs.classify(swapped)
    evidence = refs.compact(swapped.model_dump(mode="json"))["evidence"]
    assert evidence["differs"] == {
        "title": "An Entirely Different Paper",
        "first-author": "Nobody",
        "year": 2011,
    }
    assert "agrees_on" not in evidence
    # A title match says how close it was; an identifier match needn't.
    searched = refs.Reference(key="k", collection="refs.bib")
    searched.title = "A Study of Something Real"
    searched.found = refs.compare(
        searched,
        refs.Found(
            source="openalex",
            id="https://openalex.org/W1",
            title="A Study of Something Real",
        ),
    )
    refs.classify(searched)
    assert searched.evidence is not None
    assert searched.evidence.matched_by == "title"
    assert searched.evidence.url == "https://openalex.org/W1"
    assert searched.evidence.title_similarity == 1.0


# The report's serialized shape, recorded so that changing it has to be
# deliberate. A stage type's output is a contract with every project that
# has one committed: when the shape changes, reports already on disk are
# stale and nothing in the pipeline says so, because a stage cannot
# depend on the version of the tool that produced it. Until Calkit
# versions its stage types, this snapshot is the whole guard -- so if it
# fails, either the change was an accident, or every committed report of
# this type needs regenerating.
_DOCUMENT_KEYS = {
    "path",
    "sources",
    "collections",
    "n_cited",
    "n_by_status",
    "references",
}
_EVIDENCE_KEYS = {
    "matched_by",
    "source",
    "url",
    "agrees_on",
    "differs",
    "title_similarity",
}
_REFERENCE_KEYS = {
    "cited_at",
    "collection",
    "also_in",
    "status",
    "evidence",
    "notes",
}


def test_the_report_shape_is_what_was_recorded(tmp_dir: Path) -> None:
    _project(
        tmp_dir,
        "\\citep{real2020thing}\n\\citep{tool2024software}\n\\citep{ghost}\n",
    )
    check = refs.check_references("paper/main.tex", offline=True)
    payload = check.model_dump(mode="json")
    assert set(payload) == _DOCUMENT_KEYS
    # Every key a reference can carry, over every status it can take.
    statuses = set()
    keys: set[str] = set()
    for reference in check.references.values():
        keys |= set(reference.model_dump(mode="json"))
        statuses.add(reference.status)
    # Offline, three of the statuses are reachable; the others need
    # answers, so build one of each.
    verified = refs.Reference(key="k", collection="refs.bib")
    verified.title = "A Study of Something Real"
    verified.found = refs.compare(
        verified,
        refs.Found(
            source="crossref-doi",
            doi="10.1000/real",
            title="A Study of Something Real",
        ),
    )
    refs.classify(verified)
    mismatch = refs.Reference(
        key="k", collection="refs.bib", also_in=["other.bib"]
    )
    mismatch.title = "A Study of Something Real"
    mismatch.found = refs.compare(
        mismatch,
        refs.Found(
            source="crossref-doi",
            doi="10.1000/real",
            title="An Entirely Different Paper",
        ),
    )
    refs.classify(mismatch)
    bad_doi = refs.Reference(
        key="k", collection="refs.bib", doi="10.9999/no", doi_registered=False
    )
    refs.classify(bad_doi)
    not_found = refs.Reference(
        key="k", collection="refs.bib", title="A Study of Something Real"
    )
    refs.classify(not_found)
    for reference in (verified, mismatch, bad_doi, not_found):
        keys |= set(reference.model_dump(mode="json"))
        statuses.add(reference.status)
    assert keys == _REFERENCE_KEYS
    assert set(refs.Status.__args__) == statuses  # type: ignore[attr-defined]
    assert verified.evidence is not None
    assert set(verified.evidence.model_dump(mode="json")) == _EVIDENCE_KEYS
    # The citation key is the mapping's key, never a field inside it.
    assert "key" not in keys


def test_compact_drops_only_what_says_nothing(tmp_dir: Path) -> None:
    assert refs.compact(
        {"a": 1, "b": None, "c": [], "d": {}, "e": False, "f": 0, "g": ""}
    ) == {"a": 1, "e": False, "f": 0, "g": ""}
    assert refs.compact({"a": {"b": None, "c": 2}}) == {"a": {"c": 2}}
    assert refs.compact([{"a": None}, {"b": 1}]) == [{}, {"b": 1}]


def test_a_pdf_with_no_source_is_checked_against_its_list(
    tmp_dir: Path,
) -> None:
    import ctypes

    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    def make_pdf(path: Path, pages: list[list[str]]) -> None:
        pdf = pdfium.PdfDocument.new()
        for lines in pages:
            page = pdf.new_page(612, 792)
            for i, line in enumerate(lines):
                obj = raw.FPDFPageObj_NewTextObj(pdf.raw, b"Helvetica", 10.0)
                buf = ctypes.create_string_buffer(
                    (line + "\x00").encode("utf-16-le")
                )
                raw.FPDFText_SetText(
                    obj, ctypes.cast(buf, ctypes.POINTER(raw.FPDF_WCHAR))
                )
                raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 50, 740 - 14 * i)
                raw.FPDFPage_InsertObject(page.raw, obj)
            raw.FPDFPage_GenerateContent(page.raw)
        pdf.save(str(path))
        pdf.close()

    # A running header is dropped, an entry continues across a page and a
    # DOI broken at its hyphen, a line starting with a number doesn't start
    # an entry unless it's the next one, and an appendix ends the list
    (tmp_dir / "paper").mkdir()
    pdf = tmp_dir / "paper" / "review.pdf"
    make_pdf(
        pdf,
        [
            ["Journal 2026, 1 of 3", "Introduction", "As shown in [1]."],
            [
                "Journal 2026, 2 of 3",
                "References",
                "1. Vega, A.; Bloom, L. A Study of Something Real. Journal",
                "2020, 7, 1-2. https://doi.org/10.1000/9999-",
                "1111/22/3/444555.",
                "2. Okafor, C. Nested Braces, and a Comma, in One Title.",
            ],
            [
                "Journal 2026, 3 of 3",
                "3 Not a label. Proceedings of Machine Learning Research 2021.",
                "3. Rossi, G. Something Posted First. arXiv:1901.00001.",
                "Appendix A",
                "4. Not a reference.",
            ],
        ],
    )
    printed = refs.pdf_references(pdf)
    assert list(printed) == ["1", "2", "3"]
    assert printed["1"] == (
        "Vega, A.; Bloom, L. A Study of Something Real. Journal 2020, 7, "
        "1-2. https://doi.org/10.1000/9999-1111/22/3/444555."
    )
    assert "Journal 2026" not in " ".join(printed.values())
    assert printed["2"].endswith("Machine Learning Research 2021.")
    # Fields are read from the text, with no title cut out of it
    reference = refs.Reference(key="1")
    refs._fill_from_citation(reference, printed["1"])
    assert reference.doi == "10.1000/9999-1111/22/3/444555"
    assert (reference.year, reference.first_author) == (2020, "Vega")
    assert reference.title is None
    for citation, doi, year, author in [
        (
            "Ortega, A. Survey. Journal of Things 1999, 2, 1-24. https://doi.org/"
            "10.1000/(ABC)1234-5678(199901/03)2:1<1::XY-Z12>3.0.CO;2-9.",
            "10.1000/(ABC)1234-5678(199901/03)2:1<1::XY-Z12>3.0.CO;2-9",
            1999,
            "Ortega",
        ),
        (
            "Jones, B. (2014). A title from 2016. Journal "
            "(https://doi.org/10.1000/x).",
            "10.1000/x",
            2014,
            "Jones",
        ),
        (
            "N. O. Lindqvist, A. Ortega, and B. Lee, A title, J. Things, "
            "vol. 10, pp. 1843–1862, 2025.",
            None,
            2025,
            "Lindqvist",
        ),
    ]:
        reference = refs.Reference(key="k")
        refs._fill_from_citation(reference, citation)
        assert (reference.doi, reference.year, reference.first_author) == (
            doi,
            year,
            author,
        )
    reference = refs.Reference(key="3")
    refs._fill_from_citation(reference, printed["3"])
    assert reference.arxiv == "1901.00001"
    # The title compared is the stretch of the citation most like the
    # record's, so another work's title doesn't match
    reference = refs.Reference(key="1")
    refs._fill_from_citation(reference, printed["1"])

    def found(title: str) -> refs.Found:
        return refs.Found(
            source="crossref-doi", title=title, year=2020, first_author="Vega"
        )

    assert refs.compare(
        reference, found("A study of something real")
    ).title_matches
    assert (
        refs.compare(
            reference, found("Soil chemistry of an unrelated site")
        ).title_matches
        is False
    )
    # A list with no numbers is split where a line starts with a surname
    # after one ending a sentence
    unnumbered = tmp_dir / "unnumbered.pdf"
    make_pdf(
        unnumbered,
        [
            [
                "Bibliography",
                "van Dam, J. A first work that runs onto a",
                "Second line, which isn't an entry. Journal 2001.",
                "Smith, J. Another work. Journal 2002.",
            ]
        ],
    )
    assert list(refs.pdf_references(unnumbered).values()) == [
        "van Dam, J. A first work that runs onto a Second line, which isn't "
        "an entry. Journal 2001.",
        "Smith, J. Another work. Journal 2002.",
    ]
    # The check reads the PDF's list where nothing builds it, and a PDF
    # with no list is an error rather than an empty report
    (tmp_dir / "calkit.yaml").write_text("name: review\n")
    document = refs.check_references("paper/review.pdf", offline=True)
    assert document.path == "paper/review.pdf"
    assert document.sources == ["paper/review.pdf"]
    assert list(document.references) == ["1", "2", "3"]
    assert all(
        r.collection == "paper/review.pdf" and r.status == "unchecked"
        for r in document.references.values()
    )
    assert "citation" not in document.references["1"].model_dump()
    # Each reference is set off by a rule and wrapped, never inside a link
    text = refs.format_check(document, verbose=True, width=40)
    assert text.count("─" * 40) == 4
    assert "  Vega, A.; Bloom, L. A Study of" in text
    assert "https://doi.org/10.1000/9999-1111/22/3/444555." in text
    listed = text.split("References checked")[0]
    assert all(
        len(line) <= 40 or "https://" in line for line in listed.splitlines()
    )
    assert "Defined in a bibliography" not in text
    make_pdf(tmp_dir / "paper" / "empty.pdf", [["No list here."]])
    with pytest.raises(ValueError, match="no reference list"):
        refs.check_references("paper/empty.pdf", offline=True)
    assert refs.document_inputs("paper/review.pdf") == ["paper/review.pdf"]


def test_markdown_citations_are_found(tmp_dir: Path) -> None:
    (tmp_dir / "paper").mkdir()
    (tmp_dir / "paper" / "main.md").write_text(
        "---\n"
        "title: Paper\n"
        "bibliography: references.bib\n"
        "---\n"
        "Text [@real2020thing] and @thin2021venue, as @fig-results shows.\n"
        "Mail me at someone@example.com, or see https://example.com/@me.\n"
        "<!-- [@commented]\n"
        "still a comment @commented -->\n"
        "Run `@inline` or:\n"
        "\n"
        "```python\n"
        "@property\n"
        "```\n"
        "And @{tool2024software}.\n"
    )
    (tmp_dir / "paper" / "references.bib").write_text(BIB)
    (tmp_dir / "calkit.yaml").write_text(
        "pipeline:\n"
        "  stages:\n"
        "    paper:\n"
        "      kind: markdown\n"
        "      target_path: paper/main.md\n"
        "      environment: _system\n"
        "      pdf:\n"
        "        environment: _system\n"
        "        output_path: out/paper.pdf\n"
        "references:\n"
        "  - path: paper/references.bib\n"
    )
    from calkit.latex import flatten

    keys = refs.cited_keys(flatten("paper/main.md"))
    assert set(keys) == {
        "real2020thing",
        "thin2021venue",
        "fig-results",
        "tool2024software",
    }
    # The front matter names the bibliography, which wins over the one
    # calkit.yaml declares, and a cross-reference isn't a citation
    (tmp_dir / "calkit.yaml").write_text(
        (tmp_dir / "calkit.yaml")
        .read_text()
        .replace("paper/references.bib", "other.bib")
    )
    for path in ["paper/main.md", "out/paper.pdf"]:
        document = refs.check_references(path, offline=True)
        assert document.path == "paper/main.md"
        assert document.collections == ["paper/references.bib"]
        assert set(document.references) == {
            "real2020thing",
            "thin2021venue",
            "tool2024software",
        }
        assert document.ok
