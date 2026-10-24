"""Per-stage merging of ``dvc.lock`` and stage run records.

``dvc.lock`` and ``.calkit/stage-runs.json`` are keyed by stage, and each
stage's entry only makes sense whole, so they're merged stage by stage,
never mixing lines from two entries. A stage changed on one side only takes
that side. One changed on both sides needs a choice: ours, theirs, or
neither, in which case it's dropped so the next run reruns it. The choice
decides the stage's run record and its Git-tracked outputs too, so they
agree with its ``dvc.lock`` entry.
"""

from __future__ import annotations

import json
import os
import posixpath
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import git

OURS = "ours"
THEIRS = "theirs"
RERUN = "rerun"
CHOICES = (OURS, THEIRS, RERUN)
# Where a merged entry came from when both sides agree
BOTH = "both"
DRIVER_NAME = "calkit"
# Git's own line-based merge wherever Calkit isn't on PATH, e.g., an editor
# started outside the environment it's installed in, rather than a failed
# driver, which leaves the file as ours with nothing marked
DRIVER_CMD = (
    "if command -v calkit >/dev/null 2>&1; "
    "then calkit merge-driver %O %A %B %P; "
    "else git merge-file -L ours -L base -L theirs %A %O %B; fi"
)
LOCK_FNAME = "dvc.lock"
STAGE_RUNS_FNAME = posixpath.join(".calkit", "stage-runs.json")
# Matching at any depth, for subprojects too
ATTRIBUTES_LINES = [
    f"{LOCK_FNAME} merge={DRIVER_NAME}",
    f"**/{STAGE_RUNS_FNAME} merge={DRIVER_NAME}",
]
# The ref naming the other side of each operation that can conflict
OPERATION_HEADS = {
    "merge": "MERGE_HEAD",
    "rebase": "REBASE_HEAD",
    "cherry-pick": "CHERRY_PICK_HEAD",
}


class MergeError(Exception):
    pass


def _lock_hash(entry: Any) -> str | None:
    import calkit.dvc

    if not isinstance(entry, dict):
        return None
    return calkit.dvc.stage_lock_hash(entry)


def merge_stages(
    base: dict, ours: dict, theirs: dict, choices: dict[str, str]
) -> tuple[dict, dict[str, str], list[str]]:
    """Merge ``dvc.lock`` stage entries three ways, keeping each one whole.

    Entries are compared by what they record running and making, so one
    DVC only rewrote differently counts as unchanged. Returns the merged
    entries, the side each stage's came from, and the stages changed on
    both sides that ``choices`` has no choice for.
    """
    merged = {}
    sides = {}
    conflicts = []
    names = list(ours) + [n for n in theirs if n not in ours]
    names += [n for n in base if n not in names]
    for name in names:
        b, o, t = base.get(name), ours.get(name), theirs.get(name)
        hb, ho, ht = _lock_hash(b), _lock_hash(o), _lock_hash(t)
        if ho == ht:
            side, entry = BOTH, o
        elif hb == ho:
            side, entry = THEIRS, t
        elif hb == ht:
            side, entry = OURS, o
        elif name in choices:
            side = choices[name]
            entry = {OURS: o, THEIRS: t}.get(side)
        else:
            conflicts.append(name)
            continue
        sides[name] = side
        if entry is not None:
            merged[name] = entry
    return merged, sides, conflicts


