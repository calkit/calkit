"""Simulate a paper worked in small steps versus stage by stage.

Each of the paper's findings passes through the same stages, from a
literature review to writing it up. A student does the work and a PI, who has
an hour a week for them, reviews it.

- Stage-gate: every finding goes through one stage before any goes through
  the next, and the PI reviews each batch at a gate, which the student
  prepares for and waits on until the PI has been through all of it.
- Lean: one finding at a time goes through every stage, and the PI reviews
  whatever changed at a weekly meeting while the student keeps working.

Both are run with manual tooling, where moving work between stages, preparing
for a review, redoing downstream work and getting back into a stage take real
time, and with automated tooling, where a pipeline keeps everything in one
project and the paper current, so they take much less.

Working at a stage can introduce a flaw into its method, which taints every
finding done that way until a review, or the student working downstream,
catches it, at which point all of them are redone from that stage. Reviews of
finished findings also prompt new ones. Time is in working days.

Writes the results to results/research-flow.json.
"""

import json
import math
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import simpy

STAGES = [
    "literature review",
    "experiment design",
    "experiment",
    "data processing",
    "analysis",
    "figures",
    "writing",
]
NS = len(STAGES)
# Stages whose outputs are files moved into the next stage's tools
HANDOFF_FROM = {2, 3, 4, 5}
BASE: dict[str, Any] = {
    "n_findings": 6,
    # Days of hands-on work per finding at each stage, and their spread
    "work": [3.0, 2.0, 10.0, 3.0, 4.0, 2.0, 3.0],
    "work_cv": 0.5,
    # Redoing the stage a flaw was in, which includes working out the fix
    "fix_factor": [0.5, 0.5, 0.75, 0.5, 0.5, 0.5, 0.5],
    # Chance that working on a finding introduces a flaw into a stage's
    # method, if it doesn't already have one
    "flaw_prob": [0.10, 0.15, 0.10, 0.10, 0.15, 0.05, 0.05],
    # Chance a PI review catches a flaw in one finding it looks at, when the
    # finding is written up and when it's only partway through, and that the
    # student notices one while working on a later stage of the finding
    "detect_full": 0.6,
    "detect_partial": 0.3,
    "detect_self": 0.1,
    # Chance an approved finding prompts something new, halving each
    # generation, and how that splits into a new analysis, an addition to the
    # experiment, and an additional reference
    "idea_prob": 0.3,
    "idea_split": [0.5, 0.25, 0.25],
    "forget_tau": 40.0,
    # The PI's time for this student, and what reviewing takes
    "pi_hours_per_week": 1.0,
    "pi_hours_full": 1.0,
    "pi_hours_partial": 0.25,
    # Lean meets weekly; stage-gate submits at gates and the PI works
    # through them at their weekly slot
    "review_interval": 5.0,
    "max_days": 5000.0,
}
TOOLING: dict[str, dict[str, Any]] = {
    "manual": {
        # Redoing a stage because something upstream of it changed
        "redo_factor": [0.5, 0.5, 0.75, 0.5, 0.5, 0.5, 0.5],
        # Most days it takes to get back into a stage after time away
        "forget_cost": [1.0, 1.0, 5.0, 1.0, 2.0, 0.5, 1.0],
        "switch_cost": 0.25,
        "handoff_fixed": 0.25,
        "handoff_item": 0.25,
        "prep_fixed": 1.0,
        "prep_item": 0.5,
    },
    "automated": {
        "redo_factor": [0.5, 0.5, 0.75, 0.05, 0.1, 0.02, 0.2],
        "forget_cost": [0.5, 0.5, 4.0, 0.1, 0.5, 0.05, 0.5],
        "switch_cost": 0.05,
        "handoff_fixed": 0.01,
        "handoff_item": 0.01,
        "prep_fixed": 0.05,
        "prep_item": 0.0,
    },
}
POLICIES = ["stage-gate", "lean"]
# Fraction of time spent waiting on reviews that goes to other useful work
PRODUCTIVE_WAIT = 0.5
REPS = 400
OUT = Path("results/research-flow.json")


@dataclass
class Flaw:
    stage: int
    detected: bool = False
    fixed: bool = False


