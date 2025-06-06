"""CLI for creating new objects."""

from __future__ import annotations

import csv
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile
from enum import Enum

import bibtexparser
import dotenv
import git
import requests
import typer
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError
from typing_extensions import Annotated

import calkit
from calkit.cli import raise_error, warn
from calkit.cli.update import update_devcontainer
from calkit.core import ryaml
from calkit.docker import LAYERS
from calkit.models.pipeline import LatexStage, StageIteration

new_app = typer.Typer(no_args_is_help=True)


@new_app.command(name="project")
def new_project(
    path: Annotated[str, typer.Argument(help="Where to create the project.")],
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            "-n",
            help=(
                "Project name. Will be inferred as kebab-cased directory "
                "name if not provided."
            ),
        ),
    ] = None,
    title: Annotated[
        str | None, typer.Option("--title", help="Project title.")
    ] = None,
    description: Annotated[
        str | None, typer.Option("--description", help="Project description.")
    ] = None,
    cloud: Annotated[
        bool,
        typer.Option(
            "--cloud",
            help=("Create this project in the cloud (Calkit and GitHub.)"),
        ),
    ] = False,
    public: Annotated[
        bool,
        typer.Option(
            "--public",
            help="Create as a public project if --cloud is selected.",
        ),
    ] = False,
    git_repo_url: Annotated[
        str | None,
        typer.Option(
            "--git-url",
            help=(
                "Git repo URL. "
                "Usually https://github.com/{your_name}/{project_name}."
            ),
        ),
    ] = None,
    template: Annotated[
        str | None,
        typer.Option(
            "--template",
            "-t",
            help=(
                "Template from which to derive the project, e.g., "
                "'calkit/example-basic'."
            ),
        ),
    ] = None,
    no_commit: Annotated[
        bool | None,
        typer.Option("--no-commit", help="Do not commit changes to Git."),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Overwrite project if one already exists.",
        ),
    ] = False,
):
    """Create a new project."""
    docs_url = "https://docs.calkit.org"
    success_message = (
        "\nCongrats on creating your new Calkit project!\n\n"
        "Next, you'll probably want to start building your pipeline.\n\n"
        f"Check out the docs at {docs_url}."
    )
    abs_path = os.path.abspath(path)
    if template and os.path.exists(abs_path):
        raise_error("Must specify a new directory if using --template")
    try:
        repo = git.Repo(abs_path)
    except (InvalidGitRepositoryError, NoSuchPathError):
        repo = None
    if repo is not None and git_repo_url is None:
        try:
            git_repo_url = repo.remotes.origin.url
            # Convert to HTTPS if it's SSH
            if git_repo_url.startswith("git@"):
                git_repo_url = git_repo_url.replace(
                    "git@github.com:", "https://github.com/"
                )
            git_repo_url = git_repo_url.removesuffix(".git")
        except Exception as e:
            git_repo_url = None
            raise_error(
                f"Could not detect Git repo URL from existing repo: {e}"
            )
        # If this isn't a DVC repo, run `dvc init`
        if not os.path.isfile(os.path.join(abs_path, ".dvc", "config")):
            typer.echo("Initializing DVC repository")
            try:
                subprocess.run(
                    [sys.executable, "-m", "dvc", "init", "-q"],
                    cwd=abs_path,
                    capture_output=True,
                    check=True,
                    text=True,
                )
            except subprocess.CalledProcessError as e:
                raise_error(f"Failed to initialize DVC repository: {e.stderr}")
            # Commit the DVC init changes
            if not no_commit:
                repo.git.add(".dvc")
                repo.git.commit(["-m", "Initialize DVC"])
    ck_info_fpath = os.path.join(abs_path, "calkit.yaml")
    if os.path.isfile(ck_info_fpath) and not overwrite:
        raise_error(
            "Destination is already a Calkit project; "
            "use --overwrite to continue"
        )
    if os.path.isdir(abs_path) and os.listdir(abs_path) and repo is None:
        warn(f"{abs_path} is not empty")
    if name is None:
        name = calkit.to_kebab_case(os.path.basename(abs_path))
    if " " in name:
        warn("Invalid name; replacing spaces with hyphens")
        name = name.replace(" ", "-")
    typer.echo(f"Creating project {name}")
    if title is None:
        title = typer.prompt("Enter a title (ex: 'My research project')")
    typer.echo(f"Using title: {title}")
    if cloud:
        # Cloud should allow None, which will allow us to post just the name
        # NOTE: This will fail if the user hasn't logged into the Calkit Cloud
        # in 6 months, since their GitHub refresh token stored is expired
        typer.echo("Creating project in Calkit Cloud")
        try:
            resp = calkit.cloud.post(
                "/projects",
                json=dict(
                    name=name,
                    title=title,
                    description=description,
                    git_repo_url=git_repo_url,
                    is_public=public,
                    template=template,
                ),
            )
        except Exception as e:
            raise_error(f"Posting new project to cloud failed: {e}")
        # Now clone here
        if not os.path.isdir(abs_path):
            subprocess.run(["git", "clone", resp["git_repo_url"], abs_path])
        elif repo is None:
            typer.echo("Fetching from newly created Git repo")
            repo = git.Repo.init(abs_path, initial_branch="main")
            repo.git.remote(["add", "origin", resp["git_repo_url"]])
            repo.git.fetch()
            checkout_cmd = ["-t", "origin/main"]
            if overwrite:
                checkout_cmd.append("--force")
            try:
                repo.git.checkout(checkout_cmd)
            except GitCommandError as e:
                raise_error(f"Failed to check out main branch: {e}")
        else:
            # Create a calkit.yaml file if one does not exist
            calkit_fpath = os.path.join(abs_path, "calkit.yaml")
            if not os.path.isfile(calkit_fpath):
                typer.echo("Creating calkit.yaml file")
                with open(calkit_fpath, "w") as f:
                    ryaml.dump(
                        dict(
                            owner=resp["owner_account_name"],
                            name=resp["name"],
                            title=resp["title"],
                            description=resp["description"],
                            git_repo_url=resp["git_repo_url"],
                        ),
                        f,
                    )
                repo.git.add("calkit.yaml")
                if not no_commit:
                    repo.git.commit(["-m", "Create calkit.yaml"])
        try:
            calkit.dvc.set_remote_auth(wdir=abs_path)
        except Exception:
            warn("Failed to setup Calkit DVC remote auth")
        prj = calkit.detect_project_name(wdir=abs_path)
        add_msg = f"\n\nYou can view your project at https://calkit.io/{prj}"
        typer.echo(success_message + add_msg)
        return
    # If using a template, clone it first
    if template:
        # TODO: If the template is not a Git repo URL, make a request to the
        # Calkit Cloud to get it?
        # For now, assume consistency between Calkit Cloud projects and
        # GitHub repo URLs
        if "github.com" in template:
            template_git_url = template
            template_name = template.split("github.com")[-1][1:].removesuffix(
                ".git"
            )
        else:
            template_name = template
            template_git_url = f"https://github.com/{template}"
        # Now clone it
        subprocess.run(["git", "clone", template_git_url, abs_path])
        # Templates should always have DVC initialized, so no need to do that
        repo = git.Repo(abs_path)
        git_rev = repo.git.rev_parse("HEAD")
        # Rename origin remote as upstream
        typer.echo("Renaming template remote as upstream")
        repo.git.remote(["rename", "origin", "upstream"])
        # Set git repo URL if provided
        if git_repo_url:
            typer.echo("Setting origin remote URL")
            repo.git.remote(["add", "origin", git_repo_url])
        # Update Calkit info in this project
        ck_info = calkit.load_calkit_info(wdir=abs_path)
        ck_info = ck_info | dict(
            name=name,
            title=title,
            description=description,
            git_repo_url=git_repo_url,
            derived_from=dict(
                project=template_name,
                git_repo_url=template_git_url,
                git_rev=git_rev,
            ),
        )
        # Remove questions and owner if they're there
        _ = ck_info.pop("questions", None)
        _ = ck_info.pop("owner", None)
        # Write Calkit info
        with open(os.path.join(abs_path, "calkit.yaml"), "w") as f:
            ryaml.dump(ck_info, f)
        # Update README
        readme_fpath = os.path.join(abs_path, "README.md")
        typer.echo("Generating README.md")
        readme_txt = calkit.make_readme_content(
            project_name=name,
            project_title=title,
            project_description=description,
        )
        with open(readme_fpath, "w") as f:
            f.write(readme_txt)
        # Update DVC remote
        # TODO: This will fail because we don't know this user's account name
        typer.echo("Updating Calkit DVC remote")
        try:
            calkit.dvc.configure_remote(wdir=abs_path)
        except ValueError:
            warn(
                "Could not update Calkit DVC remote since "
                "no Git repo URL was provided"
            )
            warn(
                "You will need to manually run `git remote add origin` "
                "and `calkit config remote`"
            )
            subprocess.call(
                [
                    sys.executable,
                    "-m",
                    "dvc",
                    "remote",
                    "remove",
                    "calkit",
                    "-q",
                ],
                cwd=abs_path,
            )
        try:
            calkit.dvc.set_remote_auth(wdir=abs_path)
        except Exception:
            warn("Could not set authentication for Calkit DVC remote")
        # Commit this stuff to Git
        repo.git.add(".")
        if repo.git.diff("--staged"):
            repo.git.commit(["-m", f"Create new project from {template_name}"])
        typer.echo(success_message)
        return
    os.makedirs(abs_path, exist_ok=True)
    try:
        repo = git.Repo(abs_path)
    except InvalidGitRepositoryError:
        typer.echo("Initializing Git repository")
        subprocess.run(["git", "init", "-q"], cwd=abs_path)
    repo = git.Repo(abs_path)
    if not os.path.isfile(os.path.join(abs_path, ".dvc", "config")):
        typer.echo("Initializing DVC repository")
        subprocess.run(
            [sys.executable, "-m", "dvc", "init", "-q"], cwd=abs_path
        )
    # Create calkit.yaml file
    ck_info = calkit.load_calkit_info(wdir=abs_path)
    ck_info = dict(name=name, title=title, description=description) | ck_info
    with open(os.path.join(abs_path, "calkit.yaml"), "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    # Create dev container spec
    update_devcontainer(wdir=abs_path)
    repo.git.add(".devcontainer")
    # Create README
    readme_fpath = os.path.join(abs_path, "README.md")
    if os.path.isfile(readme_fpath) and not overwrite:
        warn("README.md already exists; not modifying")
    else:
        typer.echo("Generating README.md")
        readme_txt = calkit.make_readme_content(
            project_name=name,
            project_title=title,
            project_description=description,
        )
        with open(readme_fpath, "w") as f:
            f.write(readme_txt)
        repo.git.add("README.md")
    if git_repo_url and not repo.remotes:
        typer.echo(f"Adding Git remote {git_repo_url}")
        repo.git.remote(["add", "origin", git_repo_url])
    elif not git_repo_url and not repo.remotes:
        warn("No Git remotes are configured")
    # Setup Calkit Cloud DVC remote
    if repo.remotes:
        typer.echo("Setting up Calkit Cloud DVC remote")
        try:
            calkit.dvc.configure_remote(wdir=abs_path)
            calkit.dvc.set_remote_auth(wdir=abs_path)
        except Exception as e:
            warn(f"Failed to set up Calkit Cloud DVC remote: {e}")
    if repo.git.diff("--staged") and not no_commit:
        repo.git.commit(["-m", "Initialize Calkit project"])
    typer.echo(success_message)


@new_app.command(name="figure")
def new_figure(
    path: str,
    title: Annotated[str, typer.Option("--title")],
    description: Annotated[str, typer.Option("--description")],
    stage_name: Annotated[
        str,
        typer.Option(
            "--stage",
            help="Name of the pipeline stage that generates this figure.",
        ),
    ] = None,
    cmd: Annotated[
        str,
        typer.Option(
            "--cmd", help="Command to add to the stage, if specified."
        ),
    ] = None,
    deps: Annotated[
        list[str], typer.Option("--dep", help="Path to stage dependency.")
    ] = [],
    outs: Annotated[
        list[str],
        typer.Option(
            "--out",
            help=(
                "Path to stage output. "
                "Figure path will be added automatically."
            ),
        ),
    ] = [],
    outs_from_stage: Annotated[
        str,
        typer.Option(
            "--deps-from-stage-outs",
            help="Stage name from which to add outputs as dependencies.",
        ),
    ] = None,
    no_commit: Annotated[bool, typer.Option("--no-commit")] = False,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Overwrite existing figure if one exists.",
        ),
    ] = False,
):
    """Create a new figure."""
    ck_info = calkit.load_calkit_info()
    figures = ck_info.get("figures", [])
    paths = [f.get("path") for f in figures]
    if not overwrite and path in paths:
        raise_error(f"Figure at path {path} already exists")
    elif overwrite and path in paths:
        figures = [fig for fig in figures if fig.get("path") != path]
    if cmd is not None and stage_name is None:
        raise_error("Stage name must be provided if command is specified")
    if (deps or outs or outs_from_stage) and not cmd:
        raise_error("Command must be provided")
    if (deps or outs or outs_from_stage) and not stage_name:
        raise_error("Stage name must be provided")
    obj = dict(path=path, title=title)
    if description is not None:
        obj["description"] = description
    if stage_name is not None:
        obj["stage"] = stage_name
    if cmd:
        if outs_from_stage:
            pipeline = calkit.dvc.read_pipeline()
            stages = pipeline.get("stages", {})
            if outs_from_stage not in stages:
                raise_error(f"Stage {outs_from_stage} does not exist")
            stage = stages[outs_from_stage]
            if "foreach" in stage:
                for val in stage["foreach"]:
                    for out in stage.get("do", {}).get("outs", []):
                        deps.append(out.replace("${item}", val))
            else:
                deps += stage.get("outs", [])
        if path not in outs:
            outs.append(path)
        deps_cmd = []
        for dep in deps:
            deps_cmd += ["-d", dep]
        outs_cmd = []
        for out in outs:
            outs_cmd += ["-o", out]
        subprocess.check_call(
            [sys.executable, "-m", "dvc", "stage", "add", "-n", stage_name]
            + (["-f"] if overwrite else [])
            + deps_cmd
            + outs_cmd
            + [cmd]
        )
    figures.append(obj)
    ck_info["figures"] = figures
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    if not no_commit:
        repo = git.Repo()
        repo.git.add("calkit.yaml")
        if cmd:
            repo.git.add("dvc.yaml")
        if repo.git.diff("--staged"):
            repo.git.commit(["-m", f"Add figure {path}"])


