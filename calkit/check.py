"""Checking things."""

import os
from typing import Callable

import git
from git.exc import InvalidGitRepositoryError
from pydantic import BaseModel, computed_field
import calkit


INSTRUCTIONS_NOTE = (
    "Note that these could be as simple as telling the user to "
    "execute `calkit run`, so long as that will "
    "reproduce everything."
)


def _bool_to_check_x(val: bool) -> str:
    """Convert a boolean to a checkmark or an X."""
    if val:
        return "✅"
    else:
        return "❌"


class ReproCheck(BaseModel):
    has_pipeline: bool
    has_readme: bool
    instructions_in_readme: bool
    is_dvc_repo: bool
    is_git_repo: bool
    has_calkit_info: bool
    has_dev_container: bool
    n_environments: int
    n_stages: int
    stages_with_env: list[str]
    stages_without_env: list[str]
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
        if not self.has_readme:
            return (
                "There is no README.md file. "
                "Create one, and ensure it has basic instructions for "
                "reproducing this project's results. " + INSTRUCTIONS_NOTE
            )
        if not self.instructions_in_readme:
            return (
                "The README.md file doesn't contain "
                "basic instructions for reproducing results, "
                "so these should be added next. " + INSTRUCTIONS_NOTE
            )
        if not self.is_dvc_repo:
            return "DVC has not been initialized. Run `dvc init` next."
        if not self.n_dvc_remotes:
            return (
                "No DVC remotes have been defined. "
                "Run `calkit config remote` or `dvc remote add` next."
            )
        if not self.has_pipeline:
            return (
                "There is no DVC pipeline. "
                "Add some stages with `dvc stage add`."
            )
        if not self.has_calkit_info:
            return (
                "There is no `calkit.yaml` file. "
                "Add some artifacts with `calkit new`."
            )
        if self.n_environments == 0:
            return (
                "There are no computational environments defined. "
                "Add one with `calkit new environment`."
            )
        if self.n_stages_without_env > 0:
            return (
                f"There are {self.n_stages_without_env} stages "
                f"({', '.join(self.stages_without_env)}) "
                "with commands "
                "executed outside a defined environment. "
                "Define the environment for those next."
            )
        for artifact_type in ["datasets", "figures", "publications"]:
            n_bad = getattr(self, f"n_{artifact_type}_no_import_or_stage")
            if n_bad:
                return (
                    f"There are {n_bad} {artifact_type} that are neither "
                    "imported nor produced by a pipeline stage. "
                    "Define where they were imported from or create "
                    "stage(s) to produce them."
                )
        if not self.has_dev_container:
            return (
                "No dev container spec is defined. "
                "Create one with `calkit update devcontainer`."
            )

    @computed_field
    @property
    def n_datasets_with_import_or_stage(self) -> int:
        return self.n_datasets - self.n_datasets_no_import_or_stage

    @computed_field
    @property
    def n_figures_with_import_or_stage(self) -> int:
        return self.n_figures - self.n_figures_no_import_or_stage

    @computed_field
    @property
    def n_publications_with_import_or_stage(self) -> int:
        return self.n_publications - self.n_publications_no_import_or_stage

    @computed_field
    @property
    def n_stages_without_env(self) -> int:
        return len(self.stages_without_env)

    @computed_field
    @property
    def n_stages_with_env(self) -> int:
        return len(self.stages_with_env)

    def to_pretty(self) -> str:
        """Format as a nice string to print."""
        txt = f"Is a Git repo: {_bool_to_check_x(self.is_git_repo)}\n"
        txt += f"Has README.md: {_bool_to_check_x(self.has_readme)}\n"
        txt += (
            f"Instructions in README.md: "
            f"{_bool_to_check_x(self.instructions_in_readme)}\n"
        )
        txt += f"DVC initialized: {_bool_to_check_x(self.is_dvc_repo)}\n"
        txt += f"DVC remote defined: {_bool_to_check_x(self.n_dvc_remotes)}\n"
        txt += f"Has pipeline: {_bool_to_check_x(self.has_pipeline)}\n"
        txt += f"Has Calkit info: {_bool_to_check_x(self.has_calkit_info)}\n"
        txt += (
            f"Has dev container spec: "
            f"{_bool_to_check_x(self.has_dev_container)}\n"
        )
        txt += (
            f"Environments defined: {self.n_environments} "
            f"{_bool_to_check_x(self.n_environments)}\n"
        )
        txt += (
            "Pipeline stages run in an environment: "
            f"{self.n_stages_with_env}/{self.n_stages} "
            f"{_bool_to_check_x(self.n_stages_without_env == 0)}\n"
        )
        for artifact_type in ["datasets", "figures", "publications"]:
            n = getattr(self, f"n_{artifact_type}")
            n_bad = getattr(self, f"n_{artifact_type}_no_import_or_stage")
            n_good = getattr(self, f"n_{artifact_type}_with_import_or_stage")
            txt += (
                f"{artifact_type.capitalize()} imported or "
                f"created by pipeline: {n_good}/{n} "
                f"{_bool_to_check_x(n_bad == 0)}\n"
            )
        if self.recommendation:
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
        git.Repo(wdir)
        res["is_git_repo"] = True
    except InvalidGitRepositoryError:
        res["is_git_repo"] = False
    res["is_dvc_repo"] = os.path.isfile(os.path.join(wdir, ".dvc", "config"))
    res["has_pipeline"] = os.path.isfile(os.path.join(wdir, "dvc.yaml"))
    res["has_calkit_info"] = os.path.isfile(os.path.join(wdir, "calkit.yaml"))
    res["has_dev_container"] = os.path.isfile(
        os.path.join(wdir, ".devcontainer", "devcontainer.json")
    )
    # Check README for at least minimal instructions
    readme_path = os.path.join(wdir, "README.md")
    if os.path.isfile(readme_path):
        res["has_readme"] = True
        with open(readme_path) as f:
            readme_txt = f.read().lower()
        res["instructions_in_readme"] = (
            ("getting started" in readme_txt)
            or ("instructions" in readme_txt)
            or ("how to run" in readme_txt)
            or ("how to reproduce" in readme_txt)
            or ("calkit" in readme_txt)
        )
    else:
        res["has_readme"] = False
        res["instructions_in_readme"] = False
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
    stages_no_env = []
    stages_with_env = []
    for stage_name, stage in stages.items():
        if "foreach" in stage:
            cmd = stage.get("do", {}).get("cmd", "")
        else:
            cmd = stage.get("cmd", "")
        if (
            "calkit" not in cmd
            and "conda run" not in cmd
            and "mamba run" not in cmd
            and "docker run" not in cmd
            and "renv::restore()" not in cmd
        ):
            stages_no_env.append(stage_name)
        else:
            stages_with_env.append(stage_name)
    res["stages_without_env"] = stages_no_env
    res["stages_with_env"] = stages_with_env
    # DVC remotes
    dvc_remotes = calkit.dvc.get_remotes(wdir=wdir)
    res["n_dvc_remotes"] = len(dvc_remotes)
    return ReproCheck.model_validate(res)
