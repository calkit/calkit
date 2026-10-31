import shlex
import sys

import pytest
from typer.testing import CliRunner

import calkit.gimp
import calkit.inkscape
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
    monkeypatch.setattr(calkit.inkscape, "EXECUTABLES", [str(inkscape)])
    monkeypatch.setattr(calkit.gimp, "EXECUTABLES", [str(gimp)])
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
