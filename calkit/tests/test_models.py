"""Tests for the calkit.yaml data models."""

import io

import pytest
from pydantic import ValidationError

import calkit
from calkit.models.core import (
    Dataset,
    Figure,
    ImportedDataset,
    MiscArtifact,
    ProjectInfo,
    Publication,
)


def _roundtrip(ck_info: dict) -> ProjectInfo:
    # What gets written is model_dump through ryaml, and what gets read is
    # ryaml through model_validate, so both directions are exercised.
    buf = io.StringIO()
    calkit.ryaml.dump(ck_info, buf)
    buf.seek(0)
    return ProjectInfo.model_validate(calkit.ryaml.load(buf))


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
                {"path": "e.csv"},
            ]
        }
    )
    # One model carries every form, so nothing depends on union ordering
    assert all(type(d) is Dataset for d in info.datasets)
    assert info.datasets[1].imported_from.doi == "10.5281/zenodo.1"
    assert str(info.datasets[2].imported_from.date) == "2026-01-02"
    assert info.datasets[4].imported_from is None
    # A malformed imported_from is an error at the project level, not a key
    # quietly dropped by falling back to a looser model.
    for bad in [
        {"git": {"repo_url": "https://x", "rev": "main"}},
        {"doi": None},
        {"doi": "10.21223.zenodo/etc"},
        {"url": "https://x", "date": "not-a-date"},
        {"nonsense": True},
    ]:
        with pytest.raises(ValidationError):
            ProjectInfo.model_validate(
                {"datasets": [{"path": "x", "imported_from": bad}]}
            )
    # Data is either something you produced or something you got.
    with pytest.raises(ValidationError):
        ProjectInfo.model_validate(
            {
                "datasets": [
                    {
                        "path": "x",
                        "collected_by": {"email": "m@x.edu"},
                        "imported_from": {"doi": "10.1234/x"},
                    }
                ]
            }
        )
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
    # ImportedDataset only narrows imported_from to required, for callers
    # holding a dataset they know was imported.
    with pytest.raises(ValidationError):
        ImportedDataset.model_validate({"path": "x"})
    assert (
        ImportedDataset.model_validate(
            {"path": "x", "imported_from": {"doi": "10.1234/x"}}
        ).imported_from.doi
        == "10.1234/x"
    )
    # An empty list claims nobody, which would count as provenance while
    # naming no one.
    with pytest.raises(ValidationError, match="empty list"):
        Dataset.model_validate({"path": "x", "collected_by": []})
    with pytest.raises(ValidationError, match="empty list"):
        Figure.model_validate({"path": "x", "created_by": []})
    # A DOI is stored bare however it was written, and anything that isn't
    # one is refused rather than sitting under the key looking citable.
    for given in [
        "10.5281/zenodo.1234567",
        "https://doi.org/10.5281/zenodo.1234567",
        "http://dx.doi.org/10.5281/zenodo.1234567",
        "doi:10.5281/zenodo.1234567",
        "DOI:10.5281/zenodo.1234567",
        "  10.5281/zenodo.1234567  ",
    ]:
        ds = Dataset.model_validate(
            {"path": "x", "imported_from": {"doi": given}}
        )
        assert ds.imported_from.doi == "10.5281/zenodo.1234567"
    for bad in ["", "zenodo.1234567", "10.1/x", "10.5281/", "11.5281/x"]:
        with pytest.raises(ValidationError):
            Dataset.model_validate(
                {"path": "x", "imported_from": {"doi": bad}}
            )
    # Written with model_dump and read back through YAML, a date stays a
    # date and nothing else is lost along the way.
    ds = Dataset.model_validate(
        {
            "path": "c.csv",
            "imported_from": {
                "url": "https://x.org/c.csv",
                "date": "2026-01-02",
            },
        }
    )
    fig = Figure.model_validate(
        {"path": "f.png", "imported_from": {"doi": "doi:10.5281/zenodo.9"}}
    )
    dumped = {
        "datasets": [ds.model_dump(exclude_none=True)],
        "figures": [fig.model_dump(exclude_none=True)],
    }
    assert "collected_by" not in dumped["datasets"][0]
    info = _roundtrip(dumped)
    assert info.datasets[0] == ds
    assert info.figures[0] == fig
    assert str(info.datasets[0].imported_from.date) == "2026-01-02"
    assert info.figures[0].imported_from.doi == "10.5281/zenodo.9"


