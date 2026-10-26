"""Tests for ``cli.show``."""

import os
import subprocess
import sys

import pytest

import calkit


@pytest.mark.skipif(
    sys.platform == "win32", reason="Stands in for the editor with a script"
)
def test_show_latex_diff(tmp_dir, tmp_path_factory):
    stubs = tmp_path_factory.mktemp("stubs")
    opened = stubs / "opened.txt"
    with open(stubs / "code", "w") as f:
        f.write(f'#!/usr/bin/env bash\necho "$@" > {opened}\n')
    os.chmod(stubs / "code", 0o755)
    # As VS Code's integrated terminal sets it, so the editor is used rather
    # than the system's viewer
    env = os.environ | {
        "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        "TERM_PROGRAM": "vscode",
    }

    def show(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["calkit", "show", "latex-diff", *args],
            capture_output=True,
            text=True,
            env=env,
        )

    subprocess.check_call(["git", "init", "-q", "-b", "main", "."])
    subprocess.check_call(["calkit", "dvc", "init", "-q"])
    os.makedirs("paper")
    with open("paper/main.tex", "w") as f:
        f.write("Hello\n")
    ck_info = {
        "environments": {"tex": {"kind": "docker", "image": "texlive"}},
        "pipeline": {
            "stages": {
                "paper": {
                    "kind": "latex",
                    "environment": "tex",
                    "target_path": "paper/main.tex",
                    "diffs": ["v1", ["v1", "v2"]],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["git", "add", "-A"])
    subprocess.check_call(
        [
            "git",
            "-c",
            "user.email=t@e.com",
            "-c",
            "user.name=T",
            "commit",
            "-qm",
            "first",
        ]
    )
    # Which diff has to be clear
    result = show()
    assert result.returncode != 0
    assert "More than one diff matches" in result.stderr
    result = show("paper/main.pdf")
    assert "More than one diff matches" in result.stderr
    result = show("nope")
    assert "No LaTeX diff matches 'nope'" in result.stderr
    # One that isn't built says how to build it
    result = show("paper-diff-v1")
    assert result.returncode != 0
    assert "calkit run paper-diff-v1" in result.stderr
    assert not opened.exists()
    # A built one opens in the editor
    os.makedirs(".calkit/env-locks/tex")
    with open(".calkit/env-locks/tex/arm64.json", "w") as f:
        f.write("{}\n")
    out = ".calkit/latex-diffs/v1/paper/main.pdf"
    os.makedirs(os.path.dirname(out))
    with open(out, "w") as f:
        f.write("diff\n")
    subprocess.check_call(["calkit", "dvc", "commit", "-qf", "paper-diff-v1"])
    result = show("paper-diff-v1")
    assert result.returncode == 0, result.stderr
    assert opened.read_text().strip() == out
    assert "stale" not in result.stdout
    # A stale one still opens, with a warning, so it can be read while it's
    # rebuilt
    opened.unlink()
    with open("paper/main.tex", "a") as f:
        f.write("More\n")
    result = show(out)
    assert result.returncode == 0, result.stderr
    assert "is stale" in result.stdout
    assert opened.read_text().strip() == out


def test_show_question(tmp_dir):
    import json

    def show(*args: str) -> str:
        return subprocess.check_output(
            ["calkit", "show", "q", *args], text=True
        )

    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(["calkit", "new", "question", "Does it work?"])
    os.makedirs("results")
    with open("results/metrics.json", "w") as f:
        json.dump({"accuracy": 0.9, "scores": {"f1": 0.8}}, f)
    ck_info = calkit.load_calkit_info()
    ck_info["questions"].append(
        {
            "question": "What is the effect?",
            "name": "effect",
            "hypothesis": "It improves performance.",
            "approach": "Score it.",
            "answer": "Accuracy is {acc}.",
            "evidence": [
                {"kind": "figure", "path": "figures/performance.png"},
                {
                    "kind": "publication",
                    "path": "paper/paper.pdf",
                    "explanation": "See the results section.",
                },
                {
                    "kind": "result",
                    "path": "results/metrics.json",
                    "values": {"acc": "accuracy", "f1": "scores.f1"},
                },
            ],
            "verifications": [
                {
                    "by": {
                        "name": "Ada",
                        "email": "ada@example.org",
                        "with_ai": "Claude Opus 5",
                    },
                    "date": "2026-10-04",
                    "notes": "Read metrics.py.",
                }
            ],
        }
    )
    ck_info["pipeline"] = {
        "stages": {
            "metrics": {
                "kind": "python-script",
                "environment": "py",
                "script_path": "metrics.py",
                "outputs": ["results/metrics.json"],
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    # By position or name, as Markdown rendered from the evidence, with the
    # stages derived ahead of the answer and each sign-off's status
    out = show("effect")
    assert out == show("2")
    assert out.startswith("# 2. What is the effect?\n\n`H A V -`\n\n")
    assert "**Stages:** `metrics`\n\n**Answer:** Accuracy is 0.9.\n" in out
    assert "## Evidence\n\n- Figure `figures/performance.png` *(missing" in out
    assert ": See the results section. *(missing" in out
    # A result's values are listed under it, with what they read
    assert (
        "- Result `results/metrics.json`\n"
        "  - `acc` at `accuracy` = 0.9\n"
        "  - `f1` at `scores.f1` = 0.8\n"
    ) in out
    assert (
        "## Verifications\n\n- Ada (with Claude Opus 5), 2026-10-04 "
        "*(current: not yet committed"
    ) in out
    assert out.endswith(": Read metrics.py.\n")
    # Fields that aren't set aren't shown
    assert "None" not in out and "Validations" not in out
    assert show("1") == "# 1. Does it work?\n\n`- - - -`\n"
    # As written, and for tools
    assert "**Answer:** Accuracy is {acc}." in show("2", "--raw")
    shown = json.loads(show("effect", "--json"))
    assert shown["answer"] == "Accuracy is 0.9."
    assert shown["stages"] == ["metrics"]
    assert shown["verifications"][0]["by"]["email"] == "ada@example.org"
    assert shown["check"]["verification_status"] == "current"
    # A conditional answer left in its branches lists them
    ck_info["questions"][1]["answer"] = {"if acc > 0.5": "Yes.", "else": "No."}
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    assert (
        "**Answer:**\n\n- **if** `acc > 0.5`: Yes.\n- **else**: No.\n"
    ) in show("2", "--raw")
    # A question that isn't there is an error
    for ref, message in [("3", "There is no question 3"), ("x", "named 'x'")]:
        result = subprocess.run(
            ["calkit", "show", "q", ref], capture_output=True, text=True
        )
        assert result.returncode != 0
        assert message in result.stdout + result.stderr
