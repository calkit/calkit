"""CLI for interacting with Calkit hubs."""

from __future__ import annotations

from typing import Annotated

import typer

import calkit
from calkit.cli import raise_error
from calkit.cli.config import hub_config_app

hub_app = typer.Typer(no_args_is_help=True)
hub_app.add_typer(
    hub_config_app,
    name="config",
    help="Work with per-hub credentials (tokens).",
)

_HUB_OPTION_HELP = (
    "URL of the hub to target, e.g., https://staging.calkit.io. Defaults "
    "to the working directory project's hub, if declared, else calkit.io."
)


def _use_hub(hub: str | None) -> None:
    """Point subsequent hub API calls at the requested instance.

    Only ``--hub`` is handled here. Without it, every command already
    resolves the same way (``CALKIT_HUB``, then the working directory
    project's declared ``hub``, then ``default_hub``, then calkit.io),
    and re-deriving that here is how the two used to disagree.
    """
    from calkit import config

    if hub is None:
        return
    if hub in ["test", "local", "staging", "production"]:
        raise_error("--hub takes a hub URL, e.g., https://staging.calkit.io")
    config.set_hub(hub)


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
