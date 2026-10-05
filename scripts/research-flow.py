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
finished findings also prompt new ones. Once the PI has read the whole
paper through, it goes to peer review, where reviewers catch some of what's
left and send it back, or reject it outright. Time is in working days.

Automated tooling also has to be adopted: learned and set up, by the student
and, unless they keep reviewing in Word or Overleaf, by the PI, whether it's
built by hand or Calkit's. Agents speed up the mechanics of the work and add
flaws of their own. Calkit's goals are then added one at a time, from today's
status quo, to see what each is worth.

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
    # Chance each PI session's automated re-check of every approved finding
    # against its evidence catches a flaw in one, which needs the evidence
    # linked, as Calkit does
    "reverify": 0.0,
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
    # Adopting automated tooling: days the student spends learning and
    # setting it up first, the half-life over which its costs fall from
    # manual tooling's to its own, what a PI who keeps reviewing in Word or
    # Overleaf costs the student each review, and PI hours spent learning
    # to review another way; all zero once there's nothing left to learn
    "learn_days": 0.0,
    "ramp_half_life": 0.0,
    "translate_fixed": 0.0,
    "translate_item": 0.0,
    "translate_error": 0.0,
    "pi_learn_hours": 0.0,
    # Bespoke tooling: how far it gets from manual tooling's costs to
    # automated tooling's, and the days spent keeping it working every two
    # weeks
    "automation_level": 1.0,
    "upkeep_days": 0.0,
    # Peer review: working days per round, and per re-review after a
    # major revision, the chance reviewers catch each flaw left in what's
    # submitted, and the work a minor revision takes. Two or more caught
    # means rejection and resubmitting elsewhere, one a major revision
    "review_days": 60.0,
    "rereview_days": 30.0,
    "detect_reviewer": 0.5,
    "minor_revision_days": 2.0,
    # Whether the paper is shared openly with what's needed to reproduce
    # it, and the chance that rerunning everything to put that together
    # catches each flaw left
    "shared": False,
    "curate_detect": 0.3,
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
        # Chance a stage working from something copied over by hand gets it
        # wrong, e.g., a mistyped number or a stale figure
        "handoff_error": 0.05,
        # Getting a submission together, e.g., formatting and gathering files
        "submit_prep": 2.0,
        # Putting a reproducibility package together after the fact, for a
        # paper shared openly
        "curate_fixed": 5.0,
        "curate_item": 1.0,
        "prep_fixed": 1.0,
        "prep_item": 0.5,
    },
    "automated": {
        "redo_factor": [0.5, 0.5, 0.75, 0.05, 0.1, 0.02, 0.2],
        "forget_cost": [0.5, 0.5, 4.0, 0.1, 0.5, 0.05, 0.5],
        "switch_cost": 0.05,
        "handoff_fixed": 0.01,
        "handoff_item": 0.01,
        "handoff_error": 0.005,
        "submit_prep": 0.5,
        # The project is the package
        "curate_fixed": 0.5,
        "curate_item": 0.0,
        "prep_fixed": 0.05,
        "prep_item": 0.0,
    },
}
POLICIES = ["stage-gate", "lean"]
# Building it yourself, and reviewing in Word with the PI's edits merged
# back by hand, or with Calkit's round trip
DIY = {
    "learn_days": 60.0,
    "ramp_half_life": 120.0,
    "automation_level": 0.75,
    "upkeep_days": 0.5,
}
CALKIT = {"learn_days": 3.0, "ramp_half_life": 10.0}
BY_HAND = {
    "translate_fixed": 0.5,
    "translate_item": 0.25,
    "translate_error": 0.05,
}
ROUND_TRIP = {
    "translate_fixed": 0.05,
    "translate_item": 0.02,
    "translate_error": 0.005,
}
# Ways of adopting automated tooling for lean, which differ in getting
# there, how far they get, and how the PI reviews
ADOPTION: dict[str, dict[str, Any]] = {
    "diy/word": DIY | BY_HAND,
    "diy/adopts": DIY | {"pi_learn_hours": 20.0},
    "calkit/word": CALKIT | ROUND_TRIP,
    "calkit/browser": CALKIT | {"pi_learn_hours": 0.25},
}
# What agents change: hands-on work, which is faster except where it's
# thinking or physical, flaws in the stages they work in, mechanics done by
# hand, i.e., handoffs, review prep, translation, and redoing downstream
# work, and how much there is to learn about the tooling
AGENTS: dict[str, Any] = {
    "work": [0.6, 0.9, 1.0, 0.4, 0.6, 0.4, 0.7],
    "flaw_prob": [1.0, 1.0, 1.0, 1.25, 1.25, 1.25, 1.25],
    "mechanics": 0.5,
    "manual_redo": [1.0, 1.0, 1.0, 0.6, 0.6, 0.6, 0.6],
    "learn_days": {"diy": 0.5, "calkit": 0.3},
}
# What's learned once, so later papers don't pay it again
LEARNED = ["learn_days", "ramp_half_life", "pi_learn_hours"]
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
    loops: int
    final_pending: bool
    final_ok: bool
    final_caught: bool
    under_review: bool
    published_at: float | None
    submitted_at: float | None
    rejections: int

    def done() -> bool:
        return published_at is not None

    def approved() -> bool:
        return all(i.stage == NS and i.approved for i in items)

    def ready() -> bool:
        # Stage-gate's last gate reads the whole paper; lean needs one too
        return approved() and (policy != "lean" or final_ok)

    def tool(key: str) -> Any:
        # Tooling gets as far from manual tooling's costs as it's automated,
        # and while it's being learned it closes that gap by half every
        # half-life after setup
        def blend(start: float, end: float) -> float:
            end = start + (end - start) * p["automation_level"]
            return end + (start - end) * w

        w = 0.0
        if p["ramp_half_life"]:
            since = max(env.now - p["learn_days"], 0.0)
            w = 0.5 ** (since / p["ramp_half_life"])
        start, value = p["ramp_from"][key], p[key]
        if isinstance(value, list):
            return [blend(a, b) for a, b in zip(start, value)]
        return blend(start, value)

    def upkeep() -> Generator:
        # Bespoke tooling breaking, and being fixed, every two weeks
        while not done():
            yield env.timeout(10.0)
            yield from spend("upkeep", p["upkeep_days"])

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
        cost = tool("switch_cost")
        last = last_used[s]
        if last is not None:
            idle = env.now - last
            cost += tool("forget_cost")[s] * (
                1 - math.exp(-idle / p["forget_tau"])
            )
        current_stage = s
        yield from spend("setup", cost)

    def catch(flaws: list[Flaw]) -> None:
        nonlocal final_ok, final_caught
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
            # The paper needs reading again
            final_ok = False
            final_caught = final_caught or final_pending

    def process(item: Item) -> Generator:
        nonlocal loops
        s = item.stage
        yield from setup(s)
        flaw = item.fixes.get(s)
        if s not in item.done_stages:
            factor = 1.0
        elif flaw is not None and not flaw.fixed:
            factor = p["fix_factor"][s]
        else:
            factor = tool("redo_factor")[s]
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
        # Working from something copied over by hand can get it wrong, in
        # this finding alone
        copied = item.pos > 0 and item.path[item.pos - 1] in HANDOFF_FROM
        if copied and s not in item.taints:
            if rng.random() < tool("handoff_error"):
                item.taints[s] = Flaw(s)
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
            loops += 1
            catch(noticed)

    def handoff(n: float) -> Generator:
        cost = tool("handoff_fixed") + tool("handoff_item") * n
        yield from spend("handoff", cost)

    def submit(to_review: list[Item], priority: int = 1) -> Generator:
        # Prepare the materials and put them in the PI's queue
        size = sum(i.size for i in to_review)
        cost = tool("prep_fixed") + tool("prep_item") * size
        yield from spend("prep", cost, priority=priority)
        # Out to the PI's Word or Overleaf copy and their edits back in
        cost = p["translate_fixed"] + p["translate_item"] * size
        yield from spend("translate", cost, priority=priority)
        if p["translate_error"]:
            # Merging their edits back by hand can get one wrong
            for i in to_review:
                written = i.stage == NS and NS - 1 not in i.taints
                if written and rng.random() < p["translate_error"]:
                    i.taints[NS - 1] = Flaw(NS - 1)
        for i in to_review:
            i.changed = False
            full = i.stage == NS
            hours = p["pi_hours_full" if full else "pi_hours_partial"]
            queue.append([i, hours * i.size])

    def notify() -> None:
        nonlocal reviewed
        reviewed.succeed()
        reviewed = env.event()

    def reverify() -> None:
        nonlocal loops
        # Every approved finding re-checked against its evidence, without
        # the PI
        approved_items = [i for i in items if i.approved]
        if not approved_items:
            return
        loops += 1
        flaws = {
            id(f): f
            for i in approved_items
            for f in i.taints.values()
            if not f.detected
        }
        caught = []
        for flaw in flaws.values():
            n = sum(i.taints.get(flaw.stage) is flaw for i in approved_items)
            if rng.random() < 1 - (1 - p["reverify"]) ** n:
                caught.append(flaw)
        if caught:
            catch(caught)
            notify()

    def review(reviewed_items: list[Item]) -> None:
        nonlocal loops, final_pending, final_ok
        loops += 1
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
        if final_pending:
            for i in reviewed_items:
                final_left.discard(id(i))
            if not final_left:
                final_pending = False
                final_ok = not final_caught
        notify()

    def final_read() -> None:
        nonlocal final_pending, final_caught
        # The whole paper, read through by the PI before it's submitted
        final_pending, final_caught = True, False
        final_left.update(id(i) for i in items)
        for i in items:
            i.changed = True

    def publish() -> Generator:
        nonlocal under_review, published_at, submitted_at, rejections, loops
        wait, resubmit = p["review_days"], True
        while True:
            while not ready():
                yield env.timeout(1.0)
            if resubmit and p["shared"]:
                # Rerunning everything to package it up can show up flaws
                size = sum(i.size for i in items)
                cost = tool("curate_fixed") + tool("curate_item") * size
                yield from spend("curate", cost, priority=0)
                loops += 1
                flaws = {
                    id(f): f
                    for i in items
                    for f in i.taints.values()
                    if not f.detected
                }
                found = [
                    f
                    for f in flaws.values()
                    if rng.random() < p["curate_detect"]
                ]
                if found:
                    catch(found)
                    notify()
                    continue
            if resubmit:
                yield from spend("submit", tool("submit_prep"), priority=0)
            if submitted_at is None:
                submitted_at = env.now
            under_review = True
            yield env.timeout(wait)
            under_review = False
            # Reviewers catch each flaw left in what was submitted
            flaws = {
                id(f): f
                for i in items
                for f in i.taints.values()
                if not f.detected
            }
            found = [
                f
                for f in flaws.values()
                if rng.random() < p["detect_reviewer"]
            ]
            if not found:
                yield from spend(
                    "revise", p["minor_revision_days"], priority=0
                )
                published_at = env.now
                finished.succeed()
                return
            catch(found)
            notify()
            if len(found) >= 2:
                # Rejected, so fixed and sent somewhere else
                rejections += 1
                wait, resubmit = p["review_days"], True
            else:
                wait, resubmit = p["rereview_days"], False

    def pi() -> Generator:
        nonlocal pi_hours, gate_items, gate
        # The PI's sessions, with their share of the hour a week, which isn't
        # banked if nothing is waiting
        interval = p["review_interval"] if policy == "lean" else 5.0
        # Time the PI spends learning to review comes out of the same hour
        learning = p["pi_learn_hours"]
        k = 0
        while not done():
            k += 1
            yield env.timeout(max(0.0, k * interval - env.now))
            # Ahead of the PI's reviews, so a paper isn't approved and then
            # sent back in the same session
            if p["reverify"] and not under_review:
                reverify()
            if policy == "lean":
                changed = [i for i in items if i.changed]
                if changed:
                    # Prep comes ahead of the student's other work
                    yield from submit(changed, priority=0)
            cap = p["pi_hours_per_week"] * interval / 5
            use = min(cap, learning)
            learning -= use
            cap -= use
            pi_hours += use
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
        yield from spend("learning", p["learn_days"])
        while not done():
            todo = [i for i in items if i.stage < NS]
            if not todo:
                # Everything is written up: once it's all approved the PI
                # reads it through, and otherwise it's a wait for the PI
                if approved() and not (final_ok or final_pending):
                    final_read()
                yield reviewed | finished | env.timeout(5.0)
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
        yield from spend("learning", p["learn_days"])
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
            elif approved():
                # Read through and submitted, so a wait for the reviewers
                yield reviewed | finished | env.timeout(5.0)
                continue
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
        [
            "learning",
            "work",
            "rework",
            "wasted",
            "handoff",
            "setup",
            "prep",
            "translate",
            "upkeep",
            "submit",
            "revise",
            "curate",
        ],
        0.0,
    )
    pi_hours = 0.0
    loops = 0
    final_pending = final_ok = final_caught = under_review = False
    final_left: set[int] = set()
    published_at = submitted_at = None
    rejections = 0
    queue: list[list] = []
    gate_items = None
    gate = env.event()
    reviewed = env.event()
    finished = env.event()
    env.process(lean_student() if policy == "lean" else gated_student())
    env.process(pi())
    env.process(publish())
    if p["upkeep_days"]:
        env.process(upkeep())
    env.run(until=finished | env.timeout(p["max_days"]))
    approved_at = [i.approved_at for i in items[:n_original] if i.approved_at]
    return {
        "days": env.now,
        "idle": env.now - sum(effort.values()),
        "finished": done(),
        "mean_days_to_finding": float(np.mean(approved_at)),
        "days_to_first_finding": float(min(approved_at)),
        "effort": dict(effort),
        "pi_hours": pi_hours,
        "findings": len(items),
        "days_to_submission": submitted_at or env.now,
        "rejections": rejections,
        "flawed_findings": sum(bool(i.taints) for i in items),
        "flawed_per_finding": sum(bool(i.taints) for i in items) / len(items),
        # Reviews, re-checks and catches of one's own, per month of 21
        # working days
        "loops_per_month": loops / env.now * 21,
        # Value, as best it can be counted here: findings that are right,
        # per year of 250 working days
        "correct_per_year": sum(not i.taints for i in items) / env.now * 250,
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
        "flawed_per_finding_mean": stat("flawed_per_finding"),
        "days_to_submission_mean": stat("days_to_submission"),
        "rejections_mean": stat("rejections"),
        "loops_per_month_mean": stat("loops_per_month"),
        "correct_per_year_mean": stat("correct_per_year"),
        "unfinished": sum(not r["finished"] for r in runs),
    }