@new_app.command("question")
def new_question(
    question: str,
    commit: Annotated[bool, typer.Option("--commit")] = False,
):
    """Add a new question."""
    ck_info = calkit.load_calkit_info()
    questions = ck_info.get("questions", [])
    if question in questions:
        raise ValueError("Question already exists")
    if not question.endswith("?"):
        raise ValueError("Questions must end with a question mark")
    questions.append(question)
    ck_info["questions"] = questions
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    if commit:
        repo = git.Repo()
        repo.git.add("calkit.yaml")
        repo.git.commit(["-m", "Add question"])


@new_app.command("notebook")
def new_notebook(
    path: Annotated[str, typer.Argument(help="Notebook path (relative)")],
    title: Annotated[str, typer.Option("--title")],
    description: Annotated[str, typer.Option("--description")] = None,
    commit: Annotated[bool, typer.Option("--commit")] = False,
):
    """Add a new notebook."""
    if os.path.isabs(path):
        raise ValueError("Path must be relative")
    if not os.path.isfile(path):
        raise ValueError("Path is not a file")
    if not path.endswith(".ipynb"):
        raise ValueError("Path does not have .ipynb extension")
    # TODO: Add option to create stages that run `calkit nb clean` and
    # `calkit nb execute`
    ck_info = calkit.load_calkit_info()
    notebooks = ck_info.get("notebooks", [])
    paths = [f.get("path") for f in notebooks]
    if path in paths:
        raise ValueError(f"Notebook at path {path} already exists")
    obj = dict(path=path, title=title)
    if description is not None:
        obj["description"] = description
    notebooks.append(obj)
    ck_info["notebooks"] = notebooks
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    if commit:
        repo = git.Repo()
        repo.git.add("calkit.yaml")
        repo.git.commit(["-m", f"Add notebook {path}"])


