"""CLI for opening things."""

from __future__ import annotations

import os
from typing import Annotated

import typer

import calkit
from calkit.cli import raise_error, warn

open_app = typer.Typer(no_args_is_help=True)

# Commands for the editors 'default_editor' can name
EDITOR_COMMANDS = {"vscode": "code", "jupyterlab": "jupyter lab"}


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
    """Open a project on this machine in its editor, from anywhere.

    Looks for it among the Calkit projects in your home folder, e.g., in
    ~/calkit or ~/dev, and offers to clone it into ~/calkit if it isn't
    there. The editor is the 'default_editor' setting, VS Code unless
    set otherwise, e.g., with 'calkit config set default_editor cursor'.
    """
    import shlex
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
    # Open it in the configured editor, which is either one we know the
    # command for or a command itself
    editor = calkit.config.read().default_editor
    cmd = shlex.split(EDITOR_COMMANDS.get(editor, editor))
    exe = shutil.which(cmd[0]) if cmd else None
    if exe is None and editor == "vscode":
        exe = find_or_install_vscode()
    if exe is None:
        warn(
            f"The default editor's command ({' '.join(cmd)!r}) isn't on PATH, "
            "so opening the folder instead; set another with 'calkit config "
            "set default_editor'"
        )
        typer.launch(path)
        return
    calkit.echo(f"Opening {path} with {editor}")
    subprocess.call([exe, *cmd[1:], path])


def find_or_install_vscode() -> str | None:
    """Find VS Code's command where it's installed but not on PATH, e.g.,
    an app dragged into /Applications, or offer to install it, optionally
    with Calkit's recommended extensions and settings.
    """
    import json
    import shutil
    import subprocess

    import click

    from calkit import install
    from calkit.core import is_tty
    from calkit.resources import load_json

    platform = install._current_platform()
    known = {
        "mac": [
            "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/"
            "code",
            os.path.expanduser(
                "~/Applications/Visual Studio Code.app/Contents/Resources/"
                "app/bin/code"
            ),
        ],
        "windows": [
            os.path.expandvars(
                "%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\bin\\code.cmd"
            ),
        ],
    }
    for path in known.get(platform, []):
        if os.path.isfile(path):
            return path
    entry = install.get_installer("code")
    download_url = "https://code.visualstudio.com/download"
    if not is_tty():
        hint = install.get_unsupported_message("code") or (
            "install it with 'calkit install code'"
        )
        warn(f"VS Code isn't installed; {hint}")
        return None
    if entry is None:
        if typer.confirm(
            "VS Code isn't installed. Open its download page?", default=True
        ):
            typer.launch(download_url)
        return None
    calkit.echo("VS Code isn't installed. Calkit can install it with:")
    calkit.echo(f"  {entry['script']}")
    choice = typer.prompt(
        "1. Install VS Code\n"
        "2. Install VS Code, with Calkit's recommended extensions and "
        "settings\n"
        "3. Open VS Code's download page instead\n"
        "4. Don't install it; open the folder\n"
        "Choose",
        default="1",
        type=click.Choice(["1", "2", "3", "4"]),
    )
    if choice == "3":
        typer.launch(download_url)
        calkit.echo("Once it's installed, run this again to open the project")
        return None
    if choice == "4":
        return None
    if not install.install("code"):
        warn("Couldn't install VS Code")
        return None
    code = shutil.which("code")
    if code is None or choice != "2":
        return code
    # Recommended extensions, and settings that aren't already set, so a
    # choice the user made in VS Code is kept
    extensions = load_json("vscode", "extensions.json")["recommendations"]
    args = [a for e in extensions for a in ("--install-extension", e)]
    subprocess.call([code, *args])
    settings_dir = {
        "mac": "~/Library/Application Support/Code/User",
        "windows": "%APPDATA%\\Code\\User",
    }.get(platform, "~/.config/Code/User")
    settings_path = os.path.join(
        os.path.expandvars(os.path.expanduser(settings_dir)), "settings.json"
    )
    current: dict = {}
    if os.path.isfile(settings_path):
        try:
            with open(settings_path, encoding="utf-8") as f:
                current = json.load(f)
        except ValueError:
            # VS Code allows comments there, which can't be merged into
            # without losing them
            warn(
                f"Not adding Calkit's settings to {settings_path}, since it "
                "isn't plain JSON"
            )
            return code
    recommended = load_json("vscode", "settings.json")
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(recommended | current, f, indent=2)
    return code
