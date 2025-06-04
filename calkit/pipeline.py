"""Pipeline-related functionality."""

import os

import git
import typer

import calkit
from calkit.environments import get_env_lock_fpath
from calkit.models.pipeline import (
    InputsFromStageOutputs,
    PathOutput,
    Pipeline,
)


def to_dvc(
    ck_info: dict | None = None, wdir: str | None = None, write: bool = False
) -> dict:
    """Transpile a Calkit pipeline to a DVC pipeline."""
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    if "pipeline" not in ck_info:
        raise ValueError("No pipeline found in calkit.yaml")
    try:
        pipeline = Pipeline.model_validate(ck_info["pipeline"])
    except Exception as e:
        raise ValueError(f"Pipeline is not defined properly: {e}")
    dvc_stages = {}
    # First, create stages for checking/exporting all environments
    env_lock_fpaths = {}
    for env_name, env in ck_info.get("environments", {}).items():
        env_fpath = env.get("path")
        env_kind = env.get("kind")
        lock_fpath = get_env_lock_fpath(
            env=env, env_name=env_name, as_posix=True
        )
        if lock_fpath is None:
            continue
        deps = []
        outs = []
        if env_fpath is not None:
            deps.append(env_fpath)
        if env_kind == "docker":
            cmd = "calkit check docker-env"
            image = env.get("image")
            if image is None:
                raise ValueError("Docker image must be specified")
            cmd += f" {image}"
            if env_fpath is not None:
                cmd += f" -i {env_fpath}"
            cmd += f" -o {lock_fpath}"
        elif env_kind == "uv":
            lock_fpath = "uv.lock"
            cmd = "uv sync"
        elif env_kind in ["venv", "uv-venv"]:
            cmd = "calkit check venv"
            if env_fpath is None:
                raise ValueError("venvs require a path")
            cmd += f" {env_fpath}"
        elif env_kind == "conda":
            cmd = "calkit check conda-env"
            if env_fpath is None:
                raise ValueError("Conda envs require a path")
            cmd += f" --file {env_fpath} --output {lock_fpath}"
            if env.get("relaxed"):
                cmd += " --relaxed"
        elif env_kind == "matlab":
            cmd = "calkit check matlab-env"
            cmd += f" --name {env_name} --output {lock_fpath}"
        # TODO: Add more env types
        outs.append({lock_fpath: dict(cache=False, persist=True)})
        stage = dict(cmd=cmd, deps=deps, outs=outs, always_changed=True)
        dvc_stages[f"_check-env-{env_name}"] = stage
        env_lock_fpaths[env_name] = lock_fpath
    # Now convert Calkit stages into DVC stages
    for stage_name, stage in pipeline.stages.items():
        dvc_stage = stage.to_dvc()
        # Add environment lock file to deps
        env_lock_fpath = env_lock_fpaths.get(stage.environment)
        if (
            env_lock_fpath is not None
            and env_lock_fpath not in dvc_stage["deps"]
        ):
            dvc_stage["deps"].append(env_lock_fpath)
        # Check if this stage iterates, which means we should create a matrix
        # stage
        if stage.iterate_over is not None:
            # Process a list of iterations into a DVC matrix stage
            dvc_matrix = {}
            format_dict = {}
            for iteration in stage.iterate_over:
                arg_name = iteration.arg_name
                dvc_matrix[arg_name] = iteration.expand_values(
                    params=ck_info["parameters"]
                )
                # Now replace arg name in cmd, deps, and outs with
                # ${item.{arg_name}}
                format_dict[arg_name] = f"${{item.{arg_name}}}"
            try:
                cmd = dvc_stage["cmd"]
                cmd = cmd.format(**format_dict)
                dvc_stage["cmd"] = cmd
            except Exception as e:
                raise ValueError(
                    (
                        f"Failed to format cmd '{cmd}': "
                        f"{e.__class__.__name__}: {e}"
                    )
                )
            formatted_deps = []
            formatted_outs = []
            for dep in dvc_stage.get("deps", []):
                try:
                    formatted_deps.append(dep.format(**format_dict))
                except Exception as e:
                    raise ValueError(
                        (
                            f"Failed to format dep '{dep}': "
                            f"{e.__class__.__name__}: {e}"
                        )
                    )
            for out in dvc_stage.get("outs", []):
                if isinstance(out, dict):
                    formatted_outs.append(
                        {
                            str(list(out.keys())[0]).format(
                                **format_dict
                            ): dict(list(out.values())[0])
                        }
                    )
                else:
                    formatted_outs.append(out.format(**format_dict))
            dvc_stage["deps"] = formatted_deps
            dvc_stage["outs"] = formatted_outs
            dvc_stage["matrix"] = dvc_matrix
        dvc_stages[stage_name] = dvc_stage
        # Check for any outputs that should be ignored
        if write:
            repo = git.Repo(wdir)
            for out in stage.outputs:
                if (
                    isinstance(out, PathOutput)
                    and out.storage is None
                    and not repo.ignored(out.path)
                ):
                    gitignore_path = ".gitignore"
                    if wdir is not None:
                        gitignore_path = os.path.join(wdir, gitignore_path)
                    with open(gitignore_path, "a") as f:
                        f.write("\n" + out.path + "\n")
    # Now process any inputs from stage outputs
    for stage_name, stage in pipeline.stages.items():
        for i in stage.inputs:
            if isinstance(i, InputsFromStageOutputs):
                dvc_outs = dvc_stages[i.from_stage_outputs]["outs"]
                for out in dvc_outs:
                    if out not in dvc_stages[stage_name]["deps"]:
                        if isinstance(out, dict):
                            out = list(out.keys())[0]
                        dvc_stages[stage_name]["deps"].append(out)
    if write:
        if os.path.isfile("dvc.yaml"):
            with open("dvc.yaml") as f:
                dvc_yaml = calkit.ryaml.load(f)
        else:
            dvc_yaml = {}
        if dvc_yaml is None:
            dvc_yaml = {}
        existing_stages = dvc_yaml.get("stages", {})
        for stage_name, stage in existing_stages.items():
            # Skip private stages (ones whose names start with an underscore)
            if not stage_name.startswith("_") and stage_name not in dvc_stages:
                dvc_stages[stage_name] = stage
        dvc_yaml["stages"] = dvc_stages
        with open("dvc.yaml", "w") as f:
            typer.echo("Writing to dvc.yaml")
            calkit.ryaml.dump(dvc_yaml, f)
    return dvc_stages
