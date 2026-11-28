"""CLI for calkits: figures and documents that carry what made them."""

from __future__ import annotations

import os
import re
from typing import Annotated

import typer

from calkit.cli import AliasGroup, raise_error, warn

kit_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


def get_n_files_text(n_files: int) -> str:
    """Get text for a number of files, e.g., '1 file' or '3 files'."""
    return f"{n_files} file" + "s" * (n_files != 1)


def get_default_dest_dir(path: str) -> str:
    """Get where a file's calkit expands by default: a folder named after
    the project it came from.
    """
    import calkit.kits

    try:
        kit = calkit.kits.read(path)
    except ValueError as e:
        raise_error(f"Can't read calkit: {e}")
    if kit is None:
        raise_error(f"{path} has no calkit")
    # The name comes from whoever made the calkit, so it only names a folder
    # here
    name = re.sub(r"[^A-Za-z0-9._-]", "-", kit.manifest.source.name or "")
    return name.strip(".-") or os.path.splitext(os.path.basename(path))[0]


@kit_app.command(name="create")
def create(
    path: Annotated[
        str, typer.Argument(help="Path of a figure or document to share.")
    ],
    output: Annotated[
        str | None,
        typer.Option(
            "--output",
            "-o",
            help="Where to write the copy; defaults to NAME.calkit.EXT here.",
        ),
    ] = None,
    max_size: Annotated[
        str | None,
        typer.Option(
            "--max-size",
            help=(
                "Largest the calkit may grow, e.g., 500KB or 20MB; data that "
                "doesn't fit is left out. Defaults to the file's size or "
                "1MB, whichever is bigger."
            ),
        ),
    ] = None,
    no_data: Annotated[
        bool,
        typer.Option(
            "--no-data",
            help="Leave out all data, so the calkit holds only the recipe.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help=(
                "Create it even if the pipeline is out of date or there are "
                "uncommitted changes, which leave it unrecorded."
            ),
        ),
    ] = False,
    no_record: Annotated[
        bool,
        typer.Option(
            "--no-record",
            help="Don't record it as a Git tag, or push that tag.",
        ),
    ] = False,
    to_clipboard: Annotated[
        bool,
        typer.Option(
            "--to-clipboard",
            "-c",
            help="Copy it to the clipboard, to paste into a chat or email.",
        ),
    ] = False,
) -> None:
    """Write a copy of a figure or document with a calkit embedded.

    The calkit holds what makes the file (stages, scripts, environments, and
    data that fits) so anyone with the copy can see what made it with
    'calkit describe', and expand or rerun it with 'calkit kit expand' or
    'calkit kit run'. Works with PNG, PDF, SVG, and HTML files.

    It's recorded as a Git tag at the commit it came from, which is pushed,
    so 'calkit kit list' shows what's been shared and the commit stays
    available.
    """
    import calkit.kits
    import calkit.pipeline

    def parse_size(txt: str) -> int:
        match = re.fullmatch(
            r"\s*([\d.]+)\s*([kmg]?)b?\s*", txt, flags=re.IGNORECASE
        )
        if match is None:
            raise_error(f"Invalid size: {txt}")
        factor = {"": 1, "k": 1e3, "m": 1e6, "g": 1e9}[match.group(2).lower()]
        return int(float(match.group(1)) * factor)

    ck_info = calkit.load_calkit_info()
    if not os.path.isfile(path):
        raise_error(f"{path} doesn't exist")
    stage = calkit.pipeline.get_stage_for_output(path, ck_info)
    if stage is None:
        raise_error(
            f"No pipeline stage makes {path}, so there's nothing to put in "
            "its calkit"
        )
    typer.echo(f"Checking stage '{stage}' is up to date")
    status = calkit.pipeline.get_status(
        ck_info=ck_info,
        targets=[stage],
        check_environments=True,
        clean_notebooks=True,
        compile_to_dvc=True,
    )
    if status.errors:
        raise_error("Pipeline checks failed: " + "; ".join(status.errors))
    if status.failed_environment_checks and not force:
        raise_error(
            "Pipeline environment checks failed for: "
            + ", ".join(status.failed_environment_checks)
            + "; fix them or use --force"
        )
    if status.is_stale and not force:
        raise_error(
            "Out of date: "
            + ", ".join(status.stale_stage_names)
            + "; run pipeline or use --force"
        )
    if output is None:
        stem, ext = os.path.splitext(os.path.basename(path))
        output = f"{stem}.calkit{ext}"
    if os.path.abspath(output) == os.path.abspath(path):
        raise_error("Output would overwrite the original")
    try:
        kit, manifest = calkit.kits.write_copy(
            path,
            output,
            up_to_date=not status.is_stale,
            max_size=None if max_size is None else parse_size(max_size),
            include_data=not no_data,
            ck_info=ck_info,
            allow_uncommitted=force,
        )
    except ValueError as e:
        raise_error(str(e))
    included = [f for f in manifest.files if f.included]
    left_out = [f for f in manifest.files if not f.included]
    kit_size = os.path.getsize(output) - manifest.artifact.size
    typer.echo(
        f"Wrote {output} (calkit: {kit_size / 1e3:.0f} KB, "
        f"{get_n_files_text(len(included))})"
    )
    if left_out:
        typer.echo(
            f"Left out {get_n_files_text(len(left_out))} "
            f"({sum(f.size for f in left_out) / 1e6:.1f} MB); "
            "an expanded copy can pull or remake them"
        )
    if manifest.source.uncommitted_paths:
        warn(
            "Uncommitted changes, so calkit matches no commit and isn't "
            "recorded: " + ", ".join(manifest.source.uncommitted_paths)
        )
    elif not no_record and manifest.source.commit_sha:
        try:
            tag_name = calkit.kits.record(kit, manifest)
        except Exception as e:
            warn(f"Couldn't record calkit: {e}")
        else:
            if "origin" in manifest.source.git_remotes:
                try:
                    calkit.kits.push_record(tag_name)
                except Exception as e:
                    stderr = getattr(e, "stderr", "") or str(e)
                    warn(
                        f"Recorded as tag {tag_name}, but couldn't push it: "
                        + stderr.strip()
                    )
                else:
                    typer.echo(f"Recorded as tag {tag_name}")
            else:
                typer.echo(f"Recorded as tag {tag_name} (no remote)")
    if not manifest.source.git_remotes:
        warn("No Git remote, so history can't be fetched from the calkit")
    if to_clipboard:
        try:
            calkit.kits.copy_to_clipboard(output)
        except Exception as e:
            raise_error(f"Couldn't copy to clipboard: {e}")
        typer.echo(f"Copied {output} to clipboard")


