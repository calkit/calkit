"""Pipeline-related functionality."""

import os

import calkit
from calkit.models.pipeline import Pipeline


def to_dvc(wdir: str | None = None) -> dict:
    """Transpile a Calkit pipeline to a DVC pipeline."""
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
    os.makedirs(env_lock_dir, exist_ok=True)
    # TODO
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
        outs.append(lock_fpath)
    # Now convert Calkit stages into DVC stages
    for stage_name, stage in pipeline.stages.items():
        dvc_stages[stage_name] = stage.to_dvc()
        # TODO: Add environment lock file to deps
    return dvc_stages
