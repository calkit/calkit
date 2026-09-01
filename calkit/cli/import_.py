"""CLI for importing objects."""

from __future__ import annotations

import base64
import fnmatch
import json
import os
from copy import deepcopy
from typing import Annotated

import typer

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
        str | None,
        typer.Argument(help="Output path at which to save."),
    ] = None,
    filter_paths: Annotated[
        list[str] | None,
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
    http: Annotated[
        bool,
        typer.Option(
            "--http",
            help=(
                "Use the legacy HTTP URL for the imported project's DVC "
                "remote instead of ck://."
            ),
        ),
    ] = False,
):
    """Import a dataset.

    Currently only supports datasets kept in DVC, not Git.
    """
    import requests
    from tqdm import tqdm

    from calkit.dvc import run_dvc_command
    from calkit.models.core import _ImportedFromProject

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
    repo = calkit.git.get_repo()
    # Obtain, save, and commit the .dvc file for the dataset, or if this is
    # kept in Git, just download the files and commit them here
    typer.echo("Fetching import info")
    params = None
    if filter_paths is not None:
        params = {"filter_paths": filter_paths}
    try:
        resp = calkit.hub.get(
            f"/projects/{owner_name}/{project_name}/datasets/{path}",
            params=params,
        )
    except Exception as e:
        raise_error(f"Failed to fetch dataset info from the hub: {e}")
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
            owner_name=owner_name,
            project_name=project_name,
            use_ck=not http,
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
            resp_i = calkit.hub.get(
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
        raise_error("Could not fetch import info from the hub")
    # Add to datasets in calkit.yaml
    typer.echo("Adding dataset to calkit.yaml")
    new_ds = calkit.models.ImportedDataset(
        path=ds_dest_path,
        title=resp.get("title"),
        description=resp.get("description"),
        stage=None,
        imported_from=_ImportedFromProject(
            project=f"{owner_name}/{project_name}",
            path=path,
            git_rev=resp.get("git_rev"),
            filter_paths=filter_paths,
        ),
    )
    # Nulls left out, so the entry reads as what was recorded rather than as
    # a form with most of its fields blank
    datasets.append(new_ds.model_dump(exclude_none=True))
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
        result = run_dvc_command(["pull", dvc_fpath])
        if result != 0:
            raise_error("Failed to pull from DVC")


@import_app.command(name="path")
def import_path(
    src_path: Annotated[
        str,
        typer.Argument(
            help=(
                "Where to get the file: a URL, including a GitHub or GitLab "
                "link to a file, an SSH clone URL like "
                "git@github.com:owner/repo/path, a DOI, a Calkit project "
                "path like someone/some-project/scripts/setup.sh, or a path "
                "inside the repo named by --git-repo."
            )
        ),
    ],
    dest_path: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Path at which to save it in this project. Defaults to the "
                "source path."
            )
        ),
    ] = None,
    kind: Annotated[
        str,
        typer.Option(
            "--kind",
            help=(
                "Which list in calkit.yaml to record this in: 'datasets', "
                "'figures', 'publications', or 'misc' (default), which is "
                "where a path that isn't one of the typed artifacts belongs."
            ),
        ),
    ] = "misc",
    git_repo: Annotated[
        str | None,
        typer.Option(
            "--git-repo",
            help=(
                "Clone URL of a Git repo to take the file from, for a repo "
                "that isn't a Calkit project."
            ),
        ),
    ] = None,
    git_ref: Annotated[
        str | None,
        typer.Option(
            "--git-ref",
            help=(
                "Branch, tag, or commit to follow, recorded so 'calkit "
                "update path' knows where to look next time, and overriding "
                "one read out of the URL. Needed for a URL whose branch "
                "name contains a slash. Defaults to the repo's default "
                "branch."
            ),
        ),
    ] = None,
    title: Annotated[
        str | None, typer.Option("--title", help="Title for the entry.")
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", help="Description for the entry."),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Replace an existing file or entry at this path.",
        ),
    ] = False,
    no_commit: Annotated[
        bool,
        typer.Option("--no-commit", help="Do not commit changes to repo."),
    ] = False,
) -> None:
    """Import a file from elsewhere, recording where it came from.

    For a script or config maintained outside this project, e.g., a site
    setup script shared between projects. The copy is committed here, so
    the project stays self-contained and the pipeline can depend on it;
    the entry records the source so it can be refreshed with 'calkit
    update path' and so the file isn't one whose origin nobody knows.
    """
    from pydantic import TypeAdapter

    from calkit.models.core import ImportedFromType
    from calkit.provenance import get_importable_artifact_types

    importable = get_importable_artifact_types()
    if kind not in importable:
        raise_error(
            f"Invalid --kind '{kind}'; expected one of {', '.join(importable)}"
        )
    # Where it came from, in the shape the entry records it. 'rev' is
    # filled in from what the fetch actually checked out, so a source
    # naming a branch still ends up pinned to a commit.
    try:
        imported_from = calkit.provenance.source_from_location(
            src_path, git_repo=git_repo, ref=git_ref
        )
    except ValueError as e:
        raise_error(str(e))
    if dest_path is None:
        dest_path = calkit.provenance.default_dest_path(imported_from)
    if not dest_path:
        raise_error(
            f"Cannot tell what to call the file imported from '{src_path}'; "
            "give a destination path"
        )
    ck_info = calkit.load_calkit_info()
    # Checked across every list and on disk, since either would be
    # clobbered
    found = calkit.provenance.find_artifact(ck_info, dest_path)
    if found is not None and not overwrite:
        raise_error(
            f"A {found[0]} entry already exists at '{dest_path}'; pass "
            "--overwrite to replace it, or use 'calkit update path' to "
            "refresh it from where it came from"
        )
    if os.path.exists(dest_path) and not overwrite:
        raise_error(
            f"'{dest_path}' already exists; pass --overwrite to replace it"
        )
    typer.echo(f"Fetching {calkit.provenance.describe_source(imported_from)}")
    try:
        imported_from = calkit.provenance.fetch(
            imported_from, dest_path=dest_path
        )
    except ValueError as e:
        raise_error(str(e))
    # Validated the same way it would be reading calkit.yaml back, so a
    # rev that isn't a commit hash, or a DOI that isn't one, is caught
    # here rather than on the next load
    try:
        source = TypeAdapter(ImportedFromType).validate_python(imported_from)
    except Exception as e:
        raise_error(f"Failed to record where this came from: {e}")
    entry: dict = {"path": dest_path}
    if title:
        entry["title"] = title
    if description:
        entry["description"] = description
    entry["imported_from"] = source.model_dump(exclude_none=True)
    if found is not None:
        ck_info[found[0]].remove(found[1])
    ck_info.setdefault(kind, []).append(entry)
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    repo = calkit.git.get_repo()
    paths = [dest_path, "calkit.yaml"]
    repo.git.add(paths)
    typer.echo(f"Imported to {dest_path}")
    if not no_commit:
        typer.echo("Committing changes")
        # Scoped, so unrelated staged work isn't swept into a commit
        # claiming to be about this import
        repo.git.commit(paths + ["-m", f"Import {dest_path}"])


