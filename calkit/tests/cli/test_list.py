"""Tests for ``cli.list``."""

import json
import os
import subprocess

import calkit


def test_list_environments(tmp_dir):
    subprocess.check_call("calkit list environments", shell=True)
    envs = {
        "py": {"kind": "uv-venv", "path": "requirements.txt"},
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"environments": envs}, f)
    out = subprocess.check_output(
        ["calkit", "list", "environments", "--json"], text=True
    )
    assert json.loads(out) == envs


def test_list_requirements(tmp_dir):
    subprocess.check_call(["calkit", "list", "reqs"])
    ck_info = {
        "requirements": [
            "git>=2.40",
            {
                "kind": "env-var",
                "name": "TOKEN",
                "setup_command": "claude setup-token",
            },
            {"kind": "aws-credentials", "account_id": "012345678901"},
            {"kind": "cpu-count", "min": 4},
        ],
        "environments": {
            "cluster": {
                "kind": "system",
                "requirements": [{"kind": "hostname", "matches": "*.edu"}],
            },
            "py": {"kind": "uv-venv", "path": "requirements.txt"},
            "site": {
                "kind": "switch",
                "switch": [
                    {
                        "when": [{"os_is": "linux"}],
                        "use": {
                            "kind": "system",
                            "requirements": ["sbatch"],
                        },
                    },
                    {"use": "cluster"},
                ],
            },
        },
        "pipeline": {
            "stages": {
                "fetch": {
                    "kind": "shell-command",
                    "command": "echo hi",
                    "requirements": [{"kind": "env-var", "name": "DATA"}],
                },
                "other": {"kind": "shell-command", "command": "echo hi"},
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    # Each is normalized and says where it was declared
    out = subprocess.check_output(
        ["calkit", "list", "requirements", "--json"], text=True
    )
    reqs = json.loads(out)
    assert [(r["source"], r["name"]) for r in reqs] == [
        ("project", "git"),
        ("project", "TOKEN"),
        ("project", "aws-credentials-012345678901"),
        ("project", "cpu-count"),
        ("environment 'cluster'", "hostname"),
        ("environment 'site.1'", "sbatch"),
        ("stage 'fetch'", "DATA"),
    ]
    assert reqs[0]["version_spec"] == ">=2.40"
    assert reqs[1]["setup_command"] == "claude setup-token"
    out = subprocess.check_output(["calkit", "list", "reqs"], text=True)
    assert "Project:\n  - git (app)\n      version_spec: >=2.40" in out
    assert "setup_command: claude setup-token" in out
    assert "  - cpu-count\n      min: 4" in out
    assert "Environment 'cluster':\n  - hostname" in out
    assert "Stage 'fetch':\n  - DATA (env-var)" in out
    # A malformed one says where it is
    ck_info["pipeline"]["stages"]["fetch"]["requirements"] = [
        {"kind": "env-var"}
    ]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    res = subprocess.run(
        ["calkit", "list", "reqs"], capture_output=True, text=True
    )
    assert res.returncode != 0
    assert "In stage 'fetch'" in res.stderr + res.stdout


def test_list_releases(tmp_dir):
    # Internal releases are never published, so no lookup is attempted, but
    # a stray 'published' key must not override the status we determined
    releases = {
        "v1": {"kind": "project", "internal": True, "published": "bogus"},
        "v2": {"kind": "project", "internal": True, "path": "paper.pdf"},
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"releases": releases}, f)
    out = subprocess.check_output(
        ["calkit", "list", "releases", "--json"], text=True
    )
    parsed = json.loads(out)
    assert parsed["v1"]["published"] is None
    assert parsed["v2"]["published"] is None
    assert parsed["v2"]["path"] == "paper.pdf"
    out = subprocess.check_output(["calkit", "list", "releases"], text=True)
    assert "v1:" in out
    assert "    kind: project" in out
    assert "bogus" not in out


def test_list_templates():
    # Templates are grouped by kind, since they aren't interchangeable.
    out = subprocess.check_output(["calkit", "list", "templates"], text=True)
    assert "latex:" in out and "project:" in out
    # A LaTeX template is named within the package; a project template
    # names a project on a hub, so it isn't `project/example-r`
    assert "  latex/article" in out
    assert "  calkit/example-r" in out
    assert "project/example-r" not in out
    # Each one says what it is, which is the point of a listing
    assert "Article (generic)" in out
    out = subprocess.check_output(
        ["calkit", "list", "templates", "--json"], text=True
    )
    groups = json.loads(out)
    assert set(groups) == {"latex", "project"}
    assert "latex/article" in [t["name"] for t in groups["latex"]]
    assert all(t["title"] for t in groups["project"])
    # One kind at a time, for a picker that only wants one
    out = subprocess.check_output(
        ["calkit", "list", "templates", "--kind", "project", "--json"],
        text=True,
    )
    assert set(json.loads(out)) == {"project"}
    assert (
        subprocess.call(
            ["calkit", "list", "templates", "--kind", "nope"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        != 0
    )


def test_list_stages(tmp_dir):
    subprocess.check_call("calkit list stages", shell=True)
    ck_info = {
        "pipeline": {
            "stages": {
                "stage1": {
                    "kind": "python-script",
                    "script_path": "train.py",
                    "environment": "_system",
                },
                "stage2": {
                    "kind": "shell-command",
                    "command": "echo Hello",
                    "environment": "_system",
                },
            }
        }
    }
    with open("train.py", "w") as f:
        f.write("print('Training...')\n")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    out = subprocess.check_output("calkit list stages", shell=True, text=True)
    assert "stage1" in out
    assert "stage2" in out
    out = subprocess.check_output(
        "calkit list stages --kind python-script", shell=True, text=True
    )
    assert "stage1" in out
    assert "stage2" not in out
    # Test the --stale option by making stage2 stale
    subprocess.check_call(["ck", "run", "stage1"])
    out = subprocess.check_output(
        ["calkit", "list", "stages", "--stale"], text=True
    )
    assert "stage1" not in out
    assert "stage2" in out
    # JSON output includes each stage's definition, and respects the filters
    out = subprocess.check_output(
        ["calkit", "list", "stages", "--json"], text=True
    )
    stages_json = json.loads(out)
    assert set(stages_json) == {"stage1", "stage2"}
    assert stages_json["stage2"]["command"] == "echo Hello"
    out = subprocess.check_output(
        ["calkit", "list", "stages", "--kind", "python-script", "--json"],
        text=True,
    )
    assert set(json.loads(out)) == {"stage1"}
    # Subprojects' stages are listed as 'calkit run' addresses them
    os.makedirs("sub/nested")
    with open("sub/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "subprojects": [{"path": "nested"}],
                "pipeline": {
                    "stages": {"s": ck_info["pipeline"]["stages"]["stage2"]}
                },
            },
            f,
        )
    with open("sub/nested/calkit.yaml", "w") as f:
        calkit.ryaml.dump({"pipeline": {"stages": {"n": {}}}}, f)
    ck_info["subprojects"] = [{"path": "sub"}]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    out = subprocess.check_output(["calkit", "list", "stages"], text=True)
    assert out.split() == ["stage1", "stage2", "sub:s", "sub/nested:n"]


def test_list_subprojects(tmp_dir):
    out = subprocess.check_output(["calkit", "list", "subprojects"], text=True)
    assert out == ""
    os.makedirs("a/b")
    os.makedirs("c")
    os.makedirs("missing-config")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "subprojects": [
                    {"path": "a", "description": "The A one."},
                    {"path": "c"},
                    # Skipped, as 'calkit run' skips it
                    {"path": "missing-config"},
                ]
            },
            f,
        )
    # A nested one, and one naming its parent, which isn't repeated
    with open("a/calkit.yaml", "w") as f:
        calkit.ryaml.dump({"subprojects": [{"path": "b"}, {"path": ".."}]}, f)
    for path in ["a/b", "c"]:
        with open(f"{path}/calkit.yaml", "w") as f:
            calkit.ryaml.dump({}, f)
    out = subprocess.check_output(["calkit", "list", "subprojects"], text=True)
    assert out.split() == ["a", "a/b", "c"]
    out = subprocess.check_output(
        ["calkit", "list", "subprojects", "--json"], text=True
    )
    assert json.loads(out) == {
        "a": {"parent": ".", "description": "The A one."},
        "a/b": {"parent": "a", "description": None},
        "c": {"parent": ".", "description": None},
    }


def test_list_latex_diffs(tmp_dir):
    def commit(message: str) -> None:
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
                message,
            ]
        )

    def listed() -> dict:
        out = subprocess.check_output(
            ["calkit", "list", "latex-diffs", "--json"], text=True
        )
        return {diff["stage"]: diff for diff in json.loads(out)}

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
    commit("first")
    subprocess.check_call(["git", "tag", "v1"])
    subprocess.check_call(["git", "tag", "v2"])
    diffs = listed()
    # A bare revision is compared with the working tree, and nothing has
    # been built yet
    assert diffs["paper-diff-v1"] == {
        "path": ".calkit/latex-diffs/v1/paper/main.pdf",
        "document": "paper/main.tex",
        "latex_stage": "paper",
        "stage": "paper-diff-v1",
        "from_ref": "v1",
        "to_ref": None,
        "status": "not built",
    }
    assert diffs["paper-diff-v1-v2"]["to_ref"] == "v2"
    assert diffs["paper-diff-v1-v2"]["status"] == "not built"
    # Once built it's current, until something it reads changes
    os.makedirs(".calkit/env-locks/tex")
    with open(".calkit/env-locks/tex/arm64.json", "w") as f:
        f.write("{}\n")
    out = ".calkit/latex-diffs/v1/paper/main.pdf"
    os.makedirs(os.path.dirname(out))
    with open(out, "w") as f:
        f.write("diff\n")
    subprocess.check_call(["calkit", "dvc", "commit", "-qf", "paper-diff-v1"])
    assert listed()["paper-diff-v1"]["status"] == "up to date"
    with open("paper/main.tex", "a") as f:
        f.write("More\n")
    assert listed()["paper-diff-v1"]["status"] == "stale"
    # The human-readable listing says what each compares
    out = subprocess.check_output(["calkit", "list", "latex-diffs"], text=True)
    assert "- path: .calkit/latex-diffs/v1/paper/main.pdf" in out
    assert "to: working tree" in out
    assert "status: stale" in out


