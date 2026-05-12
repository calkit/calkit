"""Pipeline models."""

from __future__ import annotations

import base64
import json
import shlex
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Discriminator,
    PrivateAttr,
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


def _check_path_relative_and_child_of_cwd(s: str) -> str:
    p = Path(s)
    # Enforce that the path is relative
    if p.is_absolute():
        raise ValueError(f"Path must be relative: {p}")
    # Enforce that the path is a child of the (resolved) CWD
    cwd = Path.cwd().resolve()
    # Resolve the path relative to the resolved CWD to get a full path for
    # comparison
    absolute_path = p.resolve(strict=False)
    # Check if the absolute path starts with the resolved CWD, ensuring it's a
    # child
    try:
        absolute_path.relative_to(cwd)
    except ValueError:
        raise ValueError(
            f"Path is not a child of the current working directory: {p}"
        )
    return p.as_posix()


RelativeChildPathString = Annotated[
    str, AfterValidator(_check_path_relative_and_child_of_cwd)
]


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


EnvDefaultsMode = Literal["ignore", "replace", "merge"]


class StageSchedulerOptions(BaseModel):
    """Parameters for running a stage on a job scheduler (SLURM or PBS).

    The environment-level ``default_options`` / ``default_setup`` are
    applied by ``calkit scheduler batch`` at submission time.
    The mode for each list is controlled independently by
    ``env_default_options`` and ``env_default_setup``:

    - ``replace`` (default): if the stage provides values, those are used
      and env defaults are skipped; if the stage's list is empty, env
      defaults fill in.
    - ``merge``: env defaults are prepended to whatever the stage
      provides (the scheduler's last-occurrence-wins behavior keeps stage
      values on top of any conflicts).
    - ``ignore``: env defaults are never applied, regardless of whether
      the stage provided any values.
    """

    options: list[str] | None = None
    setup: list[str] | None = None
    env_default_options: EnvDefaultsMode = "replace"
    env_default_setup: EnvDefaultsMode = "replace"
    log_path: str | None = None
    log_storage: Literal["git", "dvc"] | None = "git"