def test_person_orcid():
    # Stored resolvable, however it was written, so CITATION.cff and any
    # exporter get one form rather than guessing at a bare identifier.
    expected = "https://orcid.org/0000-0002-1825-0097"
    for given in [
        "0000-0002-1825-0097",
        "https://orcid.org/0000-0002-1825-0097",
        "http://orcid.org/0000-0002-1825-0097",
        "orcid.org/0000-0002-1825-0097",
        "  0000-0002-1825-0097  ",
    ]:
        ds = Dataset.model_validate(
            {"path": "a", "collected_by": {"email": "m@x.edu", "orcid": given}}
        )
        assert ds.collected_by.orcid == expected
    # The trailing character is an ISO 7064 MOD 11-2 check digit, which
    # can be X; one that doesn't match the other digits is a typo, not an
    # ORCID.
    for good in ["0000-0002-1694-233X", "0000-0002-1694-233x"]:
        assert (
            Dataset.model_validate(
                {"path": "a", "collected_by": {"orcid": good}}
            ).collected_by.orcid
            == "https://orcid.org/0000-0002-1694-233X"
        )
    for bad in [
        "nope",
        "0000-0002-1825",
        "0000000218250097",
        "0000-0002-1825-009X",
        "0000-0002-1825-0098",
        "0000-0002-1694-2330",
    ]:
        with pytest.raises(ValidationError):
            Dataset.model_validate(
                {
                    "path": "a",
                    "collected_by": {"email": "m@x.edu", "orcid": bad},
                }
            )
    # An email has to look like one, lightly: an empty string or a bare
    # word can't count as identifying somebody.
    for bad_email in ["", "   ", "me", "@x.edu", "me@"]:
        with pytest.raises(ValidationError):
            Dataset.model_validate(
                {"path": "a", "collected_by": {"email": bad_email}}
            )
    assert (
        Dataset.model_validate(
            {"path": "a", "collected_by": {"email": " me@x.edu "}}
        ).collected_by.email
        == "me@x.edu"
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


def test_figure_attribution():
    # A figure from a stage needs nothing else; the stage is the record.
    assert (
        Figure.model_validate({"path": "f.png", "stage": "plot"}).created_by
        is None
    )
    fig = Figure.model_validate(
        {
            "path": "figures/schematic.png",
            "created_by": {"email": "me@x.edu", "with_ai": "Claude Opus 5"},
        }
    )
    assert fig.created_by.with_ai == "Claude Opus 5"
    # With several authors, which of them used the tool is recorded too.
    fig = Figure.model_validate(
        {
            "path": "f.png",
            "created_by": [
                {"email": "a@x.edu", "with_ai": ["Claude Opus 5", "Copilot"]},
                {"orcid": "0000-0001-5109-3700"},
            ],
        }
    )
    assert len(fig.created_by[0].with_ai) == 2
    assert fig.created_by[1].with_ai is None
    # A disclosure that names nothing discloses nothing; leaving the key
    # out is how to say no tool was used.
    for bad_ai in ["", "  ", [], [""], ["Claude Opus 5", ""]]:
        with pytest.raises(ValidationError):
            Figure.model_validate(
                {
                    "path": "f.png",
                    "created_by": {"email": "a@x.edu", "with_ai": bad_ai},
                }
            )
    # The disclosure lives on the person, so there is no shape in which one
    # exists without somebody answering for it -- no validator needed.
    assert "generated_with_ai" not in Figure.model_fields
    # A figure can come from elsewhere like a dataset can, and then it was
    # not made here: one or the other.
    fig = Figure.model_validate(
        {
            "path": "f.png",
            "imported_from": {
                "url": "https://x.org/f.png",
                "date": "2026-01-02",
            },
        }
    )
    assert fig.imported_from.url == "https://x.org/f.png"
    with pytest.raises(ValidationError):
        Figure.model_validate(
            {
                "path": "f.png",
                "created_by": {"email": "a@x.edu"},
                "imported_from": {"doi": "10.1234/x"},
            }
        )
    # Publications imported from an archive record it the same way, apart
    # from their own DOI.
    pub = Publication.model_validate(
        {
            "path": "paper.pdf",
            "imported_from": {"doi": "https://doi.org/10.1234/them"},
        }
    )
    assert pub.imported_from.doi == "10.1234/them"
    assert pub.doi is None
    # The published schema refuses the combination too, rather than
    # advertising a key the validator then rejects.
    for model, made_key in [
        (Dataset, "collected_by"),
        (ImportedDataset, "collected_by"),
        (Figure, "created_by"),
        (MiscArtifact, "created_by"),
    ]:
        schema = model.model_json_schema()
        assert schema["not"]["required"] == ["imported_from", made_key]
    # It can be recorded anywhere a person can, datasets included: a rule
    # against writing it down wouldn't stop anyone using a model, it would
    # only stop readers finding out. On a dataset it's a flag rather than a
    # footnote, which is a matter for the docs, not the schema.
    ds = Dataset.model_validate(
        {
            "path": "a.csv",
            "collected_by": {"email": "m@x.edu", "with_ai": "Claude Opus 5"},
        }
    )
    assert ds.collected_by.with_ai == "Claude Opus 5"
    # A mistyped key is refused rather than dropped, so an author can't
    # think they recorded something they didn't.
    with pytest.raises(ValidationError):
        Dataset.model_validate(
            {
                "path": "a.csv",
                "collected_by": {"email": "m@x.edu", "oricd": "x"},
            }
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
                    "created_by": {
                        "email": "me@x.edu",
                        "with_ai": "Claude Opus 5",
                    },
                },
            ]
        }
    )
    assert [m.path for m in info.misc] == [
        "img/rig.jpg",
        "cfg/solver.toml",
        "figures/schematic.png",
    ]
    assert info.misc[2].created_by.with_ai == "Claude Opus 5"
    # Made here or obtained elsewhere, not both.
    with pytest.raises(ValidationError):
        MiscArtifact.model_validate(
            {
                "path": "x",
                "created_by": {"email": "m@x.edu"},
                "imported_from": {"doi": "10.1234/x"},
            }
        )
    # Several tools, and several people, are both normal.
    m = MiscArtifact.model_validate(
        {
            "path": "x",
            "created_by": [
                {"email": "a@x.edu", "with_ai": ["Claude Opus 5", "Copilot"]},
                {"email": "b@x.edu"},
            ],
        }
    )
    assert len(m.created_by[0].with_ai) == 2
    # Misc artifacts can still be produced by a stage like anything else.
    assert (
        MiscArtifact.model_validate({"path": "x", "stage": "make-it"}).stage
        == "make-it"
    )
