"""Git-related functionality."""

from __future__ import annotations

import os
import re
import warnings
from os import PathLike
from pathlib import Path

import git
from git.exc import InvalidGitRepositoryError

__all__ = ["InvalidGitRepositoryError", "get_repo"]

# Marks the block of exemptions ensure_path_is_not_filtered maintains, so
# it's clear in a file Calkit shares with whatever installed the filter.
CALKIT_ATTRIBUTES_COMMENT = (
    "# Added by Calkit: pipeline outputs must be committed unfiltered"
)


def get_repo(path: str | None = None) -> git.Repo:
    """Return a git.Repo for ``path`` (or cwd), searching parent dirs.

    Prefer this over bare ``git.Repo()`` so that commands run from inside
    a subproject folder (plain subdirectory of a parent git repo) correctly
    discover the enclosing repo instead of raising InvalidGitRepositoryError
    or, worse, initializing a new nested repo.
    """
    return git.Repo(path, search_parent_directories=True)


def get_default_branch(repo: git.Repo) -> str | None:
    """The name of the project's default branch, e.g., ``main``.

    Determined from the remote's HEAD when there is one, since that's what
    the hosting service considers the trunk, and falls back to whichever
    conventional name the repo actually has. Returns None if neither
    answers, e.g., in a repo with no commits.
    """
    try:
        ref = repo.remotes.origin.refs.HEAD.reference.name
        # e.g., 'origin/main'
        return ref.split("/", 1)[1] if "/" in ref else ref
    except Exception:
        pass
    local_branches = set()
    try:
        local_branches = {h.name for h in repo.heads}
    except Exception:
        pass
    remote_branches = set()
    try:
        remote_branches = {
            r.name.split("/", 1)[1]
            for r in repo.remotes.origin.refs
            if "/" in r.name
        }
    except Exception:
        pass
    for candidate in ["main", "master"]:
        if candidate in local_branches or candidate in remote_branches:
            return candidate
    return None


def check_branch_is_current(
    repo: git.Repo, branch: str | None = None, fetch: bool = True
) -> str | None:
    """Check that the checked-out branch contains everything on the default
    branch, returning a message describing the problem if it doesn't.

    A branch cut from the default branch's tip passes -- what matters is
    that no work already on the trunk is missing, not which branch the work
    happens on. The default branch itself is checked the same way, since a
    local copy of it can be behind the remote. Returns None when the check
    passes or when there's nothing to check against (no remote, no default
    branch, or a repo whose refs can't be resolved).
    """
    if branch is None:
        branch = get_default_branch(repo)
    if branch is None:
        return None
    try:
        current = repo.active_branch.name
    except Exception:
        # Detached HEAD, e.g., a CI checkout of a tag
        current = None
    if fetch and repo.remotes:
        try:
            repo.git.fetch("origin", branch)
        except Exception:
            pass
    # Prefer the remote's copy, since that's the shared state; a local
    # default branch can itself be behind
    ref = None
    for candidate in [f"origin/{branch}", branch]:
        try:
            if repo.git.rev_parse("--verify", "--quiet", candidate):
                ref = candidate
                break
        except Exception:
            continue
    if ref is None:
        return None
    try:
        tip = str(repo.git.rev_parse(ref)).strip()
        merge_base = str(repo.git.merge_base("HEAD", ref)).strip()
    except Exception:
        return None
    if merge_base == tip:
        return None
    try:
        behind = str(repo.git.rev_list("--count", f"HEAD..{ref}")).strip()
    except Exception:
        behind = "some"
    return (
        f"Branch '{current or 'HEAD'}' is missing {behind} commit(s) from "
        f"'{ref}'"
    )


def get_staged_files(
    path: str | None = None, repo: git.Repo | None = None
) -> list[str]:
    """Get a list of staged files for the repo at ``path`` or the provided
    repo.
    """
    if repo is None:
        repo = get_repo(path)
    cmd = ["--staged", "--name-only"]
    if path is not None:
        cmd.append(path)
    diff = repo.git.diff(cmd)
    paths = diff.split("\n")
    return [p for p in paths if p]