def merge_runs(
    base: dict,
    ours: dict,
    theirs: dict,
    lock: dict | None = None,
    lock_sides: dict[str, str] | None = None,
) -> tuple[dict, list[str]]:
    """Merge ``stage-runs.json`` records three ways, keeping each one whole.

    Given the merged ``dvc.lock`` entries and the side each came from, a
    stage gets the record of the run that made its entry, and nothing is
    left in conflict. Without them, a stage that ran on both sides is a
    conflict unless both runs made the same entry. Returns the merged
    records and the conflicts.
    """
    lock_sides = lock_sides or {}

    def later(a: dict, b: dict) -> dict:
        return a if str(a.get("end_time")) >= str(b.get("end_time")) else b

    merged = {}
    conflicts = []
    for name in sorted(set(base) | set(ours) | set(theirs)):
        b, o, t = base.get(name), ours.get(name), theirs.get(name)
        side = lock_sides.get(name)
        if side == RERUN:
            continue
        record = None
        decided = False
        if lock is not None and name in lock:
            # The run that made the entry, preferring the side it came from
            target = _lock_hash(lock[name])
            matching = {
                s: r
                for s, r in [(OURS, o), (THEIRS, t)]
                if isinstance(r, dict) and r.get("dvc_lock_hash") == target
            }
            if side in matching:
                record = matching[side]
            elif len(matching) == 2:
                record = later(matching[OURS], matching[THEIRS])
            elif matching:
                record = next(iter(matching.values()))
            elif side in (OURS, THEIRS):
                # Even none, rather than a run that made some other entry
                record = {OURS: o, THEIRS: t}[side]
                decided = True
        if record is None and not decided:
            if o == t:
                record = o
            elif b == o:
                record = t
            elif b == t:
                record = o
            elif not isinstance(o, dict) or not isinstance(t, dict):
                # Deleted on one side and rerun on the other
                record = o or t
            elif lock is not None or (
                o.get("dvc_lock_hash") == t.get("dvc_lock_hash")
            ):
                record = later(o, t)
            else:
                conflicts.append(name)
                continue
        if record is not None:
            merged[name] = record
    return merged, conflicts


def dump_lock(
    meta: dict,
    stages: dict,
    conflicts: dict[str, tuple[dict | None, dict | None]] | None = None,
) -> str:
    """Write ``dvc.lock`` text, with Git conflict markers for ``conflicts``.

    Each conflict is a stage's entries on our side and theirs. Written as
    DVC writes it, in YAML 1.2, which is how it's read.
    """
    import io

    from ruamel.yaml import YAML

    def dump(data: dict, indent: str = "") -> str:
        yaml = YAML()
        yaml.default_flow_style = False
        buf = io.StringIO()
        yaml.dump(data, buf)
        return "".join(
            indent + line + "\n" for line in buf.getvalue().splitlines()
        )

    conflicts = conflicts or {}
    text = dump(meta) if meta else ""
    if not stages and not conflicts:
        return text + "stages: {}\n"
    text += "stages:\n"
    for name, entry in stages.items():
        text += dump({name: entry}, "  ")
    for name, (o, t) in conflicts.items():
        text += "<<<<<<< ours\n"
        if o is not None:
            text += dump({name: o}, "  ")
        text += "=======\n"
        if t is not None:
            text += dump({name: t}, "  ")
        text += ">>>>>>> theirs\n"
    return text


def dump_runs(
    runs: dict,
    conflicts: dict[str, tuple[dict | None, dict | None]] | None = None,
) -> str:
    """Write ``stage-runs.json`` text, with conflict markers for
    ``conflicts``, formatted as ``calkit run`` writes it.
    """
    conflicts = conflicts or {}
    if not conflicts:
        return json.dumps(dict(sorted(runs.items())), indent=2) + "\n"

    def entry(name: str, record: dict | None, comma: bool) -> list[str]:
        if record is None:
            return []
        text = json.dumps({name: record}, indent=2)
        return text.splitlines()[1:-1] + ([","] if comma else [])

    names = sorted(set(runs) | set(conflicts))
    lines = ["{"]
    for i, name in enumerate(names):
        comma = i < len(names) - 1
        if name in conflicts:
            o, t = conflicts[name]
            lines += ["<<<<<<< ours"] + entry(name, o, comma)
            lines += ["======="] + entry(name, t, comma)
            lines.append(">>>>>>> theirs")
        else:
            lines += entry(name, runs[name], comma)
    lines.append("}")
    # Put each comma back on the line it follows
    text = "\n".join(lines).replace("\n,", ",")
    return text + "\n"


def _load_lock(text: str) -> dict:
    import calkit.core

    data = calkit.core._load_yaml_readonly(text) if text.strip() else {}
    if data is None:
        return {}
    if not isinstance(data, dict) or not isinstance(
        data.get("stages", {}), dict
    ):
        raise MergeError("not a dvc.lock")
    return data


def _load_runs(text: str) -> dict:
    data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise MergeError("not a stage-runs.json")
    return data