@new_app.command("docker-env")
def new_docker_env(
    name: Annotated[
        str, typer.Option("--name", "-n", help="Environment name.")
    ],
    image_name: Annotated[
        str | None,
        typer.Option(
            "--image",
            help=(
                "Image identifier. Should be unique and descriptive. "
                "Will default to environment name if not specified."
            ),
        ),
    ] = None,
    base: Annotated[
        str | None,
        typer.Option(
            "--from",
            help="Base image, e.g., 'ubuntu', if creating a Dockerfile.",
        ),
    ] = None,
    path: Annotated[
        str | None,
        typer.Option(
            "--path",
            help=(
                "Dockerfile path. Will default to 'Dockerfile' "
                "if --from is specified."
            ),
        ),
    ] = None,
    layers: Annotated[
        list[str],
        typer.Option(
            "--add-layer", help="Add a layer (options: miniforge, foampy)."
        ),
    ] = [],
    wdir: Annotated[
        str, typer.Option("--wdir", help="Working directory.")
    ] = "/work",
    user: Annotated[
        str | None,
        typer.Option(
            "--user", help="User account to use to run the container."
        ),
    ] = None,
    platform: Annotated[
        str | None,
        typer.Option("--platform", help="Which platform(s) to build for."),
    ] = None,
    description: Annotated[
        str | None, typer.Option("--description", help="Description.")
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Overwrite any existing environment with this name.",
        ),
    ] = False,
    no_commit: Annotated[
        bool, typer.Option("--no-commit", help="Do not commit changes.")
    ] = False,
):
    """Create a new Docker environment."""
    if base is not None and path is None:
        path = "Dockerfile"
    if path is not None and base and os.path.isfile(path) and not overwrite:
        raise_error("Output path already exists (use -f to overwrite)")
    if image_name is None:
        typer.echo("No image name specified; using environment name")
        image_name = name
    repo = git.Repo()
    if base and path is not None:
        txt = "FROM " + base + "\n\n"
        for layer in layers:
            if layer not in LAYERS:
                raise_error(f"Unknown layer type '{layer}'")
            txt += LAYERS[layer] + "\n\n"
        txt += f"RUN mkdir {wdir}\n"
        txt += f"WORKDIR {wdir}\n"
        with open(path, "w") as f:
            f.write(txt)
    # Add environment to Calkit info
    ck_info = calkit.load_calkit_info()
    # If environments is a list instead of a dict, reformulate it
    envs = ck_info.get("environments", {})
    if isinstance(envs, list):
        typer.echo("Converting environments from list to dict")
        envs = {env.pop("name"): env for env in envs}
    if name in envs and not overwrite:
        raise_error(
            f"Environment with name {name} already exists "
            "(use -f to overwrite)"
        )
    if base:
        repo.git.add(path)
    typer.echo("Adding environment to calkit.yaml")
    env = dict(
        kind="docker",
        image=image_name,
        wdir=wdir,
    )
    if base is not None or path is not None:
        env["path"] = path
    if description is not None:
        env["description"] = description
    if layers:
        env["layers"] = layers
    if platform:
        env["platform"] = platform
    if user:
        env["user"] = user
    envs[name] = env
    ck_info["environments"] = envs
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    if not no_commit and repo.git.diff("--staged"):
        repo.git.commit(["-m", f"Add Docker environment {name}"])


@new_app.command(name="foreach-stage")
def new_foreach_stage(
    cmd: Annotated[
        str,
        typer.Option(
            "--cmd",
            help="Command to run. Can include {var} to fill with variable.",
        ),
    ],
    name: Annotated[str, typer.Option("--name", "-n", help="Stage name.")],
    vals: Annotated[list[str], typer.Argument(help="Values to iterate over")],
    deps: Annotated[
        list[str], typer.Option("--dep", help="Path to add as a dependency.")
    ] = [],
    outs: Annotated[
        list[str], typer.Option("--out", help="Path to add as an output.")
    ] = [],
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite", "-f", help="Overwrite stage if one already exists."
        ),
    ] = False,
    no_commit: Annotated[
        bool, typer.Option("--no-commit", help="Do not commit changes.")
    ] = False,
):
    """Create a new DVC 'foreach' stage.

    The list of values must be a simple list. For more complex objects,
    edit dvc.yaml directly.
    """
    pipeline = calkit.dvc.read_pipeline()
    if name in pipeline and not overwrite:
        raise_error("Stage already exists; use -f to overwrite")
    if "stages" not in pipeline:
        pipeline["stages"] = {}
    pipeline["stages"][name] = dict(
        foreach=vals,
        do=dict(
            cmd=cmd.replace("{var}", "${item}"),
            outs=[out.replace("{var}", "${item}") for out in outs],
            deps=[dep.replace("{var}", "${item}") for dep in deps],
        ),
    )
    with open("dvc.yaml", "w") as f:
        calkit.ryaml.dump(pipeline, f)
    repo = git.Repo()
    repo.git.add("dvc.yaml")
    if not no_commit and repo.git.diff("--staged"):
        repo.git.commit(["-m", f"Add foreach stage {name}"])


@new_app.command(name="dataset")
def new_dataset(
    path: str,
    title: Annotated[str, typer.Option("--title")],
    description: Annotated[str, typer.Option("--description")],
    stage_name: Annotated[
        str,
        typer.Option(
            "--stage",
            help="Name of the pipeline stage that generates this dataset.",
        ),
    ] = None,
    cmd: Annotated[
        str,
        typer.Option(
            "--cmd", help="Command to add to the stage, if specified."
        ),
    ] = None,
    deps: Annotated[
        list[str], typer.Option("--dep", help="Path to stage dependency.")
    ] = [],
    outs: Annotated[
        list[str],
        typer.Option(
            "--out",
            help=(
                "Path to stage output. "
                "Dataset path will be added automatically."
            ),
        ),
    ] = [],
    outs_from_stage: Annotated[
        str,
        typer.Option(
            "--deps-from-stage-outs",
            help="Stage name from which to add outputs as dependencies.",
        ),
    ] = None,
    no_commit: Annotated[bool, typer.Option("--no-commit")] = False,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Overwrite existing dataset if one exists.",
        ),
    ] = False,
):
    """Create a new dataset."""
    ck_info = calkit.load_calkit_info()
    datasets = ck_info.get("datasets", [])
    paths = [f.get("path") for f in datasets]
    if not overwrite and path in paths:
        raise_error(f"Dataset at path {path} already exists")
    elif overwrite and path in paths:
        datasets = [fig for fig in datasets if fig.get("path") != path]
    if cmd is not None and stage_name is None:
        raise_error("Stage name must be provided if command is specified")
    if (deps or outs or outs_from_stage) and not cmd:
        raise_error("Command must be provided")
    if (deps or outs or outs_from_stage) and not stage_name:
        raise_error("Stage name must be provided")
    obj = dict(path=path, title=title)
    if description is not None:
        obj["description"] = description
    if stage_name is not None:
        obj["stage"] = stage_name
    if cmd:
        if outs_from_stage:
            pipeline = calkit.dvc.read_pipeline()
            stages = pipeline.get("stages", {})
            if outs_from_stage not in stages:
                raise_error(f"Stage {outs_from_stage} does not exist")
            stage = stages[outs_from_stage]
            if "foreach" in stage:
                for val in stage["foreach"]:
                    for out in stage.get("do", {}).get("outs", []):
                        deps.append(out.replace("${item}", val))
            else:
                deps += stage.get("outs", [])
        if path not in outs:
            outs.append(path)
        deps_cmd = []
        for dep in deps:
            deps_cmd += ["-d", dep]
        outs_cmd = []
        for out in outs:
            outs_cmd += ["-o", out]
        subprocess.check_call(
            [sys.executable, "-m", "dvc", "stage", "add", "-n", stage_name]
            + (["-f"] if overwrite else [])
            + deps_cmd
            + outs_cmd
            + [cmd]
        )
    datasets.append(obj)
    ck_info["datasets"] = datasets
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    if not no_commit:
        repo = git.Repo()
        repo.git.add("calkit.yaml")
        if cmd:
            repo.git.add("dvc.yaml")
        if repo.git.diff("--staged"):
            repo.git.commit(["-m", f"Add dataset {path}"])


