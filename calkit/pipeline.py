"""Pipeline-related functionality."""

import itertools
import os

import git
import typer
from pydantic import BaseModel, Field, computed_field, field_validator

import calkit
import calkit.environments
from calkit.environments import get_env_lock_fpath
from calkit.models.iteration import expand_project_parameters
from calkit.models.pipeline import (
    InputsFromStageOutputs,
    PathOutput,
    Pipeline,
)


class PipelineStatus(BaseModel):
    """Current status of the project pipeline."""

    has_pipeline: bool
    environment_checks: dict[str, dict] = Field(default_factory=dict)
    cleaned_notebooks: list[str] = Field(default_factory=list)
    stale_stages: dict[str, "StaleStage"] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)

    @field_validator("stale_stages", mode="before")
    @classmethod
    def _coerce_stale_stages(cls, value):
        if not isinstance(value, dict):
            return {}
        coerced = {}
        for stage_name, stage_value in value.items():
            if isinstance(stage_value, StaleStage):
                coerced[stage_name] = stage_value
            else:
                coerced[stage_name] = StaleStage.from_status_data(stage_value)
        return coerced

    @computed_field
    @property
    def stale_stage_names(self) -> list[str]:
        return sorted(self.stale_stages.keys())

    @computed_field
    @property
    def failed_environment_checks(self) -> list[str]:
        return sorted(
            [
                env_name
                for env_name, result in self.environment_checks.items()
                if not result.get("success", False)
            ]
        )

    @computed_field
    @property
    def is_stale(self) -> bool:
        return bool(self.stale_stages)


class StaleStage(BaseModel):
    """Structured status information for a stale pipeline stage."""

    raw_status: list | dict | str | None = None
    stale_outputs: list[str] = Field(default_factory=list)
    modified_inputs: list[str] = Field(default_factory=list)
    modified_outputs: list[str] = Field(default_factory=list)

    @staticmethod
    def _as_path_list(paths: object) -> list[str]:
        if isinstance(paths, str):
            return [paths]
        if isinstance(paths, list):
            return [str(path) for path in paths]
        return []

    @classmethod
    def _collect_paths(cls, change_group: object) -> list[str]:
        paths = []
        if isinstance(change_group, list):
            for item in change_group:
                paths.extend(cls._collect_paths(item))
            return list(dict.fromkeys(paths))
        if not isinstance(change_group, dict):
            return []
        for key, values in change_group.items():
            # DVC may encode path->change_type, e.g. {"foo.txt": "modified"}
            if isinstance(values, str) and values in {
                "modified",
                "new",
                "deleted",
            }:
                paths.append(str(key))
            else:
                paths.extend(cls._as_path_list(values))

        return list(dict.fromkeys(paths))

    @classmethod
    def _collect_output_paths(
        cls, change_group: object
    ) -> tuple[list[str], list[str]]:
        all_paths = []
        changed_paths = []
        changed_statuses = {"modified"}
        known_statuses = changed_statuses | {
            "new",
            "deleted",
            "not in cache",
            "always changed",
        }
        if isinstance(change_group, list):
            for item in change_group:
                item_all, item_changed = cls._collect_output_paths(item)
                all_paths.extend(item_all)
                changed_paths.extend(item_changed)
            return list(dict.fromkeys(all_paths)), list(
                dict.fromkeys(changed_paths)
            )
        if not isinstance(change_group, dict):
            return [], []
        for key, values in change_group.items():
            if isinstance(values, str) and values in known_statuses:
                path = str(key)
                all_paths.append(path)
                if values in changed_statuses:
                    changed_paths.append(path)
                continue
            if isinstance(values, list):
                listed_paths = [str(path) for path in values]
                if key in known_statuses:
                    all_paths.extend(listed_paths)
                    if key in changed_statuses:
                        changed_paths.extend(listed_paths)
                else:
                    all_paths.extend(listed_paths)
                continue
            item_all, item_changed = cls._collect_output_paths(values)
            all_paths.extend(item_all)
            changed_paths.extend(item_changed)

        return list(dict.fromkeys(all_paths)), list(
            dict.fromkeys(changed_paths)
        )

    @classmethod
    def from_status_data(
        cls,
        status_data: list | dict | str,
        configured_outputs: list[str] | None = None,
    ) -> "StaleStage":
        modified_inputs = []
        output_paths = []
        modified_outputs = []

        status_blocks = []
        if isinstance(status_data, dict):
            status_blocks = [status_data]
        elif isinstance(status_data, list):
            status_blocks = [
                item for item in status_data if isinstance(item, dict)
            ]
        for block in status_blocks:
            modified_inputs.extend(
                cls._collect_paths(
                    block.get("changed deps", block.get("deps", {}))
                )
            )
            out_paths, changed_out_paths = cls._collect_output_paths(
                block.get("changed outs", block.get("outs", {}))
            )
            output_paths.extend(out_paths)
            modified_outputs.extend(changed_out_paths)
        modified_inputs = list(dict.fromkeys(modified_inputs))
        output_paths = list(dict.fromkeys(output_paths))
        modified_outputs = list(dict.fromkeys(modified_outputs))
        configured_outputs = [str(path) for path in (configured_outputs or [])]
        stale_outputs = []
        if modified_inputs:
            stale_outputs.extend(configured_outputs)
        stale_outputs.extend(
            [path for path in output_paths if path not in modified_outputs]
        )
        if not stale_outputs and not modified_outputs and configured_outputs:
            stale_outputs.extend(configured_outputs)
        stale_outputs = list(dict.fromkeys(stale_outputs))
        return cls(
            raw_status=status_data,
            stale_outputs=stale_outputs,
            modified_inputs=modified_inputs,
            modified_outputs=modified_outputs,
        )