def run_driver(
    base_fpath: str, ours_fpath: str, theirs_fpath: str, path: str
) -> int:
    """Merge one file as Git's merge driver, writing the result over ours.

    Never prompts, since Git runs drivers from wherever the merge was
    started, e.g., an editor. Returns 0 if merged cleanly and 1 otherwise,
    when the conflicts are left marked for 'calkit fix merge-conflicts'.
    """
    texts = []
    for fpath in [base_fpath, ours_fpath, theirs_fpath]:
        with open(fpath, encoding="utf-8") as f:
            texts.append(f.read())
    try:
        if any("\n<<<<<<< " in "\n" + t for t in texts):
            raise MergeError("already has conflict markers")
        if posixpath.basename(path) == LOCK_FNAME:
            base, ours, theirs = [_load_lock(t) for t in texts]
            bs, os_, ts = [d.get("stages") or {} for d in (base, ours, theirs)]
            merged, _, conflicts = merge_stages(bs, os_, ts, choices={})
            meta = {k: v for k, v in (theirs | ours).items() if k != "stages"}
            out = dump_lock(
                meta,
                merged,
                {n: (os_.get(n), ts.get(n)) for n in conflicts},
            )
        elif path.endswith(STAGE_RUNS_FNAME):
            base, ours, theirs = [_load_runs(t) for t in texts]
            merged, conflicts = merge_runs(base, ours, theirs)
            out = dump_runs(
                merged, {n: (ours.get(n), theirs.get(n)) for n in conflicts}
            )
        else:
            raise MergeError("not a file Calkit merges")
    except Exception as e:
        # Anything this can't read gets Git's own line-based merge
        print(f"Merging {path} line by line: {e}")
        return min(
            subprocess.call(
                ["git", "merge-file"]
                + ["-L", "ours", "-L", "base", "-L", "theirs"]
                + [ours_fpath, base_fpath, theirs_fpath]
            ),
            1,
        )
    with open(ours_fpath, "w", encoding="utf-8") as f:
        f.write(out)
    if conflicts:
        print(
            f"Stages changed on both sides in {path}: {', '.join(conflicts)}"
        )
        return 1
    return 0


def configure_driver(wdir: str | None = None) -> None:
    """Have Git merge these files with Calkit's driver in this clone.

    Both halves are kept per clone, the command in its Git config and which
    files use it in ``info/attributes``, since a driver one has without the
    other does nothing, and Git won't run a command a repository names.
    Does nothing outside a Git repo.
    """

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=wdir, capture_output=True, text=True
        )

    res = git("rev-parse", "--git-path", "info/attributes")
    if res.returncode != 0:
        return
    attributes_path = os.path.join(wdir or "", res.stdout.strip())
    lines = []
    if os.path.isfile(attributes_path):
        with open(attributes_path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    missing = [line for line in ATTRIBUTES_LINES if line not in lines]
    if missing:
        os.makedirs(os.path.dirname(attributes_path), exist_ok=True)
        with open(attributes_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines + missing) + "\n")
    current = git("config", "--local", "--get", f"merge.{DRIVER_NAME}.driver")
    if current.stdout.strip() != DRIVER_CMD:
        git(
            "config",
            "--local",
            f"merge.{DRIVER_NAME}.name",
            "Calkit per-stage",
        )
        git("config", "--local", f"merge.{DRIVER_NAME}.driver", DRIVER_CMD)


