"""Pipeline staleness detection.

Determines whether each stage in a project's DVC pipeline is up-to-date,
stale, not-run, or unknown, by diffing the committed ``dvc.yaml`` and
``dvc.lock`` against the repo tree and object storage. The pipeline's
object storage (Calkit remote) is treated as authoritative for
DVC-tracked outputs since the API clones never ``dvc fetch``.

Designed to be self-contained and easily swapped for a richer
implementation later (e.g., one that can validate environments or detect
when ``dvc.yaml`` needs recompiling from ``calkit.yaml``).
"""

from __future__ import annotations

import hashlib
import io
import itertools
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

import ruamel.yaml
from pydantic import BaseModel, Field

from app.dvc import get_data_fpath_for_md5
from app.git import RepoTree

logger = logging.getLogger(__name__)

_yaml = ruamel.yaml.YAML(typ="safe")

StatusLiteral = Literal[
    "up-to-date", "stale", "not-run", "unknown", "always-run", "frozen"
]
OverallStatusLiteral = Literal["up-to-date", "stale", "unknown"]

# Object-storage existence checks are the dominant cost in
# compute_stage_statuses (one+ network round-trip per dep/out md5). We both
# parallelize them within a computation and cache the whole result keyed by a
# content token (the tree/commit SHA) so repeat reads of the same ref are free.
_STORAGE_CHECK_MAX_WORKERS = 16
_STAGE_STATUS_CACHE_MAX = 64
# TTL bounds the one non-deterministic dimension: objects uploaded after a
# cache entry was written (the SHA pins everything in the tree itself).
_STAGE_STATUS_CACHE_TTL_S = 600
_stage_status_cache: "OrderedDict[str, tuple[float, dict[str, StageStatus]]]" = OrderedDict()
# Sync endpoints run in a threadpool, so cache reads/evictions/writes can happen
# concurrently. Guard every mutation with this lock to keep the OrderedDict and
# its LRU order consistent.
_stage_status_cache_lock = threading.Lock()


class StageStatus(BaseModel):
    """Status for a single pipeline stage."""

    status: StatusLiteral
    modified_command: bool = False
    modified_inputs: list[str] = Field(default_factory=list)
    modified_outputs: list[str] = Field(default_factory=list)
    missing_outputs: list[str] = Field(default_factory=list)


def _get_base_stage_name(name: str) -> str:
    return name.split("@")[0]


def _is_dir_md5(md5: str | None) -> bool:
    return bool(md5) and md5.endswith(".dir")


def _get_uncached_out_paths(dvc_stage: dict | None) -> set[str]:
    """Paths of a dvc.yaml stage's outs declared ``cache: false``.

    DVC records these in dvc.yaml as ``{path: {cache: false, ...}}`` but not in
    dvc.lock. They are never pushed to the DVC cache/object storage and are
    often gitignored, so the cloud can't observe them.
    """
    paths: set[str] = set()
    if not isinstance(dvc_stage, dict):
        return paths
    for out in dvc_stage.get("outs") or []:
        if isinstance(out, dict):
            for out_path, opts in out.items():
                if isinstance(opts, dict) and opts.get("cache") is False:
                    paths.add(out_path)
    return paths


def _safe_yaml_load(data: bytes) -> dict | None:
    try:
        return _yaml.load(io.BytesIO(data))
    except Exception as e:
        logger.warning(f"Failed to parse YAML: {e}")
        return None


def _read_dvc_pointer_md5(tree: RepoTree, path: str) -> str | None:
    """Return the md5 stored in ``<path>.dvc`` if present."""
    dvc_path = path + ".dvc"
    if not tree.is_file(dvc_path):
        return None
    data = _safe_yaml_load(tree.read_bytes(dvc_path))
    if not data:
        return None
    outs = data.get("outs") or []
    if not outs:
        return None
    return outs[0].get("md5")


