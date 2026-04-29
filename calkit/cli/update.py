"""CLI for updating objects."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from importlib import resources

import git
import requests
import typer
from typing_extensions import Annotated

import calkit
import calkit.pipeline
from calkit.cli import raise_error

update_app = typer.Typer(no_args_is_help=True)


@update_app.command(name="devcontainer")
def update_devcontainer(
    wdir: Annotated[
        str | None,
        typer.Option(
            "--wdir",
            help=(
                "Working directory. "
                "By default will run current working directory."
            ),
        ),
    ] = None,
    no_commit: Annotated[
        bool,
        typer.Option(
            "--no-commit",
            help="Do not create a Git commit for the updated devcontainer.",
        ),
    ] = False,
):
    """Update a project's devcontainer to match the latest Calkit spec."""
    url = (
        "https://raw.githubusercontent.com/calkit/devcontainer/"
        "refs/heads/main/devcontainer.json"
    )
    typer.echo(f"Downloading {url}")
    resp = requests.get(url)
    out_dir = os.path.join(wdir or ".", ".devcontainer")
    os.makedirs(out_dir, exist_ok=True)
    out_fpath = os.path.join(out_dir, "devcontainer.json")
    typer.echo(f"Writing to {out_fpath}")
    with open(out_fpath, "w") as f:
        f.write(resp.text)
    if not no_commit:
        repo = git.Repo(wdir)
        rel_path = os.path.join(".devcontainer", "devcontainer.json")
        repo.git.add(rel_path)
        if repo.git.diff(["--staged", "--", rel_path]):
            repo.git.commit([rel_path, "-m", "Update devcontainer"])


@update_app.command(name="license")
def update_license(
    copyright_holder: Annotated[
        str,
        typer.Option(
            "--copyright-holder",
            "-c",
            help="Copyright holder, e.g., your full name.",
        ),
    ],
    no_commit: Annotated[
        bool,
        typer.Option(
            "--no-commit",
            help="Do not create a Git commit for the updated license.",
        ),
    ] = False,
):
    """Update license with a reasonable default
    (MIT for code, CC-BY-4.0 for other files).
    """
    with open("LICENSE", "w") as f:
        f.write(
            calkit.licenses.LICENSE_TEMPLATE_DUAL.format(
                year=calkit.utcnow().year, copyright_holder=copyright_holder
            )
        )
    repo = git.Repo()
    repo.git.add("LICENSE")
    if not no_commit and repo.git.diff(["--staged", "--", "LICENSE"]):
        repo.git.commit(["LICENSE", "-m", "Update license"])


