"""CLI for checking things."""

from __future__ import annotations

import functools
import hashlib
import json
import os
import platform as _platform
import subprocess
import warnings
from typing import Annotated

from calkit.environments import get_env_lock_fpath

# See https://github.com/calkit/calkit/issues/346
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=UserWarning)
    import checksumdir

import dotenv
import git
import typer

import calkit
import calkit.matlab
import calkit.pipeline
from calkit.check import check_reproducibility
from calkit.cli import raise_error

check_app = typer.Typer(no_args_is_help=True)


@check_app.command(name="repro")
def check_repro(
    wdir: Annotated[
        str, typer.Option("--wdir", help="Project working directory.")
    ] = ".",
):
    """Check the reproducibility of a project."""
    res = check_reproducibility(wdir=wdir, log_func=typer.echo)
    typer.echo(res.to_pretty().encode("utf-8", errors="replace"))


@check_app.command(
    name="env",
    help="Check that an environment is up-to-date (alias for 'environment').",
)
@check_app.command(name="environment")
def check_environment(
    env_name: Annotated[
        str,
        typer.Option("--name", "-n", help="Name of the environment to check."),
    ],
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Print verbose output.")
    ] = False,
):
    """Check that an environment is up-to-date."""
    dotenv.load_dotenv(dotenv_path=".env", verbose=verbose)
    ck_info = calkit.load_calkit_info(process_includes="environments")
    envs = ck_info.get("environments", {})
    if not envs:
        raise_error("No environments defined in calkit.yaml")
    if isinstance(envs, list):
        raise_error("Error: Environments should be a dict, not a list")
    assert isinstance(envs, dict)
    if env_name not in envs:
        raise_error(f"Environment '{env_name}' does not exist")
    env = envs[env_name]
    if env["kind"] == "docker":
        if "image" not in env:
            raise_error("Image must be defined for Docker environments")
        check_docker_env(
            tag=env["image"],
            fpath=env.get("path"),
            lock_fpath=get_env_lock_fpath(
                env=env, env_name=env_name, as_posix=False
            ),
            platform=env.get("platform"),
            deps=env.get("deps", []),
            quiet=not verbose,
        )
    elif env["kind"] == "conda":
        check_conda_env(
            env_fpath=env["path"],
            output_fpath=get_env_lock_fpath(
                env=env, env_name=env_name, as_posix=False
            ),
            relaxed=True,  # TODO: Add option?
            quiet=not verbose,
        )
    elif env["kind"] in ["pixi", "uv"]:
        cmd = [env["kind"], "lock"]
        if verbose:
            typer.echo(f"Running command: {cmd}")
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError:
            raise_error(f"Failed to check {env['kind']} environment")
    elif (kind := env["kind"]) in ["uv-venv", "venv"]:
        if "prefix" not in env:
            raise_error("venv environments require a prefix")
        if "path" not in env:
            raise_error("venv environments require a path")
        prefix = env["prefix"]
        path = env["path"]
        # Check environment
        check_venv(
            path=path,
            prefix=prefix,
            use_uv=kind == "uv-venv",
            python=env.get("python"),
            lock_fpath=get_env_lock_fpath(
                env=env, env_name=env_name, as_posix=False
            ),
            verbose=verbose,
        )
    elif env["kind"] == "ssh":
        # TODO: How to check SSH environments?
        # Maybe just check that we can connect
        raise_error(
            "Environment checking not implemented for SSH environments"
        )
    elif env["kind"] == "renv":
        try:
            subprocess.check_call(["Rscript", "-e", "'renv::restore()'"])
        except subprocess.CalledProcessError:
            raise_error("Failed to check renv")
    elif env["kind"] == "matlab":
        check_matlab_env(
            env_name=env_name,
            output_fpath=get_env_lock_fpath(
                env=env, env_name=env_name, as_posix=False
            ),  # type: ignore
        )
    else:
        raise_error(f"Environment kind '{env['kind']}' not supported")