def _hash_tree_file(tree: RepoTree, path: str) -> str | None:
    if not tree.is_file(path):
        return None
    try:
        return hashlib.md5(tree.read_bytes(path)).hexdigest()
    except Exception as e:
        logger.warning(f"Failed to hash {path}: {e}")
        return None


def _md5_in_object_storage(
    md5: str | None, owner_name: str, project_name: str, fs
) -> bool:
    if not md5:
        return False
    try:
        return (
            get_data_fpath_for_md5(
                owner_name=owner_name,
                project_name=project_name,
                md5=md5,
                fs=fs,
            )
            is not None
        )
    except Exception as e:
        logger.warning(f"Object storage existence check failed for {md5}: {e}")
        return False


def _precompute_storage_presence(
    dvc_lock: dict, owner_name: str, project_name: str, fs
) -> dict[str, bool]:
    """Existence in object storage for every dep/out md5, checked in parallel.

    Replaces the serial per-md5 ``fs.exists`` round-trips with one concurrent
    batch. Returns a ``{md5: present}`` map; md5s absent from the map are
    treated as not present by callers.
    """
    md5s: set[str] = set()
    for stage in (dvc_lock.get("stages") or {}).values():
        for entry in (stage.get("deps") or []) + (stage.get("outs") or []):
            m = entry.get("md5") or entry.get("hash")
            if m:
                md5s.add(m)
    if not md5s:
        return {}
    presence: dict[str, bool] = {}
    workers = min(_STORAGE_CHECK_MAX_WORKERS, len(md5s))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = ex.map(
            lambda m: (
                m,
                _md5_in_object_storage(m, owner_name, project_name, fs),
            ),
            md5s,
        )
        for m, present in results:
            presence[m] = present
    return presence


def _build_stage_status_cache_key(
    owner_name: str, project_name: str, cache_token: str | None
) -> str | None:
    if not cache_token:
        return None
    h = hashlib.sha1()
    h.update(owner_name.encode())
    h.update(b"\0")
    h.update(project_name.encode())
    h.update(b"\0")
    h.update(cache_token.encode())
    return h.hexdigest()


def _stage_status_cache_get(cache_key: str) -> dict[str, StageStatus] | None:
    with _stage_status_cache_lock:
        cached = _stage_status_cache.get(cache_key)
        if cached is None:
            return None
        cached_at, value = cached
        if time.monotonic() - cached_at > _STAGE_STATUS_CACHE_TTL_S:
            del _stage_status_cache[cache_key]
            return None
        _stage_status_cache.move_to_end(cache_key)
        return value


def _stage_status_cache_put(
    cache_key: str, value: dict[str, StageStatus]
) -> None:
    with _stage_status_cache_lock:
        _stage_status_cache[cache_key] = (time.monotonic(), value)
        _stage_status_cache.move_to_end(cache_key)
        if len(_stage_status_cache) > _STAGE_STATUS_CACHE_MAX:
            _stage_status_cache.popitem(last=False)


def _build_outs_index(dvc_lock: dict) -> dict[str, str | None]:
    """Map out path -> md5 across all stages in the lock."""
    out_map: dict[str, str | None] = {}
    for stage in (dvc_lock.get("stages") or {}).values():
        for out in stage.get("outs") or []:
            p = out.get("path")
            if p:
                out_map[p] = out.get("md5")
    return out_map


def _resolve_current_dep_md5(
    path: str,
    tree: RepoTree,
    outs_index: dict[str, str | None],
) -> str | None:
    """Current md5 for a dep path, or None if it can't be observed.

    Committed content wins: a producing stage's recorded out md5
    (``outs_index``) can be stale -- e.g. non-deterministic notebook cleaning
    leaves the cleaning stage's lock entry out of sync with the committed,
    regenerated file -- so only fall back to it when the file isn't in the git
    tree (a gitignored DVC pipeline output).
    """
    ptr = _read_dvc_pointer_md5(tree, path)
    if ptr is not None:
        return ptr
    if tree.is_file(path):
        return _hash_tree_file(tree, path)
    if path in outs_index:
        return outs_index[path]
    return None


