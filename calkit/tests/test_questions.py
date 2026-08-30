"""Tests for ``calkit.questions``."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

import calkit
from calkit.questions import (
    check_questions,
    format_status,
    placeholders,
    render,
    render_question,
    resolve_key,
)


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


def test_render():
    values = {"ratio": 5.1014, "n": 8, "best": "clip", "a.b": 2.0}
    assert render("about {ratio:.1f}x", values) == "about 5.1x"
    assert render("{n} of {n}", values) == "8 of 8"
    # Dotted names are names, not attribute access; braces can be escaped
    assert render("{a.b:.0f}", values) == "2"
    assert render("literal {{x}}", values) == "literal {x}"
    assert render(None, values) is None
    assert render("no placeholders", values) == "no placeholders"
    assert placeholders("{ratio:.1f} and {best} but {{not}}") == [
        "ratio",
        "best",
    ]
    with pytest.raises(KeyError):
        render("{missing}", values)
    with pytest.raises(ValueError):
        render("{best:.2f}", values)


def _commit(msg: str) -> str:
    subprocess.check_call(["git", "add", "-A"])
    subprocess.check_call(
        ["git", "commit", "-q", "-m", msg],
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()


def _write_yaml(ck_info: dict) -> None:
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)


def test_history_is_read_once_for_all_questions(tmp_dir):
    """A long calkit.yaml history costs one reading, not one per question.

    Every question walks the same history looking for the commit it was
    last edited at. Reading it per question turned checking a handful of
    them into double-digit seconds on a project with any history at all.
    """
    import json
    import subprocess

    import calkit
    from calkit.questions import CalkitYamlHistory, check_questions

    subprocess.check_call(["git", "init", "-q"])
    os.makedirs("results")
    with open("results/findings.json", "w") as f:
        json.dump({f"k{i}": i for i in range(4)}, f)
    ck_info = {
        "questions": [
            {
                "question": f"Q{i}?",
                "answer": "It is {v}.",
                "evidence": [
                    {
                        "kind": "value",
                        "path": "results/findings.json",
                        "key": f"k{i}",
                        "name": "v",
                    }
                ],
            }
            for i in range(4)
        ]
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["git", "add", "-A"])
    subprocess.check_call(["git", "commit", "-q", "-m", "Answer"])
    # Later commits that touch the file without touching the questions, so
    # every question's walk runs the whole way back
    for i in range(5):
        ck_info["description"] = f"rev {i}"
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        subprocess.check_call(["git", "commit", "-q", "-am", f"r{i}"])
    reads: list[str] = []
    original = CalkitYamlHistory.at

    def counted(self, sha):
        reads.append(sha)
        return original(self, sha)

    CalkitYamlHistory.at = counted  # type: ignore[method-assign]
    try:
        status = check_questions()
    finally:
        CalkitYamlHistory.at = original  # type: ignore[method-assign]
    assert [q.status for q in status.questions] == ["ok"] * 4
    # Four questions over six commits: each revision is parsed once, not
    # once per question, so the distinct count is what bounds the work
    assert len(set(reads)) == 6
    assert len(reads) == 24


def test_check_questions(tmp_dir):
    subprocess.check_call(["git", "init", "-q"])
    os.makedirs("results")
    os.makedirs("paper")
    os.makedirs("figures")
    with open("results/findings.json", "w") as f:
        json.dump({"n_top": 8, "ratio": 5.1014, "nested": {"best": "a"}}, f)
    with open("paper/main.tex", "w") as f:
        f.write("\\section{Results}\\label{sec:results}\n")
    with open("paper/main.pdf", "w") as f:
        f.write("pdf")
    with open("figures/plot.png", "w") as f:
        f.write("png")
    # A DVC-tracked output known only through dvc.lock
    with open("dvc.lock", "w") as f:
        f.write(
            "stages:\n  fit:\n    outs:\n    - path: results/big.h5\n"
            "      md5: aaa\n"
        )
    with open("results/big.h5", "w") as f:
        f.write("h5")
    with open(".gitignore", "w") as f:
        f.write("results/big.h5\n")
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
            {"question": "Unanswered?", "notes": "Needs a second dataset."},
            {"question": "Answered without evidence?", "answer": "Yes."},
            {
                "question": "Do the top structures use the rectifier?",
                "answer": "{n_top} of eight do, a {ratio:.1f}x gain.",
                "evidence": [
                    {
                        "kind": "value",
                        "path": "results/findings.json",
                        "key": "n_top",
                    },
                    {
                        "kind": "value",
                        "path": "results/findings.json",
                        "key": "ratio",
                    },
                    {
                        "kind": "value",
                        "path": "results/findings.json",
                        "key": "nested.best",
                        "name": "best",
                        "explanation": "The best is {best}.",
                    },
                    {
                        "kind": "publication",
                        "path": "paper/main.pdf",
                        "section": "3",
                        "label": "sec:results",
                    },
                    {"kind": "figure", "path": "figures/plot.png"},
                    {"kind": "result", "path": "results/big.h5"},
                ],
            },
        ],
    }
    _write_yaml(ck_info)
    # Uncommitted: nothing to compare history against, but templates and
    # references are checked, and the text renders
    status = check_questions(ck_info=ck_info, wdir=".")
    assert [q.status for q in status.questions] == [
        "unanswered",
        "unanswered",
        "no-evidence",
        "ok",
    ]
    q4 = status.questions[3]
    assert q4.commit is None
    assert "not yet committed" in (q4.message or "")
    assert q4.evidence[0].current == 8
    assert q4.evidence[0].stage == "summarize"
    assert q4.evidence[3].status == "ok"
    rendered = render_question(ck_info["questions"][3], ck_info, ".")
    assert rendered["answer"] == "8 of eight do, a 5.1x gain."
    assert rendered["evidence"][2]["explanation"] == "The best is a."
    assert render_question("plain", ck_info, ".") == "plain"
    # Committed: the question dates from this commit and nothing has changed
    sha1 = _commit("Answer the question")
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].status == "ok"
    assert status.questions[3].commit == sha1
    assert status.ok
    # The results file gains an unrelated key and a cited float moves in
    # its last bits: neither touches the answer
    with open("results/findings.json", "w") as f:
        json.dump(
            {
                "n_top": 8,
                "ratio": 5.10140000001,
                "nested": {"best": "a"},
                "new_key": 1,
            },
            f,
        )
    _commit("Add an unrelated result")
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].status == "ok"
    # The pipeline changes a cited value in a later commit: stale, with
    # the old and new values named, and the rendered text already shows
    # the new number
    with open("results/findings.json", "w") as f:
        json.dump({"n_top": 0, "ratio": 5.1014, "nested": {"best": "a"}}, f)
    _commit("Re-run the pipeline")
    status = check_questions(ck_info=ck_info, wdir=".")
    q4 = status.questions[3]
    assert q4.status == "stale"
    assert q4.commit == sha1
    assert q4.evidence[0].status == "changed"
    assert "n_top was 8 at" in (q4.evidence[0].message or "")
    assert q4.evidence[1].status == "ok"
    assert q4.evidence[4].status == "ok"
    assert not status.ok
    report = format_status(status)
    assert "[stale] Do the top structures use the rectifier?" in report
    assert "set 'reviewed'" in report
    assert "1 stale" in report
    assert "1 answered without evidence" in report
    assert "2 unanswered" in report
    assert (
        render_question(ck_info["questions"][3], ck_info, ".")["answer"]
        == "0 of eight do, a 5.1x gain."
    )
    # Reading it again and setting reviewed is an edit, which marks it
    # current once committed; before the commit it is simply uncommitted
    ck_info["questions"][3]["reviewed"] = "2026-08-29"
    _write_yaml(ck_info)
    ck_info = calkit.load_calkit_info()
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].status == "ok"
    assert status.questions[3].commit is None
    sha3 = _commit("Review the answer")
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].status == "ok"
    assert status.questions[3].commit == sha3
    # An uncommitted modification to Git-tracked evidence counts too
    with open("results/findings.json", "w") as f:
        json.dump({"n_top": 1, "ratio": 5.1014, "nested": {"best": "a"}}, f)
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].status == "stale"
    assert "now 1" in (status.questions[3].evidence[0].message or "")
    _commit("Change it again")
    # A second review the same day is a timestamp, so it is a real edit
    ck_info["questions"][3]["reviewed"] = "2026-08-29T15:40:00"
    _write_yaml(ck_info)
    ck_info = calkit.load_calkit_info()
    _commit("Review again")
    assert check_questions(ck_info=ck_info, wdir=".").ok
    # A DVC-tracked output changes: seen through its hash in dvc.lock
    with open("dvc.lock", "w") as f:
        f.write(
            "stages:\n  fit:\n    outs:\n    - path: results/big.h5\n"
            "      md5: bbb\n"
        )
    _commit("Re-run fit")
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].status == "stale"
    assert "dvc.lock" in (status.questions[3].evidence[5].message or "")
    # Broken references and templates are errors, not staleness
    ck_info["questions"][3]["reviewed"] = "2026-08-31"
    _write_yaml(ck_info)
    ck_info = calkit.load_calkit_info()
    _commit("Review once more")
    assert check_questions(ck_info=ck_info, wdir=".").ok
    ck_info["questions"][3]["answer"] = "{nope} of eight"
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].status == "error"
    assert "{nope} names no evidence" in (status.questions[3].message or "")
    ck_info["questions"][3]["answer"] = "{best:.2f}"
    status = check_questions(ck_info=ck_info, wdir=".")
    assert "cannot render" in (status.questions[3].message or "")
    ck_info["questions"][3]["answer"] = "fine"
    ck_info["questions"][3]["evidence"][1]["key"] = "nope"
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].evidence[1].status == "error"
    ck_info["questions"][3]["evidence"][1]["key"] = "ratio"
    ck_info["questions"][3]["evidence"][2]["name"] = "n_top"
    status = check_questions(ck_info=ck_info, wdir=".")
    assert "duplicate evidence name" in (status.questions[3].message or "")
    ck_info["questions"][3]["evidence"][2]["name"] = "best"
    with open("paper/main.tex", "w") as f:
        f.write("\\section{Results}\\label{sec:conclusions}\n")
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].status == "error"
    assert "not found" in (status.questions[3].evidence[3].message or "")
    # A publication with no LaTeX stage is skipped, and a result with a key
    # still works but is told to become a value
    ck_info["pipeline"]["stages"].pop("build-paper")
    ck_info["questions"][3]["evidence"][0]["kind"] = "result"
    status = check_questions(ck_info=ck_info, wdir=".")
    assert status.questions[3].evidence[3].status == "skipped"
    assert "use kind: value" in (status.questions[3].evidence[0].message or "")
    assert "publication paper/main.pdf [skipped]" in format_status(
        status, verbose=True
    )