@new_app.command(name="publication", help="Create a new publication.")
def new_publication(
    path: Annotated[
        str,
        typer.Argument(
            help=(
                "Path for the publication. "
                "If using a template, this could be a directory."
            )
        ),
    ],
    title: Annotated[
        str, typer.Option("--title", help="The title of the publication.")
    ],
    description: Annotated[
        str,
        typer.Option(
            "--description", help="A description of the publication."
        ),
    ],
    kind: Annotated[
        str,
        typer.Option(
            "--kind", help="Kind of the publication, e.g., 'journal-article'."
        ),
    ],
    stage_name: Annotated[
        str | None,
        typer.Option(
            "--stage",
            help="Name of the pipeline stage to build the output file.",
        ),
    ] = None,
    deps: Annotated[
        list[str], typer.Option("--dep", help="Path to stage dependency.")
    ] = [],
    outs_from_stage: Annotated[
        str | None,
        typer.Option(
            "--deps-from-stage-outs",
            help="Stage name from which to add outputs as dependencies.",
        ),
    ] = None,
    template: Annotated[
        str | None,
        typer.Option(
            "--template",
            "-t",
            help=(
                "Template with which to create the source files. "
                "Should be in the format {type}/{name}."
            ),
        ),
    ] = None,
    env_name: Annotated[
        str | None,
        typer.Option(
            "--environment",
            help="Name of the build environment to create, if desired.",
        ),
    ] = None,
    no_commit: Annotated[
        bool,
        typer.Option(
            "--no-commit", help="Do not commit resulting changes to the repo."
        ),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Overwrite existing objects if they already exist.",
        ),
    ] = False,
) -> None:
    ck_info = calkit.load_calkit_info(process_includes=False)
    pubs = ck_info.get("publications", [])
    envs = ck_info.get("environments", {})
    pub_paths = [p.get("path") for p in pubs]
    if template is not None:
        template_type, _ = template.split("/")
    else:
        template_type = None
    # Check all of our inputs
    if template_type is not None and template_type not in ["latex"]:
        raise_error(f"Unknown template type '{template_type}'")
    if env_name is not None and template_type != "latex":
        raise_error("Environments can only be created for latex templates")
    if env_name is not None and env_name in envs and not overwrite:
        typer.echo(
            typer.style(
                f"Environment '{env_name}' already exists; overwriting",
                fg="yellow",
            )
        )
    if template_type is not None:
        try:
            template_obj = calkit.templates.get_template(template)
        except ValueError:
            raise_error(f"Template '{template}' does not exist")
    # Parse outs from stage if specified
    if outs_from_stage:
        pipeline = calkit.dvc.read_pipeline()
        stages = pipeline.get("stages", {})
        if outs_from_stage not in stages:
            raise_error(f"Stage {outs_from_stage} does not exist")
        stage = stages[outs_from_stage]
        if "foreach" in stage:
            for val in stage["foreach"]:
                for out in stage.get("do", {}).get("outs", []):
                    deps.append(out.replace("${item}", val))
        else:
            deps += stage.get("outs", [])
    # Create publication object
    if template_type == "latex":
        pub_fpath = os.path.join(
            path, template_obj.target.removesuffix(".tex") + ".pdf"
        )
    else:
        pub_fpath = path
    if not overwrite and pub_fpath in pub_paths:
        raise_error(f"Publication with path {pub_fpath} already exists")
    elif overwrite and pub_fpath in pub_paths:
        pubs = [p for p in pubs if p.get("path") != pub_fpath]
    pub = dict(
        path=pathlib.Path(pub_fpath).as_posix(),
        kind=kind,
        title=title,
        description=description,
        stage=stage_name,
    )
    pubs.append(pub)
    ck_info["publications"] = pubs
    repo = git.Repo()
    # Create environment if applicable
    if env_name is not None and template_type == "latex":
        env = dict(
            kind="docker",
            image="texlive/texlive:latest-full",
            description="TeXlive full.",
        )
        envs[env_name] = env
        ck_info["environments"] = envs
    # Create stage if applicable
    if (
        stage_name is not None
        and template_type == "latex"
        and env_name is not None
    ):
        stage = LatexStage(
            kind="latex",
            environment=env_name,
            target_path=os.path.join(path, template_obj.target),
            outputs=[pub_fpath],
        ).model_dump()
        if "pipeline" not in ck_info:
            ck_info["pipeline"] = {}
        if "stages" not in ck_info["pipeline"]:
            ck_info["pipeline"]["stages"] = {}
        ck_info["pipeline"]["stages"][stage_name] = stage
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    # Copy in template files if applicable
    if template_type == "latex":
        if overwrite and os.path.exists(path):
            shutil.rmtree(path)
        calkit.templates.use_template(
            name=template, dest_dir=path, title=title
        )
        repo.git.add(path)
    if not no_commit and repo.git.diff("--staged"):
        repo.git.commit(["-m", f"Add new publication {pub_fpath}"])


@new_app.command("conda-env")
def new_conda_env(
    packages: Annotated[
        list[str],
        typer.Argument(help="Packages to include in the environment."),
    ],
    name: Annotated[
        str, typer.Option("--name", "-n", help="Environment name.")
    ],
    conda_name: Annotated[
        str,
        typer.Option(
            "--conda-name",
            help=(
                "Name to use in the Conda environment file, if desired. "
                "Will be automatically generated if not provided. "
                "Note that these should be unique since Conda environments are "
                "a system-wide collection."
            ),
        ),
    ] = None,
    path: Annotated[
        str, typer.Option("--path", help="Environment YAML file path.")
    ] = "environment.yml",
    pip_packages: Annotated[
        list[str], typer.Option("--pip", help="Packages to install with pip.")
    ] = [],
    prefix: Annotated[
        str, typer.Option("--prefix", help="Prefix for environment location.")
    ] = None,
    description: Annotated[
        str, typer.Option("--description", help="Description.")
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Overwrite any existing environment with this name.",
        ),
    ] = False,
    no_commit: Annotated[
        bool, typer.Option("--no-commit", help="Do not commit changes.")
    ] = False,
):
    """Create a new Conda environment."""
    if os.path.isfile(path) and not overwrite:
        raise_error("Output path already exists (use -f to overwrite)")
    repo = git.Repo()
    # Add environment to Calkit info
    ck_info = calkit.load_calkit_info()
    # If environments is a list instead of a dict, reformulate it
    envs = ck_info.get("environments", {})
    if isinstance(envs, list):
        typer.echo("Converting environments from list to dict")
        envs = {env.pop("name"): env for env in envs}
    if name in envs and not overwrite:
        raise_error(
            f"Environment with name {name} already exists "
            "(use -f to overwrite)"
        )
    if conda_name is None:
        project_name = ck_info.get("name")
        if project_name is None:
            project_name = os.path.basename(os.getcwd())
        conda_name = calkit.to_kebab_case(project_name) + "-" + name
    # Write environment to path
    conda_env = dict(
        name=conda_name, channels=["conda-forge"], dependencies=packages
    )
    if prefix is not None:
        from calkit.cli.main import ignore

        conda_env["prefix"] = prefix
        ignore(prefix, no_commit=True)
        repo.git.add(".gitignore")
    if pip_packages:
        conda_env["dependencies"].append(dict(pip=pip_packages))
    with open(path, "w") as f:
        ryaml.dump(conda_env, f)
    repo.git.add(path)
    typer.echo("Adding environment to calkit.yaml")
    env = dict(path=path, kind="conda")
    if prefix is not None:
        env["prefix"] = prefix
    if description is not None:
        env["description"] = description
    envs[name] = env
    ck_info["environments"] = envs
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    if not no_commit and repo.git.diff("--staged"):
        repo.git.commit(["-m", f"Add Conda environment {name}"])


@new_app.command("uv-venv")
def new_uv_venv(
    packages: Annotated[
        list[str],
        typer.Argument(help="Packages to include in the environment."),
    ],
    name: Annotated[
        str, typer.Option("--name", "-n", help="Environment name.")
    ],
    path: Annotated[
        str, typer.Option("--path", help="Path for requirements file.")
    ] = "requirements.txt",
    prefix: Annotated[
        str, typer.Option("--prefix", help="Prefix for environment location.")
    ] = ".venv",
    python_version: Annotated[
        str, typer.Option("--python", "-p", help="Python version.")
    ] = None,
    description: Annotated[
        str, typer.Option("--description", help="Description.")
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Overwrite any existing environment with this name.",
        ),
    ] = False,
    no_commit: Annotated[
        bool, typer.Option("--no-commit", help="Do not commit changes.")
    ] = False,
):
    """Create a new uv virtual environment."""
    if os.path.isfile(path) and not overwrite:
        raise_error("Output path already exists (use -f to overwrite)")
    repo = git.Repo()
    # Add environment to Calkit info
    ck_info = calkit.load_calkit_info()
    # If environments is a list instead of a dict, reformulate it
    envs = ck_info.get("environments", {})
    if isinstance(envs, list):
        typer.echo("Converting environments from list to dict")
        envs = {env.pop("name"): env for env in envs}
    if name in envs and not overwrite:
        raise_error(
            f"Environment with name {name} already exists "
            "(use -f to overwrite)"
        )
    # Check prefixes
    if not overwrite:
        for env_name, env in envs.items():
            if env.get("prefix") == prefix:
                raise_error(
                    f"Environment '{env_name}' already exists with "
                    f"prefix '{prefix}'"
                )
    packages_txt = "\n".join(packages)
    # Write environment to path
    with open(path, "w") as f:
        f.write(packages_txt)
    repo.git.add(path)
    typer.echo("Adding environment to calkit.yaml")
    env = dict(path=path, kind="uv-venv", prefix=prefix)
    if python_version is not None:
        env["python"] = python_version
    if description is not None:
        env["description"] = description
    envs[name] = env
    ck_info["environments"] = envs
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    if not no_commit and repo.git.diff("--staged"):
        repo.git.commit(["-m", f"Add uv venv {name}"])