@update_app.command(name="release")
def update_release(
    name: Annotated[
        str | None, typer.Option("--name", "-n", help="Release name.")
    ] = None,
    use_latest: Annotated[
        bool, typer.Option("--latest", help="Update latest release.")
    ] = False,
    delete: Annotated[
        bool, typer.Option("--delete", help="Delete release.")
    ] = False,
    publish: Annotated[
        bool, typer.Option("--publish", help="Publish the release.")
    ] = False,
    reupload: Annotated[
        bool, typer.Option("--reupload", help="Reupload files.")
    ] = False,
    no_github: Annotated[
        bool,
        typer.Option("--no-github", help="Do not create a release on GitHub."),
    ] = False,
    no_push_tags: Annotated[
        bool,
        typer.Option(
            "--no-push-tags", help="Do not push Git tags to remote repository."
        ),
    ] = False,
):
    """Update a release."""
    if name is None and not use_latest:
        raise_error("Release name or --latest must be specified")
    if delete and (publish or reupload):
        raise_error("Cannot delete release if reuploading or publishing")
    ck_info = calkit.load_calkit_info()
    releases = ck_info.get("releases", {})
    if name is not None and name not in releases:
        raise_error(f"Release '{name}' does not exist")
    if use_latest:
        latest_name = None
        latest_date = None
        for release_name, release in releases.items():
            release_date = release.get("date")
            try:
                release_date = datetime.fromisoformat(release_date)
            except Exception:
                raise_error(
                    f"Release '{release_name}' has invalid date "
                    f"'{release_date}'"
                )
            if latest_date is None or release_date > latest_date:
                latest_name = release_name
                latest_date = release_date
        if latest_name is None:
            raise_error("No releases found")
        name = latest_name
    release = releases[name]
    publisher = release.get("publisher")
    release_description = release.get("description")
    project_name = calkit.detect_project_name()
    repo = git.Repo()
    if publisher is None:
        raise_error("Release does not have a publisher")
    record_id = release.get("record_id")
    if record_id is None:
        raise_error("Release has no record ID")
    if publish or reupload:
        typer.echo("Checking pipeline is up-to-date for release update")
        status = calkit.pipeline.get_status(
            ck_info=ck_info,
            check_environments=True,
            clean_notebooks=True,
            compile_to_dvc=True,
        )
        if status.errors:
            raise_error("Pipeline checks failed: " + "; ".join(status.errors))
        if status.failed_environment_checks:
            raise_error(
                "Pipeline environment checks failed for: "
                + ", ".join(status.failed_environment_checks)
            )
        if status.is_stale:
            raise_error(
                "Pipeline is not up-to-date; out-of-date stages: "
                + ", ".join(status.stale_stage_names)
            )
    if publish:
        try:
            calkit.invenio.post(
                f"/records/{record_id}/draft/actions/publish",
                service=publisher,
            )
        except Exception as e:
            raise_error(f"Failed to publish release: {e}")
        # Create a Git tag
        git_tag_message = release_description
        if git_tag_message is None:
            git_tag_message = f"Release {name}"
        repo.git.tag(["-a", name, "-m", git_tag_message])
        if not no_push_tags:
            typer.echo("Pushing Git tags to remote repository")
            repo.git.push("--tags")
        if not no_github:
            typer.echo("Creating GitHub release")
            release_body = ""
            doi = release.get("doi")
            if doi is not None:
                doi_base_url = calkit.releases.SERVICES[publisher]["url"]
                doi_md = (
                    f"[![DOI]({doi_base_url}/badge/DOI/{doi}.svg)]"
                    f"(https://handle.stage.datacite.org/{doi})"
                )
                release_body += doi_md + "\n\n"
            if release_description is not None:
                release_body += release_description
            resp = calkit.cloud.post(
                f"/projects/{project_name}/github-releases",
                json=dict(
                    tag_name=name,
                    body=release_body,
                ),
            )
            typer.echo(f"Created GitHub release at: {resp['url']}")
    if delete:
        try:
            calkit.invenio.delete(
                f"/records/{record_id}/draft", service=publisher
            )
        except Exception as e:
            raise_error(f"Failed to delete release draft: {e}")
        ck_info["releases"].pop(name)
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        repo.git.add("calkit.yaml")
        if "calkit.yaml" in calkit.git.get_staged_files():
            repo.git.commit(["calkit.yaml", "-m", f"Delete release {name}"])
        # TODO: Delete release files, GitHub release, DVC MD5s, etc.
        typer.echo(f"Deleted release '{name}'")
    if reupload:
        # Regenerate archive data and reupload
        path = release["path"]
        release_type = release["kind"]
        # TODO: Enable reuploading artifact releases
        if path != "." or release_type != "project":
            raise_error("Can only handle updating project releases")
        release_dir = f".calkit/releases/{name}"
        release_files_dir = release_dir + "/files"
        os.makedirs(release_files_dir, exist_ok=True)
        # Save a metadata file with each DVC file's MD5 checksum
        dvc_md5s = calkit.releases.make_dvc_md5s(
            zipfile="archive.zip" if path == "." else None,
            paths=None if path == "." else [path],
        )
        dvc_md5s_path = release_dir + "/dvc-md5s.yaml"
        typer.echo(f"Saving DVC MD5 info to {dvc_md5s_path}")
        with open(dvc_md5s_path, "w") as f:
            calkit.ryaml.dump(dvc_md5s, f)
        # Create a README for the Invenio release
        typer.echo("Creating README.md for release")
        title = ck_info.get("title")
        if title is None:
            raise_error("Project has no title")
        readme_txt = f"# {title}\n"
        git_rev = repo.git.rev_parse(["--short", "HEAD"])
        readme_txt += (
            f"\nThis is a {release_type} release ({name}) generated with "
            f"Calkit from Git rev {git_rev}.\n"
        )
        readme_path = release_files_dir + "/README.md"
        with open(readme_path, "w") as f:
            f.write(readme_txt)
        zip_path = release_files_dir + "/archive.zip"
        all_paths = calkit.releases.ls_files()
        typer.echo(f"Adding files to {zip_path}")
        calkit.releases.zip_paths(zip_path, all_paths)
        typer.echo("Checking project release archive")
        try:
            calkit.releases.check_project_release_archive(zip_path)
        except Exception as e:
            raise_error(str(e))
        try:
            files_in_record = [
                entry["key"]
                for entry in calkit.invenio.get(
                    f"/records/{record_id}/draft/files",
                    service=publisher.lower(),
                )["entries"]
            ]
            typer.echo(f"Existing files in record: {files_in_record}")
        except Exception as e:
            raise_error(
                "Failed to get existing files in record: "
                f"{e.__class__.__name__}: {e}"
            )
        # Check size of files dir
        size = calkit.get_size(release_files_dir)
        typer.echo(f"Release size: {(size / 1e6):.1f} MB")
        files = os.listdir(release_files_dir)
        for filename in files:
            if filename in files_in_record:
                typer.echo(f"Deleting existing file {filename} from draft")
                calkit.invenio.delete(
                    f"/records/{record_id}/draft/files/{filename}",
                    service=publisher.lower(),  # type: ignore
                    as_json=False,  # We only get a 204 back
                )
            typer.echo(f"Uploading {filename}")
            fpath = os.path.join(release_files_dir, filename)
            # First, initiate the file upload
            calkit.invenio.post(
                f"/records/{record_id}/draft/files",
                json=[{"key": filename}],
                service=publisher.lower(),  # type: ignore
            )
            # Then upload the file content
            with open(fpath, "rb") as f:
                file_data = f.read()
                resp = calkit.invenio.put(
                    f"/records/{record_id}/draft/files/{filename}/content",
                    headers={"Content-Type": "application/octet-stream"},
                    as_json=False,
                    service=publisher.lower(),  # type: ignore
                    data=file_data,
                )
                typer.echo(f"Status code: {resp.status_code}")
            # Commit the file
            calkit.invenio.post(
                f"/records/{record_id}/draft/files/{filename}/commit",
                service=publisher.lower(),  # type: ignore
            )
    # TODO: Add ability to update metadata


