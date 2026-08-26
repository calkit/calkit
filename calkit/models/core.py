"""Data models."""

from __future__ import annotations

import posixpath
import re
from datetime import date as date_type
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    computed_field,
    field_validator,
    model_validator,
)
from typing_extensions import Annotated

from calkit.calc import CalculationType
from calkit.models.iteration import ParametersType
from calkit.models.pipeline import Pipeline


class _ImportedFromProject(BaseModel):
    project: str
    path: str | None = None
    git_rev: str | None = None
    filter_paths: list[str] | None = None


class _ImportedFromUrl(BaseModel):
    url: str
    date: date_type | None = Field(
        default=None,
        description=(
            "When the data was downloaded. Optional: without it, the commit "
            "that added this entry says when, to within a commit."
        ),
    )


class _ImportedFromDoi(BaseModel):
    """Data published under a DOI, which is a citation, not just a link.

    Kept apart from a URL so it can be cited and resolved as a DOI rather
    than being one more address that happens to start with https.
    """

    doi: str = Field(
        description=(
            "The DOI, e.g. 10.5281/zenodo.1234567. A https://doi.org/ or "
            "doi: prefix is accepted and stripped."
        )
    )
    date: date_type | None = Field(
        default=None, description="When the data was downloaded."
    )

    @field_validator("doi")
    @classmethod
    def _normalize_doi(cls, v: str) -> str:
        # Stored bare, so citing it and resolving it both start from one
        # form. Anything that isn't a DOI is refused rather than kept as a
        # string that merely sits under the ``doi`` key: that would make the
        # entry look citable when it isn't.
        bare = re.sub(
            r"^(https?://(dx\.)?doi\.org/|doi:)",
            "",
            v.strip(),
            flags=re.IGNORECASE,
        )
        if not re.fullmatch(r"10\.\d{4,9}/\S+", bare):
            raise ValueError(
                f"doi must look like 10.5281/zenodo.1234567 (got {v!r})"
            )
        return bare


class _GitSource(BaseModel):
    repo_url: str = Field(
        description="Clone URL of the repo the data came from."
    )
    rev: str | None = Field(
        default=None,
        description=(
            "The commit hash the file actually came from, filled in by "
            "'calkit import path' and 'calkit update path'. A branch or "
            "tag would move, so this is what makes the entry say which "
            "bytes are here. Optional only so an entry can be written by "
            "hand before anything has been fetched."
        ),
    )
    path: str | None = Field(
        default=None,
        description="Path within that repo, if it isn't the whole thing.",
    )
    ref: str | None = Field(
        default=None,
        description=(
            "Branch, tag, or commit to follow when refreshing this, e.g., "
            "'main'. 'rev' still records the commit actually fetched, so "
            "the entry says both what it tracks and what it got. Without "
            "it, refreshing follows the repo's default branch."
        ),
    )

    @field_validator("rev")
    @classmethod
    def _check_rev_is_a_hash(cls, v: str | None) -> str | None:
        # Abbreviated hashes are fine -- Git resolves them -- but a name is
        # not a revision, and accepting one here would quietly make the
        # import irreproducible. A branch belongs in 'ref', which is where
        # something that moves is meant to be written.
        if v is None:
            return v
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", v):
            raise ValueError(
                f"rev must be a commit hash, not a branch or tag (got {v!r}); "
                "a branch or tag to follow goes in 'ref'"
            )
        return v


class _ImportedFromGit(BaseModel):
    """Data from a Git repo that isn't a Calkit project."""

    git: _GitSource
    date: date_type | None = Field(
        default=None, description="When the data was downloaded."
    )


class _Person(BaseModel):
    """A person credited with producing something in the project.

    Extra keys are refused rather than ignored: a mistyped ``oricd``, or a
    ``with_ai`` on something that doesn't take one, should say so instead of
    vanishing and leaving the author thinking they recorded it.
    """

    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(
        default=None, description="Email address of the person."
    )
    name: str | None = Field(
        default=None, description="Their name, if worth recording here."
    )
    with_ai: str | list[str] | None = Field(
        default=None,
        description=(
            "Generative AI tools this person used, e.g. 'Claude Opus 5'. "
            "Recorded against the person rather than the file, so a "
            "disclosure can't exist without someone answering for it."
        ),
    )
    orcid: str | None = Field(
        default=None,
        description=(
            "Their ORCID, which identifies them globally rather than only "
            "within this project. Accepted bare or as a full URL."
        ),
    )

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        # A light check only: a full RFC 5322 parse refuses addresses that
        # get mail. What matters is that an empty or mangled value can't
        # count as identifying someone, which it would otherwise do here.
        if v is None:
            return v
        v = v.strip()
        local, at, domain = v.partition("@")
        if not (local and at and domain):
            raise ValueError(
                f"email must look like name@example.org (got {v!r})"
            )
        return v

    @field_validator("with_ai")
    @classmethod
    def _check_with_ai(
        cls, v: str | list[str] | None
    ) -> str | list[str] | None:
        # A disclosure that names nothing discloses nothing, and would read
        # to a later tool as "used AI, tool unknown". Omitting the key is
        # how to say no tool was used.
        if v is None:
            return v
        tools = [v] if isinstance(v, str) else v
        if not tools or any(not t.strip() for t in tools):
            raise ValueError(
                "with_ai names the tool(s) used, e.g. 'Claude Opus 5'; omit "
                "it if none were"
            )
        return v

    @field_validator("orcid")
    @classmethod
    def _normalize_orcid(cls, v: str | None) -> str | None:
        # Stored as the resolvable URL, which is the form CITATION.cff and
        # RO-Crate both want, so neither has to guess at a bare identifier.
        if v is None:
            return v
        match = re.fullmatch(
            r"(?:(?:https?://)?(?:www\.)?orcid\.org/)?"
            r"(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])",
            v.strip(),
        )
        if match is None:
            raise ValueError(
                f"orcid must look like 0000-0002-1825-0097 (got {v!r})"
            )
        bare = match.group(1).upper()
        # The last character is an ISO 7064 MOD 11-2 check digit over the
        # other 15, so a typo is caught here rather than by whoever later
        # finds the identifier resolves to a stranger, or to nobody.
        total = 0
        for digit in bare[:-1].replace("-", ""):
            total = (total + int(digit)) * 2
        result = (12 - total % 11) % 11
        expected = "X" if result == 10 else str(result)
        if bare[-1] != expected:
            raise ValueError(
                f"orcid {v!r} has check digit {bare[-1]} but its other "
                f"digits call for {expected}, so one of them is mistyped"
            )
        return f"https://orcid.org/{bare}"

    @model_validator(mode="after")
    def _check_identifiable(self) -> _Person:
        # A name alone doesn't say which of the several people with it this
        # is, so credit has to rest on something resolvable. Either one is
        # enough, and an ORCID is the better of the two.
        if self.email is None and self.orcid is None:
            raise ValueError("A person needs an email or an ORCID, or both")
        return self


