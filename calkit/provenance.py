"""Functionality for handling artifact provenance."""

# TODO: Provenance stuff belongs in its own module
# The artifact kinds whose provenance is checked. Each entry must say where
# it came from: a pipeline stage, an import, or the person who collected or
# created it.
PROVENANCE_ARTIFACT_TYPES = [
    "datasets",
    "figures",
    "publications",
    "tables",
    "presentations",
    "misc",
]


def has_provenance(artifact: dict) -> bool:
    """Return whether an artifact entry records where it came from.

    A stage and an import are the stronger forms, but ``collected_by`` and
    ``created_by`` count too: a dataset someone measured, or a schematic
    someone drew, is accounted for even though there's nothing upstream to
    point at. The field names in :class:`ReproCheck` predate the latter two
    and are kept so callers reading them keep working.
    """
    # TODO: created_by covers collected_by (remove the latter?)
    return any(
        artifact.get(key) is not None
        for key in ["stage", "imported_from", "collected_by", "created_by"]
    )
