"""Functionality for working with conda environments."""

from __future__ import annotations

import json
import os
import re
import subprocess
import warnings
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel

import calkit
from calkit import ryaml


def _editable_package_name_from_dir(dir_path: str) -> str:
    """Get the package name from a directory containing ``setup.py`` or
    ``pyproject.toml``.
    """
    if os.path.isfile(os.path.join(dir_path, "setup.py")):
        # Read setup.py to get the package name
        with open(os.path.join(dir_path, "setup.py")) as f:
            setup_contents = f.read()
        match = re.search(r"name\s*=\s*['\"]([^'\"]+)['\"]", setup_contents)
        if match:
            return match.group(1)
    elif os.path.isfile(os.path.join(dir_path, "pyproject.toml")):
        # Read pyproject.toml to get the package name
        with open(os.path.join(dir_path, "pyproject.toml")) as f:
            pyproject_contents = f.read()
        match = re.search(
            r'name\s*=\s*["\']([^"\']+)["\']', pyproject_contents
        )
        if match:
            return match.group(1)
    raise ValueError(f"Could not determine package name from {dir_path}")


def _check_single(req: str, actual: str, conda: bool = False) -> bool:
    """Helper function for checking actual versions against requirements.

    Note that this also doesn't check optional dependencies.
    """
    # If this is an editable install it needs to be handled specially
    if req.startswith("-e ") or req.startswith("--editable "):
        req = req.split(" ", 1)[1]
        if "#" in req:
            req = req.split("#", 1)[0]
        req = req.strip()
        req = _editable_package_name_from_dir(req)
    # If this is a Git version, we can't check it
    # TODO: Clone Git repos to check?
    if "@git" in req:
        warnings.warn(f"Cannot check Git version for {req}")
        req = req.split("@git")[0]
    req_name = re.split("[=<>]", req)[0].strip()
    req_spec = req.removeprefix(req_name).strip().replace(" ", "")
    if "[" in req_name:
        warnings.warn(f"Cannot check optional dependencies for {req_name}")
        # Remove optional dependencies
        req_name = req_name.split("[")[0].strip()
    if conda and req_spec.startswith("="):
        req_spec = "=" + req_spec
        if not req_spec.endswith(".*"):
            # Check that the requirement spec is all numbers and dots and add
            # an asterisk if it's missing, since conda treats "package=1.2" as
            # "package=1.2.*"
            numbers_and_dots = re.match(r"^[0-9.]+$", req_spec[1:])
            if numbers_and_dots and len(req_spec.split(".")) < 3:
                req_spec += ".*"
    actual_name, actual_vers = re.split("[=<>]+", actual, maxsplit=1)
    if actual_name != req_name:
        return False
    actual_spec = actual.removeprefix(actual_name)
    if conda and actual_spec.startswith("="):
        actual_spec = "=" + actual_spec
    try:
        version = Version(actual_vers)
    except InvalidVersion:
        warnings.warn(
            f"Cannot properly check {actual_name} version {actual_vers}"
        )
        # TODO: Check exact version only
        return True
    spec = SpecifierSet(req_spec)
    return spec.contains(version)


