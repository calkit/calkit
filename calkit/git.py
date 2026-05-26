"""Git-related functionality."""

from __future__ import annotations

import os
from os import PathLike
from pathlib import Path

import git
from git.exc import InvalidGitRepositoryError

__all__ = ["InvalidGitRepositoryError", "get_repo"]


def get_repo(path: str | None = None) -> git.Repo:
    """Return a git.Repo for ``path`` (or cwd), searching parent dirs.

    Prefer this over bare ``git.Repo()`` so that commands run from inside
    a subproject folder (plain subdirectory of a parent git repo) correctly
    discover the enclosing repo instead of raising InvalidGitRepositoryError
    or, worse, initializing a new nested repo.
    """
    return git.Repo(path, search_parent_directories=True)


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
        lines = gitignore_txt.splitlines()
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
                f.write(os.linesep.join(lines))
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
                f.write(os.linesep.join(lines))
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
        f.write(os.linesep.join(lines))
    # If the path is still ignored after updating this gitignore file (e.g.,
    # because a subdirectory .gitignore also contains a matching rule), fix
    # that file as well. Depth-limit guards against pathological gitignore
    # cycles.
    if target_repo.ignored(target_path) and _depth < 10:
        ensure_path_is_not_ignored(target_repo, target_path, _depth + 1)
    return True
