"""Pipeline models."""

from __future__ import annotations

import base64
import json
import os
import posixpath
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)
from typing_extensions import Annotated

import calkit.latex
from calkit.models.io import InputsFromStageOutputs, PathInput, PathOutput
from calkit.models.iteration import (
    ExpandedParametersType,
    ParameterIteration,
    ParametersType,
    RangeIteration,
)


def check_path_relative_and_child_of_cwd(s: str) -> str:
    # An empty or blank path is Path('.'), which passes every check below and
    # silently means the project root. Callers act on what they're given, so
    # for something like a map-paths destination that would target the whole
    # project rather than erroring.
    if not s.strip():
        raise ValueError("Path must not be empty")
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
    # Collapse any '..' lexically, so a path that walks back out and in again
    # can't reach a caller still spelled the original way. 'sub/..' passes the
    # containment check above, but left as-is it would be acted on verbatim.
    return posixpath.normpath(p.as_posix())


RelativeChildPathString = Annotated[
    str, AfterValidator(check_path_relative_and_child_of_cwd)
]


def _non_glob_prefix(path: str) -> str:
    """Return the longest leading portion of a path containing no glob
    characters, so a pattern can be reduced to something usable as a DVC
    dependency, e.g. ``figures/*-umag.png`` becomes ``figures``.

    A path with no glob characters is returned unchanged.
    """
    kept = []
    for part in Path(path).as_posix().split("/"):
        if any(c in part for c in "*?["):
            break
        kept.append(part)
    return "/".join(kept)


class StageIteration(BaseModel):
    """A model for the ``iterate_over`` key in a stage definition.

    If ``arg_name`` is a list, ``values`` also must be a list of lists with
    each sublist the length of ``arg_name``.
    """

    arg_name: str | list[str] = Field(
        description="Name(s) of the argument(s) to substitute into the "
        "stage's command and paths."
    )
    values: list[
        int
        | float
        | str
        | RangeIteration
        | ParameterIteration
        | list[int | float | str]
    ] = Field(description="Values over which to iterate.")

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

    options: list[str] | None = Field(
        default=None,
        description="Options passed to the scheduler at submission.",
    )
    setup: list[str] | None = Field(
        default=None,
        description="Commands run at the start of the job script.",
    )
    env_default_options: EnvDefaultsMode = Field(
        default="replace",
        description="How to combine 'options' with the environment's "
        "default_options.",
    )
    env_default_setup: EnvDefaultsMode = Field(
        default="replace",
        description="How to combine 'setup' with the environment's "
        "default_setup.",
    )
    log_path: str | None = Field(
        default=None, description="Path at which to write the job log."
    )
    log_storage: Literal["git", "dvc"] | None = Field(
        default="git", description="Where to store the job log."
    )


def _allow_null(schema: dict[str, Any]) -> None:
    """Let a list field's published schema accept null as well as an array.

    An empty ``inputs:`` key parses as null, which ``Stage`` normalizes to an
    empty list. Without this the generated schema would reject a stage that
    loads and runs fine, which is the one thing the schema must never do.
    """
    annotations = {"title", "description", "default", "deprecated"}
    inner = {k: v for k, v in schema.items() if k not in annotations}
    for key in inner:
        schema.pop(key)
    schema["anyOf"] = [inner, {"type": "null"}]


