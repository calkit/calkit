"""CLI for linking this machine to hubs."""

from __future__ import annotations

import os

import typer
from typing_extensions import Annotated

from calkit.cli import AliasGroup, raise_error, warn

link_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)

HubOption = Annotated[
    str | None,
    typer.Option(
        "--hub",
        help=(
            "URL of the hub the hub link is for, e.g., https://calkit.io; "
            "a machine can have one per hub. Defaults to the only one here, "
            "or for linking, to your default hub."
        ),
    ),
]


def _select_hub(hub: str | None, linking: bool = False) -> None:
    """Choose which hub's link a command acts on."""
    from calkit.hub import link as hub_link

    if hub is not None:
        if hub in ["test", "local", "staging", "production"]:
            raise_error("--hub takes a hub URL, e.g., https://calkit.io")
        hub_link.select_hub(hub)
        return
    hubs = [] if linking else hub_link.list_configured_hubs()
    if len(hubs) > 1:
        raise_error(
            "This machine is linked to more than one hub ("
            + ", ".join(hubs)
            + "); choose one with --hub"
        )
    hub_link.select_hub(hubs[0] if hubs else None)


def _each_hub(hub: str | None) -> list[str | None]:
    """The hubs a command acts on: the one asked for, else every one this
    machine is linked to.
    """
    from calkit.hub import link as hub_link

    if hub is not None:
        return [hub]
    # None, for the user's own hub, so a machine with none says so
    return list(hub_link.list_configured_hubs()) or [None]


def _require_config() -> dict:
    from calkit.hub import link as hub_link

    cfg = hub_link.load_config()
    if cfg is None:
        raise_error(
            "This machine isn't linked to this hub; run 'calkit hub link "
            "install' first"
        )
    assert cfg is not None
    return cfg


@link_app.command(name="install")
def install(
    hub: HubOption = None,
    login: Annotated[
        bool,
        typer.Option(
            "--login",
            help=(
                "Start at login instead of at boot (requires sudo on macOS "
                "and Linux)."
            ),
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
                "Link another machine over SSH, e.g., "
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
                "Only register it, e.g., to run it with 'calkit hub link "
                "start' inside tmux on a cluster."
            ),
        ),
    ] = False,
) -> None:
    """Link this machine to a hub and run the hub link as a service."""
    from calkit.cli import warn
    from calkit.hub import link as hub_link

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
    try:
        hub_link.refuse_root()
        _select_hub(hub, linking=True)
        hub_url = hub_link.use_own_hub()
    except ValueError as e:
        raise_error(str(e))
    if ssh is not None:
        from calkit.core import is_tty

        try:
            remote = hub_link.install_remote(
                ssh,
                cron=cron,
                no_service=no_service,
                login=login,
                interactive=is_tty(),
            )
        except Exception as e:
            raise_error(f"Failed to link {ssh}: {explain(e)}")
        typer.echo(f"✅ Linked machine '{remote['name']}' on {ssh}")
        return
    cfg = hub_link.load_config()
    # One whose key the hub refused can't connect, so it's revoked, in case
    # someone else holds its token, and registered again
    if cfg is not None and cfg.get("key_rejected"):
        typer.echo(
            f"The hub refused machine '{cfg.get('name')}', so it will be "
            "registered again"
        )
        try:
            hub_link.revoke_self(cfg)
        except Exception as e:
            warn(f"Couldn't revoke '{cfg.get('name')}' on the hub ({e})")
        cfg = None
    # A revoked machine, or one from another hub, would exit at its first
    # check-in, so it's registered again
    if cfg is not None and not hub_link.is_registered(cfg):
        typer.echo(f"Machine '{cfg.get('name')}' is no longer registered")
        cfg = None
    if cfg is None:
        typer.echo(f"Registering this machine with {hub_url}")
        try:
            cfg = hub_link.register()
        except Exception as e:
            raise_error(f"Failed to register this machine: {explain(e)}")
        typer.echo(f"✅ Registered machine '{cfg['name']}'")
    else:
        typer.echo(f"Machine '{cfg['name']}' is already registered")
    # Whatever ran it before is replaced, e.g., a service when switching to
    # cron mode, so the two don't both run it
    try:
        hub_link.uninstall_service()
    except RuntimeError as e:
        raise_error(str(e))
    if no_service:
        typer.echo("Run 'calkit hub link start' to connect it")
        return
    if cron:
        try:
            hub_link.install_cron()
        except NotImplementedError as e:
            raise_error(str(e))
        typer.echo(
            "✅ Installed the hub link in cron mode. It checks in every "
            "5 minutes and connects when you open a workspace from the hub."
        )
        return
    try:
        notes = hub_link.install_service(login=login)
    except NotImplementedError as e:
        raise_error(str(e))
    from calkit.hub import get_hub_url

    typer.echo(
        "✅ Linked this machine. Its workspaces will show at "
        f"{get_hub_url()}/workspaces."
    )
    for note in notes:
        warn(note)