def _get_nested(data: dict | None, dotted_key: str):
    cur = data
    for part in dotted_key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _normalize_cmd(cmd) -> str | None:
    if cmd is None:
        return None
    if isinstance(cmd, list):
        return " && ".join(str(c) for c in cmd).strip()
    return str(cmd).strip()


def _compute_expansion_names(base: str, yaml_stage: dict) -> set[str] | None:
    """The ``base@...`` stage names DVC generates for a matrix/foreach stage.

    Mirrors DVC's naming: each matrix combination is named by joining its
    values with ``-``; a scalar value contributes ``str(value)`` while a
    list/dict value contributes ``{key}{index}`` (so a ``{_arg0: [..dicts..]}``
    matrix yields ``base@_arg00``, ``base@_arg01``, ...). Returns None when the
    expansion can't be determined statically (e.g. ``foreach: ${var}``).
    """
    matrix = yaml_stage.get("matrix")
    if isinstance(matrix, dict):
        keys = list(matrix.keys())
        value_lists = []
        for k in keys:
            v = matrix[k]
            if not isinstance(v, list):
                return None
            value_lists.append(v)
        names: set[str] = set()
        for combo in itertools.product(
            *(range(len(vl)) for vl in value_lists)
        ):
            comps = []
            for j, k in enumerate(keys):
                val = value_lists[j][combo[j]]
                if isinstance(val, (dict, list)):
                    comps.append(f"{k}{combo[j]}")
                else:
                    comps.append(str(val))
            names.add(f"{base}@{'-'.join(comps)}")
        return names
    foreach = yaml_stage.get("foreach")
    if isinstance(foreach, list):
        return {
            f"{base}@{v if not isinstance(v, (dict, list)) else i}"
            for i, v in enumerate(foreach)
        }
    if isinstance(foreach, dict):
        return {f"{base}@{k}" for k in foreach}
    return None


def _compute_current_expansions(
    yaml_stages: dict, lock_stages: dict
) -> dict[str, set[str]]:
    """Map each matrix/foreach base to the set of ``@`` stage names the current
    pipeline produces.

    Lets the staleness check drop leftover ``base@...`` lock entries -- old
    matrix combinations (or an older naming scheme) whose objects were later
    gc'd, which would otherwise be wrongly flagged stale. Only bases whose
    computed names actually appear in the lock are returned, so a naming
    mismatch (e.g. a DVC version change) never causes us to hide a real stage.
    """
    lock_names = set(lock_stages)
    result: dict[str, set[str]] = {}
    for base, st in yaml_stages.items():
        if not isinstance(st, dict) or base.startswith("_"):
            continue
        if "matrix" not in st and "foreach" not in st:
            continue
        names = _compute_expansion_names(base, st)
        if names and (names & lock_names):
            result[base] = names
    return result


