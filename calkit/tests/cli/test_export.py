import os
import pathlib
import shlex
import shutil
import sys
from typing import Any

import pytest
from typer.testing import CliRunner

import calkit.cli.export
from calkit.export import GIMP, INKSCAPE, LIBREOFFICE, POWERPOINT
from calkit.models.pipeline import (
    GimpExportStage,
    InkscapeExportStage,
    PptxExportStage,
)


@pytest.mark.skipif(sys.platform == "win32", reason="Fake apps are scripts")
def test_export(tmp_path, monkeypatch):
    from calkit.cli.main.core import app

    # Each writes what it's asked to export, the way the real apps name it
    inkscape = tmp_path / "inkscape"
    inkscape.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        "out = [a for a in sys.argv if a.startswith('--export-filename=')]\n"
        "pathlib.Path(out[0].split('=', 1)[1]).write_text('png')\n"
    )
    gimp = tmp_path / "gimp-console"
    gimp.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, re, sys\n"
        'dst = re.findall(r\'"([^"]+)"\', sys.argv[-1])[-1]\n'
        "pathlib.Path(dst).write_text('png')\n"
    )
    for fake in [inkscape, gimp]:
        fake.chmod(0o755)
    monkeypatch.setattr(INKSCAPE, "executables", [str(inkscape)])
    monkeypatch.setattr(GIMP, "executables", [str(gimp)])
    monkeypatch.chdir(tmp_path)
    (tmp_path / "setup.svg").write_text("<svg/>")
    (tmp_path / "photo.xcf").write_text("xcf")
    # The commands the stages run are ones the CLI takes
    for stage in [
        InkscapeExportStage(
            source_path="setup.svg", outputs=["paper/setup.png"], dpi=300
        ),
        GimpExportStage(source_path="photo.xcf", outputs=["paper/photo.png"]),
    ]:
        args = shlex.split(stage.dvc_cmd)
        assert args[:2] == ["calkit", "export"]
        result = CliRunner().invoke(app, args[1:])
        assert result.exit_code == 0, result.output
        assert (tmp_path / stage.output_path).read_text() == "png"
    # and what an app can't export says why
    result = CliRunner().invoke(
        app, ["export", "inkscape", "photo.xcf", "-o", "photo.png"]
    )
    assert result.exit_code != 0
    assert "from an SVG" in result.output


@pytest.mark.skipif(sys.platform == "win32", reason="Fake app is a script")
def test_inkscape(tmp_path, monkeypatch):
    log = tmp_path / "args.txt"
    fake = tmp_path / "inkscape"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        f"pathlib.Path({str(log)!r}).write_text(repr(sys.argv[1:]))\n"
        "out = [a for a in sys.argv if a.startswith('--export-filename=')]\n"
        "if 'nothing' not in sys.argv[1]:\n"
        "    pathlib.Path(out[0].split('=', 1)[1]).write_text('png')\n"
    )
    fake.chmod(0o755)
    monkeypatch.setattr(INKSCAPE, "executables", [str(fake)])
    assert INKSCAPE.find_executable() == str(fake)
    source = tmp_path / "setup.svg"
    source.write_text("<svg/>")
    # What it can export from and to
    for src, output, error in [
        ("a.psd", "a.png", "from an SVG"),
        ("a.svg", "a.jpg", "not 'a.jpg'"),
    ]:
        with pytest.raises(ValueError, match=error):
            calkit.cli.export.export_with_inkscape(src, output)
    with pytest.raises(ValueError, match="doesn't exist"):
        calkit.cli.export.export_with_inkscape(
            str(tmp_path / "gone.svg"), "out.png"
        )
    # Into a folder made for it
    out = tmp_path / "figs" / "setup.png"
    calkit.cli.export.export_with_inkscape(str(source), str(out), dpi=150)
    assert out.read_text() == "png"
    assert log.read_text() == repr(
        [str(source), f"--export-filename={out}", "--export-dpi=150"]
    )
    # Writing nothing is a failure, even with a zero exit code, and what
    # was there before can't pass for a new export
    nothing = tmp_path / "nothing.svg"
    nothing.write_text("<svg/>")
    with pytest.raises(ValueError, match="didn't export"):
        calkit.cli.export.export_with_inkscape(str(nothing), str(out))
    assert not out.exists()
    # It says what's missing when it isn't installed
    monkeypatch.setattr(
        INKSCAPE, "executables", ["calkit-test-no-such-inkscape"]
    )
    assert INKSCAPE.find_executable() is None
    with pytest.raises(ValueError, match="needs Inkscape installed"):
        calkit.cli.export.export_with_inkscape(str(source), str(out))


