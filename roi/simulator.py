"""What the ROI calculator page runs in the browser, in Pyodide.

A visitor's workflow is simulated to answer two questions: whether keeping
everything in one Calkit project is worth it, and whether they can work one
result at a time, i.e., in smaller batches, once automation and CI take away
most of the review prep and tool hopping that costs on every review. Each
part of Calkit is also added to how they work today on its own, to show
what it's worth to them. AI agents can be used in any of them. Every
scenario runs the same seeds, so their differences aren't swamped by noise.
"""

import ast
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import research_flow
from research_flow import (
    AGENTS,
    BASE,
    CALKIT,
    COLLABORATION,
    FOCUSED_REVIEW,
    HANDOFF_FROM,
    LEARNED,
    QUESTIONS,
    ROUND_TRIP,
    STAGES,
    TOOLING,
    TRANSPARENCY,
    VERIFICATION,
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
    "agent_work": 0.7,
    "agent_flaw": 1.25,
    "agent_redo": 0.6,
    "hop": False,
    "hop_hours": 4.0,
    "hop_error": 0.05,
}
# The scenarios that aren't one part of Calkit on its own
SCENARIOS = [
    "today",
    "small steps",
    "calkit, your batches",
    "calkit, first paper",
    "calkit, later",
]
# Adding AI agents, for those who don't use them yet
ADDING_AGENTS = {
    "alone": "AI agents alone",
    "calkit": "Calkit with AI agents",
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
            "agent_work": AGENTS["work"][s],
            "agent_flaw": AGENTS["flaw_prob"][s],
            "agent_redo": AGENTS["manual_redo"][s],
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
        # Experiment through analysis, once, until set otherwise
        "loop_from": 2,
        "loop_to": 4,
        "attempts": BASE["attempts"],
        "policy": "stage-gate",
        # Results whose framing drifts from their question, in percent,
        # and whether reviews today check results against a written one
        "drift": 20.0,
        "focus": "outputs",
        "agents": False,
        "pi_hours_per_week": BASE["pi_hours_per_week"],
        "review_interval": BASE["review_interval"],
        "prep_fixed": manual["prep_fixed"],
        "prep_item": manual["prep_item"],
        "review_days": BASE["review_days"],
        "pi_reviews_in": "browser",
        "reps": 200,
    }


