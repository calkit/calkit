"""CLI for managing this machine's Operator."""

from __future__ import annotations

import os

import typer
from typing_extensions import Annotated

from calkit.cli import AliasGroup, raise_error

operator_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)

HubOption = Annotated[
    str | None,
    typer.Option(
        "--hub",
        help=(
            "URL of the hub the Operator is for, e.g., https://calkit.io; "
            "a machine can have one per hub. Defaults to the only one here, "
            "or for install, to your default hub."
        ),
    ),
]


def _select_hub(hub: str | None, installing: bool = False) -> None:
    """Choose which hub's Operator a command acts on."""
    from calkit import operator

    if hub is not None:
        if hub in ["test", "local", "staging", "production"]:
            raise_error("--hub takes a hub URL, e.g., https://calkit.io")
        operator.select_hub(hub)
        return
    hubs = [] if installing else operator.list_configured_hubs()
    if len(hubs) > 1:
        raise_error(
            "This machine has Operators for more than one hub ("
            + ", ".join(hubs)
            + "); choose one with --hub"
        )
    operator.select_hub(hubs[0] if hubs else None)


def _require_config() -> dict:
    from calkit import operator

    cfg = operator.load_config()
    if cfg is None:
        raise_error(
            "No Operator for this hub is installed on this machine; "
            "run 'calkit operator install' first"
        )
    assert cfg is not None
    return cfg


@operator_app.command(name="install")
def install(
    hub: HubOption = None,
    at_boot: Annotated[
        bool,
        typer.Option(
            "--boot",
            help="On macOS, start at boot rather than at login (needs sudo).",
        ),
    ] = False,
    cron: Annotated[
        bool,
        typer.Option(
            "--cron",
            help=(
                "Have cron start it when the hub asks rather than running it "
                "as a service, e.g., on a cluster's login node."
            ),
        ),
    ] = False,
    ssh: Annotated[
        str | None,
        typer.Option(
            "--ssh",
            help=(
                "Install it on another machine over SSH, e.g., "
                "'user@cluster.example.edu' or a host from ~/.ssh/config, "
                "installing Calkit there if needed."
            ),
        ),
    ] = None,
    no_service: Annotated[
        bool,
        typer.Option(
            "--no-service",
            help=(
                "Only register it, e.g., to run it with 'calkit operator "
                "start' inside tmux on a cluster."
            ),
        ),
    ] = False,
) -> None:
    """Register this machine as an Operator and run it as a service.

    Also available as 'calkit install operator'.
    """
    from calkit import operator
    from calkit.cli import warn

    def explain(e: Exception) -> str:
        # Registering takes a verified email, since setting up two-factor
        # authentication proves itself by email
        if "Verify your email first" in str(e):
            from calkit.hub import get_hub_url

            return (
                f"Verify your email in your settings at {get_hub_url()}/settings,"
                " then run this again"
            )
        return str(e)

    # Sessions would be root shells, and it asks for sudo when it needs it
    if os.name == "posix" and os.geteuid() == 0 and os.getenv("SUDO_USER"):
        raise_error("Run this without sudo")
    try:
        _select_hub(hub, installing=True)
        hub_url = operator.use_own_hub()
    except ValueError as e:
        raise_error(str(e))
    if ssh is not None:
        from calkit.dependencies import _is_interactive

        try:
            remote = operator.install_remote(
                ssh,
                cron=cron,
                no_service=no_service,
                interactive=_is_interactive(),
            )
        except Exception as e:
            raise_error(
                f"Failed to install the operator on {ssh}: {explain(e)}"
            )
        typer.echo(f"✅ Installed Operator '{remote['name']}' on {ssh}")
        return
    cfg = operator.load_config()
    # A revoked Operator, or one from another hub, would exit at its first
    # check-in, so it's registered again
    if cfg is not None and not operator.is_registered(cfg):
        typer.echo(f"Operator '{cfg.get('name')}' is no longer registered")
        cfg = None
    if cfg is None:
        typer.echo(f"Registering this machine with {hub_url}")
        try:
            cfg = operator.register()
        except Exception as e:
            raise_error(f"Failed to register this machine: {explain(e)}")
        typer.echo(f"✅ Registered Operator '{cfg['name']}'")
    else:
        typer.echo(f"Operator '{cfg['name']}' is already registered")
    # Whatever ran it before is replaced, e.g., a service when switching to
    # cron mode, or one installed before Operators were kept per hub, so
    # the two don't both run it
    operator.uninstall_service()
    operator.uninstall_service(key="")
    if no_service:
        typer.echo("Run 'calkit operator start' to connect it")
        return
    if cron:
        try:
            operator.install_cron()
        except NotImplementedError as e:
            raise_error(str(e))
        typer.echo(
            "✅ Installed the Operator in cron mode; it checks in every "
            "5 minutes and connects when you open it from the hub"
        )
        return
    try:
        notes = operator.install_service(at_boot=at_boot)
    except NotImplementedError as e:
        raise_error(str(e))
    typer.echo("✅ Installed and started the Operator's service")
    for note in notes:
        warn(note)