class Stage(BaseModel):
    """A stage in the pipeline."""

    name: str | None = Field(
        default=None,
        description="The stage's name, which must match its key if set.",
    )
    kind: Literal[
        "python-script",
        "latex",
        "quarto",
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
        "marimo-html-wasm",
        "markdown",
    ] = Field(description="What kind of stage this is.")
    environment: str = Field(
        description="Name of the environment in which to run this stage."
    )
    # Constrained like other stage path fields (e.g. MatlabScriptStage's
    # matlab_path): this becomes the DVC stage's working directory and is
    # joined with the stage's other paths, where an absolute value would
    # silently win, so an unchecked one lets a project's pipeline run
    # against paths outside itself.
    wdir: RelativeChildPathString | None = Field(
        default=None,
        description="Working directory in which to run, relative to the "
        "project root. Note that all other paths in the stage are relative "
        "to this.",
    )
    # TODO: Support other input types
    inputs: list[str | PathInput | InputsFromStageOutputs] = Field(
        default=[],
        description="Paths this stage depends on, which trigger a rerun when "
        "they change. Normally plain path strings; an object carrying a "
        "'path' is also accepted.",
        json_schema_extra=_allow_null,
    )
    # TODO: Support database outputs
    outputs: list[str | PathOutput] = Field(
        default=[],
        description="Paths this stage produces.",
        json_schema_extra=_allow_null,
    )
    always_run: bool = Field(
        default=False,
        description="Run this stage every time the pipeline is run, even if "
        "nothing has changed.",
    )
    iterate_over: list[StageIteration] | None = Field(
        default=None,
        description="Arguments over which to run this stage multiple times.",
    )
    description: str | None = Field(
        default=None, description="A description of what this stage does."
    )
    frozen: bool = Field(
        default=False,
        description="Never rerun this stage, treating its outputs as "
        "up-to-date.",
    )
    scheduler: StageSchedulerOptions | None = Field(
        default=None,
        description="Options for running this stage on a job scheduler "
        "(SLURM or PBS).",
    )
    # Do not allow extra keys
    model_config = ConfigDict(extra="forbid")
    # Resolved at pipeline-compilation time by set_stage_scheduler_options;
    # all scheduler kinds now emit ``calkit scheduler batch``.
    _scheduler_cli_alias: str = PrivateAttr(default="scheduler")
    # The outer env's kind (``slurm`` or ``pbs``) when this stage runs
    # through a job scheduler; used to derive the default log path so the
    # log file can be tracked as a DVC output.
    _scheduler_kind: str | None = PrivateAttr(default=None)
    # The name of the outer ``system`` env when this stage runs on a
    # particular machine, whether or not it also names an inner runtime, so
    # the compiled command dispatches there first. Also resolved by
    # set_stage_scheduler_options.
    _system_env: str | None = PrivateAttr(default=None)

    # Declared so the published schema accepts what the validator below
    # already migrates; without it an editor flags a ``slurm:`` stage that
    # runs fine.
    slurm: StageSchedulerOptions | None = Field(
        default=None,
        deprecated=True,
        description="Deprecated name for 'scheduler'; set 'scheduler' "
        "instead.",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_keys(cls, data: Any) -> Any:
        """Accept older and looser spellings of a stage's keys.

        Migrates the old ``slurm:`` field to ``scheduler:``, and treats an
        empty ``inputs:``/``outputs:`` key, which parses as None, the same as
        omitting it rather than failing to load the stage.

        Works on a copy, so validating a stage doesn't rewrite the caller's
        parsed ``calkit.yaml`` underneath it.
        """
        if not isinstance(data, dict):
            return data
        if "slurm" in data and data.get("scheduler") is not None:
            raise ValueError(
                "Stage has both 'slurm' and 'scheduler' options set; "
                "remove 'slurm' (use 'scheduler' only)"
            )
        data = {
            k: v
            for k, v in data.items()
            if not (k in ("inputs", "outputs") and v is None)
        }
        if "slurm" in data:
            data["scheduler"] = data.pop("slurm")
        return data

    def to_ck_dict(self) -> dict:
        """Dump the stage for calkit.yaml, omitting fields left at their
        defaults so we don't write a bunch of nulls and empty lists.

        ``kind`` is kept even though subclasses define it with a default,
        since it's the discriminator needed to load the stage back.
        """
        return {"kind": self.kind} | self.model_dump(exclude_defaults=True)

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
            if isinstance(i, InputsFromStageOutputs):
                continue
            path = i if isinstance(i, str) else i.path
            if path not in deps:
                deps.append(path)
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

        A ``system`` env says which machine to run on rather than what to
        run in, so it wraps the same way: ``<system-env>:<inner-env>``
        dispatches to the machine and activates the runtime once there.
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
        if self._system_env is not None:
            # Dispatch to the machine, telling it what this stage reads and
            # writes so the transfer follows the pipeline instead of a
            # hand-maintained list that can drift out of step with it.
            # Nothing about what to move: the transfer works that out
            # from the snapshot and from what the workspace says the run
            # produced, so it can't fall out of step with the pipeline
            cmd = f"calkit xenv -n {self._system_env} --no-check"
            if self.inner_environment == self.outer_environment:
                return cmd + " --"
            # The inner xenv runs in the workspace rather than here
            return (
                cmd
                + " -- "
                + f"calkit xenv -n {self.inner_environment} --no-check --"
            )
        return f"calkit xenv -n {self.inner_environment} --no-check --"

    @property
    def dvc_out_paths(self) -> list[str]:
        """The paths this stage writes, however its outputs are spelled."""
        paths = []
        for out in self.dvc_outs:
            path = out if isinstance(out, str) else next(iter(out))
            if path not in paths:
                paths.append(path)
        return paths

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
                cmd += f" --option {opt}"
        if opts.setup is not None:
            for setup_cmd in opts.setup:
                cmd += f" --setup {shlex.quote(setup_cmd)}"
        return cmd

    @property
    def scheduler_log_output(self) -> PathOutput | None:
        """The log file produced by a scheduler-batched stage.

        Mirrors the default ``calkit scheduler batch`` chooses at runtime
        (``.calkit/scheduler/logs/<name>.out``) unless the stage explicitly
        sets ``scheduler.log_path``. For iterated stages, iteration arg
        names are interpolated as ``{arg}`` placeholders so the DVC
        matrix-format pass substitutes them into the per-item path.
        """
        if self.scheduler is None or self._scheduler_kind is None:
            return None
        log_path = self.scheduler.log_path
        if log_path is None:
            # Mirror what ``calkit scheduler batch`` chooses at runtime: the
            # CLI joins ``scheduler/logs/<--name>.out`` directly, and the
            # job name passed via ``scheduler_cmd`` already includes any
            # ``@{arg}`` suffix for iterated stages.
            log_path = f".calkit/scheduler/logs/{self.name}"
            if self.iterate_over is not None:
                arg_names = []
                for item in self.iterate_over:
                    if isinstance(item.arg_name, list):
                        arg_names += item.arg_name
                    else:
                        arg_names.append(item.arg_name)
                log_path += "@" + ",".join(
                    f"{{{arg_name}}}" for arg_name in arg_names
                )
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
            if isinstance(i, InputsFromStageOutputs):
                continue
            path = i if isinstance(i, str) else i.path
            if path not in deps:
                deps.append(path)
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
        # Scheduler-batched stages must persist their outputs: `calkit
        # scheduler batch` deletes and recreates them itself, and persisting
        # stops DVC from removing them before a re-run. That lets a job that
        # finished while the run was disconnected be recognized as done on the
        # next `calkit run` instead of being resubmitted.
        if self.scheduler is not None:
            persisted_outs: list[str | dict] = []
            for out in outs:
                if isinstance(out, str):
                    persisted_outs.append({out: {"persist": True}})
                else:
                    out_path = list(out.keys())[0]
                    out_opts = dict(out[out_path])
                    out_opts["persist"] = True
                    persisted_outs.append({out_path: out_opts})
            outs = persisted_outs
        stage = {"cmd": cmd, "deps": deps, "outs": outs}
        if self.wdir is not None:
            stage["wdir"] = self.wdir
        if self.always_run:
            stage["always_changed"] = True
        if self.frozen:
            stage["frozen"] = True
        return stage

    def extra_dvc_stages(
        self, resolve_ref: Callable[[str], str] | None = None
    ) -> dict[str, dict]:
        """Additional DVC stages this one compiles into, keyed by name.

        Most stages are one for one. A stage produces more than one when
        the work has genuinely different inputs, so that a change to one
        part doesn't force the rest to run again.

        ``resolve_ref`` turns a Git revision into a commit, for stages
        whose inputs are revisions rather than files.
        """
        return {}


class PythonScriptStage(Stage):
    kind: Literal["python-script"] = "python-script"
    script_path: RelativeChildPathString = Field(
        description="Path to the Python script to run."
    )
    args: list[str] = Field(
        default=[], description="Arguments passed to the script."
    )

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
        """Copy a single file to a single destination path."""

        kind: Literal["file-to-file"] = Field(
            default="file-to-file",
            description="Copy one file to one destination path.",
        )
        src: RelativeChildPathString = Field(
            description="Path to the file to copy."
        )
        dest: RelativeChildPathString = Field(
            description="Path to which the file is copied."
        )

        @property
        def arg(self) -> str:
            return f"--{self.kind} '{self.src}->{self.dest}'"

        @property
        def out_path(self) -> str:
            return self.dest

    class CopyFileToDir(BaseModel):
        """Copy a single file into a directory, keeping its name."""

        kind: Literal["file-to-dir"] = Field(
            default="file-to-dir",
            description="Copy one file into a destination directory.",
        )
        src: RelativeChildPathString = Field(
            description="Path to the file to copy."
        )
        dest: RelativeChildPathString = Field(
            description="Path to the directory into which the file is copied."
        )

        @property
        def arg(self) -> str:
            return f"--{self.kind} '{self.src}->{self.dest}'"

        @property
        def out_path(self) -> str:
            return Path(self.dest, Path(self.src).name).as_posix()

    class DirToDirMerge(BaseModel):
        """Copy a directory's contents into another, keeping what's there."""

        kind: Literal["dir-to-dir-merge"] = Field(
            default="dir-to-dir-merge",
            description="Merge one directory's contents into another.",
        )
        src: RelativeChildPathString = Field(
            description="Path to the directory to copy from."
        )
        dest: RelativeChildPathString = Field(
            description="Path to the directory to copy into."
        )

        @property
        def arg(self) -> str:
            return f"--{self.kind} '{self.src}->{self.dest}'"

        @property
        def out_path(self) -> str:
            return self.dest

    class DirToDirReplace(BaseModel):
        """Replace a directory with the contents of another."""

        kind: Literal["dir-to-dir-replace"] = Field(
            default="dir-to-dir-replace",
            description="Replace the destination directory entirely.",
        )
        src: RelativeChildPathString = Field(
            description="Path to the directory to copy from."
        )
        dest: RelativeChildPathString = Field(
            description="Path to the directory to replace, which is deleted "
            "first."
        )

        @field_validator("dest")
        @classmethod
        def check_dest_is_not_project_root(cls, v: str) -> str:
            """Refuse to replace the project itself.

            This kind deletes its destination before copying, so a dest of
            '.' (which '' and 'sub/..' also reduce to) would remove the whole
            project. The other kinds only copy into their destination, so the
            project root is a fine target for them.
            """
            if v == ".":
                raise ValueError(
                    "Destination must not be the project root, since "
                    "dir-to-dir-replace deletes it before copying"
                )
            return v

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
    ] = Field(description="Copy operations to perform.")

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
    target_path: str = Field(description="Path to the .tex file to compile.")
    output_dir: str | None = Field(
        default=None,
        description="Directory for latexmk output. Defaults to compiling in "
        "place, alongside the target.",
    )
    aux_dir: str | None = Field(
        default=None,
        description="Directory for latexmk auxiliary files.",
    )
    latexmkrc_path: str | None = Field(
        default=None, description="Path to a latexmkrc file to use."
    )
    pdf_storage: Literal["git", "dvc"] | None = Field(
        default="dvc", description="Where to store the resulting PDF."
    )
    diffs: list[str | list[str]] = Field(
        default=[],
        description="Comparisons to keep for this document, each a pair of "
        "revisions. A bare string is shorthand for comparing that revision "
        "against the working tree.",
    )
    diff_pdf_storage: Literal["git", "dvc"] | None = Field(
        default="dvc", description="Where to store the resulting diff PDFs."
    )
    verbose: bool = Field(
        default=False, description="Show full latexmk output."
    )
    force: bool = Field(
        default=False,
        description="Keep compiling despite errors (latexmk -f).",
    )
    synctex: bool = Field(
        default=True,
        description="Generate SyncTeX data for editor/PDF navigation.",
    )
    latexmk_args: list[str] = Field(
        default=[],
        description="Extra arguments passed straight through to latexmk, for "
        "control Calkit does not model.",
    )

    @property
    def diff_pairs(self) -> list[tuple[str, str]]:
        """The revisions to compare, oldest side first.

        A bare revision compares it against ``HEAD``. Every comparison
        here is between two commits: one against the working tree can't be
        reproduced, so it belongs to whoever is doing the work rather than
        to the project.
        """
        pairs: list[tuple[str, str]] = []
        for entry in self.diffs:
            if isinstance(entry, str):
                pairs.append((entry, "HEAD"))
            else:
                pairs.append((entry[0], entry[1]))
        return pairs

    @property
    def diff_paths(self) -> list[str]:
        return [
            calkit.latex.get_diff_path(self.target_path, from_ref, to_ref)
            for from_ref, to_ref in self.diff_pairs
        ]

    def extra_dvc_stages(
        self, resolve_ref: Callable[[str], str] | None = None
    ) -> dict[str, dict]:
        """One stage per diff, separate from building the document.

        A diff has different inputs from the document it describes, and
        some of those inputs aren't files at all, so folding them together
        would rebuild the paper whenever a comparison was added and would
        chain commands with ``&&``, which not every shell understands.

        A revision that can move is resolved into the command, so the
        command changes when it moves and DVC re-runs the stage. Without
        that the only honest option is to run every time, which is what
        happens when no resolver is given.
        """
        stages = {}
        for (from_ref, to_ref), path in zip(self.diff_pairs, self.diff_paths):
            name = (
                f"{self.name}-diff-"
                f"{calkit.latex.diff_stage_suffix(from_ref, to_ref)}"
            )
            out: str | dict = path
            if self.diff_pdf_storage != "dvc":
                out = {path: {"cache": False}}
            # Revisions are resolved to the commit that last changed this
            # document, not to the tip. The two describe the same document
            # -- nothing since has touched it -- but the tip moves with
            # every commit to anything, which would rewrite this command
            # constantly, and saving that rewrite is itself a commit.
            from_arg = resolve_ref(from_ref) if resolve_ref else from_ref
            to_arg = resolve_ref(to_ref) if resolve_ref else to_ref
            cmd = (
                f"calkit latex diff -e {shlex.quote(self.environment)}"
                f" --no-check --from {shlex.quote(from_arg)}"
                f" --to {shlex.quote(to_arg)}"
            )
            # Named from the pair as written, so the output path is the
            # same on every branch even when the command holds commits
            cmd += (
                " --output-dir "
                f"{shlex.quote(calkit.latex.get_diff_dir(from_ref, to_ref))}"
            )
            cmd += f" {shlex.quote(self.target_path)}"
            # The command already names the exact commits being compared,
            # so nothing in the working tree is an input. A DVC-tracked
            # figure is the exception: its content isn't in Git, so only
            # the dependency catches a change to it.
            moving = calkit.latex.MOVING_REFS.intersection({from_ref, to_ref})
            stage: dict = {
                "cmd": cmd,
                "deps": self.dvc_deps if moving else [],
                "outs": [out],
                "desc": (
                    f"Automatically generated from the '{self.name}' stage "
                    "in calkit.yaml. Changes made here will be overwritten."
                ),
            }
            if self.wdir is not None:
                stage["wdir"] = self.wdir
            # Without a resolver the command holds a name rather than a
            # commit, so there's nothing for DVC to notice moving
            if moving and resolve_ref is None:
                stage["always_changed"] = True
            stages[name] = stage
        return stages

    @field_validator("diffs")
    @classmethod
    def _check_diffs(cls, v: list) -> list:
        for entry in v:
            if isinstance(entry, str):
                if not entry:
                    raise ValueError("A diff revision cannot be empty")
                continue
            if len(entry) != 2 or not all(entry):
                raise ValueError(
                    "A diff must be a pair of revisions like [v1, v2], or "
                    "a single revision to compare against the working tree"
                )
            if entry[0] == entry[1]:
                raise ValueError(
                    f"Diff [{entry[0]}, {entry[1]}] compares a revision "
                    "with itself"
                )
        return v

    @model_validator(mode="after")
    def _check_args_dont_set_managed_dirs(self) -> "LatexStage":
        """Reject latexmk dir flags in ``latexmk_args`` Calkit already manages.

        ``output_dir``/``aux_dir`` drive latexmk's ``-outdir``/``-auxdir``; a
        duplicate in ``latexmk_args`` would silently fight them, so make the
        conflict an error rather than a surprise.
        """
        managed = {
            "-outdir": "output_dir",
            "-output-directory": "output_dir",
            "-auxdir": "aux_dir",
            "-aux-directory": "aux_dir",
        }
        for arg in self.latexmk_args:
            field = managed.get(arg.split("=", 1)[0])
            if field is not None and getattr(self, field) is not None:
                raise ValueError(
                    f"latexmk option '{arg}' in latexmk_args conflicts with "
                    f"the '{field}' field; set one or the other, not both."
                )
        return self

    @property
    def pdf_path(self) -> str:
        """Path to the compiled PDF.

        Like ``target_path`` and every other Calkit path field, ``output_dir``
        is relative to the stage's working directory (its ``wdir``, defaulting
        to the project root), not the LaTeX source directory. The returned path
        is in that same frame, so it drops straight into ``dvc_outs``. When
        ``output_dir`` is set, the PDF is written to
        ``<output_dir>/<target stem>.pdf``; otherwise it sits next to the
        source ``.tex`` file. This mirrors where latexmk actually writes the
        PDF when a latexmkrc sets ``$out_dir`` -- see
        ``_warn_on_latexmkrc_out_dir_mismatch`` in ``calkit.pipeline``, which
        translates the (source-relative) ``$out_dir`` into this frame and warns
        when the two disagree.
        """
        target = Path(self.target_path)
        if self.output_dir is not None:
            out_base = Path(self.output_dir) / target.stem
        else:
            out_base = target
        return Path(os.path.normpath(out_base)).with_suffix(".pdf").as_posix()

    @property
    def dvc_cmd(self) -> str:
        # Quote user-controlled paths/args so spaces or shell metacharacters in
        # them don't corrupt the compiled DVC command.
        cmd = (
            f"calkit latex build -e {shlex.quote(self.environment)} --no-check"
        )
        if self.latexmkrc_path is not None:
            cmd += f" -r {shlex.quote(self.latexmkrc_path)}"
        else:
            # Only drive latexmk's output/aux directories when the user has not
            # supplied a latexmkrc; a CLI -outdir would override the rc's
            # $out_dir. With a latexmkrc, it stays authoritative (and the
            # output_dir drift lint in calkit.pipeline covers mismatches).
            if self.output_dir is not None:
                cmd += f" --output-dir {shlex.quote(self.output_dir)}"
            if self.aux_dir is not None:
                cmd += f" --aux-dir {shlex.quote(self.aux_dir)}"
        if self.verbose:
            cmd += " --verbose"
        if self.force:
            cmd += " -f"
        if not self.synctex:
            cmd += " --no-synctex"
        for arg in self.latexmk_args:
            cmd += f" --latexmk-arg {shlex.quote(arg)}"
        cmd += f" {shlex.quote(self.target_path)}"
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
        out_path = self.pdf_path
        # If the PDF output is already in outs use that
        # Otherwise, create a DVC output from pdf_storage and add it to outs
        out_paths = []
        for out in outs:
            if isinstance(out, str):
                out_paths.append(out)
            elif isinstance(out, dict):
                out_paths.append(list(out.keys())[0])
        if out_path not in out_paths:
            if self.pdf_storage != "dvc":
                outs.append({out_path: {"cache": False}})
            else:
                outs.append(out_path)
        return outs


