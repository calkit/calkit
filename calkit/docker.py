"""Functionality for working with Docker."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from pydantic import BaseModel

MINIFORGE_LAYER_TXT = r"""
# Install Miniforge
ARG MINIFORGE_NAME=Miniforge3
ARG MINIFORGE_VERSION=24.9.2-0
ARG TARGETPLATFORM

ENV CONDA_DIR=/opt/conda
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8
ENV PATH=${CONDA_DIR}/bin:${PATH}

# 1. Install just enough for conda to work
# 2. Keep $HOME clean (no .wget-hsts file), since HSTS isn't useful in this context
# 3. Install miniforge from GitHub releases
# 4. Apply some cleanup tips from https://jcrist.github.io/conda-docker-tips.html
#    Particularly, we remove pyc and a files. The default install has no js, we can skip that
# 5. Activate base by default when running as any *non-root* user as well
#    Good security practice requires running most workloads as non-root
#    This makes sure any non-root users created also have base activated
#    for their interactive shells.
# 6. Activate base by default when running as root as well
#    The root user is already created, so won't pick up changes to /etc/skel
RUN apt-get update > /dev/null && \
    apt-get install --no-install-recommends --yes \
        wget bzip2 ca-certificates \
        git \
        tini \
        > /dev/null && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    wget --no-hsts --quiet https://github.com/conda-forge/miniforge/releases/download/${MINIFORGE_VERSION}/${MINIFORGE_NAME}-${MINIFORGE_VERSION}-Linux-$(uname -m).sh -O /tmp/miniforge.sh && \
    /bin/bash /tmp/miniforge.sh -b -p ${CONDA_DIR} && \
    rm /tmp/miniforge.sh && \
    conda clean --tarballs --index-cache --packages --yes && \
    find ${CONDA_DIR} -follow -type f -name '*.a' -delete && \
    find ${CONDA_DIR} -follow -type f -name '*.pyc' -delete && \
    conda clean --force-pkgs-dirs --all --yes  && \
    echo ". ${CONDA_DIR}/etc/profile.d/conda.sh && conda activate base" >> /etc/skel/.bashrc && \
    echo ". ${CONDA_DIR}/etc/profile.d/conda.sh && conda activate base" >> ~/.bashrc
""".strip()

FOAMPY_LAYER_TEXT = r"""
RUN pip install --no-cache-dir numpy pandas matplotlib h5py \
    && pip install --no-cache-dir scipy \
    && pip install --no-cache-dir foampy
""".strip()

UV_LAYER_TEXT = """
COPY --from=ghcr.io/astral-sh/uv:0.8.5 /uv /uvx /bin/
"""

JULIA_LAYER_TEXT = """
# Install Julia
# Ensure base image is a bullseye distribution
COPY --from=julia:1.11.6-bullseye /usr/local/julia /usr/local/julia
ENV JULIA_PATH=/usr/local/julia \
    PATH=$PATH:/usr/local/julia/bin \
    JULIA_GPG=3673DF529D9049477F76B37566E3C7DC03D6E495 \
    JULIA_VERSION=1.11.6