class Stage(BaseModel):
    """A stage in the pipeline."""

    name: str | None = None
    kind: Literal[
        "python-script",
        "latex",
        "matlab-script",
        "matlab-command",
        "command",
        "docker-command",
        "shell-command",
        "shell-script",
        "jupyter-notebook",
        "r-script",
        "julia-script",
        "julia-command",
        "word-to-pdf",
        "map-paths",
    ]
    environment: str
    wdir: str | None = None
    # TODO: Support other input types
    inputs: list[str | InputsFromStageOutputs] = []
    outputs: list[str | PathOutput] = []  # TODO: Support database outputs
    always_run: bool = False
    iterate_over: list[StageIteration] | None = None
    description: str | None = None
    scheduler: StageSchedulerOptions | None = None
    # Do not allow extra keys
    model_config = ConfigDict(extra="forbid")
    # Resolved at pipeline-compilation time by set_stage_scheduler_options;
    # all scheduler kinds now emit ``calkit scheduler batch``.
    _scheduler_cli_alias: str = PrivateAttr(default="scheduler")
    # The outer env's kind (``slurm`` or ``pbs``) when this stage runs
    # through a job scheduler; used to derive the default log path so the
    # log file can be tracked as a DVC output.
    _scheduler_kind: str | None = PrivateAttr(default=None)

    @model_validator(mode="before")
    @classmethod
    def migrate_slurm_field(cls, data: Any) -> Any:
        """Auto-migrate the old ``slurm:`` field to ``scheduler:``."""
        if not isinstance(data, dict) or "slurm" not in data:
            return data
        if data.get("scheduler") is not None:
            raise ValueError(
                "Stage has both 'slurm' and 'scheduler' options set; "
                "remove 'slurm' (use 'scheduler' only)"
            )
        data["scheduler"] = data.pop("slurm")
        return data

    @property
    def outer_environment(self) -> str:
        """The outer environment of the stage, in case it is nested."""
        from calkit.environments import COMPOSITE_ENV_SEP

        if self.environment.count(COMPOSITE_ENV_SEP) == 1:
            return self.environment.split(COMPOSITE_ENV_SEP)[0]
        elif self.environment.count(COMPOSITE_ENV_SEP) > 1:
            raise ValueError(
                f"Invalid environment name '{self.environment}': more than one "
                f"composite environment separator '{COMPOSITE_ENV_SEP}'"
            )
        return self.environment

    @property
    def inner_environment(self) -> str:
        """The inner environment of the stage, in case it is nested."""
        from calkit.environments import COMPOSITE_ENV_SEP

        if self.environment.count(COMPOSITE_ENV_SEP) == 1:
            return self.environment.split(COMPOSITE_ENV_SEP)[1]
        elif self.environment.count(COMPOSITE_ENV_SEP) > 1:
            raise ValueError(
                f"Invalid environment name '{self.environment}': more than one "
                f"composite environment separator '{COMPOSITE_ENV_SEP}'"
            )
        return self.environment

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
                            cache=out.storage == "dvc",
                            persist=not out.delete_before_run,
                        )
                    }
                )
        return outs

    @property
    def xenv_cmd(self) -> str:
        """Return the command prefix for running in an environment, if
        needed.

        When a stage uses a job-scheduler env (SLURM or PBS), the prefix
        is a ``calkit scheduler batch`` invocation. If the scheduler env
        wraps a separate inner env (composite syntax
        ``<scheduler-env>:<inner-env>``), we additionally wrap the
        scheduled command with ``calkit xenv -n <inner-env>``. For a plain
        scheduler env (no inner runtime needed), we skip the inner xenv
        wrap and let the user's command run directly inside the job.
        """
        if self.environment == "_system" and self.scheduler is None:
            return ""
        if self.scheduler is not None:
            sched_cmd = self.scheduler_cmd
            if self.inner_environment == self.outer_environment:
                # Plain scheduler env: no inner runtime to dispatch into.
                return sched_cmd + " --command --"
            return (
                sched_cmd
                + " --command -- "
                + f"calkit xenv -n {self.inner_environment} --no-check --"
            )
        return f"calkit xenv -n {self.inner_environment} --no-check --"

    @property
    def scheduler_cmd(self) -> str:
        """Build the ``calkit scheduler batch`` invocation for this stage."""
        if self.scheduler is None:
            raise ValueError("Stage has no scheduler options")
        opts = self.scheduler
        cmd = f"calkit {self._scheduler_cli_alias} batch --name {self.name}"
        if self.iterate_over is not None:
            arg_names = []
            for item in self.iterate_over:
                if isinstance(item.arg_name, list):
                    arg_names += item.arg_name
                else:
                    arg_names.append(item.arg_name)
            cmd += "@" + ",".join(
                [f"{{{arg_name}}}" for arg_name in arg_names]
            )
        # Only emit the flag when the stage overrides the default mode
        # (``replace``); this keeps the compiled cmd minimal.
        if opts.env_default_options != "replace":
            cmd += f" --env-default-options {opts.env_default_options}"
        if opts.env_default_setup != "replace":
            cmd += f" --env-default-setup {opts.env_default_setup}"
        if self.environment != "_system":
            cmd += f" --environment {self.outer_environment}"
        if opts.log_path is not None:
            cmd += f" --log-path {shlex.quote(opts.log_path)}"
        for dep in self.dvc_deps:
            cmd += f" --dep {dep}"
        for out in self.outputs:
            if isinstance(out, str):
                cmd += f" --out {out}"
            elif isinstance(out, PathOutput) and out.delete_before_run:
                cmd += f" --out {out.path}"
        # Check for any missing outs in dvc_outs (e.g., implicit notebook
        # stage outputs).
        for out in self.dvc_outs:
            if isinstance(out, str):
                txt = f" --out {out}"
                if txt not in cmd:
                    cmd += txt
            elif isinstance(out, dict):
                out_path = list(out.keys())[0]
                if not out[out_path].get("persist", False):
                    txt = f" --out {out_path}"
                    if txt not in cmd:
                        cmd += txt
        if opts.options is not None:
            for opt in opts.options:
                cmd += f" -s {opt}"
        if opts.setup is not None:
            for setup_cmd in opts.setup:
                cmd += f" --setup {shlex.quote(setup_cmd)}"
        return cmd

    @property
    def scheduler_log_output(self) -> PathOutput | None:
        """The log file produced by a scheduler-batched stage.

        Mirrors the default ``calkit scheduler batch`` chooses at runtime
        (``.calkit/<kind>/logs/<name>.out``) unless the stage explicitly
        sets ``scheduler.log_path``. For iterated stages, iteration arg
        names are interpolated as ``{arg}`` placeholders so the DVC
        matrix-format pass substitutes them into the per-item path.
        """
        if self.scheduler is None or self._scheduler_kind is None:
            return None
        log_path = self.scheduler.log_path
        if log_path is None:
            log_path = f".calkit/{self._scheduler_kind}/logs/{self.name}"
            if self.iterate_over is not None:
                arg_names = []
                for item in self.iterate_over:
                    if isinstance(item.arg_name, list):
                        arg_names += item.arg_name
                    else:
                        arg_names.append(item.arg_name)
                for arg_name in arg_names:
                    log_path += f"/{{{arg_name}}}"
            log_path += ".out"
        return PathOutput(
            path=log_path,
            storage=self.scheduler.log_storage,
            delete_before_run=False,
        )

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
        log_out = self.scheduler_log_output
        if log_out is not None:
            log_entry = {
                log_out.path: {
                    "cache": log_out.storage == "dvc",
                    "persist": True,
                }
            }
            if not any(
                isinstance(o, dict) and log_out.path in o for o in outs
            ):
                outs.append(log_entry)
        stage = {"cmd": cmd, "deps": deps, "outs": outs}
        if self.wdir is not None:
            stage["wdir"] = self.wdir
        if self.always_run:
            stage["always_changed"] = True
        return stage


