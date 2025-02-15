"""CLI for importing objects."""

from __future__ import annotations

import base64
import os
import subprocess
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
        # Import this data with DVC
        dvc_fpath = ds_dest_path + ".dvc"
        dvc_dir = os.path.dirname(dvc_fpath)
        os.makedirs(dvc_dir, exist_ok=True)
        # Update paths in .dvc file so they are relative to the DVC file
        for n, out in enumerate(dvc_import["outs"]):
            dvc_import["outs"][n]["path"] = os.path.relpath(
                out["path"], dvc_dir
            )
        typer.echo("Saving .dvc file")
        with open(dvc_fpath, "w") as f:
            calkit.ryaml.dump(dvc_import, f)
        repo.git.add(dvc_fpath)
        # Ensure we have a DVC remote corresponding to this project, and that we
        # have a token set for that remote
        typer.echo("Adding new DVC remote")
        calkit.dvc.add_external_remote(
            owner_name=owner_name, project_name=project_name
        )
        repo.git.add(".dvc/config")
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
            git_rev=None,  # TODO?
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
    if not no_dvc_pull:
        # Run dvc pull
        typer.echo("Running dvc pull")
        subprocess.call(["dvc", "pull", dest_path])


@import_app.command(name="environment")
def import_environment(
    src_path: Annotated[
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
        str,
        typer.Option("--path", help="Output path at which to save."),
    ] = None,
    dest_name: Annotated[
        str,
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
) -> None:
    project, env_name = src_path.split(":")
    if os.path.isdir(project):
        cloud = False
        typer.echo("Importing from local project directory")
    else:
        cloud = True
        typer.echo("Importing from Cloud project")
    raise_error("Not yet implemented")  # TODO
