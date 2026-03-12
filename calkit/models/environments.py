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