class PythonScriptStage(Stage):
    kind: Literal["python-script"] = "python-script"
    script_path: RelativeChildPathString
    args: list[str] = []

    @property
    def dvc_cmd(self) -> str:
        cmd = f"{self.xenv_cmd} python {self.script_path}"
        for arg in self.args:
            cmd += f" {arg}"
        return cmd.strip()

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps


class MapPathsStage(Stage):
    class CopyFileToFile(BaseModel):
        kind: Literal["file-to-file"] = "file-to-file"
        src: str
        dest: str

        @property
        def arg(self) -> str:
            return f"--{self.kind} '{self.src}->{self.dest}'"

        @property
        def out_path(self) -> str:
            return self.dest

    class CopyFileToDir(BaseModel):
        kind: Literal["file-to-dir"] = "file-to-dir"
        src: str
        dest: str

        @property
        def arg(self) -> str:
            return f"--{self.kind} '{self.src}->{self.dest}'"

        @property
        def out_path(self) -> str:
            return Path(self.dest, Path(self.src).name).as_posix()

    class DirToDirMerge(BaseModel):
        kind: Literal["dir-to-dir-merge"] = "dir-to-dir-merge"
        src: str
        dest: str

        @property
        def arg(self) -> str:
            return f"--{self.kind} '{self.src}->{self.dest}'"

        @property
        def out_path(self) -> str:
            return self.dest

    class DirToDirReplace(BaseModel):
        kind: Literal["dir-to-dir-replace"] = "dir-to-dir-replace"
        src: str
        dest: str

        @property
        def arg(self) -> str:
            return f"--{self.kind} '{self.src}->{self.dest}'"

        @property
        def out_path(self) -> str:
            return self.dest

    kind: Literal["map-paths"] = "map-paths"
    environment: str = "_system"
    paths: list[
        Annotated[
            (CopyFileToFile | CopyFileToDir | DirToDirMerge | DirToDirReplace),
            Discriminator("kind"),
        ]
    ]

    @property
    def dvc_cmd(self) -> str:
        cmd = "calkit map-paths"
        for path in self.paths:
            cmd += f" {path.arg}"
        return cmd

    @property
    def dvc_deps(self) -> list[str]:
        deps = []
        for path in self.paths:
            deps.append(path.src)
        return deps + super().dvc_deps

    @property
    def dvc_outs(self) -> list[dict]:
        """All DVC outs should not be cached, since they are just copies."""
        outs = []
        for path in self.paths:
            outs.append({path.out_path: {"cache": False, "persist": True}})
        return outs + super().dvc_outs


