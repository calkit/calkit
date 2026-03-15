"""Functionality for working with Docker."""

from __future__ import annotations

import os
import shlex
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
    return image.split("@", 1)[0].split(":", 1)[0].lower()


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
        if token.startswith("--user="):
            idx += 1
            continue
        if token.startswith("-"):
            return None
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
        stage_name = f"mermaid-{Path(detected_inputs[0]).stem}".replace(
            "_", "-"
        ).lower()
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
    inner_command = parsed.get("command", [])
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
    command_mode = (
        "entrypoint" if _uses_entrypoint_command_mode(image) else "shell"
    )
    env: dict = {
        "kind": "docker",
        "image": image,
        "description": f"Docker CLI via image {image}.",
        "wdir": parsed["workdir"] or "/work",
        "command_mode": command_mode,
    }
    return env_name, env
