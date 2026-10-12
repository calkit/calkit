"""Simulate a paper worked in small steps versus stage by stage.

Runs the model in docs/roi/research_flow.py, which the docs' ROI calculator
page shares, for the default workflow: both working styles with manual and
automated tooling, ways of adopting the tooling, where the time goes, and
Calkit's goals added one at a time from today's status quo to see what each
is worth.

Writes the results to results/research-flow.json.
"""

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, "docs/roi")

from research_flow import (  # noqa: E402
    ADOPTION,
    BASE,
    BY_HAND,
    CALKIT,
    COLLABORATION,
    DIY,
    LEARNED,
    PI_ASSIST,
    POLICIES,
    PRODUCTIVE_WAIT,
    QUESTIONS,
    STAGES,
    TOOLING,
    TRANSPARENCY,
    VERIFICATION,
    breakdown,
    params_for,
    simulate,
    summarize,
)

REPS = 400
OUT = Path("results/research-flow.json")


# The four combinations of working style and tooling
scenarios: dict[str, dict] = {}
for t in TOOLING:
    for pol in POLICIES:
        seed = len(scenarios) + 1
        scenarios[f"{pol}/{t}"] = summarize(
            simulate(pol, params_for(t), REPS, seed)
        )


def ratio(key: str, a: str, b: str) -> float:
    return float(scenarios[a][key] / scenarios[b][key])


ratios = {}
for key, name in [
    ("days_mean", "days"),
    ("student_days_mean", "student_days"),
    ("days_to_finding_mean", "days_to_finding"),
    ("days_to_first_finding_mean", "days_to_first_finding"),
]:
    for t in TOOLING:
        ratios[f"{name}_{t}"] = ratio(key, f"stage-gate/{t}", f"lean/{t}")
    ratios[f"{name}_combined"] = ratio(
        key, "stage-gate/manual", "lean/automated"
    )
    # What the tooling alone does, without changing how the work flows
    ratios[f"{name}_tooling"] = ratio(
        key, "stage-gate/manual", "stage-gate/automated"
    )
# Student-days per paper as more of the time spent waiting on reviews goes
# to other useful work
fractions = [0.0, 0.25, 0.5, 0.75, 1.0]
wait_sweep = {}
for name, slow, fast in [
    ("manual", "stage-gate/manual", "lean/manual"),
    ("automated", "stage-gate/automated", "lean/automated"),
    ("combined", "stage-gate/manual", "lean/automated"),
]:
    sg, ln = scenarios[slow], scenarios[fast]
    wait_sweep[name] = [
        (sg["days_mean"] - f * sg["idle_mean"])
        / (ln["days_mean"] - f * ln["idle_mean"])
        for f in fractions
    ]
# How often lean should meet, with and without the tooling
intervals = [1, 2, 5, 10, 20, 40]
interval_sweep = {
    t: [
        summarize(
            simulate("lean", params_for(t, review_interval=dt), 200, 100 + j)
        )["days_mean"]
        for j, dt in enumerate(intervals)
    ]
    for t in TOOLING
}
# Where lean with automated tooling beats stage-gate with manual tooling
# by most: scale the manual tooling's handoff and prep costs, and how often
# flaws get introduced for both
cost_scales = [0.0, 0.5, 1.0, 2.0, 4.0]
flaw_scales = [0.0, 0.5, 1.0, 2.0, 3.0]
ratio_grid: list[list[float]] = []
for a, cs in enumerate(cost_scales):
    row: list[float] = []
    for b, fs in enumerate(flaw_scales):
        flaws = [min(f * fs, 1.0) for f in BASE["flaw_prob"]]
        costs: dict[str, Any] = {
            k: [c * cs for c in TOOLING["manual"][k]]
            for k in ["handoff_fixed", "handoff_item"]
        } | {k: TOOLING["manual"][k] * cs for k in ["prep_fixed", "prep_item"]}
        seed = 1000 + 50 * a + 10 * b
        status_quo = params_for("manual", flaw_prob=flaws, **costs)
        flagship = params_for("automated", flaw_prob=flaws)
        row.append(
            summarize(simulate("stage-gate", status_quo, 150, seed))[
                "days_mean"
            ]
            / summarize(simulate("lean", flagship, 150, seed + 1))["days_mean"]
        )
    ratio_grid.append(row)
# Adopting the tooling, on a first paper, which pays to learn it, and on
# later ones, which don't, against the status quo
status_quo = scenarios["stage-gate/manual"]
adoption: dict[str, dict] = {}
for j, (name, opts) in enumerate(ADOPTION.items()):
    adoption[name] = {}
    for paper, over in [
        ("first", opts),
        ("later", {k: v for k, v in opts.items() if k not in LEARNED}),
    ]:
        summary = summarize(
            simulate("lean", params_for("automated", **over), REPS, 200 + j)
        )
        adoption[name][paper] = summary | {
            "days_ratio": status_quo["days_mean"] / summary["days_mean"],
            "student_days_ratio": status_quo["student_days_mean"]
            / summary["student_days_mean"],
        }
