"""Functionality for handling artifact provenance."""

from __future__ import annotations

import functools
import os
import re

# The artifact kinds whose provenance is checked. Each entry must say where
# it came from: a pipeline stage, an import, or the person who created it,
# e.g., by collecting or measuring the data or drawing the figure.
PROVENANCE_ARTIFACT_TYPES = [
    "datasets",
    "figures",
    "publications",
    "tables",
    "presentations",
    "misc",
]


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
# source actually landed on, a checksum of what was fetched, and when. It
# is committed, because it is a lock rather than a merge base -- everyone
# cloning the project should get the same bytes, the way they do from
# ``dvc.lock`` or an environment's lock file. That is what separates it
# from ``.calkit/overleaf-sync.json``, which records what one checkout
# last saw and is deliberately local.
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
    return locks


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
    with open(fpath, "w") as f:
        json.dump(locks, f, indent=2, sort_keys=True)
        f.write("\n")
    return fpath


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
    return f"sha256:{digest.hexdigest()}"


def local_edit(path: str, lock: dict | None) -> bool:
    """Whether what is on disk differs from what the import last fetched.

    False when there is nothing to compare against -- an entry written
    before locks were recorded, say -- since a refresh that can't tell
    shouldn't claim it can.
    """
    if not lock or not lock.get("sha256") or not os.path.exists(path):
        return False
    return hash_path(path) != lock["sha256"]


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


def has_provenance(artifact: dict) -> bool:
    """Return whether an artifact entry records where it came from.

    A stage and an import are the stronger forms, but ``created_by`` counts
    too: a dataset someone measured, or a schematic someone drew, is
    accounted for even though there's nothing upstream to point at. The
    field names in ``calkit.reproducibility.ReproCheck`` predate
    attribution and are kept so callers reading them keep working.
    """
    return any(
        artifact.get(key) is not None
        for key in ["stage", "imported_from", "created_by"]
    )


def find_artifact(ck_info: dict, path: str) -> tuple[str, dict] | None:
    """Find the entry recorded at ``path``, whichever list it's in.

    Returns the list's name and the entry, so the caller can edit it in
    place.
    """
    for kind in PROVENANCE_ARTIFACT_TYPES:
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
        "repo_url": f"{scheme}://{forge_host}/{repo}.git",
        "path": "/".join(path_segments),
    }
    # Recorded as a 'ref' whether it names a branch, a tag, or a commit.
    # A commit is a thing to follow that happens never to move, which is
    # what keeps a deliberate pin pinned when the import is refreshed.
    if ref is not None:
        source["ref"] = ref
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
    source: dict = {"repo_url": repo_url}
    if path_segments:
        source["path"] = "/".join(path_segments)
    if ref is not None:
        source["ref"] = ref
    return source


def source_from_location(
    location: str,
    git_repo: str | None = None,
    ref: str | None = None,
) -> dict:
    """Work out where a file is being imported from, from how it's written.

    ``location`` is a path inside ``git_repo`` when that's given, and
    otherwise a URL, an SSH clone URL like
    ``git@github.com:owner/repo/path``, a DOI, or a Calkit project path
    like ``someone/some-project/scripts/setup.sh``. An explicit ``ref`` names
    the branch, tag, or commit to follow, and overrides one read out of a
    URL. Without one, the repo's default branch is what gets fetched, now
    and whenever the import is refreshed.
    """
    if git_repo is not None:
        source: dict = {"repo_url": git_repo, "path": location}
        if ref is not None:
            source["ref"] = ref
        return {"git": source}
    stripped = re.sub(
        r"^(https?://(dx\.)?doi\.org/|doi:)", "", location.strip(), flags=re.I
    )
    if re.fullmatch(r"10\.\d{4,9}/\S+", stripped):
        # Recognized rather than downloaded: a DOI resolves to a landing
        # page, so treating it as a plain URL would save the HTML and call
        # it the data. 'fetch' says what to use instead.
        return {"doi": stripped}
    if location.startswith(("http://", "https://")):
        git_source = _git_source_from_url(location, ref=ref)
        if git_source is not None:
            return {"git": git_source}
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
        return {"git": ssh_source}
    segments = location.split("/")
    if len(segments) < 3:
        raise ValueError(
            f"Cannot tell where '{location}' comes from; give a URL, a DOI, "
            "a Calkit project path like someone/some-project/path/to/file, "
            "or a path inside a repo named with --git-repo"
        )
    return {"project": "/".join(segments[:2]), "path": "/".join(segments[2:])}


def default_dest_path(imported_from: dict) -> str:
    """Where an import lands when no destination was given."""
    if (git := imported_from.get("git")) is not None:
        return os.path.basename(str(git.get("path") or ""))
    if imported_from.get("project") is not None:
        return str(imported_from.get("path") or "")
    if (url := imported_from.get("url")) is not None:
        from urllib.parse import urlsplit

        return os.path.basename(urlsplit(str(url)).path)
    return ""


def describe_source(imported_from: dict) -> str:
    """Name where an artifact came from, for a message to a person."""
    if (git := imported_from.get("git")) is not None:
        path = git.get("path")
        where = str(git.get("repo_url") or "a Git repo")
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


def _with_state(lock: dict, dest_path: str, rev: str | None = None) -> dict:
    """Fill in what a fetch resolved to: the commit, checksum, and when."""
    from datetime import datetime, timezone

    if rev is not None:
        lock["rev"] = rev
    checksum = hash_path(dest_path)
    if checksum is not None:
        lock["sha256"] = checksum
    lock["fetched"] = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    return lock


def fetch(imported_from: dict, dest_path: str) -> tuple[dict, dict]:
    """Download what an ``imported_from`` entry points at, to ``dest_path``.

    Returns the entry as it should now be recorded, and separately what the
    fetch resolved to: the commit a Git source landed on, a checksum of the
    file, and when. The first belongs in ``calkit.yaml`` because a person
    wrote it; the second belongs in ``.calkit/imports.json`` because the
    tool worked it out.

    What gets fetched is the source's ``ref``---a branch, a tag, or a
    commit---or the repo's default branch when it names none. The recorded
    ``rev`` is the answer, never the question: refreshing an import is
    asking where the thing it follows is now, and reading the last answer
    back would make that a no-op.

    Whatever is at ``dest_path`` is replaced. This is a one-way copy from
    the source, not a merge: an import is a statement about where a file
    came from, and a local edit that survived it would make that false.
    """
    import shutil
    import subprocess
    import tempfile

    imported_from = dict(imported_from)
    lock: dict = {}
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    if (git := imported_from.get("git")) is not None:
        git = dict(git)
        repo_url = git.get("repo_url")
        if not repo_url:
            raise ValueError("Git source has no 'repo_url' to fetch from")
        src_path = git.get("path")
        if not src_path:
            raise ValueError(
                "Git source has no 'path'; importing a whole repo is what a "
                "Git submodule is for"
            )
        # What to check out. Not 'rev': that records what a previous fetch
        # returned, so using it here would make every refresh return the
        # same thing it did last time. Nothing named means the repo's
        # default branch.
        target = git.get("ref")
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
                    git["ref"], git["path"] = target, src_path
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
        git.pop("rev", None)
        imported_from["git"] = git
        return imported_from, _with_state(lock, dest_path, rev=rev)
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
        try:
            contents: dict = calkit.hub.get(
                f"/projects/{project}/contents/{src_path}"
            )
        except Exception as e:
            raise ValueError(f"Failed to fetch {src_path} from {project}: {e}")
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
