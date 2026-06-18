"""Data models."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from calkit.models.iteration import Metric, ParametersType
from calkit.models.pipeline import Pipeline


class _ImportedFromProject(BaseModel):
    project: str
    path: str | None = None
    git_rev: str | None = None
    filter_paths: list[str] | None = None


class _ImportedFromUrl(BaseModel):
    url: str


class _CalkitObject(BaseModel):
    path: str
    title: str
    description: str | None = None
    stage: str | None = None


class Dataset(_CalkitObject):
    pass


class ImportedDataset(Dataset):
    imported_from: _ImportedFromProject | _ImportedFromUrl


class Figure(_CalkitObject):
    pass


class Result(_CalkitObject):
    pass


class Presentation(_CalkitObject):
    pass


class Publication(_CalkitObject):
    kind: Literal[
        "journal-article",
        "conference-paper",
        "proposal",
        "poster",
        "report",
        "blog",
    ]
    is_published: bool = False
    doi: str | None = None


class ReferenceFile(BaseModel):
    path: str
    key: str


class ReferenceCollection(BaseModel):
    path: str
    files: list[ReferenceFile] = []


class Environment(BaseModel):
    kind: Literal[
        "conda",
        "docker",
        "julia",
        "matlab",
        "nix",
        "pbs",
        "poetry",
        "npm",
        "yarn",
        "slurm",
        "ssh",
        "uv",
        "pixi",
        "venv",
        "uv-venv",
        "renv",
    ]
    # Note: ``path`` is declared on the specific subclasses that need it (most
    # of them, required; optional for Docker) rather than here, so subclasses
    # without a spec file (e.g. Matlab/Slurm/PBS) don't carry an unused field
    # and a required ``path`` doesn't conflict with the base's optional one.
    description: str | None = None


class CondaEnvironment(Environment):
    kind: Literal["conda"] = "conda"
    path: str
    prefix: str | None = None


class VenvEnvironment(Environment):
    kind: Literal["venv"] = "venv"
    path: str
    # If unset, the prefix is resolved on the fly (defaults to .venv next to
    # the spec file, nesting under .calkit/envs/{name}/.venv on conflict)
    prefix: str | None = None
    # Python version to use when creating the environment
    python: str | None = None


class UvEnvironment(Environment):
    kind: Literal["uv"] = "uv"
    path: str


class UvVenvEnvironment(Environment):
    kind: Literal["uv-venv"] = "uv-venv"
    path: str
    # If unset, the prefix is resolved on the fly (defaults to .venv next to
    # the spec file, nesting under .calkit/envs/{name}/.venv on conflict)
    prefix: str | None = None
    # Python version to use when creating the environment
    python: str | None = None


class PixiEnvironment(Environment):
    kind: Literal["pixi"] = "pixi"
    path: str
    name: str | None = None


class NixEnvironment(Environment):
    kind: Literal["nix"] = "nix"
    # Path to the project's flake.nix (required). The flake.lock alongside
    # it is the reproducibility-anchoring lock file we track as a DVC dep.
    path: str
    # Optional name of the dev shell to enter (passed as #<shell> to
    # ``nix develop``). Defaults to the flake's default dev shell.
    shell: str | None = None


class DockerEnvironment(Environment):
    kind: Literal["docker"] = "docker"
    # Docker environments can be defined purely by an image, so the path (to a
    # Dockerfile) is optional.
    path: str | None = None
    image: str
    layers: list[str] | None = None
    shell: Literal["bash", "sh"] = "sh"
    command_mode: Literal["shell", "entrypoint"] = "shell"
    platform: str | None = None
    # Working directory inside the container; defaults to ``/work`` at run time
    wdir: str | None = None
    # User to run the container as; defaults to the host user at run time
    user: str | None = None
    # Files added to the container as dependencies
    deps: list[str] | None = None
    # Environment variables to set in the container
    env_vars: dict[str, str] | None = None
    # Ports to expose, e.g. ``"8080:80"``
    ports: list[str] | None = None
    # GPUs to make available, passed to ``docker run --gpus``
    gpus: str | None = None
    # Extra arguments passed to ``docker run``
    args: list[str] | None = None
    # Name of the Jupyter kernel inside the image, used when executing
    # notebooks with ``calkit nb execute``; defaults to ``python3`` (or ``ir``
    # for R images)
    jupyter_kernel: str | None = None


class REnvironment(Environment):
    kind: Literal["renv"] = "renv"
    path: str
    prefix: str


class JuliaEnvironment(Environment):
    kind: Literal["julia"] = "julia"
    path: str
    julia: str


class MatlabEnvironment(Environment):
    kind: Literal["matlab"] = "matlab"
    version: str | None = None
    products: list[str] | None = None


class SlurmEnvironment(Environment):
    kind: Literal["slurm"] = "slurm"
    host: str = "localhost"
    default_options: list[str] | None = None
    default_setup: list[str] | None = None


class PBSEnvironment(Environment):
    kind: Literal["pbs"] = "pbs"
    host: str = "localhost"
    default_options: list[str] | None = None
    default_setup: list[str] | None = None


class SSHEnvironment(BaseModel):
    kind: Literal["ssh"] = "ssh"
    host: str
    user: str
    wdir: str
    key: str | None = None
    send_paths: list[str] = ["./*"]
    get_paths: list[str] = ["*"]
    description: str | None = None


class Software(BaseModel):
    title: str
    path: str
    description: str


class Notebook(_CalkitObject):
    """A Jupyter notebook."""

    pass


class ProcedureInput(BaseModel):
    """An input that might be entered while running a procedure.

    Attributes
    ----------
    name : str
        The name of the input. This will be displayed to the user at the
        prompt like 'Enter {name}:'. Note the column name for the log is the
        key used to identify this input, and they can be different.
    dtype : 'int', 'bool', 'str', or 'float'
        The datatype of the input.
    units : str
        Units of the input value.
    description : str
        Optional longer description of the input.
    """

    name: str | None = None
    dtype: Literal["int", "bool", "str", "float"] | None = None
    units: str | None = None
    description: str | None = None


class ProcedureStep(BaseModel):
    summary: str
    details: str | None = None
    cmd: str | None = None
    wait_before_s: float | None = None
    wait_after_s: float | None = None
    inputs: dict[str, ProcedureInput] | None = None


class Timedelta(BaseModel):
    days: float | None = None
    seconds: float | None = None
    microseconds: float | None = None
    milliseconds: float | None = None
    minutes: float | None = None
    hours: float | None = None
    weeks: float | None = None

    def to_py_timedelta(self) -> timedelta:
        return timedelta(**self.model_dump())


class Procedure(BaseModel):
    """A procedure, typically executed by a human."""

    title: str
    description: str
    steps: list[ProcedureStep]
    imported_from: str | None = None


class Release(BaseModel):
    kind: Literal[
        "project",
        "publication",
        "dataset",
        "figure",
        "presentation",
        "software",
        "model",
    ]
    path: str | None = None
    git_rev: str | None = None
    date: str | None = None
    publisher: str | None = None
    record_id: int | str | None = None
    doi: str | None = None
    url: str | None = None
    description: str | None = None
    # Internal releases are frozen, locally-stored snapshots that are not
    # published to an archival service, so they carry no publisher or DOI.
    internal: bool = False
    # Path (relative to the project root) to the renamed, self-describing copy
    # of the artifact kept within the release directory, e.g.
    # ".calkit/releases/v0/my-project-slides-v0.pdf". Only set for internal
    # releases, which store the artifact in the repo rather than ignoring it.
    stored_path: str | None = None


class ShowcaseFigure(BaseModel):
    figure: str


class ShowcaseText(BaseModel):
    text: str


class DerivedFromProject(BaseModel):
    project: str
    git_repo_url: str
    git_rev: str


class ProjectStatus(BaseModel):
    timestamp: datetime
    status: Literal["in-progress", "on-hold", "completed"]
    message: str | None = None


class FigureEvidence(BaseModel):
    """Evidence to back up the answer to a question."""

    kind: Literal["figure"] = "figure"
    path: str
    explanation: str | None = None


class ResultsEvidence(BaseModel):
    """Evidence in the form of a result."""

    kind: Literal["result"] = "result"
    path: str
    key: str | None = None
    explanation: str | None = None


class Question(BaseModel):
    """A question the project hopes to answer."""

    question: str
    hypothesis: str | None = None
    answer: str | None = None
    evidence: list[FigureEvidence | ResultsEvidence] | None = None


class Dependency(BaseModel):
    """A system-level dependency.

    Three kinds are supported:

    - ``app``: an executable that must be on ``PATH``.
    - ``env-var``: an environmental variable that must be defined.
    - ``setup``: a per-machine precondition that isn't a file -- e.g.,
      the user must have authenticated a CLI like ``gh auth login``.
      A ``setup`` dep declares ``check_command`` (a shell command whose
      exit code determines whether the dep is satisfied) and
      ``setup_command`` (run on a TTY when the user agrees, or printed
      as a fix-it command otherwise). To run either inside a project
      environment, prefix it with ``calkit xenv -n <env> --`` explicitly
      rather than relying on an implicit wrap. A future ``cache_ttl``
      field can extend this to skip re-probing for slow checks.
    """

    kind: Literal["app", "env-var", "setup"] = "app"
    name: str
    # ``setup``-kind fields; ignored for other kinds.
    check_command: str | None = None
    setup_command: str | None = None
    # ``cache_ttl`` is a duration string ('30m', '1h', '7d', '1w') or an
    # integer number of seconds. Setup deps cache successful checks by
    # default for ``DEFAULT_SETUP_CACHE_TTL``; set ``cache_ttl: 0`` to
    # disable caching and re-probe every run.
    cache_ttl: str | int | None = None
    description: str | None = None
    # Allow a per-env-var default value to be set (used by ``check env-vars``).
    default: str | None = None


class ProjectInfo(BaseModel):
    """All of the project's information or metadata, written to the
    ``calkit.yaml`` file.

    Attributes
    ----------
    parent : str
        The project's parent project, if applicable. This should be set if
        the project was created as a copy of another. This is similar to the
        concept of forking, but unlike a fork, a child project's changes
        are not meant to be merged back into the parent.
        The format of this field should be something like
        {owner_name}/{project_name}, e.g., 'someuser/some-project-name'.
        Note that individual objects can be imported from other projects, but
        that doesn't necessarily make them parent projects.
        This is probably not that important of a distinction.
        The real use case is being able to trace where things came from and
        distinguish what has been newly created here.
    """

    title: str | None = None
    owner: str | None = None
    description: str | None = None
    name: str | None = None
    git_repo_url: str | None = None
    derived_from: DerivedFromProject | None = None
    questions: list[str | Question] = []
    dependencies: list[str | dict[str, str] | Dependency] = []
    parameters: ParametersType | None = None
    metrics: dict[str, Metric] | None = None
    pipeline: Pipeline | None = None
    datasets: list[Dataset] = []
    figures: list[Figure] = []
    results: list[Result] = []
    publications: list[Publication] = []
    presentations: list[Presentation] = []
    references: list[ReferenceCollection] = []
    environments: dict[
        str,
        # The specific subclasses must precede the catch-all Environment so a
        # dict that validates against both (e.g. a prefix-less uv-venv, whose
        # only fields are kind and path) resolves to the specific subclass.
        # All path-bearing subclasses must be listed; otherwise such an env
        # falls back to the catch-all Environment (which has no ``path``).
        CondaEnvironment
        | DockerEnvironment
        | JuliaEnvironment
        | MatlabEnvironment
        | PixiEnvironment
        | REnvironment
        | SlurmEnvironment
        | PBSEnvironment
        | VenvEnvironment
        | UvEnvironment
        | UvVenvEnvironment
        | NixEnvironment
        | SSHEnvironment
        | Environment,
    ] = {}
    software: list[Software] = []
    notebooks: list[Notebook] = []
    procedures: dict[str, Procedure] = {}
    releases: dict[str, Release] = {}
    showcase: list[ShowcaseFigure | ShowcaseText] | None = None