@new_app.command("venv")
def new_venv(
    packages: Annotated[
        list[str],
        typer.Argument(help="Packages to include in the environment."),
    ],
    name: Annotated[
        str, typer.Option("--name", "-n", help="Environment name.")
    ],
    path: Annotated[
        str, typer.Option("--path", help="Path for requirements file.")
    ] = "requirements.txt",
    prefix: Annotated[
        str, typer.Option("--prefix", help="Prefix for environment location.")
    ] = ".venv",
    description: Annotated[
        str, typer.Option("--description", help="Description.")
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Overwrite any existing environment with this name.",
        ),
    ] = False,
    no_commit: Annotated[
        bool, typer.Option("--no-commit", help="Do not commit changes.")
    ] = False,
):
    """Create a new Python virtual environment with venv."""
    if os.path.isfile(path) and not overwrite:
        raise_error("Output path already exists (use -f to overwrite)")
    repo = git.Repo()
    # Add environment to Calkit info
    ck_info = calkit.load_calkit_info()
    # If environments is a list instead of a dict, reformulate it
    envs = ck_info.get("environments", {})
    if isinstance(envs, list):
        typer.echo("Converting environments from list to dict")
        envs = {env.pop("name"): env for env in envs}
    if name in envs and not overwrite:
        raise_error(
            f"Environment with name {name} already exists "
            "(use -f to overwrite)"
        )
    # Check prefixes
    if not overwrite:
        for env_name, env in envs.items():
            if env.get("prefix") == prefix:
                raise_error(
                    f"Environment '{env_name}' already exists with "
                    f"prefix '{prefix}'"
                )
    packages_txt = "\n".join(packages)
    # Write environment to path
    with open(path, "w") as f:
        f.write(packages_txt)
    repo.git.add(path)
    typer.echo("Adding environment to calkit.yaml")
    env = dict(path=path, kind="venv", prefix=prefix)
    if description is not None:
        env["description"] = description
    envs[name] = env
    ck_info["environments"] = envs
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    if not no_commit and repo.git.diff("--staged"):
        repo.git.commit(["-m", f"Add venv {name}"])


@new_app.command("pixi-env")
def new_pixi_env(
    packages: Annotated[
        list[str],
        typer.Argument(help="Packages to include in the environment."),
    ],
    name: Annotated[
        str, typer.Option("--name", "-n", help="Environment name.")
    ],
    pip_packages: Annotated[
        list[str], typer.Option("--pip", help="Packages to install with pip.")
    ] = [],
    description: Annotated[
        str, typer.Option("--description", help="Description.")
    ] = None,
    platforms: Annotated[
        list[str], typer.Option("--platform", "-p", help="Platform.")
    ] = [],
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Overwrite any existing environment with this name.",
        ),
    ] = False,
    no_commit: Annotated[
        bool, typer.Option("--no-commit", help="Do not commit changes.")
    ] = False,
):
    """Create a new pixi virtual environment."""
    repo = git.Repo()
    # Add environment to Calkit info
    ck_info = calkit.load_calkit_info()
    # If environments is a list instead of a dict, reformulate it
    envs = ck_info.get("environments", {})
    if isinstance(envs, list):
        typer.echo("Converting environments from list to dict")
        envs = {env.pop("name"): env for env in envs}
    if name in envs and not overwrite:
        raise_error(
            f"Environment with name {name} already exists "
            "(use -f to overwrite)"
        )
    # Create the environment now
    if not os.path.isfile("pixi.toml"):
        subprocess.run(
            [
                "pixi",
                "init",
                ".",
                "--format",
                "pixi",
            ]
        )
    # Ensure all platforms exist
    for p in platforms:
        subprocess.run(["pixi", "project", "platform", "add", p])
    # Install the packages
    for pkg in packages:
        subprocess.run(["pixi", "add", pkg, "--feature", name])
    # Install any PyPI packages
    for pkg in pip_packages:
        subprocess.run(["pixi", "add", "--pypi", pkg, "--feature", name])
    # Create a pixi environment
    subprocess.run(
        [
            "pixi",
            "project",
            "environment",
            "add",
            name,
            "--feature",
            name,
            "--force",
        ]
    )
    typer.echo("Adding environment to calkit.yaml")
    env = dict(kind="pixi", path="pixi.toml", name=name)
    if description is not None:
        env["description"] = description
    envs[name] = env
    ck_info["environments"] = envs
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("pixi.toml")
    repo.git.add("calkit.yaml")
    if not no_commit and repo.git.diff("--staged"):
        repo.git.commit(["-m", f"Add pixi env {name}"])


class Status(str, Enum):
    in_progress = "in-progress"
    on_hold = "on-hold"
    completed = "completed"


@new_app.command(name="status")
def new_status(
    status: Annotated[
        Status,
        typer.Argument(help="Current status of the project."),
    ],
    message: Annotated[
        str,
        typer.Option(
            "--message",
            "-m",
            help="Optional message describing the status.",
        ),
    ] = "",
    no_commit: Annotated[
        bool,
        typer.Option(
            "--no-commit", help="Do not commit changes to the status log."
        ),
    ] = False,
):
    """Add a new project status to the log."""
    typer.echo(f"Adding {status.value} status log entry")
    fpath = os.path.join(".calkit", "status.csv")
    os.makedirs(".calkit", exist_ok=True)
    now = calkit.utcnow(remove_tz=False)
    # Append to end of CSV
    write_header = not os.path.isfile(fpath)
    with open(fpath, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp", "status", "message"])
        writer.writerow([now.isoformat(), status.value, message])
    if not no_commit:
        typer.echo("Committing")
        repo = git.Repo()
        repo.git.add(fpath)
        repo.git.commit([fpath, "-m", f"Add {status.value} status log entry"])


class StageKind(str, Enum):
    python_script = "python-script"
    latex = "latex"
    r_script = "r-script"
    sh_script = "sh-script"
    bash_script = "bash-script"
    zsh_script = "zsh-script"
    matlab_script = "matlab-script"


class StageArgs:
    """This is just a way to deduplicate stage arguments."""

    name = Annotated[
        str,
        typer.Option("--name", "-n", help="Stage name, typically kebab-case."),
    ]
    environment = Annotated[
        str,
        typer.Option(
            "--environment", "-e", help="Environment to use to run the stage."
        ),
    ]
    inputs = Annotated[
        list[str],
        typer.Option(
            "--input", "-i", help="A path on which the stage depends."
        ),
    ]
    outputs = Annotated[
        list[str],
        typer.Option(
            "--output", "-o", help="A path that is produced by the stage."
        ),
    ]
    outs_no_delete = Annotated[
        list[str],
        typer.Option(
            "--out-no-delete",
            help="An output that should not be deleted before running.",
        ),
    ]
    outs_git = Annotated[
        list[str],
        typer.Option(
            "--out-git",
            help="An output that should be stored with Git instead of DVC.",
        ),
    ]
    outs_git_no_delete = Annotated[
        list[str],
        typer.Option(
            "--out-git-no-delete",
            help=(
                "An output that should be tracked with Git instead of DVC, "
                "and also should not be deleted before running stage."
            ),
        ),
    ]
    outs_no_store = Annotated[
        list[str],
        typer.Option(
            "--out-no-store",
            help="An output that should not be stored in version control.",
        ),
    ]
    outs_no_store_no_delete = Annotated[
        list[str],
        typer.Option(
            "--out-no-store-no-delete",
            help=(
                "An output that should not be stored in version control, "
                "and should not be deleted before running."
            ),
        ),
    ]
    overwrite = Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "--force",
            "-f",
            help="Overwrite an existing stage with this name if necessary.",
        ),
    ]
    no_check = Annotated[
        bool,
        typer.Option(
            "--no-check",
            help="Do not check if the target, deps, environment, etc., exist.",
        ),
    ]
    no_commit = Annotated[
        bool, typer.Option("--no-commit", help="Do not commit changes to Git.")
    ]
    script_path = Annotated[
        str, typer.Option("--script-path", "-s", help="Path to script.")
    ]
    args = Annotated[
        list[str],
        typer.Option("--arg", help="Argument to pass to the script."),
    ]


def _save_stage(
    stage: calkit.models.pipeline.Stage,
    name: str,
    overwrite: bool = False,
    no_check: bool = False,
    no_commit: bool = False,
) -> None:
    """Save a Calkit pipeline stage."""
    ck_info = calkit.load_calkit_info()
    if "pipeline" not in ck_info:
        ck_info["pipeline"] = {}
    if "stages" not in ck_info["pipeline"]:
        ck_info["pipeline"]["stages"] = {}
    stages = ck_info["pipeline"]["stages"]
    if name in stages and not overwrite:
        raise_error(
            f"Stage '{name}' already exists; consider using --overwrite"
        )
    # Check environment exists
    if not no_check:
        env_names = ck_info.get("environments", {})
        if stage.environment not in env_names:
            raise_error(f"Environment {stage.environment} does not exist")
    stages[name] = stage.model_dump()
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    if not no_commit:
        try:
            repo = git.Repo()
        except InvalidGitRepositoryError:
            raise_error("Can't commit because this is not a Git repo")
        repo.git.add("calkit.yaml")
        if "calkit.yaml" in calkit.git.get_staged_files():
            repo.git.commit(
                [
                    "calkit.yaml",
                    "-m",
                    f"Add {stage.kind} pipeline stage '{name}'",
                ]
            )


