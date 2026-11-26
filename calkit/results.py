"""Functionality for working with the project's results.

A result is an object-like file---JSON, TOML, or YAML---whose keys are what
gets cited, the way a question's value evidence names one.

What a change did to results, e.g., in a pull request, is summarized here
too, for a reviewer: stages that reran, changed values, figures, and tables,
and the questions citing them.
"""

from __future__ import annotations

import os
from typing import Any

# Extensions whose keys can be read, which are the ones a question's
# value evidence can cite
EXTENSIONS = (".json", ".toml", ".yaml", ".yml")


def list_results(
    ck_info: dict | None = None,
    wdir: str | None = None,
    declared_only: bool = False,
    status: bool = False,
) -> list[dict]:
    """The project's results, declared and auto-detected.

    Each entry carries its producing stage when the pipeline writes it and,
    with ``status``, whether that stage is up to date, which needs DVC and
    so costs a pipeline status check.
    """
    import calkit.pipeline

    return calkit.pipeline.list_artifacts(
        "results",
        ck_info=ck_info,
        wdir=wdir,
        declared_only=declared_only,
        status=status,
        pending_extensions=EXTENSIONS,
    )


def load_result(path: str, content: bytes | None = None) -> Any:
    """A result file's contents, loaded.

    Parsed by the same reader a question's value evidence uses, so what
    can be shown here and what can be cited are the same thing.
    ``content`` loads the bytes given instead of the file at ``path``,
    which is how a result is read at a Git ref.
    """
    from calkit.questions import parse_evidence_text

    suffix = os.path.splitext(path)[1].lower()
    if suffix not in EXTENSIONS:
        from calkit.detect import TABLE_EXTENSIONS

        # A tabular file is listed as a result too, but its keys are
        # columns, so it's read as a table
        hint = (
            f"; read it with 'calkit show table {path}'"
            if suffix in TABLE_EXTENSIONS
            else "; results are " + ", ".join(EXTENSIONS)
        )
        raise ValueError(f"Can't read a result from a '{suffix}' file" + hint)
    if content is None:
        with open(path, "rb") as f:
            content = f.read()
    return parse_evidence_text(content.decode("utf-8-sig", "replace"), path)


def flatten(
    value: Any, depth: int | None = None, prefix: str = ""
) -> list[tuple[str, Any]]:
    """A result's values as ``(key, value)`` pairs, with dotted keys the
    way a citation names them.

    A list of scalars is a leaf, since its elements are read together; a
    list of objects is indexed into. ``depth`` stops flattening there.
    """
    if depth is not None and depth <= 0:
        return [(prefix, value)]
    if isinstance(value, dict):
        children = [(str(k), v) for k, v in value.items()]
    elif isinstance(value, list) and any(
        isinstance(item, (dict, list)) for item in value
    ):
        children = [(str(i), v) for i, v in enumerate(value)]
    else:
        return [(prefix, value)]
    out: list[tuple[str, Any]] = []
    for key, item in children:
        child = f"{prefix}.{key}" if prefix else key
        out += flatten(item, None if depth is None else depth - 1, child)
    return out


def read_result(
    path: str,
    content: bytes | None = None,
    keys: list[str] | None = None,
    depth: int | None = None,
) -> dict[str, Any]:
    """Read a result as the flat list of keys a citation would name.

    Keys are dotted paths, resolved the way a question's value evidence
    resolves them, so what's printed here is what an answer can cite.
    ``depth`` stops flattening and shows the rest of a value as JSON,
    which keeps a deeply nested file readable.
    """
    import json

    from calkit.questions import resolve_key

    def format_value(value: Any) -> str:
        if isinstance(value, bool) or value is None:
            return json.dumps(value)
        if isinstance(value, (int, float, str)):
            return str(value)
        # A container that flattening stopped at, kept on one line
        return json.dumps(value, default=str)

    data = load_result(path, content=content)
    selected: list[tuple[str, Any]] = []
    if keys:
        for key in keys:
            try:
                selected.append((key, resolve_key(data, key)))
            except KeyError:
                raise ValueError(
                    f"No key '{key}' in {path}; it has "
                    + ", ".join(k for k, _ in flatten(data, depth=1))
                ) from None
    else:
        selected.append(("", data))
    items: list[dict] = []
    for prefix, value in selected:
        for key, leaf in flatten(value, depth=depth):
            full = ".".join(p for p in (prefix, key) if p)
            items.append(
                {
                    "key": full or prefix,
                    "value": format_value(leaf),
                    "type": type(leaf).__name__,
                }
            )
    return {"items": items, "n_keys": len(items)}


