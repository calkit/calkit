"""CLI for updating objects."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from importlib import resources

import typer
from typing_extensions import Annotated

import calkit
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
    """Update a project's devcontainer to match this version of Calkit's
    spec.
    """
    from calkit import resources as calkit_resources

    out_dir = os.path.join(wdir or ".", ".devcontainer")
    os.makedirs(out_dir, exist_ok=True)
    out_fpath = os.path.join(out_dir, "devcontainer.json")
    typer.echo(f"Writing to {out_fpath}")
    with open(out_fpath, "w", encoding="utf-8") as f:
        f.write(
            calkit_resources.read_text(
                "devcontainer", calkit_resources.DEVCONTAINER_FNAME
            )
        )
    if not no_commit:
        repo = calkit.git.get_repo(wdir)
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
    repo = calkit.git.get_repo()
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
    import calkit.pipeline

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
    repo = calkit.git.get_repo()
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
            resp = calkit.hub.post(
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
        calkit.save_calkit_info(ck_info)
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
            f"Calkit v{calkit.__version__} from Git rev {git_rev}.\n"
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
    """Update a project's VS Code config to match this version of Calkit's
    recommendations.
    """
    from calkit import resources as calkit_resources

    out_dir = os.path.join(wdir or ".", ".vscode")
    os.makedirs(out_dir, exist_ok=True)
    repo = calkit.git.get_repo(wdir)
    for fname in calkit_resources.VSCODE_FNAMES:
        out_fpath = os.path.join(out_dir, fname)
        typer.echo(f"Writing to {out_fpath}")
        with open(out_fpath, "w", encoding="utf-8") as f:
            f.write(calkit_resources.read_text("vscode", fname))
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
    """Update a project's GitHub Actions to match this version of Calkit's
    recommendations.

    An existing workflow that runs the Calkit action is updated in place,
    pinning the action to this version of Calkit, so this is safe to rerun
    after upgrading.
    """
    from calkit import resources as calkit_resources

    # First look for an existing workflow that runs the Calkit action, so
    # rerunning this updates a project's workflow instead of writing a
    # second one beside it
    fname_out = "run-calkit.yml"
    txt_out = None
    out_dir = os.path.join(wdir or ".", ".github", "workflows")
    os.makedirs(out_dir, exist_ok=True)
    for fname in sorted(os.listdir(out_dir)):
        if fname.endswith(".yaml") or fname.endswith(".yml"):
            fpath = os.path.join(out_dir, fname)
            with open(fpath, encoding="utf-8") as f:
                txt = f.read()
            if calkit_resources.uses_run_action(txt):
                fname_out = fname
                # A workflow that's still the example gets replaced outright,
                # picking up any other improvements to it, but one that's been
                # customized only has its action ref updated
                if not calkit_resources.is_default_github_actions_workflow(
                    txt
                ):
                    txt_out = calkit_resources.set_action_ref(txt)
                break
    if txt_out is None:
        txt_out = calkit_resources.render_github_actions_workflow()
    out_fpath = os.path.join(out_dir, fname_out)
    typer.echo(f"Writing to {out_fpath}")
    with open(out_fpath, "w", encoding="utf-8") as f:
        f.write(txt_out)
    if not no_commit:
        rel_path = os.path.join(".github", "workflows", fname_out)
        repo = calkit.git.get_repo(wdir)
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
        calkit.save_calkit_info(ck_info)
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
    ck_info = calkit.load_calkit_info()
    envs = ck_info.get("environments") or {}
    if env_name not in envs:
        raise_error(f"Environment '{env_name}' does not exist")
    return ck_info, envs[env_name]


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


@update_app.command(name="pixi-env")
def update_pixi_env(
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
        typer.Option("--add-pip", help="Add a PyPI package."),
    ] = [],
    remove_pip: Annotated[
        list[str],
        typer.Option(
            "--remove-pip", "--rm-pip", help="Remove a PyPI package."
        ),
    ] = [],
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check",
            help="Skip checking (syncing) the environment after updating.",
        ),
    ] = False,
) -> None:
    """Update a pixi environment."""
    import subprocess

    import toml

    ck_info, env = _load_env(env_name)
    if env.get("kind") != "pixi":
        raise_error(f"Environment '{env_name}' is not a pixi environment")
    # Packages may live under a pixi feature named after the environment, or in
    # the default tables; only target a feature if that table actually exists
    feature = env.get("name", env_name)
    spec_path = env.get("path", "pixi.toml")
    feature_args = []
    try:
        with open(spec_path) as f:
            pixi_cfg = toml.load(f)
        if feature in pixi_cfg.get("feature", {}):
            feature_args = ["--feature", feature]
    except FileNotFoundError:
        pass
    # Build one pixi command per add/remove so a single failure is reported
    commands = []
    for pkg in remove:
        commands.append((["pixi", "remove"] + feature_args + [pkg], pkg))
    for pkg in add:
        commands.append((["pixi", "add"] + feature_args + [pkg], pkg))
    for pkg in remove_pip:
        commands.append(
            (["pixi", "remove", "--pypi"] + feature_args + [pkg], pkg)
        )
    for pkg in add_pip:
        commands.append(
            (["pixi", "add", "--pypi"] + feature_args + [pkg], pkg)
        )
    for cmd, pkg in commands:
        if subprocess.run(cmd).returncode != 0:
            raise_error(f"Failed to update package '{pkg}'")
    typer.echo(f"Updated pixi environment '{env_name}'")
    if not no_check:
        typer.echo(f"Checking environment '{env_name}'")
        from calkit.cli.check import check_environment

        check_environment(env_name=env_name)


@update_app.command(name="julia-env")
def update_julia_env(
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
    """Update a Julia environment."""
    import subprocess

    ck_info, env = _load_env(env_name)
    if env.get("kind") != "julia":
        raise_error(f"Environment '{env_name}' is not a Julia environment")
    spec_path = env.get("path", "Project.toml")
    env_dir = os.path.dirname(spec_path) or "."
    julia_version = env.get("julia")
    julia_bin = ["julia", f"+{julia_version}"] if julia_version else ["julia"]
    cmds = [f'Pkg.activate("{calkit.julia.escape_string(env_dir)}")']
    if add:
        pkg_list = "[" + ", ".join(f'"{p}"' for p in add) + "]"
        cmds.append(f"Pkg.add({pkg_list})")
    if remove:
        pkg_list = "[" + ", ".join(f'"{p}"' for p in remove) + "]"
        cmds.append(f"Pkg.rm({pkg_list})")
    if add or remove:
        cmd = julia_bin + [
            f"--project={env_dir}",
            "-e",
            "using Pkg; " + "; ".join(cmds),
        ]
        res = subprocess.run(cmd)
        if res.returncode != 0:
            raise_error("Failed to update Julia environment")
    typer.echo(f"Updated Julia environment '{env_name}'")
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
        already = any(
            isinstance(d, str) and (d == pkg or d.startswith(pkg + "="))
            for d in deps
        )
        if not already:
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
            already = any(
                p == pkg or p.startswith(pkg + "==") or p.startswith(pkg + "=")
                for p in pip_list
            )
            if not already:
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
    registry: Annotated[
        str | None,
        typer.Option(
            "--registry",
            help=(
                "Registry prefix to push images to and pull them from, or "
                "'ghcr.io' for the project's own namespace in the GitHub "
                "Container Registry, or 'none' to keep images local."
            ),
        ),
    ] = None,
    lock: Annotated[
        bool,
        typer.Option(
            "--lock",
            help=(
                "Rebuild or repull the image and write fresh lock files for "
                "every architecture."
            ),
        ),
    ] = False,
) -> None:
    """Update a docker environment."""
    from calkit.environments import (
        get_all_docker_lock_fpaths,
        get_env_lock_fpath,
    )

    ck_info, env = _load_env(env_name)
    if env.get("kind") != "docker":
        raise_error(f"Environment '{env_name}' is not a docker environment")
    if image is None and registry is None and not lock:
        raise_error(
            "No updates specified. Use --image, --registry, or --lock."
        )
    if image is not None:
        env["image"] = image
    if registry is not None:
        if registry.lower() in ["none", "false"]:
            # A shell can't pass YAML's null, so this is how it's asked for,
            # but what belongs in calkit.yaml is the null itself
            env["registry"] = None
        else:
            env["registry"] = registry
    if image is not None or registry is not None:
        calkit.save_calkit_info(ck_info)
        typer.echo(f"Updated docker environment '{env_name}'")
    if not lock:
        return
    # Relocking throws away the existing lock files so the image is fetched or
    # rebuilt from the environment's spec, which is the only way to pick up an
    # image whose tag has been moved out from under a recorded digest
    for lock_fpath in get_all_docker_lock_fpaths(env_name=env_name):
        if os.path.isfile(lock_fpath):
            typer.echo(f"Removing lock file: {lock_fpath}")
            os.remove(lock_fpath)
    legacy_lock_fpath = get_env_lock_fpath(
        env=env, env_name=env_name, as_posix=False, legacy=True
    )
    if legacy_lock_fpath is not None and os.path.isfile(legacy_lock_fpath):
        os.remove(legacy_lock_fpath)
    from calkit.cli.check import check_environment

    typer.echo(f"Relocking docker environment '{env_name}'")
    check_environment(env_name=env_name, verbose=True)


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
    max_concurrent_jobs: Annotated[
        int | None,
        typer.Option(
            "--max-concurrent-jobs",
            help=(
                "Maximum number of this project's jobs allowed in the queue "
                "at once, or 0 to remove the limit."
            ),
        ),
    ] = None,
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
    if max_concurrent_jobs is not None:
        if max_concurrent_jobs < 0:
            raise_error("--max-concurrent-jobs cannot be negative")
        # 0 is the way to clear the limit, since omitting the option means
        # "leave it alone" rather than "unlimited".
        if max_concurrent_jobs == 0:
            env.pop("max_concurrent_jobs", None)
        else:
            env["max_concurrent_jobs"] = max_concurrent_jobs
    calkit.save_calkit_info(ck_info)
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
        typer.Option(
            "--add",
            "--add-package",
            help=(
                "Package to add to the environment. Repeat the flag for "
                "multiple packages."
            ),
        ),
    ] = None,
) -> None:
    """Update an environment.

    Currently supports adding packages to Julia and Nix (flake) envs.
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
    assert isinstance(add_packages, list)
    kind = env.get("kind")
    if kind == "julia":
        # Adding to a Julia env is just a Pkg.add call inside the env.
        add_packages_str = ", ".join(
            [f'"{pkg.strip()}"' for pkg in add_packages]
        )
        julia_cmd = ["-e", f"using Pkg; Pkg.add([{add_packages_str}])"]
        run_in_env(env_name=env_name, cmd=julia_cmd)
    elif kind == "nix":
        import platform as _platform
        import subprocess

        from calkit.environments import add_packages_to_nix_flake

        flake_path = env.get("path")
        if not flake_path or not os.path.isfile(flake_path):
            raise_error(
                f"Nix flake not found at '{flake_path}' for env '{env_name}'"
            )
        try:
            added = add_packages_to_nix_flake(flake_path, add_packages)
        except ValueError as e:
            raise_error(str(e))
        if not added:
            typer.echo(
                f"All requested packages are already in {flake_path}; "
                "nothing to do."
            )
            return
        typer.echo(f"Added to {flake_path}: {', '.join(added)}")
        # ``nix flake lock`` ignores files that aren't tracked by Git
        # when run inside a Git repo. Stage the modified flake first so
        # the lock step sees our edits even if the flake was previously
        # untracked.
        try:
            _repo_for_lock = calkit.git.get_repo()
        except calkit.git.InvalidGitRepositoryError:
            _repo_for_lock = None
        if _repo_for_lock is not None:
            _repo_for_lock.git.add(flake_path)
        # Best-effort lock refresh: skip with a warning when nix isn't on
        # PATH so the flake edit + commit still go through (e.g. on a
        # machine where the user only edits configs).
        env_dir = os.path.dirname(flake_path) or "."
        if shutil.which("nix") is None:
            if _platform.system() == "Windows":
                from calkit.cli import warn

                warn(
                    "Nix is not available natively on Windows; skipping "
                    "'nix flake lock'. Run Calkit inside WSL2 to refresh "
                    "flake.lock."
                )
            else:
                from calkit.cli import warn

                warn(
                    "The 'nix' command was not found; skipping "
                    "'nix flake lock'. Install it with "
                    "'calkit install nix' to refresh flake.lock."
                )
        else:
            res = subprocess.run(
                [
                    "nix",
                    "--extra-experimental-features",
                    "nix-command flakes",
                    "flake",
                    "lock",
                ],
                cwd=env_dir,
            )
            if res.returncode != 0:
                raise_error("Failed to refresh flake.lock")
        # Commit the updated flake + lock so the change is captured.
        repo = calkit.git.get_repo()
        repo.git.add(flake_path)
        lock_path = os.path.join(env_dir, "flake.lock")
        if os.path.exists(lock_path):
            repo.git.add(lock_path)
        if repo.git.diff("--staged"):
            repo.git.commit(
                [
                    "-m",
                    f"Add {', '.join(added)} to nix env {env_name}",
                ]
            )
    else:
        raise_error(
            "Adding packages is currently supported only for "
            "julia and nix environments"
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
    set_outputs: Annotated[
        list[str],
        typer.Option(
            "--set-outputs",
            help="Replace DVC outputs list (paths only, storage=dvc).",
        ),
    ] = [],
    set_outputs_git: Annotated[
        list[str],
        typer.Option(
            "--set-outputs-git",
            help="Replace Git-tracked outputs list.",
        ),
    ] = [],
    add_output: Annotated[
        list[str],
        typer.Option("--add-output", help="Add a DVC-tracked output path."),
    ] = [],
    rm_output: Annotated[
        list[str],
        typer.Option("--rm-output", help="Remove an output path."),
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

    # Outputs — support both plain string (DVC) and {path, storage} dict entries
    def _out_path(o) -> str:
        return o["path"] if isinstance(o, dict) else o

    if set_outputs or set_outputs_git:
        # Full replacement: rebuild from both lists
        dvc_paths = [o for o in set_outputs if o]
        git_paths = [o for o in set_outputs_git if o]
        outputs_list: list = list(dvc_paths)
        for p in git_paths:
            outputs_list.append({"path": p, "storage": "git"})
    else:
        existing = list(stage.get("outputs") or [])
        rm_set = set(rm_output)
        outputs_list = [o for o in existing if _out_path(o) not in rm_set]
        existing_paths = {_out_path(o) for o in outputs_list}
        for o in add_output:
            if o not in existing_paths:
                outputs_list.append(o)
    if outputs_list:
        stage["outputs"] = outputs_list
    elif "outputs" in stage:
        del stage["outputs"]
    calkit.save_calkit_info(ck_info)


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
    stage: Annotated[
        str | None,
        typer.Option(
            "--stage",
            help="Name of the pipeline stage that produces this figure.",
        ),
    ] = None,
) -> None:
    """Update a figure entry in calkit.yaml."""
    if imported_from_url is None and stage is None:
        raise_error("No updates specified.")
    ck_info = calkit.load_calkit_info()
    figures = ck_info.get("figures", [])
    for fig in figures:
        if fig.get("path") == path:
            if imported_from_url is not None:
                fig["imported_from"] = {"url": imported_from_url}
            if stage is not None:
                fig["stage"] = stage
            break
    else:
        entry: dict = {"path": path}
        if imported_from_url is not None:
            entry["imported_from"] = {"url": imported_from_url}
        if stage is not None:
            entry["stage"] = stage
        figures.append(entry)
        ck_info["figures"] = figures
    calkit.save_calkit_info(ck_info)


@update_app.command(name="dataset")
def update_dataset(
    path: Annotated[str, typer.Argument(help="Path to the dataset file.")],
    imported_from_url: Annotated[
        str | None,
        typer.Option(
            "--imported-from-url",
            help="URL the dataset was imported from.",
        ),
    ] = None,
    imported_from_doi: Annotated[
        str | None,
        typer.Option(
            "--imported-from-doi",
            help="DOI the dataset was imported from, e.g. 10.5281/zenodo.1.",
        ),
    ] = None,
    imported_from_git_url: Annotated[
        str | None,
        typer.Option(
            "--imported-from-git-url",
            help="Clone URL of the Git repo the dataset was imported from.",
        ),
    ] = None,
    imported_from_git_rev: Annotated[
        str | None,
        typer.Option(
            "--imported-from-git-rev",
            help=(
                "Commit hash it was taken from. A branch or tag isn't "
                "accepted, since it would move."
            ),
        ),
    ] = None,
    imported_from_git_path: Annotated[
        str | None,
        typer.Option(
            "--imported-from-git-path",
            help="Path within that repo, if it isn't the whole thing.",
        ),
    ] = None,
    imported_from_date: Annotated[
        datetime | None,
        typer.Option(
            "--imported-from-date",
            formats=["%Y-%m-%d"],
            help="Date it was downloaded, as YYYY-MM-DD.",
        ),
    ] = None,
    stage: Annotated[
        str | None,
        typer.Option(
            "--stage",
            help="Name of the pipeline stage that produces this dataset.",
        ),
    ] = None,
) -> None:
    """Update a dataset entry in calkit.yaml."""
    from pydantic import ValidationError

    from calkit.models.core import (
        Dataset,
        _GitSource,
        _ImportedFromDoi,
        _ImportedFromGit,
        _ImportedFromUrl,
    )

    # One source, since the entry records where the data came from rather
    # than every place it could be found
    source_options = {
        "--imported-from-url": imported_from_url,
        "--imported-from-doi": imported_from_doi,
        "--imported-from-git-url": imported_from_git_url,
    }
    sources_given = [k for k, v in source_options.items() if v is not None]
    if len(sources_given) > 1:
        raise_error("Specify only one of " + ", ".join(source_options) + ".")
    if not sources_given and (
        imported_from_git_rev is not None
        or imported_from_git_path is not None
        or imported_from_date is not None
    ):
        raise_error(
            "--imported-from-git-rev, --imported-from-git-path, and "
            "--imported-from-date go with one of "
            + ", ".join(source_options)
            + "."
        )
    if not sources_given and stage is None:
        raise_error("No updates specified.")
    imported_from: dict | None = None
    if sources_given:
        date = imported_from_date.date() if imported_from_date else None
        try:
            source: _ImportedFromUrl | _ImportedFromDoi | _ImportedFromGit
            if imported_from_url is not None:
                source = _ImportedFromUrl(url=imported_from_url, date=date)
            elif imported_from_doi is not None:
                source = _ImportedFromDoi(doi=imported_from_doi, date=date)
            else:
                if imported_from_git_rev is None:
                    raise_error(
                        "--imported-from-git-rev is required with "
                        "--imported-from-git-url."
                    )
                source = _ImportedFromGit(
                    git=_GitSource(
                        repo_url=calkit.normalize_git_url(
                            imported_from_git_url or ""
                        ),
                        rev=imported_from_git_rev,
                        path=imported_from_git_path,
                    ),
                    date=date,
                )
        except ValidationError as e:
            raise_error(
                "Invalid import source: "
                + "; ".join(str(err["msg"]) for err in e.errors())
            )
        imported_from = source.model_dump(exclude_none=True)
    ck_info = calkit.load_calkit_info()
    datasets = ck_info.get("datasets", [])
    for ds in datasets:
        if ds.get("path") == path:
            break
    else:
        ds = {"path": path}
        datasets.append(ds)
        ck_info["datasets"] = datasets
    if imported_from is not None:
        ds["imported_from"] = imported_from
    if stage is not None:
        ds["stage"] = stage
    # Checked as a whole, so an import added to a dataset someone collected
    # is refused here rather than left for the next validation to find
    try:
        Dataset.model_validate(ds)
    except ValidationError as e:
        raise_error(
            "Invalid dataset: "
            + "; ".join(str(err["msg"]) for err in e.errors())
        )
    calkit.save_calkit_info(ck_info)


@update_app.command(name="path")
def update_path(
    path: Annotated[
        str,
        typer.Argument(help="Path of the imported file to refresh."),
    ],
    git_ref: Annotated[
        str | None,
        typer.Option(
            "--git-ref",
            help=(
                "Branch, tag, or commit to follow from now on, for a file "
                "imported from a Git repo. Recorded, so later refreshes "
                "keep using it."
            ),
        ),
    ] = None,
    no_commit: Annotated[
        bool,
        typer.Option("--no-commit", help="Do not commit changes to repo."),
    ] = False,
) -> None:
    """Re-fetch an imported file from where it came from.

    For a Git source this takes the latest on whatever the entry follows,
    which is its 'ref' if it names one and the repo's default branch
    otherwise, and records the commit it lands on. '--git-ref' changes
    what it follows, from then on and not just this once, so switching to
    a tag pins the import to that tag rather than quietly reverting to the
    default branch next time.

    This is a one-way copy from the source, not a merge: local changes to
    the file are discarded. An import records that a file came from
    somewhere else, so a local edit that survived a refresh would make the
    entry a lie about what is on disk.

    An entry that has no 'rev' yet is refreshed the same way, which is how
    one written by hand gets its commit recorded: 'rev' is required, and
    this is what fills it in.
    """
    from calkit.provenance import describe_source, find_artifact

    ck_info = calkit.load_calkit_info()
    found = find_artifact(ck_info, path)
    if found is None:
        raise_error(
            f"Nothing recorded at '{path}'; 'calkit import path' is what "
            "records where a file came from"
        )
    kind, entry = found
    imported_from = entry.get("imported_from")
    if imported_from is None:
        raise_error(
            f"'{path}' is recorded in '{kind}' but doesn't say it was "
            "imported, so there is nowhere to refresh it from"
        )
    # A dataset brought in with 'calkit import dataset' is tracked by DVC,
    # and writing over the file would leave its .dvc file describing the
    # old one
    if os.path.isfile(path + ".dvc"):
        raise_error(
            f"'{path}' is tracked by DVC; re-import it with 'calkit import "
            "dataset' to refresh it"
        )
    if git_ref is not None:
        if "git" not in imported_from:
            raise_error(
                f"'{path}' was not imported from a Git repo, so there is no "
                "ref to follow"
            )
        imported_from["git"] = dict(imported_from["git"]) | {"ref": git_ref}
    typer.echo(f"Fetching {describe_source(imported_from)}")
    try:
        entry["imported_from"] = calkit.provenance.fetch(
            imported_from, dest_path=path
        )
    except ValueError as e:
        raise_error(str(e))
    calkit.save_calkit_info(ck_info)
    repo = calkit.git.get_repo()
    paths = [path, "calkit.yaml"]
    repo.git.add(paths)
    # Scoped to the paths this command touched, both to decide whether
    # anything changed and to commit. Reading the whole index would call an
    # unchanged file updated whenever something else happened to be staged,
    # and committing it would sweep that unrelated work into a commit
    # claiming to be about this file.
    if not repo.git.diff("--cached", "--name-only", "--", *paths):
        typer.echo(f"{path} is already up-to-date")
        return
    typer.echo(f"Updated {path}")
    if not no_commit:
        typer.echo("Committing changes")
        repo.git.commit(paths + ["-m", f"Update {path} from its source"])
