"""CLI for interacting with Calkit hubs."""

from __future__ import annotations

import os
from typing import Annotated

import typer

import calkit
from calkit.cli import raise_error

hub_app = typer.Typer(no_args_is_help=True)

_HUB_OPTION_HELP = (
    "Hub to target: an environment name (production, staging, local) or a "
    "known hub URL, e.g., https://calkit.io. Defaults to the working "
    "directory project's hub, if declared, else production."
)


def _use_hub(hub: str | None) -> None:
    """Point subsequent hub API calls at the requested instance.

    Resolution order: the ``--hub`` option, then ``CALKIT_ENV``, then the
    working directory project's declared ``hub``, then production.
    """
    from calkit import config

    if hub is not None:
        if hub in ["production", "staging", "local"]:
            config.set_env(hub)  # type: ignore[arg-type]
            return
        env = calkit.hub.env_for_hub(hub)
        if env is None:
            raise_error(
                f"Unknown hub '{hub}'; arbitrary hub URLs are not yet "
                "supported (only production, staging, and local)"
            )
        config.set_env(env)  # type: ignore[arg-type]
        return
    # An explicitly set environment remains the source of truth
    if os.environ.get("CALKIT_ENV"):
        return
    try:
        declared = calkit.load_calkit_info().get("hub")
    except Exception:
        declared = None
    if declared:
        env = calkit.hub.env_for_hub(declared)
        if env is not None:
            config.set_env(env)  # type: ignore[arg-type]
        else:
            raise_error(
                f"This project declares hub {declared}, which is not yet "
                "supported; set CALKIT_ENV or use --hub to pick a built-in "
                "instance"
            )


@hub_app.command(name="get")
def get(
    endpoint: Annotated[str, typer.Argument(help="API endpoint")],
    hub: Annotated[
        str | None, typer.Option("--hub", help=_HUB_OPTION_HELP)
    ] = None,
):
    """Get a resource from the hub API."""
    _use_hub(hub)
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    try:
        resp = calkit.hub.get(endpoint)
        typer.echo(resp)
    except Exception as e:
        raise_error(str(e))


@hub_app.command(name="login")
def login(
    hub: Annotated[
        str | None, typer.Option("--hub", help=_HUB_OPTION_HELP)
    ] = None,
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
    """Log in to a Calkit hub.

    First try a GET request to the /user endpoint to check if the user is
    already logged in. If not, perform OAuth device flow.
    """
    from requests.exceptions import HTTPError

    _use_hub(hub)
    if not force:
        try:
            calkit.hub.get("/user")
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
        calkit.hub.run_device_flow()
    except calkit.hub.DeviceLoginError as e:
        raise_error(str(e))