class QuartoStage(Stage):
    """A stage that renders a Quarto document.

    Calkit controls only what belongs on the CLI: which environment to
    render in, the target document, and (optionally) the output format and
    extra ``quarto render`` arguments. The output format(s) and any other
    rendering behavior are left to the document/``_quarto.yml`` metadata, so
    there is no redundancy between the pipeline definition and the doc.

    Outputs are declared explicitly via ``outputs`` rather than parsed out
    of the Quarto document, since a document can emit multiple formats to
    arbitrary paths. As with other stages, plain string outputs are
    DVC-cached by default; use a ``PathOutput`` to store an output with Git
    instead.
    """

    kind: Literal["quarto"] = "quarto"
    target_path: str = Field(
        description="Path to the Quarto document to render."
    )
    to: str | None = Field(
        default=None,
        description="Output format, passed to 'quarto render --to'. Defaults "
        "to what the document's metadata specifies.",
    )
    args: list[str] = Field(
        default=[], description="Extra arguments passed to 'quarto render'."
    )

    @property
    def dvc_cmd(self) -> str:
        cmd = f"{self.xenv_cmd} quarto render {self.target_path}"
        if self.to is not None:
            cmd += f" --to {self.to}"
        for arg in self.args:
            cmd += f" {arg}"
        return cmd.strip()

    @property
    def dvc_deps(self) -> list[str]:
        return [self.target_path] + super().dvc_deps


