"""CLI for working with Overleaf."""

from __future__ import annotations

import filecmp
import json
import os
import shutil
from pathlib import Path

import git
import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import raise_error, warn

overleaf_app = typer.Typer(no_args_is_help=True)


def _extract_title_from_tex(tex_file_path: str) -> str | None:
    """Extract the title from a LaTeX file."""
    from TexSoup import TexSoup

    try:
        with open(tex_file_path) as f:
            overleaf_target_text = f.read()
        texsoup = TexSoup(overleaf_target_text)
        return str(texsoup.title.string) if texsoup.title else None
    except Exception:
        return None


def _get_overleaf_token() -> str:
    """Get the user's Overleaf token from config.

    If not set, we'll try to get from the cloud. If that fails, we'll prompt
    the user to enter it.

    TODO: Handle expiration?
    """
    calkit_config = calkit.config.read()
    overleaf_token = calkit_config.overleaf_token
    if not overleaf_token:
        # See if we can get it from the cloud
        if calkit_config.token is not None:
            try:
                typer.echo("Getting Overleaf token from cloud")
                resp = calkit.cloud.get("/user/overleaf-token")
                overleaf_token = resp["access_token"]
                calkit_config.overleaf_token = overleaf_token
                calkit_config.write()
            except Exception:
                typer.echo("Failed to get Overleaf token from cloud")
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
        calkit_config.overleaf_token = overleaf_token
        calkit_config.write()
    if not overleaf_token:
        raise_error(
            "Overleaf token not set in config; "
            "Please set it using 'calkit config set overleaf_token'"
        )
    return overleaf_token


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
    title: Annotated[
        str | None,
        typer.Option(
            "--title",
            "-t",
            help="Title of the publication.",
        ),
    ] = None,
    target_path: Annotated[
        str | None,
        typer.Option(
            "--target",
            "-T",
            help="Target TeX file path inside Overleaf project.",
        ),
    ] = None,
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
    ] = [],
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
    push_only: Annotated[
        bool,
        typer.Option(
            "--push-only",
            "-P",
            help=(
                "Push local files to Overleaf without pulling. "
                "Useful when initializing a new Overleaf project from local "
                "files."
            ),
        ),
    ] = False,
):
    """Import a publication from an Overleaf project."""
    from calkit.cli.new import new_latex_stage

    # First check that the user has an Overleaf token set
    overleaf_token = _get_overleaf_token()
    if (
        not src_url.startswith("https://www.overleaf.com/project/")
        and calkit.config.get_env() != "test"
    ):
        raise_error(
            "Invalid URL; must start with 'https://www.overleaf.com/project/'"
        )
    overleaf_project_id = calkit.overleaf.project_id_from_url(src_url)
    if not overleaf_project_id:
        raise_error("Invalid Overleaf project ID")
    # Check target path
    if target_path is not None and not target_path.endswith(".tex"):
        raise_error("Target path should have a .tex extension")
    # Make sure destination directory exists, and isn't a file
    if os.path.isfile(dest_dir):
        raise_error("Destination must be a directory, not a file")
    os.makedirs(dest_dir, exist_ok=True)
    ck_info = calkit.load_calkit_info(process_includes="environments")
    pubs = ck_info.get("publications", [])
    # TODO: Don't allow the same Overleaf project ID in multiple publications
    repo = git.Repo()
    # Clone the Overleaf project into .calkit/overleaf if it doesn't exist
    # otherwise pull
    overleaf_dir = os.path.join(".calkit", "overleaf")
    os.makedirs(overleaf_dir, exist_ok=True)
    # Write .gitignore in overleaf folder to ignore all contents
    gitignore_path = os.path.join(overleaf_dir, ".gitignore")
    with open(gitignore_path, "w") as f:
        f.write("*\n")
    overleaf_project_dir = os.path.join(overleaf_dir, overleaf_project_id)
    git_clone_url = calkit.overleaf.get_git_remote_url(
        project_id=overleaf_project_id, token=overleaf_token
    )
    if os.path.isdir(overleaf_project_dir):
        warn("This Overleaf project has already been cloned; removing")
        shutil.rmtree(overleaf_project_dir)
    # Clone the Overleaf project
    typer.echo("Cloning Overleaf project")
    git.Repo.clone_from(git_clone_url, overleaf_project_dir)
    # Detect target path if not specified
    if target_path is None:
        ol_contents = os.listdir(
            dest_dir if push_only else overleaf_project_dir
        )
        for cand in ["main.tex", "report.tex", "paper.tex"]:
            if cand in ol_contents:
                target_path = cand
                break
    if target_path is None:
        # Fall back to lone .tex file if there is one
        tex_files = [p for p in ol_contents if p.endswith(".tex")]
        if len(tex_files) == 1:
            target_path = tex_files[0]
    if target_path is None:
        raise_error(
            "Target TeX file path cannot be detected; "
            "please specify with --target"
        )
        return
    # Try to extract title from the target LaTeX file if not provided
    if not title:
        target_tex_path = os.path.join(
            dest_dir if push_only else overleaf_project_dir, target_path
        )
        extracted_title = _extract_title_from_tex(target_tex_path)
        if extracted_title:
            typer.echo(f"Detected title: {extracted_title}")
            title = extracted_title
    if not title:
        raise_error(
            "Title could not be detected from the LaTeX file; "
            "please specify with --title"
        )
    # Determine the PDF output path
    pdf_path = target_path.removesuffix(".tex") + ".pdf"  # type: ignore
    typer.echo(f"Using PDF path: {pdf_path}")
    tex_path = pdf_path.removesuffix(".pdf") + ".tex"
    target_tex_path = Path(dest_dir, tex_path).as_posix()
    pub_path = Path(dest_dir, pdf_path).as_posix()
    pub_paths = [pub.get("path") for pub in pubs]
    if not overwrite and pub_path in pub_paths:
        raise_error(
            f"A publication already exists in this project at {pub_path}"
        )
    elif overwrite and pub_path in pub_paths:
        # Note: This publication will go to the end of the list
        pubs = [p for p in pubs if p.get("path") != pub_path]
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
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
    # Check that we have a build stage
    typer.echo("Checking for a build stage in the pipeline")
    pipeline = ck_info.get("pipeline", {})
    stages = pipeline.get("stages", {})
    stage_name = None
    for stage_name_i, stage in stages.items():
        if (
            stage.get("kind") == "latex"
            and stage.get("target_path") == target_tex_path
        ):
            stage_name = stage_name_i
            typer.echo(f"Found build stage '{stage_name}' in pipeline")
            break
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
            target_path=target_tex_path,
            inputs=[
                os.path.join(dest_dir, p) for p in sync_paths + push_paths
            ],
            no_check=True,
            no_commit=True,
        )
        repo.git.add("calkit.yaml")
    # Add to publications in calkit.yaml
    typer.echo("Adding publication to calkit.yaml")
    ck_info = calkit.load_calkit_info()
    new_pub = dict(
        path=pub_path,
        title=title,
        description=description,
        kind=kind,
        stage=stage_name,
    )
    pubs.append(new_pub)
    ck_info["publications"] = pubs
    ol_sync = ck_info.get("overleaf_sync", {})
    if dest_dir in ol_sync:
        raise_error(f"'{dest_dir}' is already synced with Overleaf")
    ol_sync[dest_dir] = dict(url=src_url)
    if sync_paths:
        ol_sync[dest_dir]["sync_paths"] = sync_paths
    if push_paths:
        ol_sync[dest_dir]["push_paths"] = push_paths
    ck_info["overleaf_sync"] = ol_sync
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    if not no_commit and repo.git.diff(["--staged", "--", "calkit.yaml"]):
        # Commit any necessary changes
        typer.echo("Committing changes")
        repo.git.commit(
            [
                "calkit.yaml",
                "-m",
                f"Import Overleaf project ID {overleaf_project_id}",
            ]
        )
    # Sync the project
    sync(paths=[dest_dir], no_commit=no_commit, push_only=push_only)


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
            help=(
                "Do not commit the changes to the project repo. "
                "Changes will always be committed to Overleaf."
            ),
        ),
    ] = False,
    auto_commit: Annotated[
        bool,
        typer.Option(
            "--auto-commit",
            help=(
                "Automatically commit changes to the project repo if a synced "
                "folder has changes."
            ),
        ),
    ] = False,
    no_push: Annotated[
        bool,
        typer.Option(
            "--no-push",
            help=(
                "Do not push the changes to the main project remote. "
                "Changes will always be pushed to Overleaf."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Enable verbose output.",
        ),
    ] = False,
    resolve: Annotated[
        bool,
        typer.Option(
            "--resolve",
            "-r",
            help="Mark merge conflicts as resolved before committing.",
        ),
    ] = False,
    push_only: Annotated[
        bool,
        typer.Option(
            "--push-only",
            "-P",
            help=(
                "Only push local files to Overleaf without pulling from "
                "Overleaf. "
                "Useful when initializing a new Overleaf project from local "
                "files."
            ),
        ),
    ] = False,
):
    """Sync folders with Overleaf."""
    # TODO: We should probably ensure the pipeline isn't stale
    # Read all synced folders, fixing legacy schema if applicable
    overleaf_info = calkit.overleaf.get_sync_info(fix_legacy=True)
    if not overleaf_info:
        raise_error("No Overleaf sync info found")
    overleaf_sync_dirs = list(overleaf_info.keys())
    if paths is not None:
        paths = [os.path.dirname(p) if os.path.isfile(p) else p for p in paths]
        for path in paths:
            if path not in overleaf_sync_dirs:
                raise_error(f"Path '{path}' is not synced with Overleaf")
    # First check our config for an Overleaf token
    overleaf_token = _get_overleaf_token()
    repo = git.Repo()
    conflict_fpath = calkit.overleaf.get_conflict_fpath()
    in_am_session = "in the middle of an am session" in repo.git.status()
    # Check if we're in the middle of resolving a merge conflict
    if in_am_session and not resolve:
        raise_error(
            "You are in the middle of resolving a merge conflict; "
            "use 'calkit overleaf sync --resolve' after editing file(s)"
        )
    elif resolve:
        if not os.path.isfile(conflict_fpath):
            raise_error("No merge conflict to resolve")
        # Figure out which wdir has the conflict in it
        with open(conflict_fpath) as f:
            resolving_info = json.load(f)
    for synced_folder, sync_data in overleaf_info.items():
        if not sync_data:
            continue
        if paths is not None and synced_folder not in paths:
            continue
        overleaf_project_id = sync_data.get("project_id")
        if not overleaf_project_id:
            raise_error(
                "No Overleaf project ID defined for this folder; "
                "please set 'url' in the Overleaf config"
            )
        typer.echo(
            f"Syncing {synced_folder} with "
            f"Overleaf project ID {overleaf_project_id}"
        )
        wdir = synced_folder
        if resolve and wdir == resolving_info["wdir"]:
            repo.git.add(wdir)
            if repo.git.diff(["--staged", wdir]):
                repo.git.commit(
                    [wdir, "-m", f"Resolve Overleaf merge conflict in {wdir}"]
                )
            if in_am_session:
                repo.git.am("--skip")
        elif resolve:
            continue
        # If there are any uncommitted changes in the publication working
        # directory, raise an error unless auto-commit is specified
        if repo.git.diff(wdir) or repo.index.diff("HEAD", wdir):
            if auto_commit:
                repo.git.add(wdir)
                repo.git.commit(
                    [wdir, "-m", f"Save {wdir} before syncing with Overleaf"]
                )
            else:
                raise_error(
                    f"Uncommitted changes found in {wdir}; "
                    "please commit or stash them before syncing with Overleaf"
                )
        # Ensure we've cloned the Overleaf project
        overleaf_project_dir = os.path.join(
            ".calkit", "overleaf", overleaf_project_id
        )
        overleaf_remote_url = calkit.overleaf.get_git_remote_url(
            project_id=overleaf_project_id, token=str(overleaf_token)
        )
        if not os.path.isdir(overleaf_project_dir):
            overleaf_repo = git.Repo.clone_from(
                overleaf_remote_url, to_path=overleaf_project_dir
            )
        else:
            overleaf_repo = git.Repo(overleaf_project_dir)
        # Pull the latest version in the Overleaf project
        typer.echo("Pulling the latest version from Overleaf")
        # Ensure that our current Overleaf remote URL is correct
        overleaf_repo.git.remote("set-url", "origin", overleaf_remote_url)
        try:
            overleaf_repo.git.pull()
        except Exception:
            raise_error(
                "Failed to pull from Overleaf; "
                "check that your Overleaf token is valid\n"
                "Run 'calkit config get overleaf_token' and ensure that "
                "it matches one in your Overleaf account settings "
                "(https://overleaf.com/user/settings)"
            )
        if resolve:
            last_sync_commit = resolving_info["last_overleaf_commit"]
        else:
            last_sync_commit = sync_data.get("last_sync_commit")
        commits_since = calkit.overleaf.get_commits_since_last_sync(
            overleaf_repo=overleaf_repo,
            last_sync_commit=last_sync_commit,
        )
        if commits_since:
            typer.echo(
                f"There have been {len(commits_since)} changes on "
                "Overleaf since last sync"
            )
        try:
            res = calkit.overleaf.sync(
                main_repo=repo,
                overleaf_repo=overleaf_repo,
                path_in_project=synced_folder,
                sync_info_for_path=sync_data,
                last_sync_commit=last_sync_commit,
                no_commit=no_commit,
                verbose=verbose,
                resolving_conflict=resolve,
                print_info=typer.echo,
                push_only=push_only,
            )
        except Exception as e:
            raise_error(str(e))
    if not no_push and not no_commit:
        if not repo.remotes:
            raise_error("Project has no Git remotes defined")
        if res.get("committed_project", True):
            # Push to the project remote
            typer.echo("Pushing changes to project Git remote")
            repo.git.push()
    # TODO: Add option to run the pipeline after?


