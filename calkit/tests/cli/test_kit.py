"""Tests for ``calkit.cli.kit``."""

import io
import os
import subprocess
import zipfile

from typer.testing import CliRunner

import calkit.hub
import calkit.kits
from calkit.cli.main import app

runner = CliRunner()


def test_create(kit_project, monkeypatch):
    # Written beside where it's run, leaving the original alone
    res = runner.invoke(app, ["kit", "create", "figures/fig.png"])
    assert res.exit_code == 0, res.stdout
    assert "Wrote fig.calkit.png (calkit:" in res.stdout
    kit = calkit.kits.read("fig.calkit.png")
    assert kit is not None
    assert kit.manifest.source.up_to_date
    assert calkit.kits.read("figures/fig.png") is None
    # Data that doesn't fit is left out and reported
    res = runner.invoke(
        app,
        [
            "kit",
            "create",
            "figures/fig.pdf",
            "-o",
            "small.pdf",
            "--max-size",
            "1KB",
        ],
    )
    assert res.exit_code == 0, res.stdout
    assert "Left out 4 files" in res.stdout
    res = runner.invoke(
        app, ["kit", "create", "figures/fig.pdf", "--max-size", "big"]
    )
    assert res.exit_code != 0
    assert "Invalid size" in res.stdout + str(res.stderr)
    # An out-of-date pipeline needs --force, and the calkit says so
    with open("data/raw.csv", "a") as f:
        f.write("1,1\n")
    args = ["kit", "create", "figures/fig.png", "-o", "a.png"]
    res = runner.invoke(app, args)
    assert res.exit_code != 0
    assert "Out of date: make" in res.stdout + str(res.stderr)
    res = runner.invoke(app, [*args, "--force"])
    assert res.exit_code == 0, res.stdout
    kit = calkit.kits.read("a.png")
    assert kit is not None
    assert not kit.manifest.source.up_to_date
    assert "Uncommitted changes" in res.stdout + str(res.stderr)
    subprocess.check_call(["dvc", "checkout", "-q", "--force", "data/raw.csv"])
    # Copied to the clipboard as a file
    copied = []
    monkeypatch.setattr(
        "calkit.kits.copy_to_clipboard", lambda path: copied.append(path)
    )
    res = runner.invoke(
        app, ["kit", "create", "figures/fig.svg", "--to-clipboard"]
    )
    assert res.exit_code == 0, res.stdout
    assert copied == ["fig.calkit.svg"]
    assert "Copied fig.calkit.svg to clipboard" in res.stdout
    # Only what a stage makes can carry a calkit
    res = runner.invoke(app, ["kit", "create", "scripts/make.py"])
    assert res.exit_code != 0
    assert "No pipeline stage makes" in res.stdout + str(res.stderr)


def test_expand_run_open(kit_project, tmp_path, monkeypatch):
    kit_path = str(tmp_path / "fig.png")
    calkit.kits.write_copy("figures/fig.png", kit_path, up_to_date=True)
    small_path = str(tmp_path / "small.png")
    calkit.kits.write_copy(
        "figures/fig.png", small_path, up_to_date=True, max_size=1000
    )
    os.chdir(tmp_path)
    # Expanding defaults to the project's name, and says what's missing
    res = runner.invoke(app, ["kit", "expand", small_path])
    assert res.exit_code == 0, res.stdout
    assert "Expanded into kit-test" in res.stdout
    assert "Left out of calkit: 4 files" in res.stdout
    assert os.path.isfile("kit-test/figures/fig.png")
    assert os.path.isfile("kit-test/scripts/make.py")
    assert not os.path.exists("kit-test/data/raw.csv")
    res = runner.invoke(app, ["kit", "expand", small_path])
    assert res.exit_code != 0
    assert "isn't empty" in res.stdout + str(res.stderr)
    res = runner.invoke(app, ["kit", "expand", "kit-test/scripts/make.py"])
    assert res.exit_code != 0
    assert "has no calkit" in res.stdout + str(res.stderr)
    # Opening opens the expanded project in an editor, or the original on
    # the hub at the commit it came from
    opened = []
    monkeypatch.setattr(
        "calkit.cli.open_.open_project",
        lambda **kwargs: opened.append(kwargs),
    )
    res = runner.invoke(app, ["kit", "open", small_path])
    assert res.exit_code == 0, res.stdout
    assert opened[-1]["checkout"] == "kit-test"
    assert opened[-1]["file_path"] == "figures/fig.png"
    launched = []
    monkeypatch.setattr(
        "calkit.cli.kit.typer.launch", lambda url: launched.append(url)
    )
    res = runner.invoke(app, ["kit", "open", small_path, "--hub"])
    assert res.exit_code == 0, res.stdout
    assert launched[-1].startswith(
        calkit.hub.get_hub_url().rstrip("/")
        + "/someone/kit-test/files?path=figures%2Ffig.png&ref="
    )
    # Running reruns the pipeline and checks the file comes out the same
    res = runner.invoke(app, ["kit", "run", kit_path, "rerun", "--yes"])
    assert res.exit_code == 0, res.stdout
    assert "Reproduced figures/fig.png: identical" in res.stdout
    # It can't without inputs that weren't included and can't be pulled
    res = runner.invoke(
        app, ["kit", "run", small_path, "rerun-small", "--yes"]
    )
    assert res.exit_code != 0
    assert "Missing inputs: data/raw.csv" in res.stdout + str(res.stderr)
    # A file that comes out different from the shared one is reported
    kit = calkit.kits.read(kit_path)
    assert kit is not None
    changed = kit.manifest.model_copy(deep=True)
    changed.artifact.sha256 = "0" * 64
    changed.source.name = "../evil"
    with zipfile.ZipFile(io.BytesIO(kit.kit)) as z:
        entries = {name: (z.read(name), False) for name in z.namelist()}
    entries[calkit.kits.MANIFEST_NAME] = (
        changed.model_dump_json(by_alias=True).encode(),
        False,
    )
    with open("changed.png", "wb") as f:
        f.write(
            calkit.kits.embed(
                kit.artifact, "changed.png", calkit.kits.write_zip(entries)
            )
        )
    res = runner.invoke(app, ["kit", "run", "changed.png", "--yes"])
    assert res.exit_code != 0
    # Its name, from whoever made it, only names a folder here
    assert "Expanded into evil" in res.stdout
    assert "differs from the shared file" in res.stdout + str(res.stderr)
