"""Tests for ``calkit.merge``."""

import json
import subprocess

import yaml

import calkit.dvc
import calkit.merge
from calkit.merge import BOTH, OURS, RERUN, THEIRS


def _entry(md5: str, size: bool = True) -> dict:
    out: dict = {"path": "out.txt", "hash": "md5", "md5": md5}
    if size:
        out["size"] = 3
    return {"cmd": "make", "deps": [], "outs": [out]}


def _run(entry: dict, end_time: str) -> dict:
    return {
        "end_time": end_time,
        "dvc_lock_hash": calkit.dvc.stage_lock_hash(entry),
    }


def test_merge_stages():
    base = {n: _entry("0") for n in "abcd"}
    ours = base | {"a": _entry("1"), "b": _entry("1"), "f": _entry("1")}
    theirs = base | {"a": _entry("2"), "c": _entry("2"), "e": _entry("2")}
    del theirs["d"]
    # DVC writing an entry differently doesn't count as a change
    theirs["b"] = _entry("0", size=False)
    merged, sides, conflicts = calkit.merge.merge_stages(
        base, ours, theirs, choices={}
    )
    assert conflicts == ["a"]
    assert "a" not in merged
    assert sides == {
        "b": OURS,
        "c": THEIRS,
        "d": THEIRS,
        "e": THEIRS,
        "f": OURS,
    }
    assert merged["b"] == ours["b"]
    assert merged["c"] == theirs["c"]
    assert "d" not in merged
    # Ours first, then what only they added
    assert list(merged) == ["b", "c", "f", "e"]
    # A choice takes that side whole, or drops the stage to rerun it
    for choice, expected in [(OURS, "1"), (THEIRS, "2"), (RERUN, None)]:
        merged, sides, conflicts = calkit.merge.merge_stages(
            base, ours, theirs, choices={"a": choice}
        )
        assert not conflicts
        assert sides["a"] == choice
        if expected is None:
            assert "a" not in merged
        else:
            assert merged["a"]["outs"][0]["md5"] == expected


def test_merge_runs():
    e0, e1, e2 = _entry("0"), _entry("1"), _entry("2")
    base = {"a": _run(e0, "1"), "b": _run(e0, "1")}
    ours = {"a": _run(e1, "2"), "b": _run(e1, "2"), "c": _run(e1, "2")}
    theirs = {"a": _run(e2, "3"), "b": _run(e1, "3"), "d": _run(e2, "3")}
    # Without dvc.lock, runs making different entries conflict, and two
    # making the same one keep the later
    merged, conflicts = calkit.merge.merge_runs(base, ours, theirs)
    assert conflicts == ["a"]
    assert merged["b"] == theirs["b"]
    assert merged["c"] == ours["c"]
    assert merged["d"] == theirs["d"]
    # With it, each stage keeps the run that made its entry, whichever side
    # was later, and a stage to rerun keeps none
    lock = {"a": e1, "b": e1, "c": e1, "d": e2}
    sides = {"a": OURS, "b": BOTH, "c": OURS, "d": THEIRS}
    merged, conflicts = calkit.merge.merge_runs(
        base, ours, theirs, lock, sides
    )
    assert not conflicts
    assert merged["a"] == ours["a"]
    assert merged["b"] == theirs["b"]
    merged, _ = calkit.merge.merge_runs(
        base, ours, theirs, {"b": e1}, {"a": RERUN, "b": BOTH}
    )
    assert "a" not in merged


def test_run_driver(tmp_path):
    def write(name: str, text: str) -> str:
        path = tmp_path / name
        path.write_text(text)
        return str(path)

    def lock(stages: dict) -> str:
        return str(yaml.safe_dump({"schema": "2.0", "stages": stages}))

    base = {"a": _entry("0"), "b": _entry("0")}
    ours = base | {"a": _entry("1")}
    theirs = base | {"b": _entry("2")}
    paths = [
        write("base", lock(base)),
        write("ours", lock(ours)),
        write("theirs", lock(theirs)),
    ]
    assert (
        calkit.merge.run_driver(paths[0], paths[1], paths[2], "dvc.lock") == 0
    )
    with open(paths[1]) as f:
        merged = yaml.safe_load(f)
    assert merged["schema"] == "2.0"
    assert merged["stages"] == {"a": ours["a"], "b": theirs["b"]}
    # A stage changed on both sides is marked whole, with the rest merged
    theirs["a"] = _entry("2")
    paths[1] = write("ours", lock(ours))
    paths[2] = write("theirs", lock(theirs))
    assert (
        calkit.merge.run_driver(paths[0], paths[1], paths[2], "sub/dvc.lock")
        == 1
    )
    with open(paths[1]) as f:
        text = f.read()
    assert text.count("<<<<<<< ours") == 1
    ours_side = text.split("<<<<<<< ours")[1].split("=======")[0]
    assert "md5: '1'" in ours_side and "md5: '2'" not in ours_side
    assert "md5: '2'" in text.split("=======")[1]
    # Run records too, keeping each one whole
    runs = [
        {"a": _run(_entry("0"), "1")},
        {"a": _run(_entry("1"), "2")},
        {"a": _run(_entry("2"), "3")},
    ]
    paths = [write(n, json.dumps(r)) for n, r in zip(["b", "o", "t"], runs)]
    assert (
        calkit.merge.run_driver(
            paths[0], paths[1], paths[2], ".calkit/stage-runs.json"
        )
        == 1
    )
    with open(paths[1]) as f:
        text = f.read()
    assert text.count("<<<<<<< ours") == 1
    assert '"end_time": "2"' in text and '"end_time": "3"' in text
    runs[2] = runs[0] | {"b": _run(_entry("2"), "3")}
    paths = [write(n, json.dumps(r)) for n, r in zip(["b", "o", "t"], runs)]
    assert (
        calkit.merge.run_driver(
            paths[0], paths[1], paths[2], ".calkit/stage-runs.json"
        )
        == 0
    )
    with open(paths[1]) as f:
        assert json.load(f) == {"a": runs[1]["a"], "b": runs[2]["b"]}
    # Anything it can't read gets Git's line-based merge
    paths = [
        write("b", "x\n-\ny\n"),
        write("o", "X\n-\ny\n"),
        write("t", "x\n-\nY\n"),
    ]
    assert (
        calkit.merge.run_driver(paths[0], paths[1], paths[2], "dvc.lock") == 0
    )
    with open(paths[1]) as f:
        assert f.read() == "X\n-\nY\n"
    paths[2] = write("t", "Z\n-\ny\n")
    assert (
        calkit.merge.run_driver(paths[0], paths[1], paths[2], "notes.txt") == 1
    )
    assert subprocess.call(["grep", "-q", "<<<<<<<", paths[1]]) == 0