class _CalkitObject(BaseModel):
    path: str = Field(
        description="Path to the file, relative to the project root."
    )
    title: str | None = Field(
        default=None, description="A human-readable title."
    )
    description: str | None = Field(
        default=None, description="A longer description."
    )
    stage: str | None = Field(
        default=None,
        description="Name of the pipeline stage that produces this.",
    )


# Every place an artifact can have come from. One union shared by every
# artifact that can be imported, so they all accept the same forms.
ImportedFromType = (
    _ImportedFromProject
    | _ImportedFromUrl
    | _ImportedFromDoi
    | _ImportedFromGit
)

_IMPORTED_FROM_DESCRIPTION = "Where this came from, if imported."


def _exclusive_with_imported_from(made_key: str) -> dict:
    """JSON schema refusing ``imported_from`` together with ``made_key``.

    Mirrors the model validator, so the published schema doesn't advertise
    a combination the validator then rejects. Both keys have to be present
    and non-null to trip it, which is what the validator checks too: a key
    written as ``null`` is the same as one left out.
    """
    return {
        "not": {
            "required": ["imported_from", made_key],
            "properties": {
                "imported_from": {"type": "object"},
                made_key: {"type": ["object", "array"]},
            },
        }
    }


def _refuse_empty_people(key: str, v: object) -> object:
    # An empty list claims nobody, which isn't the same as saying nothing:
    # it would count as provenance while naming no one. Leave the key out
    # instead, or name at least one person.
    if isinstance(v, list) and not v:
        raise ValueError(
            f"{key} cannot be an empty list; omit it or name at least one "
            "person"
        )
    return v


class _AuthoredArtifact(_CalkitObject):
    """An artifact that may need attributing to whoever produced it.

    What's recorded here is a claim, not proof of one: calkit.yaml is
    hand-authored, so nothing in it is verified by having been written down.
    That's worth being explicit about wherever it's shown to a reader, and
    it's why hashes and signatures aren't among these fields -- they'd read
    as evidence while being just as hand-authored as the rest.

    Something made here can equally have been obtained from elsewhere, so
    every artifact that can be attributed takes the same ``imported_from``
    forms, and the two are exclusive: made here or got from there, not both.
    """

    model_config = ConfigDict(
        json_schema_extra=_exclusive_with_imported_from("created_by")
    )
    created_by: _Person | list[_Person] | None = Field(
        default=None,
        description=(
            "Who created this primary artifact here, e.g., collected or "
            "measured the data, drew the figure, or took the photo, rather "
            "than it being produced by the pipeline or obtained from "
            "elsewhere. A primary artifact has no upstream source to point "
            "at, so naming who produced it is the only way to tell it apart "
            "from one whose provenance was never recorded. Each person "
            "discloses the generative AI tools they used via ``with_ai``."
        ),
    )
    imported_from: ImportedFromType | None = Field(
        default=None, description=_IMPORTED_FROM_DESCRIPTION
    )

    @field_validator("created_by", mode="before")
    @classmethod
    def _check_created_by(cls, v: object) -> object:
        return _refuse_empty_people("created_by", v)

    @model_validator(mode="after")
    def _check_not_both_made_and_imported(self) -> _AuthoredArtifact:
        # Something is either what you produced or what you got; an entry
        # claiming both has one of the two wrong.
        if self.created_by is not None and self.imported_from is not None:
            raise ValueError(
                "An artifact made here cannot also be imported from elsewhere"
            )
        return self


class Dataset(_AuthoredArtifact):
    """A dataset, whether computed, collected here, or obtained elsewhere.

    Data someone collected or measured for this project is a primary
    artifact, and ``created_by`` names them, since there is nothing
    upstream to point at. Data from elsewhere records ``imported_from``.
    """