"""

LAYERS = {
    "mambaforge": MINIFORGE_LAYER_TXT,
    "miniforge": MINIFORGE_LAYER_TXT,
    "foampy": FOAMPY_LAYER_TEXT,
    "uv": UV_LAYER_TEXT,
    "julia": JULIA_LAYER_TEXT,
}

# Docker images whose commands should be passed directly to the image
# entrypoint when normalizing `xr` commands
XR_DOCKER_ENTRYPOINT_IMAGES = {
    "minlag/mermaid-cli",
}


class NormalizedXRDockerCommand(BaseModel):
    """Normalized Docker command metadata for `calkit xr`."""

    image: str
    wdir: str
    command: list[str]
    inputs: list[str]
    outputs: list[str]
    environment_name: str
    stage_name: str | None = None
    description: str | None = None
    command_mode: str = "shell"


def _image_name_without_tag_or_digest(image: str) -> str:
    """Return an image name without tag or digest components."""
    name = image.split("@", 1)[0]
    last_slash = name.rfind("/")
    last_colon = name.rfind(":")
    # Only strip a tag when the colon appears in the final path segment.
    if last_colon > last_slash:
        name = name[:last_colon]
    return name.lower()


def _sanitize_stage_name(stage_name: str) -> str:
    """Normalize a stage name to the same kebab-case style used by xr."""
    stage_name = stage_name.replace("_", "-").lower()
    stage_name = stage_name.replace(".", "-")
    stage_name = stage_name.replace(" ", "-")
    stage_name = re.sub(r"[(){}\[\]'\"><|&;/]", "", stage_name)
    stage_name = re.sub(r"-+", "-", stage_name)
    stage_name = stage_name.strip("-")
    if not stage_name:
        return "stage"
    return stage_name


def _uses_entrypoint_command_mode(image: str) -> bool:
    """Return True when image is in the `xr` entrypoint-mode allowlist."""
    image_name = _image_name_without_tag_or_digest(image)
    for configured in XR_DOCKER_ENTRYPOINT_IMAGES:
        configured_name = configured.lower()
        if image_name == configured_name:
            return True
        if image_name.endswith("/" + configured_name):
            return True
    return False


def split_xr_command(cmd: list[str]) -> list[str]:
    """Split a single quoted `docker run ...` command into argv tokens."""
    if len(cmd) != 1:
        return cmd
    if not cmd[0].lstrip().startswith("docker run"):
        return cmd
    try:
        return shlex.split(cmd[0])
    except ValueError:
        return cmd


def _normalize_docker_image(image: str) -> str:
    """Ensure Docker image references include an explicit tag."""
    if "@" in image:
        return image
    if ":" in image.rsplit("/", 1)[-1]:
        return image
    return image + ":latest"


def _parse_volume_spec(volume_spec: str) -> tuple[str, str] | None:
    """Parse a Docker volume spec into source and destination paths."""
    if ":" not in volume_spec:
        return None
    parts = volume_spec.rsplit(":", 2)
    source = ""
    dest = ""
    if len(parts) == 2:
        source, dest = parts
    elif len(parts) == 3:
        first, second, third = parts
        # Handle Windows drive-letter sources with no explicit mode, e.g.,
        # C:\path:/data, which rsplit(':', 2) yields as
        # ["C", "\\path", "/data"]
        if (
            len(first) == 1
            and first.isalpha()
            and second.startswith(("\\", "/"))
        ):
            source, dest = first + ":" + second, third
        else:
            # Assume source:dest:mode and ignore the optional mode segment
            source, dest = first, second
    else:
        return None
    if not source or not dest:
        return None
    return source, dest


def _to_project_relative_path(path: str, cwd: Path) -> str | None:
    """Resolve a path and return it relative to the project root when possible."""
    path_obj = Path(os.path.expanduser(path))
    if not path_obj.is_absolute():
        path_obj = (cwd / path_obj).resolve(strict=False)
    else:
        path_obj = path_obj.resolve(strict=False)
    try:
        return path_obj.relative_to(cwd).as_posix()
    except ValueError:
        return None


def _parse_docker_run_command(cmd: list[str]) -> dict | None:
    """Parse a `docker run` argv list into image, args, mounts, and workdir."""
    if len(cmd) < 3 or cmd[0] != "docker" or cmd[1] != "run":
        return None
    no_arg_opts = {"--rm", "-i", "-t", "-it"}
    one_arg_opts = {
        "-u": "user",
        "--user": "user",
        "-e": "env",
        "--env": "env",
        "--env-file": "env-file",
        "--network": "network",
        "--pull": "pull",
        "-v": "volume",
        "--volume": "volume",
        "-w": "workdir",
        "--workdir": "workdir",
        "--platform": "platform",
        "--gpus": "gpus",
        "-p": "port",
        "--publish": "port",
        "--name": "name",
        "--entrypoint": "entrypoint",
    }
    volume_specs: list[str] = []
    workdir = None
    image = None
    idx = 2
    while idx < len(cmd):
        token = cmd[idx]
        if token == "--":
            idx += 1
            break
        if token in no_arg_opts:
            idx += 1
            continue
        if token in one_arg_opts:
            if idx + 1 >= len(cmd):
                return None
            value = cmd[idx + 1]
            if one_arg_opts[token] == "volume":
                volume_specs.append(value)
            elif one_arg_opts[token] == "workdir":
                workdir = value
            idx += 2
            continue
        if token.startswith("--volume="):
            volume_specs.append(token.split("=", 1)[1])
            idx += 1
            continue
        if token.startswith("--workdir="):
            workdir = token.split("=", 1)[1]
            idx += 1
            continue
        if token.startswith("--env="):
            idx += 1
            continue
        if token.startswith("--env-file="):
            idx += 1
            continue
        if token.startswith("--network="):
            idx += 1
            continue
        if token.startswith("--pull="):
            idx += 1
            continue
        if token.startswith("--user="):
            idx += 1
            continue
        if token.startswith("-"):
            # Unknown docker option: skip and continue scanning for image.
            # This keeps normalization resilient to common flags we don't
            # explicitly model.
            idx += 1
            continue
        image = token
        idx += 1
        break
    if image is None:
        return None
    return {
        "image": image,
        "workdir": workdir,
        "volumes": volume_specs,
        "command": cmd[idx:],
    }


def _map_container_path_to_project(
    path: str,
    source_prefix: str | None,
    container_wdir: str,
) -> str:
    """Map a container path back to a project-relative path when possible."""
    path = path.strip()
    if source_prefix is None:
        return path
    source_prefix = source_prefix.strip("/")
    if path.startswith(container_wdir.rstrip("/") + "/"):
        suffix = path[len(container_wdir.rstrip("/")) + 1 :]
        if source_prefix:
            return Path(source_prefix, suffix).as_posix()
        return Path(suffix).as_posix()
    if os.path.isabs(path):
        return path
    if source_prefix and path.startswith(source_prefix + "/"):
        return path
    if source_prefix:
        return Path(source_prefix, path).as_posix()
    return Path(path).as_posix()


def normalize_xr_docker_command(
    cmd: list[str],
    environment: str | None = None,
    cwd: str | None = None,
) -> NormalizedXRDockerCommand | None:
    """Normalize supported `docker run` commands into `xr` command metadata."""
    cwd_path = Path(cwd or ".").resolve()
    cmd = split_xr_command(cmd)
    parsed = _parse_docker_run_command(cmd)
    if parsed is None:
        return None
    image = _normalize_docker_image(parsed["image"])
    if not _uses_entrypoint_command_mode(image):
        return None
    image_name = _image_name_without_tag_or_digest(image)
    is_mermaid_image = image_name.endswith("mermaid-cli")
    chosen_mount = None
    volumes = parsed["volumes"]
    if parsed["workdir"] is not None:
        for volume_spec in volumes:
            parsed_volume = _parse_volume_spec(volume_spec)
            if parsed_volume is None:
                continue
            source, dest = parsed_volume
            if dest == parsed["workdir"]:
                chosen_mount = (source, dest)
                break
    if chosen_mount is None and volumes:
        parsed_volume = _parse_volume_spec(volumes[0])
        if parsed_volume is not None:
            chosen_mount = parsed_volume
    container_wdir = parsed["workdir"]
    if container_wdir is None:
        if chosen_mount is not None:
            container_wdir = chosen_mount[1]
        else:
            container_wdir = "/data" if is_mermaid_image else "/work"
    source_prefix = None
    if chosen_mount is not None:
        source_prefix = _to_project_relative_path(chosen_mount[0], cwd_path)
        if source_prefix is None:
            source_prefix = chosen_mount[0]
    command_tokens = parsed["command"]
    if not command_tokens:
        return None
    normalized_args: list[str] = list(command_tokens)
    detected_inputs: list[str] = []
    detected_outputs: list[str] = []
    if is_mermaid_image:
        normalized_args = []
        idx = 0
        while idx < len(command_tokens):
            token = command_tokens[idx]
            if token in ["-i", "--input", "-o", "--output"]:
                normalized_args.append(token)
                if idx + 1 >= len(command_tokens):
                    break
                mapped_path = _map_container_path_to_project(
                    command_tokens[idx + 1],
                    source_prefix,
                    container_wdir,
                )
                normalized_args.append(mapped_path)
                if token in ["-i", "--input"]:
                    detected_inputs.append(mapped_path)
                else:
                    detected_outputs.append(mapped_path)
                idx += 2
                continue
            if token.startswith("--input=") or token.startswith("--output="):
                option, path_value = token.split("=", 1)
                mapped_path = _map_container_path_to_project(
                    path_value,
                    source_prefix,
                    container_wdir,
                )
                normalized_args.append(f"{option}={mapped_path}")
                if option == "--input":
                    detected_inputs.append(mapped_path)
                else:
                    detected_outputs.append(mapped_path)
                idx += 1
                continue
            normalized_args.append(token)
            idx += 1
    stage_name = None
    if is_mermaid_image and detected_inputs:
        raw_stage_name = f"mermaid-{Path(detected_inputs[0]).stem}"
        stage_name = _sanitize_stage_name(raw_stage_name)
    env_name = environment
    if env_name is None:
        if is_mermaid_image:
            env_name = "mermaid"
        else:
            env_name = image_name.split("/")[-1].replace("_", "-")
    description = "Mermaid CLI via Docker."
    if not is_mermaid_image:
        description = f"Docker CLI via image {image}."
    return NormalizedXRDockerCommand(
        image=image,
        wdir=container_wdir,
        command=normalized_args,
        inputs=detected_inputs,
        outputs=detected_outputs,
        environment_name=env_name,
        stage_name=stage_name,
        description=description,
        command_mode="entrypoint",
    )


def extract_docker_run_inner_command(
    cmd: str | list[str],
) -> list[str] | None:
    """Extract the inner command from a ``docker run ...`` invocation."""
    if isinstance(cmd, str):
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            return None
    else:
        tokens = cmd
    tokens = split_xr_command(tokens)
    parsed = _parse_docker_run_command(tokens)
    if parsed is None:
        return None
    inner_command: list[str] = parsed.get("command", [])
    if not inner_command:
        return None
    return inner_command


def infer_xr_docker_environment(
    cmd: list[str],
    environment: str | None = None,
) -> tuple[str, dict] | None:
    """Infer a Docker environment from a `docker run ...` command.

    Returns a tuple of `(env_name, env_dict)` when parsing succeeds, or
    `None` for non-Docker/non-parseable commands.
    """
    cmd = split_xr_command(cmd)
    parsed = _parse_docker_run_command(cmd)
    if parsed is None:
        return None
    image = _normalize_docker_image(parsed["image"])
    image_name = _image_name_without_tag_or_digest(image)
    env_name = environment or image_name.split("/")[-1].replace("_", "-")
    wdir = parsed["workdir"] or "/work"
    env: dict = {
        "kind": "docker",
        "image": image,
    }
    if wdir != "/work":
        env["wdir"] = wdir
    if _uses_entrypoint_command_mode(image):
        env["command_mode"] = "entrypoint"
    return env_name, env


# Keys from ``docker inspect`` that identify an image's content, as opposed
# to metadata like creation time, which changes on every build
LOCK_INSPECT_KEYS = ["RepoDigests", "Architecture", "Os", "RootFS"]
# The registry used when an image reference has no registry component
DEFAULT_REGISTRY = "docker.io"


def inspect_image(ref: str) -> dict | None:
    """Return ``docker inspect`` output for an image, or None if absent."""
    try:
        out = subprocess.check_output(
            ["docker", "inspect", ref], stderr=subprocess.DEVNULL
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    try:
        resp: list = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not resp:
        return None
    first = resp[0]
    return first if isinstance(first, dict) else None


def inspect_image_for_lock(ref: str) -> dict | None:
    """Return the identity-defining subset of an image's inspect output."""
    resp = inspect_image(ref)
    if resp is None:
        return None
    return {key: resp.get(key) for key in LOCK_INSPECT_KEYS}


