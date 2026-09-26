"""CLI for managing this machine's Operator."""

from __future__ import annotations

import os

import typer
from typing_extensions import Annotated

from calkit.cli import AliasGroup, raise_error

operator_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


def _require_config() -> dict:
    from calkit import operator

    cfg = operator.load_config()
    if cfg is None:
        raise_error(
            "No Operator is installed on this machine; "
            "run 'calkit install operator' first"
        )
    assert cfg is not None
    return cfg


@operator_app.command(name="start")
def start(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Log in more detail.")
    ] = False,
) -> None:
    """Run the Operator in the foreground, e.g., inside tmux."""
    import logging

    from calkit import operator

    cfg = _require_config()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    typer.echo(f"Starting Operator '{cfg['name']}' (Ctrl+C to stop)")
    try:
        operator.run(cfg)
    except operator.OperatorRevoked:
        # A clean exit, so a service manager doesn't restart it
        typer.echo("This Operator has been revoked on the hub; stopping")
    except KeyboardInterrupt:
        typer.echo("Stopped")


@operator_app.command(name="status")
def status() -> None:
    """Show this machine's Operator and the workspaces it allows."""
    from calkit import operator

    cfg = _require_config()
    typer.echo(f"Name: {cfg['name']}")
    typer.echo(f"Hub API: {cfg['api_url']}")
    service = operator.get_service_status()
    typer.echo(f"Service: {service or 'not installed'}")
    typer.echo("Workspaces:")
    for ws in operator.discover_workspaces(cfg):
        project = ws.get("project") or "unknown project"
        typer.echo(f"  {ws['path']} ({ws['kind']}, {project})")


@operator_app.command(name="stop")
def stop() -> None:
    """Stop the Operator's service until it's restarted."""
    from calkit import operator

    _require_config()
    try:
        operator.set_service_running(False)
    except RuntimeError as e:
        raise_error(str(e))
    typer.echo("Stopped the Operator")


@operator_app.command(name="restart")
def restart() -> None:
    """Restart the Operator's service, e.g., after updating Calkit."""
    from calkit import operator

    _require_config()
    try:
        operator.set_service_running(False)
    except Exception:
        pass
    try:
        operator.set_service_running(True)
    except RuntimeError as e:
        raise_error(str(e))
    typer.echo("Restarted the Operator")


@operator_app.command(name="logs")
def logs(
    follow: Annotated[
        bool, typer.Option("--follow", "-f", help="Keep printing new lines.")
    ] = False,
) -> None:
    """Show the Operator service's logs."""
    import platform
    import subprocess

    from calkit import operator

    _require_config()
    if platform.system() == "Linux":
        cmd = ["journalctl", "--user", "-u", operator.SYSTEMD_UNIT]
        cmd += ["-f"] if follow else ["-n", "100", "--no-pager"]
    else:
        cmd = ["tail", "-n", "100"] + (["-f"] if follow else [])
        cmd.append(operator.get_log_path())
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass


@operator_app.command(name="add-workspace")
def add_workspace(
    path: Annotated[
        str, typer.Argument(help="Path to a Calkit project.")
    ] = ".",
) -> None:
    """Let the hub use a project outside ~/calkit as a workspace."""
    from calkit import operator

    cfg = _require_config()
    path = os.path.realpath(path)
    if not os.path.isfile(os.path.join(path, "calkit.yaml")):
        raise_error(f"{path} is not a Calkit project")
    workspaces = cfg.setdefault("workspaces", [])
    if path in workspaces:
        typer.echo(f"{path} is already a workspace")
        return
    workspaces.append(path)
    operator.save_config(cfg)
    typer.echo(f"Added {path}; it will show on the hub at the next check-in")


@operator_app.command(name="uninstall")
def uninstall() -> None:
    """Revoke this machine's Operator on the hub and remove it here."""
    from calkit import hub, operator

    cfg = _require_config()
    operator.uninstall_service()
    try:
        hub._request(
            "delete", f"/operators/{cfg['id']}", base_url=cfg["api_url"]
        )
    except Exception as e:
        response = getattr(e, "response", None)
        # 410 means it was already revoked, e.g., from the hub
        if response is None or response.status_code != 410:
            typer.echo(
                f"Could not revoke '{cfg['name']}' on the hub ({e}); "
                "revoke it from your hub settings"
            )
    os.remove(operator.get_config_path())
    typer.echo(f"Uninstalled Operator '{cfg['name']}'")