@check_app.command(name="docker-env")
def check_docker_env(
    tag: Annotated[str, typer.Argument(help="Image tag.")],
    fpath: Annotated[
        str | None,
        typer.Option(
            "-i", "--input", help="Path to input Dockerfile, if applicable."
        ),
    ] = None,
    lock_fpath: Annotated[
        str | None,
        typer.Option(
            "--output",
            "-o",
            help=(
                "Path to which existing environment should be exported. "
                "If not specified, will have the same filename with '-lock' "
                "appended to it, keeping the same extension."
            ),
        ),
    ] = None,
    platform: Annotated[
        str | None,
        typer.Option("--platform", help="Which platform(s) to build for."),
    ] = None,
    deps: Annotated[
        list[str],
        typer.Option(
            "--dep",
            "-d",
            help="Declare an explicit dependency for this Docker image.",
        ),
    ] = [],
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Be quiet.")
    ] = False,
):
    """Check that Docker environment is up-to-date."""
    if fpath is None and lock_fpath is None:
        raise_error(
            "Lock file output path must be provided if input Dockerfile is not"
        )

    def get_docker_inspect():
        out = json.loads(
            subprocess.check_output(["docker", "inspect", tag]).decode()
        )
        # Remove some keys that can change without the important aspects of
        # the image changing
        _ = out[0].pop("Id")
        _ = out[0].pop("RepoDigests")
        _ = out[0].pop("Metadata")
        _ = out[0].pop("DockerVersion")
        return out

    def get_md5(path: str, exclude_files: list[str] | None = None) -> str:
        if os.path.isdir(path):
            return checksumdir.dirhash(dep, excluded_files=exclude_files)
        else:
            with open(path) as f:
                content = f.read()
            return hashlib.md5(content.encode()).hexdigest()

    outfile = open(os.devnull, "w") if quiet else None
    typer.echo(f"Checking for existing image with tag {tag}", file=outfile)
    # First call Docker inspect
    try:
        inspect = get_docker_inspect()
    except subprocess.CalledProcessError:
        typer.echo(f"No image with tag {tag} found locally", file=outfile)
        inspect = []
    if fpath is not None:
        typer.echo(f"Reading Dockerfile from {fpath}", file=outfile)
        dockerfile_md5 = get_md5(fpath)
    else:
        dockerfile_md5 = None
    if lock_fpath is None and fpath is not None:
        lock_fpath = fpath + "-lock.json"
    else:
        lock_fpath = str(lock_fpath)
    # Compute MD5s of any dependencies
    deps_md5s = {}
    for dep in deps:
        deps_md5s[dep] = get_md5(dep, exclude_files=[lock_fpath])
    rebuild_or_pull = True
    if os.path.isfile(lock_fpath):
        typer.echo(f"Reading lock file: {lock_fpath}", file=outfile)
        with open(lock_fpath) as f:
            lock = json.load(f)
    else:
        typer.echo(f"Lock file ({lock_fpath}) does not exist", file=outfile)
        lock = None
    if inspect and lock:
        typer.echo(
            "Checking image and Dockerfile against lock file", file=outfile
        )
        rebuild_or_pull = inspect[0]["RootFS"]["Layers"] != lock[0]["RootFS"][
            "Layers"
        ] or dockerfile_md5 != lock[0].get("DockerfileMD5")
        if not rebuild_or_pull:
            for dep, md5 in deps_md5s.items():
                if md5 != lock[0].get("DepsMD5s", {}).get(dep):
                    typer.echo(f"Found modified dependency: {dep}")
                    rebuild_or_pull = True
                    break
    if fpath is not None and rebuild_or_pull:
        wdir, fname = os.path.split(fpath)
        if not wdir:
            wdir = None
        cmd = ["docker", "build", "-t", tag, "-f", fname]
        if platform is not None:
            cmd += ["--platform", platform]
        cmd.append(".")
        subprocess.check_output(cmd, cwd=wdir)
    elif fpath is None and rebuild_or_pull:
        typer.echo(f"Pulling image: {tag}")
        cmd = ["docker", "pull", tag]
        try:
            subprocess.check_output(cmd)
        except subprocess.CalledProcessError:
            raise_error(f"Failed to pull image: {tag}")
    # Write the lock file
    inspect = get_docker_inspect()
    inspect[0]["DockerfileMD5"] = dockerfile_md5
    inspect[0]["DepsMD5s"] = deps_md5s
    lock_dir = os.path.dirname(lock_fpath)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    with open(lock_fpath, "w") as f:
        json.dump(inspect, f, indent=4)


@check_app.command(
    name="conda-env",
    help="Check a conda environment and rebuild if necessary.",
)
def check_conda_env(
    env_fpath: Annotated[
        str,
        typer.Option(
            "--file", "-f", help="Path to conda environment YAML file."
        ),
    ] = "environment.yml",
    output_fpath: Annotated[
        str | None,
        typer.Option(
            "--output",
            "-o",
            help=(
                "Path to which existing environment should be exported. "
                "If not specified, will have the same filename with '-lock' "
                "appended to it, keeping the same extension."
            ),
        ),
    ] = None,
    relaxed: Annotated[
        bool,
        typer.Option(
            "--relaxed", help="Treat conda and pip dependencies as equivalent."
        ),
    ] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Be quiet.")
    ] = False,
):
    if quiet:
        log_func = functools.partial(typer.echo, file=open(os.devnull, "w"))
    else:
        log_func = typer.echo
    calkit.conda.check_env(
        env_fpath=env_fpath,
        output_fpath=output_fpath,
        log_func=log_func,
        relaxed=relaxed,
    )


