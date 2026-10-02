"""Generation of the JSON schema for ``calkit.yaml``.

The schema is derived from the ``ProjectInfo`` Pydantic model, so the models
stay the single source of truth. It is published so editors can validate and
autocomplete ``calkit.yaml``, e.g., with the YAML extension for VS Code.
"""

from __future__ import annotations

import json
import os

# The URL at which the schema is published, used as its ``$id`` and in the
# modeline written into new projects' calkit.yaml files
SCHEMA_URL = "https://docs.calkit.org/schemas/calkit.json"
PROVENANCE_SCHEMA_URL = "https://docs.calkit.org/schemas/provenance.json"
# Paths of the checked-in copies, relative to the repo root. The first is
# served at SCHEMA_URL by MkDocs; the second is bundled into the VS Code
# extension so it works offline, via its yamlValidation contribution point.
SCHEMA_REPO_PATHS = [
    "docs/schemas/calkit.json",
    "vscode-ext/schemas/calkit.json",
]
MODELINE = f"# yaml-language-server: $schema={SCHEMA_URL}"
# The provenance record a build writes beside each artifact. Published the
# same way, so an editor validates one of those files too.
PROVENANCE_SCHEMA_REPO_PATH = "docs/schemas/provenance.json"


def generate_provenance() -> dict:
    """Generate the JSON schema for a provenance record."""
    from calkit.components import ProvenanceRecord

    schema = ProvenanceRecord.model_json_schema(by_alias=True)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PROVENANCE_SCHEMA_URL,
        **schema,
        "title": "Calkit artifact provenance record",
        "description": (
            "What one build took from the project and put into one "
            "artifact. See https://docs.calkit.org/provenance"
        ),
    }


def generate_provenance_json() -> str:
    """The provenance record schema as formatted JSON text."""
    return json.dumps(generate_provenance(), indent=2, sort_keys=True) + "\n"


def generate() -> dict:
    """Generate the JSON schema for ``calkit.yaml``."""
    from calkit.models import ProjectInfo

    schema = ProjectInfo.model_json_schema()
    return {
        # Pydantic emits 2020-12 but doesn't declare the dialect, which some
        # validators need in order to pick the right one
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_URL,
        **schema,
        # These override what Pydantic derives from the model's name and
        # docstring, since they're shown to users in editors and catalogs
        "title": "Calkit project information",
        "description": (
            "Metadata for a Calkit project, describing its environments, "
            "pipeline, and artifacts. See https://docs.calkit.org/calkit-yaml"
        ),
    }


def generate_json() -> str:
    """Generate the JSON schema as formatted JSON text."""
    return json.dumps(generate(), indent=2, sort_keys=True) + "\n"


def ensure_modeline(fpath: str = "calkit.yaml") -> None:
    """Add the schema modeline to a ``calkit.yaml`` file if it lacks one.

    This is what makes editors validate and autocomplete the file without any
    per-user configuration. It's only added to newly created files, since
    ``ruamel.yaml`` preserves it on subsequent reads and writes.

    A file that already declares a schema anywhere is left alone rather than
    given a second, conflicting modeline, so this prepends only when there is
    none at all.
    """
    if os.path.isfile(fpath):
        with open(fpath, encoding="utf-8") as f:
            txt = f.read()
    else:
        txt = ""
    if "yaml-language-server: $schema=" in txt:
        return
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(MODELINE + "\n" + txt)
