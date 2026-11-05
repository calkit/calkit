"""Tests for ``cli.delete``."""

import json
import os
import subprocess

import pytest

import calkit


def test_rm_question(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(["calkit", "new", "question", "First question?"])
    subprocess.check_call(["calkit", "new", "question", "Second question?"])
    assert calkit.load_calkit_info()["questions"] == [
        "First question?",
        "Second question?",
    ]
    # Remove the first (1-indexed)
    subprocess.check_call(["calkit", "rm", "question", "1"])
    assert calkit.load_calkit_info()["questions"] == ["Second question?"]
    # Out-of-range index fails
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(["calkit", "rm", "question", "5"])


def test_delete_comment(tmp_dir):
    def ck(*args: str) -> str:
        return subprocess.run(
            ["calkit", *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    os.makedirs("paper")
    with open("paper/main.tex", "w") as f:
        f.write("\\input{intro}\n\nA paragraph.\n")
    with open("paper/intro.tex", "w") as f:
        f.write("% COMMENT id=aaaa0001\n%   A:\n%     Why?\nIntro text.\n")
    with open("note.md", "w") as f:
        f.write("<!-- COMMENT id=bbbb0002\n  B:\n    Hm.\n-->\nSome text.\n")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "pipeline": {
                    "stages": {
                        "paper": {
                            "kind": "latex",
                            "target_path": "main.tex",
                            "wdir": "paper",
                            "environment": "_system",
                        },
                        "note": {
                            "kind": "markdown",
                            "target_path": "note.md",
                            "pdf": {"environment": "_system"},
                        },
                    }
                }
            },
            f,
        )
    # By ID, from any of the project's documents, or by line in a file,
    # leaving the rest of it alone
    ck("delete", "comment", "--id", "aaaa0001")
    with open("paper/intro.tex") as f:
        assert f.read() == "Intro text.\n"
    ck("delete", "comment", "note.md", "-l", "3")
    with open("note.md") as f:
        assert f.read() == "Some text.\n"
    assert json.loads(ck("list", "comments", "--json")) == []
    for args in [
        ["delete", "comment", "--id", "nope"],
        ["delete", "comment", "-l", "1"],
    ]:
        res = subprocess.run(["calkit", *args], capture_output=True)
        assert res.returncode != 0, args