@pytest.mark.skipif(
    LIBREOFFICE.find_executable() is None, reason="Needs LibreOffice"
)
def test_export_slides(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    import pypdfium2 as pdfium
    from PIL import Image

    import calkit
    from calkit.cli.main.core import app

    def pdf_sizes(path: str) -> list[tuple[float, float]]:
        pdf = pdfium.PdfDocument(path)
        try:
            return [
                (round(float(w), 1), round(float(h), 1))
                for w, h in (page.get_size() for page in pdf)
            ]
        finally:
            pdf.close()

    def export(*args: str) -> None:
        result = CliRunner().invoke(app, ["export", "pptx", *args])
        assert result.exit_code == 0, result.output

    monkeypatch.chdir(tmp_path)
    # A title, a hidden slide, a diagram off to one side, a colored
    # background, a photo filling the slide with a label on it, a picture
    # cropped to its right half beside a shape running off the slide, and
    # a small shape beside the slide's number; 960 by 540 points
    shutil.copy(
        os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "test", "slides.pptx"
        ),
        "slides.pptx",
    )
    with open("calkit.yaml", "w") as yaml_file:
        yaml_file.write(
            "environments:\n"
            "  py: {kind: uv, path: pyproject.toml}\n"
            "  plain: {kind: system, requirements: [git]}\n"
            "  lo: {kind: system, requirements: [libreoffice]}\n"
            "  ppt: {kind: system, requirements: [powerpoint]}\n"
        )
    # What it can export from and to, and where
    cases: list[tuple[dict[str, Any], str]] = [
        (dict(source="a.key", output="a.pdf"), "from a PowerPoint file"),
        (dict(output="a.svg"), "not 'a.svg'"),
        (dict(output="a.pdf", slides=[0]), "numbered from 1"),
        (dict(output="a.pdf", slides=[8]), "has 7 slides"),
        (dict(output="a.png", slides=[3, 5]), "Several slides go into one"),
        (dict(output="a.pdf", env="nope"), "no environment named 'nope'"),
        (dict(output="a.pdf", env="py"), "in a uv environment"),
        (dict(output="a.pdf", env="plain"), "requires neither"),
    ]
    for kwargs, error in cases:
        with pytest.raises(ValueError, match=error):
            calkit.cli.export.export_slides(
                **{"source": "slides.pptx", **kwargs}
            )
    assert not os.path.exists("a.pdf")
    # The diagram, cropped to what's drawn, through the command its stage
    # runs, the same each time it's exported
    stage = PptxExportStage(
        source_path="slides.pptx",
        outputs=["figs/setup.pdf"],
        slides=3,
        environment="lo",
    )
    exported = []
    for _ in range(2):
        result = CliRunner().invoke(app, shlex.split(stage.dvc_cmd)[1:])
        assert result.exit_code == 0, result.output
        with open("figs/setup.pdf", "rb") as f:
            exported.append(f.read())
    assert exported[0] == exported[1]
    [(width, height)] = pdf_sizes("figs/setup.pdf")
    assert 400 < width < 460 and 100 < height < 130
    # and the app that did it, as a run records it
    assert stage.run_properties() == {
        "libreoffice_version": LIBREOFFICE.version()
    }
    # As a PNG, at 300 DPI unless asked
    export("slides.pptx", "-o", "setup.png", "--slides", "3")
    assert Image.open("setup.png").size == (
        pytest.approx(width * 300 / 72, abs=2),
        pytest.approx(height * 300 / 72, abs=2),
    )
    # A file per slide, each cropped to what's drawn on it: the whole photo
    # under its label, the picture as cropped and the shape as far as the
    # slide's edge, and the small shape without the slide's number
    export("slides.pptx", "-o", "figs/s-{slide}.png", "--slides", "2,5-7")
    export("slides.pptx", "-o", "figs/s-{slide}.png", "--slides", "2,5-7")
    sizes = {n: Image.open(f"figs/s-{n}.png").size for n in (2, 5, 6, 7)}
    assert sizes[2][0] < 300 * 960 / 72
    assert sizes[5] == (pytest.approx(4000, abs=1), 2250)
    assert sizes[6][0] == pytest.approx(660 * 300 / 72, abs=10)
    assert sizes[7][0] < 120 * 300 / 72 and sizes[7][1] < 120 * 300 / 72
    # Every slide into one PDF, uncropped, hidden ones too, unless asked
    export("slides.pptx", "-o", "talk.pdf")
    assert pdf_sizes("talk.pdf") == [(960.0, 540.0)] * 7
    export("slides.pptx", "-o", "talk.pdf", "--slides", "3,7", "--trim")
    assert [w < 500 for w, _ in pdf_sizes("talk.pdf")] == [True, True]
    export("slides.pptx", "-o", "whole.png", "--slides", "2", "--no-trim")
    assert Image.open("whole.png").size == (pytest.approx(4000, abs=1), 2250)
    result = CliRunner().invoke(
        app, ["export", "pptx", "slides.pptx", "-o", "a.pdf", "--slides", "x"]
    )
    assert result.exit_code != 0 and "should list slides" in result.output
    # PowerPoint, when it's here, crops the same, and says its version
    if POWERPOINT.find_executable() is not None and sys.platform != "linux":
        stage = PptxExportStage(
            source_path="slides.pptx",
            outputs=["ppt/s-{slide}.pdf"],
            slides=[2, 3],
            environment="ppt",
        )
        result = CliRunner().invoke(app, shlex.split(stage.dvc_cmd)[1:])
        assert result.exit_code == 0, result.output
        [(w, h)] = pdf_sizes("ppt/s-3.pdf")
        assert w == pytest.approx(width, abs=2)
        assert h == pytest.approx(height, abs=2)
        assert pdf_sizes("ppt/s-2.pdf")[0][0] < 960
        assert stage.run_properties() == {
            "powerpoint_version": POWERPOINT.version()
        }
    # LibreOffice's image, when it's here, in a Docker environment
    image = "ghcr.io/calkit/libreoffice:0.1.0"
    if (
        shutil.which("docker") is not None
        and subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True
        ).returncode
        == 0
    ):
        with open("calkit.yaml", "a") as yaml_file:
            yaml_file.write(f"  img: {{kind: docker, image: '{image}'}}\n")
        export("slides.pptx", "-o", "img.pdf", "--slides", "3", "-e", "img")
        [(w, h)] = pdf_sizes("img.pdf")
        assert w == pytest.approx(width, abs=2)
        assert not [p for p in os.listdir(".calkit") if p.startswith("tmp-")]
    # It says what's missing when nothing that exports slides is installed
    monkeypatch.setattr(LIBREOFFICE, "executables", ["calkit-test-no-soffice"])
    monkeypatch.setattr(POWERPOINT, "executables", ["calkit-test-no-ppt"])
    with pytest.raises(ValueError, match="needs LibreOffice or PowerPoint"):
        calkit.cli.export.export_slides("slides.pptx", "a.pdf")