def test_list_results(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    os.makedirs("results")
    with open("results/metrics.json", "w") as f:
        f.write("{}")
    out = subprocess.check_output(
        ["calkit", "list", "results", "--json"], text=True
    )
    entries = json.loads(out)
    paths = [e["path"] for e in entries]
    assert "results/metrics.json" in paths
    assert all(
        e["detected"] for e in entries if e["path"] == "results/metrics.json"
    )
    # --declared-only skips auto-detection
    out = subprocess.check_output(
        ["calkit", "list", "results", "--json", "--declared-only"], text=True
    )
    assert json.loads(out) == []


def test_list_presentations(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    os.makedirs("slides")
    with open("slides/deck.pdf", "w") as f:
        f.write("%PDF-1.4")
    out = subprocess.check_output(
        ["calkit", "list", "presentations", "--json"], text=True
    )
    paths = [e["path"] for e in json.loads(out)]
    assert "slides/deck.pdf" in paths


def test_list_questions(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(["calkit", "new", "question", "Does it work?"])
    ck_info = calkit.load_calkit_info()
    ck_info["questions"].append(
        {
            "question": "What is the effect?",
            "hypothesis": "It improves performance.",
            "answer": "It improves performance by 10%.",
            "evidence": [
                {"kind": "figure", "path": "figures/performance.png"},
                {
                    "kind": "result",
                    "path": "results/metrics.json",
                    "key": "accuracy",
                },
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
    out = subprocess.check_output(
        ["calkit", "list", "questions", "--json"], text=True
    )
    questions = json.loads(out)
    assert questions[0] == "Does it work?"
    # The stages behind the evidence are derived, ahead of the answer
    assert questions[1]["stages"] == ["metrics"]
    assert list(questions[1]).index("stages") < list(questions[1]).index(
        "answer"
    )
    assert questions[1]["question"] == "What is the effect?"
    assert questions[1]["hypothesis"] == "It improves performance."
    assert questions[1]["evidence"][2]["kind"] == "publication"
    assert questions[1]["evidence"][2]["path"] == "paper/paper.pdf"
    out = subprocess.check_output(["calkit", "list", "questions"], text=True)
    assert "1. Does it work?" in out
    assert "2. question: What is the effect?" in out
    assert "hypothesis: It improves performance." in out
    assert "    stages:\n        - metrics\n    answer:" in out
    assert "answer: It improves performance by 10%." in out
    assert "evidence:" in out
    assert "- kind: figure" in out
    assert "path: figures/performance.png" in out
    assert "- kind: result" in out
    assert "path: results/metrics.json" in out
    assert "key: accuracy" in out
    assert "- kind: publication" in out
    assert "path: paper/paper.pdf" in out
    assert "explanation: See the results section." in out
    # A result's values are listed one per line under it
    assert (
        "        values:\n          acc: accuracy\n          f1: scores.f1"
        in out
    )
    # Fields that aren't set aren't listed
    assert "None" not in out
    # Subprojects' are listed too, numbered within each, with evidence
    # read from where they're declared
    os.makedirs("sub/nested/results")
    with open("sub/nested/results/m.json", "w") as f:
        json.dump({"accuracy": 0.9}, f)
    with open("sub/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {"questions": ["Sub?"], "subprojects": [{"path": "nested"}]}, f
        )
    with open("sub/nested/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "questions": [
                    {
                        "question": "How accurate?",
                        "answer": "{acc}",
                        "evidence": [
                            {
                                "kind": "result",
                                "path": "results/m.json",
                                "values": {"acc": "accuracy"},
                            }
                        ],
                    }
                ]
            },
            f,
        )
    ck_info["subprojects"] = [{"path": "sub"}]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    out = subprocess.check_output(["calkit", "list", "questions"], text=True)
    assert "1. Does it work?" in out
    assert "sub: 1. Sub?" in out
    assert "sub/nested: 1. question: How accurate?" in out
    assert "answer: 0.9" in out
    out = subprocess.check_output(
        ["calkit", "list", "questions", "--json"], text=True
    )
    questions = json.loads(out)
    assert questions[0] == "Does it work?"
    assert questions[2] == {"project": "sub", "question": "Sub?"}
    assert questions[3]["project"] == "sub/nested"
    assert questions[3]["answer"] == "0.9"


def test_list_comments(tmp_dir):
    def ck(*args: str) -> str:
        return subprocess.run(
            ["calkit", *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    INTRO = "% COMMENT id=aaaa0001\n%   A:\n%     Why?\nIntro text.\n"
    NOTE = (
        "# Note\n\n<!-- COMMENT id=bbbb0002 resolved=true\n  B:\n    Hm.\n"
        "-->\nSome text.\n"
    )
    os.makedirs("paper")
    with open("paper/main.tex", "w") as f:
        f.write("\\input{intro}\n\nA paragraph.\n")
    with open("paper/intro.tex", "w") as f:
        f.write(INTRO)
    os.makedirs("docs")
    with open("docs/note.md", "w") as f:
        f.write(NOTE)
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
                            "target_path": "docs/note.md",
                            "pdf": {"environment": "_system"},
                        },
                    }
                }
            },
            f,
        )
    with open("README.md", "w") as f:
        f.write("% COMMENT id=cccc0003\n%   C:\n%     Not built.\nText.\n")
    # Without a path, every document built into a PDF is listed, with the
    # files it inputs, but nothing else
    listed = json.loads(ck("list", "comments", "--json"))
    assert [(c["path"], c["id"]) for c in listed] == [
        ("paper/intro.tex", "aaaa0001"),
        ("docs/note.md", "bbbb0002"),
    ]
    assert listed[1]["anchor"]["text"] == "Some text."
    # With one, only that document is, and open threads can be picked out
    listed = json.loads(ck("list", "comments", "docs/note.md", "--json"))
    assert [c["id"] for c in listed] == ["bbbb0002"]
    assert "bbbb0002" not in ck("list", "comments", "-u")
    assert "paper/intro.tex:1 [aaaa0001]" in ck("list", "comments")
    res = subprocess.run(
        ["calkit", "list", "comments", "missing.md"], capture_output=True
    )
    assert res.returncode != 0


def test_list_remotes(tmp_dir):
    # Outside a repo: should warn but not fail
    result = subprocess.run(
        ["calkit", "list", "remotes"], capture_output=True, text=True
    )
    assert result.returncode == 0
    # Inside a repo with a Git remote and a DVC remote
    subprocess.check_call(["git", "init"])
    subprocess.check_call(
        ["git", "remote", "add", "origin", "https://github.com/test/repo.git"]
    )
    subprocess.check_call(["dvc", "init", "-q"])
    subprocess.check_call(
        ["dvc", "remote", "add", "myremote", "s3://my-bucket/dvc"]
    )
    out = subprocess.check_output(["calkit", "list", "remotes"], text=True)
    assert "(Git) origin: https://github.com/test/repo.git" in out
    assert "(DVC) myremote: s3://my-bucket/dvc" in out
    out = subprocess.check_output(
        ["calkit", "list", "remotes", "--json"], text=True
    )
    assert json.loads(out) == {
        "git": {"origin": "https://github.com/test/repo.git"},
        "dvc": {"myremote": "s3://my-bucket/dvc"},
    }


def test_list_objects_json(tmp_dir):
    ck_info = {
        "notebooks": [{"path": "nb.ipynb", "title": "My notebook"}],
        "publications": [{"path": "paper.pdf", "kind": "journal-article"}],
        "references": [{"path": "refs.bib", "key": "my-refs"}],
        "procedures": {"proc1": {"title": "Do the thing"}},
        "misc": [{"path": "rig.jpg", "created_by": {"email": "me@x.edu"}}],
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    out = subprocess.check_output(
        ["calkit", "list", "notebooks", "--json"], text=True
    )
    assert json.loads(out) == ck_info["notebooks"]
    out = subprocess.check_output(
        ["calkit", "list", "publications", "--json"], text=True
    )
    assert json.loads(out) == ck_info["publications"]
    out = subprocess.check_output(
        ["calkit", "list", "references", "--json"], text=True
    )
    assert json.loads(out) == ck_info["references"]
    out = subprocess.check_output(
        ["calkit", "list", "misc", "--json"], text=True
    )
    assert json.loads(out) == ck_info["misc"]
    out = subprocess.check_output(
        ["calkit", "list", "procedures", "--json"], text=True
    )
    assert json.loads(out) == ["proc1"]
    # Installers come from a static registry, not the project
    out = subprocess.check_output(
        ["calkit", "list", "installers", "--json"], text=True
    )
    installers = json.loads(out)
    by_name = {i["name"]: i for i in installers}
    assert "uv" in by_name
    assert "unix" in by_name["uv"]["scripts"]
    assert "rustup" in by_name["cargo"]["aliases"]
