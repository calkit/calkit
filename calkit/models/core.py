"""Data models."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from calkit.calc import CalculationType
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
    path: str = Field(
        description="Path to the file, relative to the project root."
    )
    title: str = Field(description="A human-readable title.")
    description: str | None = Field(
        default=None, description="A longer description."
    )
    stage: str | None = Field(
        default=None,
        description="Name of the pipeline stage that produces this.",
    )


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
    # Optional since publications can be created without one, e.g., by
    # ``calkit overleaf sync``, whose ``--kind`` option has no default
    kind: (
        Literal[
            "journal-article",
            "conference-paper",
            "proposal",
            "poster",
            "report",
            "blog",
        ]
        | None
    ) = None
    is_published: bool = False
    doi: str | None = None


class ReferenceFile(BaseModel):
    path: str
    key: str


class ReferenceCollection(BaseModel):
    path: str
    files: list[ReferenceFile] = []


class IncludedEnvironment(BaseModel):
    """An environment whose specification lives in another file.

    This variant covers entries that carry only an ``_include`` key, i.e.,
    with no ``kind`` declared inline.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    include: str = Field(
        alias="_include",
        description=(
            "Path to a YAML file whose contents are merged into this "
            "environment's definition."
        ),
    )


class Environment(BaseModel):
    """Base class for environments, which is never used directly.

    Environments are always one of the ``kind``-specific subclasses below;
    this only holds the fields they all share.
    """

    # Extra keys are forbidden so typo'd field names are reported instead of
    # silently ignored, both at runtime and by editors using the JSON schema.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    kind: Literal[
        "conda",
        "docker",
        "julia",
        "matlab",
        "nix",
        "pbs",
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
    description: str | None = Field(
        default=None, description="A description of the environment."
    )
    include: str | None = Field(
        default=None,
        alias="_include",
        description=(
            "Path to a YAML file whose contents are merged into this "
            "environment's definition."
        ),
    )


class CondaEnvironment(Environment):
    kind: Literal["conda"] = "conda"
    path: str = Field(description="Path to the Conda environment YAML file.")
    prefix: str | None = Field(
        default=None, description="Path at which to create the environment."
    )


class VenvEnvironment(Environment):
    kind: Literal["venv"] = "venv"
    path: str = Field(
        description="Path to the requirements file, e.g., requirements.txt."
    )
    prefix: str | None = Field(
        default=None,
        description=(
            "Path at which to create the environment. If unset, this is "
            "resolved on the fly, defaulting to .venv next to the spec file, "
            "nesting under .calkit/envs/{name}/.venv on conflict."
        ),
    )
    python: str | None = Field(
        default=None,
        description="Python version to use when creating the environment.",
    )


class UvEnvironment(Environment):
    kind: Literal["uv"] = "uv"
    path: str = Field(description="Path to the uv project's pyproject.toml.")


class UvVenvEnvironment(Environment):
    kind: Literal["uv-venv"] = "uv-venv"
    path: str = Field(
        description="Path to the requirements file, e.g., requirements.txt."
    )
    prefix: str | None = Field(
        default=None,
        description=(
            "Path at which to create the environment. If unset, this is "
            "resolved on the fly, defaulting to .venv next to the spec file, "
            "nesting under .calkit/envs/{name}/.venv on conflict."
        ),
    )
    python: str | None = Field(
        default=None,
        description="Python version to use when creating the environment.",
    )


class PixiEnvironment(Environment):
    kind: Literal["pixi"] = "pixi"
    path: str = Field(description="Path to the Pixi manifest file.")
    name: str | None = Field(
        default=None,
        description="Name of the environment within the Pixi manifest.",
    )


class NixEnvironment(Environment):
    kind: Literal["nix"] = "nix"
    path: str = Field(
        description=(
            "Path to the project's flake.nix. The flake.lock alongside it is "
            "the reproducibility-anchoring lock file tracked as a DVC "
            "dependency."
        )
    )
    shell: str | None = Field(
        default=None,
        description=(
            "Name of the dev shell to enter, passed as #<shell> to "
            "'nix develop'. Defaults to the flake's default dev shell."
        ),
    )


