"""Pipeline models."""

from __future__ import annotations

import base64
import json
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    ValidationError,
    field_validator,
    model_validator,
)
from typing_extensions import Annotated

from calkit.models.io import InputsFromStageOutputs, PathOutput
from calkit.models.iteration import (
    ExpandedParametersType,
    ParameterIteration,
    ParametersType,
    RangeIteration,
)
from calkit.notebooks import (
    get_cleaned_notebook_path,
    get_executed_notebook_path,
)


class StageIteration(BaseModel):
    """A model for the ``iterate_over`` key in a stage definition.

    If ``arg_name`` is a list, ``values`` also must be a list of lists with
    each sublist the length of ``arg_name``.
    """

    arg_name: str | list[str]
    values: list[
        int
        | float
        | str
        | RangeIteration
        | ParameterIteration
        | list[int | float | str]
    ]

    @field_validator("values")
    @classmethod
    def validate_values_structure(cls, v, info):
        """Validate that values are structured correctly based on arg_name."""
        arg_name = info.data.get("arg_name")
        # If arg_name is a list, check that values contains lists of the
        # correct length
        if isinstance(arg_name, list):
            expected_length = len(arg_name)
            for i, value in enumerate(v):
                # TODO: Support RangeIteration and ParameterIteration
                if isinstance(value, (RangeIteration, ParameterIteration)):
                    raise ValueError(
                        "RangeIteration and ParameterIteration are not "
                        "allowed when arg_name is a list"
                    )
                # Check if the value is a list and has the correct length
                if not isinstance(value, list):
                    raise ValueError(
                        f"When arg_name is a list, all values must be lists; "
                        f"Value at index {i} is {type(value).__name__}"
                    )
                if len(value) != expected_length:
                    raise ValueError(
                        f"When arg_name has {expected_length} elements, "
                        f"each value list must have {expected_length} "
                        f"elements;  Value at index {i} has {len(value)} "
                        "elements"
                    )
        return v

    def expand_values(
        self, params: ParametersType | ExpandedParametersType
    ) -> list[int | float | str | dict[str, int | float | str]]:
        vals = []
        if isinstance(self.arg_name, list):
            # Expand into a list of dictionaries, in which case the DVC arg
            # name must be auto-generated
            for vals_list in self.values:
                if not isinstance(vals_list, list):
                    raise ValueError(
                        "Expected a list for vals_list, got "
                        f"{type(vals_list).__name__}"
                    )
                v = {}
                for n, name in enumerate(self.arg_name):
                    v[name] = vals_list[n]
                vals.append(v)
        else:
            # arg_name is a string
            for vals_i in self.values:
                if isinstance(vals_i, ParameterIteration):
                    vals += vals_i.values_from_params(params)
                elif isinstance(vals_i, RangeIteration):
                    vals += vals_i.values
                else:
                    vals.append(vals_i)
        return vals


class Stage(BaseModel):
    """A stage in the pipeline."""

    name: str | None = None
    kind: Literal[
        "python-script",
        "latex",
        "matlab-script",
        "matlab-command",
        "docker-command",
        "shell-command",
        "shell-script",
        "jupyter-notebook",
        "r-script",
        "julia-script",
        "julia-command",
        "word-to-pdf",
    ]
    environment: str
    wdir: str | None = None
    # TODO: Support other input types
    inputs: list[str | InputsFromStageOutputs] = []
    outputs: list[str | PathOutput] = []  # TODO: Support database outputs
    always_run: bool = False
    iterate_over: list[StageIteration] | None = None
    description: str | None = None
    # Do not allow extra keys
    model_config = ConfigDict(extra="forbid")

    @property
    def dvc_cmd(self) -> str:
        raise NotImplementedError

    @property
    def dvc_deps(self) -> list[str]:
        deps = []
        for i in self.inputs:
            if isinstance(i, str) and i not in deps:
                deps.append(i)
        return deps

    @property
    def dvc_outs(self) -> list[str | dict]:
        outs = []
        for out in self.outputs:
            if isinstance(out, str):
                outs.append(out)
            elif isinstance(out, PathOutput):
                outs.append(
                    {
                        out.path: dict(
                            cache=True if out.storage == "dvc" else False,
                            persist=not out.delete_before_run,
                        )
                    }
                )
        return outs

    @property
    def xenv_cmd(self) -> str:
        if self.environment == "_system":
            return ""
        return f"calkit xenv -n {self.environment} --no-check --"

    def to_dvc(self) -> dict:
        """Convert to a DVC stage.

        Note that this does not handle ``from_stage_outputs`` input types,
        since that requires the entire pipeline.
        """
        cmd = self.dvc_cmd
        deps = self.dvc_deps
        for i in self.inputs:
            if isinstance(i, str) and i not in deps:
                deps.append(i)
        outs = self.dvc_outs
        stage = {"cmd": cmd, "deps": deps, "outs": outs}
        if self.wdir is not None:
            stage["wdir"] = self.wdir
        if self.always_run:
            stage["always_changed"] = True
        return stage