def get_changes(
    base: str | None = None,
    to: str | None = None,
    wdir: str | None = None,
    check_pipeline: bool = True,
) -> dict:
    """What a change did to a project's results, between two revisions.

    Compares ``base``, by default where the current branch left the
    default one, to ``to``, by default the working tree. Stages come from
    ``dvc.lock`` and ``.calkit/stage-runs.json``. Changed outputs are the
    ones ``dvc.lock`` records a different hash for, plus Git-tracked
    artifacts and evidence edited by hand. A DVC-stored output is only
    read if it's in the local cache, never pulled. ``check_pipeline``
    asks DVC which stages are stale, only for the working tree.
    """
    import json
    import posixpath
    from pathlib import Path

    import calkit
    import calkit.dvc
    import calkit.git
    from calkit.detect import FIGURE_EXTENSIONS, TABLE_EXTENSIONS
    from calkit.models.pipeline import LatexStage
    from calkit.questions import (
        _load_calkit_yaml_text,
        _values_equal,
        named_keys,
        resolve_key,
    )

    def get_root_path(path: str) -> str:
        # Git names paths from the repo's root
        return posixpath.normpath(posixpath.join(prefix, path))

    def read_git(ref: str | None, path: str) -> bytes | None:
        if ref is not None:
            return calkit.git.read_at_ref(repo, ref, get_root_path(path))
        try:
            with open(os.path.join(project_dir, path), "rb") as f:
                return f.read()
        except OSError:
            return None

    def read_cache(md5: str | None) -> bytes | None:
        if not md5:
            return None
        try:
            with open(os.path.join(cache_dir, md5[:2], md5[2:]), "rb") as f:
                return f.read()
        except OSError:
            return None

    def load(ref: str | None, path: str) -> dict:
        content = read_git(ref, path)
        if content is None:
            return {}
        text = content.decode("utf-8", "replace")
        try:
            loaded = (
                json.loads(text)
                if path.endswith(".json")
                else _load_calkit_yaml_text(text)
            )
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def list_git_paths(*args: str) -> list[str]:
        try:
            out = str(getattr(repo.git, args[0])(*args[1:], "--", prefix))
        except Exception:
            return []
        return [
            posixpath.relpath(p, prefix) for p in out.splitlines() if p.strip()
        ]

    def get_outs(lock: dict, stage_wdirs: dict) -> dict[str, tuple]:
        outs = {}
        for name, stage in (lock.get("stages") or {}).items():
            stage_wdir = stage_wdirs.get(str(name).split("@")[0], "")
            for out in (stage or {}).get("outs") or []:
                if isinstance(out, dict) and out.get("path"):
                    path = posixpath.normpath(
                        posixpath.join(
                            stage_wdir, Path(str(out["path"])).as_posix()
                        )
                    )
                    outs[path] = (out.get("md5") or None, str(name))
        return outs

    def read_manifest(md5: str | None) -> dict[str, str] | None:
        # A directory's files and their hashes, from its .dir in the cache
        if md5 is None:
            return {}
        content = read_cache(md5) if md5.endswith(".dir") else None
        if content is None:
            return None
        try:
            entries = json.loads(content)
            return {str(e["relpath"]): str(e["md5"]) for e in entries}
        except Exception:
            return None

    def get_kind(path: str) -> str:
        # A declared result is kept apart from other files by its type
        for kind in ("figure", "table"):
            for declared in declared_paths[kind]:
                if path == declared or path.startswith(declared + "/"):
                    return kind
        if path in other_paths:
            return "other"
        if path in cell_output_kinds:
            return cell_output_kinds[path]
        ext = posixpath.splitext(path)[1].lower()
        if ext in EXTENSIONS:
            return "value"
        if ext in FIGURE_EXTENSIONS:
            return "figure"
        if ext in TABLE_EXTENSIONS:
            return "table"
        return "other"

    def get_value_changes(old: Any, new: Any) -> list[dict]:
        old_items = dict(flatten(old))
        new_items = dict(flatten(new))
        changes = []
        for key in list(new_items) + [
            k for k in old_items if k not in new_items
        ]:
            if key in old_items and key in new_items:
                if _values_equal(old_items[key], new_items[key]):
                    continue
                change = "modified"
            else:
                change = "added" if key in new_items else "removed"
            changes.append(
                {
                    "key": key,
                    "old": old_items.get(key),
                    "new": new_items.get(key),
                    "change": change,
                    "relative_change": get_relative_change(
                        old_items.get(key), new_items.get(key)
                    ),
                }
            )
        return changes

    project_dir = os.path.abspath(wdir or os.getcwd())
    repo = calkit.git.get_repo(project_dir)
    root = str(repo.working_dir)
    prefix = Path(os.path.relpath(project_dir, root)).as_posix()
    cache_dir = os.path.join(project_dir, ".dvc", "cache", "files", "md5")
    # Revisions, resolved to commits
    to_sha = None
    if to is not None:
        to_sha = calkit.git.resolve_ref(repo, to)
        if to_sha is None:
            raise ValueError(f"Can't find revision '{to}'")
    base_label = None
    if base is None:
        default_branch = calkit.git.get_default_branch(repo)
        branch_sha = (
            calkit.git.resolve_ref(repo, default_branch)
            if default_branch
            else None
        )
        if branch_sha is None:
            raise ValueError("Can't find default branch; pass a base")
        merge_base = None
        for attempt in range(2):
            try:
                merge_base = str(
                    repo.git.merge_base(branch_sha, to_sha or "HEAD")
                ).strip()
                break
            except Exception:
                # A CI checkout is usually shallow, leaving no common
                # history until it's fetched
                if attempt == 0:
                    try:
                        repo.git.fetch("--unshallow", "origin")
                    except Exception:
                        break
        if not merge_base:
            raise ValueError(
                f"Can't find merge base with {default_branch}; fetch its "
                "history or pass a base"
            )
        base_sha = merge_base
        base_label = f"merge base with {default_branch}"
    else:
        resolved = calkit.git.resolve_ref(repo, base)
        if resolved is None:
            raise ValueError(f"Can't find revision '{base}'")
        base_sha = resolved
    # Each side's project, pipeline record, and stage runs
    base_info = load(base_sha, "calkit.yaml")
    to_info = load(to_sha, "calkit.yaml")
    stage_wdirs = {}
    for info in (base_info, to_info):
        for name, st in (
            (info.get("pipeline") or {}).get("stages") or {}
        ).items():
            if isinstance(st, dict):
                stage_wdirs[str(name)] = str(st.get("wdir") or "")
    base_lock = load(base_sha, "dvc.lock").get("stages") or {}
    to_lock = load(to_sha, "dvc.lock").get("stages") or {}
    stage_runs_path = Path(calkit.STAGE_RUNS_FPATH).as_posix()
    base_runs = load(base_sha, stage_runs_path)
    to_runs = load(to_sha, stage_runs_path)
    base_outs = get_outs({"stages": base_lock}, stage_wdirs)
    to_outs = get_outs({"stages": to_lock}, stage_wdirs)
    # Where each side keeps things in Git
    base_git_paths = set(
        list_git_paths("ls_tree", "-r", "--name-only", base_sha)
    )
    if to_sha is None:
        to_git_paths = set(list_git_paths("ls_files"))
        untracked = list_git_paths(
            "ls_files", "--others", "--exclude-standard"
        )
        to_git_paths.update(untracked)
        git_changed = list_git_paths("diff", "--name-only", base_sha)
        git_changed += untracked
    else:
        to_git_paths = set(
            list_git_paths("ls_tree", "-r", "--name-only", to_sha)
        )
        git_changed = list_git_paths("diff", "--name-only", base_sha, to_sha)
    # Stages, in the order the target runs them
    stages: list[dict[str, Any]] = []
    for name in list(to_lock) + [n for n in base_lock if n not in to_lock]:
        old, new = base_lock.get(name), to_lock.get(name)
        n_changed_outputs = sum(
            1
            for path, (_, stage) in {**base_outs, **to_outs}.items()
            if stage == name
            and base_outs.get(path, (None,))[0]
            != to_outs.get(path, (None,))[0]
        )
        if old is None:
            change = "added"
        elif new is None:
            change = "removed"
        elif calkit.dvc.stage_lock_hash(old) != calkit.dvc.stage_lock_hash(
            new
        ) or base_runs.get(name) != to_runs.get(name):
            change = "reran"
        else:
            continue
        stages.append(
            {
                "name": str(name),
                "change": change,
                "stale": False,
                "n_changed_outputs": n_changed_outputs,
                "run": to_runs.get(name),
            }
        )
    if to_sha is None and check_pipeline:
        from calkit.pipeline import get_status

        try:
            status = get_status(
                ck_info=calkit.load_calkit_info(wdir=project_dir),
                wdir=project_dir,
                check_environments=False,
            )
            stale = {n.split("@")[0] for n in status.stale_stage_names}
        except Exception:
            stale = set()
        listed = set()
        for stage in stages:
            if stage["name"].split("@")[0] in stale:
                stage["stale"] = True
                listed.add(stage["name"].split("@")[0])
        for name in sorted(stale - listed):
            stages.append(
                {
                    "name": name,
                    "change": "stale",
                    "stale": True,
                    "n_changed_outputs": 0,
                    "run": to_runs.get(name),
                }
            )
    # Changed files, from the outputs whose hashes moved
    changed: dict[str, dict] = {}
    for path in list(to_outs) + [p for p in base_outs if p not in to_outs]:
        old_md5 = base_outs.get(path, (None,))[0]
        new_md5 = to_outs.get(path, (None,))[0]
        stage = (to_outs.get(path) or base_outs[path])[1]
        if old_md5 == new_md5:
            continue
        if not (
            str(old_md5).endswith(".dir") or str(new_md5).endswith(".dir")
        ):
            changed[path] = {"stage": stage, "md5s": (old_md5, new_md5)}
            continue
        # A directory's files are compared by its manifests, if cached,
        # or else by Git, if it's Git's
        old_files = read_manifest(old_md5)
        new_files = read_manifest(new_md5)
        if old_files is not None and new_files is not None:
            for rel in list(new_files) + [
                r for r in old_files if r not in new_files
            ]:
                if old_files.get(rel) != new_files.get(rel):
                    changed[posixpath.join(path, rel)] = {
                        "stage": stage,
                        "md5s": (old_files.get(rel), new_files.get(rel)),
                    }
            continue
        git_files = [p for p in git_changed if p.startswith(path + "/")]
        for file_path in git_files:
            changed[file_path] = {"stage": stage, "md5s": (None, None)}
        if not git_files:
            changed[path] = {
                "stage": stage,
                "md5s": (old_md5, new_md5),
                "directory": True,
            }
    # What the project names as an artifact or evidence, which can change
    # in Git without the pipeline
    declared_paths: dict[str, set[str]] = {
        "figure": set(),
        "table": set(),
        "result": set(),
    }
    other_paths: set[str] = set()
    cell_output_kinds: dict[str, str] = {}
    evidence: set[str] = set()
    for info in (base_info, to_info):
        for kind in ("figure", "table", "result"):
            for item in info.get(kind + "s") or []:
                if isinstance(item, dict) and item.get("path"):
                    declared_paths[kind].add(
                        posixpath.normpath(str(item["path"]))
                    )
        for kind in ("publications", "datasets"):
            for item in info.get(kind) or []:
                if isinstance(item, dict) and item.get("path"):
                    other_paths.add(posixpath.normpath(str(item["path"])))
        for st in ((info.get("pipeline") or {}).get("stages") or {}).values():
            if not isinstance(st, dict):
                continue
            # A document's build, e.g., a paper's PDF, isn't a figure
            doc_path = None
            if st.get("kind") == "markdown":
                doc_path = st.get("target_path")
            elif st.get("kind") == "latex":
                try:
                    doc_path = LatexStage.model_validate(st).pdf_path
                except Exception:
                    pass
            if doc_path:
                other_paths.add(
                    posixpath.normpath(
                        posixpath.join(st.get("wdir") or "", doc_path)
                    )
                )
            for o in st.get("cell_outputs") or []:
                if isinstance(o, dict) and o.get("output_path"):
                    cell_output_kinds[
                        posixpath.normpath(
                            posixpath.join(
                                st.get("wdir") or "", str(o["output_path"])
                            )
                        )
                    ] = str(o.get("kind"))
        for q in info.get("questions") or []:
            for ev in (q.get("evidence") or []) if isinstance(q, dict) else []:
                if isinstance(ev, dict) and ev.get("path"):
                    evidence.add(posixpath.normpath(str(ev["path"])))
    watched = set().union(*declared_paths.values(), evidence)
    for path in git_changed:
        if path not in changed and any(
            path == p or path.startswith(p + "/") for p in watched
        ):
            changed[path] = {"stage": None, "md5s": (None, None)}
    # Each changed file, read where it can be
    outputs = []
    data: dict[str, tuple[Any, Any]] = {}
    for path, entry in changed.items():
        old_md5, new_md5 = entry["md5s"]
        directory = entry.get("directory", False)
        if directory:
            in_git = any(
                p.startswith(path + "/") for p in to_git_paths | base_git_paths
            )
        else:
            in_git = path in to_git_paths or path in base_git_paths
        storage = "git" if in_git else "dvc"
        kind = get_kind(path)
        old_content = new_content = None
        if not directory:
            old_content = (
                read_git(base_sha, path) if in_git else read_cache(old_md5)
            )
            new_content = (
                read_git(to_sha, path)
                if in_git or to_sha is None
                else read_cache(new_md5)
            )
        existed = old_md5 is not None or old_content is not None
        exists = new_md5 is not None or new_content is not None
        if not existed and not exists:
            continue
        output: dict[str, Any] = {
            "path": path,
            "kind": kind,
            "storage": storage,
            "stage": entry["stage"],
            "change": (
                "added"
                if not existed
                else "removed"
                if not exists
                else "modified"
            ),
        }
        if kind == "value" and output["change"] == "modified":
            if old_content is None or new_content is None:
                output["note"] = (
                    "not in local cache" if storage == "dvc" else "unreadable"
                )
            else:
                try:
                    old_data = load_result(path, content=old_content)
                    new_data = load_result(path, content=new_content)
                except Exception:
                    output["note"] = "unreadable"
                else:
                    data[path] = (old_data, new_data)
                    output["values"] = get_value_changes(old_data, new_data)
        outputs.append(output)
    # Questions whose cited evidence changed
    questions = []
    for number, q in enumerate(to_info.get("questions") or [], start=1):
        if not isinstance(q, dict):
            continue
        changes = []
        for ev in q.get("evidence") or []:
            if not isinstance(ev, dict) or not ev.get("path"):
                continue
            # A pin is a claim about one version, which no change moves
            if ev.get("git_ref"):
                continue
            ev_path = posixpath.normpath(str(ev["path"]))
            matched = [
                o
                for o in outputs
                if o["path"] == ev_path
                or o["path"].startswith(ev_path + "/")
                or ev_path.startswith(o["path"] + "/")
            ]
            if not matched:
                continue
            keys = named_keys(ev)
            if keys and ev_path in data:
                old_data, new_data = data[ev_path]
                for name, key in keys.items():
                    try:
                        old = resolve_key(old_data, key)
                    except KeyError:
                        old = None
                    try:
                        new = resolve_key(new_data, key)
                    except KeyError:
                        new = None
                    if not _values_equal(old, new):
                        changes.append(
                            {
                                "path": ev_path,
                                "name": name,
                                "key": key,
                                "old": old,
                                "new": new,
                                "relative_change": get_relative_change(
                                    old, new
                                ),
                            }
                        )
                continue
            changes.append(
                {
                    "path": ev_path,
                    "change": matched[0]["change"]
                    if len(matched) == 1
                    else "modified",
                }
            )
        if changes:
            questions.append(
                {
                    "number": number,
                    "question": " ".join(str(q.get("question", "")).split()),
                    "evidence": changes,
                }
            )
    return {
        "base": base_sha,
        "base_label": base_label,
        "to": to_sha,
        "stages": stages,
        "outputs": outputs,
        "questions": questions,
    }