class JsonToLatexStage(Stage):
    kind: Literal["json-to-latex"] = "json-to-latex"
    environment: str = "_system"
    command_name: str | None = Field(
        default=None,
        description="Name of the LaTeX command to define for each value.",
    )
    format: dict[str, str] | None = Field(
        default=None,
        description="Format strings for values, keyed by their JSON key.",
    )

    @property
    def dvc_cmd(self) -> str:
        cmd = "calkit latex from-json"
        # dvc_deps rather than inputs, since an input can be an object
        # carrying a path, which would otherwise interpolate its repr.
        for input_path in self.dvc_deps:
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
    script_path: RelativeChildPathString = Field(
        description="Path to the MATLAB script to run."
    )
    matlab_path: RelativeChildPathString | None = Field(
        default=None,
        description="Directory added to the MATLAB path, recursively.",
    )

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
    command: str = Field(description="MATLAB command to run.")

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
    command: str = Field(description="Shell command to run.")
    shell: Literal["sh", "bash", "zsh"] = Field(
        default="bash", description="Shell in which to run the command."
    )

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
    script_path: RelativeChildPathString = Field(
        description="Path to the shell script to run."
    )
    args: list[str] = Field(
        default=[], description="Arguments passed to the script."
    )
    shell: Literal["sh", "bash", "zsh"] = Field(
        default="bash", description="Shell in which to run the script."
    )

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
    command: str = Field(
        description="Full command to run, including the 'docker run' call."
    )

    @property
    def dvc_cmd(self) -> str:
        return self.command