class LatexStage(Stage):
    kind: Literal["latex"] = "latex"
    target_path: str
    latexmkrc_path: str | None = None
    pdf_storage: Literal["git", "dvc"] | None = "dvc"
    verbose: bool = False
    force: bool = False
    synctex: bool = True

    @property
    def dvc_cmd(self) -> str:
        cmd = f"calkit latex build -e {self.environment} --no-check"
        if self.latexmkrc_path is not None:
            cmd += f" -r {self.latexmkrc_path}"
        if self.verbose:
            cmd += " --verbose"
        if self.force:
            cmd += " -f"
        if not self.synctex:
            cmd += " --no-synctex"
        cmd += f" {self.target_path}"
        return cmd

    @property
    def dvc_deps(self) -> list[str]:
        deps = [self.target_path] + super().dvc_deps
        if self.latexmkrc_path is not None:
            deps.append(self.latexmkrc_path)
        return deps

    @property
    def dvc_outs(self) -> list[str | dict]:
        outs = super().dvc_outs
        out_path = Path(
            self.target_path.removesuffix(".tex") + ".pdf"
        ).as_posix()
        # If the PDF output is already in outs use that
        # Otherwise, create a DVC output from pdf_storage and add it to outs
        out_paths = []
        for out in outs:
            if isinstance(out, str):
                out_paths.append(out)
            elif isinstance(out, dict):
                out_paths.append(list(out.keys())[0])
        if out_path in out_paths:
            return outs
        if self.pdf_storage != "dvc":
            out_dict = {out_path: {"cache": False}}
            outs.append(out_dict)
        else:
            outs.append(out_path)
        return outs


class JsonToLatexStage(Stage):
    kind: Literal["json-to-latex"] = "json-to-latex"
    environment: str = "_system"
    command_name: str | None = None
    format: dict[str, str] | None = None

    @property
    def dvc_cmd(self) -> str:
        cmd = "calkit latex from-json"
        for input_path in self.inputs:
            cmd += f" '{input_path}'"
        for out in self.outputs:
            if isinstance(out, str):
                out_path = out
            elif isinstance(out, PathOutput):
                out_path = out.path
            cmd += f" --output '{out_path}'"
        if self.command_name is not None:
            cmd += f" --command {self.command_name}"
        if self.format is not None:
            fmt_json = json.dumps(self.format)
            cmd += f" --format-json '{fmt_json}'"
        return cmd

    @property
    def dvc_outs(self) -> list[str | dict]:
        """DVC outs should be stored with Git by default."""
        outs = []
        for out in self.outputs:
            if isinstance(out, str):
                outs.append({out: dict(cache=False, persist=False)})
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


class MatlabScriptStage(Stage):
    kind: Literal["matlab-script"]
    script_path: RelativeChildPathString
    matlab_path: RelativeChildPathString | None = None

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps

    @property
    def dvc_cmd(self) -> str:
        cmd = self.xenv_cmd
        if self.environment == "_system":
            cmd += "matlab -noFigureWindows -batch"
        matlab_cmd = ""
        if self.matlab_path is not None:
            matlab_cmd += f"addpath(genpath('{self.matlab_path}')); "
        matlab_cmd += f"run('{self.script_path}');"
        cmd += f' "{matlab_cmd}"'
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
            cmd += "matlab -noFigureWindows -batch"
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
        return cmd.strip()


class ShellScriptStage(Stage):
    kind: Literal["shell-script"]
    script_path: RelativeChildPathString
    args: list[str] = []
    shell: Literal["sh", "bash", "zsh"] = "bash"

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps

    @property
    def dvc_cmd(self) -> str:
        # For shell scripts on a plain scheduler env (no inner runtime),
        # hand the script straight to the scheduler submit command rather
        # than wrapping with xenv.
        if (
            self.scheduler is not None
            and self.inner_environment == self.outer_environment
        ):
            cmd = self.scheduler_cmd
            cmd += f" -- {self.script_path}"
            for arg in self.args:
                cmd += f" {arg}"
            # Avoid duplicating the script path as both --dep and target.
            dep_txt = f"--dep {self.script_path} "
            if dep_txt in cmd:
                cmd = cmd.replace(dep_txt, "")
            return cmd
        cmd = self.xenv_cmd
        if self.shell == "zsh":
            norc_args = "-f"
        else:
            norc_args = "--noprofile --norc"
        cmd += f" {self.shell} {norc_args} {self.script_path}"
        for arg in self.args:
            cmd += f" {arg}"
        return cmd.strip()


