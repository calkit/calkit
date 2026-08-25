"""Functionality for handling artifact provenance."""

# The artifact kinds whose provenance is checked. Each entry must say where
# it came from: a pipeline stage, an import, or the person who created it,
# e.g., by collecting or measuring the data or drawing the figure.
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

    A stage and an import are the stronger forms, but ``created_by`` counts
    too: a dataset someone measured, or a schematic someone drew, is
    accounted for even though there's nothing upstream to point at. The
    field names in :class:`calkit.reproducibility.ReproCheck` predate
    attribution and are kept so callers reading them keep working.
    """
    return any(
        artifact.get(key) is not None
        for key in ["stage", "imported_from", "created_by"]
    )
