"""CLI for importing objects."""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from copy import deepcopy
from typing import Annotated

import git
import requests
import typer
from tqdm import tqdm

import calkit
from calkit.cli import raise_error

import_app = typer.Typer(no_args_is_help=True)


@import_app.command(name="dataset")
def import_dataset(
    src_path: Annotated[
        str,
        typer.Argument(
            help=(
                "Location of dataset, including project owner and name, e.g., "
                "someone/some-project/data/some-data.csv"
            )
        ),
    ],
    dest_path: Annotated[
        str,
        typer.Argument(help="Output path at which to save."),
    ] = None,
    filter_paths: Annotated[
        list[str],
        typer.Option(
            "--filter-paths",
            help="Filter paths in target dataset if it's a folder.",
        ),
    ] = None,
    no_commit: Annotated[
        bool,
        typer.Option("--no-commit", help="Do not commit changes to repo."),
    ] = False,
    no_dvc_pull: Annotated[
        bool,
        typer.Option(
            "--no-dvc-pull", help="Do not pull imported dataset with DVC."
        ),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Force adding the dataset even if it already exists.",
        ),
    ] = False,
):
    """Import a dataset.

    Currently only supports datasets kept in DVC, not Git.
    """
    # Ensure we don't already have a dataset at this path
    path_split = src_path.split("/")
    owner_name = path_split[0]
    project_name = path_split[1]
    path = "/".join(path_split[2:])
    if dest_path is None:
        ds_dest_path = path
    else:
        ds_dest_path = dest_path
    ck_info = calkit.load_calkit_info()
    datasets = ck_info.get("datasets", [])
    ds_paths = [ds["path"] for ds in datasets]
    if not overwrite and ds_dest_path in ds_paths:
        raise_error("A dataset already exists in this project at this path")
    elif overwrite and ds_dest_path in ds_paths:
        datasets = [ds for ds in datasets if ds["path"] != ds_dest_path]
    repo = git.Repo()
    # Obtain, save, and commit the .dvc file for the dataset, or if this is
    # kept in Git, just download the files and commit them here
    typer.echo("Fetching import info")
    params = None
    if filter_paths is not None:
        params = {"filter_paths": filter_paths}
    try:
        resp = calkit.cloud.get(
            f"/projects/{owner_name}/{project_name}/datasets/{path}",
            params=params,
        )
    except Exception as e:
        raise_error(f"Failed to fetch dataset info from cloud: {e}")
    dvc_import, git_import = resp["dvc_import"], resp["git_import"]
    if dest_path is not None:
        typer.echo(f"Importing to destination path: {dest_path}")
    if dvc_import is not None:
        if dest_path is not None and len(dvc_import["outs"]) > 1:
            raise_error(
                "Cannot specify destination path when importing multiple "
                "DVC files"
            )
        # Ensure we have a DVC remote corresponding to this project, and that we
        # have a token set for that remote
        typer.echo("Adding new DVC remote")
        remote = calkit.dvc.add_external_remote(
            owner_name=owner_name, project_name=project_name
        )
        repo.git.add(".dvc/config")
        # Import this data with DVC
        dvc_fpath = ds_dest_path + ".dvc"
        dvc_dir = os.path.dirname(dvc_fpath)
        os.makedirs(dvc_dir, exist_ok=True)
        # Update paths in .dvc file so they are relative to the DVC file
        if len(dvc_import["outs"]) > 1:
            for n, out in enumerate(dvc_import["outs"]):
                dvc_import["outs"][n]["path"] = os.path.relpath(
                    out["path"], dvc_dir
                )
                dvc_import["outs"][n]["remote"] = remote["name"]
        else:
            dvc_import["outs"][0]["path"] = os.path.basename(
                dvc_import["outs"][0]["path"]
            )
            dvc_import["outs"][0]["remote"] = remote["name"]
        typer.echo("Saving .dvc file")
        with open(dvc_fpath, "w") as f:
            calkit.ryaml.dump(dvc_import, f)
        repo.git.add(dvc_fpath)
        # Add to .gitignore
        typer.echo("Checking .gitignore")
        if os.path.isfile(".gitignore"):
            with open(".gitignore") as f:
                gitignore = f.read()
        else:
            gitignore = ""
        if ds_dest_path not in gitignore.split("\n"):
            typer.echo(f"Adding {ds_dest_path} to .gitignore")
            gitignore = gitignore.rstrip() + "\n" + ds_dest_path + "\n"
            with open(".gitignore", "w") as f:
                f.write(gitignore)
            repo.git.add(".gitignore")
    elif git_import is not None:
        typer.echo("Fetching files directly since they're kept in Git")
        files = git_import["files"]
        if dest_path is not None:
            os.makedirs(dest_path, exist_ok=True)
        for f in tqdm(files):
            # Fetch content from API
            resp_i = calkit.cloud.get(
                f"/projects/{owner_name}/{project_name}/contents/{f}"
            )
            content = resp_i.get("content")
            fname = os.path.basename(f)
            dirname = os.path.dirname(f) if dest_path is None else dest_path
            os.makedirs(dirname, exist_ok=True)
            out_path = os.path.join(dirname, fname)
            if content is not None:
                # Decode base64 content and save locally
                with open(out_path, "wb") as f:
                    f.write(base64.b64decode(content))
            else:
                url = resp_i.get("url")
                if url is None:
                    raise_error(f"Could not fetch {f}")
                # Download from URL
                resp_dl = requests.get(url, stream=True)
                try:
                    resp_dl.raise_for_status()
                except Exception as e:
                    raise_error(f"Failed to download {f} from {url}: {e}")
                with open(out_path, "wb") as f:
                    for chunk in resp_dl.iter_content(chunk_size=8192):
                        f.write(chunk)
            repo.git.add(out_path)
    else:
        raise_error("Could not fetch import info from Calkit Cloud")
    # Add to datasets in calkit.yaml
    typer.echo("Adding dataset to calkit.yaml")
    new_ds = calkit.models.ImportedDataset(
        path=ds_dest_path,
        title=resp.get("title"),
        description=resp.get("description"),
        stage=None,
        imported_from=calkit.models._ImportedFromProject(
            project=f"{owner_name}/{project_name}",
            path=path,
            git_rev=resp.get("git_rev"),
            filter_paths=filter_paths,
        ),
    )
    datasets.append(new_ds.model_dump())
    ck_info["datasets"] = datasets
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    if not no_commit:
        # Commit any necessary changes
        typer.echo("Committing changes")
        repo.git.commit(["-m", f"Import dataset {src_path}"])
    if not no_dvc_pull and dvc_import is not None:
        # Run dvc pull
        typer.echo("Running dvc pull")
        subprocess.call([sys.executable, "-m", "dvc", "pull", dvc_fpath])


