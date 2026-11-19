import os
import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner


def test_update_pptx_figures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from calkit.cli.main.core import app

    monkeypatch.chdir(tmp_path)
    shutil.copy(
        os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "test", "figures.pptx"
        ),
        "deck.pptx",
    )
    Image.new("RGB", (600, 200), "orange").save("wide.png")
    original = Path("deck.pptx").read_bytes()
    # A slide's only picture and one named on a slide with two, in place
    result = CliRunner().invoke(
        app,
        [
            "office",
            "update-pptx-figures",
            "deck.pptx",
            "-f",
            "1=wide.png",
            "--figure",
            "2:Logo=wide.png",
        ],
    )
    assert result.exit_code == 0, result.output
    with zipfile.ZipFile("deck.pptx") as z:
        stored = [z.read(n) for n in z.namelist() if "/media/calkit-" in n]
    assert stored == [Path("wide.png").read_bytes()]
    # Or into another file
    Path("deck.pptx").write_bytes(original)
    result = CliRunner().invoke(
        app,
        ["office", "update-pptx-figures", "deck.pptx", "-f", "1=wide.png"]
        + ["-o", "out/deck.pptx"],
    )
    assert result.exit_code == 0, result.output
    assert Path("deck.pptx").read_bytes() == original
    assert Path("out/deck.pptx").is_file()
    # What it can't do says why
    for spec, error in [
        ("two=wide.png", "should be SLIDE:PICTURE=FIGURE"),
        ("2=wide.png", "has 2 pictures"),
        ("1:Nope=wide.png", "no picture named 'Nope'"),
    ]:
        result = CliRunner().invoke(
            app, ["office", "update-pptx-figures", "deck.pptx", "-f", spec]
        )
        assert result.exit_code != 0
        assert error in result.output
    assert Path("deck.pptx").read_bytes() == original