class PythonScriptStage(Stage):
    kind: Literal["python-script"] = "python-script"
    script_path: str
    args: list[str] = []

    @property
    def dvc_cmd(self) -> str:
        cmd = f"{self.xenv_cmd} python {self.script_path}"
        for arg in self.args:
            cmd += f" {arg}"
        return cmd

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps


class LatexStage(Stage):
    kind: Literal["latex"] = "latex"
    target_path: str
    latexmkrc_path: str | None = None
    verbose: bool = False
    force: bool = False
    synctex: bool = True

    @property
    def dvc_cmd(self) -> str:
        cmd = f"{self.xenv_cmd} latexmk -cd -norc -interaction=nonstopmode"
        if self.latexmkrc_path is not None:
            cmd += f" -r {self.latexmkrc_path}"
        if not self.verbose:
            cmd += " -silent"
        if self.force:
            cmd += " -f"
        if self.synctex:
            cmd += " -synctex=1"
        cmd += f" -pdf {self.target_path}"
        return cmd

    @property
    def dvc_deps(self) -> list[str]:
        deps = [self.target_path]
        if self.latexmkrc_path is not None:
            deps.append(self.latexmkrc_path)
        deps += super().dvc_deps
        return deps

    @property
    def dvc_outs(self) -> list[str | dict]:
        outs = super().dvc_outs
        out_path = PurePosixPath(
            self.target_path.removesuffix(".tex") + ".pdf"
        ).as_posix()
        if out_path not in outs:
            outs.append(out_path)
        return outs


class MatlabScriptStage(Stage):
    kind: Literal["matlab-script"]
    script_path: str

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps

    @property
    def dvc_cmd(self) -> str:
        cmd = self.xenv_cmd
        if self.environment == "_system":
            cmd += "matlab -batch"
        cmd += f" \"run('{self.script_path}');\""
        return cmd


class MatlabCommandStage(Stage):
    kind: Literal["matlab-command"] = "matlab-command"
    command: str

    @property
    def dvc_cmd(self) -> str:
        # We need to escape quotes in the command
        matlab_cmd = self.command.replace('"', '\\"')
        cmd = self.xenv_cmd
        if self.environment == "_system":
            cmd += "matlab -batch"
        cmd += f' "{matlab_cmd}"'
        return cmd


class ShellCommandStage(Stage):
    kind: Literal["shell-command"]
    command: str
    shell: Literal["sh", "bash", "zsh"] = "bash"

    @property
    def dvc_cmd(self) -> str:
        shell_cmd = self.command.replace('"', '\\"')
        cmd = self.xenv_cmd
        if self.shell == "zsh":
            norc_args = "-f"
        else:
            norc_args = "--noprofile --norc"
        cmd += f' {self.shell} {norc_args} -c "{shell_cmd}"'
        return cmd


class ShellScriptStage(Stage):
    kind: Literal["shell-script"]
    script_path: str
    args: list[str] = []
    shell: Literal["sh", "bash", "zsh"] = "bash"

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps

    @property
    def dvc_cmd(self) -> str:
        cmd = self.xenv_cmd
        if self.shell == "zsh":
            norc_args = "-f"
        else:
            norc_args = "--noprofile --norc"
        cmd += f" {self.shell} {norc_args} {self.script_path}"
        for arg in self.args:
            cmd += f" {arg}"
        return cmd


class DockerCommandStage(Stage):
    kind: Literal["docker-command"]
    command: str

    @property
    def dvc_cmd(self) -> str:
        return self.command


