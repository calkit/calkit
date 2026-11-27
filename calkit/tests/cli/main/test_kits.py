"""Tests for ``calkit.cli.main.kits``."""

import os

from typer.testing import CliRunner

import calkit.kits
from calkit.cli.main import app

runner = CliRunner()


def test_expand(kit_project, tmp_path):
    kit_path = str(tmp_path / "fig.png")
    calkit.kits.write_copy(
        "figures/fig.png", kit_path, up_to_date=True, max_size=1000
    )
    # Defaults to the project's name, and says what's missing
    os.chdir(tmp_path)
    res = runner.invoke(app, ["expand", kit_path])
    assert res.exit_code == 0, res.stdout
    assert "Expanded into kit-test" in res.stdout
    assert "Left out of kit: 4 files" in res.stdout
    assert os.path.isfile("kit-test/figures/fig.png")
    assert os.path.isfile("kit-test/scripts/make.py")
    assert not os.path.exists("kit-test/data/raw.csv")
    res = runner.invoke(app, ["expand", kit_path])
    assert res.exit_code != 0
    assert "isn't empty" in res.stdout + str(res.stderr)
    res = runner.invoke(app, ["expand", "kit-test/scripts/make.py"])
    assert res.exit_code != 0
    assert "has no kit" in res.stdout + str(res.stderr)
