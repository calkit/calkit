"""Simulate a paper worked in small steps versus stage by stage.

Each of the paper's findings passes through the same stages: experiment,
analysis, figures and writing. A student does the work and a PI reviews it.

- Stage-gate: every finding goes through one stage before any goes through
  the next, and the PI reviews each batch at a gate, which the student
  prepares for and waits on.
- Lean: one finding at a time goes through every stage, and the PI reviews
  whatever changed at a weekly meeting while the student keeps working.

Both are run with manual tooling, where moving work between stages and
preparing for a review take real time, and with automated tooling, where a
pipeline keeps the paper current so they take almost none.

Working at a stage can introduce a flaw into its method, which taints every
finding done that way until a review catches it, at which point all of them
are redone from that stage. Reviews of finished findings also prompt new
ones. Coming back to a stage after a while costs time to remember it, e.g.,
setting an experiment back up. Time is in working days.

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

STAGES = ["experiment", "analysis", "figures", "writing"]
NS = len(STAGES)
BASE: dict[str, Any] = {
    "n_findings": 6,
    # Days of hands-on work per finding at each stage, and their spread
    "work": [10.0, 5.0, 2.0, 3.0],
    "work_cv": 0.5,
    # Redoing a stage takes this fraction of doing it the first time
    "rework_factor": 0.5,
    # Chance that working on a finding introduces a flaw into a stage's
    # method, if it doesn't already have one
    "flaw_prob": [0.15, 0.15, 0.05, 0.05],
    # Chance a review catches a flaw in one finding it looks at, when the
    # finding is written up and when it's only partway through
    "detect_full": 0.6,
    "detect_partial": 0.3,
    # Chance an approved finding prompts a new one, halving each generation,
    # and that the new one needs a new experiment rather than more analysis
    "idea_prob": 0.3,
    "idea_new_experiment": 0.3,
    # Switching stages, plus remembering one not worked on for a while
    "switch_cost": 0.1,
    "forget_cost": [5.0, 2.0, 0.5, 1.0],
    "forget_tau": 40.0,
    # Lean meetings are weekly; stage-gate reviews take the PI a while
    "review_interval": 5.0,
    "gate_turnaround": 5.0,
    "gate_turnaround_per_item": 0.5,
    "max_days": 5000.0,
}
TOOLING = {
    "manual": {
        "handoff_fixed": 0.25,
        "handoff_item": 0.25,
        "prep_fixed": 0.5,
        "prep_item": 0.25,
    },
    "automated": {
        "handoff_fixed": 0.01,
        "handoff_item": 0.01,
        "prep_fixed": 0.05,
        "prep_item": 0.0,
    },
}
POLICIES = ["stage-gate", "lean"]
REPS = 400
OUT = Path("results/research-flow.json")


@dataclass
class Flaw:
    stage: int
    detected: bool = False


@dataclass
class Item:
    gen: int
    stage: int
    started: bool = False
    version: int = 0
    changed: bool = False
    approved: bool = False
    approved_at: float | None = None
    idea_checked: bool = False
    done_stages: set = field(default_factory=set)
    taints: dict = field(default_factory=dict)


class Project:
    def __init__(self, policy: str, p: dict, seed: int):
        self.policy = policy
        self.p = p
        self.rng = np.random.default_rng(seed)
        self.env = simpy.Environment()
        self.student = simpy.PriorityResource(self.env, capacity=1)
        self.items = [Item(gen=0, stage=0) for _ in range(p["n_findings"])]
        self.n_original = len(self.items)
        self.active_flaws: list[Flaw | None] = [None] * NS
        self.last_used: list[float | None] = [None] * NS
        self.current_stage: int | None = None
        self.effort = dict.fromkeys(
            ["work", "rework", "wasted", "handoff", "setup", "prep"], 0.0
        )
        self.n_reviews = 0
        self.reviewed = self.env.event()
        self.finished = self.env.event()

    def done(self) -> bool:
        return all(i.stage == NS and i.approved for i in self.items)

    def spend(self, kind: str, days: float, priority: int = 1) -> Generator:
        # Student time, in chunks of at most a day so a meeting can come
        # between them
        while days > 1e-9:
            dt = min(days, 1.0)
            with self.student.request(priority=priority) as req:
                yield req
                yield self.env.timeout(dt)
            self.effort[kind] += dt
            days -= dt

    def setup(self, s: int) -> Generator:
        if self.current_stage == s:
            return
        cost = self.p["switch_cost"]
        last = self.last_used[s]
        if last is not None:
            idle = self.env.now - last
            cost += self.p["forget_cost"][s] * (
                1 - math.exp(-idle / self.p["forget_tau"])
            )
        self.current_stage = s
        yield from self.spend("setup", cost)

    def process(self, item: Item, s: int) -> Generator:
        yield from self.setup(s)
        rework = s in item.done_stages
        mean = self.p["work"][s] * (self.p["rework_factor"] if rework else 1)
        sigma2 = math.log(1 + self.p["work_cv"] ** 2)
        days = self.rng.lognormal(math.log(mean) - sigma2 / 2, sigma2**0.5)
        version = item.version
        item.started = True
        kind = "rework" if rework else "work"
        spent = 0.0
        # Work stops early if a review sends the finding back meanwhile
        while days > 1e-9 and item.version == version:
            dt = min(days, 1.0)
            yield from self.spend(kind, dt)
            days -= dt
            spent += dt
        self.last_used[s] = self.env.now
        if item.version != version:
            self.effort[kind] -= spent
            self.effort["wasted"] += spent
            return
        item.taints.pop(s, None)
        if self.active_flaws[s] is None:
            if self.rng.random() < self.p["flaw_prob"][s]:
                self.active_flaws[s] = Flaw(s)
        if (flaw := self.active_flaws[s]) is not None:
            item.taints[s] = flaw
        item.done_stages.add(s)
        item.stage = s + 1
        item.changed = True

    def handoff(self, n: int) -> Generator:
        cost = self.p["handoff_fixed"] + self.p["handoff_item"] * n
        yield from self.spend("handoff", cost)

    def prep(self, n: int, priority: int = 1) -> Generator:
        cost = self.p["prep_fixed"] + self.p["prep_item"] * n
        yield from self.spend("prep", cost, priority=priority)

    def review(self, items: list[Item]) -> None:
        self.n_reviews += 1
        # A flaw is caught if any of the findings it shows up in reveals it
        flaws = {
            id(f): f
            for i in items
            for f in i.taints.values()
            if not f.detected
        }
        for flaw in flaws.values():
            p_miss = 1.0
            for i in items:
                if i.taints.get(flaw.stage) is flaw:
                    d = (
                        self.p["detect_full"]
                        if i.stage == NS
                        else self.p["detect_partial"]
                    )
                    p_miss *= 1 - d
            if self.rng.random() < 1 - p_miss:
                flaw.detected = True
                if self.active_flaws[flaw.stage] is flaw:
                    self.active_flaws[flaw.stage] = None
        # Send everything built on a caught flaw back to that stage
        for i in self.items:
            caught = [s for s, f in i.taints.items() if f.detected]
            if caught:
                for s in caught:
                    del i.taints[s]
                i.stage = min(i.stage, *caught)
                i.version += 1
                i.approved = False
        for i in items:
            i.changed = False
            if i.stage != NS or i.approved:
                continue
            i.approved = True
            i.approved_at = self.env.now
            if not i.idea_checked:
                i.idea_checked = True
                p_idea = self.p["idea_prob"] * 0.5**i.gen
                if self.rng.random() < p_idea:
                    new_exp = self.rng.random() < self.p["idea_new_experiment"]
                    self.items.append(
                        Item(gen=i.gen + 1, stage=0 if new_exp else 1)
                    )
        self.reviewed.succeed()
        self.reviewed = self.env.event()
        if self.done():
            self.finished.succeed()

    def lean_student(self) -> Generator:
        while not self.done():
            todo = [i for i in self.items if i.stage < NS]
            if not todo:
                # Everything is written up, so wait for the meeting
                yield self.reviewed | self.finished
                continue
            # Finish what's started, furthest along first, before new work
            item = min(
                todo,
                key=lambda i: (not i.started, -i.stage, self.items.index(i)),
            )
            s = item.stage
            yield from self.process(item, s)
            if item.stage == s + 1 and s < NS - 1:
                yield from self.handoff(1)

    def lean_meetings(self) -> Generator:
        while not self.done():
            yield self.env.timeout(self.p["review_interval"])
            changed = [i for i in self.items if i.changed]
            # Prep comes ahead of the student's other work
            yield from self.prep(len(changed), priority=0)
            self.review([i for i in self.items if i.changed])

    def gated_student(self) -> Generator:
        while not self.done():
            todo = [i for i in self.items if i.stage < NS]
            if todo:
                s = min(i.stage for i in todo)
                batch = [i for i in todo if i.stage == s]
                for item in batch:
                    yield from self.process(item, s)
                if s < NS - 1:
                    yield from self.handoff(len(batch))
                # Gates look at the batch; the last one reads the paper
                to_review = (
                    batch
                    if s < NS - 1
                    else [i for i in self.items if i.stage == NS]
                )
            else:
                to_review = [i for i in self.items if i.stage == NS]
            yield from self.prep(len(to_review))
            yield self.env.timeout(
                self.p["gate_turnaround"]
                + self.p["gate_turnaround_per_item"] * len(to_review)
            )
            self.review(to_review)

    def run(self) -> dict:
        if self.policy == "lean":
            self.env.process(self.lean_student())
            self.env.process(self.lean_meetings())
        else:
            self.env.process(self.gated_student())
        self.env.run(
            until=self.finished | self.env.timeout(self.p["max_days"])
        )
        originals = self.items[: self.n_original]
        approved = [i.approved_at for i in originals if i.approved_at]
        return {
            "days": self.env.now,
            "finished": self.done(),
            "mean_days_to_finding": float(np.mean(approved)),
            "days_to_first_finding": float(min(approved)),
            "effort": dict(self.effort),
            "findings": len(self.items),
            "reviews": self.n_reviews,
            "flawed_findings": sum(bool(i.taints) for i in self.items),
        }


def simulate(policy: str, params: dict, reps: int, seed: int) -> list[dict]:
    return [
        Project(policy, params, seed=seed * 100_000 + r).run()
        for r in range(reps)
    ]


def summarize(runs: list[dict]) -> dict:
    def stat(key: str) -> float:
        return float(np.mean([r[key] for r in runs]))

    effort = {
        k: float(np.mean([r["effort"][k] for r in runs]))
        for k in runs[0]["effort"]
    }
    return {
        "days_mean": stat("days"),
        "days_median": float(np.median([r["days"] for r in runs])),
        "days_p10": float(np.percentile([r["days"] for r in runs], 10)),
        "days_p90": float(np.percentile([r["days"] for r in runs], 90)),
        "days_to_finding_mean": stat("mean_days_to_finding"),
        "days_to_first_finding_mean": stat("days_to_first_finding"),
        "effort": effort,
        "effort_total": sum(effort.values()),
        "findings_mean": stat("findings"),
        "reviews_mean": stat("reviews"),
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


def ratio(key: str, tooling: str) -> float:
    a = scenarios[f"stage-gate/{tooling}"][key]
    b = scenarios[f"lean/{tooling}"][key]
    return float(a / b)


# How often lean should meet, with and without the tooling
intervals = [1, 2, 5, 10, 20, 40, 80]
interval_sweep = {
    t: [
        summarize(
            simulate("lean", params_for(t, review_interval=dt), 200, 100 + j)
        )["days_mean"]
        for j, dt in enumerate(intervals)
    ]
    for t in TOOLING
}
# Where lean's advantage is large: scale the manual tooling's costs and how
# often flaws get introduced
cost_scales = [0.0, 0.5, 1.0, 2.0, 4.0]
flaw_scales = [0.0, 0.5, 1.0, 2.0, 3.0]
ratio_grid: list[list[float]] = []
for a, cs in enumerate(cost_scales):
    row: list[float] = []
    for b, fs in enumerate(flaw_scales):
        over: dict[str, Any] = {
            k: v * cs for k, v in TOOLING["manual"].items()
        }
        over["flaw_prob"] = [min(f * fs, 1.0) for f in BASE["flaw_prob"]]
        p = {**BASE, **over}
        days = {
            pol: summarize(simulate(pol, p, 150, 1000 + 50 * a + 10 * b + k))[
                "days_mean"
            ]
            for k, pol in enumerate(POLICIES)
        }
        row.append(days["stage-gate"] / days["lean"])
    ratio_grid.append(row)
results = {
    "params": {"base": BASE, "tooling": TOOLING, "reps": REPS},
    "scenarios": scenarios,
    "ratio": {
        "days_manual": ratio("days_mean", "manual"),
        "days_automated": ratio("days_mean", "automated"),
        "days_combined": scenarios["stage-gate/manual"]["days_mean"]
        / scenarios["lean/automated"]["days_mean"],
        "days_to_finding_manual": ratio("days_to_finding_mean", "manual"),
        "days_to_finding_automated": ratio(
            "days_to_finding_mean", "automated"
        ),
        "days_to_finding_combined": scenarios["stage-gate/manual"][
            "days_to_finding_mean"
        ]
        / scenarios["lean/automated"]["days_to_finding_mean"],
        "effort_manual": ratio("effort_total", "manual"),
        "effort_automated": ratio("effort_total", "automated"),
    },
    "interval_sweep": {"intervals": intervals, "days_mean": interval_sweep},
    "ratio_grid": {
        "cost_scales": cost_scales,
        "flaw_scales": flaw_scales,
        "days_ratio": ratio_grid,
        "max": max(max(r) for r in ratio_grid),
    },
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(results, indent=2) + "\n")
print(json.dumps(results["ratio"], indent=2))
for k, v in scenarios.items():
    print(k, {kk: round(vv, 1) for kk, vv in v.items() if kk != "effort"})
    print("   ", {kk: round(vv, 1) for kk, vv in v["effort"].items()})
