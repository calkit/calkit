"""Functionality related to environments."""

import functools
import glob
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import cast

import toml
import yaml
from pydantic import BaseModel
from sqlitedict import SqliteDict

import calkit

DOCKER_ARCHS = [
    "amd64",
    "arm64",
    "arm-v7",
    "arm-v6",
    "arm-v5",
    "ppc64le",
    "s390x",
    "386",
    "riscv64",
]
# Architectures Docker environments are locked for by default, so that
# moving a project between them doesn't invalidate every stage
DEFAULT_DOCKER_LOCK_ARCHS = ["amd64", "arm64"]
DEFAULT_PYTHON_VERSION = "3.14"
CONDA_VENV_ARCHS = [
    "osx-arm64",
    "osx-64",
    "linux-aarch64",
    "linux-ppc64le",
    "linux-64",
    "win-64",
]
ENV_CHECK_CACHE_TTL_SECONDS = 3600
# Scheduler environment keys that govern how a job is dispatched rather than
# what it computes. They are excluded from the environment lock file, so
# changing them does not invalidate cached results: pacing submissions to be
# polite to a shared queue must not force every simulation to rerun.
SCHEDULER_DISPATCH_ONLY_KEYS = {"max_concurrent_jobs"}
# Environment kinds with nothing to build or verify. Note this matches on
# ``kind``; the special ``_system`` environment is excluded by name instead,
# since names starting with an underscore are filtered out of the pipeline's
# environment list before we get here. ``system`` is not listed: checking one
# means writing its lock file, so it has to go through ``check_environment``.
# No kind is unconditionally uncheckable. A ``system`` env on another host
# comes close, but that depends on the env's host rather than its kind, and
# ``check_environment`` handles it: with nothing locked there is nothing to
# check, and locking a machine we can't observe is an error.
KINDS_NO_CHECK: list[str] = []

# Kinds whose check must not be cached. Caching exists to skip rebuilding
# something expensive, but checking a ``system`` env *is* reading the
# machine -- there is nothing to skip. Caching it means a locked property
# can change and be missed until the cache expires, which is precisely the
# drift ``lock`` exists to catch.
KINDS_NO_CACHE = ["system"]


def cacheable(env: dict) -> bool:
    """Whether an environment's check is worth remembering."""
    return env.get("kind") not in KINDS_NO_CACHE


# Maps the kebab-case properties a ``system`` environment can lock onto the
# keys ``get_system_info`` returns. Not a mechanical transformation, hence
# the explicit table: note ``Rscript_version``'s capital R.
SYSTEM_LOCK_PROPERTIES = {
    "os": "os",
    "os-version": "os_version",
    "platform": "platform",
    "machine": "machine",
    "processor": "processor",
    "hostname": "hostname",
    "machine-id": "machine_id",
    "cpu-count": "cpu_count",
    "memory-gb": "memory_gb",
    "python-version": "python_version",
    "python-implementation": "python_implementation",
    "git-version": "git_version",
    "docker-version": "docker_version",
    "conda-version": "conda_version",
    "mamba-version": "mamba_version",
    "uv-version": "uv_version",
    "pixi-version": "pixi_version",
    "julia-version": "julia_version",
    "juliaup-version": "juliaup_version",
    "rscript-version": "Rscript_version",
    "brew-version": "brew_version",
}

# What each lockable property means, for the published documentation. Kept
# beside the table above so the two can be checked against each other; a
# property nobody can describe is one nobody can decide whether to lock.
SYSTEM_LOCK_PROPERTY_DESCRIPTIONS = {
    "os": "Operating system name, e.g. 'Linux' or 'Darwin'.",
    "os-version": "Operating system release, e.g. a kernel version.",
    "platform": "Full platform string, which folds in most of the above.",
    "machine": "Machine architecture, e.g. 'x86_64' or 'arm64'.",
    "processor": "Processor name, where the OS reports one.",
    "hostname": "The machine's name. Pins results to one specific host, "
    "but only by name: renaming the machine breaks the pin, and a machine "
    "elsewhere with the same name satisfies it. Prefer 'machine-id'.",
    "machine-id": "A stable identifier for the machine itself, read from "
    "the platform. Pins results to one specific machine, and unlike "
    "'hostname' survives renaming it. Declaring a 'machine_id' on the "
    "environment says where to run, not that results depend on it, so "
    "lock this to also rerun stages when the machine changes.",
    "cpu-count": "Number of CPUs, which can change what a run produces "
    "where results depend on how work was divided.",
    "memory-gb": "Total memory in GB.",
    "python-version": "Version of the Python running Calkit.",
    "python-implementation": "Python implementation, e.g. 'CPython'.",
    "git-version": "Installed Git version.",
    "docker-version": "Installed Docker version.",
    "conda-version": "Installed Conda version.",
    "mamba-version": "Installed Mamba version.",
    "uv-version": "Installed uv version.",
    "pixi-version": "Installed Pixi version.",
    "julia-version": "Installed Julia version.",
    "juliaup-version": "Installed Juliaup version.",
    "rscript-version": "Installed Rscript version.",
    "brew-version": "Installed Homebrew version.",
}

# How precisely a property is worth recording. Total memory is reported as
# a bare division of bytes by 1024**3, so a machine describes itself as
# having 15.492069244384766 GB, and a firmware or kernel update that
# reserves a little more or less moves that without changing anything a
# result could depend on. Rounding it is the difference between pinning how
# much memory the machine has and pinning what it happened to report.
# Everything else is recorded as given: an OS version or a CPU count means
# exactly what it says.
SYSTEM_LOCK_PROPERTY_PRECISION = {"memory-gb": lambda v: round(float(v), 1)}

# Properties only one platform can supply, since ``get_system_info`` collects
# package manager versions per OS. Locking one from another platform raises
# in ``get_system_lock_data`` rather than recording nothing, so this table is
# documentation (and a test hook), not a second gate.
SYSTEM_LOCK_PROPERTY_PLATFORMS = {"brew-version": "Darwin"}


def _as_posix_path(path: str) -> str:
    return Path(path).as_posix()


COMPOSITE_ENV_SEP = ":"
# Kinds that say *where* a stage runs rather than what it runs in, so they
# can wrap an inner runtime env as ``<outer>:<inner>``.
VALID_OUTER_ENV_KINDS = ["slurm", "pbs", "system"]


def host_is_local(host: str | None) -> bool:
    """Whether ``host`` names the machine we're running on.

    Environments that name a host (``system``, ``slurm``, ``pbs``) are
    declarations of where the work belongs, not instructions to connect:
    when we're already on that machine there is nothing to reach out to.

    A machine reports itself as a bare name or a fully qualified one
    depending on how it's configured, and projects write it either way, so
    the two are matched across that difference. A domain is only dropped
    from one side at a time, so two different machines that share a short
    name under different domains stay distinct.
    """
    if not host or host == "localhost":
        return True
    current_host = socket.gethostname()
    current_fqdn = socket.getfqdn()
    if host in (current_host, current_fqdn):
        return True
    if "." not in host:
        # A bare env host matches this machine's short name, however this
        # machine happens to report itself.
        if host in (
            current_host.split(".")[0],
            current_fqdn.split(".")[0],
        ):
            return True
    elif "." not in current_fqdn:
        # A qualified env host can still name a machine that only knows its
        # own short name; there is no domain here to contradict it.
        if host.split(".")[0] in (current_host, current_fqdn):
            return True
    # Names are not the only way to write a machine down. A host given as
    # an IP address never matches a hostname, and a machine reached at one
    # address may call itself something else entirely -- so ask whether any
    # address this host resolves to is one of ours.
    return _resolves_to_this_machine(host)