@import_app.command(name="environment")
def import_environment(
    src: Annotated[
        str,
        typer.Argument(
            help=(
                "Environment location and name, e.g., "
                "someone/some-project:env-name. If not present, the Calkit "
                "API will be queried."
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
        src_ck_info = dict(calkit.load_calkit_info(wdir=project))
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
        typer.echo("Importing from hub project")
        try:
            resp = calkit.hub.get(  # noqa: F841 TODO: Use this variable
                f"/projects/{project}/environments/{env_name}"
            )
        except Exception as e:
            raise_error(f"Failed to fetch environment info from the hub: {e}")
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
    repo = calkit.git.get_repo()
    repo.git.add("calkit.yaml")
    if not no_commit and calkit.git.get_staged_files():
        repo.git.commit(["-m", f"Import environment {src}"])


@import_app.command(name="zenodo")
def import_from_zenodo(
    src: Annotated[str, typer.Argument(help="Source URL or DOI.")],
    dest_dir: Annotated[
        str,
        typer.Argument(
            help="Destination folder. Will be created if it doesn't exist"
        ),
    ],
    kind: Annotated[
        str | None,
        typer.Option(
            "--kind",
            "-k",
            help=(
                "What kind of artifact is being imported, "
                "e.g., a figure, dataset, publication."
            ),
        ),
    ] = None,
    name_like: Annotated[
        list[str],
        typer.Option(
            "--name-like",
            help="Filter for file names like this. Glob patterns accepted.",
        ),
    ] = [],
    name_not_like: Annotated[
        list[str],
        typer.Option(
            "--name-not-like",
            help="Exclude names matching pattern.",
        ),
    ] = [],
    storage: Annotated[
        str | None,
        typer.Option(
            "--storage",
            help="Storage backend to use (Git or DVC). "
            "If not specified, will be chosen based on size.",
        ),
    ] = None,
    no_commit: Annotated[
        bool,
        typer.Option("--no-commit", help="Do not commit changes to project."),
    ] = False,
):
    """Import files from a Zenodo record."""
    import requests

    from calkit.dvc import run_dvc_command

    # Ensure destination directory either doesn't exist or is empty
    if os.path.isdir(dest_dir):
        if os.listdir(dest_dir):
            raise_error("Destination directory exists and is not empty")
    if kind is not None and kind not in ["figure", "dataset", "publication"]:
        raise_error(
            "Invalid kind; must be one of 'figure', 'dataset', or "
            "'publication'"
        )
    # Fetch information about the record
    # First, extract the record ID from the src
    if "zenodo.org/record/" in src:
        try:
            record_id = int(src.split("zenodo.org/record/")[1].split("/")[0])
        except Exception:
            raise_error("Could not parse Zenodo record ID from URL")
    elif "10.5281/zenodo." in src:
        try:
            record_id = int(src.split("10.5281/zenodo.")[1])
        except Exception:
            raise_error("Could not parse Zenodo record ID from DOI")
    else:
        raise_error("Source must be a Zenodo URL or DOI")
    typer.echo(f"Fetching info for Zenodo record {record_id}")
    try:
        record = calkit.invenio.get(
            f"/records/{record_id}", service="zenodo", auth=False
        )
    except Exception as e:
        raise_error(f"Could not fetch record info from Zenodo: {e}")
    # Get download URLs
    download_urls = calkit.invenio.get_download_urls(
        record_id, service="zenodo", auth=False
    )
    # Filter download URLs
    filtered_urls = {}
    for fname, url in download_urls.items():
        if name_like:
            if not any(
                fnmatch.fnmatch(fname, pattern) for pattern in name_like
            ):
                continue
        if name_not_like:
            if any(
                fnmatch.fnmatch(fname, pattern) for pattern in name_not_like
            ):
                continue
        filtered_urls[fname] = url
    if not filtered_urls:
        raise_error("No files matched the specified name filters")
    # Download files
    for fname, url in filtered_urls.items():
        out_path = os.path.join(dest_dir, fname)  # fname may include subdirs
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        typer.echo(f"Downloading {fname} to {out_path}")
        resp = requests.get(url, stream=True)
        try:
            resp.raise_for_status()
        except Exception as e:
            raise_error(f"Failed to download {fname} from {url}: {e}")
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
    # Decide if this should be stored in Git or DVC
    repo = calkit.git.get_repo()
    commit_paths = []
    if storage is None:
        if calkit.get_size(dest_dir) > calkit.DVC_SIZE_THRESH_BYTES:
            result = run_dvc_command(["add"])
            if result != 0:
                raise_error("Failed to DVC add")
            # Git add the .dvc file
            dvc_file = dest_dir + ".dvc"
            repo.git.add(dvc_file)
            commit_paths.append(dvc_file)
        else:
            repo.git.add(dest_dir)
            commit_paths.append(dest_dir)
    elif storage.lower() == "dvc":
        result = run_dvc_command(["add", dest_dir])
        if result != 0:
            raise_error("Failed to DVC add")
        # Git add the .dvc file
        dvc_file = dest_dir + ".dvc"
        repo.git.add(dvc_file)
        commit_paths.append(dvc_file)
    elif storage.lower() == "git":
        repo.git.add(dest_dir)
        commit_paths.append(dest_dir)
    else:
        raise_error("Invalid storage option; must be 'git' or 'dvc'")
    # Determine if we should put this in one of the calkit.yaml categories
    if kind is not None:
        ck_info = calkit.load_calkit_info()
        items = ck_info.get(kind + "s", [])
        # A record without a DOI (not every one has been minted one) is still
        # somewhere in particular, so fall back to its URL rather than
        # writing ``doi: null``, which nothing would then accept
        doi = calkit.invenio.extract_doi(record)
        if doi is not None:
            imported_from: dict = {"doi": doi}
        else:
            imported_from = {
                "url": record.get("links", {}).get("self_html")
                or f"https://zenodo.org/records/{record_id}"
            }
        item_record = {
            "path": dest_dir,
            "imported_from": imported_from,
        }
        title = record.get("metadata", {}).get("title")
        if title:
            item_record["title"] = title
        items.append(item_record)
        ck_info[kind + "s"] = items
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        commit_paths.append("calkit.yaml")
    # Save a record of this import in .calkit/imports.json
    import_record = {
        "from": "zenodo",
        "record_id": record_id,
        "src": src,
        "dest_dir": dest_dir,
        "timestamp": calkit.utcnow(),
        "kind": kind,
        "storage": storage,
        "name_like": name_like,
        "name_not_like": name_not_like,
    }
    os.makedirs(".calkit", exist_ok=True)
    imports_fpath = os.path.join(".calkit", "imports.json")
    commit_paths.append(imports_fpath)
    if os.path.isfile(imports_fpath):
        with open(imports_fpath) as f:
            imports = json.load(f)
    else:
        imports = []
    imports.append(import_record)
    with open(imports_fpath, "w") as f:
        json.dump(imports, f, indent=2)
    # Commit if desired
    if not no_commit:
        repo = calkit.git.get_repo()
        repo.git.add(commit_paths)
        if repo.git.diff(commit_paths + ["--staged"]):
            repo.git.commit(
                commit_paths
                + ["-m", f"Import {src} from Zenodo to {dest_dir}"]
            )