class RScriptStage(Stage):
    kind: Literal["r-script"]
    script_path: str
    args: list[str] = []

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps

    @property
    def dvc_cmd(self) -> str:
        cmd = (
            f"calkit xenv -n {self.environment} -- Rscript {self.script_path}"
        )
        for arg in self.args:
            cmd += f" {arg}"
        return cmd


class JuliaScriptStage(Stage):
    kind: Literal["julia-script"] = "julia-script"
    script_path: str

    @property
    def dvc_cmd(self) -> str:
        cmd = f'{self.xenv_cmd} "include(\\"{self.script_path}\\")"'
        return cmd

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps


class JuliaCommandStage(Stage):
    kind: Literal["julia-command"] = "julia-command"
    command: str

    @property
    def dvc_cmd(self) -> str:
        # We need to escape quotes in the command
        julia_cmd = self.command.replace('"', '\\"')
        cmd = f'{self.xenv_cmd} "{julia_cmd}"'
        return cmd


class SBatchStage(Stage):
    kind: Literal["sbatch"] = "sbatch"
    script_path: str
    args: list[str] = []
    sbatch_options: list[str] = []

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps

    @property
    def dvc_outs(self) -> list[str | dict]:
        # All outputs must be persistent, since ``calkit slurm batch``
        # handles deletion
        outs = super().dvc_outs
        final_outs = []
        for out in outs:
            if isinstance(out, str):
                final_outs.append({out: {"persist": True}})
            elif isinstance(out, dict):
                k = list(out.keys())[0]
                v = out[k]
                v["persist"] = True
                final_outs.append({k: v})
        return final_outs

    @property
    def dvc_cmd(self) -> str:
        cmd = f"calkit slurm batch --name {self.name}"
        if self.environment != "_system":
            cmd += f" --environment {self.environment}"
        for dep in self.dvc_deps:
            if dep != self.script_path:
                cmd += f" --dep {dep}"
        for out in self.outputs:
            # Determine if this is a non-persistent output
            if isinstance(out, str):
                cmd += f" --out {out}"
            elif isinstance(out, PathOutput) and out.delete_before_run:
                cmd += f" --out {out.path}"
        for opt in self.sbatch_options:
            cmd += f" -s {opt}"
        cmd += f" -- {self.script_path}"
        for arg in self.args:
            cmd += f" {arg}"
        return cmd