@dataclass
class Item:
    path: list[int]
    gen: int = 0
    # Relative to a full finding, for review and prep
    size: float = 1.0
    work: dict[int, float] = field(default_factory=dict)
    pos: int = 0
    started: bool = False
    version: int = 0
    changed: bool = False
    approved: bool = False
    approved_at: float | None = None
    idea_checked: bool = False
    done_stages: set[int] = field(default_factory=set)
    fixes: dict[int, Flaw] = field(default_factory=dict)
    taints: dict[int, Flaw] = field(default_factory=dict)

    @property
    def stage(self) -> int:
        return self.path[self.pos] if self.pos < len(self.path) else NS


def run_project(policy: str, p: dict, seed: int) -> dict:
    # State the processes below rebind, declared ahead of them
    current_stage: int | None
    pi_hours: float
    gate_items: list[Item] | None
    gate: Any
    reviewed: Any

    def done() -> bool:
        return all(i.stage == NS and i.approved for i in items)

    def spend(kind: str, days: float, priority: int = 1) -> Generator:
        # Student time, in chunks of at most a day so a meeting can come
        # between them
        while days > 1e-9:
            dt = min(days, 1.0)
            with student.request(priority=priority) as req:
                yield req
                yield env.timeout(dt)
            effort[kind] += dt
            days -= dt

    def setup(s: int) -> Generator:
        nonlocal current_stage
        if current_stage == s:
            return
        cost = p["switch_cost"]
        last = last_used[s]
        if last is not None:
            idle = env.now - last
            cost += p["forget_cost"][s] * (
                1 - math.exp(-idle / p["forget_tau"])
            )
        current_stage = s
        yield from spend("setup", cost)

    def catch(flaws: list[Flaw]) -> None:
        # Send everything built on a caught flaw back to that stage
        for flaw in flaws:
            flaw.detected = True
            if active_flaws[flaw.stage] is flaw:
                active_flaws[flaw.stage] = None
        for i in items:
            caught = [s for s, f in i.taints.items() if f.detected]
            if not caught:
                continue
            for s in caught:
                i.fixes[s] = i.taints.pop(s)
            i.pos = min(i.pos, i.path.index(min(caught)))
            i.version += 1
            i.approved = False

    def process(item: Item) -> Generator:
        s = item.stage
        yield from setup(s)
        flaw = item.fixes.get(s)
        if s not in item.done_stages:
            factor = 1.0
        elif flaw is not None and not flaw.fixed:
            factor = p["fix_factor"][s]
        else:
            factor = p["redo_factor"][s]
        mean = item.work.get(s, p["work"][s]) * factor
        sigma2 = math.log(1 + p["work_cv"] ** 2)
        days = rng.lognormal(math.log(mean) - sigma2 / 2, sigma2**0.5)
        version = item.version
        item.started = True
        kind = "work" if factor == 1.0 else "rework"
        spent = 0.0
        # Work stops early if a review sends the finding back meanwhile
        while days > 1e-9 and item.version == version:
            dt = min(days, 1.0)
            yield from spend(kind, dt)
            days -= dt
            spent += dt
        last_used[s] = env.now
        if item.version != version:
            effort[kind] -= spent
            effort["wasted"] += spent
            return
        if flaw is not None:
            flaw.fixed = True
            del item.fixes[s]
        item.taints.pop(s, None)
        if active_flaws[s] is None:
            if rng.random() < p["flaw_prob"][s]:
                active_flaws[s] = Flaw(s)
        if (new := active_flaws[s]) is not None:
            item.taints[s] = new
        item.done_stages.add(s)
        item.pos += 1
        item.changed = True
        # Working downstream can show up a flaw upstream
        noticed = [
            f
            for j, f in item.taints.items()
            if j < s and not f.detected and rng.random() < p["detect_self"]
        ]
        if noticed:
            catch(noticed)

    def handoff(n: float) -> Generator:
        cost = p["handoff_fixed"] + p["handoff_item"] * n
        yield from spend("handoff", cost)

    def submit(to_review: list[Item], priority: int = 1) -> Generator:
        # Prepare the materials and put them in the PI's queue
        size = sum(i.size for i in to_review)
        cost = p["prep_fixed"] + p["prep_item"] * size
        yield from spend("prep", cost, priority=priority)
        for i in to_review:
            i.changed = False
            full = i.stage == NS
            hours = p["pi_hours_full" if full else "pi_hours_partial"]
            queue.append([i, hours * i.size])

    def review(reviewed_items: list[Item]) -> None:
        nonlocal reviewed
        # A flaw is caught if any of the findings it shows up in reveals it
        flaws = {
            id(f): f
            for i in reviewed_items
            for f in i.taints.values()
            if not f.detected
        }
        caught = []
        for flaw in flaws.values():
            p_miss = 1.0
            for i in reviewed_items:
                if i.taints.get(flaw.stage) is flaw:
                    d = p["detect_full" if i.stage == NS else "detect_partial"]
                    p_miss *= 1 - d
            if rng.random() < 1 - p_miss:
                caught.append(flaw)
        catch(caught)
        for i in reviewed_items:
            if i.stage != NS or i.approved:
                continue
            i.approved = True
            i.approved_at = env.now
            if i.idea_checked:
                continue
            i.idea_checked = True
            if rng.random() >= p["idea_prob"] * 0.5**i.gen:
                continue
            kind = rng.choice(3, p=p["idea_split"])
            if kind == 0:
                new = Item(path=[4, 5, 6], gen=i.gen + 1)
            elif kind == 1:
                new = Item(path=list(range(1, NS)), gen=i.gen + 1)
            else:
                new = Item(
                    path=[0, 6],
                    gen=i.gen + 1,
                    size=0.25,
                    work={0: 1.0, 6: 0.5},
                )
            items.append(new)
        reviewed.succeed()
        reviewed = env.event()
        if done():
            finished.succeed()

    def pi() -> Generator:
        nonlocal pi_hours, gate_items, gate
        # The PI's sessions, with their share of the hour a week, which isn't
        # banked if nothing is waiting
        interval = p["review_interval"] if policy == "lean" else 5.0
        k = 0
        while not done():
            k += 1
            yield env.timeout(max(0.0, k * interval - env.now))
            if policy == "lean":
                changed = [i for i in items if i.changed]
                if changed:
                    # Prep comes ahead of the student's other work
                    yield from submit(changed, priority=0)
            cap = p["pi_hours_per_week"] * interval / 5
            completed = []
            while queue and cap > 1e-9:
                req = queue[0]
                use = min(cap, req[1])
                req[1] -= use
                cap -= use
                pi_hours += use
                if req[1] <= 1e-9:
                    completed.append(queue.pop(0)[0])
            if policy == "lean" and completed:
                review(completed)
            elif gate_items is not None and not queue:
                review(gate_items)
                gate_items = None
                gate.succeed()

    def lean_student() -> Generator:
        while not done():
            todo = [i for i in items if i.stage < NS]
            if not todo:
                # Everything is written up, so wait for the PI
                yield reviewed | finished
                continue
            # Finish what's started, furthest along first, before new work
            item = min(
                todo, key=lambda i: (not i.started, -i.stage, items.index(i))
            )
            s, version = item.stage, item.version
            yield from process(item)
            moved = item.version == version and item.stage != s
            if moved and s in HANDOFF_FROM:
                yield from handoff(item.size)

    def gated_student() -> Generator:
        nonlocal gate_items, gate
        while not done():
            todo = [i for i in items if i.stage < NS]
            if todo:
                s = min(i.stage for i in todo)
                batch = [i for i in todo if i.stage == s]
                for item in batch:
                    yield from process(item)
                if s in HANDOFF_FROM:
                    yield from handoff(sum(i.size for i in batch))
                # Gates look at the batch; the last one reads the paper
                to_review = (
                    batch
                    if s < NS - 1
                    else [i for i in items if i.stage == NS]
                )
            else:
                to_review = [i for i in items if i.stage == NS]
            yield from submit(to_review)
            gate_items = to_review
            yield gate
            gate = env.event()

    rng = np.random.default_rng(seed)
    env = simpy.Environment()
    student = simpy.PriorityResource(env, capacity=1)
    items = [Item(path=list(range(NS))) for _ in range(p["n_findings"])]
    n_original = len(items)
    active_flaws: list[Flaw | None] = [None] * NS
    last_used: list[float | None] = [None] * NS
    current_stage = None
    effort = dict.fromkeys(
        ["work", "rework", "wasted", "handoff", "setup", "prep"], 0.0
    )
    pi_hours = 0.0
    queue: list[list] = []
    gate_items = None
    gate = env.event()
    reviewed = env.event()
    finished = env.event()
    env.process(lean_student() if policy == "lean" else gated_student())
    env.process(pi())
    env.run(until=finished | env.timeout(p["max_days"]))
    approved = [i.approved_at for i in items[:n_original] if i.approved_at]
    return {
        "days": env.now,
        "idle": env.now - sum(effort.values()),
        "finished": done(),
        "mean_days_to_finding": float(np.mean(approved)),
        "days_to_first_finding": float(min(approved)),
        "effort": dict(effort),
        "pi_hours": pi_hours,
        "findings": len(items),
        "flawed_findings": sum(bool(i.taints) for i in items),
    }


