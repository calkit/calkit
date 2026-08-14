"""Functionality for working with projects"""

import base64
import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from typing import Any, Literal, NamedTuple

import git
import requests
import sqlalchemy
import yaml
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, and_, or_, select

import app.users
from app.config import settings
from calkit.notebooks import get_executed_notebook_path


# libyaml's C loader is ~10x faster than the pure-Python SafeLoader on
# large dvc.lock files. The Dockerfile asserts `yaml.__with_libyaml__`, so
# we can rely on CSafeLoader being present in all deployed environments.
def _yaml_load(data: bytes | str):
    return yaml.load(data, Loader=yaml.CSafeLoader)


from app.core import (
    CATEGORIES_PLURAL_TO_SINGULAR,
    normalize_artifact_path,
    params_from_url,
    ryaml,
    utcnow,
)
from app.dvc import expand_dvc_lock_outs, get_data_fpath_for_md5
from app.git import (
    RepoTree,
    get_ck_info_from_repo,
    get_dvc_pipeline_from_repo,
    get_repo_tree_for_ref,
)
from app.models import (
    Account,
    ContentsItem,
    Figure,
    ItemLock,
    Notebook,
    Org,
    OverleafLink,
    Project,
    Publication,
    User,
    UserOrgMembership,
    UserProjectAccess,
)
from app.models.core import ROLE_IDS
from app.pipeline import find_stage_for_path
from app.storage import (
    get_object_fs,
    get_object_url,
    make_data_fpath,
    remove_gcs_content_type,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RETURN_CONTENT_SIZE_LIMIT = 1_000_000


class CkInfoAndOuts(NamedTuple):
    """Parsed project metadata for a tree, returned by
    get_ck_info_and_dvc_outs_from_tree. A NamedTuple so callers can read named
    fields (and still unpack), without paying validation cost on this hot,
    cached path.
    """

    ck_info: dict
    dvc_lock_outs: dict
    zip_path_map: dict
    dvc_lock: dict


# Cache for the CkInfoAndOuts returned by
# get_ck_info_and_dvc_outs_from_tree, keyed by a hash of the raw bytes of
# calkit.yaml, dvc.lock, and .calkit/zip/paths.json plus the owner/project
# (owner/project influence DVC object-storage paths resolved during
# expansion). Invalidates automatically whenever any of those source files
# change. Hot-path cost of expanding an 8k-line dvc.lock dominates
# get_contents_from_tree; caching it removes that work from repeat reads.
_CK_DVC_CACHE_MAX = 64
# 10 minute TTL caps staleness in the rare case where dvc.lock is unchanged
# but new DVC objects (e.g., a .dir blob) have since been uploaded to object
# storage; cache_key is derived from dvc.lock bytes so normal edits already
# invalidate immediately.
_CK_DVC_CACHE_TTL_S = 600
_ck_dvc_cache: OrderedDict[str, tuple[float, CkInfoAndOuts]] = OrderedDict()
# Sync endpoints run in a threadpool, so guard the (cheap) cache read/write
# sections; the expensive expansion between them runs unlocked.
_ck_dvc_cache_lock = threading.Lock()


def _resolve_github_collaborator_access(
    session: Session, project: Project, current_user: User
) -> None:
    """Resolve a non-member user's access from the cached GitHub permission,
    querying GitHub and caching the result on a miss. Sets
    ``project.current_user_access`` (left None if it can't be determined).
    """
    # Plain read, deliberately not SELECT ... FOR UPDATE. The row lock would
    # be held until the request's session closes, so every concurrent request
    # for this (user, project) would serialize behind whichever one is doing
    # the slowest Git/object-storage work. Nothing here needs the lock: the
    # row is write-once, and the insert race below is settled by catching the
    # unique violation.
    access_query = (
        select(UserProjectAccess)
        .where(UserProjectAccess.project_id == project.id)
        .where(UserProjectAccess.user_id == current_user.id)
    )
    access = session.exec(access_query).first()
    if access is not None:
        project.current_user_access = access.github_access
        return
    # Query GitHub for permissions
    try:
        github_token = app.users.get_github_token(session, current_user)
    except HTTPException:
        github_token = None
        logger.info(f"User {current_user.email} has no GitHub token")
    if github_token is None:
        return
    logger.info("Fetching permissions from GitHub")
    url = (
        f"https://api.github.com/repos/{project.github_repo}"
        f"/collaborators/{current_user.github_username}/permission"
    )
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {github_token}"},
        timeout=15,
    )
    if resp.status_code == 200:
        logger.info("Fetched permissions from GitHub")
        permissions = resp.json()["permission"]
        if permissions == "none":
            permissions = None
    else:
        permissions = None
        logger.info(
            f"Failed to fetch permissions from GitHub ({resp.status_code})"
        )
    project.current_user_access = permissions
    # Concurrent requests for the same user and project can both get here and
    # try to insert. Losing that race is harmless (the winner cached the same
    # permission), but the unique violation would otherwise 500 the request.
    session.add(
        UserProjectAccess(
            project_id=project.id,
            user_id=current_user.id,
            github_access=permissions,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        logger.info(
            f"Access record for user {current_user.id} and project "
            f"{project.id} was written concurrently; ignoring"
        )
        session.rollback()


def get_project(
    session: Session,
    owner_name: str,
    project_name: str,
    if_not_exists: Literal["ignore", "error"] = "error",
    current_user: User | None = None,
    min_access_level: Literal["read", "write", "admin", "owner"] | None = None,
) -> Project:
    """Fetch a project by owner and name."""
    if current_user is None:
        user_name = "anonymous"
    else:
        user_name = current_user.email
    logger.info(
        f"Fetching project {owner_name}/{project_name} for {user_name}"
    )
    query = (
        select(Project)
        .where(Project.owner_account.has(name=owner_name.lower()))
        .where(sqlalchemy.func.lower(Project.name) == project_name.lower())
    )
    project = session.exec(query).first()
    if project is None and if_not_exists == "error":
        logger.info(f"Project {owner_name}/{project_name} does not exist")
        raise HTTPException(404)
    if (
        min_access_level is not None
        and current_user is None
        and not project.is_public
    ):
        raise HTTPException(403, "User is not authenticated")
    if current_user is None and project.is_public:
        project.current_user_access = "read"
    elif current_user is not None:
        # Compute access
        if project.owner == current_user:
            project.current_user_access = "owner"
        elif isinstance(project.owner, Org):
            # Org admins/owners get full access; plain members get read. This
            # matches the org condition in the project search/listing queries,
            # so a member never sees a project they then can't open.
            for org_membership in current_user.org_memberships:
                if org_membership.org_id == project.owner.account.org_id:
                    project.current_user_access = (
                        "owner"
                        if org_membership.role_name in ["admin", "owner"]
                        else "read"
                    )
                    break
            if project.current_user_access is None and project.is_public:
                project.current_user_access = "read"
        else:
            # Non-owner: a native Calkit grant (role_id, e.g., from an invite)
            # takes precedence over GitHub-derived access, and is the only
            # access path for GitHub-less collaborators.
            access_row = session.exec(
                select(UserProjectAccess)
                .where(UserProjectAccess.project_id == project.id)
                .where(UserProjectAccess.user_id == current_user.id)
            ).first()
            if access_row is not None and access_row.role_id is not None:
                project.current_user_access = access_row.role_name
            else:
                _resolve_github_collaborator_access(
                    session, project, current_user
                )
        if project.is_public and project.current_user_access is None:
            project.current_user_access = "read"
        if project.current_user_access is None:
            raise HTTPException(403)
        if min_access_level is not None:
            access_levels = {
                level: n
                for (n, level) in enumerate(
                    ["read", "write", "admin", "owner"]
                )
            }
            user_has_level = access_levels[project.current_user_access]
            min_level = access_levels[min_access_level]
            if user_has_level < min_level:
                raise HTTPException(403)
    return project


def dvc_outputs_from_tree(project: Project, tree: RepoTree) -> dict[str, dict]:
    """Every DVC-tracked output in a tree, keyed by path.

    Two sources: dvc.lock, which covers anything a pipeline stage
    produces, and the standalone ``.dvc`` pointer files that ``dvc add``
    leaves next to a tracked file, which the lock knows nothing about.
    """
    outs: dict[str, dict] = dict(
        get_ck_info_and_dvc_outs_from_tree(
            project=project, tree=tree
        ).dvc_lock_outs
    )

    def walk(dirname: str) -> list[str]:
        found = []
        for name in tree.listdir(dirname or None):
            path = os.path.join(dirname, name) if dirname else name
            if path in [".git", ".dvc"]:
                continue
            if tree.is_dir(path):
                found += walk(path)
            elif path.endswith(".dvc"):
                found.append(path)
        return found

    for pointer_path in walk(""):
        try:
            data = yaml.safe_load(tree.read_text(pointer_path))
            out = (data.get("outs") or [{}])[0]
        except Exception as e:
            logger.warning(f"Failed to read DVC pointer {pointer_path}: {e}")
            continue
        if not isinstance(out, dict) or not out.get("md5"):
            continue
        declared = out.get("path")
        path = (
            os.path.normpath(
                os.path.join(os.path.dirname(pointer_path), declared)
            )
            if declared
            else pointer_path[: -len(".dvc")]
        )
        outs.setdefault(path, out)
    return outs


def get_contents_from_repo(
    project: Project,
    repo: git.Repo,
    path: str | None = None,
    ref: str | None = None,
) -> ContentsItem:
    return get_contents_from_tree(
        project=project,
        tree=get_repo_tree_for_ref(repo, ref),
        path=path,
    )


def writable_project_clause(current_user: User):
    """Projects the user can write to, as a SQL predicate.

    Shared rather than inlined at each call site because it restates the
    access rules get_project applies per project, and two copies of an
    access rule drift into two different answers about who can write.
    """
    return or_(
        Project.owner_account_id == current_user.account.id,
        and_(
            UserProjectAccess.user_id == current_user.id,
            or_(
                UserProjectAccess.role_id >= ROLE_IDS["write"],  # type: ignore
                UserProjectAccess.github_access.in_(["write", "admin"]),  # type: ignore
            ),
        ),
        Project.owner_account.has(  # type: ignore
            and_(
                Account.org_id.is_not(None),  # type: ignore
                select(UserOrgMembership)
                .where(
                    UserOrgMembership.user_id == current_user.id,
                    UserOrgMembership.org_id == Account.org_id,
                    # A plain org member only gets read on the org's
                    # projects; admins and owners get full access
                    UserOrgMembership.role_id >= ROLE_IDS["admin"],
                )
                .exists(),
            )
        ),
    )


def overleaf_links_from_ck_info(ck_info: dict) -> dict[str, str]:
    """Map synced folder to Overleaf project ID, as calkit.yaml declares it.

    Only the committed ``overleaf_sync`` block is read, not the private
    sync state, so this works on a calkit.yaml fetched on its own without
    the rest of the repo.
    """
    import calkit.overleaf

    declared: dict[str, str] = {}
    for path, info in (ck_info.get("overleaf_sync") or {}).items():
        if not isinstance(info, dict):
            continue
        project_id = info.get("project_id")
        if not project_id and info.get("url"):
            project_id = calkit.overleaf.project_id_from_url(info["url"])
        if project_id:
            declared[str(path)] = str(project_id)
    return declared


def store_overleaf_links(
    session: Session, project: Project, declared: dict[str, str]
) -> list[OverleafLink]:
    """Make the index for a project match ``declared`` exactly."""
    existing = {
        link.path: link
        for link in session.exec(
            select(OverleafLink).where(OverleafLink.project_id == project.id)
        ).all()
    }
    changed = False
    for path, overleaf_project_id in declared.items():
        link = existing.get(path)
        if link is None:
            session.add(
                OverleafLink(
                    project_id=project.id,
                    path=path,
                    overleaf_project_id=overleaf_project_id,
                )
            )
            changed = True
        elif link.overleaf_project_id != overleaf_project_id:
            link.overleaf_project_id = overleaf_project_id
            link.updated = utcnow()
            session.add(link)
            changed = True
    for path, link in existing.items():
        if path not in declared:
            session.delete(link)
            changed = True
    if changed:
        session.commit()
    return list(
        session.exec(
            select(OverleafLink).where(OverleafLink.project_id == project.id)
        ).all()
    )


def scan_overleaf_links(
    session: Session, project: Project, user: User
) -> list[OverleafLink]:
    """Read a project's Overleaf links from its calkit.yaml on GitHub.

    Fetching the one file through the GitHub API costs a single request,
    where cloning the repo to read the same file costs a clone. That is
    what makes it reasonable to walk a user's projects looking for the one
    that syncs with a given Overleaf project.

    The scan timestamp is recorded either way, so a project with no links,
    no calkit.yaml, or no readable repo isn't re-fetched on every lookup.
    """
    declared: dict[str, str] = {}
    if project.github_repo:
        try:
            token = app.users.get_github_token(session, user)
        except HTTPException:
            token = None
        if token is not None:
            try:
                resp = requests.get(
                    f"https://api.github.com/repos/{project.github_repo}"
                    "/contents/calkit.yaml",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github.raw+json",
                    },
                    timeout=15,
                )
                if resp.status_code == 200:
                    declared = overleaf_links_from_ck_info(
                        _yaml_load(resp.text) or {}
                    )
            except Exception as e:
                logger.info(
                    f"Could not read calkit.yaml for {project.id}: {e}"
                )
    links = store_overleaf_links(session, project, declared)
    project.overleaf_scanned = utcnow()
    session.add(project)
    session.commit()
    return links


def record_overleaf_links(
    session: Session,
    project: Project,
    repo: git.Repo,
    ck_info: dict | None = None,
) -> list[OverleafLink]:
    """Index the project's Overleaf links so an Overleaf project ID can be
    resolved back to this project.

    The repo stays the source of truth, so this refreshes the index to match
    what calkit.yaml declares, dropping links that are no longer there.
    """
    import calkit.overleaf

    try:
        sync_info = calkit.overleaf.get_sync_info(
            wdir=repo.working_dir, ck_info=deepcopy(ck_info)
        )
    except Exception as e:
        logger.warning(f"Could not read Overleaf sync info: {e}")
        return []
    declared = {}
    for path, info in sync_info.items():
        overleaf_project_id = info.get("project_id")
        if overleaf_project_id:
            declared[path] = str(overleaf_project_id)
    links = store_overleaf_links(session, project, declared)
    # Reading the repo is the most authoritative look there is, so it also
    # satisfies the scan the lazy lookup would otherwise do
    project.overleaf_scanned = utcnow()
    session.add(project)
    session.commit()
    return links


# Categories in calkit.yaml whose items are keyed by a path. This is
# CATEGORIES_PLURAL_TO_SINGULAR plus presentations, which aren't a Calkit
# object kind but are still declared with a path.
_PATH_CATEGORIES = list(CATEGORIES_PLURAL_TO_SINGULAR) + ["presentations"]


def normalize_ck_info_paths(ck_info: dict[str, Any]) -> dict[str, Any]:
    """Normalize every artifact path declared in ``ck_info``, in place.

    See ``normalize_artifact_path``: a path written as ``./paper/main.pdf``
    means the same file as ``paper/main.pdf``, but only the latter matches a
    dvc.lock out or a Git tree entry, so declared paths have to be cleaned up
    before anything keys artifacts by path.

    Only safe for metadata that is read and never written back to
    calkit.yaml, since it rewrites the paths the user declared.
    """
    for category in _PATH_CATEGORIES:
        itemlist = ck_info.get(category)
        if not isinstance(itemlist, list):
            continue
        for item in itemlist:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("path"), str):
                item["path"] = normalize_artifact_path(item["path"])
            # References items carry their own files, each with a path
            files = item.get("files")
            if isinstance(files, list):
                for f in files:
                    if isinstance(f, dict) and isinstance(f.get("path"), str):
                        f["path"] = normalize_artifact_path(f["path"])
    # Showcase elements reference artifacts by path rather than declaring one
    showcase = ck_info.get("showcase")
    if isinstance(showcase, list):
        for element in showcase:
            if not isinstance(element, dict):
                continue
            for key in ("figure", "publication", "notebook"):
                if isinstance(element.get(key), str):
                    element[key] = normalize_artifact_path(element[key])
    return ck_info


