# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "numpy>=2.5.5",
#     "simpy>=4.1.2",
# ]
# ///
"""Rank research workflow problems by what solving each is worth in the model.

Uses the ROI model in docs/roi/research_flow.py. Each lever is one problem
solved, e.g., the PI reviewing in Word costing translation time, or reviews
waiting for a weekly meeting. Its worth is measured two ways, since the
model's levers interact: added alone to a baseline, and dropped from a
project where every lever is pulled. Levers that only make sense with a
pipeline (questions, review, collaboration) use automated tooling with the
PI still reviewing in Word as their baseline; the rest use today's status
quo.

Usage: rank-workflow-levers.py <dir with research_flow.py> <output.json>
Writes a Markdown table beside the JSON, with the same name.
"""

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, sys.argv[1])

from research_flow import (  # noqa: E402
    BY_HAND,
    CALKIT,
    COLLABORATION,
    FOCUSED_REVIEW,
    PI_ASSIST,
    QUESTIONS,
    ROUND_TRIP,
    TRANSPARENCY,
    VERIFICATION,
    params_for,
    simulate,
    summarize,
)

REPS = 300
METRICS = (
    "days_mean",
    "days_to_finding_mean",
    "correct_per_year_mean",
    "flawed_per_finding_mean",
    "pi_hours_mean",
)


def main() -> None:
    out_path = Path(sys.argv[2])
    # A scenario is (policy, tooling, agents, parameter overrides)
    Scenario = tuple[str, str, bool, dict[str, Any]]
    status_quo: Scenario = ("stage-gate", "manual", True, {})
    tooled: Scenario = ("lean", "automated", True, CALKIT | BY_HAND)
    # Problems solved on top of tooling, each as parameter overrides
    tooling_levers: dict[str, dict[str, Any]] = {
        "PI reviews Word, changes merged back": ROUND_TRIP,
        # The other way to stop translating by hand, so the two are never
        # pulled together
        "PI reviews in browser": COLLABORATION
        | {
            "translate_fixed": 0.0,
            "translate_item": 0.0,
            "translate_error": 0.0,
        },
        "reviews between meetings": {"review_interval": 2.0},
        "one answer at a time with evidence": FOCUSED_REVIEW,
        "answers rechecked against evidence": VERIFICATION,
        "findings start from written questions": QUESTIONS,
        "agent-assisted PI review": PI_ASSIST,
        "project shared with submission": TRANSPARENCY,
    }

    def run(s: Scenario, seed: int) -> dict[str, float]:
        policy, tooling, agents, over = s
        p = params_for(tooling, agents=agents, **over)
        summary = summarize(simulate(policy, p, REPS, seed))
        return {m: summary[m] for m in METRICS}

    def gain(base: dict, new: dict) -> dict[str, float]:
        return {
            "days_saved": base["days_mean"] - new["days_mean"],
            "correct_per_year_ratio": (
                new["correct_per_year_mean"] / base["correct_per_year_mean"]
            ),
            "flawed_per_finding_change": (
                new["flawed_per_finding_mean"]
                - base["flawed_per_finding_mean"]
            ),
            "pi_hours_saved": base["pi_hours_mean"] - new["pi_hours_mean"],
        }

    # Working style and tooling, each alone from the status quo
    base_sq = run(status_quo, 1)
    workflow_levers: dict[str, Scenario] = {
        "small steps": ("lean", "manual", True, {}),
        "pipeline keeps project current": (
            "stage-gate",
            "automated",
            True,
            CALKIT | BY_HAND,
        ),
    }
    results: dict[str, Any] = {
        "reps": REPS,
        "baselines": {"status quo": base_sq},
        "levers": [],
    }
    for j, (name, s) in enumerate(workflow_levers.items()):
        r = run(s, 10 + j)
        results["levers"].append(
            {"lever": name, "baseline": "status quo", "alone": r}
            | {"alone_gain": gain(base_sq, r)}
        )
    # Problems on top of tooling: alone from the tooled baseline, and
    # dropped from everything at once
    base_tooled = run(tooled, 2)
    alternative = "PI reviews Word, changes merged back"
    every = dict(CALKIT | BY_HAND)
    for name, over in tooling_levers.items():
        if name != alternative:
            every |= over
    everything: Scenario = ("lean", "automated", True, every)
    base_all = run(everything, 3)
    results["baselines"] |= {"tooled": base_tooled, "everything": base_all}
    for j, (name, over) in enumerate(tooling_levers.items()):
        alone = run(
            ("lean", "automated", True, CALKIT | BY_HAND | over), 20 + j
        )
        row = {
            "lever": name,
            "baseline": "tooled",
            "alone": alone,
            "alone_gain": gain(base_tooled, alone),
        }
        if name != alternative:
            rest = dict(CALKIT | BY_HAND)
            for other, o in tooling_levers.items():
                if other not in (name, alternative):
                    rest |= o
            dropped = run(("lean", "automated", True, rest), 40 + j)
            row |= {
                "dropped": dropped,
                "dropped_loss": gain(dropped, base_all),
            }
        results["levers"].append(row)
    # Short IDs, so answers can read a lever's numbers by path
    ids = {
        "small steps": "small-steps",
        "pipeline keeps project current": "pipeline",
        "PI reviews Word, changes merged back": "word-round-trip",
        "PI reviews in browser": "browser-review",
        "reviews between meetings": "reviews-between-meetings",
        "one answer at a time with evidence": "focused-review",
        "answers rechecked against evidence": "recheck-evidence",
        "findings start from written questions": "questions-first",
        "agent-assisted PI review": "agent-pi-review",
        "project shared with submission": "shared-submission",
    }
    results["by_lever"] = {ids[r["lever"]]: r for r in results["levers"]}
    out_path.write_text(json.dumps(results, indent=2) + "\n")
    # The same, as a table to read
    lines = [
        "| Problem solved | Baseline | Days saved alone | Correct/yr alone "
        "| Flawed/finding alone | PI hours saved alone | Days lost if dropped "
        "| Flawed/finding if dropped |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results["levers"]:
        a, d = r["alone_gain"], r.get("dropped_loss")
        lines.append(
            f"| {r['lever']} | {r['baseline']} | {a['days_saved']:.0f} "
            f"| ×{a['correct_per_year_ratio']:.2f} "
            f"| {a['flawed_per_finding_change']:+.3f} "
            f"| {a['pi_hours_saved']:.1f} "
            + (
                f"| {d['days_saved']:.0f} | {-d['flawed_per_finding_change']:+.3f} |"
                if d
                else "| | |"
            )
        )
    out_path.with_suffix(".md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
