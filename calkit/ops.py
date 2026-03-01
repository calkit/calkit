"""Ops functionality.

An op is a process that runs outside the pipeline, e.g., for continuous data
collection, a task run on a schedule, or a fixed number of iterations.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Op(BaseModel):
    kind = Literal[
        "single-shot",
        "continuous",
        "fixed-iterations",
        "scheduled",
        "event-driven",
    ]
    cmd: str


class ContinuousOp(Op):
    """Run continuously."""

    pass


class ScheduledOp(Op):
    kind = Literal["scheduled"]
    schedule: str  # TODO: Be more specific about validation


class FixedIterationsOp(Op):
    kind = Literal["fixed-iterations"]
    n_iterations: int


def run(op: Op):
    """Run an op."""
    pass


def start(ops: list[Op]):
    """Start and monitor a list of ops."""
    pass