def compute_stage_statuses(
    dvc_yaml: dict,
    dvc_lock: dict,
    tree: RepoTree,
    owner_name: str,
    project_name: str,
    fs=None,
    cache_token: str | None = None,
) -> dict[str, StageStatus]:
    """Compute per-stage status for a pipeline.

    Keys are stage names as they appear in ``dvc.lock`` (including
    ``@``-expansions for matrix/foreach stages). Stages declared in
    ``dvc.yaml`` but never run are reported with status ``not-run`` under
    their base name.

    When ``cache_token`` is given (a content-identifying token such as the
    tree/commit SHA the inputs were read from), the result is cached so repeat
    calls for the same ref skip the object-storage round-trips entirely. The
    token must change whenever any tracked file does -- a commit/tree SHA does,
    the ``dvc.lock`` bytes alone do NOT (a dep can change while the lock stays
    the same, which is exactly what staleness detects).

    ``fs`` is the object-storage filesystem used to check output presence;
    when omitted it defaults to ``get_object_fs()``.
    """
    cache_key = _build_stage_status_cache_key(
        owner_name, project_name, cache_token
    )
    if cache_key is not None:
        hit = _stage_status_cache_get(cache_key)
        if hit is not None:
            return hit
    if fs is None:
        from app.storage import get_object_fs

        fs = get_object_fs()
    lock_stages = dvc_lock.get("stages") or {}
    yaml_stages = dvc_yaml.get("stages") or {}
    outs_index = _build_outs_index(dvc_lock)
    presence = _precompute_storage_presence(
        dvc_lock, owner_name, project_name, fs
    )
    # DVC outputs that calkit stores as a zip live under .calkit/zip/, not at
    # the standard files/md5 object path, so the md5 presence check above can't
    # find them. Treat any output whose workspace path is zip-mapped as present
    # so zip-stored stages aren't wrongly flagged stale (calkit status sees the
    # real files locally, so it reports them up to date).
    zip_workspace_paths: set[str] = set()
    try:
        if tree.is_file(".calkit/zip/paths.json"):
            zip_map = (
                json.loads(tree.read_bytes(".calkit/zip/paths.json")) or {}
            )
            zip_workspace_paths = {k.rstrip("/") for k in zip_map}
    except Exception as e:
        logger.warning(f"Failed to read .calkit/zip/paths.json: {e}")
    current_expansions = _compute_current_expansions(yaml_stages, lock_stages)
    result: dict[str, StageStatus] = {}
    locked_bases = {_get_base_stage_name(n) for n in lock_stages.keys()}
    for stage_name in yaml_stages.keys():
        if stage_name.startswith("_"):
            continue
        if stage_name not in locked_bases:
            result[stage_name] = StageStatus(status="not-run")
    for stage_name, lock_stage in lock_stages.items():
        base = _get_base_stage_name(stage_name)
        if base.startswith("_"):
            continue
        yaml_stage = yaml_stages.get(base)
        if yaml_stage is None:
            # Stale lock entry for a stage no longer in dvc.yaml (renamed or
            # removed, or a bare entry left from before a stage became a
            # matrix). It's not part of the current pipeline, so don't report
            # it -- dvc/calkit status ignore it too.
            continue
        if (
            isinstance(yaml_stage, dict)
            and ("matrix" in yaml_stage or "foreach" in yaml_stage)
            and "@" not in stage_name
        ):
            # A matrix/foreach stage exists in dvc.lock only as ``name@...``
            # expansions; a bare ``name`` entry is stale cruft from before it
            # was expanded, often with outdated deps. Only the expansions are
            # real stages.
            continue
        if (
            base in current_expansions
            and stage_name not in current_expansions[base]
        ):
            # Drop leftover matrix/foreach expansions: ``base@...`` entries from
            # old matrix combinations (or an older DVC naming scheme, e.g.
            # ``@1-3-1`` vs the current ``@_arg01``) that aren't in the current
            # pipeline. Their objects are often gc'd, so the cloud would wrongly
            # flag them stale even though a current entry produces the same
            # output. lock files drift into this state easily, so guard for it.
            continue
        modified_command = False
        modified_inputs: list[str] = []
        modified_outputs: list[str] = []
        missing_outputs: list[str] = []
        yaml_cmd = _normalize_cmd(
            yaml_stage.get("cmd") if isinstance(yaml_stage, dict) else None
        )
        lock_cmd = _normalize_cmd(lock_stage.get("cmd"))
        if (
            yaml_cmd is not None
            and lock_cmd is not None
            and "${" not in yaml_cmd
            and yaml_cmd != lock_cmd
        ):
            modified_command = True
        for dep in lock_stage.get("deps") or []:
            dep_path = dep.get("path")
            lock_md5 = dep.get("md5") or dep.get("hash")
            if not dep_path:
                continue
            if _is_dir_md5(lock_md5):
                # Directory dep: trust object storage, otherwise assume current
                # if present in the tree. If we can observe neither, we can't
                # prove it changed -- don't flag stale (same rationale as the
                # unobservable file-dep case below).
                continue
            current = _resolve_current_dep_md5(dep_path, tree, outs_index)
            if current is None:
                # The cloud can't observe this dep: it's not in the git tree,
                # has no .dvc pointer, isn't another stage's out, and isn't in
                # object storage. This is normal for gitignored calkit
                # intermediates (e.g. cleaned notebooks, which calkit cleans
                # on the fly and never commits). We can't compute a current
                # hash, so we have no evidence it changed -- don't flag stale.
                continue
            if lock_md5 is not None and current != lock_md5:
                modified_inputs.append(dep_path)
        for params_file, locked_params in (
            lock_stage.get("params") or {}
        ).items():
            if not isinstance(locked_params, dict):
                continue
            if not tree.is_file(params_file):
                for key in locked_params:
                    modified_inputs.append(f"{params_file}:{key}")
                continue
            current_params = (
                _safe_yaml_load(tree.read_bytes(params_file)) or {}
            )
            for key, locked_val in locked_params.items():
                if _get_nested(current_params, key) != locked_val:
                    modified_inputs.append(f"{params_file}:{key}")
        # Outs marked ``cache: false`` in dvc.yaml are never pushed to object
        # storage and are often gitignored, so the cloud can't observe them.
        # Their absence isn't evidence they're missing (calkit/DVC check the
        # workspace file, which the cloud can't see), so don't flag stale --
        # same rationale as the unobservable-dep case above.
        cache_false_outs = _get_uncached_out_paths(yaml_stage)
        for out in lock_stage.get("outs") or []:
            out_path = out.get("path")
            lock_md5 = out.get("md5") or out.get("hash")
            if not out_path:
                continue
            zip_stored = out_path.rstrip("/") in zip_workspace_paths
            cache_false = out_path in cache_false_outs
            if _is_dir_md5(lock_md5):
                if presence.get(lock_md5, False) or zip_stored:
                    continue
                if not tree.exists(out_path) and not cache_false:
                    missing_outputs.append(out_path)
                continue
            available_md5: str | None = None
            if tree.is_file(out_path):
                available_md5 = _hash_tree_file(tree, out_path)
            else:
                ptr = _read_dvc_pointer_md5(tree, out_path)
                if ptr is not None:
                    available_md5 = ptr
            if available_md5 is None:
                if presence.get(lock_md5, False) or zip_stored or cache_false:
                    continue
                missing_outputs.append(out_path)
            elif lock_md5 is not None and available_md5 != lock_md5:
                modified_outputs.append(out_path)
        is_stale = bool(
            modified_command
            or modified_inputs
            or modified_outputs
            or missing_outputs
        )
        # A stage compiled with ``always_changed: true`` (calkit's
        # ``always_run``) re-executes every time by design, so its dependency
        # and output staleness is moot -- it always regenerates, and its
        # outputs are often ephemeral / not pushed to the cloud. Always surface
        # it as ``always-run`` rather than letting a missing/changed output
        # flag it stale.
        always_changed = bool(
            isinstance(yaml_stage, dict) and yaml_stage.get("always_changed")
        )
        # A frozen stage (``dvc freeze``) is pinned: DVC won't re-run it even
        # when its deps change, so it's never stale -- surface it as frozen.
        frozen = bool(
            isinstance(yaml_stage, dict) and yaml_stage.get("frozen")
        )
        if frozen:
            status: StatusLiteral = "frozen"
        elif always_changed:
            status = "always-run"
        elif is_stale:
            status = "stale"
        else:
            status = "up-to-date"
        result[stage_name] = StageStatus(
            status=status,
            modified_command=modified_command,
            modified_inputs=modified_inputs,
            modified_outputs=modified_outputs,
            missing_outputs=missing_outputs,
        )
    if cache_key is not None:
        # Don't cache a result whose staleness comes from outputs missing in
        # object storage. Pushing that content makes the stage up-to-date
        # without changing the cache_token (the commit/tree SHA), so a cached
        # "stale" would otherwise linger for the full TTL after the artifact is
        # pushed -- blocking a release the user just made reproducible. Results
        # with no missing outputs are pinned by the SHA and safe to cache.
        storage_dependent = any(s.missing_outputs for s in result.values())
        if not storage_dependent:
            _stage_status_cache_put(cache_key, result)
    return result