def _to_ck_outs(
    outputs: list[str],
    outs_git: list[str],
    outs_git_no_delete: list[str],
    outs_no_delete: list[str],
    outs_no_store: list[str],
    outs_no_store_no_delete: list[str],
) -> list[str | calkit.models.pipeline.PathOutput]:
    """Format stage outputs from CLI for Calkit pipeline."""
    ck_outs: list[str | calkit.models.pipeline.PathOutput] = list(outputs)
    for out in outs_git:
        ck_outs.append(
            calkit.models.pipeline.PathOutput(
                path=out,
                storage="git",
                delete_before_run=True,
            )
        )
    for out in outs_git_no_delete:
        ck_outs.append(
            calkit.models.pipeline.PathOutput(
                path=out,
                storage="git",
                delete_before_run=False,
            )
        )
    for out in outs_no_delete:
        ck_outs.append(
            calkit.models.pipeline.PathOutput(
                path=out,
                storage="dvc",
                delete_before_run=False,
            )
        )
    for out in outs_no_store:
        ck_outs.append(
            calkit.models.pipeline.PathOutput(
                path=out,
                storage=None,
                delete_before_run=True,
            )
        )
    for out in outs_no_store_no_delete:
        ck_outs.append(
            calkit.models.pipeline.PathOutput(
                path=out,
                storage=None,
                delete_before_run=False,
            )
        )
    return ck_outs


@new_app.command(name="python-script-stage")
def new_python_script_stage(
    name: StageArgs.name,
    environment: StageArgs.environment,
    script_path: StageArgs.script_path,
    args: StageArgs.args = [],
    inputs: StageArgs.inputs = [],
    outputs: StageArgs.outputs = [],
    outs_git: StageArgs.outs_git = [],
    outs_git_no_delete: StageArgs.outs_git_no_delete = [],
    outs_no_delete: StageArgs.outs_no_delete = [],
    outs_no_store: StageArgs.outs_no_store = [],
    outs_no_store_no_delete: StageArgs.outs_no_store_no_delete = [],
    iter_arg: Annotated[
        tuple[str, str] | None,
        typer.Option(
            "--iter",
            help=(
                "Iterate over an argument with a comma-separated list, e.g., "
                "--iter-arg var_name val1,val2,val3."
            ),
        ),
    ] = None,
    overwrite: StageArgs.overwrite = False,
    no_check: StageArgs.no_check = False,
    no_commit: StageArgs.no_commit = False,
) -> None:
    """Add a stage to the pipeline that runs a Python script."""
    ck_outs = _to_ck_outs(
        outputs=outputs,
        outs_git=outs_git,
        outs_git_no_delete=outs_git_no_delete,
        outs_no_delete=outs_no_delete,
        outs_no_store=outs_no_store,
        outs_no_store_no_delete=outs_no_store_no_delete,
    )
    try:
        if iter_arg is not None:
            arg_name, vals = iter_arg
            i = [StageIteration(arg_name=arg_name, values=vals.split(","))]  # type: ignore
        else:
            i = None
        stage = calkit.models.pipeline.PythonScriptStage(
            kind="python-script",
            environment=environment,
            args=args,
            inputs=inputs,  # type: ignore
            outputs=ck_outs,
            script_path=script_path,
            iterate_over=i,
        )
    except Exception as e:
        raise_error(f"Invalid stage specification: {e}")
    _save_stage(
        stage=stage,
        name=name,
        overwrite=overwrite,
        no_check=no_check,
        no_commit=no_commit,
    )


@new_app.command(name="matlab-script-stage")
def new_matlab_script_stage(
    name: StageArgs.name,
    environment: StageArgs.environment,
    script_path: StageArgs.script_path,
    inputs: StageArgs.inputs = [],
    outputs: StageArgs.outputs = [],
    outs_git: StageArgs.outs_git = [],
    outs_git_no_delete: StageArgs.outs_git_no_delete = [],
    outs_no_delete: StageArgs.outs_no_delete = [],
    outs_no_store: StageArgs.outs_no_store = [],
    outs_no_store_no_delete: StageArgs.outs_no_store_no_delete = [],
    overwrite: StageArgs.overwrite = False,
    no_check: StageArgs.no_check = False,
    no_commit: StageArgs.no_commit = False,
):
    """Add a stage to the pipeline that runs a MATLAB script."""
    ck_outs = _to_ck_outs(
        outputs=outputs,
        outs_git=outs_git,
        outs_git_no_delete=outs_git_no_delete,
        outs_no_delete=outs_no_delete,
        outs_no_store=outs_no_store,
        outs_no_store_no_delete=outs_no_store_no_delete,
    )
    try:
        stage = calkit.models.pipeline.MatlabScriptStage(
            kind="matlab-script",
            environment=environment,
            inputs=inputs,
            outputs=ck_outs,
            script_path=script_path,
        )
    except Exception as e:
        raise_error(f"Invalid stage specification: {e}")
    _save_stage(
        stage=stage,
        name=name,
        overwrite=overwrite,
        no_check=no_check,
        no_commit=no_commit,
    )


@new_app.command(name="latex-stage")
def new_latex_stage(
    name: StageArgs.name,
    environment: StageArgs.environment,
    target_path: Annotated[
        str, typer.Option("--target", help="Target .tex file path.")
    ],
    inputs: StageArgs.inputs = [],
    outputs: StageArgs.outputs = [],
    outs_git: StageArgs.outs_git = [],
    outs_git_no_delete: StageArgs.outs_git_no_delete = [],
    outs_no_delete: StageArgs.outs_no_delete = [],
    outs_no_store: StageArgs.outs_no_store = [],
    outs_no_store_no_delete: StageArgs.outs_no_store_no_delete = [],
    overwrite: StageArgs.overwrite = False,
    no_check: StageArgs.no_check = False,
    no_commit: StageArgs.no_commit = False,
):
    """Add a stage to the pipeline that compiles a LaTeX document."""
    ck_outs = _to_ck_outs(
        outputs=outputs,
        outs_git=outs_git,
        outs_git_no_delete=outs_git_no_delete,
        outs_no_delete=outs_no_delete,
        outs_no_store=outs_no_store,
        outs_no_store_no_delete=outs_no_store_no_delete,
    )
    try:
        stage = calkit.models.pipeline.LatexStage(
            kind="latex",
            environment=environment,
            target_path=target_path,
            inputs=inputs,
            outputs=ck_outs,
        )
    except Exception as e:
        raise_error(f"Invalid stage specification: {e}")
    _save_stage(
        stage=stage,
        name=name,
        overwrite=overwrite,
        no_check=no_check,
        no_commit=no_commit,
    )