@functools.lru_cache(maxsize=128)
def _host_addresses(host: str) -> tuple[tuple[int, str], ...]:
    """The addresses ``host`` resolves to, as (family, address) pairs."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_DGRAM)
    except (socket.gaierror, UnicodeError, OSError):
        return ()
    return tuple(
        {(family, sockaddr[0]) for family, _, _, _, sockaddr in infos}
    )


def _address_is_local(family: int, address: str) -> bool:
    """Whether an address belongs to an interface on this machine.

    Binding is the question itself rather than a proxy for it: an address
    can only be bound where it is actually configured, which is exactly
    what "this is my address" means. Reading interfaces directly would need
    a dependency and would still have to answer the same question.
    """
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.bind((address, 0))
        return True
    except OSError:
        return False


def _resolves_to_this_machine(host: str) -> bool:
    if any(
        _address_is_local(family, address)
        for family, address in _host_addresses(host)
    ):
        return True
    # A bare name can be one only mDNS knows, which is not in the resolver's
    # search list the way a DNS domain is -- so it resolves under '.local'
    # and nowhere else. This is the name macOS shows the user as theirs (in
    # Sharing, and from 'scutil --get LocalHostName'), so it is the name
    # they are most likely to write down, and it would otherwise be the one
    # name for this machine that fails to match it.
    if "." in host:
        return False
    return any(
        _address_is_local(family, address)
        for family, address in _host_addresses(host + ".local")
    )


def env_is_local(env: dict) -> bool:
    """Whether an environment's machine is the one we're running on.

    A declared ``machine_id`` is the answer when there is one: it is a
    stronger claim than a name, so a host that resolves here while the ID
    says otherwise is a machine that was rebuilt or a name that now points
    somewhere else -- both cases where running here would be wrong.

    That only holds while we can tell which machine this is. Where no ID
    can be read, a declared one can never match, and taking that as "not
    this machine" would send a user off to SSH into the box they are
    sitting at; the name is what's left to go on, so it decides.
    """
    declared = env.get("machine_id")
    if declared:
        declared = os.path.expandvars(declared)
    if declared:
        current = calkit.get_machine_id()
        if current is not None:
            return calkit.machine_ids_match(declared, current)
    return host_is_local(os.path.expandvars(env.get("host") or ""))


def get_julia_packages_dir() -> str:
    """Return the Julia packages directory for the current environment."""
    depot_env = os.getenv("JULIA_DEPOT_PATH", "")
    first_depot = depot_env.split(os.pathsep)[0].strip() if depot_env else ""
    if not first_depot:
        first_depot = os.path.join("~", ".julia")
    return os.path.join(os.path.expanduser(first_depot), "packages")


def _calc_dir_sig_shallow(path: str, max_depth: int = 1) -> str:
    """Calculate a lightweight signature by scanning only a few levels.

    This avoids deep recursive walks of large directories while still
    detecting practical state changes like added/removed packages or
    artifacts.
    """
    if not os.path.isdir(path):
        return ""
    try:
        root_stat = os.stat(path)
        latest_mtime = root_stat.st_mtime_ns
    except OSError:
        return ""
    entry_count = 0
    total_size = 0
    stack: list[tuple[str, int]] = [(path, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    entry_count += 1
                    total_size += st.st_size
                    if st.st_mtime_ns > latest_mtime:
                        latest_mtime = st.st_mtime_ns
                    if depth < max_depth and entry.is_dir(
                        follow_symlinks=False
                    ):
                        stack.append((entry.path, depth + 1))
        except OSError:
            continue
    return f"{entry_count}-{total_size}-{latest_mtime}"


def calc_julia_depot_sig() -> str | None:
    """Calculate a cheap machine-state signature for Julia depot changes."""
    packages_dir = get_julia_packages_dir()
    depot_root = os.path.dirname(packages_dir)
    packages_sig = _calc_dir_sig_shallow(packages_dir, max_depth=1)
    artifacts_sig = _calc_dir_sig_shallow(
        os.path.join(depot_root, "artifacts"), max_depth=1
    )
    registries_sig = _calc_dir_sig_shallow(
        os.path.join(depot_root, "registries"), max_depth=1
    )
    if not any([packages_sig, artifacts_sig, registries_sig]):
        return None
    return "|".join([packages_sig, artifacts_sig, registries_sig])


def language_from_env(env: dict) -> str | None:
    kind = env.get("kind")
    if kind == "julia":
        return "julia"
    if kind == "renv":
        return "r"
    if kind == "matlab":
        return "matlab"
    if kind in ["conda", "pixi", "uv", "uv-venv", "venv"]:
        return "python"
    if kind == "docker" and "texlive" in env.get("image", "").lower():
        return "latex"
    return None


def _get_julia_version() -> str:
    """Detect the active Julia version.

    Returns
    -------
    str
        Julia version string (e.g., "1.10.1"). Defaults to "1.10" if
        detection fails.
    """
    try:
        result = subprocess.run(
            [calkit.julia.get_julia_exe(), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Parse output like "julia version 1.10.1"
            output = result.stdout.strip()
            # Extract version number
            parts = output.split()
            for part in parts:
                # Check if this part looks like a version
                if part and part[0].isdigit():
                    # Return major.minor version
                    version_parts = part.split(".")
                    if len(version_parts) >= 2:
                        return f"{version_parts[0]}.{version_parts[1]}"
        return "1.10"
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        # If Julia is not available or detection fails, default to 1.10
        return "1.10"


def get_env_lock_dir(wdir: str | None = None) -> str:
    env_lock_dir = os.path.join(".calkit", "env-locks")
    if wdir is not None:
        env_lock_dir = os.path.join(wdir, env_lock_dir)
    return env_lock_dir


def _conda_venv_platform() -> str:
    sys = platform.system().lower()
    mach = platform.machine().lower()
    if sys == "darwin":
        return "osx-arm64" if mach in ("arm64", "aarch64") else "osx-64"
    if sys == "linux":
        if mach in ("arm64", "aarch64"):
            return "linux-aarch64"
        elif mach in ("ppc64le",):
            return "linux-ppc64le"
        else:
            return "linux-64"
    if sys == "windows":
        return "win-64"
    # Fallback for unusual platforms
    return f"{sys}-{mach}"


def get_docker_arch() -> str:
    """Get Docker platform string (arch part only)."""
    mach = platform.machine().lower()
    # Map common platform.machine() outputs to Docker arch names
    if mach in ("x86_64", "amd64"):
        return "amd64"
    elif mach in ("aarch64", "arm64"):
        return "arm64"
    elif mach in ("armv7l", "armv7"):
        return "arm-v7"
    elif mach in ("armv6l", "armv6"):
        return "arm-v6"
    elif mach == "ppc64le":
        return "ppc64le"
    elif mach == "s390x":
        return "s390x"
    elif mach in ("i386", "i686"):
        return "386"
    elif mach == "riscv64":
        return "riscv64"
    # Fallback
    return mach


def get_all_docker_lock_fpaths(
    env_name: str,
    wdir: str | None = None,
    as_posix: bool = True,
) -> list[str]:
    """Return docker environment lock file paths for every supported
    architecture.

    This intentionally excludes legacy (pre-arch) lock file locations;
    legacy handling is performed separately.
    """
    env_lock_dir = get_env_lock_dir(wdir=wdir)
    docker_dir = os.path.join(env_lock_dir, env_name)
    fpaths = [
        os.path.join(docker_dir, arch + ".json") for arch in DOCKER_ARCHS
    ]
    if as_posix:
        fpaths = [Path(p).as_posix() for p in fpaths]
    return fpaths


def get_all_conda_lock_fpaths(
    env_name: str,
    wdir: str | None = None,
    as_posix: bool = True,
) -> list[str]:
    """Return conda environment lock file paths for every supported
    architecture.
    """
    env_lock_dir = get_env_lock_dir(wdir=wdir)
    env_lock_dir = os.path.join(env_lock_dir, env_name)
    fpaths = [
        os.path.join(env_lock_dir, arch + ".yml") for arch in CONDA_VENV_ARCHS
    ]
    if as_posix:
        fpaths = [Path(p).as_posix() for p in fpaths]
    return fpaths


def get_all_venv_lock_fpaths(
    env_name: str,
    wdir: str | None = None,
    as_posix: bool = True,
) -> list[str]:
    """Return venv environment lock file paths for every supported
    architecture.
    """
    env_lock_dir = get_env_lock_dir(wdir=wdir)
    venv_dir = os.path.join(env_lock_dir, env_name)
    fpaths = [
        os.path.join(venv_dir, arch + ".txt") for arch in CONDA_VENV_ARCHS
    ]
    if as_posix:
        fpaths = [Path(p).as_posix() for p in fpaths]
    return fpaths


def _get_julia_manifest_fpath(
    env_dir: str, julia_version: str | None, wdir: str | None = None
) -> str:
    """Return the Manifest path for a Julia env, preferring versioned names.

    Julia 1.9+ writes ``Manifest-vMAJOR.MINOR.toml`` (e.g.
    ``Manifest-v1.11.toml``) alongside the default ``Manifest.toml``.
    We prefer the versioned file when it exists.
    """
    base_dir = env_dir or "."
    full_dir = os.path.join(wdir, base_dir) if wdir else base_dir
    if julia_version:
        parts = julia_version.split(".")
        if len(parts) >= 2:
            major_minor = f"{parts[0]}.{parts[1]}"
            versioned_name = f"Manifest-v{major_minor}.toml"
            if os.path.isfile(os.path.join(full_dir, versioned_name)):
                return os.path.join(base_dir, versioned_name)
    return os.path.join(base_dir, "Manifest.toml")


# The shell a system environment's setup commands run in. Setup is the only
# thing that uses it, and bash is the default because ``source`` is a
# bashism and sourcing a site setup script is the usual reason to have any.
SYSTEM_ENV_DEFAULT_SHELL = "bash"


def system_env_locks_anything(env: dict) -> bool:
    """Return whether a ``system`` environment has anything to lock.

    The machine properties under ``lock``, and a ``shell`` that isn't the
    default. Not ``default_setup``: the pipeline compiler merges that into
    the stage's command, so DVC already reruns the stage when it changes
    and a copy here would only add a second reason. The shell isn't in the
    command, so it stays.

    ``shell`` is compared by value rather than presence: writing
    ``shell: bash`` says exactly what leaving it out says, so it must not
    be what decides whether stages gain a dependency.
    """
    return bool(
        env.get("lock")
        or env.get("shell", SYSTEM_ENV_DEFAULT_SHELL)
        != SYSTEM_ENV_DEFAULT_SHELL
    )


def get_env_lock_fpath(
    env: dict,
    env_name: str,
    wdir: str | None = None,
    as_posix: bool = True,
    legacy: bool = False,
    for_dvc: bool = False,
) -> str | None:
    """Create the environment lock file path.

    If `for_dvc` is True, return the directory containing the lock file
    instead of the lock file itself for Docker, venv, and conda environments,
    which store a separate lock file for each platform/architecture.
    """
    env_lock_dir = get_env_lock_dir(wdir=wdir)
    env_kind = env.get("kind")
    lock_fpath = os.path.join(env_lock_dir, env_name)
    if env_kind == "docker":
        if legacy:
            lock_fpath += ".json"
        else:
            lock_fpath = os.path.join(
                env_lock_dir, env_name, get_docker_arch() + ".json"
            )
            if for_dvc:
                lock_fpath = os.path.dirname(lock_fpath)
    elif env_kind == "uv":
        env_dir = os.path.dirname(env.get("path", ""))
        if env_dir:
            lock_fpath = os.path.join(env_dir, "uv.lock")
        else:
            lock_fpath = "uv.lock"
    elif env_kind == "pixi":
        env_dir = os.path.dirname(env.get("path") or "")
        if env_dir:
            lock_fpath = os.path.join(env_dir, "pixi.lock")
        else:
            lock_fpath = "pixi.lock"
    elif env_kind in ["venv", "uv-venv"]:
        if legacy:
            lock_fpath += ".txt"
        else:
            lock_fpath = os.path.join(
                env_lock_dir,
                env_name,
                _conda_venv_platform() + ".txt",
            )
            if for_dvc:
                lock_fpath = os.path.dirname(lock_fpath)
    elif env_kind == "conda":
        if legacy:
            lock_fpath += ".yml"
        else:
            lock_fpath = os.path.join(
                env_lock_dir,
                env_name,
                _conda_venv_platform() + ".yml",
            )
            if for_dvc:
                lock_fpath = os.path.dirname(lock_fpath)
    elif env_kind == "matlab":
        lock_fpath += ".json"
    elif env_kind == "julia":
        env_path = env.get("path")
        if env_path is None:
            raise ValueError(
                "Julia environments require a path pointing to Project.toml"
            )
        env_fname = os.path.basename(env_path)
        if not env_fname == "Project.toml":
            raise ValueError(
                "Julia environments require a path pointing to Project.toml"
            )
        env_dir = os.path.dirname(env_path)
        lock_fpath = _get_julia_manifest_fpath(
            env_dir, env.get("julia"), wdir=wdir
        )
    elif env_kind == "renv":
        env_path = env.get("path")
        if env_path is None:
            raise ValueError(
                "renv environments require a path pointing to DESCRIPTION"
            )
        env_fname = os.path.basename(env_path)
        if not env_fname == "DESCRIPTION":
            raise ValueError(
                "renv environments require a path pointing to DESCRIPTION"
            )
        # Replace DESCRIPTION with renv.lock
        env_dir = os.path.dirname(env_path)
        lock_fpath = os.path.join(env_dir, "renv.lock")
    elif env_kind == "nix":
        env_path = env.get("path")
        if env_path is None:
            raise ValueError(
                "Nix environments require a path pointing to flake.nix"
            )
        env_fname = os.path.basename(env_path)
        if env_fname != "flake.nix":
            raise ValueError(
                "Nix environments require a path pointing to flake.nix"
            )
        # flake.lock is generated by ``nix flake lock`` next to flake.nix.
        env_dir = os.path.dirname(env_path)
        lock_fpath = os.path.join(env_dir, "flake.lock")
    elif env_kind == "system":
        # A system env's lock file records the machine properties it
        # declared it depends on, plus a ``shell`` that isn't the default.
        # Not ``default_setup``: that is compiled into each stage's
        # command. With neither there is nothing to depend on, so no lock
        # file and no DVC dep.
        if not system_env_locks_anything(env):
            return None
        # Written by ``write_system_env_lock`` during environment checks, and
        # referenced as a DVC dep by stage compilation. Note this is the file
        # itself even when ``for_dvc``: there's exactly one of them, so
        # there's no reason to make a stage depend on the whole directory.
        lock_fpath = os.path.join(env_lock_dir, env_name, "info.json")
    elif env_kind in ("slurm", "pbs"):
        # Job-scheduler envs have no external dependency manifest, so the
        # "lock" is just a JSON dump of the env config. The file is
        # written by ``write_scheduler_env_lock`` during environment
        # checks (e.g., ``calkit check env``) and stage compilation
        # references it as a DVC dep so changes invalidate cached runs.
        lock_fpath = os.path.join(env_lock_dir, env_name, "info.json")
        if for_dvc:
            lock_fpath = os.path.dirname(lock_fpath)
    else:
        return
    if as_posix:
        lock_fpath = Path(lock_fpath).as_posix()
    return lock_fpath


def write_scheduler_env_lock(
    env_name: str,
    env: dict,
    wdir: str | None = None,
) -> str | None:
    """Write a JSON lock file for a SLURM or PBS environment.

    The lock file simply contains a deterministic JSON dump of the env
    config so DVC can use it as a stage dependency: when the env's
    ``default_options``, ``default_setup``, ``host``, etc. change, the
    lock file changes and any stage that depends on it is invalidated.
    Keys in ``SCHEDULER_DISPATCH_ONLY_KEYS`` are left out, since they change
    only when a job is submitted, not what it computes.

    Parameters
    ----------
    env_name : str
        Environment name as it appears in ``calkit.yaml``.
    env : dict
        Environment configuration dict.
    wdir : str | None
        Working directory; defaults to the current process cwd.

    Returns
    -------
    str | None
        The lock file path, already prefixed with ``wdir`` if provided, or
        ``None`` if the env kind has no scheduler lock file.
    """
    if env.get("kind") not in ("slurm", "pbs"):
        return None
    # Already prefixed with wdir, so it must not be joined with it again
    lock_fpath = get_env_lock_fpath(
        env=env, env_name=env_name, wdir=wdir, as_posix=True
    )
    if lock_fpath is None:
        return None
    parent = os.path.dirname(lock_fpath)
    if parent:
        os.makedirs(parent, exist_ok=True)
    lock_data = {
        k: v for k, v in env.items() if k not in SCHEDULER_DISPATCH_ONLY_KEYS
    }
    # Record when the scheduler is mocked so switching between a mocked run
    # (executed locally) and a real scheduler run changes the lock file and
    # invalidates the cached result
    from calkit.cli.scheduler import _mock_enabled

    if _mock_enabled():
        lock_data["mocked"] = True
    content = json.dumps(lock_data, indent=2, sort_keys=True) + "\n"
    if os.path.isfile(lock_fpath):
        with open(lock_fpath, "r") as f:
            existing = f.read()
        if existing == content:
            return lock_fpath
    # newline="\n" so the file is byte-identical on every platform.
    # Unlike a system env's lock, this one is a dump of the env config
    # rather than of the machine, so its content is the same
    # everywhere -- and it is written wherever the check runs, not
    # where the scheduler lives, so text mode would let a Windows
    # collaborator flip it to CRLF and back for everyone else.
    with open(lock_fpath, "w", newline="\n") as f:
        f.write(content)
    return lock_fpath


def merge_setup_commands(
    env_setup: list[str] | None,
    stage_setup: list[str] | None,
    mode: str = "replace",
) -> list[str]:
    """Combine an environment's default setup commands with a stage's.

    ``replace`` (the default) uses the environment's only when the stage
    names none of its own; ``merge`` runs the environment's first, then the
    stage's; ``ignore`` never runs the environment's.

    The one implementation of the rule. A system env's stages have this
    resolved when the pipeline is compiled, so the merged list ends up in
    the stage's command; a scheduler env's is resolved by ``calkit
    scheduler batch`` when the job script is written, which is the last
    moment before that kind of stage runs.
    """
    stage_cmds = [c for c in (stage_setup or []) if c.strip()]
    env_cmds = [c for c in (env_setup or []) if c.strip()]
    if mode == "merge":
        return env_cmds + stage_cmds
    if mode == "replace" and not stage_cmds:
        return env_cmds
    return stage_cmds


# Warned once per process, not once per reader: compiling a pipeline reads
# an environment's inputs several times -- the DVC dep list, the
# environment check, the run itself -- and a project is only asked to
# rename the key once.
_warned_deprecated_deps_key = False


def get_env_input_paths(env: dict, env_name: str | None = None) -> list[str]:
    """Read the files an environment declares it depends on.

    Written as ``inputs``, and also accepted as ``deps``, which is the name
    this was published under on Docker environments. Extra keys on an
    environment are ignored rather than refused, so a project still
    spelling it the old way would otherwise have its files go silently
    untracked---which is the one failure the field exists to prevent.
    ``inputs`` wins if somehow both are written.

    This is the only reader of either spelling, so the alias lives in one
    place: the models accept it through ``AliasChoices``, and everything
    reading a raw environment dict comes through here.
    """
    global _warned_deprecated_deps_key
    inputs = env.get("inputs")
    deps = env.get("deps")
    if inputs is not None and deps is not None:
        where = f" on environment '{env_name}'" if env_name else ""
        raise ValueError(
            f"Both 'inputs' and 'deps' are set{where}; 'deps' is the old "
            "name for the same key, so merge them into 'inputs'"
        )
    if deps is not None and not _warned_deprecated_deps_key:
        from calkit.cli import warn

        _warned_deprecated_deps_key = True
        # Written for whoever has to act on it rather than raised as a
        # UserWarning, whose file-and-line formatting reads as a defect in
        # Calkit instead of a line to change in their own project
        where = f" on environment '{env_name}'" if env_name else ""
        warn(
            f"The 'deps' key{where} is deprecated; rename it to 'inputs', "
            "which is what it's called now that scheduler and system "
            "environments take one too"
        )
    paths = list(inputs if inputs is not None else deps or [])
    # Checked here rather than only on the models: every production caller
    # reads a raw environment dict, so a model annotation alone would let
    # '../outside.sh' through to DVC. Docker's list is exempt because it
    # is the long-published 'deps' under a new name, and tightening it
    # would retroactively invalidate existing projects.
    if env.get("kind") in ("system", "slurm", "pbs"):
        from calkit.provenance import check_project_path

        for path in paths:
            problem = check_project_path(path)
            if problem:
                where = f" on environment '{env_name}'" if env_name else ""
                raise ValueError(f"Environment input{where}: {problem}")
    return paths


def get_system_lock_data(
    lock: list[str], system_info: dict | None = None
) -> dict:
    """Read the machine properties a ``system`` environment locks.

    Raises if a locked property isn't available on the machine, e.g., a
    tool that isn't installed. Recording it as null would quietly claim the
    stage is pinned to something it isn't, which is worse than not pinning
    it at all.

    ``system_info`` describes a machine other than this one, for an
    environment whose host is somewhere else: what the results depend on is
    the machine the stage runs on, so that is what gets pinned.
    """
    if system_info is None:
        system_info = calkit.get_system_info()
    data = {}
    for prop in lock:
        key = SYSTEM_LOCK_PROPERTIES.get(prop)
        if key is None:
            raise ValueError(
                f"Unknown system property to lock: '{prop}'; valid options "
                f"are {', '.join(sorted(SYSTEM_LOCK_PROPERTIES))}"
            )
        value = system_info.get(key)
        if value is None:
            hint = ""
            if prop == "machine-id":
                # The one lockable property that can be supplied by hand,
                # and the one most likely to be locked implicitly -- so the
                # way out is worth naming rather than leaving to the docs
                hint = (
                    "; no identifier could be read from the platform, so "
                    "give it one with 'calkit config set machine_id <id>'"
                )
            raise ValueError(
                f"System property '{prop}' is not available on this machine"
                + hint
            )
        data[prop] = SYSTEM_LOCK_PROPERTY_PRECISION.get(prop, lambda v: v)(
            value
        )
    return data


def write_system_env_lock(
    env_name: str,
    env: dict,
    wdir: str | None = None,
    system_info: dict | None = None,
) -> str | None:
    """Write a JSON lock file for a ``system`` environment.

    Unlike the other lock files, this one describes the machine rather than
    a spec the project controls, so it changes when the project moves to a
    different machine. That is the intent: a stage that declared it depends
    on, say, the Julia version should not reuse a cached result from a box
    with a different one.

    A non-default ``shell`` is recorded alongside the machine properties.
    It isn't a property of the machine, but it feeds the same question: a
    stage whose setup commands ran under a different shell should not
    reuse the old result. The setup commands themselves aren't here --
    they are compiled into the stage's command, where DVC already watches
    them.

    Returns the lock file path, already prefixed with ``wdir`` if provided,
    or None if the environment locks nothing.
    """
    # Already prefixed with wdir, so it must not be joined with it again
    lock_fpath = get_env_lock_fpath(
        env=env, env_name=env_name, wdir=wdir, as_posix=True
    )
    if lock_fpath is None:
        return None
    # Read before anything is created: a misspelled property or a tool
    # that isn't installed raises here, and an env that failed to lock
    # shouldn't leave a directory behind suggesting it did
    lock_data = get_system_lock_data(
        env.get("lock") or [], system_info=system_info
    )
    # Named so it can't collide with a locked property, now or when the set
    # of them grows. The setup commands themselves are not recorded: they
    # go into the stage's command when the pipeline is compiled, so DVC
    # sees them change. The shell they run in doesn't, so it does -- and
    # only when it isn't the default, since writing the default says
    # nothing that leaving it out doesn't.
    shell = env.get("shell", SYSTEM_ENV_DEFAULT_SHELL)
    if shell != SYSTEM_ENV_DEFAULT_SHELL:
        lock_data["shell"] = shell
    content = json.dumps(lock_data, indent=2, sort_keys=True) + "\n"
    parent = os.path.dirname(lock_fpath)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.isfile(lock_fpath):
        with open(lock_fpath, "r") as f:
            if f.read() == content:
                return lock_fpath
    with open(lock_fpath, "w") as f:
        f.write(content)
    return lock_fpath


def get_cache_db(name="cache") -> SqliteDict:
    env_check_cache_dir = os.path.join(
        os.path.expanduser("~"), ".calkit", "env-checks"
    )
    os.makedirs(env_check_cache_dir, exist_ok=True)
    env_check_cache_path = os.path.join(env_check_cache_dir, f"{name}.sqlite")
    return SqliteDict(env_check_cache_path)


def make_cache_key(env_name: str, wdir: str | None = None) -> str:
    if wdir is None:
        wdir = os.getcwd()
    else:
        wdir = os.path.abspath(wdir)
    return f"{wdir}::{env_name}"


def hash_dict(d: dict) -> str:
    json_str = json.dumps(d, sort_keys=True)
    return hashlib.sha256(json_str.encode()).hexdigest()


def calc_data_for_env(
    env_name: str, env: dict, wdir: str | None = None
) -> dict:
    """Hash important data from the environment.

    This includes:
    1. A hash of the env definition.
    2. A hash of the env path file, if present.
    3. A hash of the env prefix, if applicable.
    4. A hash of the env lock file, if applicable.
    """

    def get_cached_md5(path: str) -> str | None:
        """Get a cached MD5 hash for a path.

        For files, use mtime as a fast invalidation check. For directories,
        use a lightweight directory signature, since directory mtimes can be
        unreliable across filesystems and operations.
        """
        key = os.path.abspath(path)
        cached_data = {}
        with get_cache_db(name="md5s") as db:
            if key in db:
                cached_data = db[key]
        if not os.path.exists(path):
            return None
        if os.path.isdir(path):
            # Avoid deep recursive walks on every cache check. A shallow
            # signature is enough to decide whether to recompute full MD5.
            shallow_sig = _calc_dir_sig_shallow(path, max_depth=2)
            if shallow_sig == cached_data.get("shallow_sig"):
                return cached_data.get("md5")
            md5 = calkit.get_md5(path)
            with get_cache_db(name="md5s") as db:
                db[key] = {"md5": md5, "shallow_sig": shallow_sig}
                db.commit()
            return md5
        mtime = os.path.getmtime(path)
        if mtime == cached_data.get("mtime"):
            return cached_data.get("md5")
        if os.path.exists(path):
            md5 = calkit.get_md5(path)
            with get_cache_db(name="md5s") as db:
                db[key] = {"md5": md5, "mtime": mtime}
                db.commit()
            return md5

    if wdir is None:
        wdir = os.getcwd()
    else:
        wdir = os.path.abspath(wdir)
    env_hash = hash_dict(env)
    env_path = env.get("path", "")
    env_path_hash = None
    if env_path:
        env_path_full = os.path.join(wdir, env_path)
        if os.path.isfile(env_path_full):
            env_path_hash = calkit.get_md5(env_path_full)
    env_prefix = env.get("prefix", "")
    env_prefix_hash = None
    if env_prefix:
        env_prefix_full = os.path.join(wdir, env_prefix)
        if os.path.exists(env_prefix_full):
            env_prefix_hash = get_cached_md5(env_prefix_full)
        else:
            env_prefix_hash = None
    julia_packages_sig = None
    if env.get("kind") == "julia":
        julia_packages_sig = calc_julia_depot_sig()
    env_lock_hash = None
    env_lock_fpath = get_env_lock_fpath(env_name=env_name, env=env, wdir=wdir)
    if env_lock_fpath is not None:
        env_lock_full = os.path.join(wdir, env_lock_fpath)
        if os.path.isfile(env_lock_full):
            env_lock_hash = calkit.get_md5(env_lock_full)
    return {
        "hashes": {
            "env_hash": env_hash,
            "env_path_hash": env_path_hash,
            "env_prefix_hash": env_prefix_hash,
            "julia_packages_sig": julia_packages_sig,
            "env_lock_hash": env_lock_hash,
        },
        "checked_at": calkit.utcnow(),
    }


def check_cache(
    env_name: str,
    env: dict,
    wdir: str | None = None,
    respect_ttl: bool = True,
) -> bool:
    """Check if the environment is up-to-date based on cached data."""
    if wdir is None:
        wdir = os.getcwd()
    else:
        wdir = os.path.abspath(wdir)
    with get_cache_db() as db:
        key = make_cache_key(env_name=env_name, wdir=wdir)
        if key not in db:
            return False
        cached_data = db[key]
    # If our last check failed, we're definitely not up-to-date
    if not cached_data.get("success", False):
        return False
    if respect_ttl:
        cached_checked_at = cached_data.get("checked_at")
        if cached_checked_at is None:
            return False
        time_diff = calkit.utcnow() - cached_checked_at
        if time_diff.total_seconds() > ENV_CHECK_CACHE_TTL_SECONDS:
            return False
    # A Docker environment's image can be deleted without anything the cache
    # hashes changing, and the pipeline can't run in an image that isn't
    # there, so its absence has to invalidate the check
    if env.get("kind") == "docker":
        from calkit.docker import get_image_name, image_exists

        image = get_image_name(env, env_name, wdir=wdir)
        if image and not image_exists(image):
            return False
    # Check if this environment is up-to-date
    current_data = calc_data_for_env(env_name=env_name, env=env, wdir=wdir)
    if env.get("path") and not current_data["hashes"]["env_path_hash"]:
        return False
    if env.get("prefix") and not current_data["hashes"]["env_prefix_hash"]:
        return False
    if (
        get_env_lock_fpath(env=env, env_name=env_name, wdir=wdir)
        and not current_data["hashes"]["env_lock_hash"]
    ):
        return False
    return current_data["hashes"] == cached_data["hashes"]


def save_cache(
    env_name: str, env: dict, wdir: str | None = None, success: bool = True
) -> dict:
    with get_cache_db() as db:
        key = make_cache_key(env_name=env_name, wdir=wdir)
        data = calc_data_for_env(env_name=env_name, env=env, wdir=wdir)
        data["success"] = success
        db[key] = data
        db.commit()
    return data


def check_all_in_pipeline(
    ck_info: dict | None = None,
    wdir: str | None = None,
    targets: list[str] | None = None,
    force: bool = False,
) -> dict:
    """Check all environments in the pipeline, caching for efficiency.

    The cache file is a simple JSON file keyed by project path.
    Each object inside tracks the last check timestamp, pass/fail,
    and some sort of hash(es) for the important file content involved.
    """
    import calkit
    from calkit.cli.check import check_environment

    # TODO: ``check_environment`` should be able to take a wdir argument
    if wdir is not None:
        raise ValueError(
            "Can currently only run from current working directory"
        )
    res = {}
    # First get a list of environments used in the pipeline
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    # Markdown stages carry no environment of their own; the stages their
    # blocks declare do, so expand before looking for environments to check.
    import calkit.markdown

    md_stages = calkit.markdown.get_markdown_stages(ck_info)
    ck_info = calkit.markdown.expand_ck_info(ck_info).ck_info
    stages = ck_info.get("pipeline", {}).get("stages", {})
    if targets:
        # Split targets by "@" to handle sub-stages from iterations
        targets = [t.split("@")[0] for t in targets]
        # A target naming a markdown stage covers every stage its file
        # declares, which are named '<stage>/<block>'
        prefixes = [
            t + calkit.markdown.STAGE_NAME_SEPARATOR
            for t in targets
            if t in md_stages
        ]
        stages = {
            k: v
            for k, v in stages.items()
            if k in targets or any(k.startswith(p) for p in prefixes)
        }
    envs_in_pipeline = [stage.get("environment") for stage in stages.values()]
    envs_in_pipeline = [
        e for e in envs_in_pipeline if e and not (str(e)).startswith("_")
    ]
    # If any environments are composite environments, we need to split them
    # up into their individual names in the list
    split_envs = []
    for env_name in envs_in_pipeline:
        if env_name.count(COMPOSITE_ENV_SEP) == 1:
            outer_env_name, sub_env_name = env_name.split(COMPOSITE_ENV_SEP)
            split_envs += [outer_env_name, sub_env_name]
        else:
            split_envs.append(env_name)
    envs_in_pipeline = list(set(split_envs))
    envs = ck_info.get("environments", {})
    for env_name in envs_in_pipeline:
        env = envs.get(env_name)
        if env.get("kind") in KINDS_NO_CHECK:
            continue
        if not force:
            up_to_date = cacheable(env) and check_cache(
                env_name=env_name, env=env, wdir=wdir
            )
            if up_to_date:
                res[env_name] = {"success": True, "cached": True}
                continue
        try:
            check_environment(env_name, verbose=False)
            res[env_name] = save_cache(
                env_name=env_name, env=env, wdir=wdir, success=True
            )
        except Exception:
            res[env_name] = save_cache(
                env_name=env_name, env=env, wdir=wdir, success=False
            )
    return res


class EnvDetectResult(BaseModel):
    name: str
    env: dict
    exists: bool
    outer: "EnvDetectResult | None" = None


class EnvForStageResult(BaseModel):
    """Result of detecting or creating an environment for a stage."""

    name: str
    env: dict
    exists: bool
    spec_path: str | None = None
    spec_content: str | None = None
    dependencies: list[str] = []
    created_from_dependencies: bool = False


def make_env_name(path: str, all_env_names: list[str], kind: str) -> str:
    """Generate a unique environment name based on path, existing
    names, and kind.

    Parameters
    ----------
    path : str
        Path to the environment spec file.
    all_env_names : list[str]
        List of existing environment names.
    kind : str
        Environment kind (e.g., "uv-venv", "conda", "renv", "julia").

    Returns
    -------
    str
        A unique environment name.
    """
    dirname = Path(path).parent.name
    # If this is the first env in the project, call it main
    if not all_env_names:
        return dirname or "main"
    # Name based on dirname if possible
    if dirname and dirname not in all_env_names:
        return dirname
    # Try a name based on the dirname and kind
    if dirname and dirname in all_env_names:
        name = f"{dirname}-{kind}"
        if name not in all_env_names:
            return name
    # Otherwise increment a number after the kind
    n = 1
    name = f"{kind}{n}"
    while name in all_env_names:
        n += 1
        name = f"{kind}{n}"
    return name


def get_default_venv_prefix(envs: dict, path: str, name: str) -> str:
    """Return the default prefix for a venv or uv-venv environment.

    The prefix defaults to ``.venv`` in the same directory as ``path``,
    unless that location is already claimed by another environment, in which
    case the virtualenv is nested under ``.calkit/envs/{name}/.venv``. This
    is resolved on the fly so that the prefix need not be stored in
    ``calkit.yaml``.

    A location is considered claimed by another environment if it pins that
    explicit ``prefix``, or if it is a ``uv``, ``venv``, or ``uv-venv``
    environment whose ``.venv`` would live there (``uv`` always creates its
    virtualenv at ``.venv`` in its project directory, so a flexible venv
    yields to it). Sibling venvs that would otherwise collide all nest under
    their own name-scoped location, which is collision-free.

    Parameters
    ----------
    envs : dict
        All environments, keyed by name.
    path : str
        Path to the spec file the environment lives alongside.
    name : str
        Name of the environment being resolved, used both to exclude it from
        the claimed locations and for the nested fallback.

    Returns
    -------
    str
        A POSIX-style prefix that does not collide with another environment.
    """
    base = os.path.join(os.path.dirname(path), ".venv")
    # Collect .venv locations claimed by the other environments
    claimed = set()
    for other_name, env in envs.items():
        if other_name == name:
            continue
        prefix = env.get("prefix")
        if prefix is not None:
            claimed.add(os.path.normpath(prefix))
        elif env.get("kind") in ("uv", "venv", "uv-venv"):
            other_dir = os.path.dirname(env.get("path", ""))
            claimed.add(os.path.normpath(os.path.join(other_dir, ".venv")))
    # Nest under .calkit/envs/{name} if the default location is taken
    if os.path.normpath(base) in claimed:
        base = os.path.join(".calkit", "envs", name, ".venv")
    return Path(base).as_posix()


def env_from_name_or_path(
    name_or_path: str | None = None,
    ck_info: dict | None = None,
    path_only: bool = False,
    language: str | None = None,
) -> EnvDetectResult:
    """Get an environment from its name or path.

    Names take precedence.

    Parameters
    ----------
    name_or_path : str | None
        Name or path of the environment. If None and language is provided,
        will search for or create a docker environment for that language.
    ck_info : dict | None
        Calkit info dict. If None, will be loaded from calkit.yaml.
    path_only : bool
        Only match on path, not name.
    language : str | None
        Language/tool to detect docker environment for (e.g., "latex").
        Only used if name_or_path is None.

    Returns
    -------
    EnvDetectResult
        Environment detection result.
    """
    # Load config and environment list
    if ck_info is None:
        ck_info = calkit.load_calkit_info()
    envs = ck_info.get("environments", {})
    all_env_names = list(envs.keys())
    # Handle language-based environment detection
    # This will usually use a spec path, not a name in ck_info
    if name_or_path is None and language is not None:
        # Look for a docker environment matching the language
        for env_name, env in envs.items():
            if env.get("kind") == "docker":
                image = env.get("image", "").lower()
                # Check if this looks like a language environment
                if language.lower() in image or f"{language}mk" in image:
                    return EnvDetectResult(name=env_name, env=env, exists=True)
        # Only create default docker environment for latex
        if language.lower() == "latex":
            env_name = "latex"
            return EnvDetectResult(
                name=env_name,
                env={
                    "kind": "docker",
                    "image": "texlive/texlive:latest-full",
                },
                exists=False,
            )
        # For shell language, use _system environment
        if language.lower() == "shell":
            return EnvDetectResult(
                name="_system",
                env={"kind": "system"},
                exists=True,
            )
        # For other languages, try to detect a default environment
        default_env = detect_default_env(ck_info=ck_info, language=language)
        if default_env:
            return default_env
        raise ValueError(
            f"Could not find or create environment for language: {language}"
        )
    # Require either name_or_path or language
    if name_or_path is None:
        raise ValueError("Either name_or_path or language must be provided")
    # Check if environment exists by name or path
    for env_name, env in envs.items():
        if (not path_only and env_name == name_or_path) or env.get(
            "path"
        ) == name_or_path:
            return EnvDetectResult(name=env_name, env=env, exists=True)
    # Check for nested environments like mycluster:mypython
    if name_or_path.count(COMPOSITE_ENV_SEP) == 1 and not path_only:
        outer_env_name, sub_env_name = name_or_path.split(COMPOSITE_ENV_SEP)
        outer_env = envs.get(outer_env_name)
        if outer_env and outer_env.get("kind") in VALID_OUTER_ENV_KINDS:
            # Look for an inner environment with the given name and path
            for sub_name, sub_env in envs.items():
                if (not path_only and sub_name == sub_env_name) or sub_env.get(
                    "path"
                ) == sub_env_name:
                    return EnvDetectResult(
                        name=sub_name,
                        env=sub_env,
                        exists=True,
                        outer=EnvDetectResult(
                            name=outer_env_name, env=outer_env, exists=True
                        ),
                    )
    # Handle special _system environment
    if name_or_path == "_system":
        return EnvDetectResult(
            name="_system",
            env={"kind": "system"},
            exists=True,
        )
    # Check if name_or_path is a file and detect environment type
    env_path = _as_posix_path(name_or_path)
    if os.path.isfile(env_path):
        if env_path.endswith("requirements.txt"):
            # TODO: Detect if uv is installed, and use a plain venv if not
            # The prefix is left unset and resolved on the fly at check/run
            # time via get_default_venv_prefix
            return EnvDetectResult(
                name=make_env_name(env_path, all_env_names, kind="uv-venv"),
                env={
                    "kind": "uv-venv",
                    "path": env_path,
                    "python": DEFAULT_PYTHON_VERSION,
                },
                exists=False,
            )
        elif env_path.endswith(".yml") or env_path.endswith(".yaml"):
            # This is probably a Conda env
            with open(env_path) as f:
                env_spec = calkit.ryaml.load(f)
            if "dependencies" not in env_spec:
                raise ValueError(
                    f"Could not detect environment from: {name_or_path}"
                )
            return EnvDetectResult(
                name=env_spec.get(
                    "name",
                    make_env_name(env_path, all_env_names, kind="conda"),
                ),
                env={"kind": "conda", "path": env_path},
                exists=False,
            )
        elif env_path.endswith("pyproject.toml"):
            # This is a uv project env
            return EnvDetectResult(
                name=make_env_name(env_path, all_env_names, kind="uv"),
                env={
                    "kind": "uv",
                    "path": env_path,
                },
                exists=False,
            )
        elif env_path.endswith("pixi.toml"):
            # This is a pixi env
            return EnvDetectResult(
                name=make_env_name(env_path, all_env_names, kind="pixi"),
                env={
                    "kind": "pixi",
                    "path": env_path,
                },
                exists=False,
            )
        elif env_path.endswith("Project.toml"):
            # This is a Julia env
            return EnvDetectResult(
                name=make_env_name(env_path, all_env_names, kind="julia"),
                env={
                    "kind": "julia",
                    "path": env_path,
                    "julia": _get_julia_version(),
                },
                exists=False,
            )
        elif env_path.endswith("DESCRIPTION"):
            # This is an R renv environment
            return EnvDetectResult(
                name=make_env_name(env_path, all_env_names, kind="renv"),
                env={"kind": "renv", "path": env_path},
                exists=False,
            )
        elif env_path.endswith("flake.nix"):
            # This is a Nix flake environment
            return EnvDetectResult(
                name=make_env_name(env_path, all_env_names, kind="nix"),
                env={"kind": "nix", "path": env_path},
                exists=False,
            )
        elif "dockerfile" in env_path.lower():
            # This is a Docker env
            project_name = calkit.detect_project_name(prepend_owner=False)
            env_name = make_env_name(env_path, all_env_names, kind="docker")
            image_name = f"{project_name}-{env_name}"
            return EnvDetectResult(
                name=env_name,
                env={
                    "kind": "docker",
                    "path": env_path,
                    "image": image_name,
                },
                exists=False,
            )
    raise ValueError(f"Environment could not be detected from: {name_or_path}")


def env_from_name_and_or_path(
    name: str | None, path: str | None, ck_info: dict | None = None
) -> EnvDetectResult:
    """Detect an environment from its name and/or path."""
    if ck_info is None:
        ck_info = calkit.load_calkit_info()
    envs = ck_info.get("environments", {})
    path = _as_posix_path(path) if path else None
    if name and name in envs:
        env = envs[name]
        if path and _as_posix_path(env.get("path", "")) != path:
            raise ValueError(
                f"Environment '{name}' exists but has a different path "
                f"('{env.get('path')}') than provided ('{path}')"
            )
        return EnvDetectResult(name=name, env=envs[name], exists=True)
    # Detect composite environments
    if name and name.count(COMPOSITE_ENV_SEP) == 1:
        outer_env_name, sub_env_name = name.split(COMPOSITE_ENV_SEP)
        outer_env = envs.get(outer_env_name)
        if outer_env and outer_env.get("kind") in VALID_OUTER_ENV_KINDS:
            # Look for a sub-environment with the given name and path
            for sub_name, sub_env in envs.items():
                if (sub_name == sub_env_name) or (
                    path and _as_posix_path(sub_env.get("path", "")) == path
                ):
                    return EnvDetectResult(
                        name=sub_name,
                        env=sub_env,
                        exists=True,
                        outer=EnvDetectResult(
                            name=outer_env_name, env=outer_env, exists=True
                        ),
                    )
    if path:
        res = env_from_name_or_path(
            name_or_path=path, ck_info=ck_info, path_only=True
        )
        if name:
            res.name = name
        return res
    # If we have neither name nor path, we can only detect the environment
    # if there's only one
    default = detect_default_env(ck_info=ck_info)
    if default:
        return default
    raise ValueError(
        f"Environment could not be detected from name: {name} "
        f"and/or path: {path}"
    )


def env_from_notebook_path(
    notebook_path: str, ck_info: dict | None = None
) -> EnvDetectResult:
    """Detect an environment for a notebook based on its path.

    First we look in pipeline stages, then in the notebooks list.
    """
    if ck_info is None:
        ck_info = calkit.load_calkit_info()
    notebook_path = _as_posix_path(notebook_path)
    stages = ck_info.get("pipeline", {}).get("stages", {})
    envs = ck_info.get("environments", {})
    for stage in stages.values():
        if (
            stage.get("kind") == "jupyter-notebook"
            and _as_posix_path(stage.get("notebook_path", "")) == notebook_path
        ):
            env_name = stage.get("environment")
            if env_name:
                env = envs.get(env_name)
                if env:
                    return EnvDetectResult(name=env_name, env=env, exists=True)
    for nb in ck_info.get("notebooks", []):
        if _as_posix_path(nb.get("path", "")) == notebook_path:
            env_name = nb.get("environment")
            if env_name:
                env = envs.get(env_name)
                if env:
                    return EnvDetectResult(name=env_name, env=env, exists=True)
    # Fall back to default env if possible
    default = detect_default_env(ck_info=ck_info)
    if default:
        return default
    raise ValueError(
        f"Environment could not be detected for notebook path: {notebook_path}"
    )


def detect_default_env(
    ck_info: dict | None = None, language: str | None = None
) -> EnvDetectResult | None:
    """Detect a default environment for the project.

    First, if the project has a single environment, we use that. Otherwise,
    we look for a single typical env spec file.

    Parameters
    ----------
    ck_info : dict | None
        Calkit info dict. If None, will be loaded from calkit.yaml.
    language : str | None
        Language to filter environments by when multiple environments exist.
    """
    if ck_info is None:
        ck_info = calkit.load_calkit_info()
    envs = ck_info.get("environments", {})
    if len(envs) == 1:
        env_name, env = next(iter(envs.items()))
        return EnvDetectResult(name=env_name, env=env, exists=True)
    elif len(envs) > 1:
        return
    # Look for typical env spec files in order
    # There must only be one, however, otherwise the default is ambiguous
    # Filter by language if provided
    if language:
        language_lower = language.lower()
        if language_lower == "python":
            env_spec_paths = [
                "pyproject.toml",
                "requirements.txt",
                "environment.yml",
                "pixi.toml",
            ]
        elif language_lower == "julia":
            env_spec_paths = ["Project.toml"]
        elif language_lower == "r":
            env_spec_paths = ["DESCRIPTION", "environment.yml", "pixi.toml"]
        elif language_lower == "shell":
            env_spec_paths = ["Dockerfile"]
        elif language_lower == "matlab":
            env_spec_paths = ["Dockerfile"]
        else:
            # For other languages, use generic list
            env_spec_paths = [
                "pyproject.toml",
                "requirements.txt",
                "environment.yml",
                "Dockerfile",
                "Project.toml",
                "renv.lock",
                "pixi.toml",
            ]
    else:
        # No language specified, use generic list
        env_spec_paths = [
            "pyproject.toml",
            "requirements.txt",
            "environment.yml",
            "Dockerfile",
            "Project.toml",
            "DESCRIPTION",
            "pixi.toml",
            "flake.nix",
        ]
    present = os.listdir(".")
    present_env_specs = [p for p in env_spec_paths if p in present]
    if len(present_env_specs) == 1:
        return env_from_name_or_path(
            present_env_specs[0], ck_info=ck_info, path_only=True
        )


def create_nix_flake_content(
    packages: list[str],
    description: str | None = None,
    nixpkgs_url: str = "github:NixOS/nixpkgs/nixos-unstable",
) -> str:
    """Generate a minimal flake.nix exposing a default dev shell.

    The flake builds a ``devShells.default`` containing the requested
    packages from nixpkgs, available on the common Linux + macOS systems.
    Reproducibility comes from ``flake.lock``, which pins the nixpkgs
    revision and is generated by ``nix flake lock`` after writing this
    file.
    """
    pkgs_block = "\n".join(f"            {p}" for p in packages)
    desc = description or "Calkit-managed Nix dev environment"
    desc_escaped = desc.replace('"', '\\"')
    return f"""{{
  description = "{desc_escaped}";

  inputs.nixpkgs.url = "{nixpkgs_url}";

  outputs = {{ self, nixpkgs }}:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f:
        nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${{system}});
    in {{
      devShells = forAllSystems (pkgs: {{
        default = pkgs.mkShell {{
          packages = with pkgs; [
{pkgs_block}
          ];
        }};
      }});
    }};
}}
"""


def add_packages_to_nix_flake(
    flake_path: str, packages: list[str]
) -> list[str]:
    """Add ``packages`` to a flake.nix's ``packages = with pkgs; [ ... ]``
    list, preserving formatting and skipping packages already present.

    Designed for flakes produced by ``calkit new nix-env``. If the anchor
    can't be found (e.g. the user hand-rolled a structurally different
    flake), raises ``ValueError`` so the caller can tell the user to edit
    manually rather than corrupting their file.

    Returns the list of packages actually inserted.
    """
    import re

    with open(flake_path) as f:
        lines = f.readlines()
    anchor_re = re.compile(r"packages\s*=\s*with\s+pkgs\s*;\s*\[")
    close_re = re.compile(r"^\s*\]\s*;")
    start = next(
        (i for i, line in enumerate(lines) if anchor_re.search(line)), None
    )
    if start is None:
        raise ValueError(
            f"Could not find 'packages = with pkgs; [' in {flake_path}; "
            "add packages manually."
        )
    end = next(
        (j for j in range(start + 1, len(lines)) if close_re.match(lines[j])),
        None,
    )
    if end is None:
        raise ValueError(
            f"Could not find closing ']' for packages list in {flake_path}."
        )
    # Collect existing entries (ignore blanks + comments) and pick up the
    # indent from the first real entry so inserted lines match.
    existing: set[str] = set()
    inner_indent: str | None = None
    for k in range(start + 1, end):
        stripped = lines[k].strip()
        if not stripped or stripped.startswith("#"):
            continue
        existing.add(stripped)
        if inner_indent is None:
            indent_match = re.match(r"^(\s*)", lines[k])
            inner_indent = indent_match.group(1) if indent_match else ""
    if inner_indent is None:
        # Empty list -- derive indent from the closing bracket + 2 spaces.
        close_indent_match = re.match(r"^(\s*)", lines[end])
        close_indent = (
            close_indent_match.group(1) if close_indent_match else ""
        )
        inner_indent = close_indent + "  "
    added: list[str] = []
    new_entries = []
    for pkg in packages:
        if pkg in existing:
            continue
        new_entries.append(f"{inner_indent}{pkg}\n")
        existing.add(pkg)
        added.append(pkg)
    if not new_entries:
        return added
    lines[end:end] = new_entries
    with open(flake_path, "w") as f:
        f.writelines(lines)
    return added


def create_python_requirements_content(dependencies: list[str]) -> str:
    """Generate requirements.txt file content from a list of dependencies.

    Parameters
    ----------
    dependencies : list[str]
        List of package names.

    Returns
    -------
    str
        The requirements.txt file content.
    """
    return "\n".join(dependencies) if dependencies else ""


def create_uv_pyproject_content(
    dependencies: list[str],
    project_name: str | None = None,
    python_version: str = DEFAULT_PYTHON_VERSION,
) -> str:
    """Generate a minimal pyproject.toml for a uv environment.

    Parameters
    ----------
    dependencies : list[str]
        List of package names.
    project_name : str | None
        Name of the project. If None, uses the detected project name.
    python_version : str
        Python version to include in requires-python.

    Returns
    -------
    str
        The pyproject.toml file content.
    """
    if project_name is None:
        project_name = calkit.detect_project_name(prepend_owner=False)
    content = "[project]\n"
    content += f'name = "{project_name}"\n'
    content += 'version = "0.1.0"\n'
    content += f'requires-python = ">={python_version}"\n'
    if dependencies:
        content += "dependencies = [\n"
        for dep in sorted(dependencies):
            content += f'  "{dep}",\n'
        content += "]\n"
    return content


def _resolve_julia_package_uuids(
    package_names: list[str],
) -> dict[str, str]:
    """Resolve Julia package names to their UUIDs using Pkg registry.

    Parameters
    ----------
    package_names : list[str]
        List of Julia package names to resolve.

    Returns
    -------
    dict[str, str]
        Dictionary mapping package names to their UUIDs.
        If a package UUID cannot be resolved, it is omitted.
    """
    if not package_names:
        return {}
    # Create Julia script to query Pkg registry for UUIDs
    # This safely handles packages that don't exist
    julia_code = """
