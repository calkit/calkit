"""Tests for app.components (a document's components, read from a tree)."""

import json

from app.components import (
    candidate_documents,
    components_for_document,
    document_in,
    sidecar_path,
    stale_stage_base_names,
    usages_of,
)
from app.pipeline import StageStatus


class FakeTree:
    """Minimal RepoTree: the files a ref holds, by path."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def is_file(self, path: str) -> bool:
        return path in self.files

    def read_bytes(self, path: str) -> bytes:
        return self.files[path]


SIDECAR = {
    "document": "paper/main.tex",
    "components": [
        {
            "kind": "value",
            "path": "results/findings.json",
            "key": "ratio",
            "pages": [1, 3],
            "value": 5.1014,
            "hash": None,
        },
        {
            "kind": "value",
            "path": "results/findings.json",
            "key": "name",
            "pages": [1],
            "value": "k_omega",
            "hash": None,
        },
        {
            "kind": "figure",
            "path": "figures/plot.pdf",
            "key": None,
            "pages": [2],
            "hash": "abc",
        },
        {
            "kind": "figure",
            "path": "img/schematic.pdf",
            "key": None,
            "pages": [2],
            "hash": None,
        },
        {"kind": "block", "path": "calkit.yaml", "key": "1", "pages": [4]},
    ],
}
CK_INFO = {
    "pipeline": {
        "stages": {
            "plot": {
                "kind": "python-script",
                "script_path": "plot.py",
                "inputs": ["results/findings.json"],
                "outputs": ["figures/plot.pdf"],
            },
            "summarize": {
                "kind": "python-script",
                "script_path": "s.py",
                "outputs": [{"path": "results/findings.json"}],
            },
            "build-paper": {"kind": "latex", "target_path": "paper/main.tex"},
        }
    },
    "figures": [
        {"path": "img/rig.pdf", "created_by": {"email": "me@myorg.edu"}}
    ],
    "publications": [{"path": "paper/main.pdf"}],
}


def _tree(results: dict | None = None) -> FakeTree:
    return FakeTree(
        {
            "paper/main.provenance.json": json.dumps(SIDECAR).encode(),
            "results/findings.json": json.dumps(
                results
                if results is not None
                else {"ratio": 5.1014, "name": "k_omega"}
            ).encode(),
            "img/schematic.pdf": b"pdf",
            "calkit.yaml": b"",
        }
    )


def test_sidecar_path_from_any_name():
    # A document is named by its source, its output, or its record, and a
    # caller has whichever the reader was looking at
    assert sidecar_path("paper/main.tex") == "paper/main.provenance.json"
    assert sidecar_path("paper/main.pdf") == "paper/main.provenance.json"
    assert (
        sidecar_path("paper/main.provenance.json")
        == "paper/main.provenance.json"
    )


def test_components_are_current_when_nothing_moved():
    components, built = components_for_document(
        document="paper/main.pdf",
        tree=_tree(),
        ck_info=CK_INFO,
        dvc_outs={"figures/plot.pdf": {"md5": "abc"}},
        stale_stage_names=set(),
    )
    assert built
    by = {(c.path, c.key): c for c in components}
    ratio = by[("results/findings.json", "ratio")]
    assert ratio.status == "ok"
    assert ratio.stage == "summarize"
    assert ratio.script == "s.py"
    assert ratio.pages == [1, 3]
    assert by[("figures/plot.pdf", None)].status == "ok"


def test_a_value_that_moved_on_since_the_build():
    components, _ = components_for_document(
        document="paper/main.pdf",
        tree=_tree({"ratio": 7.9, "name": "k_omega"}),
        ck_info=CK_INFO,
        dvc_outs={"figures/plot.pdf": {"md5": "abc"}},
        stale_stage_names=set(),
    )
    by = {(c.path, c.key): c for c in components}
    ratio = by[("results/findings.json", "ratio")]
    assert ratio.status == "stale"
    assert ratio.stale_reasons == ["changed-since-build"]
    assert (ratio.build_value, ratio.current_value) == (5.1014, 7.9)
    # The other value in the same file is untouched, which is the point of
    # comparing values rather than the file's hash
    assert by[("results/findings.json", "name")].status == "ok"


def test_a_stage_needing_a_rerun_and_a_figure_that_changed():
    components, _ = components_for_document(
        document="paper/main.pdf",
        tree=_tree(),
        ck_info=CK_INFO,
        # The pipeline recorded a different figure than the build used
        dvc_outs={"figures/plot.pdf": {"md5": "def"}},
        stale_stage_names={"summarize"},
    )
    by = {(c.path, c.key): c for c in components}
    assert by[("results/findings.json", "ratio")].stale_reasons == [
        "stage-out-of-date"
    ]
    assert by[("figures/plot.pdf", None)].stale_reasons == [
        "changed-since-build"
    ]


def test_what_nothing_could_be_said_about_is_not_called_current():
    components, _ = components_for_document(
        document="paper/main.pdf",
        tree=_tree(),
        ck_info=CK_INFO,
        dvc_outs={},
        stale_stage_names=set(),
    )
    by = {c.path: c for c in components}
    # No stage makes it and nobody declared it: the gap, and the pipeline's
    # status says nothing about it either way
    schematic = by["img/schematic.pdf"]
    assert schematic.provenance == "undeclared"
    assert schematic.status == "unknown"
    # Whether an answer's evidence has moved is read from Git
    # history, which a tree doesn't have
    assert by["calkit.yaml"].provenance == "project"
    assert by["calkit.yaml"].status == "unknown"


def test_no_build_means_nothing_to_report():
    components, built = components_for_document(
        document="paper/other.tex",
        tree=_tree(),
        ck_info=CK_INFO,
        dvc_outs={},
        stale_stage_names=set(),
    )
    assert (components, built) == ([], False)


def test_usages_are_the_reverse_view():
    tree = _tree()
    assert usages_of("figures/plot.pdf", tree, CK_INFO) == [
        {
            "document": "paper/main.tex",
            "kind": "figure",
            "key": None,
            "pages": [2],
        }
    ]
    # A results file is used once per key the document cites
    assert [
        (u["key"], u["pages"])
        for u in usages_of("results/findings.json", tree, CK_INFO)
    ] == [("name", [1]), ("ratio", [1, 3])]
    assert usages_of("figures/unused.pdf", tree, CK_INFO) == []


def test_document_in_a_folder():
    # The browser extension knows which folder syncs with Overleaf, not
    # which file in it is the paper
    assert document_in("paper", CK_INFO) == "paper/main.pdf"
    assert document_in("paper/", CK_INFO) == "paper/main.pdf"
    # A caller with the paper in hand is taken at its word, by either name
    assert document_in("paper/main.tex", CK_INFO) == "paper/main.tex"
    assert document_in("paper/main.pdf", CK_INFO) == "paper/main.pdf"
    # A folder the project declares nothing in stays as it was, so the
    # lookup that follows simply finds no record
    assert document_in("poster", CK_INFO) == "poster"


def test_candidate_documents_finds_a_paper_once():
    # The publication and the LaTeX stage name the same paper by its output
    # and by its source, and both lead to one record
    assert candidate_documents(CK_INFO) == ["paper/main.pdf"]
    assert candidate_documents({}) == []


def test_a_stage_that_never_ran_needs_running():
    statuses = {
        "summarize": StageStatus(status="stale"),
        "plot@a": StageStatus(status="not-run"),
        "publish": StageStatus(status="up-to-date"),
    }
    # An iterated stage is keyed by its expansion, but an output belongs to
    # the stage as calkit.yaml writes it
    assert stale_stage_base_names(statuses) == {"summarize", "plot"}
