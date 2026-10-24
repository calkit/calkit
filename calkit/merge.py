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
DRIVER_CMD = "calkit merge-driver %O %A %B %P"
LOCK_FNAME = "dvc.lock"
STAGE_RUNS_FNAME = posixpath.join(".calkit", "stage-runs.json")
ATTRIBUTES_LINES = [
    f"/{LOCK_FNAME} merge={DRIVER_NAME}",
    f"/{STAGE_RUNS_FNAME} merge={DRIVER_NAME}",
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
                record = {OURS: o, THEIRS: t}[side]
        if record is None:
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


def _dump_lock_stage(name: str, entry: dict) -> str:
    import yaml

    text = yaml.safe_dump(
        {name: entry}, sort_keys=False, width=float("inf")
    ).rstrip("\n")
    return "\n".join("  " + line for line in text.splitlines())


def dump_lock(
    meta: dict,
    stages: dict,
    conflicts: dict[str, tuple[dict | None, dict | None]] | None = None,
) -> str:
    """Write ``dvc.lock`` text, with Git conflict markers for ``conflicts``.

    Each conflict is a stage's entries on our side and theirs.
    """
    import yaml

    conflicts = conflicts or {}
    text = yaml.safe_dump(meta, sort_keys=False) if meta else ""
    if not stages and not conflicts:
        return text + "stages: {}\n"
    lines = ["stages:"]
    for name, entry in stages.items():
        lines.append(_dump_lock_stage(name, entry))
    for name, (o, t) in conflicts.items():
        lines.append("<<<<<<< ours")
        if o is not None:
            lines.append(_dump_lock_stage(name, o))
        lines.append("=======")
        if t is not None:
            lines.append(_dump_lock_stage(name, t))
        lines.append(">>>>>>> theirs")
    return text + "\n".join(lines) + "\n"


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
                ["git", "merge-file", ours_fpath, base_fpath, theirs_fpath]
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


def ensure_driver(wdir: str | None = None) -> None:
    """Have Git merge these files with Calkit's driver here.

    ``.gitattributes`` says which files use it, and is committed. Which
    command it runs has to be set per clone, since Git won't run a command
    a repository names.
    """
    import calkit.pipeline

    calkit.pipeline._write_managed_gitignore_block(
        os.path.join(wdir, ".gitattributes") if wdir else ".gitattributes",
        marker="calkit merge driver",
        lines=ATTRIBUTES_LINES,
    )
    configure_driver(wdir=wdir)


def configure_driver(wdir: str | None = None) -> None:
    """Set the command for Calkit's merge driver in this clone's Git config.

    Does nothing outside a Git repo.
    """
    for key, value in [
        (f"merge.{DRIVER_NAME}.name", "Calkit per-stage merge"),
        (f"merge.{DRIVER_NAME}.driver", DRIVER_CMD),
    ]:
        current = subprocess.run(
            ["git", "config", "--local", "--get", key],
            cwd=wdir,
            capture_output=True,
            text=True,
        )
        if current.returncode == 0 and current.stdout.strip() == value:
            continue
        subprocess.run(
            ["git", "config", "--local", key, value],
            cwd=wdir,
            capture_output=True,
        )


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
    ``choices``, by its name as 'calkit check stage-runs' gives it, then
    ``prefer``, then ``choose``, which is passed the stage's name and a
    description of each side. The stages' Git-tracked outputs are checked
    out from the side each was chosen from, and everything resolved is
    staged.

    Returns the choices made, the files resolved, and the paths still in
    conflict.
    """
    choices = choices or {}
    operation = get_operation(repo)
    if operation is None:
        raise MergeError("No merge, rebase, or cherry-pick is in progress")
    name, head = operation
    refs = {OURS: "HEAD", THEIRS: head}
    if name in ("merge", "squash"):
        bases = repo.git.merge_base("--all", "HEAD", head).split()
        base_ref = bases[0] if bases else None
    else:
        parents = repo.commit(head).parents
        base_ref = parents[0].hexsha if parents else None
    unmerged = get_unmerged_paths(repo)
    lock_dirs = set()
    for path in unmerged:
        if posixpath.basename(path) == LOCK_FNAME:
            lock_dirs.add(posixpath.dirname(path))
        elif is_merged_file(path):
            lock_dirs.add(path[: -len(STAGE_RUNS_FNAME)].rstrip("/"))

    def show(ref: str | None, path: str) -> str | None:
        if ref is None:
            return None
        res = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=repo.working_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return res.stdout if res.returncode == 0 else None

    def qualified(lock_dir: str, stage: str) -> str:
        return f"{lock_dir}/dvc.yaml:{stage}" if lock_dir else stage

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
        changed = sorted(
            p
            for p in set(deps[0]) | set(deps[1])
            if deps[0].get(p) != deps[1].get(p)
        )
        info["changed_deps"] = changed
        return info

    made: dict[str, str] = {}
    resolved_files = []
    outputs: dict[str, list[str]] = {OURS: [], THEIRS: []}
    for lock_dir in sorted(lock_dirs):
        lock_path = posixpath.join(lock_dir, LOCK_FNAME)
        runs_path = posixpath.join(lock_dir, STAGE_RUNS_FNAME)
        locks = {}
        runs = {}
        for side, ref in [("base", base_ref)] + list(refs.items()):
            locks[side] = _load_lock(show(ref, lock_path) or "")
            runs[side] = _load_runs(show(ref, runs_path) or "")
        stages = {s: locks[s].get("stages") or {} for s in locks}
        merged, sides, conflicts = merge_stages(
            stages["base"], stages[OURS], stages[THEIRS], choices={}
        )
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
        if conflicts:
            merged, sides, _ = merge_stages(
                stages["base"], stages[OURS], stages[THEIRS], choices=local
            )
        meta = {
            k: v
            for k, v in (locks[THEIRS] | locks[OURS]).items()
            if k != "stages"
        }
        merged_runs, _ = merge_runs(
            runs["base"], runs[OURS], runs[THEIRS], merged, sides
        )
        root = repo.working_dir
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
            dvc_yaml = _load_lock(
                show(ref, posixpath.join(lock_dir, "dvc.yaml")) or ""
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
        # Only those in Git there, since DVC-tracked outputs aren't
        tracked = [
            p
            for p in sorted(set(paths))
            if repo.git.ls_tree("-r", "--name-only", refs[side], "--", p)
        ]
        if tracked:
            repo.git.checkout(refs[side], "--", *tracked)
            resolved_files += [
                p
                for p in tracked
                if any(u == p or u.startswith(p + "/") for u in unmerged)
            ]
    return {
        "operation": name,
        "choices": made,
        "resolved": resolved_files,
        "unmerged": get_unmerged_paths(repo),
    }
