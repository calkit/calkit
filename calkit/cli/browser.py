"""CLI for connecting the browser extension to Calkit on this machine."""

from __future__ import annotations

from typing import Annotated

import typer

browser_app = typer.Typer(no_args_is_help=True)


@browser_app.command(name="install")
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
    from calkit.browser import install_host

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


@browser_app.command(name="uninstall")
def uninstall() -> None:
    """Stop the browser extension working with projects on this machine."""
    import calkit
    from calkit.browser import uninstall_host

    uninstall_host()
    calkit.echo("The browser extension can no longer reach this machine")