def split_image_ref(
    ref: str,
) -> tuple[str | None, str, str | None, str | None]:
    """Split an image reference into registry, name, tag, and digest.

    The registry is None for references like ``ubuntu:22.04``, which Docker
    implicitly resolves against Docker Hub.
    """
    digest = None
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    registry = None
    remainder = ref
    if "/" in ref:
        first, rest = ref.split("/", 1)
        # A first component is only a registry if it looks like a host, i.e.,
        # it has a dot or port separator, or is localhost. Otherwise it's a
        # Docker Hub namespace like 'library' in 'library/ubuntu'.
        if "." in first or ":" in first or first == "localhost":
            registry = first
            remainder = rest
    tag = None
    name = remainder
    last_slash = remainder.rfind("/")
    last_colon = remainder.rfind(":")
    if last_colon > last_slash:
        name = remainder[:last_colon]
        tag = remainder[last_colon + 1 :]
    return registry, name, tag, digest


def get_default_registry_prefix(wdir: str | None = None) -> str | None:
    """Return the default registry prefix for a project's images.

    Images are namespaced under the project's GitHub repo in the GitHub
    Container Registry, e.g., ``ghcr.io/someone/some-project``. Returns None
    if the project has no GitHub remote, since there's then no namespace we
    can claim on the user's behalf.
    """
    import calkit

    try:
        url = calkit.git.get_repo(wdir).remote().url
    except Exception:
        return None
    if "github.com" not in url:
        return None
    path = url.split("github.com")[-1].lstrip(":/").removesuffix(".git")
    parts = [p for p in path.split("/") if p]
    if len(parts) != 2:
        return None
    # Registry paths must be lowercase, whereas GitHub owner and repo names
    # are case-insensitive but case-preserving
    return "ghcr.io/" + "/".join(parts).lower()


