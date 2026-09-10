"""Tests for deciding a reviewed document's changes item by item."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import calkit.review
from calkit.models.docx import LatexDocxMerge

FIXTURES = Path(__file__).parent.parent.parent / "test" / "docx"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    os.makedirs("paper")
    os.makedirs("reviews")
    for name in ["main.tex", "methods.tex"]:
        shutil.copy(FIXTURES / name, f"paper/{name}")
    shutil.copy(FIXTURES / "returned.docx", "reviews/returned.docx")
    subprocess.run(["git", "init", "-q"], check=True)
    return tmp_path


def test_plan_and_decide(project: Path) -> None:
    plan = calkit.review.plan("reviews/returned.docx")
    assert plan.source == "paper/main.tex"
    assert set(plan.paths) == {"paper/main.tex", "paper/methods.tex"}
    # Both of the reviewer's edits are still tracked, so nothing applies
    # unless the lead says so
    assert [e.status for e in plan.edits] == ["pending", "pending"]
    assert all(e.result is not None for e in plan.edits)
    assert all(e.authors == ["Bachant, Pete"] for e in plan.edits)
    main_edit = next(e for e in plan.edits if e.path == "paper/main.tex")
    methods_edit = next(e for e in plan.edits if e.path == "paper/methods.tex")
    assert "as shown by" in main_edit.proposed
    assert "sampling frequency" in methods_edit.sent
    assert main_edit.source and main_edit.result != main_edit.source
    # The reviewer's comment is new; the thread that went out is unchanged
    statuses = {c.entries[0].author: c.status for c in plan.comments}
    assert statuses["A. Reviewer"] == "new"
    assert statuses["T. Author"] == "unchanged"
    # Apply as the CLI would: pending edits wait, comments land
    record = calkit.review.apply(plan)
    assert [c.status for c in record.changes] == ["pending", "pending"]
    assert record.comments_added == 1
    assert "as shown by" not in Path("paper/main.tex").read_text()
    assert "%   A. Reviewer" in Path("paper/main.tex").read_text()
    # Now decide: take one, decline the other, and keep the comment out
    plan = calkit.review.plan("reviews/returned.docx")
    reviewer = next(
        c for c in plan.comments if c.entries[0].author == "A. Reviewer"
    )
    assert reviewer.status == "unchanged"
    record = calkit.review.apply(
        plan, accept={main_edit.key}, reject={methods_edit.key}
    )
    by_key = {c.key: c.status for c in record.changes}
    assert by_key == {main_edit.key: "applied", methods_edit.key: "rejected"}
    assert (
        "as shown by \\citet{smith2020}" in Path("paper/main.tex").read_text()
    )
    assert "sampling frequency" in Path("paper/methods.tex").read_text()
    path = calkit.review.write_record(record)
    assert LatexDocxMerge.model_validate_json(Path(path).read_text())
    # The decisions stick on the next pass
    plan = calkit.review.plan("reviews/returned.docx")
    by_key = {e.key: e.status for e in plan.edits}
    assert by_key == {
        main_edit.key: "already-applied",
        methods_edit.key: "rejected",
    }
    record = calkit.review.apply(plan, accept=set())
    assert {c.status for c in record.changes} == {
        "already-applied",
        "rejected",
    }
    # Dismissing a comment removes nothing but is remembered too
    plan = calkit.review.plan("reviews/returned.docx")
    record = calkit.review.apply(plan, accept=set(), dismiss={reviewer.key})
    assert next(
        c for c in record.comments if c.key == reviewer.key
    ).status == ("dismissed")
    calkit.review.write_record(record)
    plan = calkit.review.plan("reviews/returned.docx")
    assert (
        next(c for c in plan.comments if c.key == reviewer.key).status
        == "dismissed"
    )
    assert "Applied 0 edits" in calkit.review.summary(record)


def test_plan_rejects_foreign_documents(project: Path) -> None:
    shutil.copy(FIXTURES / "word-import.docx", "reviews/foreign.docx")
    with pytest.raises(calkit.review.NotAnExportError):
        calkit.review.plan("reviews/foreign.docx")


def test_plan_from_outside_the_project(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project.parent)
    plan = calkit.review.plan("reviews/returned.docx", wdir=str(project))
    assert plan.wdir == str(project)
    assert set(plan.paths) == {"paper/main.tex", "paper/methods.tex"}
    keys = [e.key for e in plan.edits]
    record = calkit.review.apply(plan, accept=set(keys))
    assert [c.status for c in record.changes] == ["applied", "applied"]
    assert "as shown by" in (project / "paper/main.tex").read_text()
    rel = calkit.review.write_record(record, wdir=str(project))
    assert not os.path.isabs(rel) and (project / rel).is_file()
    assert not os.path.exists(project.parent / rel)
    plan = calkit.review.plan("reviews/returned.docx", wdir=str(project))
    assert {e.status for e in plan.edits} == {"already-applied"}