@update_app.command(name="vscode-config")
def update_vscode_config(
    wdir: Annotated[
        str | None,
        typer.Option(
            "--wdir",
            help=(
                "Working directory. "
                "By default will run current working directory."
            ),
        ),
    ] = None,
    no_commit: Annotated[
        bool,
        typer.Option(
            "--no-commit",
            help="Do not create a Git commit for the updated VS Code config.",
        ),
    ] = False,
):
    """Update a project's VS Code config to match the latest Calkit
    recommendations.
    """
    out_dir = os.path.join(wdir or ".", ".vscode")
    os.makedirs(out_dir, exist_ok=True)
    repo = git.Repo(wdir)
    for fname in ["settings.json", "extensions.json"]:
        url = (
            f"https://raw.githubusercontent.com/calkit/vscode-config/"
            f"refs/heads/main/{fname}"
        )
        typer.echo(f"Downloading {url}")
        resp = requests.get(url)
        out_dir = os.path.join(wdir or ".", ".vscode")
        os.makedirs(out_dir, exist_ok=True)
        out_fpath = os.path.join(out_dir, fname)
        typer.echo(f"Writing to {out_fpath}")
        with open(out_fpath, "w") as f:
            f.write(resp.text)
        repo.git.add(os.path.join(".vscode", fname))
    if not no_commit and repo.git.diff(["--staged", "--", ".vscode"]):
        repo.git.commit([".vscode", "-m", "Update VS Code config"])


@update_app.command(name="github-actions")
def update_github_actions(
    wdir: Annotated[
        str | None,
        typer.Option(
            "--wdir",
            help=(
                "Working directory. "
                "By default will run current working directory."
            ),
        ),
    ] = None,
    no_commit: Annotated[
        bool,
        typer.Option(
            "--no-commit",
            help="Do not create a Git commit for the updated GitHub Actions.",
        ),
    ] = False,
):
    """Update a project's GitHub Actions to match the latest Calkit
    recommendations.
    """
    # First look for any existing workflows that run Calkit to use as the
    # output file name
    fname_out = "run-calkit.yml"
    out_dir = os.path.join(wdir or ".", ".github", "workflows")
    os.makedirs(out_dir, exist_ok=True)
    for fname in os.listdir(out_dir):
        if fname.endswith(".yaml") or fname.endswith(".yml"):
            fpath = os.path.join(out_dir, fname)
            with open(fpath) as f:
                if "calkit" in f.read().lower():
                    fname_out = fname
                    break
    url = (
        "https://raw.githubusercontent.com/calkit/run-action/refs/heads/main"
        "/example.yml"
    )
    typer.echo(f"Downloading {url}")
    resp = requests.get(url)
    out_fpath = os.path.join(out_dir, fname_out)
    typer.echo(f"Writing to {out_fpath}")
    with open(out_fpath, "w") as f:
        f.write(resp.text)
    if not no_commit:
        rel_path = os.path.join(".github", "workflows", fname_out)
        repo = git.Repo(wdir)
        repo.git.add(rel_path)
        if repo.git.diff(["--staged", "--", rel_path]):
            repo.git.commit([rel_path, "-m", "Update GitHub Actions workflow"])


