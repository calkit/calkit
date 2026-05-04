"""CLI for interacting with Calkit Cloud instances."""

from __future__ import annotations

import socket
import time
import webbrowser
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

    try:
        calkit.cloud.get("/user")
        calkit.echo("Authenticated successfully ✅")
        if not force:
            return
    except (ValueError, HTTPError) as e:
        if isinstance(e, HTTPError) and "401" not in str(e):
            raise_error(str(e))
    # Now perform the OAuth device flow
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = None
    try:
        calkit.echo("Initiating device login flow")
        resp = calkit.cloud.post(
            "/login/device",
            json={"hostname": hostname},
            auth=False,
        )
        device_code = resp["device_code"]
        verification_uri = resp["verification_uri"]
        expires_in = int(resp["expires_in"])
        interval = int(resp["interval"])
    except Exception as e:
        raise_error(f"Failed to initiate device login flow: {e}")
    calkit.echo("Authorize this device by opening this URL:")
    calkit.echo(verification_uri)
    calkit.echo("Waiting for authorization")
    try:
        webbrowser.open(verification_uri)
    except Exception:
        # If auto-open fails, user can still copy-paste the URL.
        pass
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        try:
            token_resp = calkit.cloud.post(
                "/login/device/token",
                json={"device_code": device_code},
                auth=False,
            )
        except Exception as e:
            txt = str(e)
            if "Device code has expired" in txt:
                raise_error(
                    "Device code has expired; Run 'calkit cloud login' again"
                )
            if "Device code not found" in txt:
                raise_error(
                    "Device code not found; Run 'calkit cloud login' again"
                )
            raise_error(f"Error while polling for device authorization: {e}")
        access_token = token_resp.get("access_token")
        if access_token:
            refresh_token = token_resp.get("refresh_token")
            try:
                cfg = calkit.config.read()
                cfg.access_token = access_token
                if refresh_token:
                    cfg.refresh_token = refresh_token
                cfg.write()
                calkit.cloud._tokens[calkit.cloud.get_base_url()] = (
                    access_token
                )
            except Exception as e:
                raise_error(f"Failed to save token in config: {e}")
            calkit.echo("Logged in successfully ✅")
            return
        sleep_seconds = min(interval, max(0.0, deadline - time.monotonic()))
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    raise_error(
        "Timed out waiting for device authorization; "
        "Run 'calkit cloud login' again"
    )
