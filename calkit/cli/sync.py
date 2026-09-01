"""CLI for syncing."""

from __future__ import annotations

import os
from typing import Callable

import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import AliasGroup, raise_error, warn

sync_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


@sync_app.command(name="git")
def sync_git(
    no_check_auth: Annotated[bool, typer.Option("--no-check-auth")] = False,
) -> None:
    """Sync the Git repository by pulling and then pushing."""
    from calkit.cli.main.core import pull, push

    try:
        repo = calkit.git.get_repo()
    except Exception:
        raise_error("No Git repository found. Run 'git init' first.")
    if not repo.remotes:
        raise_error(
            "No Git remotes configured. Add a remote with "
            "'git remote add <name> <url>'."
        )
    pull(no_dvc=True, no_check_auth=no_check_auth)
    push(no_dvc=True, no_check_auth=no_check_auth)


@sync_app.command(name="dvc")
def sync_dvc(
    no_check_auth: Annotated[bool, typer.Option("--no-check-auth")] = False,
) -> None:
    """Sync the DVC repository by pulling and then pushing."""
    from calkit.cli.main.core import pull, push

    try:
        calkit.dvc.get_dvc_repo()
    except Exception:
        raise_error("No DVC repository found. Run 'calkit init' first.")
    if not calkit.dvc.get_remotes():
        raise_error(
            "No DVC remotes configured. Add a remote with "
            "'dvc remote add <name> <url>'."
        )
    pull(no_git=True, no_check_auth=no_check_auth)
    push(no_git=True, no_check_auth=no_check_auth)


@sync_app.command(name="all")
def sync_all() -> None:
    """Sync all registered systems."""
    from calkit.cli.overleaf import sync as overleaf_sync

    # Run each known target in a stable order, reporting and collecting any
    # failures. Each target is responsible for raising a clear error if it is
    # not configured, so users calling 'calkit sync <target>' directly get a
    # helpful message.
    sync_funcs: list[tuple[str, Callable[[], None]]] = [
        ("git", sync_git),
        ("dvc", sync_dvc),
        ("overleaf", overleaf_sync),
    ]
    failures = []
    for target_name, sync_func in sync_funcs:
        typer.echo(f"Syncing {target_name}...")
        try:
            sync_func()
        except Exception as e:
            typer.echo(f"Failed to sync {target_name}: {e}", err=True)
            failures.append(target_name)
    # Exit with an error if any target failed so callers can react.
    if failures:
        raise typer.Exit(1)


def _refresh_import(
    ck_info: dict,
    target: str,
    git_ref: str | None = None,
    force: bool = False,
) -> str:
    """Re-fetch one imported path, updating its entry in ``ck_info``.

    Returns an empty string on success, or a reason it couldn't be done.
    Whether that reason is fatal is the caller's to decide: naming a path
    that can't be refreshed is a failure, while one bad entry in a batch
    shouldn't leave every later import stale.
    """
    from calkit.provenance import (
        check_project_path,
        describe_source,
        find_artifact,
        git_source,
        local_edit,
        read_import_locks,
        write_import_lock,
    )

    problem = check_project_path(target)
    if problem:
        return problem
    found = find_artifact(ck_info, target)
    if found is None:
        return (
            f"nothing recorded at '{target}'; 'calkit import path' is what "
            "records where a file came from"
        )
    kind, entry = found
    imported_from = entry.get("imported_from")
    if imported_from is None:
        return (
            f"'{target}' is recorded in '{kind}' but doesn't say it was "
            "imported, so there is nowhere to refresh it from"
        )
    # A dataset brought in with 'calkit import dataset' is tracked by DVC,
    # and writing over the file would leave its .dvc file describing the
    # old one
    if os.path.isfile(target + ".dvc"):
        return (
            f"'{target}' is tracked by DVC; re-import it with 'calkit "
            "import dataset' to refresh it"
        )
    if git_ref is not None:
        git = git_source(imported_from)
        if git is None:
            return (
                f"'{target}' was not imported from a Git repo, so there is "
                "no ref to follow"
            )
        # Read before the nested spelling is dropped, so an entry written
        # that way keeps its repo rather than losing it
        git["git_ref"] = git_ref
        imported_from.pop("git", None)
        imported_from.update({k: v for k, v in git.items() if v is not None})
    # A refresh overwrites, so a file edited since it was fetched would
    # lose that work silently. Reported rather than merged: an import is
    # inbound-only, so there is no other side to merge with.
    locks = read_import_locks()
    if not force and local_edit(target, locks.get(target)):
        return (
            f"'{target}' has been edited since it was imported, and "
            "refreshing it would discard that; pass --force to overwrite, "
            "or drop its 'imported_from' if it is now maintained here"
        )
    typer.echo(f"Fetching {describe_source(imported_from)}")
    try:
        entry["imported_from"], lock = calkit.provenance.fetch(
            imported_from, dest_path=target
        )
    except ValueError as e:
        return str(e)
    # An entry written before the split carries its commit in calkit.yaml.
    # Moving it across here is what upgrades the project, so nobody has to
    # run anything to migrate.
    entry["imported_from"].pop("git_rev", None)
    write_import_lock(target, lock)
    return ""


def _commit_refreshed(
    paths: list[str], message: str, nothing_changed: str, no_commit: bool
) -> bool:
    """Stage and commit refreshed imports, reporting whether any changed.

    Scoped to the paths that were refreshed, both to decide whether
    anything changed and to commit. Reading the whole index would call an
    unchanged file updated whenever something else happened to be staged,
    and committing it would sweep that unrelated work into a commit
    claiming to be about these files.
    """
    repo = calkit.git.get_repo()
    repo.git.add(paths)
    if not repo.git.diff("--cached", "--name-only", "--", *paths):
        typer.echo(nothing_changed)
        return False
    if not no_commit:
        typer.echo("Committing changes")
        repo.git.commit(paths + ["-m", message])
    return True