def get_ck_info_and_dvc_outs_from_tree(
    project: Project,
    tree: RepoTree,
) -> CkInfoAndOuts:
    """Load calkit.yaml and expand dvc.lock outs once for a tree.

    Returns a CkInfoAndOuts (ck_info, dvc_lock_outs, zip_path_map, dvc_lock).
    zip_path_map maps workspace paths to their zip file path (e.g.
    {"data/mydir": ".calkit/zip/files/data/mydir.zip"}). dvc_lock is the raw
    parsed dvc.lock (with its top-level ``stages`` key), useful for resolving
    the stage that produces a path. Callers that read multiple paths from the
    same tree should call this once and pass the results to
    get_contents_from_tree to avoid redundant I/O.
    """
    owner_name = project.owner_account_name
    project_name = project.name
    # Read raw bytes first so we can key a cross-request cache on their
    # content hash. For the common case of repeated reads against the same
    # tree, this short-circuits the 8k-line dvc.lock YAML parse (~200ms) and
    # the DVC lock-outs expansion (~400ms for large lockfiles).
    t0 = time.perf_counter()
    ck_bytes = (
        tree.read_bytes("calkit.yaml") if tree.is_file("calkit.yaml") else b""
    )
    dvc_bytes = (
        tree.read_bytes("dvc.lock") if tree.is_file("dvc.lock") else b""
    )
    zip_paths_json = ".calkit/zip/paths.json"
    zip_bytes = (
        tree.read_bytes(zip_paths_json)
        if tree.is_file(zip_paths_json)
        else b""
    )
    t_read = time.perf_counter() - t0
    h = hashlib.sha1()
    h.update(owner_name.encode())
    h.update(b"\0")
    h.update(project_name.encode())
    h.update(b"\0")
    h.update(hashlib.sha1(ck_bytes).digest())
    h.update(hashlib.sha1(dvc_bytes).digest())
    h.update(hashlib.sha1(zip_bytes).digest())
    cache_key = h.hexdigest()
    now = time.monotonic()
    with _ck_dvc_cache_lock:
        cached = _ck_dvc_cache.get(cache_key)
        hit_value = None
        if cached is not None:
            cached_at, value = cached
            if now - cached_at <= _CK_DVC_CACHE_TTL_S:
                _ck_dvc_cache.move_to_end(cache_key)
                hit_value = value
            else:
                del _ck_dvc_cache[cache_key]
    if hit_value is not None:
        logger.info(
            f"ck/dvc cache hit for {owner_name}/{project_name} "
            f"(read {t_read * 1000:.0f}ms)"
        )
        return hit_value
    logger.info(
        f"ck/dvc cache miss for {owner_name}/{project_name} "
        f"(read {t_read * 1000:.0f}ms)"
    )
    t1 = time.perf_counter()
    ck_info = (_yaml_load(ck_bytes) or {}) if ck_bytes else {}
    # calkit.yaml can hold any YAML value, and only a mapping is usable
    if not isinstance(ck_info, dict):
        ck_info = {}
    normalize_ck_info_paths(ck_info)
    dvc_lock = (_yaml_load(dvc_bytes) or {}) if dvc_bytes else {}
    t_parse = time.perf_counter() - t1
    logger.info(f"Parsed calkit.yaml and dvc.lock in {t_parse * 1000:.0f}ms")
    t2 = time.perf_counter()
    fs = get_object_fs()
    dvc_lock_outs = expand_dvc_lock_outs(
        dvc_lock, owner_name=owner_name, project_name=project_name, fs=fs
    )
    t_expand = time.perf_counter() - t2
    logger.info(f"Expanded DVC lock outs in {t_expand * 1000:.0f}ms")
    zip_path_map: dict = {}
    if zip_bytes:
        try:
            zip_path_map = json.loads(zip_bytes) or {}
        except Exception:
            logger.warning("Failed to parse .calkit/zip/paths.json")
    result = CkInfoAndOuts(ck_info, dvc_lock_outs, zip_path_map, dvc_lock)
    with _ck_dvc_cache_lock:
        _ck_dvc_cache[cache_key] = (now, result)
        if len(_ck_dvc_cache) > _CK_DVC_CACHE_MAX:
            _ck_dvc_cache.popitem(last=False)
    return result


