"""Tests for ``results``."""

import os

import git
import pytest

import calkit
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
