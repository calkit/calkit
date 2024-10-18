"""CLI for importing objects."""

from __future__ import annotations

import os
import subprocess
from typing import Annotated, Literal

import git
import typer

import calkit

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
        typer.Option("--output", "-o", help="Output path at which to save."),
    ] = None,
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
        dest_path = path
    ck_info = calkit.load_calkit_info()
    datasets = ck_info.get("datasets", [])
    ds_paths = [ds["path"] for ds in datasets]
    if not overwrite and dest_path in ds_paths:
        raise ValueError(
            "A dataset already exists in this project at this path"
        )
    elif overwrite and dest_path in ds_paths:
        datasets = [ds for ds in datasets if ds["path"] != dest_path]
    repo = git.Repo()
    # Obtain, save, and commit the .dvc file for the dataset
    resp = calkit.cloud.get(
        f"/projects/{owner_name}/{project_name}/datasets/{path}"
    )
    if not "dvc_import" in resp:
        raise ValueError("This file is not available to import with DVC")
    dvc_fpath = dest_path + ".dvc"
    dvc_dir = os.path.dirname(dvc_fpath)
    os.makedirs(dvc_dir, exist_ok=True)
    with open(dvc_fpath, "w") as f:
        calkit.ryaml.dump(resp["dvc_import"], f)
    repo.git.add(dvc_fpath)
    # Ensure we have a DVC remote corresponding to this project, and that we
    # have a token set for that remote
    calkit.dvc.add_external_remote(
        owner_name=owner_name, project_name=project_name
    )
    repo.git.add(".dvc/config")
    # Add to .gitignore
    if os.path.isfile(".gitignore"):
        with open(".gitignore") as f:
            gitignore = f.read()
    else:
        gitignore = ""
    if dest_path not in gitignore.split("\n"):
        gitignore = gitignore.rstrip() + "\n" + dest_path + "\n"
        with open(".gitignore", "w") as f:
            f.write(gitignore)
        repo.git.add(".gitignore")
    # Add to datasets in calkit.yaml
    new_ds = calkit.models.ImportedDataset(
        path=dest_path,
        title=resp.get("title"),
        description=resp.get("description"),
        stage=None,
        imported_from=calkit.models._ImportedFromProject(
            project=f"{owner_name}/{project_name}",
            path=src_path,
            git_rev=None,  # TODO?
        ),
    )
    datasets.append(new_ds.model_dump())
    ck_info["datasets"] = datasets
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    # Commit any necessary changes
    repo.git.commit(["-m", f"Import dataset {src_path}"])
    # Run dvc pull
    subprocess.call(["dvc", "pull", dest_path])