class CommandStage(Stage):
    kind: Literal["command"] = "command"
    command: str = Field(description="Command to run in the environment.")

    @property
    def dvc_cmd(self) -> str:
        return f"{self.xenv_cmd} {self.command}".strip()


class RScriptStage(Stage):
    kind: Literal["r-script"]
    script_path: RelativeChildPathString = Field(
        description="Path to the R script to run."
    )
    args: list[str] = Field(
        default=[], description="Arguments passed to the script."
    )

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
    script_path: RelativeChildPathString = Field(
        description="Path to the Julia script to run."
    )
    args: list[str] = Field(
        default=[], description="Arguments passed to the script."
    )

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
    command: str = Field(description="Julia command to run.")

    @property
    def dvc_cmd(self) -> str:
        # We need to escape quotes in the command
        julia_cmd = self.command.replace('"', '\\"')
        cmd = f'{self.xenv_cmd} -e "{julia_cmd}"'
        return cmd


# TODO: ``sbatch`` stages are deprecated; ``convert_sbatch_stages`` rewrites
# them into ``shell-script`` + ``scheduler:`` on pipeline compile. Once the
# new schema has had enough time to propagate in the wild, drop this class,
# the union entry, the ``plain_ok_kinds`` carve-out, and
# ``convert_sbatch_stages`` to remove the legacy complexity.
class SBatchStage(Stage):
    kind: Literal["sbatch"] = "sbatch"
    script_path: RelativeChildPathString = Field(
        description="Path to the script to submit."
    )
    args: list[str] = Field(
        default=[], description="Arguments passed to the script."
    )
    sbatch_options: list[str] = Field(
        default=[], description="Options passed to sbatch."
    )
    log_path: str | None = Field(
        default=None, description="Path at which to write the job log."
    )
    log_storage: Literal["git", "dvc"] | None = Field(
        default="git", description="Where to store the job log."
    )

    @property
    def log_output(self) -> PathOutput:
        log_path = self.log_path
        if log_path is None:
            log_path = f".calkit/scheduler/logs/{self.name}"
            if self.iterate_over is not None:
                arg_names = []
                for item in self.iterate_over:
                    if isinstance(item.arg_name, list):
                        arg_names += item.arg_name
                    else:
                        arg_names.append(item.arg_name)
                log_path += "@" + ",".join(
                    f"{{{arg_name}}}" for arg_name in arg_names
                )
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
    notebook_path: str = Field(description="Path to the notebook to execute.")
    cleaned_ipynb_storage: Literal["git", "dvc"] | None = Field(
        default=None,
        description="Where to store the output-stripped notebook.",
    )
    executed_ipynb_storage: Literal["git", "dvc"] | None = Field(
        default="dvc", description="Where to store the executed notebook."
    )
    html_storage: Literal["git", "dvc"] | None = Field(
        default="dvc",
        description="Where to store the executed notebook as HTML.",
    )
    parameters: dict[str, Any] = Field(
        default={},
        description="Parameters injected into the notebook. A value like "
        "'{name}' is filled in from the project-level parameters.",
    )
    language: Literal["python", "matlab", "julia"] | None = Field(
        default=None,
        description="The notebook's language. Detected automatically if "
        "unset.",
    )

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
    word_doc_path: str = Field(
        description="Path to the Word document to convert."
    )
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