using Pkg
using Pkg.Registry

packages = split(ARGS[1], ",")
registries = Pkg.Registry.reachable_registries()
if isempty(registries)
    Pkg.Registry.add("General")
    registries = Pkg.Registry.reachable_registries()
end

for pkg in packages
    for reg in registries
        found = false
        # Scan the registry's own package table rather than calling a
        # lookup helper; Pkg.Registry.find was removed in Julia 1.12, and
        # calling it failed for every package, silently.
        for (uuid, entry) in reg.pkgs
            if entry.name == pkg
                println(pkg * "=" * string(uuid))
                found = true
                break
            end
        end
        found && break
    end
end
"""
    try:
        # Write Julia script to temp file since passing long code via
        # command line can be problematic
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".jl",
            delete=False,
        ) as f:
            f.write(julia_code)
            script_path = f.name
        # Run Julia with the script
        result = subprocess.run(
            [
                calkit.julia.get_julia_exe(),
                script_path,
                ",".join(package_names),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # Clean up temp file
        try:
            os.unlink(script_path)
        except FileNotFoundError:
            pass
        if result.returncode != 0:
            # If Julia fails, return empty dict to fall back
            return {}
        # Parse output: each line is "package=uuid"
        uuids = {}
        for line in result.stdout.strip().split("\n"):
            if "=" in line:
                parts = line.strip().split("=", 1)
                if len(parts) == 2:
                    pkg, uuid = parts
                    uuids[pkg.strip()] = uuid.strip()
        return uuids
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        # If Julia is not available or times out, return empty dict
        return {}


def create_conda_environment_content(
    dependencies: list[str],
    project_name: str | None = None,
    python_version: str = DEFAULT_PYTHON_VERSION,
) -> str:
    """Generate a minimal environment.yml for a conda environment.

    Parameters
    ----------
    dependencies : list[str]
        List of package names.
    project_name : str | None
        Name of the environment. If None, uses the detected project name.
    python_version : str
        Python version to request.

    Returns
    -------
    str
        The environment.yml file content.
    """
    if project_name is None:
        project_name = calkit.detect_project_name(prepend_owner=False)
    content = f"name: {project_name}\n"
    content += "channels:\n  - conda-forge\n"
    content += "dependencies:\n"
    content += f"  - python={python_version}\n"
    for dep in sorted(dependencies):
        if dep.lower().startswith("python") and dep[6:7] in (
            "",
            "=",
            ">",
            "<",
        ):
            continue
        content += f"  - {dep}\n"
    return content


def create_julia_project_file_content(
    dependencies: list[str],
    project_name: str = "environment",
) -> str:
    """Generate Julia Project.toml file content from a list of dependencies.

    Parameters
    ----------
    dependencies : list[str]
        List of package names.
    project_name : str
        Name of the Julia project.

    Returns
    -------
    str
        The Project.toml file content with [deps] section populated
        with UUIDs if Julia is available. Otherwise, includes package
        names in comments.
    """
    content = f'name = "{project_name}"\n'
    version = "0.1.0"
    content += f'version = "{version}"\n\n'
    if not dependencies:
        return content
    # Try to resolve UUIDs using Julia's Pkg registry
    uuids = _resolve_julia_package_uuids(dependencies)
    if uuids:
        # We have UUIDs, create proper [deps] section
        content += "[deps]\n"
        for pkg in sorted(dependencies):
            if pkg in uuids:
                content += f'{pkg} = "{uuids[pkg]}"\n'
        return content
    else:
        # Fallback: Julia not available or registry lookup failed
        # Include package names in comments for manual addition
        content += "[deps]\n"
        content += "# Dependencies (add with Julia's Pkg.add):\n"
        content += "# " + ", ".join(sorted(dependencies)) + "\n"
        return content


def create_r_description_content(
    dependencies: list[str], project_name: str | None = None
) -> str:
    """Generate R DESCRIPTION file content listing dependencies.

    This creates a minimal DESCRIPTION file that renv can work with.

    Parameters
    ----------
    dependencies : list[str]
        List of R package names.
    project_name : str | None
        Name for the DESCRIPTION's ``Package`` field. It is sanitized into a
        valid R package name (letters, numbers and dots, starting with a
        letter). Falls back to the detected project name, then to
        ``CalkitProject``.

    Returns
    -------
    str
        The DESCRIPTION file content.
    """
    if project_name is None:
        project_name = calkit.detect_project_name(prepend_owner=False)
    # Valid R package names may only contain letters, numbers and dots, and
    # must start with a letter, so replace anything else (e.g. hyphens) with a
    # dot and prefix a letter if needed
    package_name = re.sub(r"[^A-Za-z0-9.]+", ".", project_name).strip(".")
    if not package_name or not package_name[0].isalpha():
        package_name = "Calkit." + package_name if package_name else "Calkit"
    content = f"""Package: {package_name}
