"""Summarize the rounds in audit-speed/rounds/round-*/results.json.

An arm in a round's results is one run, or a list of runs once a round
repeats them.

Writes results/audit-speed.json, for answers to cite, and
results/audit-speed.md, a table of every run.
"""

import json
from pathlib import Path

summary: dict = {"rounds": {}}
rows = [
    "| Round | Date | Arm | Tool version | Found bug | Seconds | Tool calls "
    "| Tokens |",
    "| --- | --- | --- | --- | --- | --- | --- | --- |",
]
round_paths = sorted(
    Path("audit-speed/rounds").glob("round-*/results.json"),
    key=lambda path: int(path.parent.name.removeprefix("round-")),
)
for path in round_paths:
    with open(path) as f:
        results = json.load(f)
    n = str(results["round"])
    runs_by_arm = {
        arm: runs if isinstance(runs, list) else [runs]
        for arm, runs in results["arms"].items()
    }
    runs = [run for arm_runs in runs_by_arm.values() for run in arm_runs]
    seconds = [run["duration_s"] for run in runs]
    summary["rounds"][n] = {
        "date": results["date"],
        "n_arms": len(runs_by_arm),
        "n_runs": len(runs),
        "min_runs_per_arm": min(len(r) for r in runs_by_arm.values()),
        "n_found_bug": sum(run["found_bug"] for run in runs),
        "seconds": {"min": min(seconds), "max": max(seconds)},
        "arms": {
            arm: {
                "found_bug": [run["found_bug"] for run in arm_runs],
                "seconds": [run["duration_s"] for run in arm_runs],
            }
            for arm, arm_runs in runs_by_arm.items()
        },
        "conclusion": results["conclusion"],
    }
    for arm, arm_runs in runs_by_arm.items():
        for run in arm_runs:
            rows.append(
                f"| {n} | {results['date']} | {arm} | {run['tool_version']} "
                f"| {'yes' if run['found_bug'] else 'no'} "
                f"| {run['duration_s']:.0f} | {run['tool_calls']} "
                f"| {run['tokens']} |"
            )
Path("results").mkdir(exist_ok=True)
with open("results/audit-speed.json", "w") as f:
    json.dump(summary, f, indent=2)
    f.write("\n")
with open("results/audit-speed.md", "w") as f:
    f.write("\n".join(rows) + "\n")