class MarimoHtmlWasmStage(Stage):
    """A stage that exports a marimo notebook to a WebAssembly app.

    The app runs entirely in the browser via Pyodide, so it can be served
    as static files with no backend.

    marimo's export commands differ enough from each other that each gets
    its own stage kind and CLI command, rather than one kind with a format
    option whose other fields only apply to some of its values.

    marimo's own export is not self-contained: it requires the data an app
    reads to already sit in a ``public`` directory next to the notebook, and
    copies only that directory into the output. Assembling that is this
    stage's main job, and it happens in a build directory rather than
    in place, so nothing is generated in the project tree. Paths in ``include_paths`` are
    copied beneath ``public`` at their project-relative paths, so notebook
    code that reads ``mo.notebook_location() / "public" / "data.csv"`` works
    the same locally as it does in the browser.

    ``include_paths`` is deliberately separate from ``inputs`` because these
    files are published to the web, which should be opt-in per path rather
    than inferred from the dependency graph. They are dependencies too.
    """

    kind: Literal["marimo-html-wasm"] = "marimo-html-wasm"
    notebook_path: str = Field(
        description="Path to the marimo notebook to export."
    )
    # The layout file is named inside the notebook source
    # (``marimo.App(layout_file=...)``), so we can't detect it without
    # parsing Python, and a grid app silently degrades to a linear notebook
    # if it goes missing.
    layout_path: str | None = Field(
        default=None,
        description="Path to the notebook's layout file, if it has one.",
    )
    mode: Literal["run", "edit"] = Field(
        default="run",
        description="Whether the app runs its cells or opens as an editable "
        "notebook.",
    )
    show_code: bool = Field(
        default=False, description="Show the notebook's code in the app."
    )
    include_paths: list[str] = Field(
        default=[],
        description="Paths published with the app, readable from the "
        "notebook at 'public/<path>'. These are dependencies as well.",
    )
    output_dir: str = Field(
        description="Directory into which the app is exported."
    )
    output_storage: Literal["git", "dvc"] | None = Field(
        default="dvc", description="Where to store the exported app."
    )
    # A WASM export doesn't run the notebook, so we run it once beforehand to
    # keep a broken app from shipping green. That doubles the stage's runtime,
    # which isn't worth it for a notebook that takes a while and is already
    # executed elsewhere in the pipeline. Not named ``validate``, which
    # shadows a Pydantic attribute on the base model.
    validate_notebook: bool = Field(
        default=True,
        description="Run the notebook before exporting, to catch one that "
        "would fail in the browser.",
    )

    @model_validator(mode="after")
    def check_include_paths_have_a_stable_dep(self) -> MarimoHtmlWasmStage:
        """Reject an include pattern whose first segment is a glob.

        Dependencies are the pattern's longest non-glob parent, so a
        top-level pattern like ``*.csv`` leaves nothing to depend on, and
        silently dropping it would let DVC order this stage before whatever
        produces those files.
        """
        for path in self.include_paths:
            if not _non_glob_prefix(path):
                raise ValueError(
                    f"Included path '{path}' begins with a glob, leaving no "
                    "directory to depend on; put it under one, e.g. "
                    f"'data/{path}'"
                )
        return self

    @model_validator(mode="after")
    def check_export_options(self) -> MarimoHtmlWasmStage:
        """Reject options that contradict each other."""
        if self.mode == "edit" and self.show_code:
            raise ValueError(
                "Stage option 'show_code' is redundant with 'mode: edit', "
                "where code is always visible"
            )
        return self

    @property
    def dvc_deps(self) -> list[str]:
        deps = [self.notebook_path]
        if self.layout_path is not None:
            deps.append(self.layout_path)
        # A glob can't be a DVC dep, and expanding one at compile time would
        # yield no deps at all before the producing stage has ever run,
        # letting DVC order this stage first. Depend on the longest non-glob
        # parent instead: conservative, but stable and correctly ordered.
        for path in self.include_paths:
            dep = _non_glob_prefix(path)
            if dep not in deps:
                deps.append(dep)
        return deps + super().dvc_deps

    @property
    def dvc_outs(self) -> list[str | dict]:
        outs = super().dvc_outs
        if self.output_storage:
            outs.append(
                {self.output_dir: {"cache": self.output_storage == "dvc"}}
            )
        return outs

    @property
    def app_outputs(self) -> list[PathOutput]:
        """Return the exported app so its storage can be respected."""
        return [PathOutput(path=self.output_dir, storage=self.output_storage)]

    @property
    def dvc_cmd(self) -> str:
        cmd = (
            "calkit nb export-marimo-wasm --environment "
            f"{self.inner_environment} --no-check"
        )
        if self.mode != "run":
            cmd += f" --mode {self.mode}"
        if self.show_code:
            cmd += " --show-code"
        if not self.validate_notebook:
            cmd += " --no-validate"
        if self.layout_path is not None:
            cmd += f" --layout {shlex.quote(self.layout_path)}"
        for path in self.include_paths:
            cmd += f" --include {shlex.quote(path)}"
        cmd += f" -o {shlex.quote(self.output_dir)}"
        cmd += f" {shlex.quote(self.notebook_path)}"
        if self.scheduler is not None:
            cmd = self.scheduler_cmd + " --command -- " + cmd
        return cmd