@link_app.command(name="start")
def start(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Log in more detail.")
    ] = False,
    # How it's being run, which the service and crontab entries set: in
    # cron mode it only connects when the hub asks and stops when idle
    mode: Annotated[str, typer.Option("--mode", hidden=True)] = "foreground",
    hub: HubOption = None,
    # Set for a service whose manager would otherwise open the log as root
    log_file: Annotated[bool, typer.Option("--log-file", hidden=True)] = False,
) -> None:
    """Run the hub link in the foreground, e.g., inside tmux."""
    import logging

    from calkit.hub import link as hub_link

    try:
        hub_link.refuse_root()
    except ValueError as e:
        raise_error(str(e))
    _select_hub(hub)
    cfg = _require_config()
    if log_file:
        hub_link.log_to_file()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if mode not in ("foreground", "service", "cron"):
        raise_error(f"Unknown mode '{mode}'")
    if mode == "foreground":
        typer.echo(
            f"Starting the hub link for '{cfg['name']}' (Ctrl+C to stop)"
        )
    try:
        if not hub_link.run(cfg, mode=mode):
            # Cron starts one every few minutes, so this is routine there
            if mode != "cron":
                typer.echo(
                    "Another hub link to this hub is already running here"
                )
    except hub_link.LinkKeyRejected:
        # Already logged, and a clean exit, so a service manager doesn't
        # restart it
        pass
    except hub_link.LinkRevoked:
        # A clean exit, so a service manager doesn't restart it
        typer.echo("This machine has been revoked on the hub; stopping")
    except KeyboardInterrupt:
        typer.echo("Stopped")


@link_app.command(name="status")
def status(hub: HubOption = None) -> None:
    """Show this machine's hub links and their workspaces."""
    from calkit.hub import link as hub_link

    for i, hub_url in enumerate(_each_hub(hub)):
        if i:
            typer.echo()
        _select_hub(hub_url)
        cfg = _require_config()
        typer.echo(f"Name: {cfg['name']}")
        typer.echo(f"Hub: {hub_link.get_hub_url()}")
        service = hub_link.get_service_status()
        typer.echo(f"Installed as: {service or 'nothing; run it with start'}")
        pid = hub_link.get_running_pid()
        typer.echo(f"Running: {f'yes (PID {pid})' if pid else 'no'}")
        typer.echo("Workspaces:")
        for ws in hub_link.discover_workspaces(cfg):
            project = ws.get("project") or "unknown project"
            typer.echo(f"  {ws['path']} ({ws['kind']}, {project})")


@link_app.command(name="stop")
def stop(hub: HubOption = None) -> None:
    """Stop the hub link's service until it's restarted, for every hub
    unless one is given.
    """
    from calkit.hub import link as hub_link

    hubs = _each_hub(hub)
    failed = False
    for hub_url in hubs:
        _select_hub(hub_url)
        _require_config()
        name = f" for {hub_link.get_hub_url()}" if len(hubs) > 1 else ""
        try:
            hub_link.set_service_running(False)
        except RuntimeError as e:
            warn(f"Couldn't stop the hub link{name}: {e}")
            failed = True
            continue
        typer.echo(f"Stopped the hub link{name}")
    if failed:
        raise typer.Exit(1)


@link_app.command(name="restart")
def restart(hub: HubOption = None) -> None:
    """Restart the hub link's service, e.g., after updating Calkit, for
    every hub unless one is given.
    """
    import subprocess

    from calkit.hub import link as hub_link

    hubs = _each_hub(hub)
    failed = False
    for hub_url in hubs:
        _select_hub(hub_url)
        _require_config()
        name = f" for {hub_link.get_hub_url()}" if len(hubs) > 1 else ""
        try:
            hub_link.restart_service()
        except (RuntimeError, subprocess.CalledProcessError) as e:
            warn(f"Couldn't restart the hub link{name}: {e}")
            failed = True
            continue
        typer.echo(f"Restarted the hub link{name}")
    if failed:
        raise typer.Exit(1)


@link_app.command(name="logs")
def logs(
    follow: Annotated[
        bool, typer.Option("--follow", "-f", help="Keep printing new lines.")
    ] = False,
    hub: HubOption = None,
) -> None:
    """Show the hub link service's logs."""
    import platform
    import subprocess

    from calkit.hub import link as hub_link

    _select_hub(hub)
    _require_config()
    # Only a systemd service logs to the journal; cron and the others log
    # to a file
    if platform.system() == "Linux" and os.path.isfile(
        hub_link._systemd_unit_path()
    ):
        cmd = ["journalctl", "--user", "-u", hub_link.systemd_unit()]
        cmd += ["-f"] if follow else ["-n", "100", "--no-pager"]
    else:
        cmd = ["tail", "-n", "100"] + (["-f"] if follow else [])
        cmd.append(hub_link.get_log_path())
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass


@link_app.command(name="add-workspace")
def add_workspace(
    path: Annotated[
        str, typer.Argument(help="Path to a Calkit project.")
    ] = ".",
    hub: HubOption = None,
) -> None:
    """Add a project as a workspace, e.g., one outside ~/calkit and ~/dev, or
    one on another hub.
    """
    from calkit.hub import link as hub_link

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
    hub_link.save_config(cfg)
    typer.echo(f"Added {path}; it will show on the hub at the next check-in")


@link_app.command(name="uninstall")
def uninstall(hub: HubOption = None) -> None:
    """Revoke this machine on the hub and remove its hub link."""
    from calkit.hub import link as hub_link

    _select_hub(hub)
    cfg = _require_config()
    try:
        hub_link.uninstall_service()
    except RuntimeError as e:
        raise_error(str(e))
    # With its own token, so it works however you're signed in here
    try:
        hub_link.revoke_self(cfg)
    except Exception as e:
        typer.echo(
            f"Could not revoke '{cfg['name']}' on the hub ({e}); "
            "revoke it from your hub settings"
        )
    os.remove(hub_link.get_config_path())
    typer.echo(f"Unlinked machine '{cfg['name']}'")
