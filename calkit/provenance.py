"""Functionality for handling artifact provenance."""

from __future__ import annotations

import dataclasses
import functools
import os
import posixpath
import re
from collections.abc import Callable

# The artifact kinds whose provenance is *checked*. Each entry must say
# where it came from: a pipeline stage, an import, or the person who
# created it, e.g., by collecting or measuring the data or drawing the
# figure.
#
# Deliberately not the same set as the kinds an import can be *recorded*
# in, which is read off the models by ``get_artifact_types_with_imports``.
# A notebook can carry an ``imported_from`` and be refreshed like anything
# else, but notebooks are usually written by a project's own authors, so
# holding every one of them to a provenance record would report gaps that
# aren't.
PROVENANCE_ARTIFACT_TYPES = [
    "datasets",
    "figures",
    "publications",
    "tables",
    "presentations",
    "misc",
]


@functools.cache
def get_artifact_types_with_imports() -> list[str]:
    """The ``calkit.yaml`` lists whose entries can record an import.

    Read off the models, so a kind that gains ``imported_from`` is
    searched without anything here changing. Wider than
    :data:`PROVENANCE_ARTIFACT_TYPES`, which is about which kinds are held
    to having provenance at all --- an entry that says where it came from
    is honored wherever it is written, whether or not its kind is one we
    would report for staying silent.
    """
    from typing import get_args

    from pydantic import BaseModel

    from calkit.models.core import ProjectInfo

    types = []
    for kind, field in ProjectInfo.model_fields.items():
        for arg in get_args(field.annotation):
            for model in (arg, *get_args(arg)):
                if (
                    isinstance(model, type)
                    and issubclass(model, BaseModel)
                    and "imported_from" in model.model_fields
                ):
                    types.append(kind)
                    break
            else:
                continue
            break
    return types


@functools.cache
def get_importable_artifact_types() -> list[str]:
    """The kinds whose model takes ``imported_from``.

    Read off the models rather than listed by hand: whether a kind can
    record an import is a fact about its model, and a copy of that fact
    would keep validating long after it stopped being true. Adding the
    field to tables or presentations is then all it takes to make them
    importable.

    Computed on demand rather than at import: reading the models pulls in
    pydantic, and this module is imported on every CLI invocation.
    """
    from typing import get_args

    from pydantic import BaseModel

    from calkit.models.core import ProjectInfo

    types = []
    for kind in PROVENANCE_ARTIFACT_TYPES:
        field = ProjectInfo.model_fields.get(kind)
        if field is None:
            continue
        # Each list is annotated as list[<Model>], possibly through a
        # union of the imported and non-imported forms
        for arg in get_args(field.annotation):
            for model in (arg, *get_args(arg)):
                if (
                    isinstance(model, type)
                    and issubclass(model, BaseModel)
                    and "imported_from" in model.model_fields
                ):
                    types.append(kind)
                    break
            else:
                continue
            break
    return types


# Where the resolved state of each import is recorded: the commit a Git
# source actually landed on, a checksum of what was fetched, and when.
# Committed, so everyone cloning the project gets the same bytes, the way
# they do from ``dvc.lock`` or an environment's lock file --- the same
# reason ``.calkit/overleaf-sync.json`` is committed, since two people
# syncing the same Overleaf project have to agree on where they last
# were. What this file records is one-way: an import has no other side to
# reconcile with, so there is only ever what was fetched.
IMPORT_LOCK_FPATH = os.path.join(".calkit", "imports.json")


def read_import_locks(wdir: str | None = None) -> dict:
    """Read the recorded state of every import, keyed by path."""
    import json

    fpath = (
        os.path.join(wdir, IMPORT_LOCK_FPATH) if wdir else (IMPORT_LOCK_FPATH)
    )
    if not os.path.isfile(fpath):
        return {}
    with open(fpath) as f:
        try:
            locks = json.load(f)
        except ValueError as e:
            # Reported rather than treated as absent: the next write would
            # replace the file, so swallowing this turns a file somebody
            # can still fix into every import losing its recorded state
            raise ValueError(
                f"{fpath} is not valid JSON ({e}); fix or delete it -- "
                "treating it as empty would discard every import's "
                "recorded state on the next write"
            )
    # Early versions wrote a list of Zenodo import events here. Nothing
    # ever read it, so it is treated as absent rather than migrated.
    if not isinstance(locks, dict):
        return {}
    # Before entries had a 'kind', the commit was a bare 'rev', which now
    # reads as the 'git_rev' those entries used once renamed
    for lock in locks.values():
        if (
            isinstance(lock, dict)
            and "kind" not in lock
            and "rev" in lock
            and "git_rev" not in lock
        ):
            lock["git_rev"] = lock.pop("rev")
    return locks


def get_locked_rev(lock: dict | None) -> str | None:
    """The commit a lock entry says its import was fetched at.

    A Git repo's is its ``rev``; a Calkit project, which isn't a Git repo,
    records it as ``git_rev``, as does an entry from before lock entries had
    a ``kind``.
    """
    lock = lock or {}
    rev = lock.get("rev") if lock.get("kind") == "git" else lock.get("git_rev")
    return rev if isinstance(rev, str) else None


def lock_matches_source(lock: dict | None, imported_from: dict) -> bool:
    """Whether a lock entry was fetched from what ``imported_from`` names
    now, so an edited source can be told from one that was synced.

    An entry from before lock entries recorded their source can't be
    compared, and is taken to match.
    """
    import calkit

    lock = lock or {}
    kind = lock.get("kind")
    if kind is None:
        return True
    if kind == "git":
        git = git_source(imported_from)
        return git is not None and (
            git.get("git_repo_url"),
            git.get("path"),
            git.get("git_ref"),
        ) == (lock.get("repo_url"), lock.get("path"), lock.get("ref"))
    if kind == "calkit":
        return (
            imported_from.get("project"),
            imported_from.get("path"),
            imported_from.get("git_ref"),
        ) == (lock.get("project"), lock.get("path"), lock.get("git_ref")) and (
            lock.get("hub") in (None, calkit.hub.get_hub_url())
        )
    if kind == "url":
        return imported_from.get("url") == lock.get("url")
    return True


