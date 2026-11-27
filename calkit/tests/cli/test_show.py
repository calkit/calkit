"""Tests for ``cli.show``."""

import json
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


def _project_with_a_result_and_a_table():
    import git

    repo = git.Repo.init()
    os.makedirs("results", exist_ok=True)
    with open("results/kernels.csv", "w") as f:
        f.write(
            "kernel,registers_baseline,registers_mod,U [m/s]\n"
            "microphysics,255,153,[b]1\ncloud_fraction,38,38,[/x]\n"
        )
    with open("results/summary.json", "w") as f:
        f.write('{"speedup_pct": 5.35, "device": {"change_pct": -6.25}}')
    ck_info = {
        "pipeline": {
            "stages": {
                "export": {
                    "kind": "shell-command",
                    "command": "echo hi",
                    "outputs": ["results/kernels.csv"],
                }
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    repo.git.add(all=True)
    repo.git.commit("-m", "Add a result and a table")
    return repo


def test_show_table(tmp_dir):
    _project_with_a_result_and_a_table()
    out = subprocess.check_output(
        ["calkit", "show", "table", "results/kernels.csv"], text=True
    )
    assert "registers_baseline" in out
    assert "microphysics" in out
    # Brackets, e.g., units, are shown as written rather than as markup
    assert "U [m/s]" in out
    assert "[b]1" in out
    assert "[/x]" in out
    # Columns can be globbed and rows filtered, and the footer says what
    # was left out
    out = subprocess.check_output(
        [
            "calkit",
            "show",
            "table",
            "results/kernels.csv",
            "-c",
            "kernel,*_mod",
            "-f",
            "registers_baseline>100",
        ],
        text=True,
    )
    assert "registers_baseline" not in out
    assert "cloud_fraction" not in out
    assert "1 of 2 rows" in out
    # A column that isn't there names the ones that are
    result = subprocess.run(
        ["calkit", "show", "table", "results/kernels.csv", "-c", "regs"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "registers_baseline" in result.stdout + result.stderr
    # At a Git ref the committed version is read, not the working tree
    with open("results/kernels.csv", "a") as f:
        f.write("new_kernel,1,1\n")
    out = subprocess.check_output(
        [
            "calkit",
            "show",
            "table",
            "results/kernels.csv",
            "--git-ref",
            "HEAD",
        ],
        text=True,
    )
    assert "new_kernel" not in out
    assert "@ HEAD" in out
    # A table that doesn't exist says where to look
    result = subprocess.run(
        ["calkit", "show", "table", "results/absent.csv"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "calkit list tables" in result.stdout + result.stderr


def test_show_result(tmp_dir):
    _project_with_a_result_and_a_table()
    out = subprocess.check_output(
        ["calkit", "show", "result", "results/summary.json"], text=True
    )
    # Keys are shown dotted, the way a question's evidence names them
    assert "device.change_pct" in out
    assert "-6.25" in out
    out = subprocess.check_output(
        [
            "calkit",
            "show",
            "result",
            "results/summary.json",
            "-k",
            "device.change_pct",
            "--json",
        ],
        text=True,
    )
    assert json.loads(out) == [
        {"key": "device.change_pct", "value": "-6.25", "type": "float"}
    ]
    # The status line stays out of JSON output
    out = subprocess.check_output(
        [
            "calkit",
            "show",
            "result",
            "results/summary.json",
            "-k",
            "speedup_pct",
            "--json",
            "--status",
        ],
        text=True,
    )
    assert json.loads(out)[0]["key"] == "speedup_pct"
    # A key that isn't there names the ones that are
    result = subprocess.run(
        [
            "calkit",
            "show",
            "result",
            "results/summary.json",
            "-k",
            "speedup",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "speedup_pct" in result.stdout + result.stderr
    # A tabular file is a result too, and says how to read it
    result = subprocess.run(
        ["calkit", "show", "result", "results/kernels.csv"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "show table" in result.stdout + result.stderr


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
                {
                    "path": "results/metrics.json",
                    "lines": 1,
                    "explanation": "The raw output.",
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
    # A file without a kind is cited as is, at its lines
    assert "- File `results/metrics.json`, line 1: The raw output.\n" in out
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
    # A value without a key is shown with its error rather than crashing
    ck_info["questions"][1]["evidence"].append(
        {"kind": "value", "path": "results/metrics.json"}
    )
    # A subproject's question is addressed as it's listed
    os.makedirs("sub")
    with open("sub/calkit.yaml", "w") as f:
        calkit.ryaml.dump({"questions": ["Does the sub work?"]}, f)
    ck_info["subprojects"] = [{"path": "sub"}]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    assert (
        "- Value `results/metrics.json` *(error: value evidence needs a key)*"
    ) in show("2")
    assert show("sub:1") == "# sub: 1. Does the sub work?\n\n`- - - -`\n"
    # A question that isn't there is an error
    for ref, message in [
        ("3", "There is no question 3"),
        ("x", "named 'x'"),
        ("sub:2", "There is no question 2"),
        ("nope:1", "named 'nope:1'"),
    ]:
        result = subprocess.run(
            ["calkit", "show", "q", ref], capture_output=True, text=True
        )
        assert result.returncode != 0
        assert message in result.stdout + result.stderr


def test_show_provenance(tmp_dir):
    import dvc.repo

    import calkit.dvc

    def show(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["calkit", "show", "provenance", *args],
            capture_output=True,
            text=True,
        )

    def write_stages() -> None:
        ck_info = calkit.load_calkit_info()
        ck_info["pipeline"] = {"stages": stages}
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)

    subprocess.check_call(["calkit", "init"])
    with open("data.csv", "w") as f:
        f.write("x\n1\n")
    # The same in Windows' shell as in others
    py = f'"{sys.executable}" -c'
    stages: dict = {
        "clean": {
            "kind": "command",
            "environment": "_system",
            "command": (
                f"{py} \"open('clean.csv', 'w').write(open('data.csv')"
                '.read())"'
            ),
            "inputs": ["data.csv"],
            "outputs": ["clean.csv"],
        },
        "summarize": {
            "kind": "command",
            "environment": "_system",
            "command": (
                f'{py} "import json; '
                "json.dump({'n': 1}, open('results.json', 'w'))\""
            ),
            "inputs": ["clean.csv"],
            "outputs": ["results.json"],
        },
        "each": {
            "kind": "command",
            "environment": "_system",
            "command": f"{py} \"open('{{n}}.txt', 'w').write('{{n}}')\"",
            "iterate_over": [{"arg_name": "n", "values": ["x", "y"]}],
            "outputs": ["{n}.txt"],
        },
    }
    write_stages()
    subprocess.check_call(["calkit", "run"])
    # The value, that it's current, and each stage behind it, nearest first,
    # down to the data nothing records the origin of
    res = show("results.json", "--key", "n")
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert out.startswith("results.json\nn = 1\nUp to date\n")
    assert out.index("Stage summarize") < out.index("Stage clean")
    assert "Makes: clean.csv" in out
    assert "Inputs:\n    clean.csv: from stage clean" in out
    assert "data.csv: origin not defined" in out
    assert " UTC, " in out
    # Complete for agents, with nothing else on stdout
    chain = json.loads(show("results.json", "-k", "n", "--json").stdout)
    assert chain["value"] == 1 and chain["up_to_date"] is True
    assert chain["status_error"] is None
    assert [s["name"] for s in chain["stages"]] == ["summarize", "clean"]
    assert chain["stages"][1]["last_run"]["git_rev"]
    # A key that isn't there is an error naming those that are
    res = show("results.json", "--key", "nope")
    assert res.returncode != 0
    assert "No key 'nope' in results.json; it has n" in res.stderr
    # An iteration's command is as it ran
    out = show("x.txt").stdout
    assert "Stage each@x (command)" in out
    assert "write('x')" in out and "{n}" not in out
    # What a stage's source is, or reads it, rather than what makes it
    out = show("data.csv").stdout
    assert "Read by stage clean" in out
    # Whether it's up to date isn't said if it can't be checked, e.g., while
    # another process holds DVC's lock
    with open("data.csv", "w") as f:
        f.write("x\n2\n")
    dvc_repo = calkit.dvc.get_dvc_repo()
    try:
        with dvc.repo.lock_repo(dvc_repo):
            res = show("results.json")
            chain = json.loads(show("results.json", "--json").stdout)
    finally:
        dvc_repo.close()
    assert "Couldn't check whether it's up to date" in res.stderr
    assert "Status unknown" in res.stdout and "Up to date" not in res.stdout
    assert chain["up_to_date"] is None and chain["status_error"]
    # A change upstream says what changed, and what's waiting on it
    out = show("results.json").stdout
    assert "\nOut of date: waiting on clean.csv\n" in out
    assert "  Out of date: data.csv modified" in out
    assert "data.csv: origin not defined; modified" in out
    # Something read now that wasn't when it last ran is new, not modified,
    # and the stage making it is followed
    stages["summarize"]["inputs"].append("x.txt")
    write_stages()
    out = show("results.json").stdout
    assert "Out of date: x.txt new since last run" in out
    assert "x.txt: from stage each@x; new since last run" in out
    assert "Stage each@x" in out
    stages["summarize"]["inputs"].remove("x.txt")
    # A frozen stage whose inputs changed says what did, and that running
    # the pipeline won't remake it, and so does what's made after it
    stages["clean"]["frozen"] = True
    write_stages()
    out = show("results.json").stdout
    assert (
        "\nOut of date: made from outputs of frozen stage clean, which "
        "`calkit run` won't remake without --force\n"
    ) in out
    assert (
        "  Frozen: inputs changed since its outputs were made (data.csv); "
        "only `calkit run clean --force` remakes them"
    ) in out
    assert "waiting on" not in out
    chain = json.loads(show("results.json", "--json").stdout)
    summarize, clean = chain["stages"]
    assert summarize["after_frozen"] == ["clean"] and not summarize["frozen"]
    assert clean["frozen"] and clean["frozen_changes"] == ["data.csv"]
    del stages["clean"]["frozen"]
    write_stages()
    subprocess.check_call(["calkit", "run"])
    # An output that isn't here may only need pulling
    os.remove("clean.csv")
    out = show("clean.csv").stdout
    assert "Missing: clean.csv; `calkit pull` may be all it needs" in out
    # Something that isn't there, and nothing makes, is an error
    res = show("typo.json")
    assert res.returncode != 0
    assert "no stage makes it" in res.stderr