def compare_folders_recursively(
    dir1: str, dir2: str, paths: list[str], dirname: str = ""
) -> dict[str, list[str]]:
    """Compare two directories recursively."""
    res = {
        "left_only": [],
        "right_only": [],
        "diff_files": [],
        "same_files": [],
    }
    dcmp = filecmp.dircmp(dir1, dir2)
    for category in ["left_only", "right_only", "diff_files", "same_files"]:
        items = getattr(dcmp, category)
        for item in items:
            relpath = os.path.join(dirname, item)
            if relpath in paths:
                res[category].append(relpath)
    # Recursively compare subdirectories
    for subdir_name, sub_dcmp in dcmp.subdirs.items():
        subdir_res = compare_folders_recursively(
            sub_dcmp.left, sub_dcmp.right, paths=paths, dirname=subdir_name
        )
        for k in res.keys():
            res[k] += subdir_res[k]
    return res


@overleaf_app.command(name="status")
def get_status(
    paths: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Paths synced with Overleaf, e.g., 'paper'. "
                "If not provided, all Overleaf syncs will be checked."
            ),
        ),
    ] = None,
):
    """Check the status of folders synced with Overleaf in a project."""
    # Read all synced folders, fixing legacy schema if applicable
    overleaf_info = calkit.overleaf.get_sync_info(fix_legacy=False)
    if not overleaf_info:
        raise_error("No Overleaf sync info found")
    overleaf_sync_dirs = list(overleaf_info.keys())
    if paths is not None:
        paths = [os.path.dirname(p) if os.path.isfile(p) else p for p in paths]
        for path in paths:
            if path not in overleaf_sync_dirs:
                raise_error(f"Path '{path}' is not synced with Overleaf")
    # First check our config for an Overleaf token
    overleaf_token = _get_overleaf_token()
    for path_in_project, sync_data in overleaf_info.items():
        if paths is not None and path_in_project not in paths:
            continue
        overleaf_project_id = sync_data.get("project_id")
        if not overleaf_project_id:
            raise_error(
                "No Overleaf project ID defined for this folder; "
                "please set it in the project's Overleaf config"
            )
        typer.echo(
            f"Getting status of {path_in_project} with "
            f"Overleaf project ID {overleaf_project_id}"
        )
        wdir = path_in_project
        # Ensure we've cloned the Overleaf project
        overleaf_project_dir = os.path.join(
            ".calkit", "overleaf", overleaf_project_id
        )
        overleaf_remote_url = calkit.overleaf.get_git_remote_url(
            project_id=overleaf_project_id, token=str(overleaf_token)
        )
        if not os.path.isdir(overleaf_project_dir):
            overleaf_repo = git.Repo.clone_from(
                overleaf_remote_url, to_path=overleaf_project_dir
            )
        else:
            overleaf_repo = git.Repo(overleaf_project_dir)
        # Pull the latest version in the Overleaf project
        typer.echo("Pulling the latest version from Overleaf")
        # Ensure that our current Overleaf remote URL is correct
        overleaf_repo.git.remote("set-url", "origin", overleaf_remote_url)
        try:
            overleaf_repo.git.pull()
        except Exception:
            raise_error(
                "Failed to pull from Overleaf; "
                "check that your Overleaf token is valid\n"
                "Run 'calkit config get overleaf_token' and ensure that "
                "it matches one in your Overleaf account settings "
                "(https://overleaf.com/user/settings)"
            )
        last_sync_commit = sync_data.get("last_sync_commit")
        if last_sync_commit:
            commits_since = calkit.overleaf.get_commits_since_last_sync(
                overleaf_repo=overleaf_repo,
                last_sync_commit=last_sync_commit,
            )
            typer.echo(
                f"There have been {len(commits_since)} changes on "
                "Overleaf since last sync"
            )
        # Determine which paths to use for computing diff
        path_info = calkit.overleaf.OverleafSyncPaths(
            main_repo=git.Repo(),
            overleaf_repo=overleaf_repo,
            path_in_project=path_in_project,
            sync_info_for_path=sync_data,
        )
        status = compare_folders_recursively(
            wdir,
            overleaf_project_dir,
            paths=path_info.all_synced_files,
        )

        def print_path(p, fg_color=None):
            txt = f"    {os.path.join(wdir, p)}"
            typer.echo(typer.style(txt, fg=fg_color))

        if status["left_only"]:
            typer.echo("Files only in Calkit project:")
            for p in status["left_only"]:
                print_path(p, "green")
        if status["right_only"]:
            typer.echo("Files only in Overleaf project:")
            for p in status["right_only"]:
                print_path(p, "yellow")
        if status["diff_files"]:
            typer.echo("Changed files:")
            for p in status["diff_files"]:
                print_path(p, "red")