@sync_app.command(name="import")
def sync_import(
    path: Annotated[
        str | None,
        typer.Argument(
            help="Path of the imported object to refresh. Omit with --all."
        ),
    ] = None,
    update_all: Annotated[
        bool,
        typer.Option(
            "--all",
            help=(
                "Refresh every imported object in the project, across all "
                "artifact kinds. Ones that can't be refreshed in place are "
                "reported and skipped."
            ),
        ),
    ] = False,
    git_ref: Annotated[
        str | None,
        typer.Option(
            "--git-ref",
            help=(
                "Branch, tag, or commit to follow from now on, for a file "
                "imported from a Git repo. Recorded, so later refreshes "
                "keep using it."
            ),
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help=(
                "Overwrite even if the file has been edited since it was "
                "imported."
            ),
        ),
    ] = False,
    no_commit: Annotated[
        bool,
        typer.Option("--no-commit", help="Do not commit changes to repo."),
    ] = False,
) -> None:
    """Pull an imported file from where it came from.

    For a Git source this takes the latest on whatever the entry follows,
    which is its 'ref' if it names one and the repo's default branch
    otherwise, and records the commit it lands on. '--git-ref' changes
    what it follows, from then on and not just this once, so switching to
    a tag pins the import to that tag rather than quietly reverting to the
    default branch next time.

    This is a one-way copy from the source, not a merge. An import records
    that a file came from somewhere else, so a local edit that survived a
    refresh would make the entry a lie about what is on disk -- but losing
    that edit silently would be worse, so a file that differs from what was
    last fetched is reported and left alone until '--force' says otherwise.
    The checksum recorded in '.calkit/imports.json' is what makes the edit
    visible.

    What the fetch resolves to -- the commit, the checksum, the time -- is
    written to '.calkit/imports.json' rather than to 'calkit.yaml', which
    keeps only what a person declared. To pin an import, write the commit
    hash as its 'ref'. An entry written before that split carries its
    'rev' in 'calkit.yaml'; refreshing it moves that across, so nothing has
    to be migrated by hand.

    With '--all', every imported object is refreshed instead, whichever
    list it was recorded in, and they are committed together. One that
    can't be refreshed in place -- a dataset tracked by DVC, or a record
    named only by a DOI -- is reported and skipped rather than stopping
    the rest, and so is one whose source can't be reached, since a repo
    being down shouldn't leave every other import stale. Naming a single
    object that can't be refreshed is still an error, since that is what
    was asked for. With '--all' the command exits non-zero if anything was
    skipped.

    Only imported paths for now, since that is the only kind of object an
    import records. An imported environment has no path of its own, so
    when 'calkit import environment' is finished this is where refreshing
    it belongs.
    """
    from calkit.provenance import (
        IMPORT_LOCK_FPATH,
        get_artifact_types_with_imports,
    )

    if update_all and path is not None:
        raise_error("Give a path or --all, not both")
    if not update_all and path is None:
        raise_error("Give a path to refresh, or --all to refresh every one")
    if update_all and git_ref is not None:
        # One ref can't mean the same thing in several repos
        raise_error(
            "--git-ref names a ref in one repo, so it can't be combined "
            "with --all; refresh that object on its own"
        )
    ck_info = calkit.load_calkit_info()
    if not update_all:
        problem = _refresh_import(
            ck_info, str(path), git_ref=git_ref, force=force
        )
        if problem:
            raise_error(problem[0].upper() + problem[1:])
        calkit.save_calkit_info(ck_info)
        if _commit_refreshed(
            paths=[str(path), "calkit.yaml", IMPORT_LOCK_FPATH],
            message=f"Update {path} from its source",
            nothing_changed=f"{path} is already up-to-date",
            no_commit=no_commit,
        ):
            typer.echo(f"Updated {path}")
        return
    targets = [
        entry["path"]
        for kind in get_artifact_types_with_imports()
        for entry in ck_info.get(kind, []) or []
        if isinstance(entry, dict)
        and entry.get("path")
        and entry.get("imported_from")
    ]
    if not targets:
        typer.echo("No imported objects found")
        return
    refreshed: list[str] = []
    skipped: list[str] = []
    for target in targets:
        problem = _refresh_import(ck_info, target, force=force)
        if problem:
            skipped.append(f"{target}: {problem}")
            continue
        refreshed.append(target)
    n = len(refreshed)
    # Nothing fetched means nothing to record or commit. The lock file may
    # not even exist -- a project whose only imports are a DVC dataset or
    # a DOI never writes one -- and staging it would fail before these
    # diagnostics got a chance to print.
    if refreshed:
        calkit.save_calkit_info(ck_info)
        changed = _commit_refreshed(
            paths=refreshed + ["calkit.yaml", IMPORT_LOCK_FPATH],
            message=f"Update {n} imported objects from their sources",
            nothing_changed=f"{n} imported objects are already up-to-date",
            no_commit=no_commit,
        )
    else:
        changed = False
    for note in skipped:
        warn(f"Skipped {note}")
    if changed:
        typer.echo(f"Updated {n} imported objects")
    elif not refreshed and skipped:
        typer.echo(f"Nothing refreshed; {len(skipped)} skipped")
    if skipped:
        raise typer.Exit(1)
