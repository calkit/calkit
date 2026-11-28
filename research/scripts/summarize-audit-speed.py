"""Summarize the rounds in audit-speed/rounds/round-*/results.json.

An arm in a round's results is one run, or a list of runs once a round
repeats them. A run says whether it found the round's one bug in
``found_bug``, or, in a round with several, which it found in ``found``,
with null for a bug that couldn't occur in that arm.

Writes results/audit-speed.json, for answers to cite, and
results/audit-speed.md, a table of every run.
"""

import json
import statistics
from pathlib import Path


def get_found(run: dict) -> dict[str, bool | None]:
    """Get which bugs a run found, by bug."""
    if "found" in run:
        return run["found"]
    return {"bug": run["found_bug"]}


summary: dict = {"rounds": {}}
rows = [
    "| Round | Date | Arm | Tool version | Found | Seconds | Tool calls "
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
    arms = {}
    for arm, arm_runs in runs_by_arm.items():
        # How many runs found each bug, out of the runs where it could occur
        found: dict[str, dict[str, int]] = {}
        for run in arm_runs:
            for bug, hit in get_found(run).items():
                counts = found.setdefault(bug, {"found": 0, "possible": 0})
                if hit is not None:
                    counts["possible"] += 1
                    counts["found"] += hit
        arm_seconds = [run["duration_s"] for run in arm_runs]
        arms[arm] = {
            "found_bug": [run.get("found_bug") for run in arm_runs],
            "seconds": arm_seconds,
            "mean_seconds": statistics.mean(arm_seconds),
            "mean_tool_calls": statistics.mean(
                run["tool_calls"] for run in arm_runs
            ),
            "found": found,
        }
    summary["rounds"][n] = {
        "date": results["date"],
        "n_arms": len(runs_by_arm),
        "n_runs": len(runs),
        "min_runs_per_arm": min(len(r) for r in runs_by_arm.values()),
        "n_found_bug": sum(
            all(hit is not False for hit in get_found(run).values())
            for run in runs
        ),
        "seconds": {"min": min(seconds), "max": max(seconds)},
        "fastest_arm": min(arms, key=lambda arm: arms[arm]["mean_seconds"]),
        "arms": arms,
        "conclusion": results["conclusion"],
    }
    for arm, arm_runs in runs_by_arm.items():
        for run in arm_runs:
            found_text = "; ".join(
                f"{bug} {'n/a' if hit is None else 'yes' if hit else 'no'}"
                for bug, hit in get_found(run).items()
            )
            if list(get_found(run)) == ["bug"]:
                found_text = "yes" if run["found_bug"] else "no"
            rows.append(
                f"| {n} | {results['date']} | {arm} | {run['tool_version']} "
                f"| {found_text} "
                f"| {run['duration_s']:.0f} | {run['tool_calls']} "
                f"| {run['tokens']} |"
            )
Path("results").mkdir(exist_ok=True)
with open("results/audit-speed.json", "w") as f:
    json.dump(summary, f, indent=2)
    f.write("\n")
with open("results/audit-speed.md", "w") as f:
    f.write("\n".join(rows) + "\n")
