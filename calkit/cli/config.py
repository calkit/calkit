"""Config CLI."""

from __future__ import annotations

import glob
import os
import subprocess

import git
import typer
from git.exc import InvalidGitRepositoryError
from typing_extensions import Annotated

import calkit
from calkit import config
from calkit.cli.core import raise_error
from calkit.dvc import configure_remote, get_remotes, set_remote_auth

config_app = typer.Typer(no_args_is_help=True)


@config_app.command(name="set")
def set_config_value(key: str, value: str):
    """Set a value in the config."""
    keys = config.Settings.model_fields.keys()
    if key not in keys:
        raise_error(
            f"Invalid config key: '{key}'; Valid keys are: {list(keys)}"
        )
    try:
        cfg = config.read()
        cfg = config.Settings.model_validate(cfg.model_dump() | {key: value})
    except Exception as e:
        raise_error(f"Failed to set {key} in config: {e}")
    cfg.write()


@config_app.command(name="get")
def get_config_value(key: str) -> None:
    """Get and print a value from the config."""
    cfg = config.read().model_dump()
    if key not in cfg:
        raise_error(
            f"Invalid config key: '{key}'; Valid keys are: {list(cfg.keys())}"
        )
    val = cfg[key]
    if val is not None:
        print(val)
    else:
        print()


@config_app.command(name="unset")
def unset_config_value(key: str):
    """Unset a value in the config, returning it to default."""
    model_fields = config.Settings.model_fields
    if key not in model_fields:
        raise_error(
            f"Invalid config key: '{key}'; "
            f"Valid keys: {list(model_fields.keys())}"
        )
    try:
        cfg = config.read()
        setattr(cfg, key, model_fields[key].default)
    except Exception as e:
        raise_error(f"Failed to unset {key} in config: {e}")
    cfg.write()


@config_app.command(name="setup-remote", help="Alias for 'remote'.")
@config_app.command(name="remote")
def setup_remote(
    no_commit: Annotated[
        bool,
        typer.Option(
            "--no-commit", help="Do not commit changes to DVC config."
        ),
    ] = False,
):
    """Setup the Calkit cloud as the default DVC remote and store a token in
    the local config.
    """
    try:
        configure_remote()
        set_remote_auth()
    except subprocess.CalledProcessError:
        if not os.path.isfile(".dvc/config"):
            raise_error(
                "DVC remote config failed; have you run `calkit init`?"
            )
        raise_error(
            "Failed to configure DVC remote; check DVC config for errors"
        )
    except InvalidGitRepositoryError:
        raise_error("Current directory is not a Git repository")
    except (ValueError, RuntimeError) as e:
        raise_error(f"Failed to set up DVC remote: {e}")
    if not no_commit:
        repo = git.Repo()
        repo.git.add(".dvc/config")
        if ".dvc/config" in calkit.git.get_staged_files():
            typer.echo("Committing changes to DVC config")
            repo.git.commit([".dvc/config", "-m", "Set DVC remote"])


@config_app.command(name="setup-remote-auth", help="Alias for 'remote-auth'.")
@config_app.command(name="remote-auth")
def setup_remote_auth():
    """Store a Calkit cloud token in the local DVC config for all Calkit
    remotes.
    """
    try:
        remotes = get_remotes()
    except Exception:
        raise_error("Cannot list DVC remotes; check DVC config for errors")
    for name, url in remotes.items():
        if name == "calkit" or name.startswith("calkit:"):
            typer.echo(f"Setting up authentication for DVC remote: {name}")
            set_remote_auth(remote_name=name)


@config_app.command(name="list")
def list_config_keys():
    """List keys in the config."""
    cfg = config.read()
    for key in cfg.model_dump():
        typer.echo(key)


