"""Check the graders: unchanged templates should fail, solutions pass.

For every arm and task, grades a fresh, untouched copy of the template and
a fresh copy with the reference solution applied, then grades flawed
solutions (see solutions.apply_flaw), each of which one grade should catch.
Runs in a scratch folder outside the repo, with the templates unpacked
from the build's archive and Calkit snapshotted at the given commit.
Writes verification/summary.json and each case's grade to
verification/grades/, and prints a table.

Usage: python bench/verify.py --templates FILE --calkit-rev REV [--jobs N]
"""

import argparse
import json
import os
import shutil
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import archive
import arms
import grade
import new_run
import solutions

ROOT = arms.ROOT
OUT = ROOT / "verification"
# (arm, task, flaw) for the negative controls
CONTROLS = [
    ("none", "filter", "stale-one"),
    ("messy", "filter", "stale-one"),
    ("make", "filter", "no-rerun"),
    ("calkit", "filter", "no-rerun"),
    ("make", "fix-merge", "raw-edit"),
    ("calkit", "fix-merge", "raw-edit"),
    ("calkit", "new-question", "typed-answer"),
    ("make", "fix-merge", "extra-fix"),
    ("messy", "filter", "wrong-notebook"),
    ("messy-git", "filter", "wrong-notebook"),
    ("messy", "new-question", "stale-csv"),
    ("make", "provenance", "current-figure-code"),
    ("messy-git", "provenance", "copied-figure"),
    ("calkit", "distant-consumer", "missed-distant"),
    ("make", "distant-consumer", "missed-distant"),
    ("messy-git", "undo", "bundled-revert"),
    ("make", "stale-clone", "incremental-only"),
    ("messy", "regression", "wrong-draft"),
]
KEYS = [
    "correct",
    "n_stale",
    "n_unrequested_change",
    "distant",
    "consistent",
    "no_damage",
    "traceable",
    "fraction_generated",
]


def check(arm: str, task: str, variant: str, scratch: Path) -> dict:
    name = f"verify__{arm}__{task}__{variant}"
    run = new_run.create_run(arm, task, name, scratch / "runs")
    error = None
    try:
        if variant == "solution":
            solutions.solve(run)
        elif variant.startswith("flaw-"):
            solutions.apply_flaw(run, variant.removeprefix("flaw-"))
    except Exception as e:
        error = str(e)[-2000:]
    result = grade.grade(
        run, out=OUT / "grades" / f"{name}.json", work_root=scratch / "grading"
    )
    shutil.rmtree(run)
    return {
        "arm": arm,
        "task": task,
        "variant": variant,
        "solution_error": error,
        **{k: result["summary"].get(k) for k in KEYS},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--calkit-rev", required=True)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    cases = [
        (arm, task, variant)
        for arm in arms.ARMS
        for task in new_run.TASKS
        for variant in ["template", "solution"]
        if new_run.applies(arm, task)
    ] + [(a, t, f"flaw-{f}") for a, t, f in CONTROLS]
    scratch = Path(
        tempfile.mkdtemp(
            prefix="verify-", dir=os.environ.get("AGENT_RELIABILITY_SCRATCH")
        )
    )
    (OUT / "grades").mkdir(parents=True, exist_ok=True)
    try:
        archive.unpack(args.templates.resolve(), scratch / "templates")
        os.environ["BENCH_TEMPLATES"] = str(scratch / "templates")
        os.environ["BENCH_CALKIT"] = arms.snapshot_calkit(
            args.calkit_rev, scratch / "calkit"
        )
        with ProcessPoolExecutor(args.jobs) as pool:
            rows = list(pool.map(check, *zip(*cases), [scratch] * len(cases)))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    rows.sort(key=lambda r: (r["task"], r["arm"], r["variant"]))
    (OUT / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")
    header = f"{'arm':9s} {'task':16s} {'variant':25s} " + " ".join(
        f"{k[:10]:>10s}" for k in KEYS
    )
    print(header)
    for r in rows:
        cells = " ".join(f"{r.get(k)!s:>10s}" for k in KEYS)
        print(f"{r['arm']:9s} {r['task']:16s} {r['variant']:25s} {cells}")
        if r["solution_error"]:
            print("  solution error:", r["solution_error"][:500])


if __name__ == "__main__":
    main()
