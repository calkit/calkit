"""Questions judged from a repo at a ref.

The point of reading through a ref rather than the checkout: the hub's
clone sits on whatever branch it last happened to, so a check that read
the working tree would answer about the wrong commit.
"""

import json
import subprocess
from pathlib import Path

import git
import pytest
import yaml

from app.questions import questions_status

QUESTION = {
    "question": "Do the top structures use the rectifier?",
    "answer": "{n_top} of eight do.",
    "evidence": [
        {
            "kind": "value",
            "path": "results/findings.json",
            "key": "n_top",
            "name": "n_top",
        }
    ],
}


class CommitTree:
    """The files one commit holds, which is what RepoTree provides."""

    def __init__(self, commit: git.Commit) -> None:
        self.commit = commit

    def is_file(self, path: str) -> bool:
        try:
            return (self.commit.tree / path).type == "blob"
        except Exception:
            return False

    def read_bytes(self, path: str) -> bytes:
        return (self.commit.tree / path).data_stream.read()


@pytest.fixture
def answered_then_rerun(tmp_path: Path) -> tuple[git.Repo, dict, str, str]:
    """A project whose cited value moves in a commit after the answer."""
    repo = git.Repo.init(tmp_path)
    repo.config_writer().set_value("user", "email", "t@t.t").release()
    repo.config_writer().set_value("user", "name", "T").release()
    (tmp_path / "results").mkdir()
    ck_info = {"questions": [QUESTION]}
    (tmp_path / "calkit.yaml").write_text(yaml.safe_dump(ck_info))
    (tmp_path / "results/findings.json").write_text(json.dumps({"n_top": 8}))
    subprocess.check_call(["git", "add", "-A"], cwd=tmp_path)
    subprocess.check_call(["git", "commit", "-qm", "answer"], cwd=tmp_path)
    answered = repo.head.commit.hexsha
    (tmp_path / "results/findings.json").write_text(json.dumps({"n_top": 3}))
    subprocess.check_call(["git", "commit", "-qam", "rerun"], cwd=tmp_path)
    return repo, ck_info, answered, repo.head.commit.hexsha


def _status(repo: git.Repo, ck_info: dict, ref: str):
    return questions_status(
        ck_info=ck_info,
        tree=CommitTree(repo.commit(ref)),
        repo=repo,
        ref=ref,
    )


def test_the_ref_decides_whether_an_answer_is_stale(
    answered_then_rerun,
) -> None:
    repo, ck_info, answered, rerun = answered_then_rerun
    # At the commit that answered it, the answer matches what it cites
    at_answer = _status(repo, ck_info, answered)
    assert at_answer is not None
    assert at_answer.questions[0].status == "ok"
    # After the rerun it does not, and the message says which value moved
    after = _status(repo, ck_info, rerun)
    assert after is not None
    question = after.questions[0]
    assert question.status == "stale"
    assert "re-read it" in (question.message or "")
    evidence = question.evidence[0]
    assert evidence.status == "changed"
    assert evidence.current == 3
    assert f"n_top was 8 at {answered[:7]}, now 3" in (evidence.message or "")


def test_reads_the_value_the_ref_holds(answered_then_rerun) -> None:
    # Not the checkout's: reading the working tree would report 3 at both
    repo, ck_info, answered, rerun = answered_then_rerun
    assert (
        _status(repo, ck_info, answered).questions[0].evidence[0].current == 8
    )
    assert _status(repo, ck_info, rerun).questions[0].evidence[0].current == 3


def test_a_tree_it_cannot_read_reports_missing_rather_than_failing(
    tmp_path: Path,
) -> None:
    # A ref whose tree has none of the cited files is a real answer about
    # that ref, not an error: the evidence is missing there
    repo = git.Repo.init(tmp_path)
    subprocess.check_call(
        ["git", "commit", "-qm", "empty", "--allow-empty"], cwd=tmp_path
    )
    status = _status(repo, {"questions": [QUESTION]}, repo.head.commit.hexsha)
    assert status is not None
    assert status.questions[0].evidence[0].status == "missing"


def test_a_check_that_blows_up_says_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # None rather than an empty status: a project whose questions could not
    # be checked has not been found to be fine, and a page that cannot say
    # should show nothing rather than a clean bill of health
    def boom(**kwargs):
        raise RuntimeError("no")

    monkeypatch.setattr("app.questions.check_questions", boom)
    repo = git.Repo.init(tmp_path)
    assert (
        questions_status(
            ck_info={"questions": [QUESTION]},
            tree=CommitTree(None),  # type: ignore[arg-type]
            repo=repo,
            ref="whatever",
        )
        is None
    )