class MarkdownStage(Stage):
    """A stage sourced from a Markdown file's annotated code blocks.

    This stands in for however many stages the file declares. It is
    replaced by them at compile time (see
    ``Pipeline.expand_markdown_stages``), so nothing downstream needs to
    know Markdown was involved.
    """

    kind: Literal["markdown"] = "markdown"
    path: RelativeChildPathString | None = Field(
        default=None,
        description="Path to the Markdown file. Defaults to the stage name, "
        "since a Markdown stage is normally keyed by its own path.",
    )
    # A Markdown stage never runs as itself, so it needs no environment of
    # its own; this is the fallback for blocks that don't name one.
    environment: str = Field(
        default="_system",
        description="Environment used by blocks that don't name one.",
    )

    @property
    def markdown_path(self) -> str:
        path = self.path if self.path is not None else self.name
        if path is None:
            raise ValueError("Markdown stage has no path")
        return Path(path).as_posix()


class Pipeline(BaseModel):
    """The project's reproducible pipeline."""

    stages: dict[
        str,
        Annotated[
            (
                PythonScriptStage
                | LatexStage
                | QuartoStage
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
                | MarimoHtmlWasmStage
                | MarkdownStage
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

    @model_validator(mode="after")
    def check_markdown_stage_paths(self) -> Pipeline:
        """Check that markdown stages point at a Markdown file.

        This runs at the pipeline level because a stage's name is only
        filled in from its key above, and the name is where the path
        normally comes from.
        """
        for stage_name, stage in self.stages.items():
            if stage.kind != "markdown":
                continue
            path = stage.path if stage.path is not None else stage_name
            if not str(path).endswith(".md"):
                raise ValueError(
                    f"Markdown stage '{stage_name}' needs a 'path' ending "
                    "in .md, or a name that is one"
                )
        return self

    def expand_markdown_stages(self, wdir: str | None = None) -> list[str]:
        """Replace each markdown stage with the stages its blocks declare.

        A file keyed ``README.md`` becomes ``README.md@<block-name>`` for
        each stage its blocks declare, each an ordinary script stage over
        the extracted script. Running before scheduler options and env
        lock deps are resolved means those, and everything else
        downstream, treat them like any other stage.

        Returns the paths of extracted scripts whose content changed.
        """
        import calkit.markdown

        kind_classes: dict[str, type[Stage]] = {
            "python-script": PythonScriptStage,
            "r-script": RScriptStage,
            "julia-script": JuliaScriptStage,
            "shell-script": ShellScriptStage,
            "matlab-script": MatlabScriptStage,
        }
        markdown_stages = [
            (name, stage)
            for name, stage in self.stages.items()
            if stage.kind == "markdown"
        ]
        if not markdown_stages:
            return []
        changed: list[str] = []
        for stage_name, md_stage in markdown_stages:
            md_path = md_stage.markdown_path
            read_path = os.path.join(wdir, md_path) if wdir else md_path
            if not os.path.isfile(read_path):
                raise ValueError(
                    f"Markdown stage '{stage_name}' points at '{md_path}', "
                    "which does not exist"
                )
            blocks = calkit.markdown.parse_markdown_file(read_path)
            specs = calkit.markdown.extract_stages(blocks, md_path)
            if not specs:
                raise ValueError(
                    f"Markdown stage '{stage_name}' declares no stages; "
                    "annotate a code block with "
                    "'calkit stage name=<name>' to define one"
                )
            changed += calkit.markdown.write_stage_scripts(specs, wdir=wdir)
            # Drop the placeholder before inserting what it stands for, so
            # a stage sharing its name would collide loudly rather than
            # silently overwrite.
            del self.stages[stage_name]
            for spec in specs.values():
                sub_name = f"{stage_name}@{spec.name}"
                if sub_name in self.stages:
                    raise ValueError(
                        f"Stage '{sub_name}' from '{md_path}' conflicts "
                        "with an existing pipeline stage"
                    )
                kwargs: dict[str, Any] = {
                    "environment": md_stage.environment,
                    "wdir": md_stage.wdir,
                }
                kwargs.update(spec.attrs)
                kwargs.update(
                    {
                        "kind": spec.stage_kind,
                        "name": sub_name,
                        "script_path": spec.script_path,
                    }
                )
                if spec.stage_kind == "shell-script":
                    kwargs.setdefault(
                        "shell",
                        "sh" if spec.language == "sh" else spec.language,
                    )
                try:
                    # The stages dict is typed as the discriminated union,
                    # which can't be expressed as the lookup's value type;
                    # the model_validate call is what actually enforces it.
                    sub_stage: Any = kind_classes[
                        spec.stage_kind
                    ].model_validate(kwargs)
                    self.stages[sub_name] = sub_stage
                except ValidationError as e:
                    raise ValueError(
                        f"{md_path}:{spec.line}: stage '{spec.name}' is not "
                        f"defined properly: {e}"
                    )
        return changed

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
            if kind == "system":
                # A system env names the machine, so it can wrap an inner
                # runtime the same way a scheduler env does.
                stage._system_env = stage.outer_environment
                if stage.inner_environment == stage.outer_environment:
                    continue
                inner_env = environments.get(stage.inner_environment)
                if inner_env is None:
                    raise ValueError(
                        f"Stage '{stage.name}' has inner environment "
                        f"'{stage.inner_environment}' that is not "
                        "defined in environments"
                    )
                if inner_env.get("kind") in set(scheduler_kinds) | {"system"}:
                    raise ValueError(
                        f"Stage '{stage.name}' has system outer environment "
                        f"'{stage.outer_environment}' and inner environment "
                        f"'{stage.inner_environment}' of kind "
                        f"'{inner_env.get('kind')}'; the inner environment "
                        "must be a runtime, not another machine or a job "
                        "scheduler"
                    )
                continue
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
                frozen=stage.frozen,
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
            if stage.frozen:
                calkit_yaml_stage["frozen"] = True
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