def get_remote_image_ref(
    image: str, registry_prefix: str, env_name: str | None = None
) -> str:
    """Build the remote reference an image is pushed to and pulled from.

    The local image name is kept as the final path component so a project's
    images stay distinguishable within its namespace, falling back to the
    environment name for images whose local name is already qualified.
    """
    _, name, tag, _ = split_image_ref(image)
    name = name.rsplit("/", 1)[-1]
    if not name and env_name is not None:
        name = env_name
    # Repository names must be lowercase, but tags are case-sensitive, so
    # only the path is normalized
    path = f"{registry_prefix.rstrip('/')}/{name}".lower()
    return f"{path}:{tag or 'latest'}"


def _run_showing_output(cmd: list[str]) -> tuple[bool, str]:
    """Run a command, showing its output as it happens and keeping it.

    Pushing and pulling an image are the slowest things Calkit does, and
    swallowing Docker's progress for minutes on end looks like a hang, so
    the output goes to the terminal as it arrives. It's captured too, since
    what a registry says on refusal decides what happens next.
    """
    lines: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        return False, "Docker is not installed"
    assert proc.stdout is not None
    # Docker redraws each layer's status in place on a terminal, but writes
    # every repeat as its own line through a pipe, so a slow push scrolls
    # hundreds of identical 'Waiting' lines past. Only changes are worth
    # showing; a real transfer changes its byte count and still comes
    # through.
    last_status: dict[str, str] = {}
    for line in proc.stdout:
        lines.append(line)
        layer_id, sep, status = line.partition(": ")
        if sep and " " not in layer_id:
            if last_status.get(layer_id) == status:
                continue
            last_status[layer_id] = status
        print(line, end="", flush=True)
    proc.stdout.close()
    return proc.wait() == 0, "".join(lines)