def get_contents_from_tree(
    project: Project,
    tree: RepoTree,
    path: str | None = None,
    ck_info: dict | None = None,
    dvc_lock_outs: dict | None = None,
    zip_path_map: dict | None = None,
    dvc_lock: dict | None = None,
) -> ContentsItem:
    owner_name = project.owner_account_name
    project_name = project.name
    # Prevent path traversal attacks
    if path is not None:
        if os.path.isabs(path):
            raise HTTPException(400, "Absolute paths are not allowed")
        if ".." in path.split(os.sep):
            raise HTTPException(400, "Path traversal is not allowed")
        # Callers can pass a path straight through from a link or an API
        # client, e.g. "./paper/main.pdf", but every key matched below is
        # clean. Normalizing to the repo root means the same as no path.
        path = normalize_artifact_path(path) or None
    # Reject unsafe symlinks
    if path is not None and tree.is_symlink(path):
        if not tree.is_safe_symlink(path):
            logger.warning(
                f"Unsafe symlink detected in {owner_name}/{project_name} "
                f"at {path}"
            )
            raise HTTPException(404)
    # Load calkit.yaml and dvc.lock outs if not pre-computed by the caller
    if ck_info is None or dvc_lock_outs is None or zip_path_map is None:
        ck_info, dvc_lock_outs, zip_path_map, dvc_lock = (
            get_ck_info_and_dvc_outs_from_tree(project, tree)
        )
    fs = get_object_fs()
    dvc_lock_out_dirs = [
        p for p, obj in dvc_lock_outs.items() if obj["type"] == "dir"
    ]
    ignore_paths = [".git", ".dvc/cache", ".dvc/tmp", ".dvc/config.local"]
    if path is not None and path in ignore_paths:
        raise HTTPException(404)
    # Let's restructure as a dictionary keyed by path
    categories_with_path = [
        "figures",
        "publications",
        "datasets",
        "references",
        "notebooks",
    ]
    ck_objects = {}
    for category, itemlist in ck_info.items():
        if category not in categories_with_path:
            continue
        if not isinstance(itemlist, list):
            logger.warning(
                f"{owner_name}/{project_name} {category} is not a list"
            )
            continue
        if category not in CATEGORIES_PLURAL_TO_SINGULAR:
            logger.warning(
                f"{owner_name}/{project_name} {category} not understood"
            )
            continue
        for item in itemlist:
            item["kind"] = CATEGORIES_PLURAL_TO_SINGULAR[category]
            ck_objects[item["path"]] = item
            # Handle files inside references objects
            if category == "references":
                ref_item_files = item.get("files", [])
                for rif in ref_item_files:
                    if "path" in rif:
                        ck_objects[rif["path"]] = dict(
                            kind="references item file",
                            references_path=item["path"],
                            path=rif["path"],
                            key=rif.get("key"),
                        )
    # Find any DVC outs for Calkit objects
    ck_outs = {}
    for p, obj in ck_objects.items():
        if p in dvc_lock_outs:
            ck_outs[p] = dvc_lock_outs[p]
        else:
            dvc_fp = p + ".dvc"
            if tree.is_file(dvc_fp):
                dvo = yaml.safe_load(tree.read_text(dvc_fp))["outs"][0]
                ck_outs[p] = dvo
            else:
                ck_outs[p] = None
    file_locks_by_path = {
        lock.path: ItemLock.model_validate(lock.model_dump())
        for lock in project.file_locks
    }
    # Build reverse map: zip_path -> workspace_path (for size lookup)
    zip_workspace_paths = set(zip_path_map.keys())
    # See if we're listing off a directory
    if path is None or tree.is_dir(path) or path in dvc_lock_out_dirs:
        logger.info(f"Getting contents of directory: {path}")
        dirname = "" if path is None else path
        contents = []
        if path not in dvc_lock_out_dirs:
            child_names = sorted(tree.listdir(path or None))
            paths = [os.path.join(dirname, n) for n in child_names]
        else:
            paths = []
        # Derive tracked paths from standalone .dvc pointer files (files
        # tracked with `dvc add`, not via a DVC pipeline stage in dvc.lock).
        dvc_pointer_outs: dict[str, dict] = {}
        for p in paths:
            if not p.endswith(".dvc"):
                continue
            # The DVC config directory is literally named ".dvc", which also
            # matches the suffix above. Skip directories so we only try to
            # read actual ".dvc" pointer files.
            if tree.is_dir(p):
                continue
            try:
                dvc_file_data = yaml.safe_load(tree.read_text(p))
                if not isinstance(dvc_file_data, dict):
                    continue
                outs = dvc_file_data.get("outs")
                out = outs[0] if isinstance(outs, list) and outs else {}
                out_path = out.get("path") if isinstance(out, dict) else None
                if isinstance(out_path, str) and out_path:
                    actual_path = os.path.normpath(
                        os.path.join(os.path.dirname(p), out_path)
                    )
                else:
                    actual_path = p[:-4]
                if not actual_path or actual_path in dvc_lock_outs:
                    continue
                dvc_pointer_outs[actual_path] = (
                    out if isinstance(out, dict) else {}
                )
            except Exception as e:
                logger.warning(f"Failed to read DVC pointer file {p}: {e}")
        dvc_paths = [
            p for p, obj in dvc_lock_outs.items() if obj["dirname"] == dirname
        ]
        all_paths = sorted(
            set(paths + dvc_paths + list(dvc_pointer_outs.keys()))
        )
        for p in all_paths:
            if p in ignore_paths:
                continue
            in_repo = tree.exists(p)
            # size and obj_type are set in each branch; pre-initialize for the
            # fallthrough `else` case where the path has no metadata source.
            size: int | None = None
            obj_type: str = "file"
            # Only DVC-tracked paths have one, and it must not carry over
            # from the previous path in the loop
            md5: str | None = None
            if in_repo:
                size = tree.size(p)
                obj_type = "file" if tree.is_file(p) else "dir"
                storage: str | None = "git"
            elif p in dvc_lock_outs:
                size = dvc_lock_outs[p].get("size")
                obj_type = dvc_lock_outs[p]["type"]
                md5 = dvc_lock_outs[p].get("md5")
                storage = "dvc"
            elif p in dvc_pointer_outs:
                dvc_out = dvc_pointer_outs[p]
                md5 = dvc_out.get("md5", "")
                size = dvc_out.get("size")
                obj_type = "dir" if md5.endswith(".dir") else "file"
                storage = "dvc"
            else:
                storage = None
            obj = dict(
                name=os.path.basename(p),
                path=p,
                size=size,
                in_repo=in_repo,
                lock=file_locks_by_path.get(p),
                type=obj_type,
                calkit_object=ck_objects.get(p),
                storage=storage,
                md5=md5,
            )
            contents.append(ContentsItem.model_validate(obj))
        for ck_path, ck_obj in ck_objects.items():
            if (
                os.path.dirname(ck_path) == dirname
                and ck_path not in all_paths
            ):
                dvc_out = ck_outs.get(ck_path) or {}
                contents.append(
                    ContentsItem.model_validate(
                        dict(
                            name=os.path.basename(ck_path),
                            path=ck_path,
                            in_repo=False,
                            size=dvc_out.get("size"),
                            type=(
                                "dir"
                                if dvc_out.get("md5", "").endswith(".dir")
                                else "file"
                            ),
                            calkit_object=ck_obj,
                            lock=file_locks_by_path.get(ck_path),
                            storage="dvc",
                        )
                    )
                )
        # Add virtual entries for dvc-zip mapped workspace paths
        existing_paths = {c.path for c in contents}
        for ws_path, zip_path in zip_path_map.items():
            if os.path.dirname(ws_path) != dirname:
                continue
            if ws_path in existing_paths:
                # Already present (e.g. unzipped in working tree); update storage
                for c in contents:
                    if c.path == ws_path:
                        c.storage = "dvc-zip"
                continue
            # Get size from the zip's .dvc pointer file
            size = None
            dvc_pointer = zip_path + ".dvc"
            if tree.is_file(dvc_pointer):
                try:
                    dvc_out = yaml.safe_load(tree.read_text(dvc_pointer))
                    size = dvc_out.get("outs", [{}])[0].get("size")
                except Exception:
                    pass
            contents.append(
                ContentsItem.model_validate(
                    dict(
                        name=os.path.basename(ws_path),
                        path=ws_path,
                        in_repo=False,
                        size=size,
                        type="dir",
                        calkit_object=ck_objects.get(ws_path),
                        lock=file_locks_by_path.get(ws_path),
                        storage="dvc-zip",
                    )
                )
            )
        contents.sort(key=lambda c: c.path)
        return ContentsItem(
            name=os.path.basename(dirname),
            path=dirname,
            type="dir",
            size=sum(c.size or 0 for c in contents),
            dir_items=contents,
            calkit_object=ck_objects.get(path),
            in_repo=tree.is_dir(dirname or None),
        )
    # We're looking for a file. Find the pipeline stage that produces it (if
    # any) so callers can link to it. dvc_lock is the raw dvc.lock (with its
    # per-stage outs), which resolves both exact outs and files inside a
    # directory output.
    producing_stage = find_stage_for_path(path, dvc_lock) if dvc_lock else None
    if tree.is_file(path):
        size = tree.size(path)
        url = None
        content = tree.read_bytes(path)
        if size > RETURN_CONTENT_SIZE_LIMIT:
            logger.info(f"{path} is greater than return size limit")
            md5 = hashlib.md5(content).hexdigest()
            fp = make_data_fpath(
                owner_name=owner_name,
                project_name=project_name,
                idx=md5[:2],
                md5=md5[2:],
            )
            if not fs.isfile(fp):
                logger.info(f"Writing {path} to object storage")
                with fs.open(fp, "wb") as f:
                    f.write(content)
                if settings.ENVIRONMENT != "local":
                    remove_gcs_content_type(fp)
            url = get_object_url(fp, fname=os.path.basename(path), fs=fs)
            content = None
        return ContentsItem.model_validate(
            dict(
                path=path,
                name=os.path.basename(path),
                size=size,
                type="file",
                in_repo=True,
                content=(
                    base64.b64encode(content).decode()
                    if content is not None
                    else None
                ),
                calkit_object=ck_objects.get(path),
                lock=file_locks_by_path.get(path),
                url=url,
                storage="git",
                stage=producing_stage,
            )
        )
    elif path in zip_workspace_paths:
        # dvc-zip mapped directory. Must take precedence over the
        # ck_objects branch below, since a dvc-zip workspace path may
        # also be registered as a dataset/publication artifact and
        # should still be labeled with its dvc-zip storage.
        zip_path = zip_path_map[path]
        dvc_pointer = zip_path + ".dvc"
        size = None
        if tree.is_file(dvc_pointer):
            try:
                dvc_out_data = yaml.safe_load(tree.read_text(dvc_pointer))
                size = dvc_out_data.get("outs", [{}])[0].get("size")
            except Exception:
                pass
        return ContentsItem.model_validate(
            dict(
                path=path,
                name=os.path.basename(path),
                size=size,
                type="dir",
                in_repo=False,
                calkit_object=ck_objects.get(path),
                lock=file_locks_by_path.get(path),
                storage="dvc-zip",
                stage=producing_stage,
            )
        )
    elif path in ck_objects:
        logger.info(f"Looking in CK objects for {path}")
        dvc_out = ck_outs.get(path) or {}
        size = dvc_out.get("size")
        md5 = dvc_out.get("md5", "")
        dvc_fpath = dvc_out.get("path")
        dvc_type = "dir" if md5.endswith(".dir") else "file"
        content = None
        url = None
        if md5:
            fp = get_data_fpath_for_md5(
                owner_name=owner_name,
                project_name=project_name,
                md5=md5,
                fs=fs,
            )
            if fp is not None:
                url = get_object_url(
                    fp, fname=os.path.basename(dvc_fpath), fs=fs
                )
            # No fs.exists() guard: get_data_fpath_for_md5 only returns a path
            # it has already confirmed exists, so re-checking is a wasted
            # round trip on every artifact.
            if (
                size is not None
                and size <= RETURN_CONTENT_SIZE_LIMIT
                and fp is not None
                and not path.endswith(".h5")
                and not path.endswith(".parquet")
            ):
                with fs.open(fp, "rb") as f:
                    content = base64.b64encode(f.read()).decode()
        return ContentsItem.model_validate(
            dict(
                path=path,
                name=os.path.basename(path),
                size=size,
                type=dvc_type,
                in_repo=False,
                content=content,
                url=url,
                calkit_object=ck_objects[path],
                lock=file_locks_by_path.get(path),
                storage="dvc",
                stage=producing_stage,
            )
        )
    else:
        # Do we have a DVC file for this path?
        dvc_pointer = path + ".dvc"
        if path in dvc_lock_outs or tree.is_file(dvc_pointer):
            if tree.is_file(dvc_pointer):
                dvc_out = _yaml_load(tree.read_text(dvc_pointer))["outs"][0]
            else:
                dvc_out = dvc_lock_outs[path]
            md5 = dvc_out["md5"]
            fp = get_data_fpath_for_md5(
                owner_name=owner_name,
                project_name=project_name,
                md5=md5,
                fs=fs,
            )
            url = (
                get_object_url(fp, fname=os.path.basename(path), fs=fs)
                if fp
                else None
            )
            size = dvc_out.get("size")
            dvc_type = "dir" if md5.endswith(".dir") else "file"
            # Read small files inline from object storage, mirroring the
            # Calkit-object branch above, so callers can use their content
            # without a second round trip through the presigned URL.
            # As above, fp is already known to exist, so no fs.exists() guard.
            content = None
            if (
                size is not None
                and size <= RETURN_CONTENT_SIZE_LIMIT
                and fp is not None
                and not path.endswith(".h5")
                and not path.endswith(".parquet")
            ):
                with fs.open(fp, "rb") as f:
                    content = base64.b64encode(f.read()).decode()
            # TODO: If this is a directory, list dir_items
            return ContentsItem.model_validate(
                dict(
                    path=path,
                    name=os.path.basename(path),
                    size=size,
                    type=dvc_type,
                    in_repo=False,
                    content=content,
                    url=url,
                    lock=file_locks_by_path.get(path),
                    storage="dvc",
                    stage=producing_stage,
                )
            )
        raise HTTPException(404)