def stages_are_similar(stage1: dict, stage2: dict) -> bool:
    """Check if two stage configurations are fundamentally the same.

    Compares stage kind and key parameters to determine if stages represent
    the same operation.

    Parameters
    ----------
    stage1 : dict
        First stage configuration.
    stage2 : dict
        Second stage configuration.

    Returns
    -------
    bool
        True if stages are similar, False otherwise.
    """
    # Different kind means different stage
    if stage1.get("kind") != stage2.get("kind"):
        return False
    kind = stage1.get("kind")
    # For script stages, check script path and args
    if kind in [
        "python-script",
        "julia-script",
        "matlab-script",
        "shell-script",
    ]:
        if stage1.get("script_path") != stage2.get("script_path"):
            return False
        if stage1.get("args", []) != stage2.get("args", []):
            return False
    # For notebook stages
    elif kind == "jupyter-notebook":
        if stage1.get("notebook_path") != stage2.get("notebook_path"):
            return False
    # For latex
    elif kind == "latex":
        if stage1.get("target_path") != stage2.get("target_path"):
            return False
    # For command stages, check the command
    elif kind in [
        "command",
        "shell-command",
        "matlab-command",
        "julia-command",
    ]:
        if stage1.get("command") != stage2.get("command"):
            return False
    return True


def _expand_matrix(input_dict: dict[str, list]) -> list[dict]:
    """Restructure a dictionary with list values into a list of dictionaries,
    where each dictionary represents a permutation of the input dictionary's
    values.
    """
    keys = list(input_dict.keys())
    values = list(input_dict.values())
    # Create all combinations of values using itertools.product
    combinations = itertools.product(*values)
    # Create a list of dictionaries
    list_of_dicts = []
    for combination in combinations:
        list_of_dicts.append(dict(zip(keys, combination)))
    # After expanding the matrix, flatten any nested dictionaries in the result
    # This handles cases where list-of-lists iterations produce dictionaries as
    # values, by concatenating parent and child keys (e.g., "parent.child")
    # so all permutations are represented as flat dictionaries
    final_list = []
    for item in list_of_dicts:
        keys = list(item.keys())
        vals = list(item.values())
        vd = {}
        for key, val in zip(keys, vals):
            if isinstance(val, dict):
                for k, v in val.items():
                    vd[f"{key}.{k}"] = v
            else:
                vd[key] = val
        final_list.append(vd)
    return final_list