class ImportedDataset(Dataset):
    """A dataset known to have been imported, so ``imported_from`` is required.

    Otherwise the same as ``Dataset``, which already takes ``imported_from``
    and refuses a malformed one. ``ProjectInfo`` validates every dataset as
    a ``Dataset``; this is for callers holding one they know was imported
    and wanting that checked, e.g., the hub's create-dataset route.

    Required through a validator rather than by redeclaring the field
    without a default, which type checkers reject as an override that drops
    the parent's default.
    """

    @model_validator(mode="after")
    def _require_imported_from(self) -> ImportedDataset:
        if self.imported_from is None:
            raise ValueError("An imported dataset must say where it came from")
        return self


class MiscArtifact(_AuthoredArtifact):
    """A path worth attributing that isn't one of the typed artifacts.

    Most files in a project are neither a dataset nor a figure nor a paper:
    a photograph, a slide someone drew, a config a colleague sent over. They
    still have an origin, and without somewhere to record it the honest
    answer is missing rather than merely absent.
    """


class Figure(_AuthoredArtifact):
    """A figure, usually produced by a pipeline stage.

    Carries attribution for the ones that aren't: a schematic drawn by hand
    or laid out with a generative AI tool has no stage to point at, and is
    exactly the kind of thing a reader wants told. One obtained from
    elsewhere records ``imported_from`` instead, like a dataset does.
    """


class Result(_CalkitObject):
    """A finding the project produced: a value, a table, a map, or a file.

    Like the other artifacts, a result is identified by its path, but unlike
    them several results can share one file, e.g., a mean and a standard
    deviation both read out of one summary file. ``key`` is what tells those
    apart, so the identity is really the ``(path, key)`` pair. Which part of
    a file a result refers to is left open on purpose: other forms of
    addressing can be added without reshaping what a result is.
    """

    key: str | None = Field(
        default=None,
        description="Which value within the file this result refers to, "
        "e.g., 'metrics.mean'. Omit it when the result is the whole file.",
    )
    name: str | None = Field(
        default=None,
        description="A short handle for referring to this result, which "
        "stays stable if the file is renamed. Optional, since the path and "
        "key already identify it.",
    )


class Table(_CalkitObject):
    """Tabular data, whether it's the finding itself or how one is shown.

    Identified by path, like the other artifacts, and cited that way.

    Declaring one is optional: evidence says what it points at inline via
    ``kind``, so an entry here is only needed when the table is worth a title
    and a description of its own.

    Deliberately nothing beyond the shared artifact fields yet. A ``name``,
    for referring to a table symbolically, and ``columns`` both want to exist
    eventually, but neither has anything reading it today, and columns need
    per-column types and units that belong with symbol metadata rather than
    being invented separately here. Both are free to add later; a field
    shipped early is not free to remove.
    """


class Presentation(_CalkitObject):
    kind: Literal["slides", "poster"] | None = Field(
        default=None, description="What kind of presentation this is."
    )


class Publication(_CalkitObject):
    """A publication the project produced, or one it builds upon.

    Whether it has been published is not written down but derived: a
    publication of record has a DOI, so ``is_published`` is true exactly
    when ``doi`` is set, and reads the same on the hub and in the CLI.
    """

    # Note posters are presentations, not publications, since they are
    # presented rather than published, and carry no DOI or venue of record.
    # Optional since publications can be created without a kind, e.g., by
    # ``calkit overleaf sync``, whose ``--kind`` option has no default.
    kind: (
        Literal[
            "journal-article",
            "conference-paper",
            "proposal",
            "report",
            "blog",
            "book",
            "thesis",
            "phd-thesis",
        ]
        | None
    ) = None
    doi: str | None = Field(
        default=None,
        description=(
            "This publication's own DOI, once it has one. Setting it is "
            "what marks the publication as published."
        ),
    )
    # Distinct from ``doi`` above, which is this publication's own: a paper
    # pulled in from an archive to be cited or built upon records where it
    # was got from here, the same way a dataset does.
    imported_from: ImportedFromType | None = Field(
        default=None, description=_IMPORTED_FROM_DESCRIPTION
    )

    @model_validator(mode="before")
    @classmethod
    def _drop_written_is_published(cls, data: object) -> object:
        # ``is_published`` used to be a plain field, so older calkit.yaml
        # files may still write it. It's accepted and dropped rather than
        # refused: extra keys are ignored by default anyway, and the
        # computed property below is the only reading of it. A written
        # ``true`` with no DOI isn't honored, since a claim with nothing
        # resolvable behind it is exactly what the derivation replaces.
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "is_published"}
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_published(self) -> bool:
        return self.doi is not None


class ReferenceFile(BaseModel):
    path: str
    key: str


class ReferenceCollection(BaseModel):
    path: str
    files: list[ReferenceFile] = []


class RequirementAttrs(BaseModel):
    """A requirement's properties, as written under ``{name: {...}}``.

    ``Requirement`` is this plus the name; the mapping form supplies the
    name as its key instead.
    """

    kind: Literal["app", "env-var", "setup", "calkit-config"] = "app"
    check_command: str | None = None
    setup_command: str | None = None
    cache_ttl: str | int | None = None
    description: str | None = None
    default: str | None = None
    version_spec: str | None = None
    notes: str | None = None


