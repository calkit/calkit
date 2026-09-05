"""Question evidence and answer rendering, read from a repo at a ref.

The values an answer templates and the values its evidence cards show come
from the same results files, so they are read once per request and resolved
the way ``calkit list questions`` resolves them.
"""

import base64
import json
from unittest.mock import patch

import pytest

from app.api.routes.projects.core import (
    _build_question_evidence,
    _read_result_file,
    _resolve_result_value,
)
from app.models.core import ContentsItem

BENCH = {
    "improvement": 5.1014,
    "cases": {"a": {"cp": 0.42}},
    "stations": [{"cf": 0.003}],
    "a.b": "literal",
}


def _contents(path: str) -> ContentsItem:
    return ContentsItem(
        name=path.split("/")[-1],
        path=path,
        type="file",
        size=1,
        in_repo=True,
        content=base64.b64encode(json.dumps(BENCH).encode()).decode(),
        url=None,
        storage="git",
    )


def _patched_contents(reads: list[str] | None = None):
    def get_contents(project, repo, path, ref):
        if reads is not None:
            reads.append(path)
        return _contents(path)

    return patch(
        "app.api.routes.projects.core.app.projects.get_contents_from_repo",
        side_effect=get_contents,
    )


def test_resolves_keys_the_way_calkit_does() -> None:
    # A hand-rolled walk over dotted parts answers three of these wrong,
    # which would mean the hub and the CLI disagreeing about one number
    cache: dict = {}
    with _patched_contents():

        def value(key: str) -> str | None:
            return _resolve_result_value(
                project=None,
                repo=None,
                ref=None,
                path="results/bench.json",
                key=key,
                cache=cache,
            )

        assert value("improvement") == "5.1014"
        assert value("cases.a.cp") == "0.42"
        # An integer part indexes into a list
        assert value("stations.0.cf") == "0.003"
        # A key present literally at the top level wins over being split
        assert value("a.b") == "literal"
        assert value("cases.b.cp") is None


def test_reads_each_results_file_once_per_request() -> None:
    reads: list[str] = []
    cache: dict = {}
    with _patched_contents(reads):
        for key in ("improvement", "cases.a.cp"):
            _resolve_result_value(
                project=None,
                repo=None,
                ref=None,
                path="results/bench.json",
                key=key,
                cache=cache,
            )
        _read_result_file(
            project=None,
            repo=None,
            ref=None,
            path="results/bench.json",
            cache=cache,
        )
    assert reads == ["results/bench.json"]


def test_value_evidence_resolves_rather_than_being_dropped() -> None:
    # 'value' is what replaced 'result' with a key. Left out of the kinds
    # this accepts, a question's evidence renders as nothing at all.
    with _patched_contents():
        evidence = _build_question_evidence(
            project=None,
            repo=None,
            ref=None,
            evidence_ck=[
                {
                    "kind": "value",
                    "path": "results/bench.json",
                    "key": "cases.a.cp",
                    "name": "cp",
                    "explanation": "The best case.",
                },
                {"kind": "nonsense", "path": "x"},
            ],
            figures_by_path={},
            results_by_path={},
            tables_by_path={},
            publications_by_path={},
            result_value_cache={},
        )
    assert len(evidence) == 1
    assert evidence[0].kind == "value"
    assert evidence[0].key == "cases.a.cp"
    assert evidence[0].name == "cp"
    assert evidence[0].value == "0.42"


def test_a_keyed_entry_is_written_as_value_evidence() -> None:
    from app.api.routes.projects.core import (
        QuestionPut,
        _apply_question_update,
    )
    from app.models.core import QuestionEvidencePost

    updated = _apply_question_update(
        "Does the closure cut error?",
        QuestionPut(
            answer="By about {improvement:.1f}x.",
            evidence=[
                QuestionEvidencePost(
                    kind="value",
                    path="results/bench.json",
                    key="cases.a.speedup",
                    name="improvement",
                    explanation="The best case.",
                ),
                QuestionEvidencePost(kind="figure", path="figures/x.png"),
            ],
        ),
    )
    assert updated["evidence"] == [
        {
            "kind": "value",
            "path": "results/bench.json",
            "key": "cases.a.speedup",
            "name": "improvement",
            "explanation": "The best case.",
        },
        {"kind": "figure", "path": "figures/x.png"},
    ]


def test_value_evidence_without_a_key_is_refused() -> None:
    # It would round-trip into calkit.yaml as an entry the check rejects,
    # so it is better refused at the edge than written and reported later
    from fastapi import HTTPException

    from app.api.routes.projects.core import (
        QuestionPut,
        _apply_question_update,
    )
    from app.models.core import QuestionEvidencePost

    with pytest.raises(HTTPException) as excinfo:
        _apply_question_update(
            "Q?",
            QuestionPut(
                answer="A.",
                evidence=[
                    QuestionEvidencePost(
                        kind="value", path="results/bench.json"
                    )
                ],
            ),
        )
    assert excinfo.value.status_code == 422