def scenarios(inputs: dict[str, Any]) -> dict[str, tuple[str, dict]]:
    def params(
        tooling: str,
        over: dict[str, Any] | None = None,
        agents: bool | None = None,
    ) -> dict:
        return params_for(
            tooling,
            agents=uses_agents if agents is None else agents,
            base=base,
            toolings=toolings,
            agent_effects=agent_effects,
            **(over or {}),
        )

    rows = inputs["stages"]
    names = [r["name"] for r in rows]
    uses_agents = bool(inputs["agents"])
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
        "loop_from": int(inputs["loop_from"]),
        "loop_to": int(inputs["loop_to"]),
        "attempts": float(inputs["attempts"]),
        "drift_prob": float(inputs["drift"]) / 100,
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
    agent_effects = AGENTS | {
        "work": [float(r["agent_work"]) for r in rows],
        "flaw_prob": [float(r["agent_flaw"]) for r in rows],
        "manual_redo": [float(r["agent_redo"]) for r in rows],
    }
    policy = inputs["policy"]
    browser = inputs["pi_reviews_in"] == "browser"
    review = COLLABORATION if browser else ROUND_TRIP
    if inputs["focus"] == "questions":
        base |= QUESTIONS
    calkit = (
        CALKIT
        | review
        | VERIFICATION
        | FOCUSED_REVIEW
        | QUESTIONS
        | TRANSPARENCY
    )
    # Calkit's curation, for sharing the project with the paper
    curate = {k: automated[k] for k in ["curate_fixed", "curate_item"]}
    out = {"today": (policy, params("manual"))}
    # The two decisions: one project for everything, with batches as they
    # are, and one result at a time, with today's tools or Calkit
    if policy == "stage-gate":
        out["small steps"] = ("lean", params("manual"))
        out["calkit, your batches"] = (policy, params("automated", calkit))
    out["calkit, first paper"] = ("lean", params("automated", calkit))
    out["calkit, later"] = (
        "lean",
        params(
            "automated", {k: v for k, v in calkit.items() if k not in LEARNED}
        ),
    )
    # Each part of Calkit added to how the work is done today on its own,
    # with today's hop costs, which agents may have already cut
    today = params("manual")
    for s, hop in enumerate(hops):
        if not hop:
            continue
        over = {k: list(today[k]) for k in HOP_KEYS}
        for k in HOP_KEYS:
            over[k][s] = automated[k][s]
        name = f"Pipeline: {names[s]} → {names[s + 1]}"
        out[name] = (policy, params("manual", over))
    parts: list[tuple[str, list[str]]] = [
        ("Pipeline: rerunning only what's stale", ["redo_factor"]),
        (
            "A paper that's always ready for review",
            ["prep_fixed", "prep_item"],
        ),
        ("Environments and recorded commands", ["switch_cost", "forget_cost"]),
    ]
    for name, keys in parts:
        over = {k: automated[k] for k in keys}
        out[name] = (policy, params("manual", over))
    out["Answers checked against their evidence"] = (
        policy,
        params("manual", VERIFICATION),
    )
    out["Questions written first, with each result reviewed as an answer"] = (
        policy,
        params("manual", QUESTIONS),
    )
    out["Focused reviews of each answer, with its evidence and code"] = (
        policy,
        params("manual", FOCUSED_REVIEW),
    )
    out["The project shared with the paper"] = (
        policy,
        params("manual", TRANSPARENCY | curate),
    )
    if not uses_agents:
        out[ADDING_AGENTS["alone"]] = (policy, params("manual", agents=True))
        out[ADDING_AGENTS["calkit"]] = (
            "lean",
            params("automated", calkit, agents=True),
        )
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
        # And fewer flawed results published, the same way
        fewer = [
            a["flawed_findings"] - b["flawed_findings"]
            for a, b in zip(runs["today"], runs[name])
        ]
        fewer_half = (
            1.96 * float(np.std(fewer, ddof=1)) / math.sqrt(len(fewer))
        )
        s = summaries[name]
        return {
            "name": name,
            "days": s["days_mean"],
            "saved": float(np.mean(saved)),
            "low": float(np.mean(saved)) - half,
            "high": float(np.mean(saved)) + half,
            "ratio": today["days_mean"] / s["days_mean"],
            "flawed": s["flawed_findings_mean"],
            "fewer_flawed": float(np.mean(fewer)),
            "fewer_flawed_half": fewer_half,
            "learning_days": s["effort"]["learning"],
            "unfinished": s["unfinished"],
        }

    def split() -> dict[str, float] | None:
        # What Calkit saves, split between smaller batches and one project
        # by what each saves on average over both orders of adopting them,
        # so the two add up to the whole, along with what they save only
        # together
        if "small steps" not in runs:
            return None
        t, b, s, p = (
            summaries[n]["days_mean"]
            for n in [
                "today",
                "calkit, first paper",
                "small steps",
                "calkit, your batches",
            ]
        )
        return {
            "batches": ((t - s) + (p - b)) / 2,
            "project": ((t - p) + (s - b)) / 2,
            "together": (t - b) - (t - s) - (t - p),
        }

    summaries = {name: summarize(r) for name, r in runs.items()}
    today = summaries["today"]
    others = SCENARIOS + list(ADDING_AGENTS.values())
    parts = [compare(n) for n in runs if n not in others]
    return {
        "today": {
            "days": today["days_mean"],
            "p10": today["days_p10"],
            "p90": today["days_p90"],
            "flawed": today["flawed_findings_mean"],
            "unfinished": today["unfinished"],
            "breakdown": breakdown(today),
        },
        "split": split(),
        "first": compare("calkit, first paper"),
        "later": compare("calkit, later"),
        "parts": sorted(parts, key=lambda c: -c["saved"]),
        "agents": [compare(n) for n in ADDING_AGENTS.values() if n in runs],
        "uses_agents": bool(inputs["agents"]),
        "reps": len(runs["today"]),
    }


