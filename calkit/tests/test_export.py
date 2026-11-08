import sys

import pytest

import calkit.export
from calkit.models.pipeline import (
    InkscapeExportStage,
    ManualStepStage,
    Pipeline,
)


def test_export_stage():
    # Every app that exports has its own stage kind, except slides, which
    # either of two apps exports
    kinds = [e.kind for e in calkit.export.exporters()]
    assert kinds == [
        "inkscape-export",
        "gimp-export",
        "pptx-export",
        "pptx-export",
    ]
    for source, output, app, kind in [
        # An app that can, does it as the pipeline runs
        ("figs/setup.svg", "paper/setup.png", None, "inkscape-export"),
        ("figs/setup.svg", "paper/setup.pdf", "inkscape", "inkscape-export"),
        ("figs/photo.xcf", "paper/photo.png", "GIMP", "gimp-export"),
        ("figs/setup.pptx", "paper/setup.pdf", None, "pptx-export"),
        # including when it's named for the app the source is made in
        ("figs/setup.pptx", "paper/setup.png", "PowerPoint", "pptx-export"),
        ("figs/setup.pptm", "paper/setup.png", "LibreOffice", "pptx-export"),
        # One that can't is a manual step
        ("figs/photo.psd", "paper/photo.png", "Photoshop", "manual-step"),
        ("figs/setup.svg", "paper/setup.jpg", None, "manual-step"),
        ("figs/setup.pptx", "paper/setup.svg", "PowerPoint", "manual-step"),
        ("figs/setup.key", "paper/setup.pdf", "Keynote", "manual-step"),
        # The old binary format can't be prepared for cropping
        ("figs/setup.ppt", "paper/setup.pdf", None, "manual-step"),
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


@pytest.mark.skipif(sys.platform == "win32", reason="Fake app is a script")
def test_exporter_here(tmp_path, monkeypatch):
    inkscape = calkit.export.INKSCAPE
    # Found where its installer puts it, and asked its version
    fake = tmp_path / "inkscape"
    fake.write_text(
        f"#!{sys.executable}\nprint('Inkscape 1.3.2 (091e20e, 2023-11-25)')\n"
    )
    fake.chmod(0o755)
    monkeypatch.setattr(
        inkscape,
        "executables",
        ["calkit-test-no-such-inkscape", str(fake)],
    )
    assert inkscape.find_executable() == str(fake)
    assert inkscape.version() == "1.3.2"
    # and what a run of its stage records
    stage = InkscapeExportStage(source_path="a.svg", outputs=["a.png"])
    assert stage.run_properties() == {"inkscape_version": "1.3.2"}
    # A stage that runs no such app records nothing more
    assert ManualStepStage(message="Do it").run_properties() == {}
    # Not installed
    monkeypatch.setattr(
        inkscape, "executables", ["calkit-test-no-such-inkscape"]
    )
    assert inkscape.find_executable() is None
    assert inkscape.version() is None
    assert stage.run_properties() == {"inkscape_version": None}
