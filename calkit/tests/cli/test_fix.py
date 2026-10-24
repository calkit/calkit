"""Tests for ``calkit.cli.fix``."""

import json
import subprocess

import calkit
import calkit.dvc


def test_fix_merge_conflicts(tmp_dir):
    def write(path: str, text: str) -> None:
        with open(path, "w") as f:
            f.write(text + "\n")

    def commit(message: str) -> None:
        subprocess.check_call(["calkit", "run"])
        subprocess.check_call(["git", "add", "-A"])
        subprocess.check_call(["git", "commit", "-qm", message])

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], capture_output=True, text=True)

    subprocess.check_call(["calkit", "init"])
    stages = {
        n: {
            "kind": "shell-command",
            "command": f"cat {n}.in > {n}.txt",
            "environment": "_system",
            "inputs": [f"{n}.in"],
            "outputs": [{"path": f"{n}.txt", "storage": "git"}],
        }
        for n in "abc"
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"pipeline": {"stages": stages}}, f)
    for n in "abc":
        write(f"{n}.in", f"{n} base")
    commit("Base")
    # Running a pipeline sets Git up to merge its records per stage
    with open(".gitattributes") as f:
        assert "/dvc.lock merge=calkit" in f.read()
    assert git("config", "merge.calkit.driver").stdout.startswith("calkit")
    subprocess.check_call(["git", "checkout", "-qb", "other"])
    write("a.in", "a theirs")
    write("c.in", "c theirs")
    commit("Theirs")
    subprocess.check_call(["git", "checkout", "-q", "-"])
    write("a.in", "a ours")
    write("b.in", "b ours")
    commit("Ours")
    # Only the stage both sides ran conflicts
    assert git("merge", "other").returncode != 0
    with open("dvc.lock") as f:
        assert f.read().count("<<<<<<<") == 1
    # Without a terminal to ask at, its choice has to be given
    fix = ["calkit", "fix", "merge-conflicts"]
    res = subprocess.run(fix, capture_output=True, text=True, stdin=-3)
    assert res.returncode != 0
    assert "Stage 'a' changed on both sides" in res.stdout + res.stderr
    # Theirs decides its dvc.lock entry, run record, and Git-tracked output,
    # and each other stage keeps the side that ran it
    res = subprocess.run(
        fix + ["--theirs", "a", "--ours", "b"], capture_output=True, text=True
    )
    assert res.returncode != 0
    assert "Still in conflict:\n  a.in" in res.stdout
    # A choice for a stage that merged on its own is ignored
    assert "Stage 'b' wasn't changed on both sides" in res.stdout + res.stderr
    with open("a.txt") as f:
        assert f.read() == "a theirs\n"
    lock = calkit.dvc.read_lock_stages()
    with open(calkit.STAGE_RUNS_FPATH) as f:
        runs = json.load(f)
    for n in "abc":
        assert runs[n]["dvc_lock_hash"] == calkit.dvc.stage_lock_hash(lock[n])
    for n, text in [("b", "b ours"), ("c", "c theirs")]:
        with open(f"{n}.txt") as f:
            assert f.read() == text + "\n"
    subprocess.check_call(["calkit", "check", "stage-runs"])
    unmerged = git("diff", "--name-only", "--diff-filter=U").stdout.split()
    assert unmerged == ["a.in"]
    # Rerunning it drops both, so the next run reruns it
    subprocess.check_call(["git", "checkout", "-m", "--", "dvc.lock", "a.txt"])
    subprocess.check_call(
        ["git", "checkout", "-m", "--", calkit.STAGE_RUNS_FPATH]
    )
    subprocess.run(fix + ["--prefer", "rerun"], capture_output=True)
    assert "a" not in calkit.dvc.read_lock_stages()
    with open(calkit.STAGE_RUNS_FPATH) as f:
        assert "a" not in json.load(f)
    # Nothing to fix outside a merge
    subprocess.check_call(["git", "merge", "--abort"])
    res = subprocess.run(fix, capture_output=True, text=True)
    assert res.returncode != 0
    assert "No merge, rebase, or cherry-pick" in res.stdout + res.stderr


def test_fix_storage(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    with open("data.csv", "w") as f:
        f.write("a,b\n")
    subprocess.check_call(["calkit", "add", "--to", "dvc", "data.csv"])
    # Now in both Git and DVC
    subprocess.check_call(["git", "add", "-f", "data.csv"])
    assert subprocess.call(["calkit", "check", "storage"]) != 0
    subprocess.check_call(["calkit", "fix", "storage"])
    subprocess.check_call(["calkit", "check", "storage"])
