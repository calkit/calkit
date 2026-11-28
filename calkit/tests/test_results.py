"""Tests for ``results``."""

import json
import os
import subprocess

import git
import pytest

import calkit
import calkit.overleaf
import calkit.results

SUMMARY = """{
  "speedup_pct": 5.35,
  "device": {"baseline_ms": 22635.7, "mod_ms": 21221.5, "change_pct": -6.25},
  "pairs": [{"sypd": 1.4603}, {"sypd": 1.5429}],
  "arms": ["baseline", "mod"],
  "reproducible": true,
  "note": null
}
"""


def test_read_result(tmp_dir):
    with open("summary.json", "w") as f:
        f.write(SUMMARY)
    result = calkit.results.read_result("summary.json")
    keys = {item["key"]: item["value"] for item in result["items"]}
    # Nested keys are dotted the way a question's evidence names them, a
    # list of objects is indexed into, and a list of scalars is one value
    assert keys["speedup_pct"] == "5.35"
    assert keys["device.change_pct"] == "-6.25"
    assert keys["pairs.0.sypd"] == "1.4603"
    assert keys["pairs.1.sypd"] == "1.5429"
    assert keys["arms"] == '["baseline", "mod"]'
    assert keys["reproducible"] == "true"
    assert keys["note"] == "null"
    assert result["n_keys"] == len(keys)
    # A key selection shows that subtree, prefixed as it was asked for
    result = calkit.results.read_result("summary.json", keys=["device"])
    assert [item["key"] for item in result["items"]] == [
        "device.baseline_ms",
        "device.mod_ms",
        "device.change_pct",
    ]
    result = calkit.results.read_result(
        "summary.json", keys=["device.mod_ms", "speedup_pct"]
    )
    assert [item["value"] for item in result["items"]] == ["21221.5", "5.35"]
    # A key that isn't there says what the result does have
    with pytest.raises(ValueError, match="speedup_pct"):
        calkit.results.read_result("summary.json", keys=["speedup"])
    # Depth stops flattening and leaves the rest as JSON on one line
    result = calkit.results.read_result("summary.json", depth=1)
    keys = {item["key"]: item["value"] for item in result["items"]}
    assert keys["device"].startswith("{")
    assert "22635.7" in keys["device"]
    # TOML and YAML are read the same way
    with open("stats.toml", "w") as f:
        f.write("[device]\nmod_ms = 21221.5\n")
    assert calkit.results.read_result("stats.toml")["items"] == [
        {"key": "device.mod_ms", "value": "21221.5", "type": "float"}
    ]
    with open("stats.yaml", "w") as f:
        f.write("device:\n  mod_ms: 21221.5\n")
    assert calkit.results.read_result("stats.yaml")["items"][0]["value"] == (
        "21221.5"
    )
    # Contents can be given instead of a path, which is how a result is
    # read at a Git ref
    result = calkit.results.read_result(
        "summary.json", content=SUMMARY.encode(), keys=["speedup_pct"]
    )
    assert result["items"][0]["value"] == "5.35"
    # A tabular file is listed as a result too, since its values are a
    # result, but its keys are columns, so it's read as a table
    with pytest.raises(ValueError, match="calkit show table"):
        calkit.results.read_result("table.csv")


