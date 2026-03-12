"""Models for environments."""

from typing import Literal

from pydantic import BaseModel


class Environment(BaseModel):
    kind: Literal[
        "conda",
        "docker",
        "poetry",
        "npm",
        "yarn",
        "ssh",
        "uv",
        "pixi",
        "venv",
        "uv-venv",
        "renv",
    ]
    path: str | None = None
    description: str | None = None
    stage: str | None = None
    default: bool | None = None


class CondaEnvironment(Environment):
    kind: Literal["conda"] = "conda"
    prefix: str | None = None


class VenvEnvironment(Environment):
    kind: Literal["venv"] = "venv"
    prefix: str


class UvVenvEnvironment(Environment):
    kind: Literal["uv-venv"] = "uv-venv"
    prefix: str


class PixiEnvironment(Environment):
    kind: Literal["pixi"] = "pixi"
    name: str | None = None


class DockerEnvironment(Environment):
    kind: Literal["docker"] = "docker"
    image: str
    layers: list[str] | None = None
    shell: Literal["bash", "sh"] = "sh"
    platform: str | None = None


class REnvironment(Environment):
    kind: Literal["renv"] = "renv"
    prefix: str


class SSHEnvironment(BaseModel):
    kind: Literal["ssh"] = "ssh"
    host: str
    user: str
    wdir: str
    key: str | None = None
    send_paths: list[str] = ["./*"]
    get_paths: list[str] = ["*"]


class CurrentSystemEnvironment(Environment):
    """An environment the represents the current system where Calkit is being
    run.

    This is useful for ensuring all pipeline stages are run on the same system,
    e.g., for benchmarking. The properties saved in the lock file can be
    controlled with the `properties` field, which can then ensure that stage
    outputs cached will be invalidated if any of those properties change.

    Application versions can be rounded by... TODO.
    """

    kind: Literal["current-system"] = "current-system"
    properties: (
        list[
            Literal[
                "hostname",
                "n_cpus",
                "calkit_version",
                "uv_version",
                "docker_version",
            ]
        ]
        | None
    ) = None
