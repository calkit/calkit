"""Pipeline models."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, field_validator
from typing_extensions import Annotated

from calkit.models.io import InputsFromStageOutputs, PathOutput
from calkit.models.iteration import (
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
        self, params: ParametersType
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

    kind: Literal[
        "python-script",
        "latex",
        "matlab-script",
        "docker-command",
        "shell-command",
        "shell-script",
        "jupyter-notebook",
        "r-script",
        "julia-script",
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
        return f"calkit xenv -n {self.environment} --no-check"

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
        cmd = f"{self.xenv_cmd} -- python {self.script_path}"
        for arg in self.args:
            cmd += f" {arg}"
        return cmd

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps


class LatexStage(Stage):
    kind: Literal["latex"] = "latex"
    target_path: str
    verbose: bool = False
    force: bool = False
    synctex: bool = True

    @property
    def dvc_cmd(self) -> str:
        cmd = f"{self.xenv_cmd} -- latexmk -cd -interaction=nonstopmode"
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
        return [self.target_path] + super().dvc_deps

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
        return f"{self.xenv_cmd} -- \"run('{self.script_path}');\""


class ShellCommandStage(Stage):
    kind: Literal["shell-command"]
    command: str
    shell: Literal["sh", "bash", "zsh"] = "bash"

    @property
    def dvc_cmd(self) -> str:
        cmd = ""
        if self.environment != "_system":
            cmd = f"{self.xenv_cmd} -- "
        if self.shell == "zsh":
            norc_args = "-f"
        else:
            norc_args = "--noprofile --norc"
        cmd += f'{self.shell} {norc_args} -c "{self.command}"'
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
        cmd = ""
        if self.environment != "_system":
            cmd = f"{self.xenv_cmd} -- "
        if self.shell == "zsh":
            norc_args = "-f"
        else:
            norc_args = "--noprofile --norc"
        cmd += f"{self.shell} {norc_args} {self.script_path}"
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
        cmd = f'{self.xenv_cmd} -- "include(\\"{self.script_path}\\")"'
        return cmd

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps


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
        cmd = f"calkit nb execute --environment {self.environment} --no-check"
        if self.html_storage:
            cmd += " --to html"
        for k, v in self.parameters.items():
            cmd += f" -p {k}={v}"
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
                | ShellCommandStage
                | ShellScriptStage
                | DockerCommandStage
                | RScriptStage
                | WordToPdfStage
                | JupyterNotebookStage
                | JuliaScriptStage
            ),
            Discriminator("kind"),
        ],
    ]
    # Do not allow extra keys
    model_config = ConfigDict(extra="forbid")