@check_app.command(name="venv")
def check_venv(
    path: Annotated[
        str, typer.Argument(help="Path to requirements file.")
    ] = "requirements.txt",
    prefix: Annotated[str, typer.Option("--prefix", help="Prefix.")] = ".venv",
    lock_fpath: Annotated[
        str | None,
        typer.Option(
            "--output",
            "-o",
            help=(
                "Path to which existing environment should be exported. "
                "If not specified, will have the same filename with '-lock' "
                "appended to it, keeping the same extension."
            ),
        ),
    ] = None,
    wdir: Annotated[
        str | None,
        typer.Option(
            "--wdir",
            help="Working directory. Defaults to current working directory.",
        ),
    ] = None,
    use_uv: Annotated[bool, typer.Option("--uv", help="Use uv.")] = True,
    python: Annotated[
        str | None,
        typer.Option(
            "--python", help="Python version to specify if using uv."
        ),
    ] = None,
    quiet: Annotated[
        bool, typer.Option("--quiet", help="Do not print any output")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Print verbose output.")
    ] = False,
):
    """Check a Python virtual environment (uv or virtualenv)."""
    kind = "uv-venv" if use_uv else "venv"
    create_cmd = (
        ["uv", "venv"] if kind == "uv-venv" else ["python", "-m", "venv"]
    )
    pip_cmd = "pip" if kind == "venv" else "uv pip"
    pip_freeze_cmd = f"{pip_cmd} freeze"
    if kind == "uv-venv":
        pip_freeze_cmd += " --color never"
    else:
        pip_freeze_cmd += " --no-color"
    pip_install_args = "-q" if quiet else ""
    if python is not None and not use_uv:
        raise_error("Python version cannot be specified if not using uv")
    if python is not None and use_uv:
        create_cmd += ["--python", python]
        pip_install_args += f" --python {python}"
    if not os.path.isdir(prefix):
        if verbose:
            typer.echo(f"Creating {kind} at {prefix}")
        try:
            subprocess.check_call(create_cmd + [prefix], cwd=wdir)
        except subprocess.CalledProcessError:
            raise_error(f"Failed to create {kind} at {prefix}")
        # Put a gitignore file in the env dir if one doesn't exist
        if not os.path.isfile(os.path.join(prefix, ".gitignore")):
            with open(os.path.join(prefix, ".gitignore"), "w") as f:
                f.write("*\n")
    if lock_fpath is None:
        fname, ext = os.path.splitext(path)
        lock_fpath = fname + "-lock" + ext
    if _platform.system() == "Windows":
        activate_cmd = f"{prefix}\\Scripts\\activate"
    else:
        activate_cmd = f". {prefix}/bin/activate"
    lock_dir = os.path.dirname(lock_fpath)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    check_cmd = (
        f"{activate_cmd} "
        f"&& {pip_cmd} install {pip_install_args} -r {path} "
        f"&& {pip_freeze_cmd} > {lock_fpath} "
        "&& deactivate"
    )
    try:
        if verbose:
            typer.echo(f"Running command: {check_cmd}")
        subprocess.check_call(
            check_cmd,
            shell=True,
            cwd=wdir,
            stderr=subprocess.STDOUT if not verbose else None,
        )
    except subprocess.CalledProcessError:
        raise_error(f"Failed to check {kind}")