def get_operation(repo: git.Repo) -> tuple[str, str] | None:
    """The operation in progress that can conflict, and its other side."""
    for operation, head in OPERATION_HEADS.items():
        if os.path.isfile(os.path.join(repo.git_dir, head)):
            return operation, head
    # A squash merge leaves no ref, only a message naming what it squashed,
    # newest first
    squash_msg = os.path.join(repo.git_dir, "SQUASH_MSG")
    if os.path.isfile(squash_msg):
        with open(squash_msg, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("commit "):
                    return "squash", line.split()[1]
    return None


def get_unmerged_paths(repo: git.Repo) -> list[str]:
    """Paths Git has left in conflict, relative to the repo root."""
    out = repo.git.diff("--name-only", "--diff-filter=U", "-z")
    return sorted({p for p in out.split("\0") if p})


def is_merged_file(path: str) -> bool:
    """Whether Calkit merges this file, given relative to the repo root."""
    return posixpath.basename(path) == LOCK_FNAME or (
        path == STAGE_RUNS_FNAME or path.endswith("/" + STAGE_RUNS_FNAME)
    )


def resolve_conflicts(
    repo: git.Repo,
    choices: dict[str, str] | None = None,
    prefer: str | None = None,
    choose: Callable[[str, dict], str] | None = None,
) -> dict:
    """Resolve the conflicts Git left in the files Calkit merges.

    Each lock directory with either file in conflict is merged again from
    the three commits, so how Git or the driver left its files doesn't
    matter. A stage changed on both sides takes its choice from
    ``choices``, by its name as 'calkit check stage-runs' gives it from
    here, then ``prefer``, then ``choose``, which is passed the stage's name
    and a description of each side. The stages' Git-tracked outputs are
    checked out from the side each was chosen from, and everything resolved
    is staged.

    Returns the operation, the choices made, the files resolved, and the
    paths still in conflict.
    """
    root = repo.working_dir

    def show(ref: str | None, path: str) -> str | None:
        if ref is None:
            return None
        res = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return res.stdout if res.returncode == 0 else None

    def load(
        load_fn: Callable[[str], dict], ref: str | None, path: str
    ) -> dict:
        try:
            return load_fn(show(ref, path) or "")
        except Exception as e:
            raise MergeError(f"Can't read {path} at {ref}: {e}")

    def qualified(lock_dir: str, stage: str) -> str:
        # Relative to here, like 'calkit check stage-runs' names them
        rel = posixpath.relpath(lock_dir or ".", here)
        return stage if rel == "." else f"{rel}/dvc.yaml:{stage}"

    def describe(
        stage: str, ours: dict | None, theirs: dict | None, runs: dict
    ) -> dict:
        info: dict[str, Any] = {}
        for side, entry in [(OURS, ours), (THEIRS, theirs)]:
            if entry is None:
                info[side] = "deleted"
                continue
            run = runs[side].get(stage)
            if isinstance(run, dict) and run.get(
                "dvc_lock_hash"
            ) == _lock_hash(entry):
                info[side] = f"ran {run.get('end_time')}"
            else:
                info[side] = "no record of the run that made it"
        # Which inputs differ between the runs that made each entry
        deps = [
            {
                str(d.get("path")): d
                for d in (e or {}).get("deps") or []
                if isinstance(d, dict)
            }
            for e in (ours, theirs)
        ]
        info["changed_deps"] = sorted(
            p
            for p in set(deps[0]) | set(deps[1])
            if deps[0].get(p) != deps[1].get(p)
        )
        return info

    choices = choices or {}
    operation = get_operation(repo)
    if operation is None:
        raise MergeError("No merge, rebase, or cherry-pick is in progress")
    name, head = operation
    refs = {OURS: "HEAD", THEIRS: head}
    base_refs: list[str | None]
    if name in ("merge", "squash"):
        base_refs = list(repo.git.merge_base("--all", "HEAD", head).split())
    else:
        parents = repo.commit(head).parents
        base_refs = [parents[0].hexsha] if parents else []
    if not base_refs:
        base_refs = [None]
    try:
        cwd = Path(os.getcwd()).resolve()
        here = cwd.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        here = "."
    unmerged = get_unmerged_paths(repo)
    lock_dirs = set()
    for path in unmerged:
        if posixpath.basename(path) == LOCK_FNAME:
            lock_dirs.add(posixpath.dirname(path))
        elif is_merged_file(path):
            lock_dirs.add(path[: -len(STAGE_RUNS_FNAME)].rstrip("/"))
    made: dict[str, str] = {}
    resolved_files = []
    outputs: dict[str, list[str]] = {OURS: [], THEIRS: []}
    for lock_dir in sorted(lock_dirs):
        lock_path = posixpath.join(lock_dir, LOCK_FNAME)
        runs_path = posixpath.join(lock_dir, STAGE_RUNS_FNAME)
        locks = {
            s: load(_load_lock, ref, lock_path) for s, ref in refs.items()
        }
        runs = {s: load(_load_runs, ref, runs_path) for s, ref in refs.items()}
        bases = [load(_load_lock, ref, lock_path) for ref in base_refs]
        runs["base"] = load(_load_runs, base_refs[0], runs_path)
        stages = {s: locks[s].get("stages") or {} for s in locks}
        base_stages = [b.get("stages") or {} for b in bases]
        # With more than one merge base, e.g., after merging each branch
        # into the other, a stage is only merged on its own if every base
        # agrees how
        results = [
            merge_stages(b, stages[OURS], stages[THEIRS], choices={})
            for b in base_stages
        ]
        merged, sides, conflicts = results[0]
        conflicts = list(conflicts)
        for _, other_sides, other_conflicts in results[1:]:
            for stage in list(other_conflicts) + [
                s for s in sides if other_sides.get(s) != sides[s]
            ]:
                if stage not in conflicts:
                    conflicts.append(stage)
        local = {}
        for stage in conflicts:
            q = qualified(lock_dir, stage)
            choice = choices.get(q, prefer)
            if choice is None and choose is not None:
                choice = choose(
                    q,
                    describe(
                        stage,
                        stages[OURS].get(stage),
                        stages[THEIRS].get(stage),
                        runs,
                    ),
                )
            if choice is None:
                raise MergeError(
                    f"Stage '{q}' changed on both sides; choose ours, "
                    "theirs, or rerun"
                )
            made[q] = local[stage] = choice
            sides[stage] = choice
            entry = {OURS: stages[OURS], THEIRS: stages[THEIRS]}.get(
                choice, {}
            ).get(stage)
            if entry is None:
                merged.pop(stage, None)
            else:
                merged[stage] = entry
        meta = {
            k: v
            for k, v in (locks[THEIRS] | locks[OURS]).items()
            if k != "stages"
        }
        merged_runs, _ = merge_runs(
            runs["base"], runs[OURS], runs[THEIRS], merged, sides
        )
        files = []
        if (
            stages[OURS]
            or stages[THEIRS]
            or os.path.isfile(os.path.join(root, lock_path))
        ):
            with open(os.path.join(root, lock_path), "w") as f:
                f.write(dump_lock(meta, merged))
            files.append(lock_path)
        if merged_runs or os.path.isfile(os.path.join(root, runs_path)):
            os.makedirs(
                os.path.dirname(os.path.join(root, runs_path)), exist_ok=True
            )
            with open(os.path.join(root, runs_path), "w") as f:
                f.write(dump_runs(merged_runs))
            files.append(runs_path)
        # Each stage's Git-tracked outputs from the side its entry came
        # from, so they're what the entry says they are
        for side, ref in refs.items():
            dvc_yaml = load(
                _load_lock, ref, posixpath.join(lock_dir, "dvc.yaml")
            )
            for stage, entry in stages[side].items():
                # A stage to rerun keeps ours until it's rerun
                if sides.get(stage) != side and not (
                    side == OURS and sides.get(stage) == RERUN
                ):
                    continue
                dvc_stage = (dvc_yaml.get("stages") or {}).get(
                    stage.split("@")[0]
                )
                wdir = (
                    dvc_stage.get("wdir") or ""
                    if isinstance(dvc_stage, dict)
                    else ""
                )
                for out in entry.get("outs") or []:
                    if isinstance(out, dict) and out.get("path"):
                        outputs[side].append(
                            posixpath.normpath(
                                posixpath.join(lock_dir, wdir, out["path"])
                            )
                        )
        if files:
            repo.git.add("--", *files)
        resolved_files += files
    for side, paths in outputs.items():
        if not paths:
            continue
        # Only what Git has that isn't already that side's, so DVC-tracked
        # outputs and ones the merge already took from it, with any edits
        # since, are left alone. Files only the other side made are removed.
        differing = [
            p
            for p in repo.git.diff(
                "--cached",
                "--name-only",
                "-z",
                refs[side],
                "--",
                *sorted(set(paths)),
            ).split("\0")
            if p
        ]
        if differing:
            repo.git.restore(
                f"--source={refs[side]}",
                "--staged",
                "--worktree",
                "--",
                *differing,
            )
            resolved_files += [p for p in differing if p in unmerged]
    return {
        "operation": name,
        "choices": made,
        "resolved": resolved_files,
        "unmerged": get_unmerged_paths(repo),
    }