def get_status(
    ck_info: dict | None = None,
    targets: list[str] | None = None,
    wdir: str | None = None,
    check_environments: bool = True,
    clean_notebooks: bool = True,
    compile_to_dvc: bool = True,
    force_env_check: bool = False,
) -> PipelineStatus:
    """Get pipeline status after optional prep checks.

    This can compile the Calkit pipeline to DVC, clean notebook outputs,
    check pipeline environments, then query DVC for out-of-date stages.
    """
    prev_cwd = os.getcwd()
    if wdir is not None:
        os.chdir(wdir)
    try:
        if ck_info is None:
            ck_info = calkit.load_calkit_info()
        has_pipeline = bool(ck_info.get("pipeline", {}).get("stages", {}))
        has_pipeline = has_pipeline or os.path.isfile("dvc.yaml")
        result = {
            "has_pipeline": has_pipeline,
            "environment_checks": {},
            "cleaned_notebooks": [],
            "stale_stages": {},
            "errors": [],
        }
        if not has_pipeline:
            return PipelineStatus.model_validate(result)
        if check_environments:
            try:
                env_checks = calkit.environments.check_all_in_pipeline(
                    ck_info=ck_info,
                    targets=targets,
                    force=force_env_check,
                )
                result["environment_checks"] = env_checks
            except Exception as e:
                result["errors"].append(
                    "Failed to check pipeline environments: "
                    f"{e.__class__.__name__}: {e}"
                )
                return PipelineStatus.model_validate(result)
            failed_env_checks = [
                env_name
                for env_name, info in env_checks.items()
                if not info.get("success", False)
            ]
            if failed_env_checks:
                return PipelineStatus.model_validate(result)
        if compile_to_dvc and ck_info.get("pipeline", {}).get("stages", {}):
            try:
                to_dvc(ck_info=ck_info, write=True)
            except Exception as e:
                result["errors"].append(
                    f"Failed to compile pipeline: {e.__class__.__name__}: {e}"
                )
                return PipelineStatus.model_validate(result)
        if clean_notebooks and ck_info.get("pipeline", {}).get("stages", {}):
            try:
                cleaned = calkit.notebooks.clean_all_in_pipeline(
                    ck_info=ck_info
                )
                result["cleaned_notebooks"] = cleaned
            except Exception as e:
                result["errors"].append(
                    "Failed to clean notebooks in pipeline: "
                    f"{e.__class__.__name__}: {e}"
                )
                return PipelineStatus.model_validate(result)
        try:
            dvc_repo = calkit.dvc.get_dvc_repo()
            raw_status = dvc_repo.status(targets=targets)
        except Exception as e:
            result["errors"].append(
                "Failed to get pipeline status from DVC: "
                f"{e.__class__.__name__}: {e}"
            )
            return PipelineStatus.model_validate(result)
        raw_stale_stages = {
            k.split("dvc.yaml:")[-1]: v
            for k, v in raw_status.items()
            if v != ["always changed"] and not k.endswith(".dvc")
        }
        stages_config = ck_info.get("pipeline", {}).get("stages", {})
        result["stale_stages"] = {
            stage_name: StaleStage.from_status_data(
                status_data=status_data,
                configured_outputs=[
                    output.get("path", str(output))
                    if isinstance(output, dict)
                    else str(output)
                    for output in stages_config.get(stage_name, {}).get(
                        "outputs", []
                    )
                ],
            )
            for stage_name, status_data in raw_stale_stages.items()
        }
        return PipelineStatus.model_validate(result)
    finally:
        if wdir is not None:
            os.chdir(prev_cwd)