@import_app.command(name="environment")
def import_environment(
    src: Annotated[
        str,
        typer.Argument(
            help=(
                "Environment location and name, e.g., "
                "someone/some-project:env-name. If not present, the Calkit "
                "Cloud will be queried."
            )
        ),
    ],
    dest_path: Annotated[
        str | None,
        typer.Option("--path", help="Output path at which to save."),
    ] = None,
    dest_name: Annotated[
        str | None,
        typer.Option(
            "--name", "-n", help="Name to use in the destination project."
        ),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Force adding the dataset even if it already exists.",
        ),
    ] = False,
    no_commit: Annotated[
        bool, typer.Option("--no-commit", help="Do not commit changes.")
    ] = False,
) -> None:
    """Import an environment from another project."""
    raise_error(
        "This command is not yet implemented; "
        "please thumbs-up this issue if you'd like to see "
        "it finished: https://github.com/calkit/calkit/issues/239"
    )
    try:
        project, env_name = src.split(":")
    except ValueError:
        raise_error("Invalid source environment specification")
    if os.path.isdir(project):
        typer.echo(f"Importing from local project directory: {project}")
        src_ck_info = dict(
            calkit.load_calkit_info(wdir=project, process_includes=True)
        )
        environments = src_ck_info.get("environments", {})
        if env_name not in environments:
            raise_error(f"Environment {env_name} not found in project")
        src_env = environments[env_name]
        if "path" in src_env:
            env_path = src_env["path"]  # noqa: F841 TODO: Use this variable
        try:
            src_project_name = calkit.detect_project_name(project)
        except Exception as e:
            raise_error(f"Could not detect source project name: {e}")
    else:
        typer.echo("Importing from Cloud project")
        try:
            resp = calkit.cloud.get(  # noqa: F841 TODO: Use this variable
                f"/projects/{project}/environments/{env_name}"
            )
        except Exception as e:
            raise_error(f"Failed to fetch environment info from cloud: {e}")
        src_project_name = project
        # TODO: Parse information we need from the response
    # Write environment into current Calkit info
    ck_info = calkit.load_calkit_info()
    environments = ck_info.get("environments", {})
    # Check if an environment with this name already exists
    if dest_name is None:
        dest_name = env_name
    if dest_name in environments and not overwrite:
        raise_error("An environment with this name already exists")
    # If source env is imported, don't update that field
    new_env = deepcopy(src_env)
    if "imported_from" not in new_env:
        new_env["imported_from"]["project"] = src_project_name
    if dest_path is not None and "path" in new_env:
        new_env["path"] = dest_path
    # TODO: Write the environment content to file if necessary
    new_env = dict(imported_from=dict(project=project))
    environments[dest_name] = new_env
    ck_info["environments"] = environments
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    repo = git.Repo()
    repo.git.add("calkit.yaml")
    if not no_commit and calkit.git.get_staged_files():
        repo.git.commit(["-m", f"Import environment {src}"])
