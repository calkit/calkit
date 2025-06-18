"""CLI for working with Overleaf."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import PurePosixPath

import git
import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import raise_error, warn

overleaf_app = typer.Typer(no_args_is_help=True)


@overleaf_app.command(name="import")
def import_publication(
    src_url: Annotated[
        str,
        typer.Argument(
            help=(
                "Overleaf project URL, e.g., "
                "https://www.overleaf.com/project/6800005973cb2e35."
            )
        ),
    ],
    dest_dir: Annotated[
        str,
        typer.Argument(
            help="Directory at which to save in the project, e.g., 'paper'."
        ),
    ],
    sync_paths: Annotated[
        list[str],
        typer.Option(
            "--sync-path",
            "-s",
            help=(
                "Paths to sync from the Overleaf project, e.g., 'main.tex'. "
                "Note that multiple can be specified."
            ),
        ),
    ],
    title: Annotated[
        str,
        typer.Option(
            "--title",
            "-t",
            help="Title of the publication.",
        ),
    ],
    description: Annotated[
        str | None,
        typer.Option(
            "--description",
            "-d",
            help="Description of the publication.",
        ),
    ] = None,
    kind: Annotated[
        str | None,
        typer.Option(
            "--kind",
            help="What of the publication this is, e.g., 'journal-article'.",
        ),
    ] = None,
    push_paths: Annotated[
        list[str],
        typer.Option(
            "--push-path",
            "-p",
            help=(
                "Paths to push to the Overleaf project, e.g., 'figures'. "
                "Note that these are relative to the publication working "
                "directory."
            ),
        ),
    ] = [],
    pdf_path: Annotated[
        str | None,
        typer.Option(
            "--pdf-path",
            "-o",
            help=(
                "PDF output file in the Overleaf project, e.g., 'main.pdf'. "
                "If not provided, it will be determined from the first sync "
                "path."
            ),
        ),
    ] = None,
    no_commit: Annotated[
        bool,
        typer.Option("--no-commit", help="Do not commit changes to repo."),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Force adding the publication even if it already exists.",
        ),
    ] = False,
):
    """Import a publication from an Overleaf project."""
    from calkit.cli.main import ignore as git_ignore
    from calkit.cli.new import new_latex_stage

    # First check that the user has an Overleaf token set
    config = calkit.config.read()
    overleaf_token = config.overleaf_token
    if not overleaf_token:
        warn("Overleaf token not set in config", prefix="")
        typer.echo(
            "One can be generated at:\n\n"
            "    https://www.overleaf.com/user/settings\n\n"
            "under the 'Git Integration' section.\n"
        )
        overleaf_token = typer.prompt(
            "Enter Overleaf Git authentication token", hide_input=True
        )
        typer.echo("Storing Overleaf token in Calkit config")
        config.overleaf_token = overleaf_token
        config.write()
    if not src_url.startswith("https://www.overleaf.com/project/"):
        raise_error(
            "Invalid URL; must start with 'https://www.overleaf.com/project/'"
        )
    overleaf_project_id = src_url.split("/")[-1]
    if not overleaf_project_id:
        raise_error("Invalid Overleaf project ID")
    ck_info = calkit.load_calkit_info(process_includes="environments")
    pubs = ck_info.get("publications", [])
    # TODO: Don't allow the same Overleaf project ID in multiple publications
    # Determine the PDF output path
    if pdf_path is None:
        # Use the first sync path as the PDF path
        pdf_path = sync_paths[0].removesuffix(".tex") + ".pdf"
        typer.echo(f"Using PDF path: {pdf_path}")
    tex_path = pdf_path.removesuffix(".pdf") + ".tex"
    pub_path = PurePosixPath(dest_dir, pdf_path).as_posix()
    pub_paths = [pub.get("path") for pub in pubs]
    if not overwrite and pub_path in pub_paths:
        raise_error(
            f"A publication already exists in this project at {pub_path}"
        )
    elif overwrite and pub_path in pub_paths:
        # Note: This publication will go to the end of the list
        pubs = [p for p in pubs if p.get("path") != pub_path]
    repo = git.Repo()
    # Clone the Overleaf project into .calkit/overleaf if it doesn't exist
    # otherwise pull
    overleaf_dir = os.path.join(".calkit", "overleaf")
    os.makedirs(overleaf_dir, exist_ok=True)
    git_ignore(overleaf_dir, no_commit=no_commit)
    overleaf_project_dir = os.path.join(overleaf_dir, overleaf_project_id)
    git_clone_url = (
        f"https://git:{overleaf_token}@git.overleaf.com/{overleaf_project_id}"
    )
    if os.path.isdir(overleaf_project_dir):
        warn("This Overleaf project has already been cloned; removing")
        shutil.rmtree(overleaf_project_dir)
    # Clone the Overleaf project
    typer.echo("Cloning Overleaf project")
    git.Repo.clone_from(
        git_clone_url,
        overleaf_project_dir,
        depth=1,
    )
    # Check that we have a LaTeX environment
    typer.echo("Checking that this project has a LaTeX environment")
    envs = ck_info.get("environments", {})
    tex_env_name = None
    for name, env in envs.items():
        if env.get("kind") == "docker" and "texlive" in env.get("image", ""):
            tex_env_name = name
            break
    if tex_env_name is None:
        typer.echo("Creating TeXlive Docker environment")
        tex_env_name = "tex"
        n = 1
        while tex_env_name in envs:
            tex_env_name = f"tex-{n}"
            n += 1
        envs[tex_env_name] = dict(
            kind="docker",
            image="texlive/texlive:latest-full",
            description="TeXlive via Docker.",
        )
        ck_info["environments"] = envs
    # Check that we have a build stage
    # TODO: Use Calkit pipeline for this
    typer.echo("Checking for a build stage in the pipeline")
    stage_name = None
    if os.path.isfile("dvc.yaml"):
        with open("dvc.yaml", "r") as f:
            dvc_info = calkit.ryaml.load(f)
        stages = dvc_info.get("stages", {})
        for stage_name_i, stage in stages.items():
            if pub_path in stage.get("outs", []):
                stage_name = stage_name_i
                typer.echo(f"Found build stage '{stage_name}' in pipeline")
                break
    else:
        stages = {}
    if stage_name is None:
        # Create a new stage
        stage_name = calkit.to_kebab_case("build-" + dest_dir)
        n = 1
        while stage_name in stages:
            stage_name = f"{stage_name}-{n}"
            n += 1
        typer.echo(f"Creating build stage '{stage_name}'")
        new_latex_stage(
            name=stage_name,
            environment=tex_env_name,
            target_path=PurePosixPath(dest_dir, tex_path).as_posix(),
            outputs=[pub_path],
            inputs=[
                os.path.join(dest_dir, p) for p in sync_paths + push_paths
            ],
            no_check=True,
            no_commit=True,
        )
        repo.git.add("calkit.yaml")
    # Add to publications in calkit.yaml
    typer.echo("Adding publication to calkit.yaml")
    new_pub = dict(
        path=pub_path,
        title=title,
        description=description,
        kind=kind,
        stage=stage_name,
        overleaf=dict(
            project_id=overleaf_project_id,
            wdir=dest_dir,
            sync_paths=sync_paths,
            push_paths=push_paths,
            last_sync_commit=None,
        ),
    )
    pubs.append(new_pub)
    ck_info["publications"] = pubs
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    if not no_commit:
        # Commit any necessary changes
        typer.echo("Committing changes")
        repo.git.commit(
            ["-m", f"Import Overleaf project ID {overleaf_project_id}"]
        )
    # Sync the project
    sync(paths=[pub_path], no_commit=no_commit)


@overleaf_app.command(name="sync")
def sync(
    paths: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Paths to sync with Overleaf, e.g., 'paper/paper.pdf'. "
                "If not provided, all Overleaf publications will be synced."
            ),
        ),
    ] = None,
    no_commit: Annotated[
        bool,
        typer.Option(
            "--no-commit",
            help="Do not commit the changes.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Enable verbose output.",
        ),
    ] = False,
):
    """Sync publications with Overleaf."""
    # TODO: We should probably ensure the pipeline isn't stale
    # Find all publications with Overleaf projects linked
    ck_info = calkit.load_calkit_info()
    pubs = ck_info.get("publications", [])
    if paths is not None:
        for path in paths:
            if not any(pub.get("path") == path for pub in pubs):
                raise_error(f"Publication with path '{path}' not found")
    repo = git.Repo()
    for pub in pubs:
        overleaf_config = pub.get("overleaf", {})
        if not overleaf_config:
            continue
        if paths is not None and pub.get("path") not in paths:
            continue
        overleaf_project_id = overleaf_config.get("project_id")
        if not overleaf_project_id:
            raise_error(
                "No Overleaf project ID defined for this publication; "
                "please set it in the publication's Overleaf config"
            )
        typer.echo(
            f"Syncing {pub['path']} with "
            f"Overleaf project ID {overleaf_project_id}"
        )
        wdir = pub["overleaf"].get("wdir")
        if wdir is None:
            raise_error(
                "No working directory defined for this publication; "
                "please set it in the publication's Overleaf config"
            )
        # Ensure we've cloned the Overleaf project
        overleaf_project_dir = os.path.join(
            ".calkit", "overleaf", overleaf_project_id
        )
        if not os.path.isdir(overleaf_project_dir):
            calkit_config = calkit.config.read()
            overleaf_token = calkit_config.overleaf_token
            if not overleaf_token:
                raise_error(
                    "Overleaf token not set; "
                    "Please set it using 'calkit config set overleaf_token'"
                )
            overleaf_clone_url = (
                f"https://git:{overleaf_token}@git.overleaf.com/"
                f"{overleaf_project_id}"
            )
            overleaf_repo = git.Repo.clone_from(
                overleaf_clone_url, to_path=overleaf_project_dir
            )
        else:
            overleaf_repo = git.Repo(overleaf_project_dir)
        # Pull the latest version in the Overleaf project
        typer.echo("Pulling the latest version from Overleaf")
        overleaf_repo.git.pull()
        last_sync_commit = pub["overleaf"].get("last_sync_commit")
        # Determine which paths to sync and push
        # TODO: Support glob patterns
        sync_paths = pub["overleaf"].get("sync_paths", [])
        push_paths = pub["overleaf"].get("push_paths", [])
        sync_paths_in_project = [os.path.join(wdir, p) for p in sync_paths]
        if not sync_paths:
            warn("No sync paths defined in the publication's Overleaf config")
        elif last_sync_commit:
            # Compute a diff in the Overleaf project between HEAD and the last
            # sync
            diff = overleaf_repo.git.diff(
                [last_sync_commit, "HEAD", "--"] + sync_paths
            )
            # Ensure the diff ends with a new line
            if diff and not diff.endswith("\n"):
                diff += "\n"
            if verbose:
                typer.echo(f"Git diff:\n{diff}")
            if diff:
                typer.echo("Applying to project repo")
                process = subprocess.run(
                    ["git", "apply", "--directory", wdir, "-"],
                    input=diff,
                    text=True,
                )
                if process.returncode != 0:
                    raise_error("Failed to apply diff")
            else:
                typer.echo("No changes to apply")
        else:
            # Simply copy in all files
            typer.echo(
                "No last sync commit defined; "
                "copying all files from Overleaf project"
            )
            for sync_path in sync_paths:
                src = os.path.join(overleaf_project_dir, sync_path)
                dst = os.path.join(wdir, sync_path)
                if os.path.isdir(src):
                    # Copy the directory and its contents
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                elif os.path.isfile(src):
                    # Copy the file
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                else:
                    raise_error(
                        f"Source path {src} does not exist; "
                        "please check your Overleaf config"
                    )
        # Copy our versions of sync and push paths into the Overleaf project
        for sync_push_path in sync_paths + push_paths:
            src = os.path.join(wdir, sync_push_path)
            dst = os.path.join(overleaf_project_dir, sync_push_path)
            if os.path.isdir(src):
                # Remove destination directory if it exists
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                # Copy the directory and its contents
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(src):
                # Copy the file
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            else:
                raise_error(
                    f"Source path {src} does not exist; "
                    "please check your Overleaf config"
                )
                continue
        # Stage the changes in the Overleaf project
        overleaf_repo.git.add(sync_paths + push_paths)
        if (
            overleaf_repo.git.diff("--staged", sync_paths + push_paths)
            and not no_commit
        ):
            commit_message = "Sync with Calkit project"
            overleaf_repo.git.commit(
                *(sync_paths + push_paths),
                "-m",
                commit_message,
            )
            # TODO: We should probably always push and pull to we can
            # idempotently run this command
            typer.echo("Pushing changes to Overleaf")
            overleaf_repo.git.push()
        # Update the last sync commit
        last_overleaf_commit = overleaf_repo.head.commit.hexsha
        typer.echo(f"Updating last sync commit as {last_overleaf_commit}")
        pub["overleaf"]["last_sync_commit"] = last_overleaf_commit
        # Write publications back to calkit.yaml
        ck_info["publications"] = pubs
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        repo.git.add("calkit.yaml")
        # Stage the changes in the project repo
        repo.git.add(sync_paths_in_project)
        if (
            repo.git.diff("--staged", sync_paths_in_project + ["calkit.yaml"])
            and not no_commit
        ):
            typer.echo("Committing changes to project repo")
            commit_message = f"Sync {wdir} with Overleaf project"
            repo.git.commit(
                *(sync_paths_in_project + ["calkit.yaml"]),
                "-m",
                commit_message,
            )
    # Push to the project remote
    typer.echo("Pushing changes to project Git remote")
    repo.git.push()
    # TODO: Add option to run the pipeline after?