class Requirement(BaseModel):
    """Something that must be true of a machine before the project runs.

    Four kinds are supported:

    - ``app``: an executable that must be on ``PATH``, optionally
      satisfying a ``version_spec``.
    - ``env-var``: an environmental variable that must be defined.
    - ``setup``: a per-machine precondition that isn't a file -- e.g.,
      the user must have authenticated a CLI like ``gh auth login``.
      A ``setup`` requirement declares ``check_command`` (a shell command
      whose exit code determines whether it is satisfied) and
      ``setup_command`` (run on a TTY when the user agrees, or printed
      as a fix-it command otherwise). To run either inside a project
      environment, prefix it with ``calkit xenv -n <env> --`` explicitly
      rather than relying on an implicit wrap. ``cache_ttl`` skips
      re-probing slow checks.
    - ``calkit-config``: a value that must be set in the user's Calkit
      configuration.

    These name a thing that must be present, so each has a ``name``. The
    properties of a machine that can't be installed -- how many CPUs it
    has, what OS it runs -- are constrained by
    :class:`SystemNumberRequirement` and :class:`SystemValueRequirement`
    instead, which name a property rather than a thing.
    """

    kind: Literal["app", "env-var", "setup", "calkit-config"] = "app"
    name: str
    # ``setup``-kind fields; ignored for other kinds.
    check_command: str | None = None
    setup_command: str | None = None
    # ``cache_ttl`` is a duration string ('30m', '1h', '7d', '1w') or an
    # integer number of seconds. Setup requirements cache successful checks
    # by default for ``DEFAULT_SETUP_CACHE_TTL``; set ``cache_ttl: 0`` to
    # disable caching and re-probe every run.
    cache_ttl: str | int | None = None
    description: str | None = None
    # Allow a per-env-var default value to be set (used by ``check env-vars``).
    default: str | None = None
    version_spec: str | None = Field(
        default=None,
        description="Version specifier an 'app' must satisfy, e.g. '>=2.40'. "
        "A string requirement like 'git>=2.40' is shorthand for this.",
    )
    notes: str | None = None


class SetupRequirement(Requirement):
    """A ``setup`` requirement, whose ``name`` may be omitted.

    A single anonymous setup step is common enough that requiring a name
    adds friction, so Calkit synthesizes a stable ``setup-<hash>`` one from
    ``check_command``. This is a separate model rather than a loosening of
    ``Requirement.name`` so the published schema still rejects an ``app``
    or ``env-var`` requirement with no name, where the name is the
    identity.
    """

    kind: Literal["setup"] = "setup"
    name: str | None = None


# Machine properties whose values are numbers, so they're constrained by
# range rather than by matching. Kebab-case like the rest of calkit.yaml;
# ``calkit.environments`` maps these onto the snake_case keys
# ``get_system_info`` returns.
SystemNumberProperty = Literal["cpu-count", "memory-gb"]

# Machine properties whose values are strings. ``*-version`` properties of
# installed tools are deliberately absent: those are reachable as an ``app``
# requirement with a ``version_spec``, which is one way to say it rather
# than two. ``python-version`` stays because it describes the interpreter
# running Calkit, which need not be whatever ``python`` resolves to.
SystemValueProperty = Literal[
    "os",
    "os-version",
    "platform",
    "machine",
    "processor",
    "hostname",
    "machine-id",
    "python-version",
    "python-implementation",
]


class SystemNumberRequirement(BaseModel):
    """A bound on a numeric property of the machine.

    A property is not a thing that can be installed, so there is nothing to
    name and nothing to offer to fix: the check either passes on this
    machine or reports what it found against what was asked for.

    At least one bound must be given. An entry that constrains nothing says
    nothing -- if the intent is 'results depend on this property', that is
    what a ``system`` environment's ``lock`` is for.
    """

    kind: SystemNumberProperty = Field(
        description="Which numeric property of the machine to constrain."
    )
    min: float | None = Field(
        default=None, description="Smallest acceptable value, inclusive."
    )
    max: float | None = Field(
        default=None, description="Largest acceptable value, inclusive."
    )
    description: str | None = None

    @model_validator(mode="after")
    def _check_bounded(self) -> SystemNumberRequirement:
        if self.min is None and self.max is None:
            raise ValueError(
                f"Requirement on '{self.kind}' needs a 'min' or a 'max'; "
                "to depend on its value rather than constrain it, add it to "
                "the environment's 'lock'"
            )
        if self.min is not None and self.max is not None:
            if self.min > self.max:
                raise ValueError(
                    f"Requirement on '{self.kind}' has min {self.min} greater "
                    f"than max {self.max}, which nothing can satisfy"
                )
        return self


class SystemValueRequirement(BaseModel):
    """A constraint on a string-valued property of the machine.

    ``equals`` matches exactly, case-insensitively, and a list of values
    means any of them will do. ``version_spec`` compares as a version, for
    properties like ``os-version`` and ``python-version`` where '>=' means
    something.

    At least one of the two must be given, for the same reason a numeric
    requirement needs a bound.
    """

    kind: SystemValueProperty = Field(
        description="Which property of the machine to constrain."
    )
    equals: str | list[str] | None = Field(
        default=None,
        description="Value the property must have, matched "
        "case-insensitively. A list means any one of them is acceptable.",
    )
    version_spec: str | None = Field(
        default=None,
        description="PEP 440 version specifier the property must satisfy, "
        "e.g. '>=3.11'. For properties that are versions.",
    )
    description: str | None = None

    @model_validator(mode="after")
    def _check_constrained(self) -> SystemValueRequirement:
        if self.equals is None and self.version_spec is None:
            raise ValueError(
                f"Requirement on '{self.kind}' needs an 'equals' or a "
                "'version_spec'; to depend on its value rather than "
                "constrain it, add it to the environment's 'lock'"
            )
        return self