def get_ck_info_for_ref(
    project: Project,
    repo: git.Repo,
    ref: str | None = None,
    process_includes: bool = False,
    read_only: bool = False,
) -> dict:
    """Return Calkit metadata for the requested ref, if provided.

    Always returns a dict; an empty one when calkit.yaml doesn't exist at
    the ref or doesn't hold a mapping. Declared artifact paths come back
    normalized (see ``normalize_ck_info_paths``), so callers must not write
    the result back to calkit.yaml.

    Pass ``read_only=True`` only when the caller won't write the result back;
    see ``get_ck_info_from_repo``.
    """
    if ref is None:
        return normalize_ck_info_paths(
            get_ck_info_from_repo(
                repo=repo,
                process_includes=process_includes,
                read_only=read_only,
            )
        )
    try:
        ck_item = get_contents_from_repo(
            project=project,
            repo=repo,
            path="calkit.yaml",
            ref=ref,
        )
    except HTTPException as e:
        if e.status_code == 404:
            return {}
        raise
    if ck_item.content is None:
        return {}
    ck_info = yaml.safe_load(base64.b64decode(ck_item.content))
    # calkit.yaml can hold any YAML value (empty, a list, a string); only a
    # mapping is usable project metadata
    if not isinstance(ck_info, dict):
        return {}
    return normalize_ck_info_paths(ck_info)


