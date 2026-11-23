"""Line endings of the files a pipeline hashes, which Git can rewrite.

Git for Windows checks text files out with CRLF by default
(``core.autocrlf``), and DVC hashes the working tree, so a file committed
with LF hashes differently there than it did wherever ``dvc.lock`` was
written. A stage that depends on it, or writes it, then reads as out of date
on Windows and nowhere else. An ``eol`` attribute in ``.gitattributes``
outranks ``core.autocrlf``, which is what pins a file's line endings on
every platform.
"""

import os
import posixpath
import subprocess
from dataclasses import dataclass

#: What to do about files whose line endings aren't pinned
FIX = (
    "add `* text=auto eol=lf` to .gitattributes, run "
    "`git add --renormalize .`, and commit"
)


@dataclass
class TrackedEol:
    """How Git stores a tracked file's line endings, and how it checks it
    out, as ``git ls-files --eol`` reports them."""

    path: str
    #: In the index: ``lf``, ``crlf``, ``mixed``, ``none`` (no line
    #: breaks), or ``-text`` (binary)
    index: str
    #: In the working tree, likewise, or empty if the file isn't there
    worktree: str
    #: The ``text`` and ``eol`` attributes that apply, e.g., ``text eol=lf``
    attr: str

    @property
    def pinned(self) -> bool:
        """Whether Git checks it out the same way on every platform."""
        tokens = self.attr.split()
        return any(t.startswith("eol=") for t in tokens) or "-text" in tokens

    @property
    def at_risk(self) -> bool:
        """Whether a checkout on Windows would have other bytes than one on
        macOS or Linux."""
        return self.index in ("lf", "mixed") and not self.pinned

    @property
    def rewritten(self) -> bool:
        """Whether this checkout has CRLF where Git has LF, so it hashes
        differently from a checkout on macOS or Linux."""
        return self.index == "lf" and self.worktree == "crlf"


def list_tracked_eol(paths: list[str], wdir: str = ".") -> list[TrackedEol]:
    """Report the line endings of the Git-tracked files at or under
    ``paths``, relative to ``wdir``, in one call to Git.

    Paths Git doesn't track, e.g., outputs kept in DVC, are left out, as is
    everything when ``wdir`` isn't in a Git repo.
    """
    if not paths:
        return []
    try:
        out = subprocess.run(
            ["git", "ls-files", "--eol", "-z", "--", *paths],
            cwd=wdir,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.CalledProcessError):
        return []
    res = []
    for entry in out.split("\0"):
        # <index> <worktree> attr/<attrs>, padded with spaces, then a tab
        info, sep, path = entry.partition("\t")
        if not sep:
            continue
        fields = info.split()
        if len(fields) < 3:
            continue
        res.append(
            TrackedEol(
                path=path,
                index=fields[0].removeprefix("i/"),
                worktree=fields[1].removeprefix("w/"),
                attr=" ".join(fields[2:]).removeprefix("attr/"),
            )
        )
    return res


def pipeline_paths(wdir: str = ".") -> list[str]:
    """The paths the compiled pipeline in ``wdir`` hashes, its stages'
    dependencies and outputs, relative to ``wdir``."""
    import calkit.dvc

    paths = []
    for stage in (
        calkit.dvc.read_pipeline(wdir=wdir).get("stages") or {}
    ).values():
        if not isinstance(stage, dict):
            continue
        base = stage.get("wdir") or ""
        for field in ("deps", "outs"):
            for item in stage.get(field) or []:
                path = (
                    item if isinstance(item, str) else next(iter(item), None)
                )
                # A templated path names no file until DVC expands it
                if not isinstance(path, str) or "${" in path:
                    continue
                path = posixpath.normpath(posixpath.join(base, path))
                if path.startswith("../") or os.path.isabs(path):
                    continue
                paths.append(path)
    return list(dict.fromkeys(paths))


def check_pipeline(wdir: str = ".") -> list[TrackedEol]:
    """The Git-tracked text files the pipeline hashes whose line endings
    Git doesn't pin, or that this checkout has rewritten."""
    files = list_tracked_eol(pipeline_paths(wdir=wdir), wdir=wdir)
    return [f for f in files if f.at_risk or f.rewritten]


def summarize(paths: list[str], n: int = 3) -> str:
    """A few paths, and how many more there are."""
    shown = ", ".join(paths[:n])
    if len(paths) > n:
        shown += f", and {len(paths) - n} more"
    return shown