Version: 0.0.1
Title: Auto-generated R environment
"""
    if dependencies:
        if len(dependencies) == 1:
            content += f"Imports: {dependencies[0]}\n"
        else:
            # Format with first package on same line, rest indented
            content += f"Imports: {dependencies[0]},\n"
            for i, dep in enumerate(dependencies[1:], 1):
                if i < len(dependencies) - 1:
                    content += f"    {dep},\n"
                else:
                    content += f"    {dep}\n"
    return content


def extract_dependencies_from_spec_file(
    spec_path: str, language: str | None = None
) -> list[str]:
    """Extract dependencies from an environment spec file.

    Parameters
    ----------
    spec_path : str
        Path to the spec file (requirements.txt, Project.toml, etc.).
    language : str | None
        Language hint to help identify the format. If None, will be inferred
        from the file path.

    Returns
    -------
    list[str]
        List of package/dependency names.
    """
    if not os.path.exists(spec_path):
        return []
    try:
        with open(spec_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (IOError, UnicodeDecodeError):
        return []
    # Determine format from filename if not provided
    if language is None:
        if spec_path.endswith("requirements.txt"):
            language = "python-requirements"
        elif spec_path.endswith("pyproject.toml"):
            language = "python-pyproject"
        elif spec_path.endswith("Project.toml"):
            language = "julia"
        elif spec_path.endswith("DESCRIPTION"):
            language = "r"
        elif spec_path.endswith("environment.yml"):
            language = "conda"
    dependencies: list[str] = []
    if language in ["python-requirements"]:
        # Parse requirements.txt
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                # Extract package name (before any version specifiers)
                pkg = line.split("[")[0].split("==")[0].split(">=")[0]
                pkg = pkg.split("<=")[0].split(">")[0].split("<")[0]
                pkg = pkg.split("~=")[0].strip()
                if pkg:
                    dependencies.append(pkg)
    elif language == "python-pyproject":
        # Parse pyproject.toml to extract dependencies
        try:
            data = toml.loads(content)
            project_deps = data.get("project", {}).get("dependencies", [])
            for dep in project_deps:
                # Extract package name (before any version specifiers)
                pkg = dep.split("[")[0].split("==")[0].split(">=")[0]
                pkg = pkg.split("<=")[0].split(">")[0].split("<")[0]
                pkg = pkg.split("~=")[0].strip()
                if pkg:
                    dependencies.append(pkg)
        except Exception:
            pass
    elif language == "julia":
        # Parse Julia Project.toml for [deps] section
        try:
            data = toml.loads(content)
            # Package names are the keys in the [deps] section
            deps_section = data.get("deps", {})
            if isinstance(deps_section, dict):
                dependencies = list(deps_section.keys())
        except Exception:
            pass
    elif language == "r":
        # Parse R DESCRIPTION file for Imports/Depends fields,
        # correctly handling multi-line (continued) fields where
        # continuation lines start with whitespace.
        lines = content.splitlines()
        i = 0
        while i < len(lines):
            raw_line = lines[i]
            stripped = raw_line.lstrip()
            if stripped.startswith(("Imports:", "Depends:")):
                # Extract the text after the field name and colon
                _, after_colon = stripped.split(":", 1)
                pkg_chunks: list[str] = [after_colon.strip()]
                # Collect continuation lines that start with whitespace
                j = i + 1
                while j < len(lines) and (
                    lines[j].startswith(" ") or lines[j].startswith("\t")
                ):
                    pkg_chunks.append(lines[j].strip())
                    j += 1
                # Join all chunks into a single dependency string
                pkg_str = " ".join(pkg_chunks)
                # Split on commas to get individual package entries
                pkgs = [p.strip() for p in pkg_str.split(",") if p.strip()]
                for pkg in pkgs:
                    # Remove version specifications if present
                    pkg = pkg.split("(", 1)[0].strip()
                    if pkg:
                        dependencies.append(pkg)
                # Continue parsing from the first non-continuation line
                i = j
                continue
            i += 1
    elif language == "conda":
        # Parse conda environment.yml
        try:
            data = yaml.safe_load(content)
            deps = data.get("dependencies", [])
            for dep in deps:
                if isinstance(dep, str):
                    # Extract package name (before version spec)
                    pkg = dep.split("==")[0].split(">=")[0].split("<=")[0]
                    pkg = pkg.split("=")[0].strip()
                    if "::" in pkg:
                        pkg = pkg.split("::", 1)[1]
                    if pkg:
                        dependencies.append(pkg)
                elif isinstance(dep, dict):
                    # Handle pip dependencies nested as {pip: [...]}
                    pip_deps = dep.get("pip", [])
                    for pip_dep in pip_deps:
                        if isinstance(pip_dep, str):
                            pkg = (
                                pip_dep.split("==")[0]
                                .split(">=")[0]
                                .split("<=")[0]
                                .split("[")[0]
                                .strip()
                            )
                            if "::" in pkg:
                                pkg = pkg.split("::", 1)[1]
                            if pkg:
                                dependencies.append(pkg)
        except Exception:
            pass
    # Remove duplicates and sort
    return sorted(list(set(dependencies)))


def env_has_superset_dependencies(
    env: dict,
    required_deps: list[str],
    env_spec_path: str | None = None,
    strict: bool = False,
) -> bool:
    """Check if an environment has a superset of required dependencies.

    Parameters
    ----------
    env : dict
        Environment dict from calkit.yaml with 'kind' and 'path' keys.
    required_deps : list[str]
        List of required dependencies to check for.
    env_spec_path : str | None
        Path to the environment spec file. If None, will use env.get("path").
    strict : bool
        If True, require the spec file to exist and have extractable
        dependencies. If False, be optimistic when spec file doesn't exist.

    Returns
    -------
    bool
        True if the environment contains all required dependencies,
        False otherwise.
    """
    if not required_deps:
        # No dependencies to check, so any environment works
        return True
    if env_spec_path is None:
        env_spec_path = env.get("path")
    if not env_spec_path:
        # No path to check
        if strict:
            return False
        return True
    if not os.path.exists(env_spec_path):
        # Spec file doesn't exist
        if strict:
            # Strict mode: can't verify, so reject
            return False
        # Optimistic mode: assume it might work
        return True
    # Extract dependencies from the environment's spec file
    env_deps = extract_dependencies_from_spec_file(env_spec_path)
    if not env_deps:
        # Couldn't extract dependencies (or file is empty)
        if strict:
            # Strict mode: can't verify, so reject
            return False
        # Optimistic mode: assume it might work
        return True
    # Check if env_deps is a superset of required_deps
    # (case-insensitive comparison for package names)
    env_deps_lower = {dep.lower() for dep in env_deps}
    required_deps_lower = {dep.lower() for dep in required_deps}
    transitive = {
        "jupyter": {"ipykernel"},
        "pandas": {"numpy"},
    }
    for base, provides in transitive.items():
        if base in env_deps_lower:
            env_deps_lower.update(provides)
    return required_deps_lower.issubset(env_deps_lower)


def detect_env_for_stage(
    stage: dict,
    environment: str | None = None,
    ck_info: dict | None = None,
    language: str | None = None,
) -> EnvForStageResult:
    """Detect or create an environment for a pipeline stage.

    This function first attempts to detect an existing environment. If that
    fails, it detects dependencies from the stage and creates an environment
    spec file.

    Parameters
    ----------
    stage : dict
        The pipeline stage dict with 'kind' and script/notebook paths.
    environment : str | None
        Optional environment name or path to use. If None, will be detected.
    ck_info : dict | None
        Calkit info dict. If None, will be loaded from calkit.yaml.
    language : str | None
        Language hint for environment detection.

    Returns
    -------
    EnvForStageResult
        Result containing environment info, spec path, content,
        and dependencies.
    """
    from calkit.detect import (
        detect_dependencies_from_notebook,
        detect_julia_dependencies,
        detect_python_dependencies,
        detect_r_dependencies,
        language_from_notebook,
    )

    if ck_info is None:
        ck_info = calkit.load_calkit_info()
    # Get existing environment names
    envs = ck_info.get("environments", {})
    all_env_names = list(envs.keys())
    # Generic shell commands should run on the host when no env is set.
    if environment is None and stage.get("kind") == "shell-command":
        return EnvForStageResult(
            name="_system",
            env={"kind": "system"},
            exists=True,
            spec_path=None,
            dependencies=[],
            created_from_dependencies=False,
        )
    # 1) If stage has an environment, use that
    if environment is not None:
        res = env_from_name_or_path(
            name_or_path=environment, ck_info=ck_info, language=language
        )
        return EnvForStageResult(
            name=res.name,
            env=res.env,
            exists=res.exists,
            spec_path=res.env.get("path"),
            dependencies=[],
            created_from_dependencies=False,
        )
    # Infer stage language if not provided
    stage_kind = stage.get("kind")
    stage_language = language
    if stage_language is None:
        if stage_kind == "jupyter-notebook":
            stage_language = (
                language_from_notebook(stage["notebook_path"]) or "python"
            )
        elif stage_kind == "python-script":
            stage_language = "python"
        elif stage_kind == "r-script":
            stage_language = "r"
        elif stage_kind == "julia-script":
            stage_language = "julia"
        elif stage_kind == "latex":
            stage_language = "latex"
        elif stage_kind in ["matlab-script", "matlab-command"]:
            stage_language = "matlab"
        elif stage_kind in ["shell-script", "shell-command"]:
            stage_language = "shell"
    language_kinds = {
        "python": ["uv", "uv-venv", "venv", "conda", "pixi"],
        "r": ["renv", "conda", "pixi"],
        "julia": ["julia"],
        "matlab": ["matlab"],
        "latex": ["docker"],
        "shell": ["system"],
    }
    preferred_kinds = (
        language_kinds.get(stage_language, []) if stage_language else []
    )
    is_first_env_for_language = not any(
        env.get("kind") in preferred_kinds for env in envs.values()
    )
    # Stages with analyzable content where we should check dependencies before
    # reusing existing environments
    analyzable_stages = {
        "jupyter-notebook",
        "python-script",
        "r-script",
        "julia-script",
        "shell-script",
    }
    # Initialize detected_dependencies so it's available throughout function
    detected_dependencies: list[str] = []
    # For analyzable stages, detect dependencies and check if existing
    # environments satisfy them
    if stage_language and stage_kind in analyzable_stages:
        if stage_kind == "python-script":
            detected_dependencies = detect_python_dependencies(
                script_path=stage["script_path"]
            )
        elif stage_kind == "r-script":
            detected_dependencies = detect_r_dependencies(
                script_path=stage["script_path"]
            )
        elif stage_kind == "julia-script":
            detected_dependencies = detect_julia_dependencies(
                script_path=stage["script_path"]
            )
        elif stage_kind == "jupyter-notebook":
            notebook_lang = language_from_notebook(stage["notebook_path"])
            detected_dependencies = detect_dependencies_from_notebook(
                stage["notebook_path"], language=notebook_lang
            )
        elif stage_kind == "matlab-script":
            # MATLAB detection if needed
            detected_dependencies = []
        elif stage_kind == "shell-script":
            # Shell script detection if needed
            detected_dependencies = []

        # Check if any existing environment has all these dependencies
        matching_envs = [
            (name, env)
            for name, env in envs.items()
            if env.get("kind") in preferred_kinds
        ]
        if matching_envs and detected_dependencies:
            # Check if any matching environment has all required dependencies
            # Use strict mode: only reuse if we can verify the deps are satisfied
            for env_name, env in sorted(
                matching_envs, key=lambda item: item[0]
            ):
                if env_has_superset_dependencies(
                    env, detected_dependencies, strict=True
                ):
                    env_name = cast(str, env_name)
                    return EnvForStageResult(
                        name=env_name,
                        env=env,
                        exists=True,
                        spec_path=env.get("path"),
                        dependencies=detected_dependencies,
                        created_from_dependencies=False,
                    )
            # No existing environment has verified dependencies, fall through to create
        # If no matching environment found or no dependencies detected,
        # fall through to create one from dependencies
    # 2) If there is already an environment for the stage language (for
    # non-analyzable stages or analyzable stages with no match), use that
    if stage_language and stage_kind not in analyzable_stages:
        matching_envs = [
            (name, env)
            for name, env in envs.items()
            if env.get("kind") in preferred_kinds
        ]
        if matching_envs:
            env_name, env = sorted(matching_envs, key=lambda item: item[0])[0]
            env_name = cast(str, env_name)
            return EnvForStageResult(
                name=env_name,
                env=env,
                exists=True,
                spec_path=env.get("path"),
                dependencies=[],
                created_from_dependencies=False,
            )
        if stage_language == "matlab":
            return EnvForStageResult(
                name="_system",
                env={"kind": "system"},
                exists=True,
                spec_path=None,
                dependencies=[],
                created_from_dependencies=False,
            )
    # 3) If a typical env spec exists for the stage language, use that
    # (fallback for analyzable stages if no existing environment matched)
    if stage_language:
        if stage_language == "latex":
            res = env_from_name_or_path(
                name_or_path=None,
                ck_info=ck_info,
                language=stage_language,
            )
            return EnvForStageResult(
                name=res.name,
                env=res.env,
                exists=res.exists,
                spec_path=res.env.get("path"),
                dependencies=[],
                created_from_dependencies=False,
            )
        spec_candidates = {
            "python": [
                "pyproject.toml",
                "requirements.txt",
                "environment.yml",
                "env/*.yml",
                "envs/*.yml",
                "pixi.toml",
            ],
            "r": [
                "DESCRIPTION",
                "environment.yml",
                "env/*.yml",
                "envs/*.yml",
                "pixi.toml",
            ],
            "julia": ["Project.toml"],
            "shell": ["Dockerfile"],
        }
        for spec_path in spec_candidates.get(stage_language, []):
            if "*" in spec_path:
                matches = sorted(glob.glob(spec_path))
                if matches:
                    spec_path = matches[0]
                else:
                    continue
            if os.path.isfile(spec_path):
                res = env_from_name_or_path(
                    name_or_path=spec_path,
                    ck_info=ck_info,
                    language=stage_language,
                )
                # For analyzable stages with detected dependencies, verify the
                # spec file has all required packages before reusing
                if stage_kind in analyzable_stages:
                    # Detect dependencies for this stage if not already done
                    if not detected_dependencies:
                        if stage_kind == "python-script":
                            detected_dependencies = detect_python_dependencies(
                                script_path=stage["script_path"]
                            )
                        elif stage_kind == "r-script":
                            detected_dependencies = detect_r_dependencies(
                                script_path=stage["script_path"]
                            )
                        elif stage_kind == "julia-script":
                            detected_dependencies = detect_julia_dependencies(
                                script_path=stage["script_path"]
                            )
                        elif stage_kind == "jupyter-notebook":
                            notebook_lang = language_from_notebook(
                                stage["notebook_path"]
                            )
                            detected_dependencies = (
                                detect_dependencies_from_notebook(
                                    stage["notebook_path"],
                                    language=notebook_lang,
                                )
                            )
                    # Only reuse if it has all the dependencies (strict mode)
                    if (
                        detected_dependencies
                        and not env_has_superset_dependencies(
                            res.env,
                            detected_dependencies,
                            spec_path,
                            strict=True,
                        )
                    ):
                        # This spec file doesn't have all deps, try next
                        # candidate
                        continue
                return EnvForStageResult(
                    name=res.name,
                    env=res.env,
                    exists=res.exists,
                    spec_path=res.env.get("path"),
                    dependencies=[],
                    created_from_dependencies=False,
                )
    dependencies: list[str] = []
    spec_path: str | None = None
    spec_content: str | None = None
    env_name: str | None = None
    env_dict: dict = {}
    # Detect dependencies based on stage kind
    if stage["kind"] == "python-script":
        dependencies = detect_python_dependencies(
            script_path=stage["script_path"]
        )
        project_name = calkit.detect_project_name(prepend_owner=False)
        # Generate unique environment name
        if is_first_env_for_language:
            temp_path = "pyproject.toml"
            env_name = make_env_name(temp_path, all_env_names, kind="uv")
            spec_path = "pyproject.toml"
            spec_content = create_uv_pyproject_content(dependencies)
            env_dict = {
                "kind": "uv",
                "path": spec_path,
            }
        else:
            temp_path = ".calkit/envs/py/pyproject.toml"
            env_name = make_env_name(temp_path, all_env_names, kind="uv")
            spec_path = f".calkit/envs/{env_name}/pyproject.toml"
            spec_content = create_uv_pyproject_content(
                dependencies,
                project_name=f"{project_name}-{env_name}",
            )
            env_dict = {
                "kind": "uv",
                "path": spec_path,
            }
    elif stage["kind"] == "r-script":
        dependencies = detect_r_dependencies(script_path=stage["script_path"])
        # Generate unique environment name
        if is_first_env_for_language:
            temp_path = "DESCRIPTION"
            env_name = make_env_name(temp_path, all_env_names, kind="renv")
            spec_path = "DESCRIPTION"
        else:
            temp_path = ".calkit/envs/r/DESCRIPTION"
            env_name = make_env_name(temp_path, all_env_names, kind="renv")
            spec_path = f".calkit/envs/{env_name}/DESCRIPTION"
        spec_content = create_r_description_content(dependencies)
        env_dict = {
            "kind": "renv",
            "path": spec_path,
        }
    elif stage["kind"] == "julia-script":
        dependencies = detect_julia_dependencies(
            script_path=stage["script_path"]
        )
        project_name = calkit.detect_project_name(prepend_owner=False)
        # Generate unique environment name
        if is_first_env_for_language:
            temp_path = "Project.toml"
            env_name = make_env_name(temp_path, all_env_names, kind="julia")
            spec_path = "Project.toml"
            julia_env_name = project_name
        else:
            temp_path = ".calkit/envs/julia/Project.toml"
            env_name = make_env_name(temp_path, all_env_names, kind="julia")
            spec_path = f".calkit/envs/{env_name}/Project.toml"
            julia_env_name = f"{project_name}-{env_name}"
        spec_content = create_julia_project_file_content(
            dependencies, project_name=julia_env_name
        )
        env_dict = {
            "kind": "julia",
            "path": spec_path,
            "julia": _get_julia_version(),
        }
    elif stage["kind"] == "jupyter-notebook":
        notebook_lang = language_from_notebook(stage["notebook_path"])
        dependencies = detect_dependencies_from_notebook(
            stage["notebook_path"], language=notebook_lang
        )
        if notebook_lang == "python" or notebook_lang is None:
            project_name = calkit.detect_project_name(prepend_owner=False)
            # Add ipykernel for Jupyter notebook support
            if "ipykernel" not in dependencies:
                dependencies.append("ipykernel")
            # Generate unique environment name
            if is_first_env_for_language:
                temp_path = "pyproject.toml"
                env_name = make_env_name(temp_path, all_env_names, kind="uv")
                spec_path = "pyproject.toml"
                spec_content = create_uv_pyproject_content(dependencies)
                env_dict = {
                    "kind": "uv",
                    "path": spec_path,
                }
            else:
                temp_path = ".calkit/envs/py/pyproject.toml"
                env_name = make_env_name(temp_path, all_env_names, kind="uv")
                spec_path = f".calkit/envs/{env_name}/pyproject.toml"
                spec_content = create_uv_pyproject_content(
                    dependencies,
                    project_name=f"{project_name}-{env_name}",
                )
                env_dict = {
                    "kind": "uv",
                    "path": spec_path,
                }
        elif notebook_lang == "r":
            # Add IRkernel for Jupyter notebook support
            if "IRkernel" not in dependencies:
                dependencies.append("IRkernel")
            # Generate unique environment name
            if is_first_env_for_language:
                temp_path = "DESCRIPTION"
                env_name = make_env_name(temp_path, all_env_names, kind="renv")
                spec_path = "DESCRIPTION"
            else:
                temp_path = ".calkit/envs/r/DESCRIPTION"
                env_name = make_env_name(temp_path, all_env_names, kind="renv")
                spec_path = f".calkit/envs/{env_name}/DESCRIPTION"
            spec_content = create_r_description_content(dependencies)
            env_dict = {
                "kind": "renv",
                "path": spec_path,
            }
        elif notebook_lang == "julia":
            # Add IJulia for Jupyter notebook support
            if "IJulia" not in dependencies:
                dependencies.append("IJulia")
            project_name = calkit.detect_project_name(prepend_owner=False)
            # Generate unique environment name
            if is_first_env_for_language:
                temp_path = "Project.toml"
                env_name = make_env_name(
                    temp_path, all_env_names, kind="julia"
                )
                spec_path = "Project.toml"
                julia_env_name = project_name
            else:
                temp_path = ".calkit/envs/julia/Project.toml"
                env_name = make_env_name(
                    temp_path, all_env_names, kind="julia"
                )
                spec_path = f".calkit/envs/{env_name}/Project.toml"
                julia_env_name = f"{project_name}-{env_name}"
            spec_content = create_julia_project_file_content(
                dependencies, project_name=julia_env_name
            )
            env_dict = {
                "kind": "julia",
                "path": spec_path,
                "julia": _get_julia_version(),
            }
    if not spec_path or not env_name:
        raise ValueError(
            f"Could not create environment for stage kind: {stage.get('kind')}"
        )
    return EnvForStageResult(
        name=env_name,
        env=env_dict,
        exists=False,
        spec_path=spec_path,
        spec_content=spec_content,
        dependencies=dependencies,
        created_from_dependencies=True,
    )