def get_changed_files(
    path: str | None = None, repo: git.Repo | None = None
) -> list[str]:
    """Get a list of files that have been changed but not staged."""
    if repo is None:
        repo = get_repo(path)
    return [
        item.a_path
        for item in repo.index.diff(None)
        if item.a_path is not None
    ]


def get_untracked_files(
    path: str | None = None, repo: git.Repo | None = None
) -> list[str]:
    """Get a list of untracked files."""
    if repo is None:
        repo = get_repo(path)
    return repo.untracked_files


def get_staged_files_with_status(
    path: str | None = None, repo: git.Repo | None = None
) -> list[dict]:
    if repo is None:
        repo = get_repo(path)
    cmd = ["--staged", "--name-status"]
    if path is not None:
        cmd.append(path)
    diff = repo.git.diff(cmd)
    paths = diff.split("\n")
    res = []
    for pathi in paths:
        # Make sure line is not empty, e.g., a trailing newline
        if pathi:
            status, p = pathi.split("\t")
            res.append({"status": status, "path": p})
    return res


def ls_files(repo: git.Repo, *args, **kwargs) -> list[str]:
    """Get a list of all files tracked by git."""
    output = repo.git.ls_files(*args, **kwargs)
    return [f for f in output.split("\n") if f]


def _resolve_repo_and_ignore_path(
    repo: git.Repo, path: str | PathLike
) -> tuple[git.Repo, str]:
    """Resolve which repo should own ignore rules for ``path``."""
    # Normalize target path to absolute from the current repo root.
    repo_root = Path(repo.working_dir).resolve()
    path_obj = Path(path)
    if path_obj.is_absolute():
        abs_path = path_obj.resolve()
    else:
        abs_path = (repo_root / path_obj).resolve()
    # If the path is inside a submodule, use that repo and relative path.
    for submodule in repo.submodules:
        submodule_root = (repo_root / submodule.path).resolve()
        if abs_path == submodule_root:
            continue
        if abs_path.is_relative_to(submodule_root):
            sub_repo = submodule.module()
            rel_path = abs_path.relative_to(submodule_root).as_posix()
            return sub_repo, rel_path
    # Fall back to a repo-relative path when possible.
    try:
        rel_path = abs_path.relative_to(repo_root).as_posix()
    except ValueError:
        rel_path = path_obj.as_posix()
    return repo, rel_path


def _get_matching_gitignore_details(
    repo: git.Repo, path: str
) -> tuple[Path | None, str | None]:
    """Return the repo-local gitignore file and pattern matching ``path``."""
    try:
        check_ignore = repo.git.check_ignore("-v", "--", path)
    except git.GitCommandError:
        return None, None
    line = check_ignore.splitlines()[0]
    try:
        source_info, _ = line.split("\t", 1)
        source_path, _, pattern = source_info.rsplit(":", 2)
    except ValueError:
        return None, None
    if not source_path.endswith(".gitignore"):
        return None, pattern
    gitignore_path = (Path(repo.working_dir) / source_path).resolve()
    try:
        gitignore_path.relative_to(Path(repo.working_dir).resolve())
    except ValueError:
        return None, pattern
    return gitignore_path, pattern


