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


def test_list_templates():
    subprocess.check_call("calkit list templates", shell=True)
    out = subprocess.check_output(
        ["calkit", "list", "templates", "--json"], text=True
    )
    assert "latex/article" in json.loads(out)


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
            ],
        }
    )
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    out = subprocess.check_output(
        ["calkit", "list", "questions", "--json"], text=True
    )
    questions = json.loads(out)
    assert questions[0] == "Does it work?"
    assert questions[1]["question"] == "What is the effect?"
    assert questions[1]["hypothesis"] == "It improves performance."
    assert questions[1]["evidence"][2]["kind"] == "publication"
    assert questions[1]["evidence"][2]["path"] == "paper/paper.pdf"
    out = subprocess.check_output(["calkit", "list", "questions"], text=True)
    assert "1. Does it work?" in out
    assert "2. question: What is the effect?" in out
    assert "hypothesis: It improves performance." in out
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
