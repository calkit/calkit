"""Core CLI functionality."""

import os
import subprocess

import typer


def print_sep(name: str):
    width = 66
    txt_width = len(name) + 2
    buffer_width = (width - txt_width) // 2
    buffer = "-" * buffer_width
    typer.echo(f"{buffer} {name} {buffer}")


def run_cmd(cmd: list[str]):
    if os.name == "nt":
        subprocess.call(cmd)
    else:
        import pty

        pty.spawn(cmd, lambda fd: os.read(fd, 1024))


def raise_error(txt: str):
    typer.echo(typer.style("Error: " + txt, fg="red"), err=txt)
    raise typer.Exit(1)


def warn(txt: str):
    typer.echo(typer.style("Warning: " + txt, fg="yellow"))
