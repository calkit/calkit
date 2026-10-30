import sys

import pytest

import calkit.inkscape


@pytest.mark.skipif(sys.platform == "win32", reason="Fake app is a script")
def test_export(tmp_path, monkeypatch):
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
    monkeypatch.setattr(calkit.inkscape, "EXECUTABLES", [str(fake)])
    assert calkit.inkscape.find_executable() == str(fake)
    out = tmp_path / "setup.png"
    calkit.inkscape.export("setup.svg", str(out), dpi=150)
    assert out.read_text() == "png"
    assert log.read_text() == repr(
        ["setup.svg", f"--export-filename={out}", "--export-dpi=150"]
    )
    # Writing nothing is a failure, even with a zero exit code
    with pytest.raises(ValueError, match="didn't export"):
        calkit.inkscape.export("nothing.svg", str(tmp_path / "none.png"))
    # It says what's missing when it isn't installed
    monkeypatch.setattr(
        calkit.inkscape, "EXECUTABLES", ["calkit-test-no-such-inkscape"]
    )
    assert calkit.inkscape.find_executable() is None
    with pytest.raises(ValueError, match="needs Inkscape installed"):
        calkit.inkscape.export("setup.svg", str(out))