def params_for(
    tooling: str, *, agents: bool = False, **overrides: Any
) -> dict:
    manual = dict(TOOLING["manual"])
    p = {**BASE, **TOOLING[tooling], **overrides}
    if agents:
        a = AGENTS
        manual["redo_factor"] = [
            r * m for r, m in zip(manual["redo_factor"], a["manual_redo"])
        ]
        for k in [
            "handoff_fixed",
            "handoff_item",
            "prep_fixed",
            "prep_item",
            "submit_prep",
        ]:
            manual[k] *= a["mechanics"]
        if tooling == "manual":
            p.update(manual)
        for k in ["translate_fixed", "translate_item"]:
            p[k] *= a["mechanics"]
        p["work"] = [w * m for w, m in zip(p["work"], a["work"])]
        p["flaw_prob"] = [
            min(f * m, 1.0) for f, m in zip(p["flaw_prob"], a["flaw_prob"])
        ]
        kind = "diy" if p["automation_level"] < 1 else "calkit"
        p["learn_days"] *= a["learn_days"][kind]
        p["ramp_half_life"] *= a["learn_days"][kind]
    return p | {"ramp_from": manual}


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
        costs = {
            k: TOOLING["manual"][k] * cs
            for k in [
                "handoff_fixed",
                "handoff_item",
                "prep_fixed",
                "prep_item",
            ]
        }
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
COLLABORATION = {"pi_learn_hours": 0.25}
VERIFICATION = {"detect_self": 0.2, "reverify": 0.3}
PI_ASSIST = {"pi_hours_full": 0.5, "pi_hours_partial": 0.125}
# The project shipped with the paper, so reviewers can check the work itself
TRANSPARENCY = {"detect_reviewer": 0.8, "shared": True}
ALL_GOALS = CALKIT | COLLABORATION | VERIFICATION | PI_ASSIST | TRANSPARENCY
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
        "agent-assisted PI review",
        "lean",
        "automated",
        True,
        CALKIT | COLLABORATION | VERIFICATION | PI_ASSIST,
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
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(results, indent=2) + "\n")
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