class DockerCommandStage(Stage):
    kind: Literal["docker-command"]
    command: str

    @property
    def dvc_cmd(self) -> str:
        return self.command


class CommandStage(Stage):
    kind: Literal["command"] = "command"
    command: str

    @property
    def dvc_cmd(self) -> str:
        return f"{self.xenv_cmd} {self.command}".strip()


class RScriptStage(Stage):
    kind: Literal["r-script"]
    script_path: RelativeChildPathString
    args: list[str] = []

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps

    @property
    def dvc_cmd(self) -> str:
        cmd = f"{self.xenv_cmd} Rscript {self.script_path}"
        for arg in self.args:
            cmd += f" {arg}"
        return cmd.strip()


class JuliaScriptStage(Stage):
    kind: Literal["julia-script"] = "julia-script"
    script_path: RelativeChildPathString
    args: list[str] = []

    @property
    def dvc_cmd(self) -> str:
        cmd = f'{self.xenv_cmd} "{self.script_path}"'
        for arg in self.args:
            cmd += f" {arg}"
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
        cmd = f'{self.xenv_cmd} -e "{julia_cmd}"'
        return cmd


class SBatchStage(Stage):
    kind: Literal["sbatch"] = "sbatch"
    script_path: RelativeChildPathString
    args: list[str] = []
    sbatch_options: list[str] = []
    log_path: str | None = None
    log_storage: Literal["git", "dvc"] | None = "git"

    @property
    def log_output(self) -> PathOutput:
        log_path = self.log_path
        if log_path is None:
            log_path = f".calkit/slurm/logs/{self.name}"
            if self.iterate_over is not None:
                arg_names = []
                for item in self.iterate_over:
                    if isinstance(item.arg_name, list):
                        arg_names += item.arg_name
                    else:
                        arg_names.append(item.arg_name)
                for arg_name in arg_names:
                    log_path += f"/{{{arg_name}}}"
            log_path += ".out"
        return PathOutput(
            path=log_path,
            storage=self.log_storage,
            delete_before_run=False,
        )

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps

    @property
    def dvc_outs(self) -> list[str | dict]:
        # All outputs must be persistent, since ``calkit slurm batch``
        # handles deletion
        outs = super().dvc_outs
        # Add log file output
        log_path = self.log_output.path
        if self.log_storage == "dvc":
            outs.append({log_path: {"cache": True, "persist": True}})
        else:
            outs.append({log_path: {"cache": False, "persist": True}})
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
        if self.scheduler is None:
            self.scheduler = StageSchedulerOptions()
        self.scheduler.options = self.sbatch_options + (
            self.scheduler.options or []
        )
        # Dedupe options but retain order
        deduped_options = []
        for opt in self.scheduler.options:
            if opt not in deduped_options:
                deduped_options.append(opt)
        self.scheduler.options = deduped_options
        self.scheduler.log_path = self.log_path
        self.scheduler.log_storage = self.log_storage
        cmd = self.scheduler_cmd
        cmd += f" -- {self.script_path}"
        for arg in self.args:
            cmd += f" {arg}"
        # Remove the script path from deps for backward compatibility
        dep_txt = f"--dep {self.script_path} "
        if dep_txt in cmd:
            cmd = cmd.replace(dep_txt, "")
        return cmd


