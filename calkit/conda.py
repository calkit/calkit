"""Functionality for working with conda environments."""

import json
import os
import re
import subprocess

from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import BaseModel

import calkit
from calkit import ryaml


def _check_single(req: str, actual: str, conda: bool = False) -> bool:
    """Helper function for checking actual versions against requirements."""
    req_name = re.split("[=<>]", req)[0]
    req_spec = req.removeprefix(req_name)
    if conda and req_spec.startswith("="):
        req_spec = "=" + req_spec
        if not req_spec.endswith(".*"):
            req_spec += ".*"
    actual_name, actual_vers = re.split("[=<>]+", actual, maxsplit=1)
    if actual_name != req_name:
        return False
    actual_spec = actual.removeprefix(actual_name)
    if conda and actual_spec.startswith("="):
        actual_spec = "=" + actual_spec
    version = Version(actual_vers)
    spec = SpecifierSet(req_spec)
    return spec.contains(version)


def _check_list(req: str, actual: list[str], conda: bool = False) -> bool:
    for installed in actual:
        if _check_single(req, installed, conda=conda):
            return True
    return False


class EnvCheckResult(BaseModel):
    env_exists: bool | None = None
    env_needs_export: bool | None = None
    env_needs_rebuild: bool | None = None


def check_env(
    env_fpath: str = "environment.yml",
    use_mamba=True,
    log_func=None,
    output_fpath: str = None,
    relaxed: bool = False,
) -> EnvCheckResult:
    """Check that a conda environment matches its spec.

    If it doesn't match, recreate it.

    Note that this only works with exact or no version specification.
    Using greater than and less than operators is not supported.

    If ``relaxed`` is enabled, dependencies can exist in either the conda or
    pip category.
    """
    conda = "mamba" if use_mamba else "conda"
    if log_func is None:
        log_func = calkit.logger.info
    log_func(f"Checking conda env defined in {env_fpath}")
    res = EnvCheckResult()
    envs = json.loads(
        subprocess.check_output([conda, "env", "list", "--json"]).decode()
    )["envs"]
    # Get existing env names, but skip the base environment
    # Note that this could fail for environments with non-default prefixes
    existing_env_names = [
        os.path.basename(env) for env in envs if "envs" in env
    ]
    with open(env_fpath) as f:
        env_spec = ryaml.load(f)
    env_name = env_spec["name"]
    env_check_fpath = os.path.join(
        os.path.expanduser("~"),
        ".calkit",
        "conda-env-checks",
        env_name + ".yml",
    )
    env_check_dir = os.path.dirname(env_check_fpath)
    os.makedirs(env_check_dir, exist_ok=True)
    # Check if env even exists
    if env_name not in existing_env_names:
        log_func(f"Environment {env_name} doesn't exist; creating")
        res.env_exists = False
        # Environment doesn't exist, so create it
        subprocess.check_call([conda, "env", "create", "-y", "-f", env_fpath])
        env_needs_rebuild = False
        env_needs_export = True
    else:
        res.env_exists = True
        env_needs_export = False
        # Environment does exist, so check it
        if os.path.isfile(env_check_fpath):
            # Open up the env check result file
            with open(env_check_fpath) as f:
                env_check = ryaml.load(f)
            # Check the prefix mtime saved to that file against the actual
            # prefix mtime
            # If they match, the environment saved in env_check is still
            # valid, so we don't need to re-export
            existing_mtime = env_check["mtime"]
            current_mtime = os.path.getmtime(
                os.path.normpath(env_check["prefix"])
            )
            env_needs_export = existing_mtime != current_mtime
        else:
            env_needs_export = True
        if env_needs_export:
            res.env_needs_export = True
            log_func(f"Exporting existing env to {env_check_fpath}")
            env_check = json.loads(
                subprocess.check_output(
                    [
                        "conda",  # Mamba output is slightly different
                        "env",
                        "export",
                        "-n",
                        env_name,
                        "--no-builds",
                        "--json",
                    ]
                ).decode()
            )
            env_check["mtime"] = os.path.getmtime(
                os.path.normpath(env_check["prefix"])
            )
            with open(env_check_fpath, "w") as f:
                ryaml.dump(env_check, f)
        # Determine if the env matches
        env_needs_rebuild = False
        if isinstance(env_check["dependencies"][-1], dict):
            existing_conda_deps = env_check["dependencies"][:-1]
            existing_pip_deps = env_check["dependencies"][-1]["pip"]
        else:
            existing_conda_deps = env_check["dependencies"]
            existing_pip_deps = []
        if isinstance(env_spec["dependencies"][-1], dict):
            required_conda_deps = env_spec["dependencies"][:-1]
            required_pip_deps = env_spec["dependencies"][-1]["pip"]
        else:
            required_conda_deps = env_spec["dependencies"]
            required_pip_deps = []
        if relaxed:
            log_func("Running in relaxed mode; combining pip and conda deps")
            for dep in existing_pip_deps:
                existing_conda_deps.append(dep.replace("==", "="))
            for dep in required_pip_deps:
                required_conda_deps.append(dep.replace("==", "="))
        log_func("Checking conda dependencies")
        for dep in required_conda_deps:
            is_okay = _check_list(
                req=dep, actual=existing_conda_deps, conda=True
            )
            if not is_okay:
                log_func(f"Found missing dependency: {dep}")
                env_needs_rebuild = True
                break
        if not env_needs_rebuild and not relaxed:
            log_func("Checking pip dependencies")
            for dep in required_pip_deps:
                is_okay = _check_list(
                    req=dep, actual=existing_pip_deps, conda=False
                )
                if not is_okay:
                    env_needs_rebuild = True
                    log_func(f"Found missing dependency: {dep}")
                    break
    if env_needs_rebuild:
        res.env_needs_rebuild = True
        log_func(f"Rebuilding {env_name} since it does not match spec")
        subprocess.check_call([conda, "env", "create", "-y", "-f", env_fpath])
        env_needs_export = True
    else:
        log_func(f"Environment {env_name} matches spec")
        res.env_needs_rebuild = False
    # If the env was rebuilt, export the env check
    if env_needs_export:
        log_func(f"Exporting existing env to {env_check_fpath}")
        env_check = json.loads(
            subprocess.check_output(
                [
                    "conda",  # Mamba output is slightly different
                    "env",
                    "export",
                    "-n",
                    env_name,
                    "--no-builds",
                    "--json",
                ]
            ).decode()
        )
        env_check["mtime"] = os.path.getmtime(
            os.path.normpath(env_check["prefix"])
        )
        with open(env_check_fpath, "w") as f:
            ryaml.dump(env_check, f)
    if output_fpath is None:
        fname, ext = os.path.splitext(env_fpath)
        output_fpath = fname + "-lock" + ext
    if (
        not res.env_exists
        or res.env_needs_rebuild
        or not os.path.isfile(output_fpath)
    ):
        log_func(f"Exporting lock file to {output_fpath}")
        with open(output_fpath, "w") as f:
            _ = env_check.pop("mtime")
            _ = env_check.pop("prefix")
            ryaml.dump(env_check, f)
    return res
