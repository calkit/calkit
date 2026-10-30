import sys

import pytest

import calkit.gimp


@pytest.mark.skipif(sys.platform == "win32", reason="Fake app is a script")
def test_export(tmp_path, monkeypatch):
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
    monkeypatch.setattr(calkit.gimp, "EXECUTABLES", [str(fake)])
    source = tmp_path / "figure.xcf"
    source.write_text("xcf")
    # What it can export from and to
    for src, output, error in [
        ("a.psd", "a.png", "from an XCF"),
        ("a.xcf", "a.pdf", "not 'a.pdf'"),
    ]:
        with pytest.raises(ValueError, match=error):
            calkit.gimp.check_export(src, output)
    with pytest.raises(ValueError, match="doesn't exist"):
        calkit.gimp.export(str(tmp_path / "gone.xcf"), "out.png")
    out = tmp_path / "figure.png"
    calkit.gimp.export(str(source), str(out))
    assert out.read_text() == "png"
    # GIMP 3's dialect first, then GIMP 2's, each flattening the document
    attempts = log.read_text().splitlines()
    assert len(attempts) == 2
    assert "--batch-interpreter" in attempts[0]
    assert "--batch-interpreter" not in attempts[1]
    assert "gimp-image-flatten" in attempts[1]
    # Writing nothing in either dialect is a failure
    with pytest.raises(ValueError, match="didn't export"):
        calkit.gimp.export(str(source), str(tmp_path / "nothing.png"))
    monkeypatch.setattr(calkit.gimp, "EXECUTABLES", ["calkit-test-no-gimp"])
    assert calkit.gimp.find_executable() is None
    with pytest.raises(ValueError, match="needs GIMP installed"):
        calkit.gimp.export(str(source), str(out))