def ensure_path_is_ignored(
    repo: git.Repo, path: str | PathLike
) -> None | bool:
    """Ensure that the given path is ignored by Git.

    Returns True if ``.gitignore`` was modified.
    """
    # Resolve whether the ignore rule belongs to this repo or a submodule.
    target_repo, target_path = _resolve_repo_and_ignore_path(repo, path)
    # No-op if Git already ignores this path.
    if target_repo.ignored(target_path):
        return
    # Read gitignore first to check if the path is already ignored
    # If not, we don't want to add a line for it since it was added
    # TODO: Add an option to remove cached (`git rm --cached`)
    gitignore_path = os.path.join(target_repo.working_dir, ".gitignore")
    if os.path.isfile(gitignore_path):
        with open(gitignore_path) as f:
            gitignore_txt = f.read()
        lines = [line for line in gitignore_txt.splitlines() if line]
        if target_path in lines:
            # The direct rule exists; also remove any stale negation that
            # follows it, otherwise the negation wins and the path stays
            # unignored.
            negation_variants = [f"!{target_path}", f"!/{target_path}"]
            stale = [n for n in negation_variants if n in lines]
            if not stale:
                return
            for n in stale:
                lines.remove(n)
            with open(gitignore_path, "w") as f:
                f.write("\n".join(lines))
            return True
        # Remove any stale negations for this path so the ignore rule takes
        # effect cleanly without accumulating contradictory entries.
        negation_variants = [f"!{target_path}", f"!/{target_path}"]
        stale = [n for n in negation_variants if n in lines]
        if stale:
            for n in stale:
                lines.remove(n)
            lines.append(target_path)
            with open(gitignore_path, "w") as f:
                f.write("\n".join(lines))
            return True
    with open(gitignore_path, "a") as f:
        if (
            os.path.isfile(gitignore_path)
            and os.path.getsize(gitignore_path) > 0
        ):
            f.write("\n")
        f.write(f"{target_path}\n")
        return True


