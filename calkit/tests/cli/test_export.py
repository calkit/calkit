import shlex
import sys

import pytest
from typer.testing import CliRunner

import calkit.cli.export
from calkit.export import GIMP, INKSCAPE
from calkit.models.pipeline import GimpExportStage, InkscapeExportStage


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
            calkit.cli.export.inkscape(src, output)
    with pytest.raises(ValueError, match="doesn't exist"):
        calkit.cli.export.inkscape(str(tmp_path / "gone.svg"), "out.png")
    # Into a folder made for it
    out = tmp_path / "figs" / "setup.png"
    calkit.cli.export.inkscape(str(source), str(out), dpi=150)
    assert out.read_text() == "png"
    assert log.read_text() == repr(
        [str(source), f"--export-filename={out}", "--export-dpi=150"]
    )
    # Writing nothing is a failure, even with a zero exit code, and what
    # was there before can't pass for a new export
    nothing = tmp_path / "nothing.svg"
    nothing.write_text("<svg/>")
    with pytest.raises(ValueError, match="didn't export"):
        calkit.cli.export.inkscape(str(nothing), str(out))
    assert not out.exists()
    # It says what's missing when it isn't installed
    monkeypatch.setattr(
        INKSCAPE, "executables", ["calkit-test-no-such-inkscape"]
    )
    assert INKSCAPE.find_executable() is None
    with pytest.raises(ValueError, match="needs Inkscape installed"):
        calkit.cli.export.inkscape(str(source), str(out))


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
            calkit.cli.export.gimp(src, output)
    with pytest.raises(ValueError, match="doesn't exist"):
        calkit.cli.export.gimp(str(tmp_path / "gone.xcf"), "out.png")
    out = tmp_path / "figure.png"
    calkit.cli.export.gimp(str(source), str(out))
    assert out.read_text() == "png"
    # GIMP 3's dialect first, then GIMP 2's, each flattening the document
    attempts = log.read_text().splitlines()
    assert len(attempts) == 2
    assert "--batch-interpreter" in attempts[0]
    assert "--batch-interpreter" not in attempts[1]
    assert "gimp-image-flatten" in attempts[1]
    # Writing nothing in either dialect is a failure
    with pytest.raises(ValueError, match="didn't export"):
        calkit.cli.export.gimp(str(source), str(tmp_path / "nothing.png"))
    monkeypatch.setattr(GIMP, "executables", ["calkit-test-no-gimp"])
    assert GIMP.find_executable() is None
    with pytest.raises(ValueError, match="needs GIMP installed"):
        calkit.cli.export.gimp(str(source), str(out))