@new_app.command(name="release")
def new_release(
    name: Annotated[
        str,
        typer.Option(
            "--name",
            "-n",
            help=(
                "A name for the release, typically kebab-case. "
                "Will be used for the Git tag and GitHub release title."
            ),
        ),
    ],
    release_type: Annotated[
        str, typer.Option("--kind", help="What kind of release to create.")
    ] = "project",
    path: Annotated[
        str,
        typer.Argument(help="The path to release; '.' for a project release."),
    ] = ".",
    description: Annotated[
        str,
        typer.Option(
            "--description",
            "--desc",
            help=(
                "A description of the release. "
                "Will be auto-generated if not provided."
            ),
        ),
    ] = None,
    release_date: Annotated[
        str,
        typer.Option("--date", help="Release date. Will default to today."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Only print actions that would be taken but don't take them.",
        ),
    ] = False,
    no_commit: Annotated[
        bool,
        typer.Option(
            "--no-commit",
            help="Do not commit changes to Git repo.",
        ),
    ] = False,
    no_push: Annotated[
        bool,
        typer.Option(
            "--no-push",
            help="Do not push to Git remote.",
        ),
    ] = False,
):
    """Create a new release."""
    if release_type not in [
        "project",
        "publication",
        "figure",
        "dataset",
        "software",
    ]:
        raise_error(f"Unknown release type '{release_type}'")
    # TODO: Check path is consistent with release type
    dotenv.load_dotenv()
    # First see if we have a Zenodo token
    typer.echo("Checking for Zenodo token")
    try:
        token = calkit.zenodo.get_token()
    except Exception as e:
        raise_error(e)
    ck_info = calkit.load_calkit_info()
    releases = ck_info.get("releases", {})
    # TODO: Enable resuming a release if upload failed part-way?
    if name in releases:
        raise_error(f"Release with name '{name}' already exists")
    repo = git.Repo()
    if name in repo.tags:
        raise_error(f"Git tag with name '{name}' already exists")
    release_dir = f".calkit/releases/{name}"
    release_files_dir = release_dir + "/files"
    os.makedirs(release_files_dir, exist_ok=True)
    # Ignore release files dir
    typer.echo(f"Ignoring {release_files_dir}")
    gitignore_path = release_dir + "/.gitignore"
    with open(gitignore_path, "w") as f:
        f.write("/files\n")
    if not dry_run:
        repo.git.add(gitignore_path)
    if release_date is None:
        release_date = str(calkit.utcnow().date())
    typer.echo(f"Using release date: {release_date}")
    # Gather up the list of files to upload
    if path == ".":
        zip_path = release_files_dir + "/archive.zip"
        all_paths = calkit.releases.ls_files()
        typer.echo(f"Adding files to {zip_path}")
        with zipfile.ZipFile(zip_path, "w") as zipf:
            for fpath in all_paths:
                zipf.write(fpath)
        if description is None:
            description = "An archive of all project files."
        title = ck_info.get("title")
        if title is None:
            warn("Project has no title")
            title = typer.prompt("Enter a title for the project")
            ck_info["title"] = title
    else:
        # TODO: Handle directories, e.g., datasets
        if not os.path.isfile(path):
            raise_error("Single artifact releases must be a single file")
        typer.echo(f"Copying {path} into {release_files_dir}")
        shutil.copy2(path, release_files_dir)
        if description is None:
            description = f"Release {release_type} at {path}."
        # Check that this artifact actually exists
        artifact_key = (
            release_type + "s" if release_type != "software" else release_type
        )
        artifacts = ck_info.get(artifact_key, [])
        title = None
        artifact = None
        for a in artifacts:
            if a.get("path") == path:
                artifact = a
                title = artifact.get("title")
                break
        if artifact is None:
            raise_error(f"{release_type} at {path} not defined in calkit.yaml")
        if title is None:
            raise_error(f"{release_type} at {path} has no title")
    # Save a metadata file with each DVC file's MD5 checksum
    dvc_md5s = calkit.releases.make_dvc_md5s(
        zipfile="archive.zip" if path == "." else None,
        paths=None if path == "." else [path],
    )
    dvc_md5s_path = release_dir + "/dvc-md5s.yaml"
    typer.echo(f"Saving DVC MD5 info to {dvc_md5s_path}")
    with open(dvc_md5s_path, "w") as f:
        calkit.ryaml.dump(dvc_md5s, f)
    if not dry_run:
        repo.git.add(dvc_md5s_path)
    # Create a README for the Zenodo release
    readme_txt = f"# {title}\n"
    git_rev = repo.git.rev_parse(["--short", "HEAD"])
    readme_txt += (
        f"\nThis is a {release_type} release ({name}) generated with "
        f"Calkit from Git rev {git_rev}.\n"
    )
    readme_path = release_files_dir + "/README.md"
    with open(readme_path, "w") as f:
        f.write(readme_txt)
    # Check size of files dir
    size = calkit.get_size(release_files_dir)
    typer.echo(f"Release size: {(size / 1e6):.1f} MB")
    if size >= 50e9:
        raise_error("Release is too large (>50 GB) to upload to Zenodo")
    # Upload to Zenodo
    # Is there already a deposition for this release, which indicates we should
    # create a new version?
    zenodo_dep_id = None
    project_name = calkit.detect_project_name()
    zenodo_metadata = dict(
        title=title,
        description=description,
        notes=f"Created from Calkit project {project_name} release {name}.",
        publication_date=release_date,
    )
    # Determine creators from authors, adding to project if not present
    authors = ck_info.get("authors", [])
    if not authors:
        warn("No authors defined for the project")
        still_entering_authors = True
        n = 0
        while still_entering_authors:
            n += 1
            author = dict()
            author["first_name"] = typer.prompt(
                f"Enter the first name of author {n}"
            )
            author["last_name"] = typer.prompt(
                f"Enter the last name of author {n}"
            )
            author["affiliation"] = typer.prompt(
                f"Enter the affiliation of author {n}"
            )
            has_orchid = typer.confirm(
                f"Does author {n} have an ORCID?", default=False
            )
            if has_orchid:
                author["orcid"] = typer.prompt(
                    f"Enter the ORCID of author {n}"
                )
            authors.append(author)
            still_entering_authors = typer.confirm(
                "Are there more authors to enter?", default=True
            )
        ck_info["authors"] = authors
    zenodo_creators = []
    for author in authors:
        creator = dict(
            name=f"{author['last_name']}, {author['first_name']}",
            affiliation=author["affiliation"],
        )
        if "orcid" in author:
            creator["orcid"] = author["orcid"]
        zenodo_creators.append(creator)
    zenodo_metadata["creators"] = zenodo_creators
    if release_type == "project":
        zenodo_metadata["upload_type"] = "other"
    elif release_type == "publication":
        pubtype = artifact.get("kind")
        if pubtype == "journal-article":
            zenodo_metadata["upload_type"] = "publication"
            zenodo_metadata["publication_type"] = "article"
        elif pubtype == "presentation":
            zenodo_metadata["upload_type"] = "presentation"
        elif pubtype == "poster":
            zenodo_metadata["upload_type"] = "poster"
        else:
            zenodo_metadata["upload_type"] = "other"
    elif release_type in ["dataset", "software"]:
        zenodo_metadata["upload_type"] = release_type
    elif release_type == "figure":
        zenodo_metadata["upload_type"] = "image"
        zenodo_metadata["image_type"] = "figure"
    else:
        zenodo_metadata["upload_type"] = "other"
    doi = None
    url = None
    for existing_name, existing_release in releases.items():
        if (
            existing_release.get("kind") == release_type
            and existing_release.get("path") == path
            and existing_release.get("publisher") == "zenodo.org"
        ):
            zenodo_dep_id = existing_release.get("zenodo_dep_id")
            typer.echo(
                f"Found existing Zenodo deposition ID {zenodo_dep_id} "
                f"in release {existing_name} to create new version for"
            )
            break
    if not dry_run:
        typer.echo("Uploading to Zenodo")
        if zenodo_dep_id is not None:
            # Create a new version of the existing deposit
            # TODO: This might fail if a new version is in progress, in which
            # case we should discard that
            zenodo_dep = calkit.zenodo.post(
                f"/deposit/depositions/{zenodo_dep_id}/actions/newversion",
                json=dict(metadata=zenodo_metadata),
            )
            typer.echo("Created new version deposition")
            typer.echo("Fetching latest draft")
            zenodo_dep = requests.get(
                zenodo_dep["links"]["latest_draft"],
                params=dict(access_token=token),
            ).json()
            zenodo_dep_id = zenodo_dep["id"]
            typer.echo(
                f"Fetched latest draft with deposition ID: {zenodo_dep_id} "
            )
            # Now update that draft with the metadata
            typer.echo("Updating latest draft metadata")
            calkit.zenodo.put(
                f"/deposit/depositions/{zenodo_dep_id}",
                json=dict(metadata=zenodo_metadata),
            )
        else:
            zenodo_dep = calkit.zenodo.post(
                "/deposit/depositions", json=dict(metadata=zenodo_metadata)
            )
            zenodo_dep_id = zenodo_dep["id"]
        bucket_url = zenodo_dep["links"]["bucket"]
        files = os.listdir(release_files_dir)
        for filename in files:
            typer.echo(f"Uploading {filename}")
            fpath = os.path.join(release_files_dir, filename)
            with open(fpath, "rb") as f:
                resp = requests.put(
                    f"{bucket_url}/{filename}",
                    data=f,
                    params={"access_token": token},
                )
                typer.echo(f"Status code: {resp.status_code}")
                resp.raise_for_status()
        # Now publish the new deposition
        typer.echo(f"Publishing Zenodo deposition ID {zenodo_dep_id}")
        zenodo_dep = calkit.zenodo.post(
            f"/deposit/depositions/{zenodo_dep_id}/actions/publish"
        )
        zenodo_dep_id = zenodo_dep["id"]
        doi = zenodo_dep["doi"]
        url = zenodo_dep["doi_url"]
        typer.echo(f"Published to Zenodo with DOI: {doi}")
    else:
        typer.echo(f"Would have posted Zenodo deposition: {zenodo_metadata}")
    # If this is a project release, add Zenodo badge to project README if
    # it doesn't exist
    doi_md = None
    if release_type == "project" and doi is not None:
        typer.echo("Adding DOI badge to README.md")
        doi_md = (
            f"[![DOI](https://zenodo.org/badge/DOI/{doi}.svg)]"
            f"(https://handle.stage.datacite.org/{doi})"
        )
        if os.path.isfile("README.md"):
            with open("README.md") as f:
                readme_txt = f.read()
        else:
            readme_txt = f"# {title}\n"
        existing_lines = readme_txt.split("\n")
        new_lines = []
        first_content_line_index = None
        for n, line in enumerate(existing_lines):
            if line.startswith(doi_md[:6]):
                pass  # Skip DOI lines
            else:
                if (
                    n != 0
                    and line.strip()
                    and first_content_line_index is None
                ):
                    first_content_line_index = len(new_lines)
                new_lines.append(line)
        # Ensure first 3 lines are title, blank, DOI lines
        new_lines = (
            [new_lines[0]]
            + ["", doi_md, ""]
            + new_lines[first_content_line_index:]
        )
        readme_txt = "\n".join(new_lines)
        with open("README.md", "w") as f:
            f.write(readme_txt)
        if not dry_run:
            repo.git.add("README.md")
    # Create Git tag
    if not dry_run:
        repo.git.tag(["-a", name, "-m", description])
    else:
        typer.echo(
            f"Would have created Git tag {name} with message: {description}"
        )
    # Save release in Calkit info
    release = dict(
        kind=release_type,
        path=path,
        git_rev=git_rev,
        date=release_date,
        publisher="zenodo.org",
        zenodo_dep_id=zenodo_dep_id,
        doi=doi,
        url=url,
        description=description,
    )
    releases[name] = release
    ck_info["releases"] = releases
    # Create CITATION.cff file
    if release_type == "project":
        typer.echo("Writing CITATION.cff")
        cff = calkit.releases.create_citation_cff(
            ck_info=ck_info, release_name=name, release_date=release_date
        )
        with open("CITATION.cff", "w") as f:
            calkit.ryaml.dump(cff, f)
        if not dry_run:
            repo.git.add("CITATION.cff")
    # Add to references so it can be cited
    typer.echo("Adding BibTeX entry to references")
    reference_collections = ck_info.get("references", [])
    if len(reference_collections) > 1:
        warn("Multiple references collections; writing to first")
    if not reference_collections:
        references = dict(path="references.bib")
        ck_info["references"] = [references]
    else:
        references = reference_collections[0]
    ref_path = references.get("path", "references.bib")
    try:
        if os.path.isfile(ref_path):
            with open(ref_path) as f:
                reflib = bibtexparser.load(f)
        else:
            reflib = bibtexparser.bibdatabase.BibDatabase()
        zenodo_bibtex = calkit.releases.create_bibtex(
            authors=authors,
            release_date=release_date,
            title=title,
            doi=doi,
            dep_id=zenodo_dep_id,
        )
        new_entry = bibtexparser.loads(zenodo_bibtex).entries[0]
        # Search through entries for one with the same DOI, and replace if
        # there is a match
        existing_index = None
        for n, entry in enumerate(reflib.entries):
            if entry.get("doi") == doi:
                typer.echo("Found matching DOI in existing references")
                existing_index = n
        if existing_index is not None:
            _ = reflib.entries.pop(existing_index)
        reflib.entries.append(new_entry)
        with open(ref_path, "w") as f:
            bibtexparser.dump(reflib, f)
        if not dry_run:
            repo.git.add(ref_path)
    except Exception as e:
        warn(f"Failed to add to references: {e}")
    # Write out Calkit metadata
    if not dry_run:
        typer.echo("Writing to calkit.yaml")
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        repo.git.add("calkit.yaml")
    else:
        typer.echo(f"Would have created release:\n{release}")
    # Commit with Git
    if not dry_run and calkit.git.get_staged_files() and not no_commit:
        repo.git.commit(["-m", f"Create new {release_type} release {name}"])
    # Push with Git
    if not dry_run and not no_push and not no_commit:
        repo.git.push(["origin", repo.active_branch.name, "--tags"])
        # Now create GitHub release
        typer.echo("Creating GitHub release")
        release_body = ""
        if doi_md is not None:
            release_body += doi_md + "\n\n"
        release_body += description
        resp = calkit.cloud.post(
            f"/projects/{project_name}/github-releases",
            json=dict(
                tag_name=name,
                body=release_body,
            ),
        )
        typer.echo(f"Created GitHub release at: {resp['url']}")
        # TODO: Upload assets for GitHub release if they're not too big?
    typer.echo(f"New {release_type} release {name} successfully created")