def explain() -> dict[str, Any]:
    # How the model works, read from its source so it can't drift from it:
    # docstrings, every assumption with the comment above it, and the
    # comment opening each step of a simulated project
    def note(lines: list[str], line: int) -> str:
        # The comment block right above a line, as one paragraph
        found: list[str] = []
        i = line - 2
        while i >= 0 and lines[i].strip().startswith("#"):
            found.insert(0, lines[i].strip().lstrip("#").strip())
            i -= 1
        return " ".join(found)

    def plain(value: Any) -> Any:
        if isinstance(value, (set, frozenset)):
            return sorted(value)
        if isinstance(value, dict):
            return {k: plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [plain(v) for v in value]
        return value

    def describe(
        src: str, name: str, line: int, node: ast.expr, value: Any
    ) -> dict[str, Any]:
        lines = src.splitlines()
        out: dict[str, Any] = {
            "name": name,
            "line": line,
            "note": note(lines, line),
        }
        if isinstance(node, ast.Dict):
            out["entries"] = [
                describe(src, k.value, k.lineno, v, value[k.value])
                for k, v in zip(node.keys, node.values)
                if isinstance(k, ast.Constant)
            ]
        elif isinstance(node, (ast.Name, ast.BinOp)):
            # Built from other assumptions, so it's shown as written
            out["expr"] = ast.get_source_segment(src, node)
        else:
            out["value"] = plain(value)
        return out

    def blocks(doc: str) -> list[dict[str, Any]]:
        # A docstring's paragraphs and bulleted lists
        out: list[dict[str, Any]] = []
        for block in doc.split("\n\n"):
            rows = [r.strip() for r in block.splitlines()]
            if rows[0].startswith("- "):
                items: list[str] = []
                for r in rows:
                    if r.startswith("- "):
                        items.append(r[2:])
                    else:
                        items[-1] += " " + r
                out.append({"items": items})
            else:
                out.append({"text": " ".join(rows)})
        return out

    def steps(src: str, tree: ast.Module) -> list[dict[str, Any]]:
        # Each process and event in a project, by the comment opening it
        lines = src.splitlines()
        run = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "run_project"
        )
        out = []
        for f in run.body:
            if not isinstance(f, ast.FunctionDef):
                continue
            # The comment above its first statement, past any nonlocal
            first = next(b for b in f.body if not isinstance(b, ast.Nonlocal))
            comment = note(lines, first.lineno)
            if comment:
                out.append(
                    {
                        "name": f.name,
                        "line": f.lineno,
                        "note": comment,
                    }
                )
        return out

    src = Path(research_flow.__file__).read_text()
    tree = ast.parse(src)
    assumptions = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            target: ast.expr = node.target
            value: ast.expr = node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        else:
            continue
        if not (isinstance(target, ast.Name) and target.id.isupper()):
            continue
        name = target.id
        item = describe(
            src, name, node.lineno, value, getattr(research_flow, name)
        )
        # Structure, e.g., the stage names, isn't an assumption, and
        # assumptions sharing a comment follow the one it's above
        if item["note"] or "entries" in item:
            assumptions.append(item)
    page_src = Path(__file__).read_text()
    page_tree = ast.parse(page_src)
    # What Calkit means in this calculator's scenarios
    calkit = next(
        n
        for n in ast.walk(page_tree)
        if isinstance(n, ast.Assign)
        and isinstance(n.targets[0], ast.Name)
        and n.targets[0].id == "calkit"
    )
    return {
        "model": blocks(ast.get_docstring(tree) or ""),
        "page": blocks(ast.get_docstring(page_tree) or ""),
        "calkit": {
            "line": calkit.lineno,
            "expr": ast.get_source_segment(page_src, calkit.value),
        },
        "assumptions": assumptions,
        "steps": steps(src, tree),
        "stages": STAGES,
    }


def handle(message: str) -> str:
    # What the page's workers call, in JSON both ways
    m = json.loads(message)
    calls: dict[str, Callable[..., Any]] = {
        "defaults": defaults,
        "plan": plan,
        "run": run,
        "report": report,
        "explain": explain,
    }
    return json.dumps(calls[m["call"]](*m["args"]))