@update_app.command(name="notebook")
def update_notebook(
    notebook_path: Annotated[
        str,
        typer.Argument(
            help="Path to the notebook file (relative to workspace)"
        ),
    ],
    set_env: Annotated[
        str | None,
        typer.Option(
            "--set-env",
            help="Environment name to associate with the notebook",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON."),
    ] = False,
):
    """Update notebook information.

    Updates the notebook's environment association in either the
    'notebooks' section or the appropriate 'pipeline' stage, depending on
    whether the notebook has a corresponding pipeline stage.
    """
    try:
        # TODO: Enable updating other things
        if set_env is None:
            raise ValueError("--set-env option is required")
        # Load the current configuration
        ck_info = calkit.load_calkit_info()
        # Normalize the notebook path
        notebook_path_normalized = notebook_path.replace("\\", "/")
        # Check if notebook is part of a pipeline stage first
        found_in_pipeline = False
        if "pipeline" in ck_info and "stages" in ck_info["pipeline"]:
            for stage_name, stage in ck_info["pipeline"]["stages"].items():
                if stage.get("notebook_path") == notebook_path_normalized:
                    stage["environment"] = set_env
                    found_in_pipeline = True
                    break
        # If not in pipeline, update in notebooks section
        if not found_in_pipeline:
            if "notebooks" not in ck_info:
                ck_info["notebooks"] = []
            # Find existing notebook entry or create new one
            notebooks = ck_info["notebooks"]
            found_index = None
            for i, nb in enumerate(notebooks):
                if nb.get("path") == notebook_path_normalized:
                    found_index = i
                    break
            if found_index is not None:
                notebooks[found_index]["environment"] = set_env
            else:
                notebooks.append(
                    {
                        "path": notebook_path_normalized,
                        "environment": set_env,
                    }
                )
        # Write the updated configuration
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        # Output result
        result = {
            "notebook_path": notebook_path_normalized,
            "environment": set_env,
            "location": "pipeline" if found_in_pipeline else "notebooks",
        }
        if json_output:
            typer.echo(json.dumps(result))
        else:
            location_text = (
                "pipeline stage" if found_in_pipeline else "notebooks section"
            )
            typer.echo(
                f"Updated notebook '{notebook_path_normalized}' with "
                f"environment '{set_env}' in {location_text}"
            )
    except Exception as e:
        raise_error(f"Failed to update notebook: {e}")


@update_app.command(name="agent-skills")
def update_agent_skills(
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            help="Suppress non-essential output.",
            hidden=True,
        ),
    ] = False,
):
    """Copy packaged Calkit agent skills to ``~/.agents/skills``."""
    source = resources.files("calkit").joinpath("agent_skills")
    source_repo = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "agent-plugin",
            "skills",
        )
    )
    use_packaged = source.is_dir()
    if not use_packaged and not os.path.isdir(source_repo):
        raise_error("Bundled agent skills are missing from this installation")
    dest_root = os.path.join(os.path.expanduser("~"), ".agents", "skills")
    os.makedirs(dest_root, exist_ok=True)
    copied = 0
    if use_packaged:
        for entry in source.iterdir():
            if not entry.is_dir():
                continue
            dest = os.path.join(dest_root, entry.name)
            with resources.as_file(entry) as source_dir:
                shutil.copytree(source_dir, dest, dirs_exist_ok=True)
            copied += 1
    else:
        for name in os.listdir(source_repo):
            source_dir = os.path.join(source_repo, name)
            if not os.path.isdir(source_dir):
                continue
            dest = os.path.join(dest_root, name)
            shutil.copytree(source_dir, dest, dirs_exist_ok=True)
            copied += 1
    if not quiet:
        typer.echo(f"Updated {copied} skills in {dest_root}")


@update_app.command(name="environment")
@update_app.command(name="env")
def update_environment(
    env_name: Annotated[
        str,
        typer.Option("--name", "-n", help="Name of the environment to update"),
    ],
    add_packages: Annotated[
        list[str] | None,
        typer.Option(
            "--add",
            help=("Add package to environment,"),
        ),
    ] = None,
) -> None:
    """Update an environment.

    Currently only supports adding packages to Julia environments.
    """
    from calkit.cli.main import run_in_env

    ck_info = calkit.load_calkit_info()
    envs = ck_info.get("environments", {})
    if env_name not in envs:
        raise_error(f"Environment '{env_name}' does not exist")
    if add_packages is None:
        raise_error(
            "No updates specified. Use --add to specify packages to add."
        )
    env = envs[env_name]
    if env.get("kind") != "julia":
        raise_error("Currently only Julia environments are supported")
    # If adding package to a Julia environment, we need to simply run a command
    # in it
    assert isinstance(add_packages, list)
    add_packages_str = ", ".join([f'"{pkg.strip()}"' for pkg in add_packages])
    julia_cmd = ["-e", f"using Pkg; Pkg.add([{add_packages_str}])"]
    run_in_env(env_name=env_name, cmd=julia_cmd)
    typer.echo(f"Updated environment '{env_name}'")
