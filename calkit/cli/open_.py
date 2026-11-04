"""CLI for opening things."""

from __future__ import annotations

import os
from typing import Annotated

import typer

import calkit
from calkit.cli import raise_error, warn

open_app = typer.Typer(no_args_is_help=True)


@open_app.command(name="project")
def open_project(
    project: Annotated[
        str,
        typer.Argument(
            help="Project name, or owner and name, e.g., 'someone/my-proj'."
        ),
    ],
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Clone into ~/calkit without asking if it isn't here.",
        ),
    ] = False,
) -> None:
    """Open a project on this machine in VS Code, from anywhere.

    Looks for it among the Calkit projects in your home folder, e.g., in
    ~/calkit or ~/dev, and offers to clone it into ~/calkit if it isn't
    there.
    """
    import shutil
    import subprocess

    from calkit.core import is_tty

    owner, _, name = project.rpartition("/")
    if not name or "/" in owner:
        raise_error("Give the project as NAME or OWNER/NAME")
    home = os.path.expanduser("~")
    default_path = os.path.join(home, "calkit", name)
    # Find checkouts of it, by the owner and name each project says it has
    found: dict[str, str] = {}
    for path in calkit.find_project_dirs():
        path = os.path.realpath(path)
        # Most projects say their name, which rules them out without asking
        # Git for a remote
        declared = calkit.load_calkit_info(wdir=path, read_only=True).get(
            "name"
        )
        if declared is not None and declared != name:
            continue
        # A subproject without its own repo would look like its parent
        repo = calkit.git.get_repo(path)
        if os.path.realpath(str(repo.working_tree_dir)) != path:
            continue
        try:
            p_owner, p_name = calkit.detect_project_name(wdir=path).split(
                "/", 1
            )
        except ValueError:
            continue
        if p_name == name and owner in ("", p_owner):
            found[path] = p_owner
    owners = sorted(set(found.values()))
    if len(owners) > 1:
        raise_error(
            f"More than one project named '{name}' is on this machine; "
            "give its owner, e.g., "
            + ", ".join(f"'calkit open project {o}/{name}'" for o in owners)
        )
    paths = sorted(found)
    # Clone it if it isn't here
    if not paths:
        if not owner:
            raise_error(
                f"No project named '{name}' is on this machine; give its "
                f"owner to clone it, e.g., 'calkit open project OWNER/{name}'"
            )
        if os.path.exists(default_path):
            raise_error(f"{default_path} exists, but isn't {owner}/{name}")
        if not yes:
            if not is_tty():
                raise_error(
                    f"{owner}/{name} isn't on this machine; rerun with --yes "
                    f"to clone it into {default_path}"
                )
            if not typer.confirm(
                f"{owner}/{name} isn't on this machine. Clone it into "
                f"{default_path}?",
                default=True,
            ):
                raise typer.Exit(1)
        from calkit.cli.main.core import clone

        clone(url=f"{owner}/{name}", location=default_path)
        paths = [default_path]
    # With more than one checkout, e.g., Git worktrees, prefer the one in
    # ~/calkit, then the main checkout, whose .git is a folder rather than a
    # file pointing to it
    if len(paths) > 1:
        preferred = [
            p for p in paths if p == os.path.realpath(default_path)
        ] or [p for p in paths if os.path.isdir(os.path.join(p, ".git"))]
        if len(preferred) != 1:
            raise_error(
                f"{owner or found[paths[0]]}/{name} is in more than one "
                "place; open one with 'code PATH': " + ", ".join(paths)
            )
        paths = preferred
    path = paths[0]
    code = shutil.which("code")
    if code is None:
        warn(
            "VS Code's 'code' command isn't on PATH, so opening the folder "
            "instead; add it from VS Code's command palette with 'Shell "
            "Command: Install 'code' command in PATH'"
        )
        typer.launch(path)
        return
    calkit.echo(f"Opening {path} in VS Code")
    subprocess.call([code, path])
