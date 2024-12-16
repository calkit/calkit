"""Checking things."""

import os
from typing import Callable

import git
from git.exc import InvalidGitRepositoryError
from pydantic import BaseModel, computed_field
import calkit


def _bool_to_check_x(val: bool) -> str:
    """Convert a boolean to a checkmark or an X.

    TODO: Need to detect if the terminal can handle these characters so we
    don't get a UnicodeEncodeError, e.g., on Git Bash.
    """
    if val:
        return "✅"
    else:
        return "❌"


class ReproCheck(BaseModel):
    has_pipeline: bool
    is_dvc_repo: bool
    is_git_repo: bool
    has_calkit_info: bool
    n_environments: int
    n_stages: int
    n_stages_without_env: int
    n_datasets: int
    n_datasets_no_import_or_stage: int
    n_figures: int
    n_figures_no_import_or_stage: int
    n_publications: int
    n_publications_no_import_or_stage: int
    n_dvc_remotes: int
    # TODO: Check calkit remotes are authenticated

    @computed_field
    @property
    def recommendation(self) -> str | None:
        """Formulate a recommendation for the project."""
        if not self.is_git_repo:
            return "Since this is not a Git repo, run `git init` next."
        if not self.is_dvc_repo:
            return "DVC has not been initialized. Run `dvc init` next."
        if not self.n_dvc_remotes:
            return (
                "No DVC remotes have been defined. "
                "Run `calkit config setup-remote` or `dvc remote add` next."
            )
        if not self.has_pipeline:
            return (
                "There is no DVC pipeline. "
                "Add some stages with `dvc stage add`."
            )
        if not self.has_calkit_info:
            return (
                "There is no `calkit.yaml` file. "
                "Add some artifacts with `calkit new `."
            )
        if self.n_environments == 0:
            return (
                "There are no computational environments defined. "
                "Add one with `calkit new environment`."
            )
        if self.n_stages_without_env > 0:
            return (
                f"There are {self.n_stages_without_env} stages with commands "
                "executed outside a defined environment. "
                "Define the environment for those."
            )

    def to_pretty(self) -> str:
        """Format as a nice string to print."""
        txt = f"Is a Git repo: {_bool_to_check_x(self.is_git_repo)}\n"
        txt += f"DVC initialized: {_bool_to_check_x(self.is_dvc_repo)}\n"
        txt += f"DVC remote defined: {_bool_to_check_x(self.n_dvc_remotes)}\n"
        txt += f"Has pipeline: {_bool_to_check_x(self.has_pipeline)}\n"
        txt += f"Has Calkit info: {_bool_to_check_x(self.has_calkit_info)}\n"
        txt += f"Environments defined: {self.n_environments}\n"
        txt += (
            "Pipeline stages run outside environment: "
            f"{self.n_stages_without_env}/{self.n_stages}\n"
        )
        for artifact_type in ["datasets", "figures", "publications"]:
            n = getattr(self, f"n_{artifact_type}")
            n_bad = getattr(self, f"n_{artifact_type}_no_import_or_stage")
            txt += (
                f"{artifact_type.capitalize()} not imported "
                f"or created by pipeline: {n_bad}/{n}\n"
            )
        txt += f"\nRecommendation: {self.recommendation}\n"
        return txt


def check_reproducibility(
    wdir: str = ".", log_func: Callable = None
) -> ReproCheck:
    """Check the reproducibility of a project."""
    res = dict()
    if log_func is None:
        log_func = print
    try:
        repo = git.Repo(wdir)
        res["is_git_repo"] = True
    except InvalidGitRepositoryError:
        res["is_git_repo"] = False
    res["is_dvc_repo"] = os.path.isfile(os.path.join(wdir, ".dvc", "config"))
    res["has_pipeline"] = os.path.isfile(os.path.join(wdir, "dvc.yaml"))
    res["has_calkit_info"] = os.path.isfile(os.path.join(wdir, "calkit.yaml"))
    ck_info = calkit.load_calkit_info(wdir=wdir, process_includes=False)
    pipeline = calkit.dvc.read_pipeline(wdir=wdir)
    # Check for non-imported artifacts not produced by the pipeline
    for artifact_type in ["datasets", "figures", "publications"]:
        artifacts = ck_info.get(artifact_type, [])
        res[f"n_{artifact_type}"] = len(artifacts)
        res[f"n_{artifact_type}_no_import_or_stage"] = len(
            [
                a
                for a in artifacts
                if a.get("stage") is None and a.get("imported_from") is None
            ]
        )
    res["n_environments"] = len(ck_info.get("environments", {}))
    # Check for stages not run with environments
    stages = pipeline.get("stages", {})
    res["n_stages"] = len(stages)
    n_stages_no_env = 0
    for stage_name, stage in stages.items():
        cmd = stage.get("cmd", "")
        if (
            "calkit runenv" not in cmd
            and "conda run" not in cmd
            and "mamba run" not in cmd
            and "docker run" not in cmd
        ):
            n_stages_no_env += 1
    res["n_stages_without_env"] = n_stages_no_env
    # DVC remotes
    dvc_remotes = calkit.dvc.get_remotes(wdir=wdir)
    res["n_dvc_remotes"] = len(dvc_remotes)
    return ReproCheck.model_validate(res)
