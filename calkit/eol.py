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
import re
import subprocess
from dataclasses import dataclass
from dataclasses import field as dataclass_field

#: What to do about files whose line endings aren't pinned
FIX = "run `calkit fix line-endings` and commit .gitattributes"

#: Marks the block of rules :func:`pin` writes
MARKER = "calkit line endings"

#: The rules :func:`pin` writes, first in ``.gitattributes`` so a project's
#: own rules after them win. ``text=auto`` leaves binary files alone, and
#: files committed with CRLF, which are checked out the same everywhere
#: already, so pinning makes no committed file read as changed.
RULES = [
    "# Check out text files with LF everywhere, including Windows, so the",
    "# files the pipeline hashes are the same on every machine",
    "* text=auto eol=lf",
    "# cmd.exe can misread batch files with LF",
    "*.bat text=auto eol=crlf",
    "*.cmd text=auto eol=crlf",
]


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
    subs = submodules(wdir)
    paths = [posixpath.normpath(p).rstrip("/") or "." for p in paths]
    # Git refuses a path inside a submodule
    top_paths = [
        p for p in paths if not any(p.startswith(sm + "/") for sm in subs)
    ]
    out = ""
    try:
        if top_paths:
            out = subprocess.run(
                ["git", "ls-files", "--eol", "-z", "--", *top_paths],
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
    # Git lists a submodule as one entry, so what's in it is asked of its
    # own repo, whose attributes are its own
    for sm in subs:
        sub_paths = []
        for path in paths:
            if path in (".", sm) or sm.startswith(path + "/"):
                sub_paths = ["."]
                break
            if path.startswith(sm + "/"):
                sub_paths.append(path[len(sm) + 1 :])
        for f in list_tracked_eol(sub_paths, wdir=os.path.join(wdir, sm)):
            f.path = f"{sm}/{f.path}"
            res.append(f)
    return res


def submodules(wdir: str = ".") -> list[str]:
    """The paths, relative to ``wdir``, of the checked-out submodules
    under it."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-s", "-z"],
            cwd=wdir,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.CalledProcessError):
        return []
    res = []
    for entry in out.split("\0"):
        info, sep, path = entry.partition("\t")
        if sep and info.startswith("160000 "):
            if os.path.exists(os.path.join(wdir, path, ".git")):
                res.append(path)
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


@dataclass
class PinResult:
    """What :func:`pin` changed."""

    #: Whether ``.gitattributes`` was written
    wrote_gitattributes: bool = False
    #: Working-tree files rewritten to the line endings Git checks out
    converted: list[str] = dataclass_field(default_factory=list)
    #: Submodules set to check files out as committed, in this clone only
    submodules: list[str] = dataclass_field(default_factory=list)


def pins_all(wdir: str = ".") -> bool:
    """Whether ``wdir``'s ``.gitattributes`` already sets ``eol`` for every
    file, with Calkit's block or a ``*`` rule of its own."""
    path = os.path.join(wdir, ".gitattributes")
    if not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if (
                len(parts) > 1
                and parts[0] == "*"
                and any(p.startswith("eol=") for p in parts[1:])
            ):
                return True
    return False


def write_rules(wdir: str = ".") -> bool:
    """Put :data:`RULES` first in ``wdir``'s ``.gitattributes``, unless it
    pins every file already. Returns whether the file was written."""
    path = os.path.join(wdir, ".gitattributes")
    begin = f"# >>> {MARKER} (managed by calkit) >>>"
    end = f"# <<< {MARKER} <<<"
    block = "\n".join([begin, *RULES, end])
    existing = ""
    if os.path.isfile(path):
        # Read with universal newlines and written with LF, as the rules
        # it gets say it should be
        with open(path, encoding="utf-8") as f:
            existing = f.read()
    block_re = re.compile(
        re.escape(begin) + r".*?" + re.escape(end), flags=re.DOTALL
    )
    if block_re.search(existing):
        updated = block_re.sub(lambda _: block, existing)
    elif pins_all(wdir):
        return False
    else:
        # First, since the last rule that matches a file wins
        updated = block + "\n" + ("\n" + existing if existing else "")
    if updated == existing:
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(updated)
    return True


def convert_worktree(wdir: str = ".", as_committed: bool = False) -> list[str]:
    """Rewrite the Git-tracked files under ``wdir`` whose line endings on
    disk aren't what Git would check out now, e.g., CRLF from a checkout
    made before an ``eol=lf`` rule, and return their paths.

    With ``as_committed``, a text file without an ``eol`` attribute is
    expected as Git has it, as when ``core.autocrlf`` is off.

    Git itself only rewrites a file it checks out again, and skips one whose
    size and time haven't changed. Until then the file reads as modified,
    with nothing in its diff, and hashes differently from other machines.
    Converting in place keeps any uncommitted changes. Only files Git has
    with LF are touched, since one committed with CRLF is checked out as it
    is.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "--eol", "-z"],
            cwd=wdir,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.CalledProcessError):
        return []
    converted = []
    for entry in out.split("\0"):
        info, sep, path = entry.partition("\t")
        fields = info.split()
        if not sep or len(fields) < 3:
            continue
        tracked = TrackedEol(
            path=path,
            index=fields[0].removeprefix("i/"),
            worktree=fields[1].removeprefix("w/"),
            attr=" ".join(fields[2:]).removeprefix("attr/"),
        )
        eols = [
            t.removeprefix("eol=")
            for t in tracked.attr.split()
            if t.startswith("eol=")
        ]
        want = eols[-1] if eols else None
        if want is None and as_committed:
            want = None if "-text" in tracked.attr.split() else "lf"
        if tracked.index != "lf" or want not in ("lf", "crlf"):
            continue
        if tracked.worktree not in ("lf", "crlf", "mixed"):
            continue
        if tracked.worktree == want:
            continue
        fpath = os.path.join(wdir, path)
        if os.path.islink(fpath) or not os.path.isfile(fpath):
            continue
        with open(fpath, "rb") as f:
            data = f.read()
        new = data.replace(b"\r\n", b"\n")
        if want == "crlf":
            new = new.replace(b"\n", b"\r\n")
        if new == data:
            continue
        with open(fpath, "wb") as f:
            f.write(new)
        converted.append(path)
    _refresh_index(converted, wdir=wdir)
    return converted


def _refresh_index(paths: list[str], wdir: str = ".") -> None:
    """Record the new size and time of rewritten files that match what's
    staged, which Git otherwise shows as modified, since it doesn't compare
    content when a file's size has changed. Files with uncommitted changes
    are left as they are, so nothing new is staged."""
    if not paths:
        return
    try:
        staged = {}
        out = subprocess.run(
            ["git", "ls-files", "-s", "-z", "--", *paths],
            cwd=wdir,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8", errors="replace")
        for entry in out.split("\0"):
            info, sep, path = entry.partition("\t")
            if sep:
                staged[path] = info.split()[1]
        hashes = (
            subprocess.run(
                ["git", "hash-object", "--", *paths],
                cwd=wdir,
                capture_output=True,
                check=True,
            )
            .stdout.decode()
            .split()
        )
        same = [p for p, h in zip(paths, hashes) if staged.get(p) == h]
        if same:
            subprocess.run(
                ["git", "update-index", "-q", "--", *same],
                cwd=wdir,
                capture_output=True,
                check=True,
            )
    except (OSError, subprocess.CalledProcessError, IndexError):
        pass


def pin(wdir: str = ".") -> PinResult:
    """Pin line endings for everything under ``wdir`` and bring this
    checkout in line with the rules.

    This changes no file's committed content, and on a checkout that
    already matches, e.g., most on macOS and Linux, nothing on disk but
    ``.gitattributes``.
    """
    res = PinResult(wrote_gitattributes=write_rules(wdir))
    res.converted = convert_worktree(wdir)
    sub = pin_submodules(wdir)
    res.converted += sub.converted
    res.submodules = sub.submodules
    return res


def pin_submodules(wdir: str = ".") -> PinResult:
    """Check the files of the submodules under ``wdir`` out as committed,
    and bring this checkout in line, for those that don't pin their line
    endings themselves.

    A submodule is its own repo, so the project's ``.gitattributes`` doesn't
    reach it, and a rule committed to it would be a change to someone else's
    project. Instead, ``core.autocrlf`` is turned off in this clone of it,
    which leaves its own attributes in charge, unlike a rule in
    ``info/attributes``, which would outrank them. Its files then have the
    bytes it committed, on every platform.
    """
    res = PinResult()
    for sm in submodules(wdir):
        subdir = os.path.join(wdir, sm)
        if not pins_all(subdir):
            try:
                current = subprocess.run(
                    ["git", "config", "--local", "core.autocrlf"],
                    cwd=subdir,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                if current != "false":
                    subprocess.run(
                        ["git", "config", "--local", "core.autocrlf", "false"],
                        cwd=subdir,
                        capture_output=True,
                        check=True,
                    )
                    res.submodules.append(sm)
            except (OSError, subprocess.CalledProcessError):
                continue
        res.converted += [
            f"{sm}/{p}"
            for p in convert_worktree(
                subdir, as_committed=not pins_all(subdir)
            )
        ]
        nested = pin_submodules(subdir)
        res.converted += [f"{sm}/{p}" for p in nested.converted]
        res.submodules += [f"{sm}/{p}" for p in nested.submodules]
    return res
