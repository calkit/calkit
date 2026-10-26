"""Tests for ``calkit.cli.fix``."""

import json
import os
import shutil
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

    def git(*args: str, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, **kwargs
        )

    def fix(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["calkit", "fix", "merge-conflicts", *args],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )

    def stage(name: str, command: str, output: str) -> dict:
        return {
            "kind": "shell-command",
            "command": command,
            "environment": "_system",
            "inputs": [f"{name}.in"],
            "outputs": [{"path": output, "storage": "git"}],
        }

    subprocess.check_call(["calkit", "init"])
    stages = {n: stage(n, f"cat {n}.in > {n}.txt", f"{n}.txt") for n in "abc"}
    # A directory of outputs, named for what made them
    stages["d"] = stage(
        "d",
        "rm -rf outdir && mkdir outdir && cp d.in outdir/$(cat d.in)",
        "outdir",
    )
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"pipeline": {"stages": stages}}, f)
    for n in "abcd":
        write(f"{n}.in", f"{n}-base")
    commit("Base")
    # Running a pipeline sets this clone up to merge its records per stage,
    # in subprojects too
    attrs = git(
        "check-attr", "merge", "dvc.lock", "sub/.calkit/stage-runs.json"
    )
    assert attrs.stdout.count("merge: calkit") == 2, attrs.stdout
    assert "calkit merge-driver" in git("config", "merge.calkit.driver").stdout
    subprocess.check_call(["git", "checkout", "-qb", "other"])
    for n in "acd":
        write(f"{n}.in", f"{n}-theirs")
    commit("Theirs")
    subprocess.check_call(["git", "checkout", "-q", "-"])
    for n in "abd":
        write(f"{n}.in", f"{n}-ours")
    commit("Ours")
    # Without Calkit on PATH, e.g., in an editor started elsewhere, Git merges
    # them line by line rather than leaving ours unmarked
    git_dir = os.path.dirname(shutil.which("git") or "/usr/bin/git")
    path = os.pathsep.join([git_dir, "/bin", "/usr/bin"])
    if shutil.which("calkit", path=path) is None:
        env = os.environ | {"PATH": path}
        assert git("merge", "other", env=env).returncode != 0
        with open("dvc.lock") as f:
            assert "<<<<<<< ours" in f.read()
        subprocess.check_call(["git", "merge", "--abort"])
    # An edit to an output since it was made survives the merge
    write("b.txt", "b edited")
    # Only the stages both sides ran conflict
    assert git("merge", "other").returncode != 0
    with open("dvc.lock") as f:
        assert f.read().count("<<<<<<<") == 2
    # Without a terminal to ask at, its choice has to be given
    res = fix()
    assert res.returncode != 0
    assert "Stage 'a' changed on both sides" in res.stdout + res.stderr
    # Theirs decides its dvc.lock entry, run record, and Git-tracked
    # outputs, and each other stage keeps the side that ran it
    res = fix("--theirs", "a", "--theirs", "d", "--ours", "b")
    assert res.returncode != 0
    assert "Still in conflict:\n  a.in\n  d.in" in res.stdout
    # A choice for a stage that merged on its own is ignored
    assert "Stage 'b' wasn't changed on both sides" in res.stdout + res.stderr
    with open("a.txt") as f:
        assert f.read() == "a-theirs\n"
    assert os.listdir("outdir") == ["d-theirs"]
    lock = calkit.dvc.read_lock_stages()
    with open(calkit.STAGE_RUNS_FPATH) as f:
        runs = json.load(f)
    for n in "abcd":
        assert runs[n]["dvc_lock_hash"] == calkit.dvc.stage_lock_hash(lock[n])
    for n, text in [("b", "b edited"), ("c", "c-theirs")]:
        with open(f"{n}.txt") as f:
            assert f.read() == text + "\n"
    subprocess.check_call(["calkit", "check", "stage-runs"])
    unmerged = git("diff", "--name-only", "--diff-filter=U").stdout.split()
    assert unmerged == ["a.in", "d.in"]
    # Rerunning it drops both, so the next run reruns it
    subprocess.check_call(
        ["git", "checkout", "-m", "--", "dvc.lock", calkit.STAGE_RUNS_FPATH]
    )
    fix("--prefer", "rerun")
    assert "a" not in calkit.dvc.read_lock_stages()
    with open(calkit.STAGE_RUNS_FPATH) as f:
        assert "a" not in json.load(f)
    # Nothing to fix outside a merge
    subprocess.check_call(["git", "merge", "--abort"])
    res = fix()
    assert res.returncode != 0
    assert "No merge, rebase, or cherry-pick" in res.stdout + res.stderr
    # A project in a subdirectory of its repo names stages from there. After
    # each branch has merged the other, keeping its own result, there are
    # two merge bases, and a stage is only merged on its own if both agree.
    os.makedirs("proj")
    os.chdir("proj")
    subprocess.check_call(["calkit", "init"])
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "pipeline": {
                    "stages": {"s": stage("s", "cat s.in > s.txt", "s.txt")}
                }
            },
            f,
        )
    write("s.in", "s-base")
    commit("Project")
    for branch in ["p", "q"]:
        subprocess.check_call(["git", "checkout", "-q", "-b", branch, "main"])
        write("s.in", f"s-{branch}")
        commit(branch)
    tips = {b: git("rev-parse", b).stdout.strip() for b in "pq"}
    for branch, other in [("p", "q"), ("q", "p")]:
        subprocess.check_call(["git", "checkout", "-q", branch])
        git("merge", tips[other])
        subprocess.check_call(["git", "checkout", "--ours", "--", "."])
        subprocess.check_call(["git", "add", "-A"])
        subprocess.check_call(["git", "commit", "-qm", f"Merge into {branch}"])
    subprocess.check_call(["git", "checkout", "-q", "p"])
    assert git("merge", "q").returncode != 0
    res = fix()
    assert "Stage 's' changed on both sides" in res.stdout + res.stderr
    res = fix("--theirs", "s")
    assert "Resolved dvc.lock" not in res.stdout
    assert "Resolved proj/dvc.lock" in res.stdout
    with open("s.txt") as f:
        assert f.read() == "s-q\n"


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