def calc_overall_pipeline_status(
    stage_statuses: dict[str, StageStatus],
) -> OverallStatusLiteral:
    if not stage_statuses:
        return "unknown"
    statuses = {s.status for s in stage_statuses.values()}
    if "stale" in statuses or "not-run" in statuses:
        return "stale"
    # Always-run stages re-execute by design and frozen stages are pinned;
    # neither makes a pipeline stale.
    if statuses <= {"up-to-date", "always-run", "frozen"}:
        return "up-to-date"
    return "unknown"


_MERMAID_NODE_RE = re.compile(r'^\s*(node\d+)\["([^"]+)"\]\s*$')

_MERMAID_STYLES = {
    "stale": "fill:#8a6a00,stroke:#c9a227,color:#fff5cc",
    "not-run": "fill:#3a3a3a,stroke:#888,color:#ddd",
    "up-to-date": "fill:#1f5a1f,stroke:#3a8a3a,color:#d6f5d6",
    "always-run": "fill:#1a4f7a,stroke:#3a8fd6,color:#d6ecff",
    # Frozen stages are pinned, not stale -- a frosty gray-blue (ice).
    "frozen": "fill:#5e7d8a,stroke:#a9d7e8,color:#eaf7fc",
}


def color_mermaid_by_status(
    mermaid: str, stage_statuses: dict[str, StageStatus]
) -> str:
    """Append classDef/class lines to a Mermaid diagram that color each
    stage node by its status. Stages with ``unknown`` status are left
    uncolored.
    """
    if not mermaid or not stage_statuses:
        return mermaid
    rank = {
        "up-to-date": 0,
        "frozen": 1,
        "always-run": 1,
        "unknown": 2,
        "not-run": 3,
        "stale": 4,
    }
    # Collapse @-expanded matrix stages to their base, worst-status wins
    base_status: dict[str, str] = {}
    for name, info in stage_statuses.items():
        base = name.split("@")[0]
        prev = base_status.get(base)
        if prev is None or rank.get(info.status, 0) > rank.get(prev, 0):
            base_status[base] = info.status
    buckets: dict[str, list[str]] = {
        "stale": [],
        "not-run": [],
        "up-to-date": [],
        "always-run": [],
        "frozen": [],
    }
    for line in mermaid.splitlines():
        m = _MERMAID_NODE_RE.match(line)
        if not m:
            continue
        node_id, label = m.group(1), m.group(2)
        status = base_status.get(label.split("@")[0])
        if status in buckets:
            buckets[status].append(node_id)
    extra: list[str] = []
    for status, nodes in buckets.items():
        if not nodes:
            continue
        extra.append(f"\tclassDef {status} {_MERMAID_STYLES[status]}")
        extra.append(f"\tclass {','.join(nodes)} {status}")
    if not extra:
        return mermaid
    return mermaid.rstrip() + "\n" + "\n".join(extra) + "\n"


def find_stage_for_path(path: str, dvc_lock: dict) -> str | None:
    """Return the stage in ``dvc.lock`` that produces *path*.

    Matches an exact out path first; failing that, matches a stage whose out is
    a *directory* containing *path* (e.g. an out of ``figures`` produces
    ``figures/test.png``). Exact matches always win over directory matches.
    """
    dir_match: str | None = None
    for stage_name, stage in (dvc_lock.get("stages") or {}).items():
        for out in stage.get("outs") or []:
            out_path = out.get("path")
            if not out_path:
                continue
            if out_path == path:
                return stage_name
            if dir_match is None and path.startswith(
                out_path.rstrip("/") + "/"
            ):
                dir_match = stage_name
    return dir_match