def get_dvc_pipeline_for_ref(
    repo: git.Repo,
    ref: str | None = None,
) -> dict:
    """Return the parsed dvc.yaml for the requested ref, if provided.

    ``get_dvc_pipeline_from_repo`` reads the live working tree, which always
    reflects the default branch (``get_repo`` only fetches a ref, it does
    not check it out), so it must not be used for ref-scoped reads.
    """
    if ref is None:
        return get_dvc_pipeline_from_repo(repo)
    tree = get_repo_tree_for_ref(repo, ref)
    if not tree.is_file("dvc.yaml"):
        return {}
    return ryaml.load(tree.read_text("dvc.yaml")) or {}


def get_figure_from_repo(
    project: Project,
    repo: git.Repo,
    path: str,
    ref: str | None = None,
) -> Figure:
    ck_info = get_ck_info_for_ref(project=project, repo=repo, ref=ref)
    figures = ck_info.get("figures", [])
    # Get the figure content (will be base64-encoded)
    for fig in figures:
        if fig.get("path") == path:
            item = get_contents_from_repo(
                project=project,
                repo=repo,
                path=fig["path"],
                ref=ref,
            )
            fig["content"] = item.content
            fig["url"] = item.url
            fig["storage"] = item.storage
            return Figure.model_validate(fig)
    raise HTTPException(404, "Figure not found")


