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
            "-q",
            help="Suppress non-essential output.",
        ),
    ] = False,
):
    """Copy packaged Calkit agent skills to `~/.agents/skills`."""
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

    def _fix_skill_name(dest_dir: str, prefixed_name: str) -> None:
        skill_md = os.path.join(dest_dir, "SKILL.md")
        if not os.path.isfile(skill_md):
            return
        with open(skill_md) as f:
            content = f.read()
        import re

        content = re.sub(
            r"^(name:\s*)(.+)$",
            f"\\g<1>{prefixed_name}",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        with open(skill_md, "w") as f:
            f.write(content)

    copied = 0
    if use_packaged:
        for entry in source.iterdir():
            if not entry.is_dir():
                continue
            prefixed = f"calkit-{entry.name}"
            dest = os.path.join(dest_root, prefixed)
            with resources.as_file(entry) as source_dir:
                shutil.copytree(source_dir, dest, dirs_exist_ok=True)
            _fix_skill_name(dest, prefixed)
            copied += 1
    else:
        for name in os.listdir(source_repo):
            source_dir = os.path.join(source_repo, name)
            if not os.path.isdir(source_dir):
                continue
            prefixed = f"calkit-{name}"
            dest = os.path.join(dest_root, prefixed)
            shutil.copytree(source_dir, dest, dirs_exist_ok=True)
            _fix_skill_name(dest, prefixed)
            copied += 1
    if not quiet:
        typer.echo(f"Updated {copied} skills in {dest_root}")


def _load_env(env_name: str) -> tuple[dict, dict]:
    """Load calkit.yaml and return (ck_info, env_dict)."""
    with open("calkit.yaml") as f:
        ck_info = calkit.ryaml.load(f)
    if ck_info is None:
        ck_info = {}
    envs = ck_info.get("environments") or {}
    if env_name not in envs:
        raise_error(f"Environment '{env_name}' does not exist")
    return ck_info, envs[env_name]


def _save_calkit_yaml(ck_info: dict) -> None:
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)


@update_app.command(name="uv-env")
def update_uv_env(
    env_name: Annotated[
        str,
        typer.Option("--name", "-n", help="Environment name."),
    ],
    add: Annotated[
        list[str],
        typer.Option("--add", help="Add a package."),
    ] = [],
    remove: Annotated[
        list[str],
        typer.Option("--remove", "--rm", help="Remove a package."),
    ] = [],
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check",
            help="Skip checking (syncing) the environment after updating.",
        ),
    ] = False,
) -> None:
    """Update a uv environment."""
    import subprocess

    ck_info, env = _load_env(env_name)
    if env.get("kind") not in ("uv", "uv-venv"):
        raise_error(f"Environment '{env_name}' is not a uv environment")
    spec_path = env.get("path", "pyproject.toml")
    env_dir = os.path.dirname(spec_path) or "."
    if add:
        res = subprocess.run(["uv", "add"] + list(add), cwd=env_dir)
        if res.returncode != 0:
            raise_error("Failed to add packages")
    if remove:
        res = subprocess.run(["uv", "remove"] + list(remove), cwd=env_dir)
        if res.returncode != 0:
            raise_error("Failed to remove packages")
    typer.echo(f"Updated uv environment '{env_name}'")
    if not no_check:
        typer.echo(f"Checking environment '{env_name}'")
        from calkit.cli.check import check_environment

        check_environment(env_name=env_name)


