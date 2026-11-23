"""Saying what's being done, e.g., on ``calkit run``'s spinner.

Whoever shows progress sets a reporter around the work, and code deep
inside it reports through that without being passed it, e.g., an
environment check behind a CLI command that takes no such argument.
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import IO

#: How much of what was printed behind a spinner is shown when the work
#: fails
TAIL_LINES = 20


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


@contextlib.contextmanager
def capture_output(log: IO[str]) -> Iterator[None]:
    """Send what's printed inside this block to ``log``, including by
    subprocesses, which write to the terminal directly, so the redirect is
    done where they inherit it from as well as Python's. Nobody can see a
    prompt meanwhile, so input is from devnull, which answers one rather
    than hangs."""
    from contextlib import redirect_stderr, redirect_stdout

    sys.stdout.flush()
    sys.stderr.flush()
    saved_stdin = sys.stdin
    with (
        open(os.devnull) as null,
        redirect_stdout(log),
        redirect_stderr(log),
    ):
        sys.stdin = null
        try:
            if sys.platform == "win32":
                # Replacing descriptors 0-2 would close the console handles
                # Click uses, so only the standard handles that subprocesses
                # inherit are swapped
                import ctypes
                import msvcrt
                from ctypes import wintypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
                kernel32.GetStdHandle.restype = wintypes.HANDLE
                kernel32.SetStdHandle.argtypes = [
                    wintypes.DWORD,
                    wintypes.HANDLE,
                ]
                kernel32.SetStdHandle.restype = wintypes.BOOL
                # STD_INPUT_HANDLE, STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
                std_ids = [-10, -11, -12]
                handles = [
                    msvcrt.get_osfhandle(f.fileno()) for f in (null, log, log)
                ]
                saved = [kernel32.GetStdHandle(i) for i in std_ids]
                try:
                    for i, h in zip(std_ids, handles):
                        kernel32.SetStdHandle(i, h)
                    yield
                finally:
                    for i, h in zip(std_ids, saved):
                        kernel32.SetStdHandle(i, h)
            else:
                saved = [os.dup(fd) for fd in (0, 1, 2)]
                try:
                    for fd, f in zip((0, 1, 2), (null, log, log)):
                        os.dup2(f.fileno(), fd)
                    yield
                finally:
                    for fd, saved_fd in enumerate(saved):
                        os.dup2(saved_fd, fd)
                        os.close(saved_fd)
        finally:
            sys.stdin = saved_stdin


def tail(log: IO[str], n: int = TAIL_LINES) -> str:
    """The last ``n`` lines written to ``log``."""
    log.flush()
    log.seek(0)
    return "".join(log.readlines()[-n:])


@contextlib.contextmanager
def spinner(
    text: str, label: str | None = None, show: bool = True
) -> Iterator[None]:
    """Show ``text`` on a spinner, changed to what's reported inside this
    block, e.g., each step of creating an environment, and hide what's
    printed meanwhile. If the block fails, the end of that is shown.

    Nothing changes without ``show``, e.g., with ``--verbose``, when
    stderr isn't a terminal, or when a spinner is already showing, e.g.,
    ``calkit run``'s.
    """
    import tempfile

    from calkit.core import is_mintty

    mintty = is_mintty(sys.stderr)
    if not show or active() or not (sys.stderr.isatty() or mintty):
        yield
        return
    from rich.console import Console

    # Its own copy of the terminal, since stderr is redirected under it.
    # mintty takes ANSI and UTF-8, though it isn't a console.
    console = Console(
        file=os.fdopen(os.dup(2), "w", encoding="utf-8" if mintty else None),
        force_terminal=mintty or None,
        legacy_windows=False if mintty else None,
    )
    status = console.status(text)
    with tempfile.TemporaryFile(
        "w+", encoding="utf-8", errors="replace"
    ) as log:
        status.start()
        try:
            with reporting(status.update, label=label), capture_output(log):
                yield
        except BaseException as e:
            status.stop()
            # A clean exit, e.g., typer.Exit(0), has nothing to show
            code = getattr(e, "exit_code", getattr(e, "code", 1))
            if code not in (0, None):
                if output := tail(log):
                    sys.stderr.write(output)
                    if not output.endswith("\n"):
                        sys.stderr.write("\n")
                sys.stderr.write(
                    "Rerun with --verbose for all of the output\n"
                )
                sys.stderr.flush()
            raise
        finally:
            status.stop()
            console.file.close()
