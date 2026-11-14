"""CLI for opening things."""

from __future__ import annotations

import os
from typing import Annotated

import typer

import calkit
from calkit.cli import raise_error, warn

open_app = typer.Typer(no_args_is_help=True)

# Commands for the editors 'default_editor' can name
EDITOR_COMMANDS = {
    "vscode": "code",
    "cursor": "cursor",
    "vscodium": "codium",
    "positron": "positron",
    "antigravity": "antigravity",
    "windsurf": "windsurf",
    "jupyterlab": "jupyter lab",
}
# Commands of editors built on VS Code, which take its extensions, from its
# marketplace or Open VSX, both of which have Calkit's
VSCODE_COMMANDS = {
    "code",
    "code-insiders",
    "cursor",
    "codium",
    "positron",
    "antigravity",
    "windsurf",
}
CALKIT_EXTENSION_ID = "calkit.calkit-vscode"


def split_command(command: str, windows: bool | None = None) -> list[str]:
    """Split a command into its arguments the way the platform's shell
    would, so a Windows path keeps its backslashes.
    """
    import shlex

    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return shlex.split(command)
    # Non-POSIX mode keeps backslashes, but also the quotes around a quoted
    # argument, e.g., a path with spaces
    return [
        arg[1:-1] if len(arg) > 1 and arg[0] == arg[-1] == '"' else arg
        for arg in shlex.split(command, posix=False)
    ]


@open_app.command(name="project")
def open_project(
    project: Annotated[
        str,
        typer.Argument(
            help=(
                "Project name, or owner and name, e.g., 'someone/my-proj', "
                "with its hub to clone from another, e.g., "
                "'calkit.example.edu/someone/my-proj'."
            )
        ),
    ],
    file_path: Annotated[
        str | None,
        typer.Option(
            "--path",
            "-p",
            help="File in the project to open too, e.g., a notebook.",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Clone into ~/calkit without asking if it isn't here.",
        ),
    ] = False,
    with_editor: Annotated[
        str | None,
        typer.Option(
            "--with",
            "-w",
            help=(
                "Editor to open it with instead of the default, e.g., "
                "'jupyterlab', or a command that takes the folder."
            ),
        ),
    ] = None,
    hub: Annotated[
        str | None,
        typer.Option(
            "--hub",
            help=(
                "Hub to clone it from if it isn't here, e.g., "
                "https://calkit.example.edu, or localhost for a development "
                "hub. Defaults to calkit.io."
            ),
        ),
    ] = None,
) -> None:
    """Open a project on this machine in its editor, from anywhere.

    Looks for it among the Calkit projects in your home folder, e.g., in
    ~/calkit or ~/dev, or wherever Calkit created or cloned it, and offers
    to clone it into ~/calkit if it isn't there. The editor is the
    'default_editor' setting, VS Code unless set otherwise, e.g., with
    'calkit config set default_editor cursor', or the one given with
    '--with'. Editors built on VS Code, e.g., Cursor, VSCodium, Positron,
    or Antigravity, get Calkit's extension if they don't have it.
    """
    import shutil
    import subprocess

    from calkit.core import is_tty

    # A hub only matters for cloning, since checkouts are found by owner and
    # name
    named_hub, owner, name = ([""] * 2 + project.split("/"))[-3:]
    if not name or project.count("/") > 2 or (named_hub and not owner):
        raise_error("Give the project as NAME, OWNER/NAME, or HUB/OWNER/NAME")
    # Read now, since cloning moves into the new repo, and a '.env' file
    # there must not get to choose what runs
    editor = with_editor or calkit.config.read().default_editor
    home = os.path.expanduser("~")
    default_path = os.path.join(home, "calkit", name)
    found = calkit.get_project_checkouts(name, owner=owner, warn=warn)
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

        clone(url=project, location=default_path, hub=hub)
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
    extra_args = []
    if file_path is not None:
        full_path = os.path.realpath(os.path.join(path, file_path))
        if os.path.commonpath([full_path, path]) != path:
            raise_error(f"{file_path} isn't in the project")
        if not os.path.isfile(full_path):
            raise_error(f"{file_path} isn't in {path}")
        extra_args = [full_path]
    # Open it in the configured editor, which is either one we know the
    # command for or a command itself
    cmd = split_command(EDITOR_COMMANDS.get(editor, editor))
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
    # Calkit's extension is how the editor shows the project's pipeline
    command_name = os.path.splitext(os.path.basename(cmd[0]))[0].lower()
    if command_name in VSCODE_COMMANDS:
        try:
            listed = subprocess.run(
                [exe, "--list-extensions"],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=60,
            ).stdout
        except (OSError, subprocess.SubprocessError) as e:
            warn(f"Couldn't check for Calkit's extension in {editor}: {e}")
            listed = CALKIT_EXTENSION_ID
        if CALKIT_EXTENSION_ID not in listed.lower().split():
            calkit.echo(f"Installing Calkit's extension in {editor}")
            subprocess.call([exe, "--install-extension", CALKIT_EXTENSION_ID])
    calkit.echo(f"Opening {path} with {editor}")
    # JupyterLab opens a file in the folder it's started from, where an
    # editor like VS Code takes the folder, then the file
    if editor == "jupyterlab" and extra_args:
        subprocess.call([exe, *cmd[1:], *extra_args], cwd=path)
    else:
        subprocess.call([exe, *cmd[1:], path, *extra_args])


def find_or_install_vscode() -> str | None:
    """Find VS Code's command, even where it isn't on PATH, or offer to
    install it, optionally with Calkit's recommended extensions and
    settings.
    """
    import click

    from calkit import install
    from calkit.core import is_tty

    code = install.find("code")
    if code is not None:
        return code
    entry = install.get_installer("code")
    download_url = install.DOWNLOAD_PAGES["code"]
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
    code = install.find("code")
    if code is not None and choice == "2":
        install.add_vscode_recs(code)
    return code