def test_list_results(tmp_dir):
    git.Repo.init()
    os.makedirs("results", exist_ok=True)
    with open("results/summary.json", "w") as f:
        f.write(SUMMARY)
    with open("results/stats.toml", "w") as f:
        f.write("a = 1\n")
    with open("results/kernels.csv", "w") as f:
        f.write("a,b\n1,2\n")
    os.makedirs("results/runs")
    ck_info = {
        "results": [
            {"path": "results/summary.json", "title": "Run summary"},
            {"path": "results/runs"},
        ],
        "pipeline": {
            "stages": {
                "summarize": {
                    "kind": "shell-command",
                    "command": "echo hi",
                    "outputs": ["results/summary.json"],
                },
                "later": {
                    "kind": "shell-command",
                    "command": "echo hi",
                    "outputs": ["results/not-yet.json"],
                },
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    results = {r["path"]: r for r in calkit.results.list_results()}
    assert results["results/summary.json"]["title"] == "Run summary"
    assert results["results/summary.json"]["stages"] == ["summarize"]
    # A TOML result is detected, and one the pipeline hasn't written yet
    # is listed so its status can say so
    assert results["results/stats.toml"]["detected"] is True
    assert results["results/not-yet.json"]["exists"] is False
    # A tabular result is listed here as well as under tables
    assert results["results/kernels.csv"]["detected"] is True
    # A directory result exists too
    assert results["results/runs"]["exists"] is True


def test_get_changes(tmp_dir):
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], text=True)

    def run() -> None:
        subprocess.check_call(["calkit", "run"], stdout=subprocess.DEVNULL)

    subprocess.check_call(["calkit", "init"])
    with open("make.py", "w") as f:
        f.write(
            "import json, os, sys\n"
            "scale = float(open('scale.txt').read())\n"
            "os.makedirs('results', exist_ok=True)\n"
            "os.makedirs('figures', exist_ok=True)\n"
            "json.dump({'slope': 2 * scale, 'n': 10, 'label': 'fit'},"
            " open('results/fit.json', 'w'))\n"
            "json.dump({'total': 100 * scale}, open('results/big.json', 'w'))\n"
            "open('figures/fit.png', 'w').write(str(scale))\n"
            "open('figures/same.png', 'w').write('same')\n"
        )
    with open("scale.txt", "w") as f:
        f.write("1")
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = {
        "stages": {
            "make": {
                "kind": "shell-command",
                "environment": "_system",
                "command": "python make.py",
                "inputs": ["make.py", "scale.txt"],
                "outputs": [
                    {"path": "results/fit.json", "storage": "git"},
                    {"path": "results/big.json", "storage": "dvc"},
                    {"path": "figures/fit.png", "storage": "git"},
                    {"path": "figures/same.png", "storage": "git"},
                ],
            }
        }
    }
    ck_info["questions"] = [
        {
            "question": "What's the slope?",
            "answer": "{slope}",
            "evidence": [
                {"kind": "value", "path": "results/fit.json", "key": "slope"}
            ],
        },
        {
            "question": "How many?",
            "answer": "{n}",
            "evidence": [
                {"kind": "value", "path": "results/fit.json", "key": "n"}
            ],
        },
        {
            "question": "What does it look like?",
            "evidence": [{"kind": "figure", "path": "figures/fit.png"}],
        },
    ]
    calkit.save_calkit_info(ck_info)
    run()
    git("add", "-A")
    git("commit", "-qm", "Run")
    default_branch = git("branch", "--show-current").strip()
    # Nothing changed yet
    changes = calkit.results.get_changes(check_pipeline=False)
    assert not changes["stages"] and not changes["outputs"]
    assert changes["base_label"] == f"merge base with {default_branch}"
    assert "No results changed." in calkit.results.format_changes(changes)
    # A change on a branch, in the working tree, is compared to where the
    # branch started
    git("checkout", "-qb", "change")
    with open("scale.txt", "w") as f:
        f.write("1.5")
    run()
    changes = calkit.results.get_changes(check_pipeline=False)
    assert changes["to"] is None
    assert [(s["name"], s["change"]) for s in changes["stages"]] == [
        ("make", "reran")
    ]
    assert changes["stages"][0]["n_changed_outputs"] == 3
    outputs = {o["path"]: o for o in changes["outputs"]}
    assert set(outputs) == {
        "results/fit.json",
        "results/big.json",
        "figures/fit.png",
    }
    fit = outputs["results/fit.json"]
    assert (fit["kind"], fit["storage"], fit["stage"]) == (
        "value",
        "git",
        "make",
    )
    assert fit["values"] == [
        {
            "key": "slope",
            "old": 2.0,
            "new": 3.0,
            "change": "modified",
            "relative_change": 0.5,
        }
    ]
    # A DVC-stored result is read from the local cache
    big = outputs["results/big.json"]
    assert big["storage"] == "dvc"
    assert big["values"][0]["relative_change"] == 0.5
    assert outputs["figures/fit.png"]["kind"] == "figure"
    assert outputs["figures/fit.png"]["storage"] == "git"
    # Only questions citing what changed are listed, with the value
    questions = {q["number"]: q for q in changes["questions"]}
    assert set(questions) == {1, 3}
    assert questions[1]["evidence"][0]["old"] == 2.0
    assert questions[1]["evidence"][0]["new"] == 3.0
    assert questions[3]["evidence"] == [
        {"path": "figures/fit.png", "change": "modified"}
    ]
    text = calkit.results.format_changes(changes)
    assert "- `make`: reran, 3 outputs changed" in text
    assert "| `slope` | 2 | 3 | +50% |" in text
    assert "- `figures/fit.png` (Git, `make`)" in text
    assert "- Q1: What's the slope?" in text
    assert "  - `slope`: 2 → 3 (+50%)" in text
    assert "How many?" not in text
    assert "same.png" not in text
    # Long lists are cut, counting the rest
    text = calkit.results.format_changes(changes, max_items=1)
    assert "- 1 more" in text
    # Committed, it's compared at revisions, and once the cache doesn't
    # have the old version of a DVC-stored output, that's said rather than
    # pulled
    git("add", "-A")
    git("commit", "-qm", "Change scale")
    calkit.overleaf.rmtree(os.path.join(".dvc", "cache"))
    changes = calkit.results.get_changes(
        base=default_branch, to="HEAD", check_pipeline=False
    )
    assert changes["base_label"] is None
    outputs = {o["path"]: o for o in changes["outputs"]}
    assert outputs["results/big.json"]["note"] == "not in local cache"
    assert outputs["results/fit.json"]["values"][0]["new"] == 3.0
    assert "big.json` (DVC, `make`): not in local cache" in (
        calkit.results.format_changes(changes)
    )
    # A declared figure edited by hand is a change too, even with a name
    # Git would quote, and an edit to a stage's inputs makes it stale
    with open("notes-café.png", "w") as f:
        f.write("drawn")
    ck_info = calkit.load_calkit_info()
    ck_info["figures"] = [{"path": "notes-café.png", "title": "Notes"}]
    calkit.save_calkit_info(ck_info)
    with open("scale.txt", "w") as f:
        f.write("2")
    changes = calkit.results.get_changes(base="HEAD")
    assert changes["stale_check_error"] is None
    assert changes["stages"] == [
        {
            "name": "make",
            "change": "stale",
            "stale": True,
            "n_changed_outputs": 0,
            "run": changes["stages"][0]["run"],
        }
    ]
    outputs = {o["path"]: o for o in changes["outputs"]}
    assert outputs["notes-café.png"]["change"] == "added"
    assert outputs["notes-café.png"]["storage"] == "git"
    assert outputs["notes-café.png"]["stage"] is None
    # A stale check that fails says so, rather than that nothing changed
    ck_info["pipeline"]["stages"]["make"]["kind"] = "nope"
    calkit.save_calkit_info(ck_info)
    changes = calkit.results.get_changes(base="HEAD")
    assert "nope" in changes["stale_check_error"]
    text = calkit.results.format_changes(changes)
    assert "Stale stages unknown: " in text
    assert "No results changed." not in text
    git("checkout", "-q", "--", ".")
    git("clean", "-fdq")
    # Directory outputs are compared file by file, from DVC's manifests or
    # Git, and a PDF is only a figure in a figures directory
    with open("dirs.py", "w") as f:
        f.write(
            "import json, os\n"
            "scale = float(open('scale.txt').read())\n"
            "for d in ['dvcdir', 'gitdir']:\n"
            "    os.makedirs(d, exist_ok=True)\n"
            "    json.dump({'x': scale}, open(f'{d}/a.json', 'w'))\n"
            "    open(f'{d}/b.txt', 'w').write('same')\n"
            "open('paper.pdf', 'w').write(str(scale))\n"
            "open('figures/plot.pdf', 'w').write(str(scale))\n"
        )
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"]["stages"]["dirs"] = {
        "kind": "shell-command",
        "environment": "_system",
        "command": "python dirs.py",
        "inputs": ["dirs.py", "scale.txt"],
        "outputs": [
            {"path": "dvcdir", "storage": "dvc"},
            {"path": "gitdir", "storage": "git"},
            {"path": "paper.pdf", "storage": "git"},
            {"path": "figures/plot.pdf", "storage": "git"},
        ],
    }
    ck_info["questions"].append(
        {
            "question": "What's x?",
            "evidence": [
                {"kind": "value", "path": "dvcdir/a.json", "key": "x"}
            ],
        }
    )
    calkit.save_calkit_info(ck_info)
    run()
    git("add", "-A")
    git("commit", "-qm", "Add dirs")
    # A stage is added in one direction and removed in the other
    changes = calkit.results.get_changes(
        base="HEAD~1", to="HEAD", check_pipeline=False
    )
    assert ("dirs", "added") in [
        (s["name"], s["change"]) for s in changes["stages"]
    ]
    changes = calkit.results.get_changes(
        base="HEAD", to="HEAD~1", check_pipeline=False
    )
    assert ("dirs", "removed") in [
        (s["name"], s["change"]) for s in changes["stages"]
    ]
    with open("scale.txt", "w") as f:
        f.write("3")
    run()
    changes = calkit.results.get_changes(check_pipeline=False, base="HEAD")
    outputs = {o["path"]: o for o in changes["outputs"]}
    assert outputs["dvcdir/a.json"]["storage"] == "dvc"
    assert outputs["dvcdir/a.json"]["values"][0]["new"] == 3.0
    assert outputs["gitdir/a.json"]["storage"] == "git"
    assert outputs["gitdir/a.json"]["values"][0]["old"] == 1.5
    assert "dvcdir/b.txt" not in outputs and "gitdir/b.txt" not in outputs
    assert outputs["paper.pdf"]["kind"] == "other"
    assert outputs["figures/plot.pdf"]["kind"] == "figure"
    questions = {q["question"]: q for q in changes["questions"]}
    assert questions["What's x?"]["evidence"][0]["new"] == 3.0
    # Without the manifests, only the DVC directory is known to have
    # changed, and so is all a question citing a file in it can say
    git("add", "-A")
    git("commit", "-qm", "Change scale again")
    calkit.overleaf.rmtree(os.path.join(".dvc", "cache"))
    changes = calkit.results.get_changes(
        base="HEAD~1", to="HEAD", check_pipeline=False
    )
    outputs = {o["path"]: o for o in changes["outputs"]}
    assert outputs["dvcdir"]["directory"] is True
    assert "gitdir/a.json" in outputs
    questions = {q["question"]: q for q in changes["questions"]}
    assert questions["What's x?"]["evidence"] == [
        {"path": "dvcdir/a.json", "change": "directory changed"}
    ]
    # Nothing outside the project or the cache is read, whatever dvc.lock
    # says
    with open(os.path.join("..", "outside.json"), "w") as f:
        f.write('{"secret": 1}')
    with open("dvc.lock") as f:
        lock = calkit.ryaml.load(f)
    lock["stages"]["make"]["outs"] += [
        {"path": "../outside.json", "md5": "0" * 32},
        {"path": "results/fit.json", "md5": "../../../outside.json"},
    ]
    with open("dvc.lock", "w") as f:
        calkit.ryaml.dump(lock, f)
    changes = calkit.results.get_changes(base="HEAD", check_pipeline=False)
    assert not any(o["path"].startswith("..") for o in changes["outputs"])
    assert "secret" not in json.dumps(changes)
    # A revision that isn't there says so
    with pytest.raises(ValueError, match="nope"):
        calkit.results.get_changes(base="nope")