def to_dvc(
    ck_info: dict | None = None,
    wdir: str | None = None,
    write: bool = False,
    verbose: bool = False,
) -> dict:
    """Compile a Calkit pipeline to a DVC pipeline."""
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    if "pipeline" not in ck_info:
        raise ValueError("No pipeline found in calkit.yaml")
    try:
        pipeline = Pipeline.model_validate(ck_info["pipeline"])
    except Exception as e:
        raise ValueError(f"Pipeline is not defined properly: {e}")
    dvc_stages = {}
    # Read existing dvc.yaml now so we can clean up stale .gitignore entries
    # when stage outputs are renamed or removed
    if write:
        dvc_yaml_path = os.path.join(wdir, "dvc.yaml") if wdir else "dvc.yaml"
        if os.path.isfile(dvc_yaml_path):
            with open(dvc_yaml_path) as f:
                existing_dvc_yaml = calkit.ryaml.load(f)
        else:
            existing_dvc_yaml = {}
        if existing_dvc_yaml is None:
            existing_dvc_yaml = {}
        existing_dvc_stages = existing_dvc_yaml.get("stages", {})
    else:
        existing_dvc_stages = {}
    # First, gather up any env lock paths we might need for DVC deps
    used_envs = set(
        [stage.inner_environment for stage in pipeline.stages.values()]
    )
    env_lock_fpaths = {}
    environments = ck_info.get("environments", {})
    for env_name, env in environments.items():
        if env_name not in used_envs:
            continue
        lock_fpath = get_env_lock_fpath(
            env=env, env_name=env_name, as_posix=True, for_dvc=True
        )
        if lock_fpath is None:
            continue
        env_lock_fpaths[env_name] = lock_fpath
    project_params = expand_project_parameters(ck_info.get("parameters", {}))
    # Set any stage slurm options, which requires environment information
    pipeline.set_stage_slurm_options(environments=environments)
    # Ensure environment lock files are set as stage inputs if necessary
    pipeline.ensure_env_lock_paths_are_inputs(env_lock_fpaths=env_lock_fpaths)
    # Now convert Calkit stages into DVC stages
    for stage_name, stage in pipeline.stages.items():
        # If this stage is a Jupyter notebook stage, we need to update its
        # parameters if any reference project-level parameters
        if stage.kind == "jupyter-notebook":
            stage.update_parameters(params=project_params)
        dvc_stage = stage.to_dvc()
        # Check if this stage iterates, which means we should create a matrix
        # stage
        if stage.iterate_over is not None:
            # Process a list of iterations into a DVC matrix stage
            # Initialize a DVC matrix
            dvc_matrix = {}
            # Initialize a dict for doing string formatting on the DVC stage
            format_dict = {}
            for n, iteration in enumerate(stage.iterate_over):
                arg_name = iteration.arg_name
                exp_vals = iteration.expand_values(params=project_params)
                if isinstance(arg_name, list):
                    dvc_arg_name = f"_arg{n}"
                    for arg_name_i in arg_name:
                        item_string = f"${{item.{dvc_arg_name}.{arg_name_i}}}"
                        format_dict[arg_name_i] = item_string
                else:
                    dvc_arg_name = arg_name
                    format_dict[arg_name] = f"${{item.{arg_name}}}"
                dvc_matrix[dvc_arg_name] = exp_vals
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
                            f"Failed to format dep '{dep}' with "
                            f"'{format_dict}': "
                            f"{e.__class__.__name__}: {e}"
                        )
                    )
            for out in dvc_stage.get("outs", []):
                try:
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
                except Exception as e:
                    raise ValueError(
                        (
                            f"Failed to format out '{out}' with "
                            f"'{format_dict}': "
                            f"{e.__class__.__name__}: {e}"
                        )
                    )
            dvc_stage["deps"] = formatted_deps
            dvc_stage["outs"] = formatted_outs
            dvc_stage["matrix"] = dvc_matrix
        # Add a description to the DVC stage
        desc = (
            f"Automatically generated from the '{stage_name}' stage "
            "in calkit.yaml. Changes made here will be overwritten."
        )
        dvc_stage["desc"] = desc
        dvc_stages[stage_name] = dvc_stage
        # Check for any outputs that should be ignored/unignored
        if write:
            repo = git.Repo(wdir)
            # Ensure we catch any Jupyter Notebook outputs
            outputs = stage.outputs.copy()
            if stage.kind == "jupyter-notebook":
                outputs += stage.notebook_outputs
            elif stage.kind == "sbatch":
                outputs.append(stage.log_output)
            # Build the set of current DVC output paths so we can detect stale
            # .gitignore entries from the previous version of the stage,
            # including synthesized outputs like LaTeX PDFs
            current_out_paths = set(calkit.dvc.out_paths_from_stage(dvc_stage))
            # If this stage already existed, un-ignore any outputs that have
            # been renamed or removed so .gitignore does not accumulate stale
            # entries (e.g., after a capitalization change in the path)
            old_stage = existing_dvc_stages.get(stage_name, {})
            for old_path in calkit.dvc.out_paths_from_stage(old_stage):
                if old_path not in current_out_paths:
                    calkit.git.ensure_path_is_not_ignored(repo, path=old_path)
            # Deal with any gitignore changes necessary
            for out in outputs:
                if isinstance(out, PathOutput) and out.storage is None:
                    calkit.git.ensure_path_is_ignored(repo, path=out.path)
                # Unignore path if necessary
                elif isinstance(out, PathOutput) and out.storage == "git":
                    calkit.git.ensure_path_is_not_ignored(repo, path=out.path)
    # Now process any inputs from stage outputs
    for stage_name, stage in pipeline.stages.items():
        for i in stage.inputs:
            if isinstance(i, InputsFromStageOutputs):
                dvc_outs = dvc_stages[i.from_stage_outputs]["outs"]
                for out in dvc_outs:
                    if out not in dvc_stages[stage_name]["deps"]:
                        # Handle cases where outs are from a matrix,
                        # in which case this output could become a list of
                        # outputs
                        if isinstance(out, dict):
                            out = list(out.keys())[0]
                        if "${item." in out:
                            extra_outs = []
                            dvc_matrix = dvc_stages[i.from_stage_outputs][
                                "matrix"
                            ]
                            replacements = _expand_matrix(dvc_matrix)
                            for r in replacements:
                                out_i = out
                                for var_name, var_val in r.items():
                                    out_i = out_i.replace(
                                        f"${{item.{var_name}}}",
                                        str(var_val),
                                    )
                                extra_outs.append(out_i)
                            for out_i in extra_outs:
                                if out_i not in dvc_stages[stage_name]["deps"]:
                                    dvc_stages[stage_name]["deps"].append(
                                        out_i
                                    )
                        else:
                            dvc_stages[stage_name]["deps"].append(out)
    if write:
        dvc_yaml = existing_dvc_yaml
        existing_stages = existing_dvc_stages
        for stage_name, stage in existing_stages.items():
            # Skip private stages (ones whose names start with an underscore)
            # and stages that are automatically generated
            if (
                not stage_name.startswith("_")
                and stage_name not in dvc_stages
                and not stage.get("desc", "").startswith(
                    "Automatically generated"
                )
            ):
                dvc_stages[stage_name] = stage
        dvc_yaml["stages"] = dvc_stages
        with open("dvc.yaml", "w") as f:
            if verbose:
                typer.echo("Writing to dvc.yaml")
            calkit.ryaml.dump(dvc_yaml, f)
    return dvc_stages