@new_app.command(name="stage")
def new_stage(
    name: StageArgs.name,
    kind: Annotated[
        StageKind, typer.Option("--kind", help="What kind of stage to create.")
    ],
    target: Annotated[
        str,
        typer.Option(
            "--target", "-t", help="Target file, e.g., the script to run."
        ),
    ],
    environment: Annotated[
        str | None,
        typer.Option(
            "--environment", "-e", help="Environment to use to run the stage."
        ),
    ] = None,
    deps: Annotated[
        list[str],
        typer.Option("--dep", "-d", help="A path on which the stage depends."),
    ] = [],
    outs: Annotated[
        list[str],
        typer.Option(
            "--out", "-o", help="A path that is produced by the stage."
        ),
    ] = [],
    outs_persist: Annotated[
        list[str],
        typer.Option(
            "--out-persist",
            help="An output that should not be deleted before running.",
        ),
    ] = [],
    outs_no_cache: Annotated[
        list[str],
        typer.Option(
            "--out-git",
            help="An output that should be tracked with Git instead of DVC.",
        ),
    ] = [],
    outs_persist_no_cache: Annotated[
        list[str],
        typer.Option(
            "--out-git-persist",
            help=(
                "An output that should be tracked with Git instead of DVC, "
                "and also should not be deleted before running stage."
            ),
        ),
    ] = [],
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "--force",
            "-f",
            help="Overwrite an existing stage with this name if necessary.",
        ),
    ] = False,
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check",
            help="Do not check if the target, deps, environment, etc., exist.",
        ),
    ] = False,
    no_commit: Annotated[
        bool, typer.Option("--no-commit", help="Do not commit changes to Git.")
    ] = False,
):
    """Create a new DVC pipeline stage (deprecated)."""
    ck_info = calkit.load_calkit_info(process_includes="environments")
    environments = ck_info.get("environments", {})
    if environment is None:
        warn("No environment is specified")
        cmd = ""
    else:
        if environment not in environments and not no_check:
            raise_error(f"Environment '{environment}' does not exist")
        cmd = f"calkit xenv -n {environment} -- "
        # Add environment path as a dependency if applicable
        env_path = environments.get(environment, {}).get("path")
        if env_path is not None and env_path not in deps:
            deps = [env_path] + deps
    if not os.path.exists(target) and not no_check:
        raise_error(f"Target '{target}' does not exist")
    if kind.value == "python-script":
        cmd += f"python {target}"
    elif kind.value == "latex":
        cmd += f"latexmk -cd -interaction=nonstopmode -pdf {target}"
        out_target = target.removesuffix(".tex") + ".pdf"
        if out_target not in (
            outs + outs_no_cache + outs_persist + outs_persist_no_cache
        ):
            outs = [out_target] + outs
    elif kind.value == "matlab-script":
        cmd += f"matlab -noFigureWindows -batch \"run('{target}');\""
    elif kind.value == "sh-script":
        cmd += f"sh {target}"
    elif kind.value == "bash-script":
        cmd += f"bash {target}"
    elif kind.value == "zsh-script":
        cmd += f"zsh {target}"
    elif kind.value == "r-script":
        cmd += f"Rscript {target}"
    add_cmd = [sys.executable, "-m", "dvc", "stage", "add", "-n", name]
    if target not in deps:
        deps = [target] + deps
    for dep in deps:
        add_cmd += ["-d", dep]
    for out in outs:
        add_cmd += ["-o", out]
    for out in outs_no_cache:
        add_cmd += ["--outs-no-cache", out]
    for out in outs_persist:
        add_cmd += ["--outs-persist", out]
    for out in outs_persist_no_cache:
        add_cmd += ["--outs-persist-no-cache", out]
    if overwrite:
        add_cmd.append("-f")
    add_cmd.append(cmd)
    try:
        subprocess.check_call(add_cmd)
    except subprocess.CalledProcessError:
        raise_error("Failed to create stage")
    if not no_commit:
        try:
            repo = git.Repo()
        except InvalidGitRepositoryError:
            raise_error("Can't commit because this is not a Git repo")
        repo.git.add("dvc.yaml")
        if "dvc.yaml" in calkit.git.get_staged_files():
            repo.git.commit(
                ["dvc.yaml", "-m", f"Add {kind.value} pipeline stage '{name}'"]
            )