def get_publication_from_repo(
    project: Project,
    repo: git.Repo,
    path: str,
    ref: str | None = None,
) -> Publication:
    ck_info = get_ck_info_for_ref(project=project, repo=repo, ref=ref)
    publications = ck_info.get("publications", [])
    # Get the figure content (will be base64-encoded)
    for pub in publications:
        if pub.get("path") == path:
            item = get_contents_from_repo(
                project=project,
                repo=repo,
                path=pub["path"],
                ref=ref,
            )
            pub["content"] = item.content
            pub["storage"] = item.storage
            # Prioritize URL defined in the publication itself
            if "url" not in pub:
                pub["url"] = item.url
            if pub.get("stage"):
                pub["calkit_stage"] = (
                    (ck_info.get("pipeline") or {})
                    .get("stages", {})
                    .get(pub["stage"])
                )
            return Publication.model_validate(pub)
    raise HTTPException(404, "Publication not found")


def get_notebook_from_repo(
    project: Project,
    repo: git.Repo,
    path: str,
    ref: str | None = None,
) -> Notebook:
    """Get a notebook from a project's repo, fetching its HTML export if it
    exists.
    """
    ck_info = get_ck_info_for_ref(project=project, repo=repo, ref=ref)
    notebooks = ck_info.get("notebooks", [])
    notebook = None
    for nb in notebooks:
        if nb.get("path") == path:
            notebook = nb
            break
    # Notebooks don't need to be declared in the ``notebooks`` list, e.g., one
    # defined as a jupyter-notebook pipeline stage, so fall back to the path
    # itself and let fetching its contents below decide whether it exists
    if notebook is None:
        notebook = {"path": path}
    # Associate with a jupyter-notebook stage if one runs this notebook
    if not notebook.get("stage"):
        stages = (ck_info.get("pipeline") or {}).get("stages", {}) or {}
        for stage_name, stage in stages.items():
            if (
                isinstance(stage, dict)
                and stage.get("kind") == "jupyter-notebook"
                and stage.get("notebook_path") == path
            ):
                notebook["stage"] = stage_name
                break
    item = get_contents_from_repo(
        project=project,
        repo=repo,
        path=path,
        ref=ref,
    )
    try:
        # If the notebook has HTML output, return that
        html_path = get_executed_notebook_path(notebook_path=path, to="html")
        html_item = get_contents_from_repo(
            project=project,
            repo=repo,
            path=html_path,
            ref=ref,
        )
        item = html_item
        notebook["output_format"] = "html"
    except HTTPException as e:
        logger.info(f"Notebook HTML does not exist at {html_path}: {e}")
    notebook["url"] = item.url
    notebook["content"] = item.content
    notebook["storage"] = item.storage
    # Figure out the output format from the URL content disposition
    if item.url is not None:
        params = params_from_url(item.url)
        rcd = params.get("response-content-disposition")
        if rcd is not None:
            if rcd[0].endswith(".ipynb"):
                notebook["output_format"] = "notebook"
            elif rcd[0].endswith(".html"):
                notebook["output_format"] = "html"
    # Default to the raw notebook if no HTML version was found
    if not notebook.get("output_format") and item.content and not item.url:
        notebook["output_format"] = "notebook"
    return Notebook.model_validate(notebook)
