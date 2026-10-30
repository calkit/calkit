import os
import sys

import pytest

import calkit.export
import calkit.inkscape


@pytest.mark.skipif(sys.platform == "win32", reason="Fake app is a script")
def test_export(tmp_dir, monkeypatch):
    # Which app exports what, and what it can't
    assert calkit.export.app_name("figs/a.SVG") == "Inkscape"
    assert calkit.export.app_name("a.xcf") == "GIMP"
    assert calkit.export.app_name("a.psd") is None
    for source, output, dpi, error in [
        ("a.psd", "a.png", None, "manual stage"),
        ("a.svg", "a.jpg", None, "not 'a.jpg'"),
        ("a.xcf", "a.pdf", None, "not 'a.pdf'"),
        ("a.xcf", "a.png", 300, "dpi only applies"),
    ]:
        with pytest.raises(ValueError, match=error):
            calkit.export.check_paths(source, output, dpi)
    with pytest.raises(ValueError, match="doesn't exist"):
        calkit.export.export("missing.svg", "out.png")
    # An export replaces what was there, which can't pass for a new one
    fake = "fake-inkscape"
    with open(fake, "w") as f:
        f.write(f"#!{sys.executable}\nimport sys\n")
    os.chmod(fake, 0o755)
    monkeypatch.setattr(
        calkit.inkscape, "EXECUTABLES", [os.path.abspath(fake)]
    )
    with open("setup.svg", "w") as f:
        f.write("<svg/>")
    os.makedirs("figs")
    with open("figs/setup.png", "w") as f:
        f.write("old")
    with pytest.raises(ValueError, match="didn't export"):
        calkit.export.export("setup.svg", "figs/setup.png")
    assert not os.path.exists("figs/setup.png")
    assert calkit.export.find_app("setup.svg") == os.path.abspath(fake)
    assert calkit.export.find_app("setup.psd") is None
