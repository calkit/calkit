"""Tests for ``calkit.questions``."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

import calkit
from calkit.models.core import ProjectInfo, Question
from calkit.pipeline import frozen_tainted_stage_names
from calkit.questions import (
    QuestionsStatus,
    check_question,
    check_questions,
    check_sign_offs,
    expand_questions_stages,
    format_status,
    format_summary,
    latex_values,
    placeholders,
    question_stages,
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
    # Keys containing dots are found below the top level too, and a dotted
    # key that leads nowhere falls back to shorter ones
    nested = {
        "sweep": {"back_off_1.50_k": {"failed": 13}, "back_off_1": {"x": 1}},
        "v1.2": {"a": {"b": 5}},
    }
    assert resolve_key(nested, "sweep.back_off_1.50_k.failed") == 13
    assert resolve_key(nested, "sweep.back_off_1.x") == 1
    assert resolve_key(nested, "v1.2.a.b") == 5
    with pytest.raises(KeyError):
        resolve_key(nested, "sweep.back_off_1.50_k.missing")
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
    # A value the spec can't take at all, e.g., a null, is a ValueError
    # too, not a TypeError nothing expects
    for bad in (None, {"a": 1}):
        with pytest.raises(ValueError, match="cannot be formatted"):
            render("{x:.2f}", {"x": bad})
    # The check reports it as a problem rather than crashing
    problems = calkit.questions._placeholder_problems("{x:.2f}", {"x": None})
    assert problems and "cannot render" in problems[0]


def _commit(msg: str, date: str | None = None) -> str:
    subprocess.check_call(["git", "add", "-A"])
    dates = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    subprocess.check_call(
        ["git", "commit", "-q", "-m", msg],
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            **(dates if date else {}),
        },
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()


def _write_yaml(ck_info: dict) -> None:
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)


def test_history_is_read_once_for_all_questions(tmp_dir):
    # Every question walks the same calkit.yaml history looking for the
    # commit it was last edited at. Reading it per question turned checking
    # a handful of them into double-digit seconds on a project with any
    # history at all.
    import json
    import subprocess

    import calkit
    from calkit.questions import CalkitYamlHistory, check_questions

    subprocess.check_call(["git", "init", "-q"])
    os.makedirs("results")
    with open("results/findings.json", "w") as f:
        json.dump({f"k{i}": i for i in range(4)}, f)
    ck_info = {
        "pipeline": {
            "stages": {
                "summarize": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "s.py",
                    "outputs": ["results/findings.json"],
                }
            }
        },
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
        ],
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
    os.makedirs("docs")
    with open("docs/notes.md", "w") as f:
        f.write("# Method\n")
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
                "notes": {
                    "kind": "markdown",
                    "environment": "py",
                    "target_path": "docs/notes.md",
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
                    {
                        "kind": "document",
                        "path": "docs/notes.md",
                        "section": "Method",
                    },
                    # Related values from one file, named in one entry
                    {
                        "kind": "result",
                        "path": "results/findings.json",
                        "values": {"top": "n_top", "r": "ratio"},
                        "explanation": "{top} and {r:.2f}",
                    },
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
    # The figure is real and nothing says where it came from: no stage
    # makes it and it is not declared with an import or a person
    assert q4.evidence[4].status == "unattributed"
    assert [ev.path for ev in status.unattributed] == ["figures/plot.png"]
    # A document is attributed to the Markdown stage that builds it
    assert q4.evidence[6].status == "ok"
    assert q4.evidence[6].stage == "notes"
    assert q4.evidence[7].status == "ok"
    assert q4.evidence[7].values == {"top": 8, "r": 5.1014}
    assert q4.evidence[7].stage == "summarize"
    # A result's values are checked like value entries: every key has to
    # resolve, key and values are exclusive, and names can't repeat
    for values, extra, expected in [
        ({"top": "n_top", "x": "nope", "y": "nested.nope"}, {}, "'nope', "),
        ({"top": "n_top"}, {"key": "ratio"}, "'values' or 'key'"),
        ({}, {}, "map each name"),
        ({"n_top": "ratio"}, {}, None),
    ]:
        grouped = {
            "question": "Grouped?",
            "answer": "{n_top}",
            "evidence": [
                {
                    "kind": "value",
                    "path": "results/findings.json",
                    "key": "n_top",
                },
                {
                    "kind": "result",
                    "path": "results/findings.json",
                    "values": values,
                }
                | extra,
            ],
        }
        checked = check_question(5, grouped, ck_info, ".")
        assert checked.status == "error", values
        if expected is None:
            assert "duplicate evidence name(s): n_top" in (
                checked.message or ""
            )
        else:
            assert expected in (checked.evidence[1].message or ""), values
    # A value no stage computes is a magic number, so it fails rather than
    # being advice; an import is traceable, a person typing it in is not
    with open("results/typed.json", "w") as f:
        json.dump({"n": 3}, f)
    typed = {
        "question": "Typed?",
        "answer": "{n}",
        "evidence": [
            {"kind": "value", "path": "results/typed.json", "key": "n"}
        ],
    }
    for declared, expected in [
        (None, "error"),
        ({"created_by": "someone"}, "error"),
        ({"imported_from": {"project": "a/b"}}, "ok"),
    ]:
        info = dict(ck_info)
        if declared:
            info["datasets"] = [{"path": "results/typed.json"} | declared]
        checked = check_question(5, typed, info, ".")
        assert checked.status == expected, declared
        if expected == "error":
            assert "no pipeline stage computes" in (
                checked.evidence[0].message or ""
            )
    os.remove("results/typed.json")
    # Likewise a document nothing builds: whatever it says was typed in
    with open("docs/typed.md", "w") as f:
        f.write("It is 3.\n")
    handwritten = {
        "question": "Written by hand?",
        "answer": "See the notes.",
        "evidence": [{"kind": "document", "path": "docs/typed.md"}],
    }
    for declared, expected in [
        (None, "error"),
        ({"created_by": "someone"}, "error"),
        ({"imported_from": {"project": "a/b"}}, "ok"),
    ]:
        info = dict(ck_info)
        if declared:
            info["publications"] = [{"path": "docs/typed.md"} | declared]
        checked = check_question(5, handwritten, info, ".")
        assert checked.status == expected, declared
        if expected == "error":
            assert "no pipeline stage builds" in (
                checked.evidence[0].message or ""
            )
    os.remove("docs/typed.md")
    # A Quarto document is evidence as rendered, not as its source
    with open("docs/report.qmd", "w") as f:
        f.write("It is `{python} 3`.\n")
    with open("docs/report.html", "w") as f:
        f.write("It is 3.\n")
    info = dict(ck_info)
    info["pipeline"] = {
        "stages": ck_info["pipeline"]["stages"]
        | {
            "report": {
                "kind": "quarto",
                "environment": "py",
                "target_path": "docs/report.qmd",
                "outputs": ["docs/report.html"],
            }
        }
    }
    for path, expected in [
        ("docs/report.html", "ok"),
        ("docs/report.qmd", "error"),
    ]:
        quarto = {
            "question": "Rendered?",
            "answer": "See the report.",
            "evidence": [{"kind": "document", "path": path}],
        }
        checked = check_question(5, quarto, info, ".")
        assert checked.status == expected, path
    assert checked.evidence[0].message == (
        "this is the source Quarto stage 'report' renders; cite what it "
        "renders instead, e.g., docs/report.html"
    )
    rendered = render_question(ck_info["questions"][3], ck_info, ".")
    assert rendered["answer"] == "8 of eight do, a 5.1x gain."
    assert rendered["evidence"][2]["explanation"] == "The best is a."
    assert rendered["evidence"][7]["explanation"] == "8 and 5.10"
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
    # A number moving after the answer was written is worth a reader's
    # attention, not a failure: the prose can still hold, and a templated
    # number rewrites itself
    assert q4.status == "ok"
    assert q4.commit == sha1
    assert q4.evidence[0].status == "changed"
    assert "n_top was 8 at" in (q4.evidence[0].message or "")
    assert q4.evidence[1].status == "ok"
    assert q4.evidence[4].status == "unattributed"
    # Each of a result's values is compared on its own
    assert q4.evidence[7].status == "changed"
    assert "n_top was 8 at" in (q4.evidence[7].message or "")
    assert "ratio" not in (q4.evidence[7].message or "")
    assert status.ok
    assert [ev.path for ev in status.changed] == [
        "results/findings.json",
        "results/findings.json",
    ]
    # Without history, the same checks hold but nothing is compared
    # against when the answer was written
    no_history = check_questions(
        ck_info=ck_info, wdir=".", check_history=False
    )
    q4 = no_history.questions[3]
    assert [q.status for q in no_history.questions] == [
        q.status for q in status.questions
    ]
    assert q4.commit is None
    assert not no_history.changed
    assert "not yet committed" not in (q4.message or "")
    assert q4.evidence[4].status == "unattributed"
    report = format_status(status)
    # It still earns a block, since nothing else would say it
    assert "[ok] Do the top structures use the rectifier?" in report
    assert "editing the answer or validating it" in report
    assert (
        "Evidence that changed after the answer was written: 2 (worth a look)"
        in report
    )
    assert "Answers given without evidence: 1 (worth a look)" in report
    assert "Questions answered: 2/4" in report
    assert "Evidence with nothing recorded behind it: 1" in report
    assert (
        render_question(ck_info["questions"][3], ck_info, ".")["answer"]
        == "0 of eight do, a 5.1x gain."
    )
    # Reading it again and editing the question marks it current once
    # committed; before the commit it is simply uncommitted
    ck_info["questions"][3]["notes"] = "Reread against the new value."
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
    assert status.questions[3].evidence[0].status == "changed"
    assert "now 1" in (status.questions[3].evidence[0].message or "")
    _commit("Change it again")
    # A second review has to be a real edit, so it says something new
    ck_info["questions"][3]["notes"] = "Reread again after the rerun."
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
    assert status.questions[3].evidence[5].status == "changed"
    assert "dvc.lock" in (status.questions[3].evidence[5].message or "")
    # Broken references and templates are errors, not staleness
    ck_info["questions"][3]["notes"] = "Reread after the fit changed."
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
    assert status.questions[3].status == "error"
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


def test_check_questions_pipeline_and_pins(tmp_dir):
    # Four ways an answer can rest on something it shouldn't: a stage that
    # needs re-running, one frozen out of reach, one downstream of the
    # freeze, and a citation pinned to a ref that isn't there. The pinned
    # ones are checked at their ref, so the working tree can't fix or break
    # them.
    subprocess.check_call(["git", "init", "-q"])
    os.makedirs("results")
    for name, value in [("fresh", 1), ("drifted", 2), ("pinned", 3)]:
        with open(f"results/{name}.json", "w") as f:
            json.dump({"v": value}, f)
    os.makedirs("docs")
    with open("docs/write-up.md", "w") as f:
        f.write("# Write-up\n")
    with open("dvc.lock", "w") as f:
        calkit.ryaml.dump(
            {
                "stages": {
                    "collect": {"outs": [{"path": "results/pinned.json"}]},
                    "derive": {
                        "deps": [{"path": "results/pinned.json"}],
                        "outs": [{"path": "results/fresh.json"}],
                    },
                    "drift": {"outs": [{"path": "results/drifted.json"}]},
                }
            },
            f,
        )
    ck_info = {
        "pipeline": {
            "stages": {
                # Frozen, so DVC will never call it or its consumers stale
                "collect": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "c.py",
                    "outputs": [{"path": "results/pinned.json"}],
                    "frozen": True,
                },
                "derive": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "d.py",
                    "inputs": ["results/pinned.json"],
                    "outputs": [{"path": "results/fresh.json"}],
                },
                "drift": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "s.py",
                    "outputs": [{"path": "results/drifted.json"}],
                },
                # Builds the document it names as its target
                "write-up": {
                    "kind": "markdown",
                    "environment": "py",
                    "target_path": "docs/write-up.md",
                },
            }
        },
        "questions": [
            {
                "question": "Does the drifted stage still say so?",
                "answer": "It says {drifted}.",
                "evidence": [
                    {
                        "kind": "value",
                        "path": "results/drifted.json",
                        "key": "v",
                        "name": "drifted",
                    }
                ],
            },
            {
                "question": "And the frozen one?",
                "answer": "Frozen at {pinned}.",
                "evidence": [
                    {
                        "kind": "value",
                        "path": "results/pinned.json",
                        "key": "v",
                        "name": "pinned",
                    }
                ],
            },
            {
                "question": "And what the freeze feeds?",
                "answer": "Downstream reads {fresh}.",
                "evidence": [
                    {
                        "kind": "value",
                        "path": "results/fresh.json",
                        "key": "v",
                        "name": "fresh",
                    }
                ],
            },
            {
                "question": "And one pinned to a ref that never existed?",
                "answer": "It said something once.",
                "evidence": [
                    {
                        "kind": "value",
                        "path": "results/drifted.json",
                        "key": "v",
                        "git_ref": "exp/never-pushed",
                    }
                ],
            },
            {
                "question": "And a document its stage would rebuild?",
                "answer": "The write-up says so.",
                "evidence": [{"kind": "document", "path": "docs/write-up.md"}],
            },
        ],
    }
    _write_yaml(ck_info)
    sha = _commit("Everything")
    # Stand in for DVC: only 'drift' needs re-running
    status = check_questions(ck_info=ck_info, wdir=".", check_pipeline=False)
    stale, frozen = (
        {"drift", "write-up/analyze"},
        frozen_tainted_stage_names(ck_info=ck_info, wdir="."),
    )
    # The freeze taints itself and everything reading what it wrote
    assert frozen == {"collect", "derive"}
    status = QuestionsStatus(
        questions=[
            check_question(
                n,
                q,
                ck_info,
                ".",
                calkit.git.get_repo("."),
                stale_stages=stale,
                frozen_stages=frozen,
            )
            for n, q in enumerate(ck_info["questions"], start=1)
        ]
    )
    assert [q.status for q in status.questions] == [
        "stale",
        "frozen",
        "frozen",
        "missing",
        "stale",
    ]
    assert status.questions[4].evidence[0].stage == "write-up"
    assert "out of date" in (status.questions[0].evidence[0].message or "")
    assert "git_ref" in (status.questions[1].evidence[0].message or "")
    assert "exp/never-pushed" in (
        status.questions[3].evidence[0].message or ""
    )
    # Missing and stale fail the check; a freeze is only worth a look
    assert not status.ok
    report = format_status(status)
    assert "Answers citing evidence that isn't there: 1" in report
    assert "Answers whose evidence the pipeline would rebuild: 2" in report
    assert "Answers resting on a frozen stage, unpinned: 2 (worth a look)" in (
        report
    )
    # Pinned to a ref that does exist: read there, and nothing the working
    # tree does afterwards touches it
    ck_info["questions"][3]["evidence"][0]["git_ref"] = sha
    os.remove("results/drifted.json")
    checked = check_question(
        4,
        ck_info["questions"][3],
        ck_info,
        ".",
        calkit.git.get_repo("."),
        stale_stages=stale,
        frozen_stages=frozen,
    )
    assert checked.status == "ok"
    assert checked.evidence[0].current == 2
    assert checked.evidence[0].git_ref == sha


def test_check_questions_frozen_subproject(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    os.makedirs("decisions")
    with open("decisions/n.txt", "w") as f:
        f.write("2\n")
    sub_info = {
        "pipeline": {
            "stages": {
                "measure": {
                    "kind": "shell-command",
                    "environment": "_system",
                    "command": "echo '{\"v\": 2}' > result.json",
                    "inputs": ["n.txt"],
                    "outputs": [{"path": "result.json", "storage": "git"}],
                }
            }
        },
        "questions": [
            {
                "question": "How big?",
                "answer": "{v}.",
                "evidence": [
                    {
                        "kind": "value",
                        "path": "result.json",
                        "key": "v",
                        "name": "v",
                    }
                ],
            }
        ],
    }
    with open("decisions/calkit.yaml", "w") as f:
        calkit.ryaml.dump(sub_info, f)
    ck_info = calkit.load_calkit_info()
    ck_info["subprojects"] = [{"path": "decisions"}]
    _write_yaml(ck_info)
    subprocess.check_call(["calkit", "run"])
    # Frozen once run, and still matching dvc.lock, so as current as ever
    sub_info["pipeline"]["stages"]["measure"]["frozen"] = True
    with open("decisions/calkit.yaml", "w") as f:
        calkit.ryaml.dump(sub_info, f)
    subprocess.check_call(["calkit", "run"])
    assert frozen_tainted_stage_names(wdir="decisions") == set()
    # And checked from the parent, with where it came from
    status = check_questions(wdir=".")
    assert [(q.project, q.index, q.status) for q in status.questions] == [
        ("decisions", 1, "ok")
    ]
    assert status.ok
    assert "decisions: 1. [ok] How big?" in format_status(status, True)
    # Once its input moves, it won't be rerun, which is worth a look
    with open("decisions/n.txt", "w") as f:
        f.write("3\n")
    assert frozen_tainted_stage_names(wdir="decisions") == {"measure"}
    status = check_questions(wdir=".")
    assert [q.status for q in status.questions] == ["frozen"]
    assert status.ok
    # Pinned to a commit, it's read from there, relative to the subproject,
    # both to check it and to fill in the answer
    sha = _commit("Measure")
    sub_info["questions"][0]["evidence"][0]["git_ref"] = sha
    with open("decisions/calkit.yaml", "w") as f:
        calkit.ryaml.dump(sub_info, f)
    with open("decisions/result.json", "w") as f:
        f.write('{"v": 5}\n')
    status = check_questions(wdir=".")
    assert [q.status for q in status.questions] == ["ok"]
    sub_ck_info = calkit.load_calkit_info(wdir="decisions")
    rendered = render_question(
        sub_ck_info["questions"][0], wdir="decisions", strict=True
    )
    assert isinstance(rendered, dict)
    assert rendered["answer"] == "2."


def test_sign_offs_and_stages(tmp_dir):
    subprocess.check_call(["git", "init", "-q"])
    os.makedirs("results")
    with open("results/summary.json", "w") as f:
        json.dump({"r": 2.0}, f)
    with open("results/plot.png", "w") as f:
        f.write("png")
    with open("fit.py", "w") as f:
        f.write("fit()\n")
    # Only what dvc.lock lists for the question's stages is followed
    with open("dvc.lock", "w") as f:
        calkit.ryaml.dump(
            {
                "schema": "2.0",
                "stages": {
                    "fit": {
                        "cmd": "python fit.py",
                        "deps": [{"path": "fit.py"}],
                    },
                    "unrelated": {
                        "cmd": "python other.py",
                        "deps": [{"path": "other.py"}],
                    },
                },
            },
            f,
        )
    question = {
        "question": "Does it work?",
        "approach": "Fit it, then summarize the fit.",
        "answer": "It does, by {r}x.",
        "evidence": [
            {"kind": "value", "path": "results/summary.json", "key": "r"},
            {"kind": "figure", "path": "results/plot.png"},
        ],
    }
    ck_info = {
        "pipeline": {
            "stages": {
                "plot": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "plot.py",
                    "inputs": [{"from_stage_outputs": "summarize"}],
                    "outputs": ["results/plot.png"],
                },
                "summarize": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "summarize.py",
                    "inputs": ["summarize.py", "results/fit.json"],
                    "outputs": [
                        {"path": "results/summary.json", "storage": "git"}
                    ],
                },
                "fit": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "fit.py",
                    "outputs": ["results/fit.json"],
                },
                "unrelated": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "other.py",
                    "outputs": ["results/other.json"],
                },
            }
        },
        "questions": [question],
    }

    def check(**kwargs):
        return check_questions(wdir=".", check_pipeline=False, **kwargs)

    def sign_off(date="2026-10-04"):
        by = {"name": "Ada", "email": "ada@example.org"}
        question["verifications"] = [{"by": by, "date": date}]
        question["validations"] = [{"by": by, "date": date}]
        _write_yaml(ck_info)
        _commit(f"Sign off {date}")

    # The stages behind the evidence, upstream first, followed through
    # both input paths and from_stage_outputs
    _write_yaml(ck_info)
    status = check()
    q = status.questions[0]
    assert q.stages == ["fit", "summarize", "plot"]
    assert q.approach and not q.hypothesis
    assert (q.verification_status, q.validation_status) == ("none", "none")
    lines = format_status(status).splitlines()
    assert "Answers verified: 0/1" in lines
    assert "Answers validated: 0/1" in lines
    # Statuses are in the JSON the editor and hub read
    dumped = q.model_dump(mode="json")
    assert dumped["verification_status"] == "none"
    assert dumped["validation_status"] == "none"
    # Paths in a stage are relative to its wdir, and a LaTeX stage's PDF is
    # its output without being listed
    wdir_info = {
        "pipeline": {
            "stages": {
                "collect": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "collect.py",
                    "outputs": ["data/raw.csv"],
                },
                "fit": {
                    "kind": "python-script",
                    "environment": "py",
                    "wdir": "analysis",
                    "script_path": "fit.py",
                    "inputs": ["../data/raw.csv"],
                    "outputs": ["summary.json"],
                },
                "paper": {
                    "kind": "latex",
                    "environment": "tex",
                    "target_path": "paper/main.tex",
                    "inputs": ["analysis/summary.json"],
                },
            }
        }
    }
    for path, expected in [
        ("analysis/summary.json", ["collect", "fit"]),
        ("paper/main.pdf", ["collect", "fit", "paper"]),
        ("paper/main.tex", []),
    ]:
        q_dict = {"question": "Q?", "evidence": [{"path": path}]}
        assert question_stages(q_dict, wdir_info) == expected, path
    # A sign-off not yet committed covers the working tree
    question["validations"] = [
        {
            "by": {"name": "Ada", "email": "ada@example.org"},
            "date": "2026-10-04",
        }
    ]
    _write_yaml(ck_info)
    q = check().questions[0]
    assert q.validation_status == "current"
    assert "not yet committed" in (q.validations[0].message or "")
    # Committed, each applies to that commit
    sign_off()
    status = check()
    assert status.questions[0].validations[0].commit is not None
    assert status.questions[0].verification_status == "current"
    assert status.questions[0].validation_status == "current"
    assert status.ok
    # Evidence changing makes a validation stale, which fails the check,
    # but not a verification, since no stage changed
    with open("results/summary.json", "w") as f:
        json.dump({"r": 3.0}, f)
    _commit("Rerun")
    status = check()
    q = status.questions[0]
    assert (q.verification_status, q.validation_status) == ("current", "stale")
    assert "results/summary.json: r was 2 at" in (
        q.validations[0].message or ""
    )
    assert not status.ok
    assert [s.index for s in status.stale_validations] == [1]
    assert not status.stale_verifications
    report = format_status(status)
    assert (
        "1. [ok, verification current, validation stale] Does it work?"
        in report
    )
    assert "validated by Ada on 2026-10-04 [stale]" in report
    assert "verified by" not in report
    assert (
        "Answers validated: 1/1, stale since their question or evidence "
        "changed: 1" in report
    )
    assert format_summary(status) == "1 question, 1 with a stale validation"
    # The generic nudge gives way to the validation's own
    assert "editing the answer or validating" not in (q.message or "")
    # At a ref, as the hub reads it, the check is as of that commit, and
    # ignores the working tree
    import git

    repo = git.Repo(".")
    with open("results/summary.json", "w") as f:
        json.dump({"r": 2.0}, f)
    for ref, expected in [("HEAD~1", "current"), ("HEAD", "stale")]:
        sha = repo.git.rev_parse(ref)
        at_ref = calkit.questions._load_calkit_yaml_text(
            repo.git.show(f"{sha}:calkit.yaml")
        )
        _, validations = check_sign_offs(
            at_ref["questions"][0], at_ref, ".", repo, ref=sha
        )
        assert validations[0].status == expected, ref
    assert check().questions[0].validation_status == "current"
    repo.git.checkout("--", "results/summary.json")
    # Each kind goes stale on its own changes, and notes go stale on neither
    edits = [
        ("notes", "Checked twice.", "current", "current", None),
        ("answer", "It does.", "current", "stale", "question was edited"),
        ("question", "Does it?", "current", "stale", "question was edited"),
        ("approach", "Fit it.", "stale", "stale", "approach was edited"),
    ]
    for n, (field, value, verification, validation, reason) in enumerate(
        edits, start=5
    ):
        sign_off(date=f"2026-10-0{n}")
        question[field] = value
        _write_yaml(ck_info)
        _commit(f"Edit the {field}")
        q = check().questions[0]
        assert q.verification_status == verification, field
        assert q.validation_status == validation, field
        if reason:
            messages = [
                s.message or "" for s in q.verifications + q.validations
            ]
            assert any(reason in m for m in messages), (field, messages)
    # Code a stage runs changing makes a verification stale, but not a
    # validation, since the evidence didn't change; nor does code outside
    # the question's stages
    sign_off(date="2026-10-10")
    for path in ["fit.py", "other.py"]:
        with open(path, "w") as f:
            f.write("changed()\n")
    _commit("Refactor")
    q = check().questions[0]
    assert (q.verification_status, q.validation_status) == ("stale", "current")
    assert "fit.py: changed in 1 commit(s)" in (
        q.verifications[0].message or ""
    )
    assert "other.py" not in (q.verifications[0].message or "")
    # So does redefining one of its stages
    sign_off(date="2026-10-11")
    ck_info["pipeline"]["stages"]["plot"]["script_path"] = "plot2.py"
    _write_yaml(ck_info)
    _commit("Redefine")
    q = check().questions[0]
    assert q.verification_status == "stale"
    assert "stage plot was redefined" in (q.verifications[0].message or "")
    # Identical sign-offs on two questions each find their own question,
    # and evidence on a branch goes stale when the branch moves, but not
    # evidence pinned to a commit
    repo.git.branch("published")
    pinned = repo.git.rev_parse("HEAD")
    record = {
        "by": {"name": "Ada", "email": "ada@example.org"},
        "date": "2026-10-12",
    }
    question["validations"] = [record]
    ck_info["questions"].append(
        {
            "question": "Is it published?",
            "answer": "It is.",
            "evidence": [
                {
                    "kind": "value",
                    "path": "results/summary.json",
                    "key": "r",
                    "git_ref": "published",
                },
                {
                    "kind": "figure",
                    "path": "results/plot.png",
                    "git_ref": pinned,
                },
            ],
            "validations": [record],
        }
    )
    _write_yaml(ck_info)
    _commit("Sign off both", date="2099-01-01T00:00:00+00:00")
    statuses = [q.validation_status for q in check().questions]
    assert statuses == ["current", "current"]
    with open("results/summary.json", "w") as f:
        json.dump({"r": 4.0}, f)
    with open("results/plot.png", "w") as f:
        f.write("png2")
    _commit("Publish", date="2099-01-02T00:00:00+00:00")
    repo.git.branch("-f", "published", "HEAD")
    q = check().questions[1]
    assert q.validation_status == "stale"
    message = q.validations[0].message or ""
    assert "results/summary.json: r was 3 at" in message
    assert "plot.png" not in message
    ck_info["questions"].pop()
    _write_yaml(ck_info)
    # A stage's script counts even if it has never run, so dvc.lock has
    # nothing for it
    with open("summarize.py", "w") as f:
        f.write("summarize()\n")
    sign_off(date="2026-10-13")
    with open("summarize.py", "w") as f:
        f.write("summarize(again=True)\n")
    _commit("Edit a stage that hasn't run")
    q = check().questions[0]
    assert q.verification_status == "stale"
    assert "summarize.py: changed in 1 commit(s)" in (
        q.verifications[0].message or ""
    )
    # A stage reading calkit.yaml, as questions-to-latex does, doesn't make
    # a verification stale when someone else signs off in it
    lock = calkit.ryaml.load(open("dvc.lock"))
    lock["stages"]["fit"]["deps"].append({"path": "calkit.yaml"})
    with open("dvc.lock", "w") as f:
        calkit.ryaml.dump(lock, f)
    sign_off(date="2026-10-14")
    question["verifications"].append(
        {
            "by": {"name": "Bob", "email": "bob@example.org"},
            "date": "2026-10-14",
        }
    )
    _write_yaml(ck_info)
    _commit("Bob verifies")
    q = check().questions[0]
    assert [v.status for v in q.verifications] == ["current", "current"]
    # One made on a branch is checked from where it was added, so a change
    # on main it never saw counts, though main's commits are newer
    main = repo.active_branch.name
    repo.git.checkout("-q", "-b", "side")
    sign_off(date="2026-10-15")
    repo.git.checkout("-q", main)
    with open("fit.py", "w") as f:
        f.write("fit(differently=True)\n")
    with open("calkit.yaml", "a") as f:
        f.write("description: Changed on main.\n")
    _commit("Change main", date="2099-02-01T00:00:00+00:00")
    subprocess.check_call(
        ["git", "merge", "-q", "--no-edit", "side"],
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_COMMITTER_DATE": "2099-02-02T00:00:00+00:00",
        },
    )
    q = check().questions[0]
    assert q.verification_status == "stale"
    assert "fit.py: changed in 1 commit(s)" in (
        q.verifications[0].message or ""
    )
    # dvc.lock's paths are relative to the stage's wdir
    ck_info["pipeline"]["stages"]["fit"]["wdir"] = "analysis"
    ck_info["pipeline"]["stages"]["fit"]["outputs"] = ["../results/fit.json"]
    os.makedirs("analysis")
    with open("analysis/fit.py", "w") as f:
        f.write("fit()\n")
    sign_off(date="2026-10-16")
    with open("analysis/fit.py", "w") as f:
        f.write("fit(in_analysis=True)\n")
    _commit("Edit the stage in its wdir")
    q = check().questions[0]
    assert "fit" in q.stages
    assert q.verification_status == "stale"
    message = q.verifications[0].message or ""
    assert "analysis/fit.py: changed in 1 commit(s)" in message
    assert " fit.py" not in message
    lock_text = (
        "stages:\n  fit:\n    outs:\n    - path: out.txt\n      md5: abc\n"
    )
    for path, wdirs, expected in [
        ("analysis/out.txt", {"fit": "analysis"}, "abc"),
        ("out.txt", {"fit": "analysis"}, None),
        ("out.txt", None, "abc"),
    ]:
        assert calkit.questions._lock_hash(lock_text, path, wdirs) == expected
    # Without history, a sign-off can't be checked either way
    q = check(check_history=False).questions[0]
    assert q.verifications[0].status == "unchecked"
    assert q.verification_status == "current"
    # Sign-offs and the approach are part of the schema
    assert ProjectInfo.model_validate(calkit.load_calkit_info())
    for field in ["verifications", "validations"]:
        with pytest.raises(ValueError):
            Question.model_validate(
                {"question": "Q?", field: [{"by": {"name": "Ada"}}]}
            )


def test_format_summary():
    from calkit.questions import QuestionCheck

    def check(status, answered=True):
        return QuestionCheck(
            index=1, question="Q?", answered=answered, status=status
        )

    assert format_summary(QuestionsStatus()) == "No questions defined."
    # One clean question reads as a verdict, and counts are singular
    assert (
        format_summary(QuestionsStatus(questions=[check("ok")]))
        == "1 question, all answered with current evidence ✅"
    )
    # Everything worth knowing lands on the one line
    summary = format_summary(
        QuestionsStatus(
            questions=[
                check("ok"),
                check("unanswered", answered=False),
                check("unanswered", answered=False),
                check("stale"),
                check("missing"),
                check("error"),
                check("frozen"),
                check("no-evidence"),
            ]
        )
    )
    assert summary == (
        "8 questions, 2 unanswered, 1 with stale evidence, "
        "1 with missing evidence, 1 with broken references, "
        "1 resting on a frozen stage, 1 with no evidence"
    )


def test_latex_values(tmp_dir):
    with open("results.json", "w") as f:
        json.dump({"gain": 0.2531, "p": 0.007}, f)
    value = {"kind": "value", "path": "results.json"}
    ck_info = {
        "questions": [
            {
                "name": "staging",
                "question": "Does staging help?",
                "hypothesis": "Where the surrogate\n  fits poorly.",
                "answer": {
                    "if gain > 0": "Yes, by {gain:+.3f} (p {p:.3f}).",
                    "else": "No.",
                },
                "evidence": [
                    {**value, "key": "gain", "name": "gain"},
                    {**value, "key": "p", "name": "p"},
                ],
            },
            "Is this a bare question?",
            {"question": "Unanswered?", "notes": "Needs a run."},
        ]
    }
    values = latex_values(ck_info)
    # Addressable by position and by name, with the conditional resolved,
    # values templated, and folded YAML whitespace collapsed
    assert values["1.answer"] == values["staging.answer"]
    assert values["staging.answer"] == "Yes, by +0.253 (p 0.007)."
    assert values["staging.hypothesis"] == "Where the surrogate fits poorly."
    assert values["2.question"] == "Is this a bare question?"
    # Absent fields are left out rather than exposed as empty
    assert "3.answer" not in values and values["3.notes"] == "Needs a run."
    # A placeholder that can't be filled is an error, not literal text
    broken = {"questions": [{"question": "Q?", "answer": "Up {missing}."}]}
    with pytest.raises(ValueError, match="answer"):
        latex_values(broken)
    unreadable = {
        "questions": [
            {
                "question": "Q?",
                "answer": "{x}",
                "evidence": [
                    {"kind": "value", "path": "gone.json", "key": "x"}
                ],
            }
        ]
    }
    with pytest.raises(ValueError, match="gone.json"):
        latex_values(unreadable)
    duplicate = {
        "questions": [
            {"name": "a", "question": "One?"},
            {"name": "a", "question": "Two?"},
        ]
    }
    with pytest.raises(ValueError, match="'a'"):
        latex_values(duplicate)
    # A name can't be a number, which would collide with a position
    with pytest.raises(ValueError, match="can't be a number"):
        Question(name="2", question="Q?")
    numeric = {"questions": [{"name": "2", "question": "Q?"}, "Other?"]}
    with pytest.raises(ValueError, match="can't be a number"):
        latex_values(numeric)
    # The project model also rejects duplicate names
    with pytest.raises(ValueError, match="must be unique"):
        ProjectInfo.model_validate(duplicate)
    ProjectInfo.model_validate(
        {"questions": [{"name": "a", "question": "One?"}, "Two?"]}
    )
    # The stage gains calkit.yaml and the evidence, keeping declared
    # inputs and listing nothing twice
    ck_info["pipeline"] = {
        "stages": {
            "qa": {
                "kind": "questions-to-latex",
                "inputs": ["results.json", "extra.txt"],
                "outputs": ["qa.tex"],
            },
            "other": {"kind": "shell-command", "command": "true"},
        }
    }
    stages = expand_questions_stages(ck_info)["pipeline"]["stages"]
    assert stages["qa"]["inputs"] == [
        "results.json",
        "extra.txt",
        "calkit.yaml",
    ]
    assert "inputs" not in stages["other"]
    assert "inputs" not in ck_info["pipeline"]["stages"]["other"]
    assert ck_info["pipeline"]["stages"]["qa"]["inputs"] == [
        "results.json",
        "extra.txt",
    ]


def test_conditional_answers(tmp_dir):
    values = {"p": 0.007, "rho": 0.8373, "n": 17, "leader": "turns-max"}
    # Rendering picks the branch, then fills its placeholders
    answer = {
        "if p < 0.05": "{leader} predicts it (rho {rho:+.2f})",
        "else": "no feature predicts it",
    }
    assert render(answer, values) == "turns-max predicts it (rho +0.84)"
    assert render(answer, values | {"p": 0.2}) == "no feature predicts it"
    # Plain strings are untouched by the conditional path
    assert render("if and only if", values) == "if and only if"
    # Checking reports every clause's problems, including the clauses the
    # current values don't select, rather than crashing or passing
    with open("r.json", "w") as f:
        json.dump({"p": 0.2, "leader": "x"}, f)
    evidence = [
        {"kind": "value", "path": "r.json", "key": "p"},
        {"kind": "value", "path": "r.json", "key": "leader"},
    ]
    cases = [
        ({"if p < 0.5": "{leader}", "else": "no"}, []),
        (
            {"if p < 0.05": "x"},
            ["no condition of the conditional answer holds"],
        ),
        ({"when p < 1": "x"}, ["conditional answer: expected 'if'"]),
        (
            {"if leader < 0.05": "x", "else": "y"},
            ["cannot evaluate condition 'leader < 0.05'"],
        ),
        (
            {"if p > 0.1": "yes", "elif typo < 1": "x", "else": "{rhoo:.2f}"},
            [
                "condition 'typo < 1' names no evidence 'typo'",
                "placeholder {rhoo} names no evidence",
            ],
        ),
    ]
    ck_info = {
        "pipeline": {
            "stages": {
                "scan": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "s.py",
                    "outputs": ["r.json"],
                }
            }
        }
    }
    for answer, expected in cases:
        checked = check_question(
            1,
            {"question": "q", "answer": answer, "evidence": evidence},
            ck_info,
            ".",
        )
        messages = checked.message or ""
        assert (checked.status == "error") == bool(expected), answer
        for fragment in expected:
            assert fragment in messages, (answer, messages)
