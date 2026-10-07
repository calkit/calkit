"""What the simulator page runs in the browser, in Pyodide.

A visitor's workflow is simulated as they work today, fully integrated, i.e.,
in small steps with automated tooling, and with each of today's manual costs
automated on its own, to show which is worth automating first. Every
scenario runs the same seeds, so their differences aren't swamped by noise.
"""

import json
import math
from collections.abc import Callable
from typing import Any

import numpy as np
from research_flow import (
    ADOPTION,
    BASE,
    HANDOFF_FROM,
    LEARNED,
    STAGES,
    TOOLING,
    breakdown,
    params_for,
    run_project,
    summarize,
)

HOURS_PER_DAY = 8.0
HOP_KEYS = ["handoff_fixed", "handoff_item", "handoff_error"]
# What a stage added on the page starts with
NEW_STAGE: dict[str, Any] = {
    "name": "",
    "work": 3.0,
    "fix_factor": 0.5,
    "flaw_prob": 0.1,
    "redo_manual": 0.5,
    "redo_automated": 0.1,
    "forget_manual": 1.0,
    "forget_automated": 0.25,
    "hop": False,
    "hop_hours": 4.0,
    "hop_error": 0.05,
}


def defaults() -> dict[str, Any]:
    manual, automated = TOOLING["manual"], TOOLING["automated"]
    stages = [
        {
            "name": name,
            "work": BASE["work"][s],
            "fix_factor": BASE["fix_factor"][s],
            "flaw_prob": BASE["flaw_prob"][s],
            "redo_manual": manual["redo_factor"][s],
            "redo_automated": automated["redo_factor"][s],
            "forget_manual": manual["forget_cost"][s],
            "forget_automated": automated["forget_cost"][s],
            "hop": s in HANDOFF_FROM,
            "hop_hours": NEW_STAGE["hop_hours"],
            "hop_error": NEW_STAGE["hop_error"],
        }
        for s, name in enumerate(STAGES)
    ]
    for s in HANDOFF_FROM:
        stages[s]["hop_hours"] = HOURS_PER_DAY * (
            manual["handoff_fixed"][s] + manual["handoff_item"][s]
        )
        stages[s]["hop_error"] = manual["handoff_error"][s]
    return {
        "stages": stages,
        "new_stage": NEW_STAGE,
        "n_findings": BASE["n_findings"],
        "policy": "stage-gate",
        "pi_hours_per_week": BASE["pi_hours_per_week"],
        "review_interval": BASE["review_interval"],
        "prep_fixed": manual["prep_fixed"],
        "prep_item": manual["prep_item"],
        "review_days": BASE["review_days"],
        "pi_reviews_in": "word",
        "reps": 200,
    }