def ensure_path_is_not_ignored(
    repo: git.Repo, path: str | PathLike, _depth: int = 0
) -> None | bool:
    """Ensure a path is not ignored by Git."""
    # Resolve whether the unignore rule belongs to this repo or a submodule.
    target_repo, target_path = _resolve_repo_and_ignore_path(repo, path)
    # No-op if Git does not ignore this path.
    if not target_repo.ignored(target_path):
        return
    matching_gitignore_path, matched_pattern = _get_matching_gitignore_details(
        target_repo, target_path
    )
    if matching_gitignore_path is not None:
        gitignore_path = matching_gitignore_path.as_posix()
        path_for_gitignore = (
            (Path(target_repo.working_dir) / target_path)
            .resolve()
            .relative_to(matching_gitignore_path.parent.resolve())
            .as_posix()
        )
    else:
        gitignore_path = os.path.join(target_repo.working_dir, ".gitignore")
        path_for_gitignore = target_path
    if not os.path.isfile(gitignore_path):
        with open(gitignore_path, "w") as f:
            f.write(f"!{path_for_gitignore}\n")
        return True
    with open(gitignore_path) as f:
        gitignore_txt = f.read()
    lines = gitignore_txt.splitlines()
    direct_rule_variants = [path_for_gitignore, f"/{path_for_gitignore}"]
    if matched_pattern is not None and matched_pattern.startswith("/"):
        no_ignore_line = f"!/{path_for_gitignore}"
    else:
        no_ignore_line = f"!{path_for_gitignore}"
    path_parts = Path(path_for_gitignore).parts

    def ancestor_requires_recursive_unignore() -> bool:
        """Return True if any ancestor-level ignore rule would block this path.

        This includes explicit directory ignores (e.g., 'dir/' or '/dir/')
        as well as ancestor-based glob patterns like 'dir/*' or '/dir/*',
        i.e., any rule that would prevent reaching the nested path without
        adding recursive unignore patterns.
        """
        for i in range(1, len(path_parts)):
            ancestor = "/".join(path_parts[:i])
            if (
                ancestor in lines
                or f"/{ancestor}" in lines
                or f"{ancestor}/" in lines
                or f"/{ancestor}/" in lines
                or f"{ancestor}/*" in lines
                or f"/{ancestor}/*" in lines
            ):
                return True
        return False

    if len(path_parts) == 1:
        # Simple (non-nested) path: remove the direct ignore rule, or add a
        # negation if the ignore comes from a glob or other pattern
        direct_rule = next(
            (rule for rule in direct_rule_variants if rule in lines), None
        )
        if direct_rule is not None:
            lines.remove(direct_rule)
        else:
            # Remove any stale negation and re-append at the end so it takes
            # precedence over any later re-ignore rule
            if no_ignore_line in lines:
                lines.remove(no_ignore_line)
            lines.append(no_ignore_line)
    else:
        # Nested path: only apply recursive un-ignore rules when an ancestor
        # directory is explicitly ignored
        # Otherwise, remove a direct ignore
        # rule for this path or add a simple negation if needed
        removed_direct_rule = False
        direct_rule = next(
            (rule for rule in direct_rule_variants if rule in lines), None
        )
        if direct_rule is not None:
            lines.remove(direct_rule)
            removed_direct_rule = True
        if ancestor_requires_recursive_unignore():
            # Git will not traverse into a directory excluded by a "dir/"
            # pattern, so a bare "!dir/sub/file" negation has no effect.
            # We need to:
            #   1. Convert any "ancestor/" (or "ancestor") exclude to
            #      "ancestor/*" so git traverses the directory while still
            #      ignoring direct children by default.
            #   2. Add "!ancestor/" rules for intermediate directories.
            #   3. Add "ancestor/*" re-ignore rules for each intermediate dir.
            #   4. Add "!target_path" for the specific file.
            for i in range(1, len(path_parts)):
                ancestor = "/".join(path_parts[:i])
                reignore_glob = f"{ancestor}/*"
                if f"{ancestor}/" in lines:
                    idx = lines.index(f"{ancestor}/")
                    lines[idx] = reignore_glob
                elif f"/{ancestor}/" in lines:
                    idx = lines.index(f"/{ancestor}/")
                    lines[idx] = f"/{ancestor}/*"
                elif ancestor in lines:
                    idx = lines.index(ancestor)
                    lines[idx] = reignore_glob
                elif f"/{ancestor}" in lines:
                    idx = lines.index(f"/{ancestor}")
                    lines[idx] = f"/{ancestor}/*"
                no_ignore_dir = f"!{ancestor}/"
                anchored_no_ignore_dir = f"!/{ancestor}/"
                # The first ancestor does not need an explicit un-ignore once
                # converted to "ancestor/*". Deeper ancestors do.
                if i > 1:
                    # Remove stale entry and re-append so it takes precedence
                    if no_ignore_dir in lines:
                        lines.remove(no_ignore_dir)
                    elif anchored_no_ignore_dir in lines:
                        lines.remove(anchored_no_ignore_dir)
                    lines.append(no_ignore_dir)
                if (
                    reignore_glob not in lines
                    and f"/{ancestor}/*" not in lines
                ):
                    lines.append(reignore_glob)
            # Remove stale negation and re-append at the end so it takes
            # precedence over any later re-ignore rule
            if no_ignore_line in lines:
                lines.remove(no_ignore_line)
            lines.append(no_ignore_line)
        elif not removed_direct_rule:
            # The path may be ignored by a non-directory pattern (e.g., glob);
            # remove stale negation and append at end so it takes precedence
            if no_ignore_line in lines:
                lines.remove(no_ignore_line)
            lines.append(no_ignore_line)
    with open(gitignore_path, "w") as f:
        f.write("\n".join(lines))
    # If the path is still ignored after updating this gitignore file (e.g.,
    # because a subdirectory .gitignore also contains a matching rule), fix
    # that file as well. Depth-limit guards against pathological gitignore
    # cycles.
    if target_repo.ignored(target_path) and _depth < 10:
        ensure_path_is_not_ignored(target_repo, target_path, _depth + 1)
    return True


