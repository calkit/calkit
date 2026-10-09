"""Models for what must be true of a machine for a project to run."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    - ``setup``: a per-machine precondition that isn't a file---e.g.,
      the user must have authenticated a CLI like ``gh auth login``.
      A ``setup`` requirement declares ``check_command`` (a shell command
      whose exit code determines whether it is satisfied) and
      ``setup_command`` (run on a TTY when the user agrees, or printed
      as a fix-it command otherwise). To run either inside a project
      environment, prefix it with ``calkit xenv -n <env> --``.
      ``cache_ttl`` skips re-probing slow checks.
    - ``calkit-config``: a value that must be set in the user's Calkit
      configuration.

    These name a thing that must be present, so each has a ``name``. The
    properties of a machine that can't be installed, e.g., how many CPUs
    it has or what OS it runs, are constrained by giving the property as
    the ``kind`` instead, e.g., ``kind: cpu-count`` with a ``min``.
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

    Without a ``name``, Calkit derives a stable ``setup-<hash>`` one from
    ``check_command``.
    """

    kind: Literal["setup"] = "setup"
    name: str | None = None  # type: ignore[assignment]


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

    A property can't be installed, so there is nothing to name and nothing
    to fix: the check either passes on this machine or reports what it
    found against what was asked for.

    At least one of ``min`` and ``max`` must be given. To record a property
    that results depend on rather than constrain it, add it to a
    ``system`` environment's ``lock``.
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

    ``equals`` matches exactly and ``matches`` as a glob, both
    case-insensitively, and a list of values means any of them will do.
    ``version_spec`` compares as a version, for properties like
    ``os-version`` and ``python-version`` where '>=' means something.

    At least one of ``equals``, ``matches`` and ``version_spec`` must be
    given. To record a property that results depend on rather than
    constrain it, add it to a ``system`` environment's ``lock``.
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
    matches: str | list[str] | None = Field(
        default=None,
        description="Glob the property must match, case-insensitively, "
        "e.g., `*.cluster.edu` for a hostname. A list means any one of "
        "them.",
    )
    description: str | None = None

    @model_validator(mode="after")
    def _check_constrained(self) -> SystemValueRequirement:
        if (
            self.equals is None
            and self.version_spec is None
            and self.matches is None
        ):
            raise ValueError(
                f"Requirement on '{self.kind}' needs an 'equals', "
                "'matches' or 'version_spec'; to depend on its value rather "
                "than constrain it, add it to the environment's 'lock'"
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
