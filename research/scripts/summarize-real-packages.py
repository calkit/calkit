"""Summarize the agent audits of published replication packages.

Each package in real-packages/audits.json lists its runs, each saying
whether it found each of the package's known problems in a ``found_*``
field. Writes results/real-packages.json, with how many runs found each,
for answers to cite, and results/real-packages.md, a table of every run.
"""

import json
from pathlib import Path

with open("real-packages/audits.json") as f:
    audits = json.load(f)
summary: dict = {"date": audits["date"], "packages": {}}
rows = [
    "| Package | Run | Found | Other findings |",
    "| --- | --- | --- | --- |",
]
for package, info in audits["packages"].items():
    runs = info["runs"]
    problems = [key for key in runs[0] if key.startswith("found_")]
    summary["packages"][package] = {
        "source": info["source"],
        "n_runs": len(runs),
        "found": {
            problem.removeprefix("found_"): sum(run[problem] for run in runs)
            for problem in problems
        },
    }
    for i, run in enumerate(runs, start=1):
        found_text = "; ".join(
            f"{problem.removeprefix('found_')} "
            f"{'yes' if run[problem] else 'no'}"
            for problem in problems
        )
        rows.append(f"| {package} | {i} | {found_text} | {run['other']} |")
Path("results").mkdir(exist_ok=True)
with open("results/real-packages.json", "w") as f:
    json.dump(summary, f, indent=2)
    f.write("\n")
with open("results/real-packages.md", "w") as f:
    f.write("\n".join(rows) + "\n")
