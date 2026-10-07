"""A model of a paper worked in small steps versus stage by stage.

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
flaws of their own.

The stages and their costs are parameters, so this runs for any workflow:
scripts/research-flow.py runs it for the default one, and the simulator page
in the docs runs it in the browser for one a visitor enters.
"""

import math
from collections.abc import Generator
from dataclasses import dataclass, field
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


def by_hop(cost: float) -> list[float]:
    # A cost for each stage's hop to the next, where there's a handoff
    return [cost if s in HANDOFF_FROM else 0.0 for s in range(NS)]


BASE: dict[str, Any] = {
    "n_findings": 6,
    # Stages repeated until a result is worth writing up: on reaching the
    # loop's last stage, a finding goes back to its first for another
    # attempt, as many times on average as this, so one never repeats
    "loop_from": 0,
    "loop_to": 0,
    "attempts": 1.0,
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
        # Moving a stage's outputs into the next stage's tools, per hop
        "handoff_fixed": by_hop(0.25),
        "handoff_item": by_hop(0.25),
        # Chance a stage working from something copied over by hand gets it
        # wrong, e.g., a mistyped number or a stale figure
        "handoff_error": by_hop(0.05),
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
        "handoff_fixed": by_hop(0.01),
        "handoff_item": by_hop(0.01),
        "handoff_error": by_hop(0.005),
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
# Calkit's goals beyond its tooling: the PI reviewing in the browser,
# answers checked against their evidence, agent-assisted PI review, which
# Calkit doesn't do, and the project shipped with the paper, so reviewers
# can check the work itself
COLLABORATION = {"pi_learn_hours": 0.25}
VERIFICATION = {"detect_self": 0.2, "reverify": 0.3}
PI_ASSIST = {"pi_hours_full": 0.5, "pi_hours_partial": 0.125}
TRANSPARENCY = {"detect_reviewer": 0.8, "shared": True}
# Reviewing one answer at a time with its evidence and the code behind it,
# which takes the PI less time and catches more
FOCUSED_REVIEW = {
    "pi_hours_full": 0.75,
    "pi_hours_partial": 0.2,
    "detect_full": 0.75,
    "detect_partial": 0.45,
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
    # Its last attempt didn't work, so it went back to try again
    retried: bool = False
    idea_checked: bool = False
    done_stages: set[int] = field(default_factory=set)
    fixes: dict[int, Flaw] = field(default_factory=dict)
    taints: dict[int, Flaw] = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return self.pos >= len(self.path)

    @property
    def stage(self) -> int:
        return -1 if self.done else self.path[self.pos]


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
    journal_wait: float

    def done() -> bool:
        return published_at is not None

    def approved() -> bool:
        return all(i.done and i.approved for i in items)

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
        # A review can send the finding back while switching to its stage
        version = item.version
        item.retried = False
        yield from setup(s)
        if item.version != version:
            return
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
        if item.pos > 0 and s not in item.taints:
            error = tool("handoff_error")[item.path[item.pos - 1]]
            if error and rng.random() < error:
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
        # An attempt that didn't work, which starts the loop over in full
        retry = (
            s == p["loop_to"]
            and p["attempts"] > 1
            and item.version == version
            and p["loop_from"] in item.path
        )
        if retry and rng.random() >= 1 / p["attempts"]:
            start = item.path.index(p["loop_from"])
            item.done_stages.difference_update(item.path[start : item.pos])
            item.pos = start
            item.retried = True

    def handoff(s: int, n: float) -> Generator:
        cost = tool("handoff_fixed")[s] + tool("handoff_item")[s] * n
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
                written = i.done and ns - 1 not in i.taints
                if written and rng.random() < p["translate_error"]:
                    i.taints[ns - 1] = Flaw(ns - 1)
        for i in to_review:
            i.changed = False
            full = i.done
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
                    d = p["detect_full" if i.done else "detect_partial"]
                    p_miss *= 1 - d
            if rng.random() < 1 - p_miss:
                caught.append(flaw)
        catch(caught)
        for i in reviewed_items:
            if not i.done or i.approved:
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
                new = Item(path=list(range(max(ns - 3, 0), ns)), gen=i.gen + 1)
            elif kind == 1:
                new = Item(path=list(range(1, ns)), gen=i.gen + 1)
            else:
                new = Item(
                    path=[0, ns - 1],
                    gen=i.gen + 1,
                    size=0.25,
                    work={0: 1.0, ns - 1: 0.5},
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
        nonlocal journal_wait
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
            journal_wait += wait
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
            todo = [i for i in items if not i.done]
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
            if moved and not item.retried:
                yield from handoff(s, item.size)

    def gated_student() -> Generator:
        nonlocal gate_items, gate
        yield from spend("learning", p["learn_days"])
        while not done():
            todo = [i for i in items if not i.done]
            if todo:
                s = min(i.stage for i in todo)
                batch = [i for i in todo if i.stage == s]
                for item in batch:
                    yield from process(item)
                # Not the ones going back to try again
                moved = sum(i.size for i in batch if not i.retried)
                if moved:
                    yield from handoff(s, moved)
                # Gates look at the batch; the last one reads the paper
                to_review = (
                    batch if s < ns - 1 else [i for i in items if i.done]
                )
            elif approved():
                # Read through and submitted, so a wait for the reviewers
                yield reviewed | finished | env.timeout(5.0)
                continue
            else:
                to_review = [i for i in items if i.done]
            yield from submit(to_review)
            gate_items = to_review
            yield gate
            gate = env.event()

    ns = len(p["work"])
    rng = np.random.default_rng(seed)
    env = simpy.Environment()
    student = simpy.PriorityResource(env, capacity=1)
    items = [Item(path=list(range(ns))) for _ in range(p["n_findings"])]
    n_original = len(items)
    active_flaws: list[Flaw | None] = [None] * ns
    last_used: list[float | None] = [None] * ns
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
    journal_wait = 0.0
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
    # A run cut off before anything was approved counts as approved then
    approved_at = approved_at or [env.now]
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
        "journal_wait": journal_wait,
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
        "journal_wait_mean": stat("journal_wait"),
        "loops_per_month_mean": stat("loops_per_month"),
        "correct_per_year_mean": stat("correct_per_year"),
        "unfinished": sum(not r["finished"] for r in runs),
    }


def params_for(
    tooling: str,
    *,
    agents: bool = False,
    base: dict[str, Any] = BASE,
    toolings: dict[str, dict[str, Any]] = TOOLING,
    agent_effects: dict[str, Any] = AGENTS,
    **overrides: Any,
) -> dict:
    def scale(value: Any, factor: float) -> Any:
        if isinstance(value, list):
            return [v * factor for v in value]
        return value * factor

    manual = dict(toolings["manual"])
    p = {**base, **toolings[tooling], **overrides}
    if agents:
        a = agent_effects
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
            manual[k] = scale(manual[k], a["mechanics"])
        if tooling == "manual":
            # Agents make manual tooling cheaper, except where it's been
            # set outright
            p.update({k: v for k, v in manual.items() if k not in overrides})
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


def breakdown(summary: dict) -> dict[str, float]:
    # A scenario's calendar, by what it's spent on
    e = summary["effort"]
    return {
        "hands-on work": e["work"],
        "rework": e["rework"] + e["wasted"],
        "review prep": e["prep"],
        "tool hopping": e["handoff"] + e["setup"],
        "submitting and revising": e["submit"] + e["revise"],
        "waiting on the PI": summary["idle_mean"]
        - summary["journal_wait_mean"],
        "waiting on the journal": summary["journal_wait_mean"],
    }
