"""CLI for connecting the browser extension to Calkit on this machine."""

from __future__ import annotations

from typing import Annotated

import typer

browser_link_app = typer.Typer(no_args_is_help=True)


@browser_link_app.command(name="install")
def install(
    extension_ids: Annotated[
        list[str],
        typer.Option(
            "--extension-id",
            help=(
                "ID of another extension that may connect, e.g., one loaded "
                "unpacked in development."
            ),
        ),
    ] = [],
) -> None:
    """Let the browser extension work with projects on this machine."""
    import calkit
    from calkit.browser_link import install_host

    browsers = install_host(extension_ids=extension_ids)
    if not browsers:
        calkit.echo(
            "No supported browser has been run here yet; run this again "
            "after opening one"
        )
        return
    calkit.echo(
        "The browser extension can now work with projects on this machine "
        f"from {', '.join(browsers)}"
    )


@browser_link_app.command(name="uninstall")
def uninstall() -> None:
    """Stop the browser extension working with projects on this machine."""
    import calkit
    from calkit.browser_link import uninstall_host

    uninstall_host()
    calkit.echo("The browser extension can no longer reach this machine")


@browser_link_app.command(name="status")
def status() -> None:
    """Check whether the browser extension can reach Calkit on this
    machine.
    """
    import calkit
    from calkit.browser_link import (
        CHROME_EXTENSION_IDS,
        FIREFOX_EXTENSION_IDS,
        get_host_status,
    )
    from calkit.cli import raise_error

    host = get_host_status()
    if host["python_path"]:
        calkit.echo(
            f"Launcher: {host['launcher_path']} (runs {host['python_path']})"
        )
    for browser, ids in host["browsers"].items():
        if ids is None:
            calkit.echo(f"{browser}: not set up")
            continue
        names = [
            "the Calkit extension"
            if i in CHROME_EXTENSION_IDS + FIREFOX_EXTENSION_IDS
            else i
            for i in ids
        ]
        calkit.echo(f"{browser}: allows {', '.join(names)}")
    if host["error"] is not None:
        raise_error(
            f"{host['error']}; run 'calkit browser-link install' to set it up"
        )
    calkit.echo(f"Calkit {host['version']} answers when the browser starts it")
