"""CLI for interacting with Calkit Cloud instances."""

from __future__ import annotations

from typing import Annotated

import typer

import calkit
from calkit.cli import raise_error

cloud_app = typer.Typer(no_args_is_help=True)


@cloud_app.command(name="get")
def get(endpoint: Annotated[str, typer.Argument(help="API endpoint")]):
    """Get a resource from the Cloud API."""
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    try:
        resp = calkit.cloud.get(endpoint)
        typer.echo(resp)
    except Exception as e:
        raise_error(str(e))


@cloud_app.command(name="login")
def login(
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help=(
                "Force logging in again even if already authenticated. "
                "Will store a new token in your local config."
            ),
        ),
    ] = False,
):
    """Login to the Calkit Cloud.

    First try a GET request to the /user endpoint to check if the user is
    already logged in. If not, perform OAuth device flow.
    """
    from requests.exceptions import HTTPError

    if not force:
        try:
            calkit.cloud.get("/user")
            calkit.echo("Authenticated successfully ✅")
            return
        except (ValueError, HTTPError) as e:
            # Any auth failure (no token, 401, 403) falls through to the
            # device flow so the user can re-authenticate. Other HTTP errors
            # (e.g. 5xx) are surfaced.
            if isinstance(e, HTTPError) and not any(
                code in str(e) for code in ("401", "403")
            ):
                raise_error(str(e))
    try:
        calkit.cloud.run_device_flow()
    except calkit.cloud.DeviceLoginError as e:
        raise_error(str(e))