# How much learning a first paper can absorb and still beat the status quo,
# with the savings arriving over twice as long as the setup takes, and the
# PI reviewing in Word by hand or not needing a translation at all
learn_days = [0.0, 10.0, 30.0, 60.0, 100.0, 150.0]
learn_sweep: dict[str, list[float]] = {}
for name, translate in [("word", BY_HAND), ("none", {})]:
    learn_sweep[name] = []
    for j, d in enumerate(learn_days):
        learning: dict[str, Any] = {
            "learn_days": d,
            "ramp_half_life": 2 * d,
            **translate,
        }
        days = summarize(
            simulate("lean", params_for("automated", **learning), 200, 300 + j)
        )["days_mean"]
        learn_sweep[name].append(status_quo["days_mean"] / days)

# What Calkit would need to deliver, on a first paper, going from today's
# status quo to lean with automated tooling and agents one step at a time,
# each on top of the ones before it
ALL_GOALS = (
    CALKIT
    | COLLABORATION
    | VERIFICATION
    | QUESTIONS
    | PI_ASSIST
    | TRANSPARENCY
)
GOALS: list[tuple[str, str, str, bool, dict[str, Any]]] = [
    ("status quo", "stage-gate", "manual", False, {}),
    ("agents", "stage-gate", "manual", True, {}),
    ("small steps", "lean", "manual", True, {}),
    ("automated tooling", "lean", "automated", True, CALKIT | BY_HAND),
    (
        "faster collaboration",
        "lean",
        "automated",
        True,
        CALKIT | COLLABORATION,
    ),
    (
        "faster verification",
        "lean",
        "automated",
        True,
        CALKIT | COLLABORATION | VERIFICATION,
    ),
    (
        "questions first",
        "lean",
        "automated",
        True,
        CALKIT | COLLABORATION | VERIFICATION | QUESTIONS,
    ),
    (
        "agent-assisted PI review",
        "lean",
        "automated",
        True,
        CALKIT | COLLABORATION | VERIFICATION | QUESTIONS | PI_ASSIST,
    ),
    ("transparent submission", "lean", "automated", True, ALL_GOALS),
]
# For comparison: building the tooling yourself in place of Calkit's, and
# every Calkit goal met but without agents
GOAL_ALTERNATIVES: dict[str, tuple[str, str, bool, dict[str, Any]]] = {
    "diy tooling": ("lean", "automated", True, DIY | BY_HAND),
    "all goals, no agents": ("lean", "automated", False, ALL_GOALS),
    # If reviewers could check a transparent submission faster
    "faster review": (
        "lean",
        "automated",
        True,
        ALL_GOALS | {"review_days": 45.0, "rereview_days": 22.0},
    ),
    # The other edge: today's work, shared openly
    "status quo, shared": ("stage-gate", "manual", False, TRANSPARENCY),
}


def goal_summary(
    policy: str, tooling: str, agents: bool, over: dict, seed: int
) -> dict:
    p = params_for(tooling, agents=agents, **over)
    return summarize(simulate(policy, p, REPS, seed))


goal_steps = [
    {"step": name} | goal_summary(policy, tooling, agents, over, 400 + j)
    for j, (name, policy, tooling, agents, over) in enumerate(GOALS)
]
goal_alternatives = {
    name: goal_summary(*spec, seed=450 + j)
    for j, (name, spec) in enumerate(GOAL_ALTERNATIVES.items())
}
for summary in [*goal_steps, *goal_alternatives.values()]:
    summary["days_ratio"] = goal_steps[0]["days_mean"] / summary["days_mean"]
    summary["student_days_ratio"] = (
        goal_steps[0]["student_days_mean"] / summary["student_days_mean"]
    )
    summary["correct_ratio"] = (
        summary["correct_per_year_mean"]
        / goal_steps[0]["correct_per_year_mean"]
    )
    # The same as gains, e.g., 0.2 for 20% more
    summary["student_days_gain"] = summary["student_days_ratio"] - 1
    summary["correct_gain"] = summary["correct_ratio"] - 1


# Where the status quo's time goes, and what holds it back: each of manual
# tooling's costs taken away on its own, i.e., set to automated tooling's,
# for the status quo and for working in small steps with today's tools
WASTE: dict[str, dict[str, Any]] = {
    "tool hopping": {
        k: TOOLING["automated"][k]
        for k in [
            "handoff_fixed",
            "handoff_item",
            "handoff_error",
            "switch_cost",
            "forget_cost",
        ]
    },
    "review prep": {
        k: TOOLING["automated"][k] for k in ["prep_fixed", "prep_item"]
    },
    "redoing work by hand": {
        "redo_factor": TOOLING["automated"]["redo_factor"]
    },
    "waiting on the PI": PI_ASSIST,
    "drifting from the question": QUESTIONS,
}
WASTE_BASELINES = [
    ("status quo", "stage-gate", False),
    ("small steps, manual", "lean", False),
    ("status quo, agents", "stage-gate", True),
    ("small steps, manual, agents", "lean", True),
]
waste_baselines: dict[str, dict] = {}
waste: dict[str, dict[str, dict]] = {}
for b, (baseline, policy, agents) in enumerate(WASTE_BASELINES):
    base = summarize(
        simulate(policy, params_for("manual", agents=agents), REPS, 600 + b)
    )
    waste_baselines[baseline] = base
    removed = dict(WASTE)
    if policy == "stage-gate":
        removed = removed | {"big batches": {}}
    waste[baseline] = {}
    for j, (name, over) in enumerate(removed.items()):
        run_policy = "lean" if name == "big batches" else policy
        p = params_for("manual", agents=agents, **over)
        summary = summarize(simulate(run_policy, p, REPS, 610 + 10 * b + j))
        waste[baseline][name] = summary | {
            "days_ratio": base["days_mean"] / summary["days_mean"],
            "loops_gain": summary["loops_per_month_mean"]
            / base["loops_per_month_mean"],
        }