def write_import_lock(
    path: str, lock: dict | None, wdir: str | None = None
) -> str:
    """Record what an import resolved to, or drop it with ``lock=None``.

    Returns the lock file's path, so the caller can commit it alongside
    whatever it fetched.
    """
    import json

    fpath = (
        os.path.join(wdir, IMPORT_LOCK_FPATH) if wdir else (IMPORT_LOCK_FPATH)
    )
    locks = read_import_locks(wdir=wdir)
    if lock is None:
        locks.pop(path, None)
    else:
        # 'fetched' says when this version arrived, not when it was last
        # checked for. Refreshing an unchanged import must leave the file
        # alone, or every check would be a commit and nothing would ever
        # read as up to date.
        previous = locks.get(path)
        if previous is not None and {
            k: v for k, v in previous.items() if k != "fetched"
        } == {k: v for k, v in lock.items() if k != "fetched"}:
            lock = dict(lock)
            if "fetched" in previous:
                lock["fetched"] = previous["fetched"]
        locks[path] = lock
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    # Sorted so the file is stable across runs and diffs read as changes to
    # one import rather than a reshuffle
    # newline="\n" so the file is byte-identical on every platform; it is
    # committed, and CRLF on Windows would churn the diff for everyone else
    with open(fpath, "w", newline="\n") as f:
        json.dump(locks, f, indent=2, sort_keys=True)
        f.write("\n")
    return fpath


# Named in the recorded value rather than in the key it is stored under,
# so it can change without the lock file's shape changing --- and so a
# hash written by another version is recognizable as one this version
# can't compare against.
HASH_ALGORITHM = "sha256"