class JupyterNotebookStage(Stage):
    """A stage that runs a Jupyter notebook.

    Notebooks need to be cleaned of outputs so they can be used as DVC
    dependencies. The ``status`` and ``run`` commands handle this
    automatically.
    """

    kind: Literal["jupyter-notebook"] = "jupyter-notebook"
    notebook_path: str
    cleaned_ipynb_storage: Literal["git", "dvc"] | None = None
    executed_ipynb_storage: Literal["git", "dvc"] | None = "dvc"
    html_storage: Literal["git", "dvc"] | None = "dvc"
    parameters: dict[str, Any] = {}
    language: Literal["python", "matlab", "julia"] | None = None

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
        from calkit.notebooks import get_cleaned_notebook_path

        return get_cleaned_notebook_path(self.notebook_path, as_posix=True)

    @property
    def executed_notebook_path(self) -> str:
        from calkit.notebooks import get_executed_notebook_path

        return get_executed_notebook_path(
            self.notebook_path,
            to="notebook",
            as_posix=True,
            parameters=self.parameters,
        )

    @property
    def html_path(self) -> str:
        from calkit.notebooks import get_executed_notebook_path

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
            f"calkit nb execute --environment {self.inner_environment} "
            "--no-check"
        )
        if self.language is not None:
            cmd += f" --language {self.language}"
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
        if self.scheduler is not None:
            cmd = self.scheduler_cmd + " --command -- " + cmd
        return cmd

    @property
    def dvc_outs(self) -> list[str | dict]:
        outs = super().dvc_outs
        exec_nb_path = self.executed_notebook_path
        if self.executed_ipynb_storage:
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
        return Path(
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
                | JsonToLatexStage
                | MatlabScriptStage
                | MatlabCommandStage
                | ShellCommandStage
                | ShellScriptStage
                | DockerCommandStage
                | CommandStage
                | RScriptStage
                | WordToPdfStage
                | JupyterNotebookStage
                | JuliaScriptStage
                | JuliaCommandStage
                | SBatchStage
                | MapPathsStage
            ),
            Discriminator("kind"),
        ],
    ]
    # Do not allow extra keys
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def set_stage_names(self) -> Pipeline:
        """Set the name field of each stage to match its key in the dict."""
        for stage_name, stage in self.stages.items():
            if stage.name is not None and stage.name != stage_name:
                raise ValueError(
                    f"Stage name '{stage.name}' does not match key "
                    f"'{stage_name}'"
                )
            stage.name = stage_name
        return self

    def set_stage_scheduler_options(
        self, environments: dict[str, dict]
    ) -> None:
        """Validate and initialize scheduler (SLURM/PBS) options on stages.

        For each stage whose outer environment is a job scheduler (SLURM or
        PBS), this validates the environment configuration and sets
        ``stage.scheduler`` so the stage's ``xenv_cmd`` emits
        ``calkit scheduler batch``.

        Environment-level ``default_options`` and ``default_setup`` are NOT
        merged into the stage here; the batch CLI applies them at submission
        time so the pipeline does not need to be recompiled when env defaults
        change.
        """
        # Stage kinds that don't require a separate inner runtime, so they
        # can run on a plain (non-composite) scheduler env. Anything else
        # must use a composite env like ``<scheduler-env>:<inner-env>``.
        # ``sbatch`` is the legacy stage type; convert_sbatch_stages() should
        # run first, but it stays here as a safety net.
        plain_ok_kinds = {
            "shell-script",
            "shell-command",
            "command",
            "sbatch",
        }
        # Both scheduler kinds now emit ``calkit scheduler batch``.
        scheduler_kinds = {
            "slurm": "scheduler",
            "pbs": "scheduler",
        }
        for stage in self.stages.values():
            env_name = stage.outer_environment
            if env_name != "_system" and env_name not in environments:
                raise ValueError(
                    f"Stage '{stage.name}' has outer environment "
                    f"'{stage.outer_environment}' which is not defined in "
                    "environments"
                )
            env = environments.get(stage.outer_environment, {})
            kind = env.get("kind")
            if kind not in scheduler_kinds:
                continue
            cli_alias = scheduler_kinds[kind]
            scheduler_label = kind.upper()
            if stage.kind not in plain_ok_kinds:
                if stage.inner_environment == stage.outer_environment:
                    raise ValueError(
                        f"Stage '{stage.name}' has kind '{stage.kind}' but "
                        f"environment '{stage.outer_environment}' is a "
                        f"{scheduler_label} env with no inner runtime; use "
                        f"a composite environment like "
                        f"'<{kind}-env>:<inner-env>'"
                    )
                inner_env = environments.get(stage.inner_environment)
                if inner_env is None:
                    raise ValueError(
                        f"Stage '{stage.name}' has inner environment "
                        f"'{stage.inner_environment}' that is not "
                        "defined in environments"
                    )
                if inner_env.get("kind") in scheduler_kinds:
                    raise ValueError(
                        f"Stage '{stage.name}' has {scheduler_label} outer "
                        f"environment '{stage.outer_environment}' and "
                        f"scheduler inner environment "
                        f"'{stage.inner_environment}'; the inner "
                        "environment must not be a job scheduler"
                    )
            if stage.scheduler is None:
                stage.scheduler = StageSchedulerOptions()
            stage._scheduler_cli_alias = cli_alias
            stage._scheduler_kind = kind

    def convert_sbatch_stages(self) -> dict[str, dict]:
        """Replace legacy ``sbatch`` stages with ``shell-script`` equivalents.

        Returns a dict mapping stage name → new stage data suitable for
        updating ``calkit.yaml`` (keys present only for converted stages).
        """
        converted = {}
        for name, stage in list(self.stages.items()):
            if stage.kind != "sbatch":
                continue
            sched_opts: dict = {}
            if stage.sbatch_options:
                sched_opts["options"] = list(stage.sbatch_options)
            if stage.log_path is not None:
                sched_opts["log_path"] = stage.log_path
            if stage.log_storage != "git":
                sched_opts["log_storage"] = stage.log_storage
            if stage.scheduler is not None:
                if stage.scheduler.setup:
                    sched_opts["setup"] = list(stage.scheduler.setup)
                if stage.scheduler.env_default_options != "replace":
                    sched_opts["env_default_options"] = (
                        stage.scheduler.env_default_options
                    )
                if stage.scheduler.env_default_setup != "replace":
                    sched_opts["env_default_setup"] = (
                        stage.scheduler.env_default_setup
                    )
            new_stage = ShellScriptStage(
                kind="shell-script",
                name=name,
                environment=stage.environment,
                script_path=stage.script_path,
                args=stage.args,
                inputs=list(stage.inputs),
                outputs=list(stage.outputs),
                wdir=stage.wdir,
                always_run=stage.always_run,
                iterate_over=stage.iterate_over,
                description=stage.description,
                scheduler=StageSchedulerOptions(**sched_opts)
                if sched_opts
                else StageSchedulerOptions(),
            )
            self.stages[name] = new_stage
            calkit_yaml_stage: dict = {
                "kind": "shell-script",
                "environment": stage.environment,
                "script_path": stage.script_path,
            }
            if stage.args:
                calkit_yaml_stage["args"] = list(stage.args)
            if stage.inputs:
                calkit_yaml_stage["inputs"] = [
                    (i.model_dump() if isinstance(i, BaseModel) else i)
                    for i in stage.inputs
                ]
            if stage.outputs:
                calkit_yaml_stage["outputs"] = [
                    (
                        o.model_dump(exclude_none=True)
                        if isinstance(o, BaseModel)
                        else o
                    )
                    for o in stage.outputs
                ]
            if sched_opts:
                calkit_yaml_stage["scheduler"] = sched_opts
            if stage.wdir is not None:
                calkit_yaml_stage["wdir"] = stage.wdir
            if stage.always_run:
                calkit_yaml_stage["always_run"] = True
            if stage.description is not None:
                calkit_yaml_stage["description"] = stage.description
            if stage.iterate_over is not None:
                calkit_yaml_stage["iterate_over"] = [
                    it.model_dump() for it in stage.iterate_over
                ]
            converted[name] = calkit_yaml_stage
        return converted

    def ensure_env_lock_paths_are_inputs(
        self, env_lock_fpaths: dict[str, str]
    ) -> None:
        """Ensure that all environment lock file paths are included as inputs
        to each stage.

        Both the stage's inner and outer environments are considered, so a
        SLURM/PBS env used as the outer half of a composite environment
        contributes its lock file as a stage dependency.
        """
        for _, stage in self.stages.items():
            for env_name in (
                stage.inner_environment,
                stage.outer_environment,
            ):
                lock_fpath = env_lock_fpaths.get(env_name)
                if lock_fpath is not None and lock_fpath not in stage.inputs:
                    stage.inputs.append(lock_fpath)