@update_app.command(name="conda-env")
def update_conda_env(
    env_name: Annotated[
        str,
        typer.Option("--name", "-n", help="Environment name."),
    ],
    add: Annotated[
        list[str],
        typer.Option("--add", help="Add a conda package."),
    ] = [],
    remove: Annotated[
        list[str],
        typer.Option("--remove", "--rm", help="Remove a conda package."),
    ] = [],
    add_pip: Annotated[
        list[str],
        typer.Option("--add-pip", help="Add a pip package."),
    ] = [],
    remove_pip: Annotated[
        list[str],
        typer.Option("--remove-pip", "--rm-pip", help="Remove a pip package."),
    ] = [],
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check",
            help="Skip checking (syncing) the environment after updating.",
        ),
    ] = False,
) -> None:
    """Update a conda environment spec file."""
    ck_info, env = _load_env(env_name)
    if env.get("kind") != "conda":
        raise_error(f"Environment '{env_name}' is not a conda environment")
    spec_path = env.get("path", "environment.yml")
    with open(spec_path) as f:
        spec = calkit.ryaml.load(f)
    if spec is None:
        spec = {}
    deps = list(spec.get("dependencies") or [])
    # Edit conda (string) deps
    for pkg in remove:
        deps = [
            d
            for d in deps
            if not isinstance(d, str)
            or (d != pkg and not d.startswith(pkg + "="))
        ]
    for pkg in add:
        if pkg not in deps:
            deps.append(pkg)
    # Edit pip sublist
    if add_pip or remove_pip:
        pip_dict = next(
            (d for d in deps if isinstance(d, dict) and "pip" in d), None
        )
        pip_list = list(pip_dict["pip"] if pip_dict else [])
        for pkg in remove_pip:
            pip_list = [
                p for p in pip_list if p != pkg and not p.startswith(pkg + "=")
            ]
        for pkg in add_pip:
            if pkg not in pip_list:
                pip_list.append(pkg)
        if pip_dict is not None:
            deps.remove(pip_dict)
        if pip_list:
            deps.append({"pip": pip_list})
    if deps:
        spec["dependencies"] = deps
    elif "dependencies" in spec:
        del spec["dependencies"]
    with open(spec_path, "w") as f:
        calkit.ryaml.dump(spec, f)
    typer.echo(f"Updated conda environment spec '{spec_path}'")
    if not no_check:
        typer.echo(f"Checking environment '{env_name}'")
        from calkit.cli.check import check_environment

        check_environment(env_name=env_name)


@update_app.command(name="docker-env")
def update_docker_env(
    env_name: Annotated[
        str,
        typer.Option("--name", "-n", help="Environment name."),
    ],
    image: Annotated[
        str | None,
        typer.Option("--image", help="Docker image name/tag."),
    ] = None,
) -> None:
    """Update a docker environment."""
    ck_info, env = _load_env(env_name)
    if env.get("kind") != "docker":
        raise_error(f"Environment '{env_name}' is not a docker environment")
    if image is None:
        raise_error("No updates specified. Use --image to set the image.")
    env["image"] = image
    _save_calkit_yaml(ck_info)
    typer.echo(f"Updated docker environment '{env_name}'")


@update_app.command(name="slurm-env")
def update_slurm_env(
    env_name: Annotated[
        str,
        typer.Option("--name", "-n", help="Environment name."),
    ],
    host: Annotated[
        str | None,
        typer.Option("--host", help="SLURM host."),
    ] = None,
    add_default_option: Annotated[
        list[str],
        typer.Option(
            "--add-default-option", help="Add a default sbatch option."
        ),
    ] = [],
    rm_default_option: Annotated[
        list[str],
        typer.Option(
            "--rm-default-option", help="Remove a default sbatch option."
        ),
    ] = [],
    set_default_options: Annotated[
        list[str],
        typer.Option(
            "--set-default-options", help="Replace default options list."
        ),
    ] = [],
    add_default_setup: Annotated[
        list[str],
        typer.Option(
            "--add-default-setup", help="Add a default setup command."
        ),
    ] = [],
    rm_default_setup: Annotated[
        list[str],
        typer.Option(
            "--rm-default-setup", help="Remove a default setup command."
        ),
    ] = [],
    set_default_setup: Annotated[
        list[str],
        typer.Option(
            "--set-default-setup", help="Replace default setup list."
        ),
    ] = [],
) -> None:
    """Update a SLURM environment."""
    ck_info, env = _load_env(env_name)
    if env.get("kind") != "slurm":
        raise_error(f"Environment '{env_name}' is not a slurm environment")
    if host is not None:
        env["host"] = host
    if set_default_options:
        opts = [o for o in set_default_options if o]
    else:
        opts = list(env.get("default_options") or [])
        opts = [o for o in opts if o not in rm_default_option]
        for o in add_default_option:
            if o not in opts:
                opts.append(o)
    if opts:
        env["default_options"] = opts
    elif "default_options" in env:
        del env["default_options"]
    if set_default_setup:
        cmds = [c for c in set_default_setup if c]
    else:
        cmds = list(env.get("default_setup") or [])
        cmds = [c for c in cmds if c not in rm_default_setup]
        for c in add_default_setup:
            if c not in cmds:
                cmds.append(c)
    if cmds:
        env["default_setup"] = cmds
    elif "default_setup" in env:
        del env["default_setup"]
    _save_calkit_yaml(ck_info)
    typer.echo(f"Updated slurm environment '{env_name}'")


