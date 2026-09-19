"""Reading and writing contribution request records in a project."""

from __future__ import annotations

import os
from pathlib import Path

from calkit.core import ryaml
from calkit.models.contrib import ContribRequestRecord

REQUESTS_DIR = os.path.join(".calkit", "requests")


def record_path(request_id: str) -> str:
    return os.path.join(REQUESTS_DIR, f"{request_id}.yaml")


def load(request_id: str, wdir: str | None = None) -> ContribRequestRecord:
    path = Path(wdir or ".", record_path(request_id))
    with open(path, encoding="utf-8") as f:
        return ContribRequestRecord.model_validate(ryaml.load(f))


def save(record: ContribRequestRecord, wdir: str | None = None) -> str:
    """Write a request record, returning its path relative to the project."""
    rel = record_path(record.id)
    path = Path(wdir or ".", rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = record.model_dump(mode="json", exclude_none=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        ryaml.dump(data, f)
    return rel.replace(os.sep, "/")


def list_records(wdir: str | None = None) -> list[ContribRequestRecord]:
    root = Path(wdir or ".", REQUESTS_DIR)
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            out.append(ContribRequestRecord.model_validate(ryaml.load(f)))
    return out
