"""Pipeline-related functionality."""

import os

import typer

import calkit
from calkit.models.pipeline import InputsFromStageOutputs, Pipeline


def to_dvc(
    ck_info: dict | None = None, wdir: str | None = None, write: bool = False
) -> dict:
    """Transpile a Calkit pipeline to a DVC pipeline."""
    if ck_info is None:
        ck_info = dict(calkit.load_calkit_info(wdir=wdir))
    if "pipeline" not in ck_info:
        raise ValueError("No pipeline found in calkit.yaml")
    try:
        pipeline = Pipeline.model_validate(ck_info["pipeline"])
    except Exception as e:
        raise ValueError(f"Pipeline is not defined properly: {e}")
    dvc_stages = {}
    # First, create stages for checking/exporting all environments
    env_lock_fpaths = {}
    env_lock_dir = os.path.join(".calkit/env-locks")
    for env_name, env in ck_info.get("environments", {}).items():
        env_fpath = env.get("path")
        env_kind = env.get("kind")
        lock_fpath = os.path.join(env_lock_dir, env_name)
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
            lock_fpath += ".json"
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
            lock_fpath += ".txt"
        elif env_kind == "conda":
            cmd = "calkit check conda-env"
            if env_fpath is None:
                raise ValueError("Conda envs require a path")
            lock_fpath += ".yml"
            cmd += f" --file {env_fpath} --output {lock_fpath}"
            if env.get("relaxed"):
                cmd += " --relaxed"
        elif env_kind == "matlab":
            cmd = "calkit check matlab-env"
            lock_fpath += ".json"
            cmd += f" --name {env_name} --output {lock_fpath}"
        else:
            continue
        # TODO: Add more env types
        outs.append({lock_fpath: dict(cache=False, persist=True)})
        stage = dict(cmd=cmd, deps=deps, outs=outs, always_changed=True)
        # TODO: Rationalize stage naming and ensure we remove all private
        # stages
        dvc_stages[f"_check_env_{env_name}"] = stage
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
        dvc_stages[stage_name] = dvc_stage
    # Now process any inputs from stage outputs
    for stage_name, stage in pipeline.stages.items():
        for i in stage.inputs:
            if isinstance(i, InputsFromStageOutputs):
                dvc_outs = dvc_stages[i.from_stage_outputs]["outs"]
                for out in dvc_outs:
                    if out not in dvc_stages[stage_name]["deps"]:
                        dvc_stages[stage_name]["deps"].append(out)
    if write:
        if os.path.isfile("dvc.yaml"):
            with open("dvc.yaml") as f:
                dvc_yaml = calkit.ryaml.load(f)
        else:
            dvc_yaml = {}
        existing_stages = dvc_yaml.get("stages", {})
        for stage_name, stage in existing_stages.items():
            # TODO: Skip private stages
            if stage_name not in dvc_stages:
                dvc_stages[stage_name] = stage
        dvc_yaml["stages"] = dvc_stages
        with open("dvc.yaml", "w") as f:
            typer.echo("Writing to dvc.yaml")
            calkit.ryaml.dump(dvc_yaml, f)
    return dvc_stages