class DockerEnvironment(Environment):
    kind: Literal["docker"] = "docker"
    path: str | None = Field(
        default=None,
        description=(
            "Path to the Dockerfile. Optional, since Docker environments can "
            "be defined purely by an image."
        ),
    )
    image: str = Field(description="Name of the Docker image.")
    layers: list[str] | None = Field(
        default=None,
        description="Predefined layers to add to the generated Dockerfile.",
    )
    shell: Literal["bash", "sh"] = Field(
        default="sh", description="Shell used to run commands in the image."
    )
    command_mode: Literal["shell", "entrypoint"] = Field(
        default="shell",
        description="Whether commands run through a shell or the image's "
        "entrypoint.",
    )
    platform: str | None = Field(
        default=None, description="Platform to run as, e.g., 'linux/amd64'."
    )
    wdir: str | None = Field(
        default=None,
        description="Working directory inside the container. Defaults to "
        "'/work'.",
    )
    user: str | None = Field(
        default=None,
        description="User to run the container as. Defaults to the host user.",
    )
    deps: list[str] | None = Field(
        default=None,
        description="Files added to the container as dependencies.",
    )
    env_vars: dict[str, str] | None = Field(
        default=None,
        description="Environmental variables to set in the container.",
    )
    ports: list[str] | None = Field(
        default=None, description="Ports to expose, e.g., '8080:80'."
    )
    gpus: str | None = Field(
        default=None,
        description="GPUs to make available, passed to 'docker run --gpus'.",
    )
    args: list[str] | None = Field(
        default=None, description="Extra arguments passed to 'docker run'."
    )
    jupyter_kernel: str | None = Field(
        default=None,
        description=(
            "Name of the Jupyter kernel inside the image, used when executing "
            "notebooks with 'calkit nb execute'. Defaults to 'python3', or "
            "'ir' for R images."
        ),
    )


class REnvironment(Environment):
    kind: Literal["renv"] = "renv"
    path: str = Field(description="Path to the renv lock file.")
    prefix: str = Field(description="Path at which to create the environment.")


class JuliaEnvironment(Environment):
    kind: Literal["julia"] = "julia"
    path: str = Field(description="Path to the Julia project's Project.toml.")
    julia: str = Field(description="Julia version to use.")


class MatlabEnvironment(Environment):
    kind: Literal["matlab"] = "matlab"
    version: str | None = Field(
        default=None, description="MATLAB version to use."
    )
    products: list[str] | None = Field(
        default=None, description="MATLAB products (toolboxes) required."
    )


class SlurmEnvironment(Environment):
    kind: Literal["slurm"] = "slurm"
    host: str = Field(
        default="localhost",
        description="Host on which to submit jobs, over SSH if not localhost.",
    )
    default_options: list[str] | None = Field(
        default=None, description="Options passed to sbatch by default."
    )
    default_setup: list[str] | None = Field(
        default=None,
        description="Commands run at the start of every job script.",
    )


class PBSEnvironment(Environment):
    kind: Literal["pbs"] = "pbs"
    host: str = Field(
        default="localhost",
        description="Host on which to submit jobs, over SSH if not localhost.",
    )
    default_options: list[str] | None = Field(
        default=None, description="Options passed to qsub by default."
    )
    default_setup: list[str] | None = Field(
        default=None,
        description="Commands run at the start of every job script.",
    )


class SSHEnvironment(Environment):
    kind: Literal["ssh"] = "ssh"
    host: str = Field(description="Host to connect to.")
    user: str = Field(description="User to connect as.")
    wdir: str = Field(description="Working directory on the remote host.")
    key: str | None = Field(
        default=None, description="Path to the SSH private key to use."
    )
    send_paths: list[str] = Field(
        default=["./*"], description="Paths sent to the remote host."
    )
    get_paths: list[str] = Field(
        default=["*"], description="Paths fetched back from the remote host."
    )


class Software(BaseModel):
    title: str
    path: str
    description: str


class Notebook(BaseModel):
    """A Jupyter notebook.

    Unlike the other objects, a notebook entry can be created just to record
    which environment it runs in (by ``calkit update notebook-env``), so
    ``title`` is optional here.
    """

    path: str
    title: str | None = None
    description: str | None = None
    stage: str | None = None
    environment: str | None = Field(
        default=None,
        description="Name of the environment in which to run this notebook, "
        "if it is not part of the pipeline.",
    )


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
    # Version of Calkit that created the release, for reproducibility.
    calkit_version: str | None = None
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


class ShowcaseMarkdown(BaseModel):
    markdown: str


class ShowcasePublication(BaseModel):
    publication: str


class Subproject(BaseModel):
    """A smaller project executed as part of this one."""

    path: str = Field(
        description="Path to the subproject directory, relative to this "
        "project's root."
    )
    description: str | None = None


