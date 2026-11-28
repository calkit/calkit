"""Summarize the rounds in audit-speed/rounds/round-*/results.json.

An arm in a round's results is one run, or a list of runs once a round
repeats them. A run says whether it found the round's one bug in
``found_bug``, or, in a round with several, which it found in ``found``,
with null for a bug that couldn't occur in that arm.

A run's cost is real time, tool calls, and tokens (``duration_s``,
``tool_calls``, ``tokens``), or, in a round read at human speed, the
simulated minutes its reader charged (``simulated_minutes``) under one of
the round's cost ``settings``, which are copied into the summary. Only the
measures a round's runs have are summarized for it.

Writes results/audit-speed.json, for answers to cite, and
results/audit-speed.md, a table of every run.
"""

import json
import statistics
from pathlib import Path


def get_found(run: dict) -> dict[str, bool | None]:
    """Get which bugs a run found, by bug."""
    found: dict[str, bool | None] = (
        run["found"] if "found" in run else {"bug": run["found_bug"]}
    )
    return found


def count_found(runs: list[dict]) -> dict[str, dict[str, int]]:
    """Count the runs that found each bug, of those where it could occur."""
    found: dict[str, dict[str, int]] = {}
    for run in runs:
        for bug, hit in get_found(run).items():
            counts = found.setdefault(bug, {"found": 0, "possible": 0})
            if hit is not None:
                counts["possible"] += 1
                counts["found"] += hit
    return found


def summarize_costs(runs: list[dict]) -> dict:
    """Summarize whichever cost measures the runs have."""
    summary: dict = {}
    if all("duration_s" in run for run in runs):
        seconds = [run["duration_s"] for run in runs]
        summary["seconds"] = seconds
        summary["mean_seconds"] = statistics.mean(seconds)
    if all("tool_calls" in run for run in runs):
        summary["mean_tool_calls"] = statistics.mean(
            run["tool_calls"] for run in runs
        )
    if all("simulated_minutes" in run for run in runs):
        minutes = [run["simulated_minutes"] for run in runs]
        summary["simulated_minutes"] = minutes
        summary["mean_simulated_minutes"] = statistics.mean(minutes)
    return summary


def format_cell(value: object, spec: str = "") -> str:
    """Format a table cell, with a dash for a measure a run lacks."""
    return "—" if value is None else format(value, spec)


summary: dict = {"rounds": {}}
rows = [
    "| Round | Date | Arm | Tool version | Setting | Found | Seconds "
    "| Simulated min | Tool calls | Tokens |",
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
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
    arms = {}
    for arm, arm_runs in runs_by_arm.items():
        arms[arm] = {
            "found_bug": [run.get("found_bug") for run in arm_runs],
            **summarize_costs(arm_runs),
            "found": count_found(arm_runs),
        }
    round_summary: dict = {
        "date": results["date"],
        "n_arms": len(runs_by_arm),
        "n_runs": len(runs),
        "min_runs_per_arm": min(len(r) for r in runs_by_arm.values()),
        "n_found_bug": sum(
            all(hit is not False for hit in get_found(run).values())
            for run in runs
        ),
        "found": count_found(runs),
    }
    # The time measure the round has, for its range and fastest arm
    for measure in ("seconds", "simulated_minutes"):
        if all(measure in arm for arm in arms.values()):
            values = [v for arm in arms.values() for v in arm[measure]]
            round_summary[measure] = {"min": min(values), "max": max(values)}
            round_summary["fastest_arm"] = min(
                arms, key=lambda arm: arms[arm][f"mean_{measure}"]
            )
            break
    # What each cost setting and way of checking found, across arms
    for field, key in (("setting", "settings"), ("checked_by", "checked_by")):
        groups: dict[str, list[dict]] = {}
        for run in runs:
            if field in run:
                groups.setdefault(run[field], []).append(run)
        if groups:
            round_summary[key] = {
                name: {
                    **(
                        {"costs": results["settings"][name]}
                        if key == "settings"
                        else {}
                    ),
                    "n_runs": len(group),
                    "found": count_found(group),
                    **summarize_costs(group),
                }
                for name, group in groups.items()
            }
    round_summary["arms"] = arms
    round_summary["conclusion"] = results["conclusion"]
    summary["rounds"][n] = round_summary
    for arm, arm_runs in runs_by_arm.items():
        for run in arm_runs:
            found_text = "; ".join(
                f"{bug} {'n/a' if hit is None else 'yes' if hit else 'no'}"
                for bug, hit in get_found(run).items()
            )
            if list(get_found(run)) == ["bug"]:
                found_text = "yes" if run["found_bug"] else "no"
            rows.append(
                f"| {n} | {results['date']} | {arm} "
                f"| {format_cell(run.get('tool_version'))} "
                f"| {format_cell(run.get('setting'))} "
                f"| {found_text} "
                f"| {format_cell(run.get('duration_s'), '.0f')} "
                f"| {format_cell(run.get('simulated_minutes'), '.1f')} "
                f"| {format_cell(run.get('tool_calls'))} "
                f"| {format_cell(run.get('tokens'))} |"
            )
Path("results").mkdir(exist_ok=True)
with open("results/audit-speed.json", "w") as f:
    json.dump(summary, f, indent=2)
    f.write("\n")
with open("results/audit-speed.md", "w") as f:
    f.write("\n".join(rows) + "\n")