@update_app.command(name="environment")
@update_app.command(name="env")
def update_environment(
    env_name: Annotated[
        str,
        typer.Option("--name", "-n", help="Name of the environment to update"),
    ],
    add_packages: Annotated[
        list[str] | None,
        typer.Option("--add", help="Add package (julia only)."),
    ] = None,
) -> None:
    """Update an environment (generic; use update [kind]-env for full options)."""
    from calkit.cli.main import run_in_env

    ck_info, env = _load_env(env_name)
    kind = env.get("kind")
    if kind == "julia" and add_packages:
        add_packages_str = ", ".join(
            [f'"{pkg.strip()}"' for pkg in add_packages]
        )
        julia_cmd = ["-e", f"using Pkg; Pkg.add([{add_packages_str}])"]
        run_in_env(env_name=env_name, cmd=julia_cmd)
    else:
        raise_error(
            f"Use 'calkit update {kind}-env' for kind '{kind}', "
            "or --add for Julia."
        )
    typer.echo(f"Updated environment '{env_name}'")


@update_app.command(name="stage")
def update_stage(
    name: Annotated[str, typer.Argument(help="Stage name.")],
    environment: Annotated[
        str | None,
        typer.Option("--environment", "-e", help="Set environment."),
    ] = None,
    add_input: Annotated[
        list[str],
        typer.Option("--add-input", help="Add an input path."),
    ] = [],
    rm_input: Annotated[
        list[str],
        typer.Option("--rm-input", help="Remove an input path."),
    ] = [],
    set_inputs: Annotated[
        list[str],
        typer.Option("--set-inputs", help="Replace the inputs list."),
    ] = [],
    add_output: Annotated[
        list[str],
        typer.Option("--add-output", help="Add an output path."),
    ] = [],
    rm_output: Annotated[
        list[str],
        typer.Option("--rm-output", help="Remove an output path."),
    ] = [],
    set_outputs: Annotated[
        list[str],
        typer.Option("--set-outputs", help="Replace the outputs list."),
    ] = [],
) -> None:
    """Update a pipeline stage in calkit.yaml."""
    with open("calkit.yaml") as f:
        ck_info = calkit.ryaml.load(f)
    if ck_info is None:
        ck_info = {}
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    if name not in stages:
        raise_error(f"Stage '{name}' not found in calkit.yaml.")
    stage = stages[name]
    if environment is not None:
        stage["environment"] = environment or None
    # Inputs
    if set_inputs:
        inputs_list = [i for i in set_inputs if i]
    else:
        inputs_list = list(stage.get("inputs") or [])
        inputs_list = [i for i in inputs_list if i not in rm_input]
        for i in add_input:
            if i not in inputs_list:
                inputs_list.append(i)
    if inputs_list:
        stage["inputs"] = inputs_list
    elif "inputs" in stage:
        del stage["inputs"]
    # Outputs
    if set_outputs:
        outputs_list = [o for o in set_outputs if o]
    else:
        outputs_list = list(stage.get("outputs") or [])
        outputs_list = [o for o in outputs_list if o not in rm_output]
        for o in add_output:
            if o not in outputs_list:
                outputs_list.append(o)
    if outputs_list:
        stage["outputs"] = outputs_list
    elif "outputs" in stage:
        del stage["outputs"]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)


@update_app.command(name="figure")
def update_figure(
    path: Annotated[str, typer.Argument(help="Path to the figure file.")],
    imported_from_url: Annotated[
        str | None,
        typer.Option(
            "--imported-from-url",
            help="URL the figure was imported from.",
        ),
    ] = None,
) -> None:
    """Update a figure entry in calkit.yaml."""
    if imported_from_url is None:
        raise_error("No updates specified.")
    with open("calkit.yaml") as f:
        ck_info = calkit.ryaml.load(f)
    if ck_info is None:
        ck_info = {}
    figures = ck_info.get("figures", [])
    imported_from_val = {"url": imported_from_url}
    for fig in figures:
        if fig.get("path") == path:
            fig["imported_from"] = imported_from_val
            break
    else:
        figures.append({"path": path, "imported_from": imported_from_val})
        ck_info["figures"] = figures
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