def simulate(policy: str, params: dict, reps: int, seed: int) -> list[dict]:
    return [
        run_project(policy, params, seed=seed * 100_000 + r)
        for r in range(reps)
    ]


def summarize(runs: list[dict]) -> dict:
    def stat(key: str) -> float:
        return float(np.mean([r[key] for r in runs]))

    days = [r["days"] for r in runs]
    effort = {
        k: float(np.mean([r["effort"][k] for r in runs]))
        for k in runs[0]["effort"]
    }
    return {
        "days_mean": stat("days"),
        "days_median": float(np.median(days)),
        "days_p10": float(np.percentile(days, 10)),
        "days_p90": float(np.percentile(days, 90)),
        "idle_mean": stat("idle"),
        "student_days_mean": stat("days") - PRODUCTIVE_WAIT * stat("idle"),
        "days_to_finding_mean": stat("mean_days_to_finding"),
        "days_to_first_finding_mean": stat("days_to_first_finding"),
        "effort": effort,
        "effort_total": sum(effort.values()),
        "pi_hours_mean": stat("pi_hours"),
        "findings_mean": stat("findings"),
        "flawed_findings_mean": stat("flawed_findings"),
        "unfinished": sum(not r["finished"] for r in runs),
    }


def params_for(tooling: str, **overrides: Any) -> dict:
    return {**BASE, **TOOLING[tooling], **overrides}


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
# Student-days per paper as more of the time spent waiting on reviews goes
# to other useful work
fractions = [0.0, 0.25, 0.5, 0.75, 1.0]
wait_sweep = {}
for t in TOOLING:
    sg, ln = scenarios[f"stage-gate/{t}"], scenarios[f"lean/{t}"]
    wait_sweep[t] = [
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
# Where lean's advantage is large: scale the manual tooling's handoff and
# prep costs and how often flaws get introduced
cost_scales = [0.0, 0.5, 1.0, 2.0, 4.0]
flaw_scales = [0.0, 0.5, 1.0, 2.0, 3.0]
ratio_grid: list[list[float]] = []
for a, cs in enumerate(cost_scales):
    row: list[float] = []
    for b, fs in enumerate(flaw_scales):
        over: dict[str, Any] = {
            k: TOOLING["manual"][k] * cs
            for k in [
                "handoff_fixed",
                "handoff_item",
                "prep_fixed",
                "prep_item",
            ]
        }
        over["flaw_prob"] = [min(f * fs, 1.0) for f in BASE["flaw_prob"]]
        p = params_for("manual", **over)
        days = {
            pol: summarize(simulate(pol, p, 150, 1000 + 50 * a + 10 * b + k))[
                "days_mean"
            ]
            for k, pol in enumerate(POLICIES)
        }
        row.append(days["stage-gate"] / days["lean"])
    ratio_grid.append(row)
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
    "ratio_grid": {
        "cost_scales": cost_scales,
        "flaw_scales": flaw_scales,
        "days_ratio": ratio_grid,
        "max": max(max(r) for r in ratio_grid),
        "min": min(min(r) for r in ratio_grid),
    },
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(results, indent=2) + "\n")
print(json.dumps(results["ratio"], indent=2))
for k, v in scenarios.items():
    print(k, {kk: round(vv, 1) for kk, vv in v.items() if kk != "effort"})
    print("   ", {kk: round(vv, 1) for kk, vv in v["effort"].items()})
