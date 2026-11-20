"""Tests for ``calkit.cli.quarto``."""

import json
import os
import stat
import subprocess
import sys

import calkit


def test_prepare(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def prepare(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "calkit", "quarto", "prepare", *args],
            capture_output=True,
            text=True,
        )

    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"name": "test"}, f)
    (tmp_path / "results.json").write_text(json.dumps({"rms": 0.123456}))
    (tmp_path / "report.qmd").write_text(
        "RMS is {{< ckvalue results.json rms .3f >}}.\n"
    )
    # Quarto rendered outside any environment, from wherever it's installed
    # on this machine, has to be a declared requirement
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    quarto = bin_dir / "quarto"
    quarto.write_text(f"#!/bin/sh\necho {bin_dir}\necho {tmp_path}/share\n")
    quarto.chmod(quarto.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    res = prepare("-e", "_system", "report.qmd")
    assert res.returncode != 0
    assert "Quarto isn't in an environment" in res.stdout + res.stderr
    assert str(bin_dir) in res.stdout + res.stderr
    assert not (tmp_path / "_calkit").exists()
    # Declared, it's fine, and the document's values are written beside it
    # with the shortcode that shows them
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"name": "test", "requirements": ["quarto"]}, f)
    res = prepare("-e", "_system", "report.qmd")
    assert res.returncode == 0, res.stdout + res.stderr
    values = json.loads(
        (tmp_path / "_calkit" / "values" / "report.json").read_text()
    )
    assert values == {"results.json\trms\t.3f": "0.123"}
    assert (tmp_path / "_calkit" / "calkit.lua").is_file()
    # Without an environment to check, it only resolves values, and a
    # mistake fails the stage, naming where it is
    (tmp_path / "report.qmd").write_text(
        "\nRMS is {{< ckvalue results.json nope >}}.\n"
    )
    res = prepare("report.qmd")
    assert res.returncode != 0
    assert "has no key 'nope'" in res.stdout + res.stderr
    assert "report.qmd:2" in res.stdout + res.stderr
    # Run from a stage's working directory, values are read from the
    # project, and written beside the document
    (tmp_path / "pub").mkdir()
    (tmp_path / "pub" / "index.qmd").write_text(
        "{{< ckvalue results.json rms .1f >}}\n"
    )
    res = subprocess.run(
        [sys.executable, "-m", "calkit", "quarto", "prepare"]
        + ["--project-dir", "..", "index.qmd"],
        capture_output=True,
        text=True,
        cwd="pub",
    )
    assert res.returncode == 0, res.stdout + res.stderr
    values = json.loads(
        (tmp_path / "pub" / "_calkit" / "values" / "index.json").read_text()
    )
    assert values == {"results.json\trms\t.1f": "0.1"}