def pull_image(ref: str, platform: str | None = None) -> tuple[bool, str]:
    """Pull an image, returning success and its output."""
    cmd = ["docker", "pull"]
    if platform is not None:
        cmd += ["--platform", platform]
    cmd.append(ref)
    return _run_showing_output(cmd)


def pull_image_with_login(ref: str, platform: str | None = None) -> bool:
    """Pull an image, sorting out registry credentials if it's refused.

    Logging in replaces whatever credentials the machine already holds for
    that registry, which in CI are the ones the workflow logged in with, so
    it's only done when the registry actually refused this pull. An image
    that isn't there, or a registry that can't be reached, is not something
    a different set of credentials would fix.
    """
    success, output = pull_image(ref, platform=platform)
    if success or not is_auth_error(output):
        return success
    logged_in, _ = login_to_registry(ref)
    if not logged_in:
        return False
    success, _ = pull_image(ref, platform=platform)
    return success


def tag_image(source: str, target: str) -> bool:
    """Apply an additional tag to an image, returning True on success."""
    try:
        subprocess.check_output(
            ["docker", "tag", source, target], stderr=subprocess.STDOUT
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


def push_image(ref: str) -> tuple[bool, str]:
    """Push an image, returning success and its output."""
    return _run_showing_output(["docker", "push", ref])


def platform_to_arch_name(platform: dict | str) -> str | None:
    """Convert an OCI platform into Calkit's lock file architecture name.

    Returns None for non-Linux platforms and for the ``unknown/unknown``
    entries registries use for attestation manifests, neither of which
    describe a runnable image.
    """
    if isinstance(platform, str):
        parts = platform.split("/")
        os_name = parts[0] if parts else ""
        arch = parts[1] if len(parts) > 1 else ""
        variant = parts[2] if len(parts) > 2 else ""
    else:
        os_name = platform.get("os", "")
        arch = platform.get("architecture", "")
        variant = platform.get("variant", "") or ""
    if os_name != "linux" or not arch or arch == "unknown":
        return None
    if variant:
        return f"{arch}-{variant}"
    return arch


def inspect_remote_image(ref: str) -> dict | None:
    """Inspect an image in a registry without pulling it.

    Returns the parsed ``docker buildx imagetools inspect`` output, which
    carries the manifest (or index) and the image config for every platform
    the reference resolves to.
    """
    try:
        out = subprocess.check_output(
            [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                ref,
                "--format",
                "{{json .}}",
            ],
            stderr=subprocess.DEVNULL,
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    try:
        resp = json.loads(out)
    except json.JSONDecodeError:
        return None
    return resp if isinstance(resp, dict) else None


def get_remote_image_platform_locks(ref: str) -> dict[str, dict] | None:
    """Read the identity of every platform behind a remote image reference.

    Returns a mapping of Calkit architecture name to the same identifying
    fields ``docker inspect`` provides, so lock files can be written for
    platforms this machine can't run.

    None means the registry couldn't be asked---it's unreachable, the image
    isn't there, or this machine has no buildx plugin---as opposed to an
    empty mapping, which is the registry answering that it serves no
    platform we can lock. Only an answer can make a lock file stale.
    """
    resp = inspect_remote_image(ref)
    if resp is None:
        return None
    manifest = resp.get("manifest") or {}
    digest = manifest.get("digest")
    repo_digests = [digest] if digest else []
    images = resp.get("image") or {}
    # A single-platform reference yields one config object rather than a
    # mapping of platform to config
    if "rootfs" in images:
        images = {
            f"{images.get('os')}/{images.get('architecture')}": images,
        }
    locks = {}
    for platform, config in images.items():
        if not isinstance(config, dict):
            continue
        arch_name = platform_to_arch_name(platform)
        if arch_name is None:
            continue
        rootfs = config.get("rootfs") or {}
        diff_ids = rootfs.get("diff_ids")
        if not diff_ids:
            continue
        locks[arch_name] = {
            "RepoDigests": repo_digests,
            "Architecture": config.get("architecture"),
            "Os": config.get("os"),
            "RootFS": {"Type": "layers", "Layers": diff_ids},
        }
    return locks


def lock_matches_spec(
    lock: dict,
    dockerfile_md5: str | None,
    deps_md5s: dict[str, str],
) -> bool:
    """Return True if a lock file describes the current environment spec.

    A lock that doesn't match is stale rather than merely out-of-date with
    the local image: its recorded digest identifies an image built from
    different inputs, so it can't be used to pull.

    What the image is called isn't part of this. A lock belongs to the
    environment whose directory it sits in, the name comes from calkit.yaml,
    and the digest names the content, so renaming an image would only rerun
    every stage in it for software that didn't change. A digest left over
    from a different image can't resolve either, since the repo it's asked
    for comes from the current definition.
    """
    if lock.get("DockerfileMD5") != dockerfile_md5:
        return False
    if (lock.get("DepsMD5s") or {}) != (deps_md5s or {}):
        return False
    return True


def lock_matches_image(lock: dict, image_info: dict) -> bool:
    """Return True if an image's content is what a lock file records."""
    locked = (lock.get("RootFS") or {}).get("Layers")
    actual = (image_info.get("RootFS") or {}).get("Layers")
    return bool(locked) and locked == actual


def get_lock_digest_refs(
    lock: dict, remote_ref: str | None = None
) -> list[str]:
    """Return references that pull the image a lock records, best first.

    A lock records the digest alone, since a digest names the image's
    content while a repository only says where a copy of it lives. The repo
    to pull from comes from ``remote_ref``, worked out from the environment
    definition at the time of asking, so an environment that changes which
    image it uses can't resolve a digest left over from the old one. Locks
    written before digests were stored bare name their repo outright and
    are still honored.
    """
    refs = []
    remote_repo = (
        get_repo_from_ref(remote_ref) if remote_ref is not None else None
    )
    for digest in lock.get("RepoDigests") or []:
        if "@" in digest:
            refs.append(digest)
        elif remote_repo is not None and ":" in digest:
            refs.append(f"{remote_repo}@{digest}")
    if remote_repo is None:
        return refs
    preferred = [r for r in refs if r.split("@", 1)[0] == remote_repo]
    return preferred + [r for r in refs if r not in preferred]


def build_lock(
    identity: dict,
    dockerfile_md5: str | None,
    deps_md5s: dict[str, str],
    run_config: dict,
) -> dict:
    """Assemble a lock file's contents for one platform.

    Key order is fixed so that a lock written for a platform from a registry
    matches byte-for-byte the one that platform would write for itself.
    """
    lock = {key: identity.get(key) for key in LOCK_INSPECT_KEYS}
    # Normalize here rather than at each call site, so that a lock carried
    # over from an earlier run, in whatever form that run wrote it, comes
    # out in the same form as one written from scratch
    lock["RepoDigests"] = get_content_digests(lock)
    lock["DockerfileMD5"] = dockerfile_md5
    lock["DepsMD5s"] = deps_md5s
    lock.update(run_config)
    return lock


# Values of an environment's ``registry`` that name the GitHub Container
# Registry without saying which namespace, leaving that to be worked out
# from the project's Git remote. ``ghcr.io`` is the documented one, since a
# registry Calkit runs itself someday would have as much claim to 'auto'
AUTO_REGISTRY_VALUES = ["ghcr.io", "ghcr", "github", "auto", "true"]


def registry_is_auto(registry: str | None) -> bool:
    """Return True if a ``registry`` value asks Calkit to work one out."""
    if registry is None:
        return False
    return str(registry).strip().lower() in AUTO_REGISTRY_VALUES


def resolve_registry_prefix(env: dict, wdir: str | None = None) -> str | None:
    """Return the registry prefix used for an environment's images.

    Registries are opt-in, since pushing an image publishes it somewhere the
    project doesn't necessarily control, so images are kept local when
    ``registry`` is unset or null. ``ghcr.io`` on its own resolves to the
    GitHub Container Registry namespace beside the project's repo, which is
    the one namespace we can name on the user's behalf. The strings a shell
    has to use in place of null are read as null too, since ``--registry
    none`` is the only way to say it on the command line.
    """
    registry = env.get("registry")
    if registry is None or registry is False:
        return None
    registry = str(registry).strip()
    if registry.lower() in ["none", "false", ""]:
        return None
    if registry.lower() in AUTO_REGISTRY_VALUES:
        return get_default_registry_prefix(wdir=wdir)
    return registry


def get_repo_from_ref(ref: str) -> str:
    """Return an image reference's repository, without its tag or digest."""
    repo = ref.split("@", 1)[0]
    if ":" in repo.rsplit("/", 1)[-1]:
        repo = repo[: repo.rfind(":")]
    return repo


def untag_image(ref: str) -> bool:
    """Remove one tag from an image, leaving the image itself alone."""
    try:
        subprocess.check_output(
            ["docker", "rmi", "--no-prune", ref], stderr=subprocess.STDOUT
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


def registry_has_image(remote_ref: str, identity: dict) -> bool:
    """Return True if a registry already serves this exact image.

    Tagging an image with a registry-qualified name is enough to give it a
    digest under that repo locally, so an image's own digests say nothing
    about whether anything was ever pushed. Only what the registry serves
    does, so its layers are what get compared.
    """
    layers = (identity.get("RootFS") or {}).get("Layers")
    if not layers:
        return False
    remote = get_remote_image_platform_locks(remote_ref)
    if remote is None:
        return False
    return any(
        (entry.get("RootFS") or {}).get("Layers") == layers
        for entry in remote.values()
    )


def get_content_digests(identity: dict) -> list[str]:
    """Return the digests an image carries, without their repositories.

    A manifest is content-addressed, so an image built here already carries
    the digest it will have in a registry: pushing transfers those bytes
    rather than recomputing them. That makes a local build's digest worth
    recording before it has been pushed anywhere.
    """
    digests = []
    for entry in identity.get("RepoDigests") or []:
        _, _, digest = entry.rpartition("@")
        if ":" in digest and digest not in digests:
            digests.append(digest)
    return digests


def keep_only_repo_digests(identity: dict, ref: str | None) -> dict:
    """Reduce an image's digests to the bare one a lock should record.

    Which digests an image carries locally depends on how it was obtained:
    building assigns one under a repo name that doesn't exist anywhere, and
    pulling by digest then tagging leaves both that and the real one. Only
    the digest the given reference's repo serves is kept, and only the
    ``sha256:...`` itself, since that names the image's content while the
    repository only says where a copy of it lives. Moving an environment to
    a different registry then leaves the lock alone, rather than rerunning
    every stage in it for software that didn't change.
    """
    identity = dict(identity)
    if ref is None:
        identity["RepoDigests"] = []
        return identity
    repo = get_repo_from_ref(ref)
    digests = []
    for entry in identity.get("RepoDigests") or []:
        entry_repo, _, digest = entry.rpartition("@")
        if entry_repo and entry_repo != repo:
            continue
        # A digest is ``<algorithm>:<hex>``, so anything without a separator
        # is not one, whatever else it might be
        if ":" in digest and digest not in digests:
            digests.append(digest)
    identity["RepoDigests"] = digests
    return identity


def get_lock_archs(env: dict) -> list[str]:
    """Return the architectures an environment should be locked for.

    Both of the architectures in common use are locked whether or not this
    machine runs them, so that moving a project between them doesn't
    invalidate every stage in the environment.
    """
    from calkit.environments import DEFAULT_DOCKER_LOCK_ARCHS

    archs = list(DEFAULT_DOCKER_LOCK_ARCHS)
    for platform in env.get("build_platforms") or []:
        arch = platform_to_arch_name(platform)
        if arch is not None and arch not in archs:
            archs.append(arch)
    return archs


def image_exists(ref: str) -> bool:
    """Return True if an image is present in the local image store."""
    try:
        subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", ref],
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


# What a registry says when the credentials it got aren't good enough, as
# opposed to the network being down or the image not existing
_AUTH_ERROR_MARKERS = [
    "permission_denied",
    "does not match expected scopes",
    "insufficient_scope",
    "unauthorized",
    "authentication required",
    "denied:",
    "requested access to the resource is denied",
]
# Creating a classic token with exactly what pushing an image needs
GITHUB_PACKAGES_TOKEN_URL = (
    "https://github.com/settings/tokens/new"
    "?scopes=write:packages,read:packages&description=Calkit"
)


def is_auth_error(output: str) -> bool:
    """Return True if a registry refused the credentials it was given."""
    lowered = output.lower()
    return any(marker in lowered for marker in _AUTH_ERROR_MARKERS)


def get_github_token_scopes(token: str) -> set[str]:
    """Return the OAuth scopes a GitHub token carries.

    A GitHub App token and a fine-grained token both report none, so an
    empty set means "can't tell from here", not "can't do anything".
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.headers.get("X-OAuth-Scopes") or ""
    except (urllib.error.URLError, OSError):
        return set()
    return {scope.strip() for scope in raw.split(",") if scope.strip()}


def get_github_username() -> str:
    """Return the user's GitHub login, or a placeholder if unavailable.

    The GitHub Container Registry authenticates on the token, so the
    username only has to be non-empty.
    """
    import calkit.github

    try:
        login = calkit.github.get("/user")["login"]
    except Exception:
        return "calkit"
    return str(login) if login else "calkit"


def prompt_for_packages_token() -> str | None:
    """Walk the user through creating a token that can push packages.

    Only reached once the tokens Calkit already holds have been refused.
    The one it uses for the GitHub API can usually push, since its GitHub
    App can be granted permission to write packages, so a token the user
    creates is what's left when that permission isn't there.
    """
    import webbrowser

    import typer

    typer.echo(
        "\nPushing to the GitHub Container Registry needs permission to "
        "write packages, which the token Calkit uses for the GitHub API "
        "was refused.\n\nOpening GitHub to create one with the "
        "'write:packages' scope already selected:\n"
        f"  {GITHUB_PACKAGES_TOKEN_URL}\n"
    )
    try:
        webbrowser.open(GITHUB_PACKAGES_TOKEN_URL)
    except Exception:
        pass
    entered: str = typer.prompt(
        "Paste the token here (input hidden)", hide_input=True, default=""
    )
    token = entered.strip()
    if not token:
        return None
    scopes = get_github_token_scopes(token)
    if scopes and "write:packages" not in scopes:
        typer.echo(
            "That token doesn't have the 'write:packages' scope; it has: "
            + (", ".join(sorted(scopes)) or "none")
        )
        return None
    return token


def save_packages_token(token: str) -> None:
    """Remember a token that can push packages, so this is a one-off."""
    from calkit import config

    cfg = config.read()
    cfg = config.Settings.model_validate(
        cfg.model_dump() | {"github_packages_token": token}
    )
    cfg.write()


def login_to_registry(
    ref: str, interactive: bool = False
) -> tuple[bool, str | None]:
    """Log in to a registry, reporting success and any new token to save.

    Only the GitHub Container Registry is handled, since that's the one
    Calkit has a path to credentials for. Anything else relies on the
    user's own ``docker login``.

    ``interactive`` asks the user for a token instead of trying the ones
    Calkit already holds. It's only reached once those have been tried and
    the push was still refused, so retrying them would just fail again.
    """
    host = ref.split("/", 1)[0]
    if host != "ghcr.io":
        return False, None
    import calkit

    from_prompt = False
    token: str | None = None
    if interactive:
        token = prompt_for_packages_token()
        from_prompt = token is not None
    else:
        stored = calkit.config.read().github_packages_token
        token = str(stored) if stored is not None else None
    if token is None and not interactive:
        # The token Calkit already holds is worth trying: its GitHub App can
        # be granted permission to write packages, as can the token GitHub
        # Actions provides, and neither reports any OAuth scope, so whether
        # one can push is only settled by pushing with it
        try:
            token = calkit.github.get_token()
        except Exception:
            token = None
    if not token:
        return False, None
    try:
        subprocess.run(
            [
                "docker",
                "login",
                host,
                "-u",
                get_github_username(),
                "--password-stdin",
            ],
            input=str(token).encode(),
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False, None
    return True, str(token) if from_prompt else None


def push_image_with_login(
    ref: str, interactive: bool = False
) -> tuple[bool, str]:
    """Push an image, sorting out registry credentials if it's refused.

    A token is only remembered once a push has actually gone through with
    it, since logging in succeeds with credentials that still can't push.
    """
    success, output = push_image(ref)
    if success or not is_auth_error(output):
        return success, output
    logged_in, _ = login_to_registry(ref)
    if logged_in:
        success, output = push_image(ref)
        if success or not is_auth_error(output):
            return success, output
    if not interactive:
        return success, output
    logged_in, new_token = login_to_registry(ref, interactive=True)
    if not logged_in:
        return success, output
    success, output = push_image(ref)
    if success and new_token is not None:
        save_packages_token(new_token)
    return success, output


def get_image_name(
    env: dict, env_name: str, wdir: str | None = None
) -> str | None:
    """Return the name of the image an environment uses.

    An environment that builds from a Dockerfile doesn't have to be told
    what to call its image: the project and environment it belongs to name
    it unambiguously, by the same convention its Jupyter kernel is named
    by. One defined purely by an image has to name it, since it's someone
    else's, so there's nothing to work out and None comes back.

    None also comes back for a project with nothing to be named after: no
    ``owner`` or ``name`` in ``calkit.yaml`` and no Git remote to read them
    from. The directory a project happens to sit in is not a name---moving
    or renaming it would rename the image, and every image built by every
    project called ``analysis`` would collide---so this is for the project
    to say rather than for Calkit to guess.
    """
    import calkit

    image: str | None = env.get("image")
    if image:
        return image
    if not env.get("path"):
        return None
    project: str | None
    try:
        project = calkit.detect_project_name(wdir=wdir)
    except ValueError:
        # A project that isn't published anywhere yet still names itself if
        # calkit.yaml says what it's called
        project = calkit.load_calkit_info(wdir=wdir).get("name")
        if not project:
            return None
    # Repository names must be lowercase, unlike tags
    return f"{project}.{env_name}".lower()


def get_pushable_images(wdir: str | None = None) -> dict[str, dict]:
    """Return the images a project builds that belong in a registry.

    Only environments built from the project's own Dockerfile are included:
    an environment named after an image someone else publishes already lives
    somewhere it can be pulled back from.
    """
    import calkit

    ck_info = calkit.load_calkit_info(wdir=wdir)
    resp = {}
    for env_name, env in (ck_info.get("environments") or {}).items():
        if not isinstance(env, dict) or env.get("kind") != "docker":
            continue
        if not env.get("path"):
            continue
        image = get_image_name(env, env_name, wdir=wdir)
        if not image:
            continue
        prefix = resolve_registry_prefix(env, wdir=wdir)
        if prefix is None:
            continue
        resp[env_name] = dict(
            env=env,
            image=image,
            remote_ref=get_remote_image_ref(image, prefix),
        )
    return resp