def hash_path(path: str) -> str | None:
    """Checksum what is at ``path``, for telling whether it has changed.

    A directory is hashed over its entries as well as their contents, so a
    renamed or removed file changes the digest. Symlinks are hashed by
    their target rather than followed, since following one would reach
    outside the tree. Returns None only when there is nothing there.

    A Git source can bring in a directory, and refreshing one replaces it
    wholesale, so it needs a checksum for the same reason a file does:
    without one, an edit inside it would be deleted without warning.
    """
    import hashlib

    digest = hashlib.sha256()

    def add_file(fpath: str) -> None:
        with open(fpath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                digest.update(chunk)

    if os.path.islink(path):
        digest.update(b"link\0" + os.readlink(path).encode())
    elif os.path.isfile(path):
        add_file(path)
    elif os.path.isdir(path):
        # Sorted so the digest doesn't depend on directory order, and
        # names are hashed too so a rename is a change
        for root, dirs, files in os.walk(path):
            dirs.sort()
            for name in sorted(files + dirs):
                full = os.path.join(root, name)
                rel = os.path.relpath(full, path).replace(os.sep, "/")
                digest.update(rel.encode() + b"\0")
                if os.path.islink(full):
                    digest.update(b"link\0" + os.readlink(full).encode())
                elif os.path.isfile(full):
                    add_file(full)
    else:
        return None
    return f"{HASH_ALGORITHM}:{digest.hexdigest()}"


def local_edit(path: str, lock: dict | None) -> bool:
    """Whether what is on disk differs from what the import last fetched.

    False when there is nothing to compare against -- an entry written
    before hashes were recorded, or one recorded with an algorithm this
    version doesn't compute -- since a refresh that can't tell shouldn't
    claim it can.
    """
    recorded = (lock or {}).get("hash")
    if not isinstance(recorded, str) or not os.path.exists(path):
        return False
    # The algorithm is named in the value, so a file hashed by a version
    # that used a different one is not mistaken for an edited file
    algorithm = recorded.split(":", 1)[0]
    if algorithm != HASH_ALGORITHM:
        return False
    return hash_path(path) != recorded


def check_project_path(path: str) -> str:
    """Return why ``path`` isn't safe to write in the project, or "".

    An import writes to this path and later hands it to ``git add``, so a
    hand-written ``../..`` or an absolute path would put a file outside
    the repo and then fail confusingly. Symlinks are resolved, since one
    inside the project can still point out of it.
    """
    if os.path.isabs(path):
        return f"'{path}' must be a path inside the project, not absolute"
    root = os.path.realpath(os.getcwd())
    full = os.path.realpath(os.path.join(root, path))
    if full != root and os.path.commonpath([root, full]) != root:
        return f"'{path}' points outside the project"
    return ""


def artifact_kind_to_list(kind: str) -> str:
    """The ``calkit.yaml`` list a singular artifact kind is recorded in.

    Kinds are named in the singular where a person types one -- a figure,
    a dataset -- and the lists holding them are plural. ``misc`` is
    already a mass noun, so it is spelled the same either way.
    """
    return kind if kind == "misc" else kind + "s"


@functools.cache
def get_importable_artifact_kinds() -> list[str]:
    """Singular names of the kinds an import can be recorded as.

    The same set as :func:`get_importable_artifact_types`, spelled the way
    the CLI takes them, so the two can't name different things.
    """
    return [
        kind if kind == "misc" else kind.removesuffix("s")
        for kind in get_importable_artifact_types()
    ]


# Formats exported from something else, e.g., a plotting script or an
# image editor's own file, rather than made directly, so a person can't be
# their origin: they're imported or produced by the pipeline. Photos and
# instrument images, e.g., JPEG and TIFF, and SVG drawn in an editor that
# saves it natively, can be made by a person.
EXPORTED_EXTENSIONS = {".png", ".gif", ".webp", ".bmp", ".pdf", ".eps"}


def can_be_created_by_person(path: str) -> bool:
    """Whether ``created_by`` can account for what's at ``path``."""
    return posixpath.splitext(path)[1].lower() not in EXPORTED_EXTENSIONS


def import_is_checkable(imported_from: object) -> bool:
    """Whether ``imported_from`` names a source someone else can look at,
    rather than only describing one.
    """
    if isinstance(imported_from, str):
        try:
            imported_from = source_from_location(imported_from)
        except ValueError:
            return False
    return isinstance(imported_from, dict) and any(
        imported_from.get(k) for k in ("git_repo_url", "project", "url", "doi")
    )


def how_to_define_origin(path: str) -> str:
    """Say what defines the origin of ``path``, for a message."""
    if can_be_created_by_person(path):
        return (
            "record it in calkit.yaml with imported_from or created_by, "
            "or add the stage that makes it"
        )
    return (
        "it's exported from something else, so add the stage that makes "
        "it, or record it in calkit.yaml with imported_from"
    )


def get_import_statuses(ck_info: dict, check_git: bool = True) -> list[dict]:
    """Say, for each imported file, whether it's as imported and whether its
    source has moved on.

    Each status is a dict with the file's ``path``, a description of its
    ``source``, the ``git_rev`` it was fetched at, if recorded, and one of
    these ``status`` values, with a ``detail`` saying more where there is
    more to say:

    - ``missing``: the file isn't there;
    - ``edited``: it's been changed since it was fetched;
    - ``source-changed``: calkit.yaml names a different source than the one
      it was fetched from;
    - ``up-to-date``: the source has the same file, or is pinned to the
      commit it was fetched at;
    - ``update-available``: a Calkit project has a different file there, or
      a URL's server says its file has changed;
    - ``source-moved``: a Git repo's branch or tag is at a different commit,
      which may or may not have changed the file, since telling would mean
      fetching it;
    - ``unknown``: it couldn't be told, e.g., for a URL whose server gave
      nothing to compare, or when offline.

    ``check_git=False`` leaves Git repos as ``unknown`` rather than asking
    them, for a check that should be quick.
    """
    import base64
    import hashlib
    import subprocess

    import requests
    from requests.exceptions import ConnectionError, Timeout

    import calkit

    unreachable = "the source couldn't be reached"
    locks = read_import_locks()
    statuses: list[dict] = []
    offline = False
    for kind in get_artifact_types_with_imports():
        entries = ck_info.get(kind)
        for entry in entries if isinstance(entries, list) else []:
            source = (
                entry.get("imported_from") if isinstance(entry, dict) else None
            )
            if not isinstance(source, dict) or not entry.get("path"):
                continue
            path = str(entry["path"])
            lock = locks.get(path) or {}
            git_rev = get_locked_rev(lock)
            status = {
                "path": path,
                "source": describe_source(source),
                "git_rev": git_rev,
                "status": "unknown",
                "detail": None,
            }
            statuses.append(status)
            ref = source.get("git_ref")
            git = git_source(source)
            if not os.path.exists(path):
                status["status"] = "missing"
                continue
            if local_edit(path, lock):
                status["status"] = "edited"
                continue
            if not lock_matches_source(lock, source):
                status["status"] = "source-changed"
                status["detail"] = "calkit.yaml names a different source"
                continue
            # A commit can't move, so an import pinned to one is current
            if (
                isinstance(ref, str)
                and git_rev is not None
                and re.fullmatch(r"[0-9a-f]{7,40}", ref)
                and git_rev.startswith(ref)
            ):
                status["status"] = "up-to-date"
                status["detail"] = f"pinned to {ref}"
                continue
            if offline:
                status["detail"] = unreachable
                continue
            if source.get("project") and source.get("path"):
                try:
                    contents = calkit.hub.get(
                        f"/projects/{source['project']}/contents/"
                        f"{source['path']}",
                        params={"ref": ref} if ref else None,
                        max_retries=0,
                        allow_login=False,
                        timeout=(5, 30),
                    )
                except (ConnectionError, Timeout):
                    # The rest would fail the same way, one timeout at a time
                    offline = True
                    status["detail"] = unreachable
                    continue
                except Exception as e:
                    status["detail"] = f"the source couldn't be read: {e}"
                    continue
                latest = contents.get("commit_sha")
                # The same commit can't hold a different file
                if git_rev and latest == git_rev:
                    status["status"] = "up-to-date"
                    continue
                content = contents.get("content")
                recorded = lock.get("hash")
                if content is None or not isinstance(recorded, str):
                    status["detail"] = (
                        "nothing recorded to compare against"
                        if content is not None
                        else "the source serves it as a link to download"
                    )
                    continue
                digest = hashlib.sha256(base64.b64decode(content)).hexdigest()
                same = f"{HASH_ALGORITHM}:{digest}" == recorded
                status["status"] = "up-to-date" if same else "update-available"
                if not same and latest:
                    status["detail"] = f"at {latest[:9]}"
                continue
            if git is not None:
                if not check_git:
                    continue
                if git_rev is None:
                    status["detail"] = (
                        "no commit was recorded when it was fetched"
                    )
                    continue
                wanted = ref or "HEAD"
                try:
                    # The peeled ref too, so an annotated tag gives the commit
                    # it points to rather than the tag object
                    out = subprocess.run(
                        [
                            "git",
                            "ls-remote",
                            str(git["git_repo_url"]),
                            wanted,
                            wanted + "^{}",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=os.environ | {"GIT_TERMINAL_PROMPT": "0"},
                    )
                except (subprocess.TimeoutExpired, OSError):
                    offline = True
                    status["detail"] = unreachable
                    continue
                # Each line is a commit and the ref it's at
                refs: dict[str, str] = {}
                for line in out.stdout.splitlines():
                    sha, _, name = line.partition("\t")
                    if name:
                        refs[name] = sha
                peeled = [
                    sha for name, sha in refs.items() if name.endswith("^{}")
                ]
                if out.returncode != 0 or not refs:
                    status["detail"] = (
                        f"'{wanted}' couldn't be found in the repo"
                    )
                    continue
                latest = peeled[0] if peeled else next(iter(refs.values()))
                if latest == git_rev:
                    status["status"] = "up-to-date"
                else:
                    status["status"] = "source-moved"
                    status["detail"] = f"{wanted} is at {latest[:9]}"
                continue
            if source.get("url"):
                etag = lock.get("etag")
                modified = lock.get("last_modified")
                if not etag and not modified:
                    status["detail"] = "its server gave nothing to compare"
                    continue
                try:
                    resp = requests.head(
                        str(source["url"]),
                        allow_redirects=True,
                        timeout=(5, 30),
                    )
                except (ConnectionError, Timeout):
                    offline = True
                    status["detail"] = unreachable
                    continue
                except requests.RequestException as e:
                    status["detail"] = f"the source couldn't be read: {e}"
                    continue
                now = (
                    ("ETag", resp.headers.get("ETag"), etag)
                    if etag
                    else (
                        "Last-Modified",
                        resp.headers.get("Last-Modified"),
                        modified,
                    )
                )
                if not resp.ok or now[1] is None:
                    status["detail"] = f"its server no longer gives a {now[0]}"
                elif now[1] == now[2]:
                    status["status"] = "up-to-date"
                else:
                    status["status"] = "update-available"
                    status["detail"] = f"its {now[0]} changed"
                continue
            status["detail"] = "it can't be fetched again"
    return statuses


def get_imports_with_updates(ck_info: dict) -> list[str]:
    """Paths of files imported from Calkit projects whose source now has a
    different version than was fetched, for a quick check that says nothing
    when it can't tell."""
    # Only project imports are looked at, so nothing else is hashed
    projects_only = {
        kind: [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("imported_from"), dict)
            and entry["imported_from"].get("project")
        ]
        for kind, entries in ck_info.items()
        if kind in get_artifact_types_with_imports()
        and isinstance(entries, list)
    }
    return [
        s["path"]
        for s in get_import_statuses(projects_only, check_git=False)
        if s["status"] == "update-available"
    ]


def has_provenance(artifact: dict) -> bool:
    """Return whether an artifact entry records where it came from.

    A stage and an import are the stronger forms, but ``created_by`` counts
    too: a dataset someone measured, or a schematic someone drew, is
    accounted for even though there's nothing upstream to point at. It
    doesn't for a format that's exported rather than made, e.g., a PNG.
    The field names in ``calkit.reproducibility.ReproCheck`` predate
    attribution and are kept so callers reading them keep working.
    """
    if artifact.get("stage") is not None:
        return True
    if artifact.get("imported_from") is not None:
        return True
    return artifact.get("created_by") is not None and can_be_created_by_person(
        str(artifact.get("path", ""))
    )


def find_artifact(ck_info: dict, path: str) -> tuple[str, dict] | None:
    """Find the entry recorded at ``path``, whichever list it's in.

    Returns the list's name and the entry, so the caller can edit it in
    place.
    """
    for kind in get_artifact_types_with_imports():
        for entry in ck_info.get(kind, []) or []:
            if isinstance(entry, dict) and entry.get("path") == path:
                return kind, entry
    return None


# Hosts whose file URLs name a Git repo, a revision, and a path within it,
# so a link copied out of the browser can be imported as the Git source it
# actually is rather than as an HTML page that happens to contain the file.
_GIT_FORGE_HOSTS = ("github.com", "gitlab.com", "raw.githubusercontent.com")
# The segment that separates the ref from the path in a forge URL. GitLab
# additionally puts '/-/' before it, since its group paths nest.
_FORGE_REF_MARKERS = ("blob", "raw", "tree", "blame", "src")


def _git_source_from_url(url: str, ref: str | None = None) -> dict | None:
    """Read a Git repo, revision, and path out of a forge URL.

    Returns None for a URL that isn't one, which is then just a URL to
    download. Guessing is confined to hosts whose layout is known: for
    anything else, the bytes at the address are what was asked for.

    A ref can contain slashes, and the URL doesn't say where it ends and
    the path begins. It's taken to be one segment unless ``ref`` says
    what it is, in which case the path is whatever follows it.
    """
    from urllib.parse import unquote, urlsplit

    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    if host not in _GIT_FORGE_HOSTS:
        return None
    # Decoded, since a browser writes a space as '%20' and the checkout
    # doesn't
    segments = [unquote(s) for s in parts.path.split("/") if s]
    # GitLab separates the repo from what you're looking at inside it with
    # '/-/', because its groups nest and there is otherwise no telling
    # where the repo path ends
    if "-" in segments:
        split_at = segments.index("-")
        repo_segments, rest = segments[:split_at], segments[split_at + 1 :]
    elif host == "raw.githubusercontent.com":
        # Always <owner>/<repo>/<ref>/<path>, with no marker segment
        if len(segments) < 3:
            return None
        repo_segments, rest = segments[:2], ["raw"] + segments[2:]
    else:
        if len(segments) < 2:
            return None
        repo_segments, rest = segments[:2], segments[2:]
    if not rest:
        return None
    url_ref: str | None = None
    if rest[0] in _FORGE_REF_MARKERS and len(rest) >= 3:
        url_ref, path_segments = rest[1], rest[2:]
        # GitHub's raw URLs spell a branch as 'refs/heads/<name>'
        if url_ref == "refs" and len(path_segments) >= 2:
            if path_segments[0] in ("heads", "tags"):
                url_ref, path_segments = path_segments[1], path_segments[2:]
        ref_segments = ref.split("/") if ref else []
        if len(ref_segments) > 1 and rest[1 : 1 + len(ref_segments)] == (
            ref_segments
        ):
            path_segments = rest[1 + len(ref_segments) :]
    else:
        # No revision named, e.g. a path written out by hand. The default
        # branch is what gets fetched, and the commit it resolves to is
        # what gets recorded.
        path_segments = rest
    if ref is None:
        ref = url_ref
    if not path_segments:
        return None
    scheme = parts.scheme or "https"
    forge_host = "github.com" if host == "raw.githubusercontent.com" else host
    repo = "/".join(repo_segments).removesuffix(".git")
    source: dict = {
        "git_repo_url": f"{scheme}://{forge_host}/{repo}.git",
        "path": "/".join(path_segments),
    }
    # Recorded as a 'git_ref' whether it names a branch, a tag, or a
    # commit. A commit is a thing to follow that happens never to move,
    # which is what keeps a deliberate pin pinned when refreshed.
    if ref is not None:
        source["git_ref"] = ref
    return source


# Schemes git understands that aren't HTTP. A clone URL is the most
# natural thing to paste, so it's recognized as the Git source it is
# rather than falling through to the Calkit-project reading, where
# 'git@github.com:o/r' would be sent to the hub as a project name.
_GIT_URL_SCHEMES = ("ssh://", "git://", "git+ssh://")
# The scp-like form, 'git@github.com:owner/repo/path'. The host is required
# to contain a dot so an ordinary relative path with a colon in it isn't
# mistaken for one.
_SCP_URL_RE = re.compile(
    r"^(?P<user>[^@/\s]+@)?(?P<host>[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+)"
    r":(?P<path>[^/].*)$"
)


def _git_source_from_ssh_url(url: str, ref: str | None = None) -> dict | None:
    """Read a repo and a path within it out of an SSH-style clone URL.

    Handles both the scp-like ``git@host:owner/repo/path`` and the
    ``ssh://git@host/owner/repo/path`` form, and returns None for anything
    that is neither.

    Unlike a forge's web URL, a clone URL has no marker saying where the
    repo ends and a path inside it begins, so the repo is taken to be the
    first two segments. That is right for GitHub and for GitLab projects
    that aren't in nested groups; for anything else, naming the repo with
    ``--git-repo`` says it exactly rather than leaving it to be guessed.
    """
    from urllib.parse import urlsplit

    scp_prefix = None
    if url.startswith(_GIT_URL_SCHEMES):
        parts = urlsplit(url)
        host = parts.netloc
        rest = parts.path.lstrip("/")
        scheme = parts.scheme
    else:
        match = _SCP_URL_RE.match(url)
        if match is None:
            return None
        host = (match.group("user") or "") + match.group("host")
        rest = match.group("path")
        scheme = None
        scp_prefix = host
    segments = [seg for seg in rest.split("/") if seg]
    if len(segments) < 2:
        return None
    repo_segments, path_segments = segments[:2], segments[2:]
    repo = "/".join(repo_segments).removesuffix(".git")
    # Written back in the form it was given, since that is what git was
    # going to be handed either way and what the person will recognize
    if scp_prefix is not None:
        repo_url = f"{scp_prefix}:{repo}.git"
    else:
        repo_url = f"{scheme}://{host}/{repo}.git"
    source: dict = {"git_repo_url": repo_url}
    if path_segments:
        source["path"] = "/".join(path_segments)
    if ref is not None:
        source["git_ref"] = ref
    return source


def _project_source_from_hub_url(
    location: str, ref: str | None = None
) -> dict | None:
    """Read a project source out of a link to a file on the hub, or None.

    Both the address a file's page shows, e.g.,
    ``https://calkit.io/owner/project/files?path=fig.png&ref=v1``, and the
    shorter ``calkit.io/owner/project/fig.png`` are read, with or without
    a scheme. An explicit ``ref`` overrides one in the link.
    """
    from urllib.parse import parse_qs, urlsplit

    import calkit.hub

    has_scheme = location.startswith(("http://", "https://"))
    parts = urlsplit(location if has_scheme else "https://" + location)
    host = (parts.hostname or "").lower()
    if not host:
        return None
    active_host = urlsplit(calkit.hub.get_hub_url()).hostname
    if host != active_host:
        # A link to another built-in hub would be fetched from the active
        # one, which may not have the project or have a different one
        others = {
            urlsplit(url).hostname for url in calkit.hub.HUB_URLS.values()
        }
        if host in others and host != "localhost":
            raise ValueError(
                f"'{location}' links to {host}, but this project uses the "
                f"hub at {calkit.hub.get_hub_url()}"
            )
        return None
    segments = [seg for seg in parts.path.split("/") if seg]
    if len(segments) < 2:
        raise ValueError(f"'{location}' doesn't name a project on the hub")
    project = "/".join(segments[:2])
    query = parse_qs(parts.query)
    path = "/".join(segments[2:])
    url_ref: str | None = None
    if segments[2:] == ["files"]:
        path = (query.get("path") or [""])[0].strip("/")
        url_ref = (query.get("ref") or [""])[0] or None
    if not path:
        raise ValueError(
            f"'{location}' links to the project {project}, not a file in it"
        )
    source: dict = {"project": project, "path": path}
    if ref or url_ref:
        source["git_ref"] = ref or url_ref
    return source


def source_from_location(
    location: str,
    git_repo: str | None = None,
    ref: str | None = None,
) -> dict:
    """Work out where a file is being imported from, from how it's written.

    ``location`` is a path inside ``git_repo`` when that's given, and
    otherwise a URL, an SSH clone URL like
    ``git@github.com:owner/repo/path``, a DOI, a link to a file on the hub,
    or a Calkit project path like ``someone/some-project/scripts/setup.sh``.
    An explicit ``ref`` names
    the branch, tag, or commit to follow, and overrides one read out of a
    URL. Without one, the repo's default branch is what gets fetched, now
    and whenever the import is refreshed.
    """
    if git_repo is not None:
        source: dict = {"git_repo_url": git_repo, "path": location}
        if ref is not None:
            source["git_ref"] = ref
        return source
    stripped = re.sub(
        r"^(https?://(dx\.)?doi\.org/|doi:)", "", location.strip(), flags=re.I
    )
    if re.fullmatch(r"10\.\d{4,9}/\S+", stripped):
        # Recognized rather than downloaded: a DOI resolves to a landing
        # page, so treating it as a plain URL would save the HTML and call
        # it the data. 'fetch' says what to use instead.
        return {"doi": stripped}
    hub_source = _project_source_from_hub_url(location, ref=ref)
    if hub_source is not None:
        return hub_source
    if location.startswith(("http://", "https://")):
        git_source = _git_source_from_url(location, ref=ref)
        if git_source is not None:
            return git_source
        # A link to a Zenodo record is that record, not a file. Read as the
        # DOI it stands for, since the two name the same thing and a record
        # is a landing page: downloading it would save the HTML and call it
        # the data, which is the mistake the DOI branch above exists to
        # prevent. Zenodo's version DOI is its record ID, which is how
        # 'calkit import zenodo' reads one in the other direction.
        record_match = re.match(
            r"^https?://(www\.)?zenodo\.org/records?/(?P<id>\d+)",
            location,
            flags=re.I,
        )
        if record_match is not None:
            return {"doi": f"10.5281/zenodo.{record_match.group('id')}"}
        return {"url": location}
    ssh_source = _git_source_from_ssh_url(location, ref=ref)
    if ssh_source is not None:
        return ssh_source
    segments = location.split("/")
    if len(segments) < 3:
        raise ValueError(
            f"Cannot tell where '{location}' comes from; give a URL, a DOI, "
            "a Calkit project path like someone/some-project/path/to/file, "
            "or a path inside a repo named with --git-repo"
        )
    source = {
        "project": "/".join(segments[:2]),
        "path": "/".join(segments[2:]),
    }
    if ref is not None:
        source["git_ref"] = ref
    return source


def git_source(imported_from: dict) -> dict | None:
    """Read a Git source out of an entry, or None if it isn't one."""
    if imported_from.get("git_repo_url") is None:
        return None
    return {
        k: imported_from.get(k)
        for k in ("git_repo_url", "path", "git_ref", "git_rev")
    }


def default_dest_path(imported_from: dict) -> str:
    """Where an import lands when no destination was given."""
    if (git := git_source(imported_from)) is not None:
        return os.path.basename(str(git.get("path") or ""))
    if imported_from.get("project") is not None:
        return str(imported_from.get("path") or "")
    if (url := imported_from.get("url")) is not None:
        from urllib.parse import urlsplit

        return os.path.basename(urlsplit(str(url)).path)
    return ""


def describe_source(imported_from: dict) -> str:
    """Name where an artifact came from, for a message to a person."""
    if (git := git_source(imported_from)) is not None:
        path = git.get("path")
        where = str(git.get("git_repo_url") or "a Git repo")
        return where + (f"/{path}" if path else "")
    if (project := imported_from.get("project")) is not None:
        path = imported_from.get("path")
        return str(project) + (f"/{path}" if path else "")
    if (url := imported_from.get("url")) is not None:
        return str(url)
    if (doi := imported_from.get("doi")) is not None:
        return f"doi:{doi}"
    return "an unrecorded source"


def _rev_exists(repo_dir: str, rev: str) -> bool:
    """Return whether ``rev`` names something in the clone at ``repo_dir``.

    The clone has no checkout and no local branches, so a branch is only
    there as ``origin/<name>``. That's what ``git checkout`` finds by
    DWIM, and it has to be looked for explicitly here: ``rev-parse``
    resolves ``refs/remotes/<name>``, which a branch called ``feature/foo``
    is not.
    """
    import subprocess

    for candidate in (rev, f"origin/{rev}"):
        if (
            subprocess.call(
                [
                    "git",
                    "-C",
                    repo_dir,
                    "rev-parse",
                    "--verify",
                    "--quiet",
                    candidate,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            == 0
        ):
            return True
    return False


def _widen_ref(repo_dir: str, ref: str, path: str) -> tuple[str, str] | None:
    """Move the ref/path boundary rightwards until the ref resolves.

    A forge URL for a branch called ``feature/foo`` reads as
    ``.../blob/feature/foo/scripts/a.sh``, and nothing in it says whether
    ``foo`` is the rest of the branch name or the first directory. The
    boundary is guessed at one segment when the URL is parsed; here, with
    the repo in hand, the guess can be checked and corrected.

    Returns the corrected ``(ref, path)``, or None if no split resolves.
    The shortest widening wins, so a repo with both ``feature`` and
    ``feature/foo`` keeps the reading the URL most likely meant.
    """
    segments = [s for s in path.split("/") if s]
    for n in range(1, len(segments)):
        candidate = "/".join([ref, *segments[:n]])
        rest = "/".join(segments[n:])
        if _ref_and_path_resolve(repo_dir, candidate, rest):
            return candidate, rest
    return None


def _ref_and_path_resolve(repo_dir: str, ref: str, path: str) -> bool:
    """Whether ``ref`` exists *and* holds ``path``.

    Checked as a pair. A repo with both ``feature`` and ``feature/foo``
    would otherwise stop at ``feature``, which resolves, and then look for
    a path that only exists on ``feature/foo`` -- the split has to be
    judged by whether the whole thing works, not by the ref alone.
    """
    import subprocess

    if not _rev_exists(repo_dir, ref):
        return False
    if not path:
        return True
    for candidate in (ref, f"origin/{ref}"):
        if (
            subprocess.call(
                [
                    "git",
                    "-C",
                    repo_dir,
                    "cat-file",
                    "-e",
                    f"{candidate}:{path}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            == 0
        ):
            return True
    return False


def _with_state(lock: dict, dest_path: str) -> dict:
    """Finish a lock entry with what every kind records: a checksum of what
    was fetched, and when. Fields with nothing to say are left out."""
    from datetime import datetime, timezone

    lock = {k: v for k, v in lock.items() if v is not None}
    checksum = hash_path(dest_path)
    if checksum is not None:
        lock["hash"] = checksum
    lock["fetched"] = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    return lock


def fetch(
    imported_from: dict, dest_path: str, source_entry: dict | None = None
) -> tuple[dict, dict]:
    """Download what an ``imported_from`` entry points at, to ``dest_path``.

    Returns the entry as it should now be recorded, and separately what the
    fetch resolved to: the source as it was used, under a ``kind`` of
    ``git``, ``calkit``, or ``url``, what that source was at, e.g., the commit
    a Git repo landed on or a URL's ``ETag``, a checksum of the file, and
    when. The first belongs in ``calkit.yaml`` because a person wrote it;
    the second belongs in ``.calkit/imports.json`` because the tool worked
    it out, like any lock file, which is why it repeats the source.

    What gets fetched is the source's ``ref``---a branch, a tag, or a
    commit---or the repo's default branch when it names none. The recorded
    commit is the answer, never the question: refreshing an import is
    asking where the thing it follows is now, and reading the last answer
    back would make that a no-op.

    Whatever is at ``dest_path`` is replaced. This is a one-way copy from
    the source, not a merge: an import is a statement about where a file
    came from, and a local edit that survived it would make that false.

    ``source_entry``, if given, is filled with the source project's own
    entry for the file, e.g., a figure's title and description, when it has
    one.
    """
    import shutil
    import subprocess
    import tempfile

    imported_from = dict(imported_from)
    lock: dict = {}
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    if (git := git_source(imported_from)) is not None:
        repo_url = git.get("git_repo_url")
        if not repo_url:
            raise ValueError("Git source has no 'repo_url' to fetch from")
        src_path = git.get("path")
        if not src_path:
            raise ValueError(
                "Git source has no 'path'; importing a whole repo is what a "
                "Git submodule is for"
            )
        # What to check out. Not 'git_rev': that records what a previous fetch
        # returned, so using it here would make every refresh return the
        # same thing it did last time. Nothing named means the repo's
        # default branch.
        target = git.get("git_ref")
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Blobless and checkout-less, so a big repo costs about as
            # little as fetching one file from it can
            clone_cmd = [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                "--quiet",
                repo_url,
                tmp_dir,
            ]
            try:
                subprocess.check_call(clone_cmd)
            except subprocess.CalledProcessError as e:
                raise ValueError(f"Failed to clone {repo_url}: {e}")
            # A branch name can contain slashes, and a forge URL doesn't say
            # where the ref ends and the path begins, so the guess made when
            # the URL was read may have cut it in the wrong place. Only
            # reached when the ref as recorded doesn't resolve, so an
            # explicit --git-ref that works is never second-guessed.
            if target is not None and not _ref_and_path_resolve(
                tmp_dir, target, src_path
            ):
                widened = _widen_ref(tmp_dir, target, src_path)
                if widened is not None:
                    target, src_path = widened
                    git["git_ref"], git["path"] = target, src_path
            try:
                subprocess.check_call(
                    [
                        "git",
                        "-C",
                        tmp_dir,
                        "checkout",
                        "--quiet",
                        target or "HEAD",
                    ]
                )
                rev = subprocess.check_output(
                    ["git", "-C", tmp_dir, "rev-parse", "HEAD"], text=True
                ).strip()
            except subprocess.CalledProcessError as e:
                raise ValueError(
                    f"Failed to fetch {src_path} from {repo_url}: {e}"
                )
            # Resolved, so neither a '..' in the path nor a symlink in the
            # checkout can reach outside the clone
            clone_root = os.path.realpath(tmp_dir)
            full_src = os.path.realpath(os.path.join(clone_root, src_path))
            if os.path.commonpath([clone_root, full_src]) != clone_root:
                raise ValueError(f"'{src_path}' points outside of {repo_url}")
            if not os.path.exists(full_src):
                raise ValueError(
                    f"'{src_path}' does not exist in {repo_url} at "
                    f"{target or rev}"
                )
            if os.path.isdir(full_src):
                shutil.rmtree(dest_path, ignore_errors=True)
                # Symlinks are copied as symlinks rather than followed: the
                # containment check above covers the path asked for, but a
                # link *inside* the tree could still point anywhere on this
                # machine, and copying its target would pull a local file
                # into the project as though it came from the repo
                shutil.copytree(full_src, dest_path, symlinks=True)
            else:
                shutil.copyfile(full_src, dest_path)
        # What was actually fetched, so the import is reproducible even
        # when it follows a moving branch. Kept out of the entry: the entry
        # says what to follow, this says where that led.
        git.pop("git_rev", None)
        imported_from.update({k: v for k, v in git.items() if v is not None})
        lock = {
            "kind": "git",
            "repo_url": repo_url,
            "path": src_path,
            "ref": target,
            "rev": rev,
        }
        return imported_from, _with_state(lock, dest_path)
    if (url := imported_from.get("url")) is not None:
        import requests

        # Written beside the destination and moved over it once complete,
        # so a download that dies partway leaves the old file intact.
        # Every failure is reported the same way, including a connection
        # that never opens or dies mid-body: a caller refreshing many
        # imports has to be able to skip this one and carry on.
        part_path = dest_path + ".part"
        try:
            with requests.get(url, stream=True) as resp:
                resp.raise_for_status()
                with open(part_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                # What the server says identifies this version, so asking
                # whether there's a newer one needn't download it
                lock = {
                    "kind": "url",
                    "url": url,
                    "etag": resp.headers.get("ETag"),
                    "last_modified": resp.headers.get("Last-Modified"),
                }
            os.replace(part_path, dest_path)
        except requests.RequestException as e:
            raise ValueError(f"Failed to download {url}: {e}")
        except OSError as e:
            raise ValueError(f"Failed to write {dest_path}: {e}")
        finally:
            if os.path.exists(part_path):
                os.remove(part_path)
        return imported_from, _with_state(lock, dest_path)
    if (project := imported_from.get("project")) is not None:
        import base64

        import calkit

        src_path = imported_from.get("path")
        if not src_path:
            raise ValueError("Project source has no 'path' to fetch")
        project_ref = imported_from.get("git_ref")
        # The repo behind the project, so the lock says where the commit is
        # a commit of; not needed to fetch, so not having it is no failure
        try:
            info = calkit.hub.get(f"/projects/{project}")
            git_repo_url = (
                info.get("git_repo_url") if isinstance(info, dict) else None
            )
        except Exception:
            git_repo_url = None
        try:
            contents: dict = calkit.hub.get(
                f"/projects/{project}/contents/{src_path}",
                params={"ref": project_ref} if project_ref else None,
            )
        except Exception as e:
            raise ValueError(f"Failed to fetch {src_path} from {project}: {e}")
        lock = {
            "kind": "calkit",
            "hub": calkit.hub.get_hub_url(),
            "project": project,
            "path": src_path,
            "git_repo_url": git_repo_url,
            "git_ref": project_ref,
            # Older hubs don't say what commit they read
            "git_rev": contents.get("commit_sha"),
        }
        if source_entry is not None and isinstance(
            contents.get("calkit_object"), dict
        ):
            source_entry.update(contents["calkit_object"])
        content = contents.get("content")
        if content is not None:
            with open(dest_path, "wb") as f:
                f.write(base64.b64decode(content))
            return imported_from, _with_state(lock, dest_path)
        download_url = contents.get("url")
        if download_url is None:
            raise ValueError(f"Could not fetch {src_path} from {project}")
        # Big files come back as a link to fetch rather than inline, so the
        # URL branch above finishes the job. The entry still records the
        # project, since that is where the file came from.
        fetch({"url": download_url}, dest_path=dest_path)
        return imported_from, _with_state(lock, dest_path)
    if imported_from.get("doi") is not None:
        raise ValueError(
            "Fetching by DOI is not supported here, since a DOI resolves to "
            "a record rather than to a file; use 'calkit import zenodo' for "
            "a Zenodo record"
        )
    raise ValueError(
        "Nothing to fetch from: expected one of 'git', 'url', 'project', or "
        "'doi'"
    )


@dataclasses.dataclass
class ProvenanceStep:
    """A path on the way back from something shown, and the stage that
    produces it, if one does.
    """

    path: str
    stage: str | None = None


@dataclasses.dataclass
class ProvenanceGap:
    """A path nothing records the origin of, and the chain from what's
    shown back to it.

    One that's ``unchecked`` is recorded as imported, but from somewhere
    only described, e.g., a folder on someone's computer, so nobody else
    can check it.
    """

    steps: list[ProvenanceStep]
    unchecked: bool = False

    @property
    def path(self) -> str:
        return self.steps[-1].path

    def __str__(self) -> str:
        what = (
            f"{self.path} is imported from somewhere that can't be checked"
            if self.unchecked
            else f"origin not defined for {self.path}"
        )
        if len(self.steps) == 1:
            return what
        chain = []
        for step in self.steps:
            chain.append(step.path)
            if step.stage:
                chain.append(f"stage {step.stage}")
        return f"{what} ({' <- '.join(chain)})"


def find_provenance_gaps(
    paths: list[str],
    ck_info: dict,
    dvc_yaml: dict,
    dvc_lock: dict,
    is_data: Callable[[str], bool],
) -> list[ProvenanceGap]:
    """Follow each path back through the stages that produce it, to where
    each chain starts, and return the starts nothing accounts for.

    A chain starts somewhere accounted for at an entry recording an import
    or who created it, or at code and config the authors wrote. Anything
    else nothing produces, i.e., what ``is_data`` says is data, is a gap.
    Stages are read from ``dvc.lock`` where they've run, and from
    ``dvc.yaml`` where they haven't, except for matrix stages, whose
    expansions aren't known until they run.
    """

    def norm(path: str, wdir: str = "") -> str:
        return posixpath.normpath(posixpath.join(wdir, path))

    def stage_paths(items: list | None, wdir: str) -> list[str]:
        out = []
        for item in items or []:
            if isinstance(item, dict):
                item = item.get("path") or next(iter(item), None)
            if isinstance(item, str) and "${" not in item:
                out.append(norm(item, wdir))
        return out

    def under(path: str, parent: str) -> bool:
        return path == parent or path.startswith(parent.rstrip("/") + "/")

    def producer(path: str) -> str | None:
        for name, (_, outs) in stages.items():
            if any(under(path, out) for out in outs):
                return name
        return None

    def walk(path: str, trail: list[ProvenanceStep]) -> None:
        # Every entry covering the path counts, e.g., a file's and its
        # folder's, whatever order calkit.yaml lists them in
        covering = [e for e in entries if under(path, norm(e["path"]))]
        if any(
            import_is_checkable(e.get("imported_from"))
            or (
                e.get("created_by") is not None
                and can_be_created_by_person(path)
            )
            for e in covering
        ):
            return
        if any(e.get("imported_from") is not None for e in covering):
            if path not in gaps:
                gaps[path] = ProvenanceGap(
                    trail + [ProvenanceStep(path)], unchecked=True
                )
            return
        stage = producer(path)
        if stage is None:
            # An entry naming a stage not compiled yet is taken at its word
            if not any(e.get("stage") is not None for e in covering):
                if is_data(path) and path not in gaps:
                    gaps[path] = ProvenanceGap(trail + [ProvenanceStep(path)])
            return
        if stage in walked:
            return
        walked.add(stage)
        for dep in stages[stage][0]:
            # Calkit's own bookkeeping, e.g., environment locks
            if dep.startswith(".calkit/") or dep == "calkit.yaml":
                continue
            walk(dep, trail + [ProvenanceStep(path, stage)])

    yaml_stages = dvc_yaml.get("stages") or {}
    lock_stages = dvc_lock.get("stages") or {}
    # Each stage's inputs and outputs, relative to the project
    stages: dict[str, tuple[list[str], list[str]]] = {}
    for name, stage in lock_stages.items():
        base = (yaml_stages.get(name.split("@")[0]) or {}).get("wdir") or ""
        stages[name] = (
            stage_paths((stage or {}).get("deps"), base),
            stage_paths((stage or {}).get("outs"), base),
        )
    for name, stage in yaml_stages.items():
        if (
            not isinstance(stage, dict)
            or name in stages
            or "matrix" in stage
            or "foreach" in stage
        ):
            continue
        wdir = stage.get("wdir") or ""
        stages[name] = (
            stage_paths(stage.get("deps"), wdir),
            stage_paths(stage.get("outs"), wdir),
        )
    entries = [
        entry
        for items in ck_info.values()
        if isinstance(items, list)
        for entry in items
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    ]
    gaps: dict[str, ProvenanceGap] = {}
    walked: set[str] = set()
    for path in paths:
        walk(norm(path), [])
    return list(gaps.values())


def is_data_path(
    path: str,
    is_file: Callable[[str], bool],
    is_dir: Callable[[str], bool],
    listdir: Callable[[str], list[str]],
) -> bool:
    """Whether a path is data, which needs a recorded origin, rather than
    code or config the authors wrote.

    Data is anything DVC tracks, and otherwise files of a kind that isn't
    code or config, including inside a directory. Takes the filesystem as
    functions, so a project on disk and one read out of Git agree.
    """
    from calkit.detect import DATASET_EXTENSIONS
    from calkit.reproducibility import MISC_EXTENSIONS_NEEDING_PROVENANCE

    exts = MISC_EXTENSIONS_NEEDING_PROVENANCE | DATASET_EXTENSIONS | {".tsv"}
    parts = path.split("/")
    if any(
        is_file("/".join(parts[:i]) + ".dvc") for i in range(1, len(parts) + 1)
    ):
        return True
    # Named like data, even as a folder, e.g., a .zarr store
    if posixpath.splitext(path)[1].lower() in exts:
        return True
    if not is_dir(path):
        return False
    pending = [path]
    while pending:
        parent = pending.pop()
        for name in listdir(parent):
            child = f"{parent}/{name}"
            if posixpath.splitext(name)[1].lower() in exts:
                return True
            if is_dir(child):
                pending.append(child)
            # A DVC pointer stands in for data, whether pulled or not
            elif name.endswith(".dvc"):
                return True
    return False


def find_project_provenance_gaps(
    paths: list[str], wdir: str = ".", ck_info: dict | None = None
) -> list[ProvenanceGap]:
    """:func:`find_provenance_gaps` for a project on disk."""
    import calkit

    def read_yaml(name: str) -> dict:
        fpath = os.path.join(wdir, name)
        if not os.path.isfile(fpath):
            return {}
        with open(fpath) as f:
            return calkit.ryaml.load(f) or {}

    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    return find_provenance_gaps(
        paths,
        ck_info=ck_info,
        dvc_yaml=read_yaml("dvc.yaml"),
        dvc_lock=read_yaml("dvc.lock"),
        is_data=lambda path: is_data_path(
            path,
            is_file=lambda p: os.path.isfile(os.path.join(wdir, p)),
            is_dir=lambda p: os.path.isdir(os.path.join(wdir, p)),
            listdir=lambda p: os.listdir(os.path.join(wdir, p)),
        ),
    )