# Every shape a requirement can be written in. The mapping form
# ``{name: {...}}`` comes last so a flat dict is matched as the object it
# looks like rather than as a one-key mapping.
RequirementType = (
    str
    | SystemNumberRequirement
    | SystemValueRequirement
    | SetupRequirement
    | Requirement
    | dict[str, RequirementAttrs | None]
)

# Pre-rename names, kept so existing imports keep working.
DependencyAttrs = RequirementAttrs
Dependency = Requirement
SetupDependency = SetupRequirement


class Environment(BaseModel):
    """Base class for environments, which is never used directly.

    Environments are always one of the ``kind``-specific subclasses below;
    this only holds the fields they all share.
    """

    # Extra keys are allowed for the same reason as on ProjectInfo: the set
    # of per-kind options is still growing. ``kind`` is still closed, so an
    # unknown kind is reported rather than silently accepted.
    model_config = ConfigDict(populate_by_name=True)
    kind: Literal[
        "conda",
        "docker",
        "julia",
        "matlab",
        "nix",
        "pbs",
        "slurm",
        "system",
        "uv",
        "pixi",
        "venv",
        "uv-venv",
        "renv",
    ] = Field(description="What kind of environment this is.")
    # Note: ``path`` is declared on the specific subclasses that need it (most
    # of them, required; optional for Docker) rather than here, so subclasses
    # without a spec file (e.g. Matlab/Slurm/PBS) don't carry an unused field
    # and a required ``path`` doesn't conflict with the base's optional one.
    description: str | None = Field(
        default=None, description="A description of the environment."
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
    inputs: list[str] | None = Field(
        default=None,
        # See the note on the other environments that take this field
        validation_alias=AliasChoices("inputs", "deps"),
        description="Files added to the container as dependencies. Their "
        "checksums are recorded in the environment's lock file, so editing "
        "one rebuilds the image and reruns the stages that use it.",
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
    path: str = Field(
        description="Path to the project's DESCRIPTION file. The renv lock "
        "file is created next to it."
    )
    prefix: str | None = Field(
        default=None, description="Path at which to create the environment."
    )


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
    inputs: list[str] | None = Field(
        default=None,
        # 'deps' is the name this was published under on Docker
        # environments, and extra keys on an environment are ignored rather
        # than refused, so a project still spelling it that way would
        # otherwise go silently untracked. Accepted, not documented: one
        # name for one thing.
        validation_alias=AliasChoices("inputs", "deps"),
        description="Files in the project that 'default_setup' reads, e.g., "
        "a setup script it sources. Added as an input to every stage using "
        "this environment, so editing one reruns them.",
    )
    max_concurrent_jobs: int | None = Field(
        default=None,
        ge=1,
        description="How many of this project's jobs may sit in the queue "
        "(running or pending) at once. Submissions beyond the limit wait for "
        "a slot, so an iterated stage does not flood a shared cluster's queue "
        "with every one of its jobs at the same time. Null means no limit.",
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
    inputs: list[str] | None = Field(
        default=None,
        # 'deps' is the name this was published under on Docker
        # environments, and extra keys on an environment are ignored rather
        # than refused, so a project still spelling it that way would
        # otherwise go silently untracked. Accepted, not documented: one
        # name for one thing.
        validation_alias=AliasChoices("inputs", "deps"),
        description="Files in the project that 'default_setup' reads, e.g., "
        "a setup script it sources. Added as an input to every stage using "
        "this environment, so editing one reruns them.",
    )
    max_concurrent_jobs: int | None = Field(
        default=None,
        ge=1,
        description="How many of this project's jobs may sit in the queue "
        "(running or pending) at once. Null means no limit.",
    )


# Properties of a machine that a ``system`` environment can pin. A closed set
# rather than any key from ``calkit describe system``, so editors can offer
# them and a typo is reported instead of silently locking nothing. Kebab-case
# like the rest of calkit.yaml; ``calkit.environments`` maps these onto the
# snake_case keys ``get_system_info`` returns.
SystemLockProperty = Literal[
    "os",
    "os-version",
    "platform",
    "machine",
    "processor",
    "hostname",
    "machine-id",
    "cpu-count",
    "memory-gb",
    "python-version",
    "python-implementation",
    "git-version",
    "docker-version",
    "conda-version",
    "mamba-version",
    "uv-version",
    "pixi-version",
    "julia-version",
    "juliaup-version",
    "rscript-version",
    "brew-version",
]


class SystemEnvironment(Environment):
    """The machine as it is, with nothing built, installed, or isolated.

    An escape hatch for software Calkit doesn't manage, e.g., a site-wide
    module system or a hand-built toolchain. Nothing is pinned by default,
    since opting out of isolation is the whole point of this kind, so
    ``lock`` is how a project says which properties of the machine its
    results actually depend on.

    Locked properties are written to the environment's lock file, which
    stages depend on, so moving to a machine where one of them differs
    invalidates the cached result rather than silently reusing it.

    ``requirements`` is the other half, and answers a different question.
    It says what must be *true* of this machine -- apps that must be
    installed, variables that must be set, at least this many CPUs -- and
    is checked before anything runs, on the machine the environment names.
    A requirement that fails stops the run and says how to fix it; a locked
    property that changes silently invalidates a cached result. One gates,
    the other pins, so a property that matters both ways is written in both
    places.

    ``default_setup`` is what has to be *done* on this machine before a
    stage can run: sourcing a site setup script, loading modules, putting a
    hand-built toolchain on the ``PATH``. It runs in the same shell as the
    stage's own command, so what it exports is what the stage sees, which
    is why it can't be a ``setup`` requirement -- those run in a shell of
    their own and are cached, since they check whether something has been
    done rather than doing it every time. It is recorded in the lock file
    for the same reason a SLURM env's is: changing how a build is set up
    changes what the build produces, so the stages that used it should
    rerun.

    ``host`` names the machine. SSH is how a machine is reached, not a kind
    of environment, so there is no separate ``ssh`` kind: a system env whose
    host isn't this machine is reached over SSH, and one whose host is this
    machine runs here, the same way a SLURM env does. The built-in
    ``_system`` environment is shorthand for this kind on ``localhost``
    with nothing locked.

    ``machine_id`` says *which* machine, where ``host`` only says what it
    answers to. Names are renamed, resolve differently from different
    networks, and are reused; a project that means one particular machine
    can name it here instead and have that survive all of it. It replaces
    the name in deciding whether this is that machine, and is checked again
    on the far end when it isn't -- so a host that has come to point at a
    different box is reported rather than run on. ``host`` is still what
    reaches it, so both are worth declaring for a machine that isn't this
    one. Run ``calkit describe system`` on a machine to read its ID.

    Declaring one says where to run, which is a separate question from
    whether results depend on the machine: moving a project to a new one
    and updating this need not invalidate everything computed on the old
    one. Whether it does is left to ``lock``, where ``machine-id`` is
    available for projects whose results really are machine-specific.

    ``wdir`` is the project's workspace on that host -- the directory the
    stage runs in. It defaults to
    ``~/.calkit/workspaces/<hub>/<owner>/<name>``, so a project that just
    names a host lands somewhere predictable rather than having to spell
    out a path that is the same on every machine anyway. Qualified by hub
    and owner because a host is shared, and hidden because transfers check
    out with ``--force``: a path that looks like the user's own checkout is
    one whose edits would be silently destroyed.

    What moves in and out of that workspace is deliberately not declared
    here. An environment doesn't know which files a stage reads, so a list
    kept alongside it can fall behind the pipeline and quietly run against
    stale inputs; the paths are taken from the stage instead.
    """

    kind: Literal["system"] = "system"
    host: str = Field(
        default="localhost",
        description="Host on which to run. Reached over SSH unless it names "
        "this machine.",
    )
    machine_id: str | None = Field(
        default=None,
        description="Stable identifier of the machine to run on, as "
        "reported by 'calkit describe system'. Decides whether this is "
        "that machine, in place of matching 'host' by name; 'host' is "
        "still how the machine is reached when it isn't this one. Says "
        "where to run, not that results depend on the machine; lock "
        "'machine-id' for that.",
    )
    user: str | None = Field(
        default=None,
        description="User to connect as. Left to SSH by default, which "
        "resolves it from ~/.ssh/config or falls back to the current user.",
    )
    ssh_key: str | None = Field(
        default=None,
        description="Path to the SSH private key used to reach another "
        "host. Left to SSH and its agent by default.",
    )
    wdir: str | None = Field(
        default=None,
        description="The project's workspace on the host, in which stages "
        "run. A relative path is taken from the connecting user's home "
        "directory. Defaults to '.calkit/workspaces/<hub>/<owner>/<name>'.",
    )
    default_setup: list[str] | None = Field(
        default=None,
        description="Commands run in the same shell, before every stage "
        "that uses this environment, e.g. 'module load cuda' or a site "
        "setup script that exports compiler paths. Recorded in the "
        "environment's lock file, so changing them reruns those stages.",
    )
    shell: Literal["sh", "bash", "zsh"] = Field(
        default="bash",
        description="Shell in which setup commands run, both "
        "'default_setup' and a stage's own 'setup', together with the "
        "stage's command. Defaults to bash, since 'source' is a bashism "
        "and sourcing a setup script is the usual reason to have setup "
        "commands. Ignored when there are none.",
    )
    inputs: list[str] | None = Field(
        default=None,
        # 'deps' is the name this was published under on Docker
        # environments, and extra keys on an environment are ignored rather
        # than refused, so a project still spelling it that way would
        # otherwise go silently untracked. Accepted, not documented: one
        # name for one thing.
        validation_alias=AliasChoices("inputs", "deps"),
        description="Files in the project that 'default_setup' reads, e.g., "
        "a setup script it sources. Added as an input to every stage using "
        "this environment, so editing one reruns them.",
    )
    lock: list[SystemLockProperty] = Field(
        default=[],
        description="Properties of the machine this environment's results "
        "depend on. Stages rerun when a locked property changes. Empty means "
        "nothing about the machine is pinned.",
    )
    requirements: list[RequirementType] = Field(
        default=[],
        description="What must be true of this machine before stages run on "
        "it: apps on PATH, environmental variables, setup steps, and "
        "constraints on properties like CPU count. Checked on the machine "
        "this environment names, which is not necessarily this one.",
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
    """A procedure, typically executed by a human, written out in full."""

    # Mirrors ``ProcedureFile``'s refusal of inline keys, so the published
    # schema rejects the combination the validator does
    model_config = ConfigDict(
        json_schema_extra={"not": {"required": ["path"]}}
    )
    title: str
    description: str
    steps: list[ProcedureStep]
    imported_from: str | None = None


class ProcedureFile(BaseModel):
    """A procedure kept in its own YAML or JSON file.

    The file holds what an inline ``Procedure`` would: ``title``,
    ``description``, and ``steps``. Nothing else can be given alongside
    ``path``, so a procedure is defined in one place, not split between
    calkit.yaml and the file it points at. ``calkit.procedures.load``
    resolves one of these to the ``Procedure`` it names.
    """

    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        description=(
            "Path to a YAML or JSON file holding the procedure, relative "
            "to the project root."
        )
    )

    @model_validator(mode="before")
    @classmethod
    def _refuse_inline_fields(cls, data: object) -> object:
        # Said here rather than left to the extra-keys error, since that
        # would read as if the inline keys were simply unknown
        if isinstance(data, dict):
            inline = sorted(set(data) & set(Procedure.model_fields))
            if inline:
                raise ValueError(
                    "A procedure is either a path to a file or written "
                    f"inline, not both (got path with {', '.join(inline)})"
                )
        return data


def _procedure_form(v: object) -> str:
    # Routes on the presence of ``path`` so the error for a bad entry comes
    # from the one model it was meant for, rather than from both
    if isinstance(v, dict):
        return "file" if "path" in v else "inline"
    return "file" if isinstance(v, ProcedureFile) else "inline"


# What an entry under ``procedures`` can be: the procedure itself, or a
# pointer to the file that holds it.
ProcedureEntry = Annotated[
    Annotated[ProcedureFile, Tag("file")]
    | Annotated[Procedure, Tag("inline")],
    Discriminator(_procedure_form),
]


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


class StaticHtmlApp(BaseModel):
    """An app served as static files, with no backend.

    ``path`` points at the HTML file itself rather than its directory, since
    the kind names a file type. The containing directory is the serving root,
    so sibling assets are served alongside it, and ``index.html`` is implied
    when a directory is served.

    There is no ``url`` field: for apps a hub serves, the URL is derived from
    the project and the app's key, and a value written here could only go
    stale.
    """

    kind: Literal["static-html"] = "static-html"
    path: str
    title: str | None = None
    description: str | None = None
    # The stage that produces this app, mirroring how figures and datasets
    # record their provenance.
    stage: str | None = None
    # Catch typos, and reject a hand-written ``url`` rather than silently
    # ignoring it
    model_config = ConfigDict(extra="forbid")

    @field_validator("path")
    @classmethod
    def check_path_is_a_file_in_the_project(cls, v: str) -> str:
        """The path names the app's HTML entrypoint, not its directory.

        Its parent is what gets served, so a path that isn't a file leaves
        nothing to serve and no root to serve it from.
        """
        if not v.strip():
            raise ValueError("Path must not be empty")
        p = PurePosixPath(v)
        if p.is_absolute():
            raise ValueError(f"Path must be relative: {v}")
        norm = posixpath.normpath(v)
        if norm == "." or norm.startswith(".."):
            raise ValueError(
                f"Path must be a file within the project, not '{v}'"
            )
        if not norm.endswith((".html", ".htm")):
            raise ValueError(
                f"Path must name an HTML file for a static-html app, got '{v}'"
            )
        return norm

    @property
    def serve_dir(self) -> str:
        """The directory to serve, i.e., the app's root."""
        return PurePosixPath(self.path).parent.as_posix()


class ShowcaseFigure(BaseModel):
    figure: str


class ShowcaseText(BaseModel):
    text: str


class ShowcaseMarkdown(BaseModel):
    markdown: str


class ShowcasePublication(BaseModel):
    publication: str


class ShowcaseMarkdownFile(BaseModel):
    markdown_file: str


class ShowcaseYamlFile(BaseModel):
    yaml_file: str
    object_name: str | None = None


class ShowcaseNotebook(BaseModel):
    notebook: str


class ShowcaseApp(BaseModel):
    """Show an app in the project's showcase, by its key in ``apps``."""

    app: str


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


class TableEvidence(BaseModel):
    """Evidence in the form of a table."""

    kind: Literal["table"] = "table"
    path: str
    explanation: str | None = None


class PublicationEvidence(BaseModel):
    """Evidence in the form of a publication."""

    kind: Literal["publication"] = "publication"
    path: str
    explanation: str | None = None


class Question(BaseModel):
    """A question the project hopes to answer.

    Each piece of evidence defines what it points at inline, discriminated by
    ``kind``, so citing something doesn't require declaring it at the top
    level first. The top-level collections are for the things worth naming or
    annotating, not a registry that evidence has to be registered in.
    """

    question: str
    hypothesis: str | None = None
    answer: str | None = None
    evidence: (
        list[
            FigureEvidence
            | ResultsEvidence
            | TableEvidence
            | PublicationEvidence
        ]
        | None
    ) = None


class ProjectInfo(BaseModel):
    """All of the project's information or metadata, written to the
    ``calkit.yaml`` file.

    This model is the source of truth for the published JSON schema, so every
    key that can validly appear in ``calkit.yaml`` should be declared here.
    Unknown keys are tolerated rather than rejected while the schema evolves;
    the pipeline is where typos are caught.
    """

    # Extra keys are allowed while the schema is still evolving, so a
    # project using a newer or experimental feature (e.g. ``app``, ``ops``)
    # isn't reported as invalid. The pipeline stays strict, since that's
    # where a typo'd key silently changes what runs.
    model_config = ConfigDict(populate_by_name=True)
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
        description="The account name that owns the project on Calkit.",
    )
    description: str | None = Field(
        default=None, description="A short description of the project."
    )
    name: str | None = Field(
        default=None,
        description="The project's name on Calkit, e.g., 'my-project'.",
    )
    hub: str | None = Field(
        default=None,
        description="Base URL of the Calkit Hub on which the project is "
        "shared, backed up, and collaborated on, e.g., 'calkit.io'. The "
        "scheme can be omitted, in which case https is inferred, or http "
        "for a local host. Each project belongs to at most one hub, which "
        "makes 'ck://' paths resolvable against a known instance. Projects "
        "with no hub set are assumed to belong to 'calkit.io'.",
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
    requirements: list[RequirementType] = Field(
        default=[],
        description=(
            "What must be true of the machine before the project runs: "
            "applications that must be on PATH, environmental variables, "
            "per-machine setup steps, and constraints on machine properties "
            "like CPU count. These describe the host, which is the built-in "
            "'_system' environment; a 'system' environment declares its own."
        ),
    )
    dependencies: list[RequirementType] = Field(
        default=[],
        description=(
            "Deprecated alias for 'requirements', still honored so existing "
            "projects keep working. Set one or the other, not both."
        ),
    )
    parameters: ParametersType | None = Field(
        default=None,
        description="Project-level parameters, which can be referenced from "
        "pipeline stages.",
    )
    pipeline: Pipeline | None = Field(
        default=None, description="The project's reproducible pipeline."
    )
    # A plain list: Dataset itself carries ``imported_from``, so a malformed
    # one is an error here rather than a key quietly dropped, which is what
    # a union with a looser fallback would have done.
    datasets: list[Dataset] = Field(
        default=[], description="The project's datasets."
    )
    figures: list[Figure] = Field(
        default=[], description="The project's figures."
    )
    results: list[Result] = Field(
        default=[],
        description="The project's findings, each referring to a file, or to "
        "part of one.",
    )
    publications: list[Publication] = Field(
        default=[],
        description="The project's papers, reports, and proposals.",
    )
    presentations: list[Presentation] = Field(
        default=[], description="The project's slides and posters."
    )
    tables: list[Table] = Field(
        default=[],
        description="The project's tables. Only needed for tables worth a "
        "title of their own; evidence can point at one inline.",
    )
    references: list[ReferenceCollection] = Field(
        default=[], description="The project's bibliographies."
    )
    environments: dict[
        str,
        # Discriminated on ``kind``, like pipeline stages, for two reasons.
        # The union is closed, so an environment matching no kind-specific
        # class is reported rather than silently validating with its fields
        # dropped; without the discriminator that only holds when ``kind`` is
        # present, since a kind-less environment would fall through to
        # whichever class happens to fit. It also decides what to report
        # against, so a uv-venv missing ``path`` is told exactly that instead
        # of "is not valid under any of the given schemas".
        Annotated[
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
            | SystemEnvironment,
            Discriminator("kind"),
        ],
    ] = Field(
        default={},
        description="Environments in which pipeline stages are run, keyed by "
        "name.",
    )
    misc: list[MiscArtifact] = Field(
        default=[],
        description=(
            "Paths worth attributing that aren't one of the typed "
            "artifacts, e.g. an image someone sent over or a file produced "
            "with help from a generative AI tool."
        ),
    )
    software: list[Software] = Field(
        default=[], description="Software created as part of the project."
    )
    notebooks: list[Notebook] = Field(
        default=[], description="The project's Jupyter notebooks."
    )
    procedures: dict[str, ProcedureEntry] = Field(
        default={},
        description="Procedures, typically executed by a human, keyed by "
        "name. Each is written inline or points at the file holding it.",
    )
    releases: dict[str, Release] = Field(
        default={},
        description="Published or archived snapshots, keyed by name.",
    )
    # Keyed by slug rather than a list, since the key becomes a public URL
    # segment and must stay stable if the app's path is renamed. Keying also
    # makes a duplicate slug a parse error rather than a validation pass.
    apps: dict[str, StaticHtmlApp] = Field(
        default={},
        description="The project's apps, keyed by name.",
    )
    showcase: (
        list[
            ShowcaseFigure
            | ShowcaseText
            | ShowcaseMarkdown
            | ShowcaseMarkdownFile
            | ShowcaseYamlFile
            | ShowcaseNotebook
            | ShowcasePublication
            | ShowcaseApp
        ]
        | None
    ) = Field(
        default=None,
        description="Elements that best represent the project, shown on its "
        "project homepage on Calkit.",
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