def get_relative_change(old: Any, new: Any) -> float | None:
    """How much a number changed, as a fraction of what it was, or None if
    either isn't a number or it was zero."""
    numbers = all(
        isinstance(v, (int, float)) and not isinstance(v, bool)
        for v in (old, new)
    )
    if not numbers or old == 0:
        return None
    return float((new - old) / abs(old))


def format_changes(changes: dict, max_items: int = 10) -> str:
    """What a change did to results, from :func:`get_changes`, as Markdown
    short enough for a job summary or pull request comment.

    Each list stops at ``max_items``, counting the rest.
    """
    import json

    from calkit.notebooks import get_notebook_of_values_path
    from calkit.questions import _fmt

    def cap(items: list) -> tuple[list, list[str]]:
        rest = len(items) - max_items
        return items[:max_items], [f"- {rest} more"] if rest > 0 else []

    def format_value(value: Any, missing: bool = False) -> str:
        if missing:
            return "—"
        if isinstance(value, (dict, list)):
            text = json.dumps(value, default=str)
        elif isinstance(value, bool) or value is None:
            text = json.dumps(value)
        else:
            text = _fmt(value)
        if len(text) > 40:
            text = text[:39] + "…"
        return text.replace("|", "\\|").replace("\n", " ")

    def format_relative(item: dict) -> str:
        rel = item.get("relative_change")
        return "" if rel is None else f"{rel * 100:+.3g}%"

    def format_where(output: dict) -> str:
        storage = {"git": "Git", "dvc": "DVC"}[output["storage"]]
        stage = f", `{output['stage']}`" if output.get("stage") else ""
        return f"({storage}{stage})"

    def format_path(path: str) -> str:
        notebook = get_notebook_of_values_path(path)
        return f"`{notebook}` values" if notebook else f"`{path}`"

    base = changes["base"][:7]
    to = changes["to"][:7] if changes.get("to") else "working tree"
    label = changes.get("base_label")
    since = (
        f"`{base}` ({label})"
        if label and label != changes["base"]
        else f"`{base}`"
    )
    lines = ["## Changed results", "", f"{since} → {to}"]
    stages = changes.get("stages") or []
    outputs = changes.get("outputs") or []
    questions = changes.get("questions") or []
    if not (stages or outputs or questions):
        lines += ["", "No results changed."]
        return "\n".join(lines) + "\n"
    # Stages
    if stages:
        lines += ["", f"### Stages ({len(stages)})", ""]
        shown, more = cap(stages)
        for stage in shown:
            n = stage.get("n_changed_outputs", 0)
            text = {
                "added": "new",
                "removed": "removed",
                "stale": "stale",
                "reran": (
                    f"reran, {n} output{'s' if n != 1 else ''} changed"
                    if n
                    else "reran, outputs unchanged"
                ),
            }[stage["change"]]
            if stage.get("stale") and stage["change"] != "stale":
                text += ", stale"
            lines.append(f"- `{stage['name']}`: {text}")
        lines += more
    # Values, with what each key was and is
    values = [o for o in outputs if o["kind"] == "value"]
    if values:
        lines += ["", f"### Values ({len(values)})"]
        shown, more = cap(values)
        for output in shown:
            heading = f"{format_path(output['path'])} {format_where(output)}"
            items = output.get("values")
            if output["change"] != "modified":
                lines += ["", f"{heading}: {output['change']}"]
                continue
            if items is None:
                lines += ["", f"{heading}: {output.get('note', 'modified')}"]
                continue
            if not items:
                lines += ["", f"{heading}: values unchanged"]
                continue
            lines += [
                "",
                heading,
                "",
                "| Key | Old | New | Change |",
                "| --- | --- | --- | --- |",
            ]
            shown_items, more_items = cap(items)
            for item in shown_items:
                change = (
                    item["change"]
                    if item["change"] != "modified"
                    else format_relative(item)
                )
                lines.append(
                    f"| `{item['key']}` "
                    f"| {format_value(item['old'], item['change'] == 'added')} "
                    f"| {format_value(item['new'], item['change'] == 'removed')} "
                    f"| {change} |"
                )
            if more_items:
                lines += ["", f"{len(items) - max_items} more keys changed"]
        if more:
            lines += [""] + more
    # Figures, tables, and anything else, by path
    for kind, title in [
        ("figure", "Figures"),
        ("table", "Tables"),
        ("other", "Other outputs"),
    ]:
        of_kind = [o for o in outputs if o["kind"] == kind]
        if not of_kind:
            continue
        lines += ["", f"### {title} ({len(of_kind)})", ""]
        shown, more = cap(of_kind)
        for output in shown:
            change = (
                f", {output['change']}"
                if output["change"] != "modified"
                else ""
            )
            lines.append(
                f"- {format_path(output['path'])} "
                f"{format_where(output)}{change}"
            )
        lines += more
    # Questions whose answers rest on changed evidence
    if questions:
        lines += [
            "",
            f"### Questions with changed evidence ({len(questions)})",
            "",
        ]
        shown, more = cap(questions)
        for q in shown:
            text = q["question"]
            if len(text) > 100:
                text = text[:99] + "…"
            lines.append(f"- Q{q['number']}: {text}")
            shown_ev, more_ev = cap(q["evidence"])
            for ev in shown_ev:
                if "key" in ev:
                    rel = format_relative(ev)
                    lines.append(
                        f"  - `{ev['name']}`: {format_value(ev['old'])} → "
                        f"{format_value(ev['new'])}"
                        + (f" ({rel})" if rel else "")
                    )
                else:
                    lines.append(f"  - `{ev['path']}`: {ev['change']}")
            lines += ["  " + line for line in more_ev]
        lines += more
    return "\n".join(lines) + "\n"
