import pytest

import calkit.export
from calkit.models.pipeline import Pipeline


def test_export_stage():
    # Every app that exports has its own stage kind
    kinds = [e.kind for e in calkit.export.exporters()]
    assert kinds == ["inkscape-export", "gimp-export"]
    for source, output, app, kind in [
        # An app that can, does it as the pipeline runs
        ("figs/setup.svg", "paper/setup.png", None, "inkscape-export"),
        ("figs/setup.svg", "paper/setup.pdf", "inkscape", "inkscape-export"),
        ("figs/photo.xcf", "paper/photo.png", "GIMP", "gimp-export"),
        # One that can't is a manual step
        ("figs/photo.psd", "paper/photo.png", "Photoshop", "manual-step"),
        ("figs/setup.svg", "paper/setup.jpg", None, "manual-step"),
        # and so is one the person exports with another app
        ("figs/setup.svg", "paper/setup.png", "Illustrator", "manual-step"),
        ("figs/notes", "paper/notes.png", None, "manual-step"),
    ]:
        stage = calkit.export.export_stage(source, output, app=app)
        assert stage["kind"] == kind, (source, output, app)
        assert stage["outputs"] == [output]
        # What it makes is a stage calkit.yaml can have
        Pipeline.model_validate({"stages": {"export": stage}})
    assert calkit.export.export_stage(
        "figs/photo.psd", "paper/photo.png", app=" Photoshop "
    ) == {
        "kind": "manual-step",
        "message": "In Photoshop, export paper/photo.png from figs/photo.psd",
        "inputs": ["figs/photo.psd"],
        "outputs": ["paper/photo.png"],
        "open": {"app": "Photoshop", "path": "figs/photo.psd"},
    }
    assert calkit.export.export_stage("a.psd", "b.png") == {
        "kind": "manual-step",
        "message": "Export b.png from a.psd",
        "inputs": ["a.psd"],
        "outputs": ["b.png"],
    }
    # Named after what it makes
    for output, name in [
        ("paper/Setup Final.png", "export-setup-final"),
        ("paper/__.png", "export-figure"),
        ("fig", "export-fig"),
    ]:
        assert calkit.export.export_stage_name(output) == name


@pytest.mark.parametrize("missing", [True, False])
def test_find_executable(tmp_path, missing):
    exe = tmp_path / "app"
    if not missing:
        exe.write_text("")
    found = calkit.export.find_executable(
        ["calkit-test-no-such-app", str(exe)]
    )
    assert found == (None if missing else str(exe))