def ensure_dvc_pointer_is_not_ignored(repo, path: str) -> None:
    """Ensure the .dvc pointer for ``path`` will not be Git-ignored.

    A broad pattern in a ``.gitignore`` (e.g. ``*.pdf*``) can also match the
    ``<path>.dvc`` pointer DVC commits to Git, causing ``dvc add`` to fail with
    "bad DVC file name ... is git-ignored". This appends a ``!*.dvc`` negation
    to the ``.gitignore`` in the pointer's own directory (which wins under Git
    precedence) so pointers stay tracked. Idempotent.
    """
    path = path.replace("\\", "/").rstrip("/")
    pointer = path + ".dvc"
    if pointer not in repo.ignored(pointer):
        return
    pointer_dir = os.path.dirname(pointer)
    gitignore_path = os.path.join(repo.working_dir, pointer_dir, ".gitignore")
    exception = "!*.dvc"
    existing_lines = []
    if os.path.isfile(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8") as f:
            existing_lines = f.read().splitlines()
    if exception in existing_lines:
        return  # Already present
    os.makedirs(os.path.dirname(gitignore_path), exist_ok=True)
    with open(gitignore_path, "a", encoding="utf-8") as f:
        if existing_lines and existing_lines[-1] != "":
            f.write("\n")
        f.write(exception + "\n")


def get_filter_driver(repo: git.Repo, path: str | PathLike) -> str | None:
    """The name of the clean/smudge filter Git applies to ``path``, if any.

    Asks Git rather than reading attributes files, since a filter can be
    declared in any of several places with different precedence---most
    relevantly ``$GIT_DIR/info/attributes``, where ``nbstripout --install``
    puts it, which is per-clone and never committed.
    """
    path = Path(path).as_posix()
    try:
        # -z gives NUL-separated <path> <attr> <value> triples, so a path
        # containing ": " can't be mistaken for a field separator.
        out = repo.git.check_attr("-z", "filter", "--", path)
    except git.GitCommandError as e:
        warnings.warn(
            f"Failed to check Git attributes for {path}: {e}", stacklevel=2
        )
        return None
    fields = out.split("\0")
    if len(fields) < 3:
        return None
    value = fields[2]
    # Git reports these two when no driver applies; anything else names one.
    if value in ("unspecified", "unset"):
        return None
    return value


def ensure_path_is_not_filtered(
    repo: git.Repo, path: str | PathLike
) -> bool | None:
    """Ensure Git stores ``path`` byte-for-byte, applying no clean filter.

    A clean filter rewrites content on its way into Git while leaving the
    working tree alone, and Git compares the filtered forms, so the committed
    bytes can differ from the file on disk with nothing showing up as
    modified. For a pipeline output that is fatal: DVC hashes the working
    tree file, so anything reading the repository instead---the Calkit hub,
    a fresh clone, a collaborator---sees a hash that disagrees with
    ``dvc.lock`` and reports the stage stale forever. ``nbstripout`` does
    exactly this to notebooks.

    The exemption is written to ``$GIT_DIR/info/attributes`` because that
    file outranks every other source of attributes, including the
    ``.gitattributes`` and the ``$GIT_DIR/info/attributes`` line
    ``nbstripout --install`` writes. Returns True if a rule was added, None
    if the path was already unfiltered.
    """
    path = Path(path).as_posix()
    if get_filter_driver(repo, path) is None:
        return
    attributes_path = os.path.join(repo.git_dir, "info", "attributes")
    # Quoted only when it has to be: an unquoted pattern is what a reader
    # expects, and Git only needs the quotes for whitespace.
    pattern = f'"{path}"' if any(c.isspace() for c in path) else path
    # ``-filter`` unsets the attribute rather than leaving it unspecified, so
    # no lower-precedence rule can put a driver back.
    rule = f"{pattern} -filter"
    existing_lines = []
    if os.path.isfile(attributes_path):
        with open(attributes_path, "r", encoding="utf-8") as f:
            existing_lines = f.read().splitlines()
    # Within one attributes file the last matching line wins, so the rule goes
    # at the end. If it's already in there, a filter still applying means
    # something was appended after it -- another `nbstripout --install`, most
    # likely -- and moving ours back to the end is what fixes that. Dropping
    # the old copy first keeps the file from growing a duplicate each time.
    lines = [line for line in existing_lines if line != rule]
    if CALKIT_ATTRIBUTES_COMMENT not in lines:
        lines.append(CALKIT_ATTRIBUTES_COMMENT)
    lines.append(rule)
    os.makedirs(os.path.dirname(attributes_path), exist_ok=True)
    with open(attributes_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    # Nothing higher-precedence than this file should exist, but a filter that
    # survives the rewrite would otherwise strip content silently on the next
    # commit, so say so rather than reporting success.
    if get_filter_driver(repo, path) is not None:
        warnings.warn(
            f"{path} is still filtered by Git despite an exemption in "
            f"{attributes_path}",
            stacklevel=2,
        )
        return
    # The rule alone doesn't fix what's already committed: Git trusts the
    # index's cached stat info, so an unchanged file is never re-read and the
    # filtered blob stays. Renormalizing re-hashes it through the new
    # attributes, staging the real content so the next commit repairs the
    # repository rather than waiting for the stage to run again.
    if ls_files(repo, "--", path):
        try:
            repo.git.add("--renormalize", "--", path)
        except git.GitCommandError as e:
            warnings.warn(
                f"Failed to renormalize {path} after unfiltering it: {e}",
                stacklevel=2,
            )
    return True


def resolve_ref(repo: git.Repo, ref: str) -> str | None:
    """Return the commit a revision points at, fetching if it isn't here.

    A CI checkout is usually shallow and often has only the branch being
    built, so comparing against another revision fails on a repo that
    looks fine otherwise. Rather than asking every workflow to set
    fetch-depth, get what's missing when it turns out to be missing: the
    revision itself, then the history behind it.

    Returns None if it still can't be resolved, which means the revision
    doesn't exist rather than isn't here yet.
    """

    def parse() -> str | None:
        # A clone that fetched only one branch has the others solely as
        # remote-tracking refs, if at all
        for name in (ref, f"origin/{ref}"):
            try:
                sha = str(repo.git.rev_parse(name)).strip()
            except Exception:
                continue
            if sha:
                return sha
        return None

    sha = parse()
    if sha is not None:
        return sha
    # Anything that isn't a plain revision name is not worth handing to
    # git, if only to keep a leading dash from being read as an option
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", ref):
        return None
    try:
        if re.fullmatch(r"[0-9a-f]{7,40}", ref):
            repo.git.fetch("origin", ref)
        else:
            # Into the tracking ref, so it's there by name afterwards
            repo.git.fetch("origin", f"{ref}:refs/remotes/origin/{ref}")
    except Exception:
        pass
    sha = parse()
    if sha is not None:
        return sha
    try:
        shallow = str(repo.git.rev_parse("--is-shallow-repository")).strip()
    except Exception:
        shallow = "false"
    if shallow != "true":
        return None
    warnings.warn(f"Fetching full history to compare against {ref}")
    try:
        repo.git.fetch("--unshallow", "--tags", "origin")
    except Exception as e:
        warnings.warn(f"Failed to fetch history: {e}")
        return None
    return parse()


def last_change(repo: git.Repo, ref: str, paths: list[str]) -> str | None:
    """The last commit at or before ``ref`` that touched any of ``paths``.

    Used to name a revision by its content rather than its position. A
    comparison against ``HEAD`` means the document as it stands, and the
    document doesn't change when something else in the project is
    committed, so resolving to the commit that last changed it keeps the
    answer stable and keeps a pipeline from invalidating itself.

    Returns None if nothing matches, including when the paths were never
    tracked.
    """
    if not paths:
        return None
    try:
        out = str(repo.git.rev_list("-1", ref, "--", *paths)).strip()
    except Exception:
        return None
    return out or None