def _check_list(req: str, actual: list[str], conda: bool = False) -> bool:
    """Check a requirement against a list of installed packages."""
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
    log_func=None,
    output_fpath: str | None = None,
    alt_lock_fpaths: list[str] = [],
    alt_lock_fpaths_delete: list[str] = [],
    relaxed: bool = False,
) -> EnvCheckResult:
    """Check that a conda environment matches its spec.

    If it doesn't match, recreate it.

    Note that this only works with exact or no version specification.
    Using greater than and less than operators is not supported.

    If ``relaxed`` is enabled, dependencies can exist in either the conda or
    pip category.
    """
    if log_func is None:
        log_func = calkit.logger.info
    log_func(f"Checking conda env defined in {env_fpath}")
    # Determine which lock file to use for creating the environment
    lock_to_use_for_creation = None
    used_legacy_lock = None
    if output_fpath and not os.path.isfile(output_fpath):
        # Try alternative lock files first
        for alt_fpath in alt_lock_fpaths:
            if os.path.isfile(alt_fpath):
                lock_to_use_for_creation = alt_fpath
                log_func(
                    f"Found alternative lock file for creation: {alt_fpath}"
                )
                break
        # Try legacy lock files
        for legacy_fpath in alt_lock_fpaths_delete:
            if os.path.isfile(legacy_fpath):
                lock_to_use_for_creation = legacy_fpath
                used_legacy_lock = legacy_fpath
                log_func(
                    f"Using legacy lock file for creation: {legacy_fpath}"
                )
                break
    elif output_fpath and os.path.isfile(output_fpath):
        lock_to_use_for_creation = output_fpath
        log_func(f"Using existing lock file for creation: {output_fpath}")
    res = EnvCheckResult()
    info = json.loads(subprocess.check_output(["conda", "info", "--json"]))
    root_prefix = info["root_prefix"]
    envs_dir = os.path.join(root_prefix, "envs")
    if calkit.check_dep_exists("mamba"):
        # Use mamba by default because it's faster and produces less output
        conda_name = "mamba"
    else:
        conda_name = "conda"
    envs = json.loads(
        subprocess.check_output([conda_name, "env", "list", "--json"]).decode()
    )["envs"]
    # Get existing env names for those in the envs directory
    existing_env_names = [
        os.path.basename(env) for env in envs if env.startswith(envs_dir)
    ]
    # Get a list of environments defined by prefix instead of name
    env_prefixes = [e for e in envs if not e.startswith(root_prefix)]
    with open(env_fpath) as f:
        env_spec = ryaml.load(f)
    env_name = env_spec["name"]
    prefix = env_spec.get("prefix")
    prefix_orig = prefix
    if prefix is not None:
        prefix = os.path.abspath(prefix)
        env_check_fpath = os.path.join(prefix, "env-export.yml")
    else:
        env_check_fpath = os.path.join(
            os.path.expanduser("~"),
            ".calkit",
            "conda-env-checks",
            env_name + ".yml",
        )
    env_check_dir = os.path.dirname(env_check_fpath)
    os.makedirs(env_check_dir, exist_ok=True)
    # Create env export command, which will be used later
    export_cmd = [
        "conda",  # Mamba output is slightly different
        "env",
        "export",
        "--no-builds",
        "--json",
    ]
    # Create with conda since newer mamba versions create a strange
    # "Library" subdirectory, at least on Windows
    # Use lock file for creation if available, otherwise use env spec
    create_file = (
        lock_to_use_for_creation if lock_to_use_for_creation else env_fpath
    )
    create_cmd = ["conda", "env", "create", "-y", "-f", create_file]
    if prefix is not None:
        export_cmd += ["--prefix", prefix]
        create_cmd += ["--prefix", prefix]
    else:
        export_cmd += ["-n", env_name]
    # Check if env even exists
    # If env has a prefix defined, it will be identified by that
    if env_name not in existing_env_names and prefix not in env_prefixes:
        log_func(f"Environment {env_name} doesn't exist; creating")
        res.env_exists = False
        # Environment doesn't exist, so create it
        try:
            subprocess.check_call(create_cmd)
            # Delete legacy lock file after successful creation
            if used_legacy_lock:
                try:
                    os.remove(used_legacy_lock)
                    log_func(
                        "Deleted legacy lock file after use: "
                        f"{used_legacy_lock}"
                    )
                except Exception as e:
                    log_func(
                        f"Failed to delete legacy lock file "
                        f"{used_legacy_lock}: {e}"
                    )
        except subprocess.CalledProcessError:
            # If creation from lock file failed, try from env spec
            if create_file != env_fpath:
                log_func(
                    "Failed to create from lock file, trying from env spec"
                )
                create_cmd = ["conda", "env", "create", "-y", "-f", env_fpath]
                if prefix is not None:
                    create_cmd += ["--prefix", prefix]
                subprocess.check_call(create_cmd)
            else:
                raise
        env_needs_rebuild = False
        env_needs_export = True
    else:
        res.env_exists = True
        env_needs_export = False
        # Environment does exist, so check it
        if os.path.isfile(env_check_fpath):
            log_func(f"Found env check file at {env_check_fpath}")
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
            log_func(f"Env check mtime: {existing_mtime}")
            log_func(f"Env dir mtime: {current_mtime}")
            env_needs_export = existing_mtime != current_mtime
        else:
            log_func(f"Env check file at {env_check_fpath} does not exist")
            env_needs_export = True
        if env_needs_export:
            log_func(f"Exporting existing env to {env_check_fpath}")
            env_check = json.loads(
                subprocess.check_output(export_cmd).decode()
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
        # Always rebuild from env spec file, not lock file
        rebuild_cmd = [
            "conda",
            "env",
            "create",
            "-y",
            "-f",
            env_fpath,
        ]
        if prefix is not None:
            rebuild_cmd += ["--prefix", prefix]
        subprocess.check_call(rebuild_cmd)
        env_needs_export = True
        # Delete legacy lock file after successful rebuild from spec
        if used_legacy_lock:
            try:
                os.remove(used_legacy_lock)
                log_func(
                    "Deleted legacy lock file after rebuild: "
                    f"{used_legacy_lock}"
                )
            except Exception as e:
                log_func(
                    "Failed to delete legacy lock file "
                    f"{used_legacy_lock}: {e}"
                )
    else:
        log_func(f"Environment {env_name} matches spec")
        res.env_needs_rebuild = False
        # Delete legacy lock file since environment is up-to-date
        if used_legacy_lock:
            try:
                os.remove(used_legacy_lock)
                log_func(
                    "Deleted legacy lock file (env matches spec): "
                    f"{used_legacy_lock}"
                )
            except Exception as e:
                log_func(
                    "Failed to delete legacy lock file "
                    f"{used_legacy_lock}: {e}"
                )
    # If the env was rebuilt, export the env check
    res.env_needs_export = env_needs_export
    if env_needs_export:
        log_func(f"Exporting existing env to {env_check_fpath}")
        env_check = json.loads(subprocess.check_output(export_cmd).decode())
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
        env_export = json.loads(
            subprocess.check_output(
                [a for a in export_cmd if a != "--no-builds"]
            ).decode()
        )
        # Remove prefix from env export since it will be an absolute path
        _ = env_export.pop("prefix")
        # Remove name if prefix is set, since that will be the prefix
        if prefix is not None:
            _ = env_export.pop("name")
            env_export["prefix"] = prefix_orig
        # If we have any editable installs, convert them back to editable from
        # their exported package names
        # Note that this needs to be relative to the env lock directory,
        # since that's how pip will interpret it
        editable_pip_deps = {}
        if isinstance(env_spec["dependencies"][-1], dict):
            # Map editable install dir to package name we'd see in lock
            required_pip_deps = env_spec["dependencies"][-1]["pip"]
            for dep in required_pip_deps:
                if dep.startswith("-e ") or dep.startswith("--editable "):
                    dir_path = dep.split(" ", 1)[1]
                    if "#" in dir_path:
                        dir_path = dir_path.split("#", 1)[0]
                    dir_path = dir_path.strip()
                    pkg_name = _editable_package_name_from_dir(dir_path)
                    editable_pip_deps[pkg_name] = dir_path
        if isinstance(env_export["dependencies"][-1], dict):
            export_pip_deps = env_export["dependencies"][-1]["pip"]
            for i, dep in enumerate(export_pip_deps):
                dep_name = re.split("[=<>]+", dep, maxsplit=1)[0]
                if dep_name in editable_pip_deps:
                    path_rel_to_project_root = editable_pip_deps[dep_name]
                    lock_dir = os.path.dirname(output_fpath)
                    path_rel_to_lock = os.path.relpath(
                        path_rel_to_project_root, start=lock_dir
                    )
                    export_pip_deps[i] = (
                        "-e " + Path(path_rel_to_lock).as_posix()
                    )
        out_dir = os.path.dirname(output_fpath)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output_fpath, "w") as f:
            ryaml.dump(env_export, f)
    return res