@check_app.command(name="matlab-env")
def check_matlab_env(
    env_name: Annotated[
        str,
        typer.Option("--name", "-n", help="Environment name in calkit.yaml."),
    ],
    output_fpath: Annotated[str, typer.Option("--output", "-o")],
) -> None:
    """Check a MATLAB environment matches its spec and export a JSON lock
    file.
    """
    ck_info = calkit.load_calkit_info()
    environments = ck_info.get("environments", {})
    if env_name not in environments:
        raise_error(f"Environment '{env_name}' not found in calkit.yaml")
    env = environments[env_name]
    if env.get("kind") != "matlab":
        raise_error(f"Environment '{env_name}' is not a MATLAB environment")
    if "version" not in env:
        raise_error("A MATLAB version must be specified")
    typer.echo(f"Checking MATLAB environment '{env_name}'")
    # First generate a Dockerfile for this environment
    out_dir = os.path.join(".calkit", "environments", env_name)
    os.makedirs(out_dir, exist_ok=True)
    dockerfile_fpath = os.path.join(out_dir, "Dockerfile")
    calkit.matlab.create_dockerfile(
        matlab_version=env["version"],
        additional_products=env.get("products", []),
        write=True,
        fpath_out=dockerfile_fpath,
    )
    # Now check that Docker environment
    tag = calkit.matlab.get_docker_image_name(
        ck_info=ck_info,
        env_name=env_name,
    )
    check_docker_env(
        tag=tag,
        fpath=dockerfile_fpath,
        lock_fpath=output_fpath,
        platform="linux/amd64",  # Only one available for now
    )


@check_app.command(name="env-vars")
def check_env_vars(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output")
    ] = False,
):
    """Check that the project's required environmental variables exist."""
    typer.echo("Checking project environmental variables")
    dotenv.load_dotenv(dotenv_path=".env")
    ck_info = calkit.load_calkit_info()
    deps = ck_info.get("dependencies", [])
    env_var_deps = {}
    for d in deps:
        if isinstance(d, dict):
            keys = list(d.keys())
            if len(keys) > 1:
                raise_error(
                    f"Malformed dependency: {d}\n"
                    "Dependencies with attributes should have a single key "
                    "(their name)"
                )
            name = keys[0]
            attrs = list(d.values())[0]
            if attrs.get("kind") == "env-var":
                env_var_deps[name] = attrs
    for name, attrs in env_var_deps.items():
        if verbose:
            typer.echo(f"Checking for environmental variable '{name}'")
        if name not in os.environ:
            typer.echo(f"Missing env var '{name}'")
            if "default" in attrs:
                default = attrs["default"]
            else:
                default = None
            value = typer.prompt(
                f"Enter a value for {name}", default=default, type=str
            )
            dotenv.set_key(
                dotenv_path=".env", key_to_set=name, value_to_set=value
            )
    # Ensure that .env is ignored by git
    repo = git.Repo()
    if not repo.ignored(".env"):
        typer.echo("Adding .env to .gitignore")
        with open(".gitignore", "a") as f:
            f.write("\n.env\n")
    message = "✅ All set!"
    typer.echo(message.encode("utf-8", errors="replace"))


@check_app.command(name="pipeline")
def check_pipeline(
    compile_to_dvc: Annotated[
        bool,
        typer.Option(
            "--compile",
            "-c",
            help="Compile the pipeline to DVC stages and merge into dvc.yaml.",
        ),
    ] = False,
):
    """Check that the project pipeline is defined correctly."""
    from calkit.models.pipeline import Pipeline

    ck_info = calkit.load_calkit_info()
    if "pipeline" not in ck_info:
        raise_error("No pipeline is defined in calkit.yaml")
    try:
        pipeline = Pipeline.model_validate(ck_info["pipeline"], strict=True)
    except Exception as e:
        raise_error(f"Pipeline is not defined correctly: {e}")
    # Check that we have no leading underscores in stage names, since those
    # are reserved for auto-generated stages
    for stage_name in pipeline.stages.keys():
        if stage_name.startswith("_"):
            raise_error("Stage names cannot start with an underscore")
    message = "✅ This project's pipeline is defined correctly!"
    typer.echo(message.encode("utf-8", errors="replace"))
    if compile_to_dvc:
        typer.echo("Attempting to compile to DVC stages")
        try:
            calkit.pipeline.to_dvc(ck_info=ck_info, write=True)
        except Exception as e:
            raise_error(
                f"Failed to compile pipeline: {e.__class__.__name__}: {e}"
            )


@check_app.command(name="call")
def check_call(
    cmd: Annotated[str, typer.Argument(help="Command to check.")],
    if_error: Annotated[
        str,
        typer.Option(
            "--if-error", help="Command to run if there is an error."
        ),
    ],
):
    """Check that a command succeeds and run an alternate if not."""
    try:
        subprocess.check_call(cmd, shell=True)
        typer.echo("Command succeeded")
    except subprocess.CalledProcessError:
        typer.echo("Command failed")
        try:
            typer.echo("Attempting fallback call")
            subprocess.check_call(if_error, shell=True)
            typer.echo("Fallback call succeeded")
        except subprocess.CalledProcessError:
            raise_error("Fallback call failed")
