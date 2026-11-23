"""Saying what's being done, e.g., on ``calkit run``'s spinner.

Whoever shows progress sets a reporter around the work, and code deep
inside it reports through that without being passed it, e.g., an
environment check behind a CLI command that takes no such argument.
"""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Callable, Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class _Reporter:
    func: Callable[[str], None]
    label: str | None


_reporter: contextvars.ContextVar[_Reporter | None] = contextvars.ContextVar(
    "progress_reporter", default=None
)


@contextlib.contextmanager
def reporting(
    func: Callable[[str], None], label: str | None = None
) -> Iterator[None]:
    """Send what's reported inside this block to ``func``.

    ``label`` is what the work is on, as whoever's watching knows it, e.g.,
    an environment's name in ``calkit.yaml`` rather than in its spec.
    """
    token = _reporter.set(_Reporter(func=func, label=label))
    try:
        yield
    finally:
        _reporter.reset(token)


def active() -> bool:
    """Whether anyone is being told what's being done."""
    return _reporter.get() is not None


def label(default: str) -> str:
    """What the work is on, as whoever's watching knows it."""
    reporter = _reporter.get()
    if reporter is None or reporter.label is None:
        return default
    return reporter.label


def report(text: str) -> None:
    """Say what's being done, if anyone's watching."""
    reporter = _reporter.get()
    if reporter is not None:
        reporter.func(text)