waste_breakdown = {name: breakdown(s) for name, s in waste_baselines.items()}
waste_share = {
    name: {k: v / sum(parts.values()) for k, v in parts.items()}
    for name, parts in waste_breakdown.items()
}
# What the answer cites, by names that don't depend on the scenarios'
small = waste["small steps, manual"]["tool hopping"]
waste_headline = {
    "status_quo_waiting_share": waste_share["status quo"]["waiting on the PI"],
    "agents_waiting_share": waste_share["status quo, agents"][
        "waiting on the PI"
    ],
    "batches_loops_gain": waste["status quo"]["big batches"]["loops_gain"],
    "small_steps_hopping_share": waste_share["small steps, manual"][
        "tool hopping"
    ],
    "small_steps_hopping_gain": small["days_ratio"],
    "small_steps_hopping_flaw_cut": 1
    - small["flawed_per_finding_mean"]
    / waste_baselines["small steps, manual"]["flawed_per_finding_mean"],
}


def crossing(xs: list[float], ys: list[float], level: float) -> float | None:
    # Where a falling curve first drops below a level, interpolated
    for x0, x1, y0, y1 in zip(xs, xs[1:], ys, ys[1:]):
        if y0 >= level > y1:
            return x0 + (x1 - x0) * (y0 - level) / (y0 - y1)
    return None


results = {
    "params": {
        "stages": STAGES,
        "base": BASE,
        "tooling": TOOLING,
        "productive_wait": PRODUCTIVE_WAIT,
        "reps": REPS,
    },
    "scenarios": scenarios,
    "ratio": ratios,
    "wait_sweep": {"fractions": fractions, "student_days_ratio": wait_sweep},
    "interval_sweep": {"intervals": intervals, "days_mean": interval_sweep},
    "adoption": adoption,
    "learn_sweep": {
        "learn_days": learn_days,
        "days_ratio": learn_sweep,
        # Learning a first paper can absorb before it's no longer 2x, or
        # no better at all
        "days_to_2x": {
            k: crossing(learn_days, v, 2.0) for k, v in learn_sweep.items()
        },
        "days_to_1x": {
            k: crossing(learn_days, v, 1.0) for k, v in learn_sweep.items()
        },
    },
    "waste": {
        "breakdown": waste_breakdown,
        "share": waste_share,
        "headline": waste_headline,
        "baselines": waste_baselines,
        "removed": waste,
    },
    "goals": {
        "steps": goal_steps,
        "alternatives": goal_alternatives,
        "days_ratio": goal_steps[-1]["days_ratio"],
        "student_days_ratio": goal_steps[-1]["student_days_ratio"],
        "correct_ratio": goal_steps[-1]["correct_ratio"],
        "student_days_gain": goal_steps[-1]["student_days_gain"],
        "correct_gain": goal_steps[-1]["correct_gain"],
    },
    "ratio_grid": {
        "cost_scales": cost_scales,
        "flaw_scales": flaw_scales,
        "days_ratio": ratio_grid,
        "max": max(max(r) for r in ratio_grid),
        "min": min(min(r) for r in ratio_grid),
    },
}


def rounded(value: Any) -> Any:
    # Draws are seeded, but macOS and Linux math libraries can differ in a
    # float's last digits, so keep 12 significant figures to write the same
    # file wherever it's run
    if isinstance(value, float):
        return float(f"{value:.12g}")
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [rounded(v) for v in value]
    return value


OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(rounded(results), indent=2) + "\n")
print(json.dumps(results["ratio"], indent=2))
for k, v in adoption.items():
    print(k, {pp: round(vv["days_ratio"], 2) for pp, vv in v.items()})
print(json.dumps(results["learn_sweep"], indent=2))
for g in [*goal_steps, *goal_alternatives.values()]:
    print(
        g.get("step", "alt"),
        round(g["days_mean"]),
        round(g["days_ratio"], 2),
        round(g["student_days_ratio"], 2),
    )
for k, v in scenarios.items():
    print(k, {kk: round(vv, 1) for kk, vv in v.items() if kk != "effort"})
    print("   ", {kk: round(vv, 1) for kk, vv in v["effort"].items()})
