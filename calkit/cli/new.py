"""CLI for creating new objects."""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import zipfile
from enum import Enum

import dotenv
import git
import typer
from git.exc import GitCommandError, InvalidGitRepositoryError
from typing_extensions import Annotated

import calkit
from calkit.cli import raise_error, warn
from calkit.cli.update import update_devcontainer
from calkit.core import ryaml
from calkit.docker import LAYERS

new_app = typer.Typer(no_args_is_help=True)


@new_app.command(name="project")
def new_project(
    path: Annotated[str, typer.Argument(help="Where to create the project.")],
    name: Annotated[
        str,
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
        str, typer.Option("--title", help="Project title.")
    ] = None,
    description: Annotated[
        str, typer.Option("--description", help="Project description.")
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
        str,
        typer.Option(
            "--git-url",
            help=(
                "Git repo URL. "
                "Usually https://github.com/{your_name}/{project_name}."
            ),
        ),
    ] = None,
    template: Annotated[
        str,
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
        bool, typer.Option("--no-commit", help="Do not commit changes to Git.")
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
    if cloud and os.path.isdir(os.path.join(abs_path, ".git")):
        raise_error("Must not already be a Git repo to use --cloud")
    ck_info_fpath = os.path.join(abs_path, "calkit.yaml")
    if os.path.isfile(ck_info_fpath) and not overwrite:
        raise_error(
            "Destination is already a Calkit project; "
            "use --overwrite to continue"
        )
    if os.path.isdir(abs_path) and os.listdir(abs_path):
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
        else:
            typer.echo("Fetching from newly create Git repo")
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
        try:
            calkit.dvc.set_remote_auth(wdir=abs_path)
        except Exception:
            warn("Failed to setup Calkit DVC remote auth")
        prj = calkit.git.detect_project_name(path=abs_path)
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
                ["dvc", "remote", "remove", "calkit", "-q"], cwd=abs_path
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
        subprocess.run(["dvc", "init", "-q"], cwd=abs_path)
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
        calkit.dvc.configure_remote(wdir=abs_path)
        calkit.dvc.set_remote_auth(wdir=abs_path)
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
            ["dvc", "stage", "add", "-n", stage_name]
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
        str,
        typer.Option(
            "--image",
            help=(
                "Image identifier. Should be unique and descriptive. "
                "Will default to environment name if not specified."
            ),
        ),
    ] = None,
    base: Annotated[
        str,
        typer.Option(
            "--from",
            help="Base image, e.g., 'ubuntu', if creating a Dockerfile.",
        ),
    ] = None,
    path: Annotated[
        str,
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
    platform: Annotated[
        str, typer.Option("--platform", help="Which platform(s) to build for.")
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
    """Create a new Docker environment."""
    if base is not None and path is None:
        path = "Dockerfile"
    if base and os.path.isfile(path) and not overwrite:
        raise_error("Output path already exists (use -f to overwrite)")
    if image_name is None:
        typer.echo("No image name specified; using environment name")
        image_name = name
    repo = git.Repo()
    if base:
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
            ["dvc", "stage", "add", "-n", stage_name]
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
        str,
        typer.Option(
            "--stage",
            help="Name of the pipeline stage to build the output file.",
        ),
    ] = None,
    deps: Annotated[
        list[str], typer.Option("--dep", help="Path to stage dependency.")
    ] = [],
    outs_from_stage: Annotated[
        str,
        typer.Option(
            "--deps-from-stage-outs",
            help="Stage name from which to add outputs as dependencies.",
        ),
    ] = None,
    template: Annotated[
        str,
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
        str,
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
):
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
        path=pub_fpath,
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
        env_path = f".calkit/environments/{env_name}.yaml"
        os.makedirs(".calkit/environments", exist_ok=True)
        env = {"_include": env_path}
        envs[env_name] = env
        env_remote = dict(
            kind="docker",
            image="texlive/texlive:latest-full",
            description="TeXlive full.",
        )
        with open(env_path, "w") as f:
            calkit.ryaml.dump(env_remote, f)
        ck_info["environments"] = envs
        repo.git.add(env_path)
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
    # Create stage if applicable
    if stage_name is not None and template_type == "latex":
        cmd = (
            "latexmk -cd -interaction=nonstopmode -pdf "
            f"{path}/{template_obj.target}"
        )
        if env_name is not None:
            cmd = f"calkit xenv -n {env_name} -- {cmd}"
        target_dep = os.path.join(path, template_obj.target)
        dvc_cmd = [
            "dvc",
            "stage",
            "add",
            "-n",
            stage_name,
            "-o",
            pub_fpath,
            "-d",
            target_dep,
        ]
        if env_name is not None:
            dvc_cmd += ["-d", env_path]
        for dep in deps:
            dvc_cmd += ["-d", dep]
        if overwrite:
            dvc_cmd.append("-f")
        dvc_cmd.append(cmd)
        subprocess.check_call(dvc_cmd)
        repo.git.add("dvc.yaml")
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
    if pip_packages:
        conda_env["dependencies"].append(dict(pip=pip_packages))
    with open(path, "w") as f:
        ryaml.dump(conda_env, f)
    repo.git.add(path)
    typer.echo("Adding environment to calkit.yaml")
    env = dict(path=path, kind="conda")
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
    with open(fpath, "a") as f:
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


@new_app.command(name="stage")
def new_stage(
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Stage name, typically kebab-case."),
    ],
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
        str,
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
    no_commit: Annotated[
        bool, typer.Option("--no-commit", help="Do not commit changes to Git.")
    ] = False,
):
    """Create a new pipeline stage."""
    ck_info = calkit.load_calkit_info()
    if environment is None:
        warn("No environment is specified")
        cmd = ""
    else:
        if environment not in ck_info["environments"]:
            raise_error(f"Environment '{environment}' does not exist")
        cmd = f"calkit xenv -n {environment} -- "
        # Add environment path as a dependency
        env_path = ck_info["environments"][environment].get("path")
        if env_path is not None:
            deps = [env_path] + deps
    if not os.path.exists(target):
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
    add_cmd = ["dvc", "stage", "add", "-n", name]
    for dep in [target] + deps:
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
        str, typer.Option("--type", help="The type of release to create.")
    ] = "project",
    path: Annotated[
        str,
        typer.Argument(help="The path to release; '.' for a project release."),
    ] = ".",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Only print actions that would be taken but don't take them.",
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
        calkit.zenodo.get_token()
    except Exception as e:
        raise_error(e)
    # Is there already a deposition for this release, which indicates we should
    # create a new version?
    # TODO: Save release state in .calkit/releases/{name}.yaml
    ck_info = calkit.load_calkit_info()
    releases = ck_info.get("releases", {})
    # TODO: Enable resuming a release?
    if name in releases:
        raise_error(f"Release with name '{name}' already exists")
    repo = git.Repo()
    release_dir = f".calkit/releases/{name}"
    release_files_dir = release_dir + "/files"
    os.makedirs(release_files_dir, exist_ok=True)
    # TODO: Ignore release files dir
    typer.echo(f"Ignoring {release_files_dir}")
    gitignore_path = release_dir + "/.gitignore"
    with open(gitignore_path, "w") as f:
        f.write("/files\n")
    if not dry_run:
        repo.git.add(gitignore_path)
    # TODO: Gather up a list of files to upload and strategize how to fit
    # within limits
    # TODO: Zip Git files into one archive and DVC into another?
    zip_path = release_files_dir + "/archive.zip"  # TODO: Name descriptively?
    all_paths = calkit.releases.ls_files()
    typer.echo(f"Adding files to {zip_path}")
    with zipfile.ZipFile(zip_path, "w") as zipf:
        for fpath in all_paths:
            zipf.write(fpath)
    # Check size of archive
    size = os.path.getsize(zip_path)
    typer.echo(f"Archive size: {(size / 1e6):.1f} MB")
    if size >= 50e9:
        raise_error("Archive is too large (>50 GB) to upload to Zenodo")
    # Save a metadata file with each DVC file's MD5 checksum
    dvc_md5s = calkit.releases.make_dvc_md5s(zipfile="archive.zip")
    dvc_md5s_path = release_dir + "/dvc-md5s.yaml"
    typer.echo(f"Saving DVC MD5 info to {dvc_md5s_path}")
    with open(dvc_md5s_path, "w") as f:
        calkit.ryaml.dump(dvc_md5s, f)
    if not dry_run:
        repo.git.add(dvc_md5s_path)
    # Create a README for the Zenodo release
    readme_txt = ""
    if title := ck_info.get("title"):
        readme_txt += f"# {title}\n"
    else:
        if os.path.isfile("README.md"):
            with open("README.md") as f:
                readme_txt += f.readline() + "\n"
    readme_txt += f"\nThis is an archived Calkit project (release: {name}).\n"
    readme_path = release_files_dir + "/README.md"
    with open(readme_path, "w") as f:
        f.write(readme_txt)
    # TODO: Upload to Zenodo
    if not dry_run:
        typer.echo("Uploading to Zenodo")
    # Add Zenodo badge to main README
    # TODO: Create Git tag
    # TODO: Create GitHub release
    # TODO: Save URL and MD5 information to
    # .calkit/releases/{name}/dvc-md5s.yaml
    # Save release in Calkit info
    release = dict(
        kind=release_type,
        path=path,
        host="zenodo.org",
        zenodo_deposition_id=1234,  # TODO
        doi=None,  # TODO
        url=None,  # TODO
        description=None,  # TODO
    )
    releases[name] = release
    ck_info["releases"] = releases
    if not dry_run:
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        repo.git.add("calkit.yaml")
        # TODO: Commit?
        # TODO: Push?
    else:
        typer.echo(f"Would have created release:\n{release}")
