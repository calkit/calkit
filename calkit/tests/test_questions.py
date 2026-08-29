"""Tests for ``calkit.questions``."""

from __future__ import annotations

import json
import os

import pytest

from calkit.questions import (
    check_questions,
    format_status,
    record_evidence_values,
    resolve_key,
    values_match,
)


def test_values_match():
    # Floating-point noise is ignored, visible changes are not
    assert values_match(0.0125171247158, 0.01251712471587, None)
    assert not values_match(8, 0, None)
    assert not values_match(1.0, 1.001, None)
    assert values_match(1.0, 1.001, tolerance=0.01)
    assert values_match(0.0, 0.0, None)
    assert not values_match(0.0, 1e-9, None)
    # Booleans are exact and never equal to their integer twins
    assert values_match(True, True, None)
    assert not values_match(True, 1, None)
    # Containers compare element-wise under the same rule
    assert values_match([1.0, "a"], [1.0000000001, "a"], None)
    assert not values_match(["a", "b"], ["a"], None)
    assert values_match({"x": 2.0}, {"x": 2.0}, None)
    assert not values_match({"x": 2.0}, {"y": 2.0}, None)
    assert values_match(float("nan"), float("nan"), None)
    assert values_match("clip-k-omega-gamma", "clip-k-omega-gamma", None)
    assert not values_match("a", "b", None)


def test_resolve_key():
    data = {"a.b": 1, "a": {"b": 2, "list": [10, {"c": 3}]}, "top": 4}
    # A literal top-level key wins over a dotted walk
    assert resolve_key(data, "a.b") == 1
    assert resolve_key(data, "a.list.1.c") == 3
    assert resolve_key(data, "a.list.0") == 10
    assert resolve_key(data, "top") == 4
    with pytest.raises(KeyError):
        resolve_key(data, "a.missing")
    with pytest.raises(KeyError):
        resolve_key(data, "a.list.x")


def test_check_and_record(tmp_dir):
    os.makedirs("results")
    os.makedirs("paper")
    with open("results/findings.json", "w") as f:
        json.dump({"n_top": 8, "score": 0.5, "nested": {"best": "a"}}, f)
    with open("paper/main.tex", "w") as f:
        f.write("\\section{Results}\\label{sec:results}\n")
    with open("paper/main.pdf", "w") as f:
        f.write("pdf")
    ck_info = {
        "pipeline": {
            "stages": {
                "build-paper": {
                    "kind": "latex",
                    "environment": "tex",
                    "target_path": "paper/main.tex",
                    "outputs": ["paper/main.pdf"],
                },
                "summarize": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "s.py",
                    "outputs": [{"path": "results/findings.json"}],
                },
            }
        },
        "questions": [
            "Is this a plain question?",
            {"question": "Unanswered?", "hypothesis": "Maybe."},
            {"question": "Answered without evidence?", "answer": "Yes."},
            {
                "question": "Do the top structures use the rectifier?",
                "answer": "All eight do.",
                "evidence": [
                    {
                        "kind": "result",
                        "path": "results/findings.json",
                        "key": "n_top",
                    },
                    {
                        "kind": "result",
                        "path": "results/findings.json",
                        "key": "nested.best",
                    },
                    {
                        "kind": "publication",
                        "path": "paper/main.pdf",
                        "section": "3",
                        "label": "sec:results",
                    },
                    {"kind": "figure", "path": "figures/missing.png"},
                ],
            },
        ],
    }
    # Before anything is recorded: the figure is missing, so the question is
    # in error; the keyed results are unrecorded; the label is found
    status = check_questions(ck_info=ck_info, wdir=".")
    assert [q.status for q in status.questions] == [
        "unanswered",
        "unanswered",
        "no-evidence",
        "error",
    ]
    q4 = status.questions[3]
    assert q4.evidence[0].status == "unrecorded"
    assert q4.evidence[0].current == 8
    assert q4.evidence[0].stage == "summarize"
    assert q4.evidence[2].status == "ok"
    assert q4.evidence[3].status == "missing"
    assert not status.ok
    # Fix the missing figure and record the values for question 4 only
    os.makedirs("figures")
    with open("figures/missing.png", "w") as f:
        f.write("png")
    changed = record_evidence_values(ck_info, wdir=".", indices=[4])
    assert [(n, k, new) for n, k, _, new in changed] == [
        (4, "n_top", 8),
        (4, "nested.best", "a"),
    ]
    assert ck_info["questions"][3]["evidence"][0]["value"] == 8
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].status == "ok"
    assert status.ok
    # Recording again changes nothing
    assert record_evidence_values(ck_info, wdir=".") == []
    # The pipeline produces a different number: the answer is stale, and the
    # report says what moved. A tolerance on the entry can absorb it
    with open("results/findings.json", "w") as f:
        json.dump({"n_top": 0, "score": 0.5, "nested": {"best": "a"}}, f)
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].status == "stale"
    ev = status.questions[3].evidence[0]
    assert ev.status == "stale"
    assert ev.recorded == 8 and ev.current == 0
    assert "changed from 8 to 0" in (ev.message or "")
    report = format_status(status)
    assert "[stale] Do the top structures use the rectifier?" in report
    assert "1 stale" in report
    assert "1 answered without evidence" in report
    assert "2 unanswered" in report
    assert not status.ok
    # Re-recording accepts the new value; force re-records matching ones
    changed = record_evidence_values(ck_info, wdir=".", indices=[4])
    assert [(k, old, new) for _, k, old, new in changed] == [("n_top", 8, 0)]
    assert check_questions(ck_info=ck_info, wdir=".").ok
    changed = record_evidence_values(ck_info, wdir=".", force=True)
    assert len(changed) == 2
    # A label that disappears from the source is an error, a bad key too
    with open("paper/main.tex", "w") as f:
        f.write("\\section{Results}\\label{sec:conclusions}\n")
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].status == "error"
    assert "not found" in (status.questions[3].evidence[2].message or "")
    ck_info["questions"][3]["evidence"][1]["key"] = "nested.nope"
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].evidence[1].status == "error"
    # A publication with no LaTeX stage is skipped, not failed
    ck_info["pipeline"]["stages"].pop("build-paper")
    ck_info["questions"][3]["evidence"][1]["key"] = "nested.best"
    with open("paper/main.tex", "w") as f:
        f.write("\\section{Results}\\label{sec:results}\n")
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].evidence[2].status == "skipped"
    assert status.questions[3].status == "ok"
    # Verbose output lists everything
    assert "publication paper/main.pdf [skipped]" in format_status(
        status, verbose=True
    )