class OverleafSync(BaseModel):
    """Configuration for syncing a directory with an Overleaf project."""

    url: str | None = Field(
        default=None, description="URL of the Overleaf project."
    )
    sync_paths: list[str] | None = Field(
        default=None,
        description="Paths synced in both directions with Overleaf.",
    )
    push_paths: list[str] | None = Field(
        default=None,
        description="Paths only pushed to Overleaf, never pulled back.",
    )


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


class PublicationEvidence(BaseModel):
    """Evidence in the form of a publication."""

    kind: Literal["publication"] = "publication"
    path: str
    explanation: str | None = None


class Question(BaseModel):
    """A question the project hopes to answer."""

    question: str
    hypothesis: str | None = None
    answer: str | None = None
    evidence: (
        list[FigureEvidence | ResultsEvidence | PublicationEvidence] | None
    ) = None


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

    This model is the source of truth for the published JSON schema, so every
    key that can validly appear in ``calkit.yaml`` must be declared here.
    Extra keys are rejected, which is what lets editors flag typos.
    """

    # Extra keys are forbidden so a misspelled top-level key is reported
    # rather than silently ignored.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_: str | None = Field(
        default=None,
        alias="$schema",
        description="URL of the JSON schema describing this file.",
    )
    title: str | None = Field(
        default=None, description="A human-readable title for the project."
    )
    owner: str | None = Field(
        default=None,
        description="The account name that owns the project on Calkit Cloud.",
    )
    description: str | None = Field(
        default=None, description="A short description of the project."
    )
    name: str | None = Field(
        default=None,
        description="The project's name on Calkit Cloud, e.g., 'my-project'.",
    )
    git_repo_url: str | None = Field(
        default=None, description="URL of the project's Git repository."
    )
    derived_from: DerivedFromProject | None = Field(
        default=None,
        description="The project this one was created as a copy of.",
    )
    questions: list[str | Question] = Field(
        default=[], description="Questions the project seeks to answer."
    )
    dependencies: list[str | dict[str, str] | Dependency] = Field(
        default=[],
        description=(
            "System-level dependencies: applications that must be on PATH, "
            "environmental variables, or per-machine setup steps."
        ),
    )
    parameters: ParametersType | None = Field(
        default=None,
        description="Project-level parameters, which can be referenced from "
        "pipeline stages.",
    )
    metrics: dict[str, Metric] | None = Field(
        default=None, description="Metrics the project tracks."
    )
    pipeline: Pipeline | None = Field(
        default=None, description="The project's reproducible pipeline."
    )
    datasets: list[Dataset] = Field(
        default=[], description="The project's datasets."
    )
    figures: list[Figure] = Field(
        default=[], description="The project's figures."
    )
    results: list[Result] = Field(
        default=[],
        description="Files holding the project's important values.",
    )
    publications: list[Publication] = Field(
        default=[],
        description="The project's papers, posters, reports, and proposals.",
    )
    presentations: list[Presentation] = Field(
        default=[], description="The project's slides and posters."
    )
    references: list[ReferenceCollection] = Field(
        default=[], description="The project's bibliographies."
    )
    environments: dict[
        str,
        # Note the union is closed, i.e., there is no catch-all variant, so an
        # environment that matches no kind-specific class is reported as an
        # error instead of silently validating with its fields dropped.
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
        | IncludedEnvironment,
    ] = Field(
        default={},
        description="Environments in which pipeline stages are run, keyed by "
        "name.",
    )
    software: list[Software] = Field(
        default=[], description="Software created as part of the project."
    )
    notebooks: list[Notebook] = Field(
        default=[], description="The project's Jupyter notebooks."
    )
    procedures: dict[str, Procedure] = Field(
        default={},
        description="Procedures, typically executed by a human, keyed by "
        "name.",
    )
    releases: dict[str, Release] = Field(
        default={},
        description="Published or archived snapshots, keyed by name.",
    )
    showcase: (
        list[
            ShowcaseFigure
            | ShowcaseText
            | ShowcaseMarkdown
            | ShowcasePublication
        ]
        | None
    ) = Field(
        default=None,
        description="Elements that best represent the project, shown on its "
        "Calkit Cloud homepage.",
    )
    subprojects: list[Subproject] = Field(
        default=[],
        description="Smaller projects executed as part of this one.",
    )
    calculations: dict[str, CalculationType] = Field(
        default={},
        description="Calculations that can be run with 'calkit calc run'.",
    )
    env_vars: dict[str, str] = Field(
        default={},
        description="Environmental variables set when running project "
        "commands.",
    )
    overleaf_sync: dict[str, OverleafSync] = Field(
        default={},
        description="Overleaf sync configuration, keyed by the path of the "
        "synced directory.",
    )
