"""CLI for creating new objects."""

from __future__ import annotations

import os
import shutil
import subprocess

import git
import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import raise_error
from calkit.core import ryaml
from calkit.docker import LAYERS

new_app = typer.Typer(no_args_is_help=True)


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
        str, typer.Option("--path", help="Dockerfile path.")
    ] = "Dockerfile",
    stage: Annotated[
        str,
        typer.Option(
            "--stage", help="DVC pipeline stage name, if built in one."
        ),
    ] = None,
    layers: Annotated[
        list[str],
        typer.Option(
            "--add-layer", help="Add a layer (options: mambaforge, foampy)."
        ),
    ] = [],
    wdir: Annotated[
        str, typer.Option("--wdir", help="Working directory.")
    ] = "/work",
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
    if base and os.path.isfile(path) and not overwrite:
        raise_error("Output path already exists (use -f to overwrite)")
    if stage and not base:
        raise_error("--from must be specified when creating a build stage")
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
    if base is not None:
        env["path"] = path
    if stage is not None:
        env["stage"] = stage
    if description is not None:
        env["description"] = description
    if layers:
        env["layers"] = layers
    envs[name] = env
    ck_info["environments"] = envs
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    # If we're creating a stage, do so with DVC
    if stage:
        typer.echo(f"Creating DVC stage {stage}")
        subprocess.call(
            [
                "dvc",
                "stage",
                "add",
                "-f",
                "-n",
                stage,
                "--always-changed",
                "-d",
                path,
                "--outs-persist-no-cache",
                f"{path}-lock.json",
                f"calkit build-docker {image_name} -i {path}",
            ]
        )
    repo.git.add("calkit.yaml")
    if stage:
        repo.git.add("dvc.yaml")
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
    if template_type not in ["latex"]:
        raise_error(f"Unknown template type '{template_type}'")
    if env_name is not None and template_type != "latex":
        raise_error("Environments can only be created for latex templates")
    if env_name is not None and env_name in envs and not overwrite:
        raise_error(f"Environment '{env_name}' already exists")
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
            image="kjarosh/latex:2024.4",
            description="TeXlive full from kjarosh.",
            platform="linux/amd64",
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
        cmd = f"cd {path} && latexmk -pdf {template_obj.target}"
        if env_name is not None:
            cmd = f'calkit runenv -n {env_name} "{cmd}"'
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