@config_app.command(name="github-ssh")
def config_github_ssh():
    """Walk through the process of adding an SSH key to GitHub."""
    typer.echo("Checking if you can already connect to GitHub via SSH")
    # First check if we can already connect to GitHub
    ssh_test_cmd = ["ssh", "-T", "git@github.com"]
    p = subprocess.run(ssh_test_cmd, capture_output=True, text=True)
    if "successfully authenticated" in p.stderr:
        typer.echo("You can already connect to GitHub via SSH")
        go_on = typer.confirm("Do you want to add a new SSH key anyway?")
        if not go_on:
            raise typer.Exit()
    # If we can, ask the user if they still want to add a new key
    # First check if the user has any SSH keys
    ssh_dir = os.path.expanduser("~/.ssh")
    existing_pub_keys = glob.glob(os.path.join(ssh_dir, "*.pub"))
    # If not run ssh-keygen
    if existing_pub_keys:
        # Ask the user if they want to use an existing key or create a new one
        typer.echo("Existing SSH public keys found:")
        for i, key in enumerate(existing_pub_keys):
            typer.echo(f"{i + 1}: {key}")
        use_existing = typer.confirm("Do you want to use one of these keys?")
        if use_existing:
            key_choice = typer.prompt(
                "Enter the number of the key to use", type=int
            )
            if 1 <= key_choice <= len(existing_pub_keys):
                key_path = existing_pub_keys[key_choice - 1][:-4]
            else:
                typer.echo("Invalid choice")
                # Keep asking until they give a valid choice
                while True:
                    key_choice = typer.prompt(
                        "Enter the number of the key to use", type=int
                    )
                    if 1 <= key_choice <= len(existing_pub_keys):
                        key_path = existing_pub_keys[key_choice - 1][:-4]
                        break
                    else:
                        typer.echo("Invalid choice, please try again.")
        else:
            key_path = typer.prompt(
                "Enter the path to save the new SSH key",
                default=os.path.join(ssh_dir, "id_ed25519"),
            )
    else:
        typer.echo("No existing SSH keys found")
        key_path = typer.prompt(
            "Enter the path to save the new SSH key",
            default=os.path.join(ssh_dir, "id_ed25519"),
        )
    # Get the user's email from their Git config, and ask them if they want to
    # use that or a different one
    try:
        user_git_email = git.Git().config("--get", "user.email").strip()
    except Exception:
        user_git_email = typer.prompt(
            "No email found in Git config; enter email for SSH key"
        )
        git.Git().config("--global", "user.email", user_git_email)
    # Do the same for user name even though we don't need it
    try:
        user_git_name = git.Git().config("--get", "user.name").strip()
    except Exception:
        user_git_name = typer.prompt(
            "No name found in Git config; enter name for SSH key"
        )
        git.Git().config("--global", "user.name", user_git_name)
    keygen_cmd = [
        "ssh-keygen",
        "-t",
        "ed25519",
        "-C",
        user_git_email,
        "-f",
        key_path,
    ]
    subprocess.run(keygen_cmd)
    # Start the SSH agent in the background
    typer.echo("Checking that the SSH agent is running")
    ssh_agent_cmd = subprocess.run(
        ["ssh-agent", "-s"], capture_output=True, text=True
    ).stdout
    p = subprocess.run(ssh_agent_cmd, shell=True)
    if p.returncode != 0:
        raise_error("Failed to start ssh-agent")
    # Add the SSH key to the ssh-agent
    typer.echo(f"Adding SSH key to ssh-agent: {key_path}")
    cmd = ["ssh-add", key_path]
    p = subprocess.run(cmd)
    if p.returncode != 0:
        raise_error("Failed to add SSH key to ssh-agent; please try again")
    # Now add to GitHub
    gh_ssh_url = "https://github.com/settings/ssh/new"
    typer.echo(
        "Add the new SSH key to your GitHub account by visiting:\n"
        f"{gh_ssh_url}"
    )
    with open(key_path + ".pub", "r") as f:
        pub_key = f.read()
    typer.echo(f"Paste this into the public key field:\n\n{pub_key}\n")
    typer.confirm("Press Enter when done", default=True)
    typer.echo("Testing SSH connection to GitHub")
    p = subprocess.run(ssh_test_cmd, capture_output=True, text=True)
    if "successfully authenticated" in p.stderr:
        typer.echo("Successfully connected to GitHub via SSH!")
    else:
        raise_error(
            "Failed to connect to GitHub via SSH; please check your setup"
        )