class JupyterNotebookStage(Stage):
    """A stage that runs a Jupyter notebook.

    Notebooks need to be cleaned of outputs so they can be used as DVC
    dependencies. This means we will have two DVC stages:

    1. Notebook cleaning.
    2. Notebook running, depending on the cleaned notebook, and optionally
       producing HTML output.

    Alternatively, we could force the use of ``nbstripout`` so the cleaned
    notebook is saved at the notebook path.

    TODO: Can/should we do something like Papermill and let users modify
    parameters in the notebook?

    With this paradigm, we want to force users treat their notebooks as
    needing to be run from top to bottom every time they change.
    """

    kind: Literal["jupyter-notebook"] = "jupyter-notebook"
    notebook_path: str
    cleaned_ipynb_storage: Literal["git", "dvc"] | None = "git"
    executed_ipynb_storage: Literal["git", "dvc"] | None = "dvc"
    html_storage: Literal["git", "dvc"] | None = "dvc"
    parameters: dict[str, Any] = {}
    language: Literal["python", "matlab", "julia"] = "python"

    def update_parameters(self, params: dict) -> None:
        """If we have any templated parameters, update those, e.g., from
        project-level parameters.

        This needs to happen before writing a DVC stage, so we can properly
        create JSON for the notebook.
        """
        updated_params = {}
        for k, v in self.parameters.items():
            # If we have something like {var_name} in v, replace it with the
            # value from params
            if isinstance(v, str) and v.startswith("{") and v.endswith("}"):
                var_name = v[1:-1]
                if var_name in params:
                    updated_params[k] = params[var_name]
                else:
                    updated_params[k] = v
            else:
                updated_params[k] = v
            # Try parsing as a RangeIteration and expanding
            try:
                updated_params[k] = RangeIteration.model_validate(
                    updated_params[k]
                ).values
            except ValidationError:
                pass
        self.parameters = updated_params

    @property
    def cleaned_notebook_path(self) -> str:
        return get_cleaned_notebook_path(self.notebook_path, as_posix=True)

    @property
    def executed_notebook_path(self) -> str:
        return get_executed_notebook_path(
            self.notebook_path,
            to="notebook",
            as_posix=True,
            parameters=self.parameters,
        )

    @property
    def html_path(self) -> str:
        return get_executed_notebook_path(
            self.notebook_path,
            to="html",
            as_posix=True,
            parameters=self.parameters,
        )

    @property
    def dvc_deps(self) -> list[str]:
        return [self.cleaned_notebook_path] + super().dvc_deps

    @property
    def dvc_cmd(self) -> str:
        cmd = (
            f"calkit nb execute --environment {self.environment} "
            f"--no-check --language {self.language}"
        )
        if self.html_storage:
            cmd += " --to html"
        if self.parameters:
            # If we have parameters, we need to pass them as JSON, escaping
            # double quotes
            params_json = json.dumps(self.parameters)
            # Now base64 encode
            params_base64 = base64.b64encode(
                params_json.encode("utf-8")
            ).decode("utf-8")
            cmd += f' --params-base64 "{params_base64}"'
        cmd += f' "{self.notebook_path}"'
        return cmd

    @property
    def dvc_outs(self) -> list[str | dict]:
        outs = super().dvc_outs
        exec_nb_path = self.executed_notebook_path
        outs.append(
            {exec_nb_path: {"cache": self.executed_ipynb_storage == "dvc"}}
        )
        if self.html_storage:
            html_path = self.html_path
            outs.append(
                {html_path: {"cache": self.html_storage == "dvc"}},
            )
        return outs

    @property
    def dvc_clean_stage(self) -> dict:
        """Create a DVC stage for notebook cleaning so the cleaned notebook
        can be used as a DVC dependency.

        TODO: Should we use Jupytext for this so diffs are nice?
        """
        clean_nb_path = self.cleaned_notebook_path
        stage = {
            "cmd": f'calkit nb clean "{self.notebook_path}"',
            "deps": [self.notebook_path],
            "outs": [
                {clean_nb_path: {"cache": self.cleaned_ipynb_storage == "dvc"}}
            ],
        }
        return stage

    @property
    def notebook_outputs(self) -> list[PathOutput]:
        """Return a list of special notebook outputs so their storage can be
        respected.
        """
        return [
            PathOutput(
                path=self.cleaned_notebook_path,
                storage=self.cleaned_ipynb_storage,
            ),
            PathOutput(
                path=self.executed_notebook_path,
                storage=self.executed_ipynb_storage,
            ),
            PathOutput(path=self.html_path, storage=self.html_storage),
        ]


class WordToPdfStage(Stage):
    kind: Literal["word-to-pdf"] = "word-to-pdf"
    word_doc_path: str
    environment: str = "_system"

    @property
    def dvc_deps(self) -> list[str]:
        return [self.word_doc_path] + super().dvc_deps

    @property
    def out_path(self) -> str:
        return PurePosixPath(
            self.word_doc_path.removesuffix(".docx") + ".pdf"
        ).as_posix()

    @property
    def dvc_outs(self) -> list[str | dict]:
        outs = super().dvc_outs
        out_path = self.out_path
        if out_path not in outs:
            outs.append(out_path)
        return outs

    @property
    def dvc_cmd(self) -> str:
        return (
            f'calkit office word-to-pdf "{self.word_doc_path}" '
            f'-o "{self.out_path}"'
        )


class Pipeline(BaseModel):
    stages: dict[
        str,
        Annotated[
            (
                PythonScriptStage
                | LatexStage
                | MatlabScriptStage
                | MatlabCommandStage
                | ShellCommandStage
                | ShellScriptStage
                | DockerCommandStage
                | RScriptStage
                | WordToPdfStage
                | JupyterNotebookStage
                | JuliaScriptStage
                | JuliaCommandStage
                | SBatchStage
            ),
            Discriminator("kind"),
        ],
    ]
    # Do not allow extra keys
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def set_stage_names(self):
        """Set the name field of each stage to match its key in the dict."""
        for stage_name, stage in self.stages.items():
            if stage.name is not None and stage.name != stage_name:
                raise ValueError(
                    f"Stage name '{stage.name}' does not match key "
                    f"'{stage_name}'"
                )
            stage.name = stage_name
        return self