@operator_app.command(name="start")
def start(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Log in more detail.")
    ] = False,
    # How it's being run, which the service and crontab entries set: in
    # cron mode it only connects when the hub asks and stops when idle
    mode: Annotated[str, typer.Option("--mode", hidden=True)] = "foreground",
    hub: HubOption = None,
) -> None:
    """Run the Operator in the foreground, e.g., inside tmux."""
    import logging

    from calkit import operator

    _select_hub(hub)
    cfg = _require_config()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if mode not in ("foreground", "service", "cron"):
        raise_error(f"Unknown mode '{mode}'")
    if mode == "foreground":
        typer.echo(f"Starting Operator '{cfg['name']}' (Ctrl+C to stop)")
    try:
        if not operator.run(cfg, mode=mode):
            # Cron starts one every few minutes, so this is routine there
            if mode != "cron":
                typer.echo("Another Operator is already running here")
    except operator.OperatorRevoked:
        # A clean exit, so a service manager doesn't restart it
        typer.echo("This Operator has been revoked on the hub; stopping")
    except KeyboardInterrupt:
        typer.echo("Stopped")


@operator_app.command(name="status")
def status(hub: HubOption = None) -> None:
    """Show this machine's Operators and the workspaces they allow."""
    from calkit import operator

    # Each hub's Operator, unless one was asked for
    hubs = [hub] if hub is not None else operator.list_configured_hubs()
    if not hubs:
        _select_hub(None)
        _require_config()
    for i, hub_url in enumerate(hubs):
        if i:
            typer.echo()
        _select_hub(hub_url)
        cfg = _require_config()
        typer.echo(f"Name: {cfg['name']}")
        typer.echo(f"Hub: {operator.get_hub_url()}")
        service = operator.get_service_status()
        typer.echo(f"Installed as: {service or 'nothing; run it with start'}")
        pid = operator.get_running_pid()
        typer.echo(f"Running: {f'yes (PID {pid})' if pid else 'no'}")
        typer.echo("Workspaces:")
        for ws in operator.discover_workspaces(cfg):
            project = ws.get("project") or "unknown project"
            typer.echo(f"  {ws['path']} ({ws['kind']}, {project})")


@operator_app.command(name="stop")
def stop(hub: HubOption = None) -> None:
    """Stop the Operator's service until it's restarted."""
    from calkit import operator

    _select_hub(hub)
    _require_config()
    try:
        operator.set_service_running(False)
    except RuntimeError as e:
        raise_error(str(e))
    typer.echo("Stopped the Operator")


@operator_app.command(name="restart")
def restart(hub: HubOption = None) -> None:
    """Restart the Operator's service, e.g., after updating Calkit."""
    import subprocess

    from calkit import operator

    _select_hub(hub)
    _require_config()
    try:
        operator.restart_service()
    except (RuntimeError, subprocess.CalledProcessError) as e:
        raise_error(str(e))
    typer.echo("Restarted the Operator")


@operator_app.command(name="logs")
def logs(
    follow: Annotated[
        bool, typer.Option("--follow", "-f", help="Keep printing new lines.")
    ] = False,
    hub: HubOption = None,
) -> None:
    """Show the Operator service's logs."""
    import platform
    import subprocess

    from calkit import operator

    _select_hub(hub)
    _require_config()
    # Only a systemd service logs to the journal; cron and the others log
    # to a file
    if platform.system() == "Linux" and os.path.isfile(
        operator._systemd_unit_path()
    ):
        cmd = ["journalctl", "--user", "-u", operator.systemd_unit()]
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
    hub: HubOption = None,
) -> None:
    """Let the hub use a project outside ~/calkit as a workspace."""
    from calkit import operator

    _select_hub(hub)
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
def uninstall(hub: HubOption = None) -> None:
    """Revoke this machine's Operator on the hub and remove it here."""
    from calkit import hub as hub_api
    from calkit import operator

    _select_hub(hub)
    cfg = _require_config()
    operator.uninstall_service()
    try:
        hub_api._request(
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