@pytest.mark.skipif(sys.platform == "win32", reason="Fake app is a script")
def test_gimp(tmp_path, monkeypatch):
    log = tmp_path / "attempts.txt"
    # Stands in for GIMP 2, which doesn't know the batch interpreter flag
    # and, like GIMP 3, exits 0 whether or not its script worked
    fake = tmp_path / "gimp-console"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, re, sys\n"
        f"with open({str(log)!r}, 'a') as f:\n"
        "    f.write(repr(sys.argv[1:]) + '\\n')\n"
        "script = sys.argv[-1]\n"
        "if '--batch-interpreter' not in ' '.join(sys.argv):\n"
        '    dst = re.findall(r\'"([^"]+)"\', script)[-1]\n'
        "    if 'nothing' not in dst:\n"
        "        pathlib.Path(dst).write_text('png')\n"
    )
    fake.chmod(0o755)
    monkeypatch.setattr(GIMP, "executables", [str(fake)])
    source = tmp_path / "figure.xcf"
    source.write_text("xcf")
    # What it can export from and to
    for src, output, error in [
        ("a.psd", "a.png", "from an XCF"),
        ("a.xcf", "a.pdf", "not 'a.pdf'"),
    ]:
        with pytest.raises(ValueError, match=error):
            calkit.cli.export.export_with_gimp(src, output)
    with pytest.raises(ValueError, match="doesn't exist"):
        calkit.cli.export.export_with_gimp(
            str(tmp_path / "gone.xcf"), "out.png"
        )
    out = tmp_path / "figure.png"
    calkit.cli.export.export_with_gimp(str(source), str(out))
    assert out.read_text() == "png"
    # GIMP 3's dialect first, then GIMP 2's, each flattening the document
    attempts = log.read_text().splitlines()
    assert len(attempts) == 2
    assert "--batch-interpreter" in attempts[0]
    assert "--batch-interpreter" not in attempts[1]
    assert "gimp-image-flatten" in attempts[1]
    # Writing nothing in either dialect is a failure
    with pytest.raises(ValueError, match="didn't export"):
        calkit.cli.export.export_with_gimp(
            str(source), str(tmp_path / "nothing.png")
        )
    monkeypatch.setattr(GIMP, "executables", ["calkit-test-no-gimp"])
    assert GIMP.find_executable() is None
    with pytest.raises(ValueError, match="needs GIMP installed"):
        calkit.cli.export.export_with_gimp(str(source), str(out))