def scenarios(inputs: dict[str, Any]) -> dict[str, tuple[str, dict]]:
    def params(tooling: str, **overrides: Any) -> dict:
        return params_for(tooling, base=base, toolings=toolings, **overrides)

    rows = inputs["stages"]
    names = [r["name"] for r in rows]
    # The last stage has nowhere to hop to
    hops = [bool(r["hop"]) and s < len(rows) - 1 for s, r in enumerate(rows)]
    # Half of a hop's cost is moving anything at all, and half is per
    # finding moved, so moving one finding costs what was entered
    half = [
        float(r["hop_hours"]) / HOURS_PER_DAY / 2 if hop else 0.0
        for r, hop in zip(rows, hops)
    ]
    base = BASE | {
        "n_findings": int(inputs["n_findings"]),
        "work": [float(r["work"]) for r in rows],
        "fix_factor": [float(r["fix_factor"]) for r in rows],
        "flaw_prob": [float(r["flaw_prob"]) for r in rows],
        "pi_hours_per_week": float(inputs["pi_hours_per_week"]),
        "review_interval": float(inputs["review_interval"]),
        "review_days": float(inputs["review_days"]),
        "rereview_days": float(inputs["review_days"]) / 2,
    }
    manual = TOOLING["manual"] | {
        "redo_factor": [float(r["redo_manual"]) for r in rows],
        "forget_cost": [float(r["forget_manual"]) for r in rows],
        "handoff_fixed": half,
        "handoff_item": half,
        "handoff_error": [
            float(r["hop_error"]) if hop else 0.0 for r, hop in zip(rows, hops)
        ],
        "prep_fixed": float(inputs["prep_fixed"]),
        "prep_item": float(inputs["prep_item"]),
    }
    # Automated tooling's cost of a hop, wherever there's one to make
    automated = TOOLING["automated"] | {
        "redo_factor": [float(r["redo_automated"]) for r in rows],
        "forget_cost": [float(r["forget_automated"]) for r in rows],
    }
    for k in HOP_KEYS:
        automated[k] = [max(TOOLING["automated"][k]) * h for h in hops]
    toolings = {"manual": manual, "automated": automated}
    policy = inputs["policy"]
    adopt = ADOPTION[f"calkit/{inputs['pi_reviews_in']}"]
    out = {
        "today": (policy, params("manual")),
        "integrated, first paper": ("lean", params("automated", **adopt)),
        "integrated, later papers": (
            "lean",
            params(
                "automated",
                **{k: v for k, v in adopt.items() if k not in LEARNED},
            ),
        ),
    }
    # Each of today's manual costs automated on its own
    for s, hop in enumerate(hops):
        if not hop:
            continue
        over = {k: list(manual[k]) for k in HOP_KEYS}
        for k in HOP_KEYS:
            over[k][s] = automated[k][s]
        out[f"{names[s]} → {names[s + 1]}"] = (
            policy,
            params("manual", **over),
        )
    for name, keys in [
        ("review prep", ["prep_fixed", "prep_item"]),
        ("getting back into a stage", ["switch_cost", "forget_cost"]),
        ("redoing downstream work", ["redo_factor"]),
    ]:
        over = {k: automated[k] for k in keys}
        out[name] = (policy, params("manual", **over))
    if policy == "stage-gate":
        out["small steps"] = ("lean", params("manual"))
    return out


def plan(inputs: dict[str, Any]) -> list[str]:
    return list(scenarios(inputs))


def run(inputs: dict[str, Any], name: str, start: int, stop: int) -> list:
    policy, p = scenarios(inputs)[name]
    return [run_project(policy, p, seed=r) for r in range(start, stop)]


def report(inputs: dict[str, Any], runs: dict[str, list]) -> dict[str, Any]:
    def compare(name: str) -> dict[str, Any]:
        # Days saved per paper, paired by seed, with a 95% interval
        saved = [
            a["days"] - b["days"] for a, b in zip(runs["today"], runs[name])
        ]
        half = 1.96 * float(np.std(saved, ddof=1)) / math.sqrt(len(saved))
        s = summaries[name]
        return {
            "name": name,
            "days": s["days_mean"],
            "saved": float(np.mean(saved)),
            "low": float(np.mean(saved)) - half,
            "high": float(np.mean(saved)) + half,
            "ratio": today["days_mean"] / s["days_mean"],
            "flawed_per_finding": s["flawed_per_finding_mean"],
            "learning_days": s["effort"]["learning"],
            "unfinished": s["unfinished"],
        }

    summaries = {name: summarize(r) for name, r in runs.items()}
    today = summaries["today"]
    fixed = ["today", "integrated, first paper", "integrated, later papers"]
    candidates = [compare(name) for name in runs if name not in fixed]
    return {
        "today": {
            "days": today["days_mean"],
            "p10": today["days_p10"],
            "p90": today["days_p90"],
            "flawed_per_finding": today["flawed_per_finding_mean"],
            "unfinished": today["unfinished"],
            "breakdown": breakdown(today),
        },
        "first": compare("integrated, first paper"),
        "later": compare("integrated, later papers"),
        "candidates": sorted(candidates, key=lambda c: -c["saved"]),
        "reps": len(runs["today"]),
    }


def handle(message: str) -> str:
    # What the page's workers call, in JSON both ways
    m = json.loads(message)
    calls: dict[str, Callable[..., Any]] = {
        "defaults": defaults,
        "plan": plan,
        "run": run,
        "report": report,
    }
    return json.dumps(calls[m["call"]](*m["args"]))
