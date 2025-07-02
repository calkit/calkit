"""Functionality for working with notebooks."""

import os
from pathlib import PurePosixPath
from typing import Literal

import git

import calkit
from calkit.models.io import InputsFromStageOutputs, PathOutput


def get_executed_notebook_path(
    notebook_path: str, to: Literal["html", "notebook"], as_posix: bool = True
) -> str:
    """Return the path of an executed notebook."""
    nb_dir = os.path.dirname(notebook_path)
    nb_fname = os.path.basename(notebook_path)
    if to == "html":
        fname_out = nb_fname.removesuffix(".ipynb") + ".html"
    else:
        fname_out = nb_fname
    # Different output types go to different subdirectories
    subdirs = {"html": "html", "notebook": "executed"}
    p = os.path.join(".calkit", "notebooks", subdirs[to], nb_dir, fname_out)
    if as_posix:
        p = PurePosixPath(p).as_posix()
    return p


def get_cleaned_notebook_path(path: str, as_posix: bool = True) -> str:
    """Return the path of a cleaned notebook."""
    p = os.path.join(".calkit", "notebooks", "cleaned", path)
    if as_posix:
        p = PurePosixPath(p).as_posix()
    return p


def declare_notebook(
    path: str,
    stage_name: str,
    environment_name: str,
    inputs: list[str | InputsFromStageOutputs] = [],
    outputs: list[str | PathOutput] = [],
    always_run: bool = False,
    title: str | None = None,
    description: str | None = None,
    html_storage: Literal["git", "dvc"] | None = "dvc",
    executed_ipynb_storage: Literal["git", "dvc"] | None = "dvc",
    cleaned_ipynb_storage: Literal["git", "dvc"] | None = "git",
):
    """Declare a notebook as part of the current project.

    If this function is called as part of a running pipeline, it will fail
    if anything has changed about the pipeline declaration, then prompt the
    user to rerun.
    """
    from calkit.models.pipeline import JupyterNotebookStage, Pipeline

    # Detect the project root directory so we ensure calkit.yaml lives there
    repo = git.Repo(search_parent_directories=True)
    wdir = repo.working_dir
    if not os.path.isfile(os.path.join(wdir, path)):
        raise FileNotFoundError(
            f"Notebook '{path}' does not exist in the project directory"
        )
    pipeline_running = os.getenv("CALKIT_PIPELINE_RUNNING", "0") == "1"
    ck_info = calkit.load_calkit_info(wdir=str(wdir))
    envs = ck_info.get("environments", {})
    if environment_name not in envs:
        raise ValueError(
            f"Environment '{environment_name}' does not exist in calkit.yaml"
        )
    # TODO: Check that we are running in the correct environment
    # This could be tricky depending on what type of environment it is
    pipeline_dict = ck_info.get("pipeline", {})
    if "stages" not in pipeline_dict:
        pipeline_dict["stages"] = {}
    pipeline = Pipeline.model_validate(pipeline_dict)
    new_stage = JupyterNotebookStage(
        notebook_path=path,
        environment=environment_name,
        inputs=inputs,
        outputs=outputs,
        always_run=always_run,
        html_storage=html_storage,
        executed_ipynb_storage=executed_ipynb_storage,
        cleaned_ipynb_storage=cleaned_ipynb_storage,
    )
    stages = pipeline.stages
    must_be_rerun = False
    # Check to see if we're mutating an existing stage
    if pipeline_running and stage_name in stages:
        # If the pipeline is running, we can't change the stage
        existing_stage = stages[stage_name]
        if existing_stage != new_stage:
            must_be_rerun = True
    new_stage_dump = new_stage.model_dump()
    new_stage_dict = {
        "kind": "jupyter-notebook",
        "notebook_path": path,
        "environment": environment_name,
    }
    if inputs:
        new_stage_dict["inputs"] = new_stage_dump["inputs"]
    if outputs:
        new_stage_dict["outputs"] = new_stage_dump["outputs"]
    if always_run:
        new_stage_dict["always_run"] = always_run  # type: ignore
    new_stage_dict.update(
        {
            "html_storage": html_storage,
            "executed_ipynb_storage": executed_ipynb_storage,
            "cleaned_ipynb_storage": cleaned_ipynb_storage,
        }  # type: ignore
    )
    pipeline_dict["stages"][stage_name] = new_stage_dict
    # Update existing notebook if it exists, else append
    notebooks = ck_info.get("notebooks", [])
    updated = False
    for notebook in notebooks:
        if notebook.get("path") == path:
            notebook.update(
                {
                    "title": title,
                    "description": description,
                    "stage": stage_name,
                }
            )
            updated = True
            break
    if not updated:
        notebooks.append(
            {
                "path": path,
                "title": title,
                "description": description,
                "stage": stage_name,
            }
        )
    # Write calkit.yaml
    fpath = os.path.join(wdir, "calkit.yaml")
    ck_info["pipeline"] = pipeline_dict
    ck_info["notebooks"] = notebooks
    with open(fpath, "w") as f:
        calkit.ryaml.dump(ck_info, f)
    if must_be_rerun:
        raise RuntimeError(
            f"Notebook stage '{stage_name}' was modified while the pipeline "
            "was running; please run the pipeline again"
        )
    # TODO: Change to the correct working directory?