@kit_app.command(name="expand")
def expand(
    path: Annotated[str, typer.Argument(help="Path of a file with a calkit.")],
    dest_dir: Annotated[
        str | None,
        typer.Argument(
            help="Directory for the project; defaults to the project's name."
        ),
    ] = None,
) -> None:
    """Expand the calkit embedded in a file into a project.

    The project holds what makes the file, committed to a new Git repo with
    the original project's remote as 'upstream'.
    """
    import calkit.kits

    if not os.path.isfile(path):
        raise_error(f"{path} doesn't exist")
    if dest_dir is None:
        dest_dir = get_default_dest_dir(path)
    try:
        kit = calkit.kits.expand(path, dest_dir)
    except ValueError as e:
        raise_error(str(e))
    typer.echo(f"Expanded into {dest_dir}")
    if not kit.artifact_unchanged:
        warn(
            f"{kit.manifest.artifact.path} was modified since calkit was "
            "created"
        )
    left_out = [f for f in kit.manifest.files if not f.included]
    if left_out:
        typer.echo(
            f"Left out of calkit: {get_n_files_text(len(left_out))}; "
            "'calkit pull --no-git' fetches them if you have access, "
            "'calkit run' remakes outputs"
        )


@kit_app.command(name="run")
def run(
    path: Annotated[str, typer.Argument(help="Path of a file with a calkit.")],
    dest_dir: Annotated[
        str | None,
        typer.Argument(
            help="Directory for the project; defaults to the project's name."
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes", "-y", help="Run without asking first what it runs."
        ),
    ] = False,
) -> None:
    """Expand the calkit embedded in a file, rerun its pipeline, and check
    the file comes out the same.

    Inputs left out of the calkit are pulled from the original project's
    storage first, which needs access to it. The pipeline is code, so look
    at what it runs before running a calkit from someone you don't trust.
    """
    import hashlib
    import subprocess
    import sys

    import calkit
    import calkit.kits
    import calkit.pipeline
    from calkit.core import is_tty

    if not os.path.isfile(path):
        raise_error(f"{path} doesn't exist")
    if dest_dir is None:
        dest_dir = get_default_dest_dir(path)
    try:
        kit = calkit.kits.expand(path, dest_dir)
    except ValueError as e:
        raise_error(str(e))
    typer.echo(f"Expanded into {dest_dir}")
    if not kit.artifact_unchanged:
        warn(
            f"{kit.manifest.artifact.path} was modified since calkit was "
            "created"
        )
    # The pipeline is someone else's code, so say what it runs before pulling
    # or running anything. Compile from calkit.yaml as 'calkit run' does,
    # rather than trusting dvc.yaml to match it.
    ck_info = (
        calkit.load_calkit_info(wdir=dest_dir)
        if os.path.isfile(os.path.join(dest_dir, "calkit.yaml"))
        else {}
    )
    if (ck_info.get("pipeline") or {}).get("stages"):
        try:
            dvc_stages = calkit.pipeline.to_dvc(
                ck_info=ck_info,
                wdir=dest_dir,
                write=False,
                manage_gitignore=False,
            )
        except Exception as e:
            raise_error(f"Can't read calkit's pipeline: {e}")
    elif os.path.isfile(os.path.join(dest_dir, "dvc.yaml")):
        with open(os.path.join(dest_dir, "dvc.yaml")) as f:
            dvc_stages = (calkit.ryaml.load(f) or {}).get("stages") or {}
    else:
        raise_error("Calkit has no pipeline to run")
    envs = ck_info.get("environments") or {}
    if envs:
        typer.echo("Environments: " + ", ".join(envs))
    typer.echo("Stages to run:")
    for name, stage in dvc_stages.items():
        cmd = stage.get("cmd") or (stage.get("do") or {}).get("cmd")
        typer.echo(f"  {name}: {cmd}")
    missing = calkit.kits.get_missing_inputs(kit, dest_dir)
    if missing:
        typer.echo(
            f"Inputs to pull ({get_n_files_text(len(missing))}): "
            + ", ".join(missing)
        )
    if not yes:
        if not is_tty():
            raise_error("Rerun with --yes to run these")
        if not typer.confirm("Run them?", default=False):
            raise typer.Exit(1)
    # Rerunning needs every input that no stage makes
    if missing:
        typer.echo(f"Pulling {get_n_files_text(len(missing))} left out")
        subprocess.run(
            [sys.executable, "-m", "calkit", "pull", "--no-git"],
            cwd=dest_dir,
            check=False,
        )
        missing = calkit.kits.get_missing_inputs(kit, dest_dir)
        if missing:
            raise_error(
                "Missing inputs: "
                + ", ".join(missing)
                + "; pull them, or create calkit with a larger --max-size"
            )
    typer.echo("Rerunning pipeline")
    res = subprocess.run(
        [sys.executable, "-m", "calkit", "run", "--force"], cwd=dest_dir
    )
    if res.returncode != 0:
        raise_error("Pipeline failed")
    artifact_path = os.path.join(dest_dir, kit.manifest.artifact.path)
    with open(artifact_path, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()
    expected_sha256 = hashlib.sha256(kit.artifact).hexdigest()
    if sha256 != expected_sha256 or sha256 != kit.manifest.artifact.sha256:
        raise_error(
            f"Reran, but {kit.manifest.artifact.path} differs from the "
            "shared file"
        )
    typer.echo(f"Reproduced {kit.manifest.artifact.path}: identical")


@kit_app.command(name="open")
def open_(
    path: Annotated[str, typer.Argument(help="Path of a file with a calkit.")],
    dest_dir: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Directory to expand it into, if it isn't already; defaults "
                "to the project's name."
            )
        ),
    ] = None,
    hub: Annotated[
        bool,
        typer.Option(
            "--hub",
            help="Open its project on the hub, at the commit it came from.",
        ),
    ] = False,
    with_editor: Annotated[
        str | None,
        typer.Option(
            "--with",
            "-w",
            help="Editor to open it with instead of the default.",
        ),
    ] = None,
) -> None:
    """Open the project a file's calkit came from.

    Expands the calkit, unless that's been done already, and opens it in
    the default editor, or with '--hub', opens the original project on the
    hub at the commit the calkit came from.
    """
    import calkit.kits
    from calkit.cli.open_ import open_project

    if not os.path.isfile(path):
        raise_error(f"{path} doesn't exist")
    try:
        kit = calkit.kits.read(path)
    except ValueError as e:
        raise_error(f"Can't read calkit: {e}")
    if kit is None:
        raise_error(f"{path} has no calkit")
    if hub:
        url = calkit.kits.get_hub_file_url(kit.manifest)
        if url is None:
            raise_error("Calkit names no hub project")
        typer.echo(f"Opening {url}")
        typer.launch(url)
        return
    if dest_dir is None:
        dest_dir = get_default_dest_dir(path)
    if not os.path.isfile(os.path.join(dest_dir, "calkit.yaml")):
        try:
            calkit.kits.expand(path, dest_dir)
        except ValueError as e:
            raise_error(str(e))
        typer.echo(f"Expanded into {dest_dir}")
    open_project(
        project=os.path.basename(os.path.abspath(dest_dir)),
        file_path=kit.manifest.artifact.path,
        checkout=dest_dir,
        with_editor=with_editor,
        yes=False,
        hub=None,
    )


@kit_app.command(name="list")
def list_(
    as_json: Annotated[
        bool, typer.Option("--json", help="Print as JSON.")
    ] = False,
) -> None:
    """List the calkits created from this project, newest first.

    Read from the tags 'calkit kit create' records, so fetch tags first,
    e.g., with 'git fetch --tags', to see those others created.
    """
    import calkit.kits
    from calkit.cli import echo_json

    records = calkit.kits.get_records()
    if as_json:
        echo_json(records)
        return
    if not records:
        typer.echo("No calkits recorded")
        return
    for r in records:
        created = str(r.get("created", ""))[:10]
        commit = str(r.get("commit_sha", ""))[:7]
        stale = "" if r.get("up_to_date", True) else " (out of date)"
        typer.echo(
            f"{created}  {r.get('artifact_path')} at {commit}{stale}  "
            f"{r['name']}"
        )
