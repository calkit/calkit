"""Tests for the calkit.yaml data models."""

import pytest
from pydantic import ValidationError

from calkit.models.core import (
    Dataset,
    ImportedDataset,
    MiscArtifact,
    ProjectInfo,
)


def test_dataset_provenance():
    info = ProjectInfo.model_validate(
        {
            "datasets": [
                {"path": "a.csv", "collected_by": {"email": "me@x.edu"}},
                {
                    "path": "b.csv",
                    "imported_from": {"doi": "10.5281/zenodo.1"},
                },
                {
                    "path": "c.csv",
                    "imported_from": {
                        "url": "https://x.org/c.csv",
                        "date": "2026-01-02",
                    },
                },
                {
                    "path": "d.csv",
                    "imported_from": {
                        "git": {
                            "repo_url": "https://github.com/a/b",
                            "rev": "4031e49efbea3be3b6b10e66f30d7cff6dfc60cc",
                            "path": "data/x.csv",
                        }
                    },
                },
            ]
        }
    )
    kinds = [type(d).__name__ for d in info.datasets]
    assert kinds == [
        "Dataset",
        "ImportedDataset",
        "ImportedDataset",
        "ImportedDataset",
    ]
    # Provenance survives validation rather than being dropped as an extra
    # key, which is what a plain list[Dataset] would have done.
    assert info.datasets[1].imported_from.doi == "10.5281/zenodo.1"
    # A branch or tag would move, so the data behind the entry could change
    # without the entry changing.
    for bad_rev in ["main", "v1.2.3", "abc"]:
        with pytest.raises(ValidationError):
            ImportedDataset.model_validate(
                {
                    "path": "x",
                    "imported_from": {
                        "git": {"repo_url": "https://x", "rev": bad_rev}
                    },
                }
            )
    # Data is either something you produced or something you got.
    with pytest.raises(ValidationError):
        ImportedDataset.model_validate(
            {
                "path": "x",
                "collected_by": {"email": "m@x.edu"},
                "imported_from": {"doi": "10.1/x"},
            }
        )


def test_person_orcid():
    # Stored resolvable, however it was written, so CITATION.cff and any
    # exporter get one form rather than guessing at a bare identifier.
    expected = "https://orcid.org/0000-0002-1825-0097"
    for given in [
        "0000-0002-1825-0097",
        "https://orcid.org/0000-0002-1825-0097",
        "http://orcid.org/0000-0002-1825-0097",
        "  0000-0002-1825-0097  ",
    ]:
        ds = Dataset.model_validate(
            {"path": "a", "collected_by": {"email": "m@x.edu", "orcid": given}}
        )
        assert ds.collected_by.orcid == expected
    # The trailing check digit can be X, and anything else isn't an ORCID.
    assert (
        Dataset.model_validate(
            {
                "path": "a",
                "collected_by": {
                    "email": "m@x",
                    "orcid": "0000-0002-1825-009X",
                },
            }
        ).collected_by.orcid
        == "https://orcid.org/0000-0002-1825-009X"
    )
    for bad in ["nope", "0000-0002-1825", "0000000218250097"]:
        with pytest.raises(ValidationError):
            Dataset.model_validate(
                {"path": "a", "collected_by": {"email": "m@x", "orcid": bad}}
            )
    # Several collectors is the normal case for collaborative work, and
    # each is identified however they can be.
    ds = Dataset.model_validate(
        {
            "path": "a",
            "collected_by": [
                {"email": "a@x.edu", "orcid": "0000-0002-1825-0097"},
                {"orcid": "0000-0001-5109-3700"},
                {"email": "c@x.edu", "name": "C Person"},
            ],
        }
    )
    assert len(ds.collected_by) == 3
    assert ds.collected_by[1].email is None
    # A name alone doesn't say which of the several people with it this is.
    with pytest.raises(ValidationError):
        Dataset.model_validate(
            {"path": "a", "collected_by": {"name": "Just A Name"}}
        )


def test_misc_artifact():
    info = ProjectInfo.model_validate(
        {
            "misc": [
                {"path": "img/rig.jpg", "created_by": {"email": "me@x.edu"}},
                {
                    "path": "cfg/solver.toml",
                    "imported_from": {"url": "https://x.org/solver.toml"},
                },
                {
                    "path": "figures/schematic.png",
                    "created_by": {"email": "me@x.edu"},
                    "generated_with_ai": "Claude Opus 5",
                },
            ]
        }
    )
    assert [m.path for m in info.misc] == [
        "img/rig.jpg",
        "cfg/solver.toml",
        "figures/schematic.png",
    ]
    assert info.misc[2].generated_with_ai == "Claude Opus 5"
    # A model can't answer for a file, so the disclosure names people too.
    with pytest.raises(ValidationError):
        MiscArtifact.model_validate(
            {"path": "x", "generated_with_ai": "Claude Opus 5"}
        )
    # Made here or obtained elsewhere, not both.
    with pytest.raises(ValidationError):
        MiscArtifact.model_validate(
            {
                "path": "x",
                "created_by": {"email": "m@x.edu"},
                "imported_from": {"doi": "10.1/x"},
            }
        )
    # Several tools, and several people, are both normal.
    m = MiscArtifact.model_validate(
        {
            "path": "x",
            "created_by": [{"email": "a@x.edu"}, {"email": "b@x.edu"}],
            "generated_with_ai": ["Claude Opus 5", "GitHub Copilot"],
        }
    )
    assert len(m.generated_with_ai) == 2
    # Misc artifacts can still be produced by a stage like anything else.
    assert (
        MiscArtifact.model_validate({"path": "x", "stage": "make-it"}).stage
        == "make-it"
    )
