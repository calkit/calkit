"""Tests for ``calkit.references``."""

import json
from pathlib import Path

import pytest

import calkit
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
    check = refs.check_references(offline=True)
    reference = check.documents[0].references["real2020thing"]
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


def test_handle_responses_map_to_an_answer(tmp_dir: Path) -> None:
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


def test_offline_check_reports_what_needs_no_network(tmp_dir: Path) -> None:
    _project(
        tmp_dir,
        "\\citep{real2020thing}\n\\citep{tool2024software}\n\\citep{ghost}\n",
    )
    check = refs.check_references(offline=True)
    assert len(check.documents) == 1
    document = check.documents[0]
    assert document.path == "paper/main.tex"
    assert document.n_cited == 3
    by_key = document.references
    assert by_key["ghost"].status == "missing-from-bib"
    assert by_key["ghost"].collection is None
    assert by_key["real2020thing"].collection == "paper/references.bib"
    assert by_key["tool2024software"].status == "not-checkable"
    # Offline, a real entry cannot be confirmed, but it is not accused.
    assert by_key["real2020thing"].status == "not-found"
    assert not check.ok
    paths = refs.write_reports(check)
    assert paths == [".calkit/reference-checks/paper/main.tex.json"]
    payload = json.loads((tmp_dir / paths[0]).read_text())
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
    text = refs.format_check(check)
    assert "ghost" in text and "cannot be accounted for" in text


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
    "offline",
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
    check = refs.check_references(offline=True)
    payload = check.documents[0].model_dump(mode="json")
    assert set(payload) == _DOCUMENT_KEYS
    # Every key a reference can carry, over every status it can take.
    statuses = set()
    keys: set[str] = set()
    for reference in check.documents[0].references.values():
        keys |= set(reference.model_dump(mode="json"))
        statuses.add(reference.status)
    # Offline, three of the statuses are reachable; the other three need
    # a record, so build one of each.
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
    for reference in (verified, mismatch, bad_doi):
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


def test_stage_expansion_derives_inputs_and_a_report_per_document(
    tmp_dir: Path,
) -> None:
    _project(tmp_dir, "\\input{sec}\n")
    (tmp_dir / "paper" / "sec.tex").write_text("\\citep{real2020thing}\n")
    ck_info = calkit.load_calkit_info()
    # No environment: it defaults to the system, which is where the
    # Calkit running the pipeline already is.
    ck_info["pipeline"]["stages"]["check-refs"] = {
        "kind": "references-check",
        "target_path": "paper/main.tex",
    }
    expanded = refs.expand_reference_check_stages(ck_info)
    stage = expanded["pipeline"]["stages"]["check-refs"]
    # The document, the file it inputs, and the collection, so an edit to
    # any of them reruns the check.
    assert "calkit.yaml" in stage["inputs"]
    assert "paper/main.tex" in stage["inputs"]
    assert "paper/sec.tex" in stage["inputs"]
    assert "paper/references.bib" in stage["inputs"]
    assert stage["outputs"] == [
        {
            "path": ".calkit/reference-checks/paper/main.tex.json",
            "storage": "git",
        }
    ]
    # Other stages are untouched.
    assert expanded["pipeline"]["stages"]["paper"]["kind"] == "latex"
    # A project with no such stage is returned as it came in.
    assert refs.expand_reference_check_stages(ck_info) is not ck_info


def test_the_stage_compiles_to_a_dvc_stage(tmp_dir: Path) -> None:
    from calkit.models.pipeline import ReferencesCheckStage

    stage = ReferencesCheckStage(
        kind="references-check", target_path="paper/main.tex"
    )
    # The environment is not required: the check runs where the Calkit
    # running the pipeline already is.
    assert stage.environment == "_system"
    assert stage.dvc_cmd == "calkit check references paper/main.tex"
    offline = ReferencesCheckStage(
        kind="references-check", target_path="a b.tex", offline=True
    )
    assert offline.dvc_cmd == "calkit check references 'a b.tex' --offline"


def test_markdown_citations_are_found(tmp_dir: Path) -> None:
    (tmp_dir / "paper").mkdir()
    (tmp_dir / "paper" / "main.md").write_text(
        "Text [@real2020thing] and @thin2021venue.\n"
        "Mail me at someone@example.com though.\n"
    )
    (tmp_dir / "paper" / "references.bib").write_text(BIB)
    (tmp_dir / "calkit.yaml").write_text(
        "pipeline:\n"
        "  stages:\n"
        "    paper:\n"
        "      kind: markdown\n"
        "      target_path: paper/main.md\n"
        "      environment: _system\n"
        "      pdf: true\n"
        "references:\n"
        "  - path: paper/references.bib\n"
    )
    from calkit.latex import flatten

    keys = refs.cited_keys(flatten("paper/main.md"))
    assert set(keys) == {"real2020thing", "thin2021venue"}
