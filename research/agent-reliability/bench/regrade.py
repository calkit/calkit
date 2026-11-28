"""Grade every archived run of a batch with the current graders.

Each run in runs/<batch>/ is unpacked into a scratch folder outside the repo,
given a fresh venv (every arm but calkit, which rebuilds its own) and the
Calkit its trial used, snapshotted from its commit, and graded into
grades/<batch>/<run>.json. The archive isn't written to, so a grader fix
regrades a batch without rerunning its agents.

Usage: python bench/regrade.py <batch> [--jobs N]
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

ROOT = arms.ROOT


def get_calkit_rev(run: Path) -> str | None:
    """The Calkit commit a run's trial used, if its arm is calkit."""
    meta = json.loads((run / "meta.json").read_text())
    if meta["arm"] != "calkit":
        return None
    if meta.get("calkit_rev"):
        return str(meta["calkit_rev"])
    return str(json.loads((run / "import.json").read_text())["calkit_rev"])


def regrade(run: Path, out: Path, scratch: Path, calkit: dict) -> dict:
    work = scratch / "runs" / run.name
    try:
        work.mkdir(parents=True)
        for f in run.iterdir():
            if f.name != "project.tgz":
                shutil.copy2(f, work / f.name)
        archive.unpack(run / "project.tgz", work / "project")
        meta = json.loads((work / "meta.json").read_text())
        if meta["arm"] == "calkit":
            meta["calkit_command"] = calkit[str(get_calkit_rev(run))]
            (work / "meta.json").write_text(json.dumps(meta, indent=2))
        else:
            new_run.create_venv(work / "venv")
        result = grade.grade(
            work, out=out / f"{run.name}.json", work_root=scratch / "grading"
        )
        return {"run": run.name, **result["summary"]}
    except Exception as e:
        return {"run": run.name, "error": str(e)[-500:]}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch")
    parser.add_argument("--jobs", type=int, default=6)
    args = parser.parse_args()
    runs_dir = ROOT / "runs" / args.batch
    out = ROOT / "grades" / args.batch
    out.mkdir(parents=True, exist_ok=True)
    runs = sorted(p for p in runs_dir.iterdir() if (p / "meta.json").exists())
    scratch = Path(
        tempfile.mkdtemp(
            prefix="grade-", dir=os.environ.get("AGENT_RELIABILITY_SCRATCH")
        )
    )
    try:
        revs = {rev for r in runs if (rev := get_calkit_rev(r))}
        calkit = {
            rev: arms.snapshot_calkit(rev, scratch / f"calkit-{rev[:9]}")
            for rev in sorted(revs)
        }
        with ProcessPoolExecutor(args.jobs) as pool:
            rows = list(
                pool.map(
                    regrade,
                    runs,
                    [out] * len(runs),
                    [scratch] * len(runs),
                    [calkit] * len(runs),
                )
            )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print(json.dumps(rows, indent=1))
    errors = [r for r in rows if "error" in r]
    if errors:
        raise SystemExit(f"{len(errors)} runs failed to grade")


if __name__ == "__main__":
    main()
