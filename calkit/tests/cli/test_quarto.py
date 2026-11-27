"""Tests for ``calkit.cli.quarto``."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import calkit


@pytest.mark.skipif(sys.platform == "win32", reason="Uses a shell script")
def test_render(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def render(*args: str, cwd: str = ".") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "calkit", "quarto", "render", *args],
            capture_output=True,
            text=True,
            cwd=cwd,
        )

    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"name": "test"}, f)
    (tmp_path / "results.json").write_text(json.dumps({"rms": 0.123456}))
    (tmp_path / "report.qmd").write_text(
        "RMS is {{< ckvalue results.json rms .3f >}}.\n"
    )
    # A stand-in for Quarto installed on this machine, which records how it
    # was called
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    quarto = bin_dir / "quarto"
    quarto.write_text(f'#!/bin/sh\necho "$@" > {tmp_path}/called.txt\n')
    quarto.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    # The environment has to be named
    res = render("report.qmd")
    assert res.returncode != 0
    assert "Name the environment" in res.stdout + res.stderr
    assert "_system" in res.stdout + res.stderr
    assert not (tmp_path / "called.txt").exists()
    # In '_system', the machine's is used
    res = render("-e", "_system", "report.qmd")
    assert res.returncode == 0, res.stdout + res.stderr
    (tmp_path / "called.txt").unlink()
    # Declared by the project, the document's values are checked, the
    # extension that shows them is written, and then it's rendered with
    # what's passed
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"name": "test", "requirements": ["quarto"]}, f)
    res = render(
        "-e", "_system", "report.qmd", "--to", "pdf", "--", "--execute"
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert (tmp_path / "called.txt").read_text().split() == [
        "render",
        "report.qmd",
        "--to",
        "pdf",
        "--execute",
    ]
    assert (tmp_path / "_extensions" / "calkit" / "calkit.lua").is_file()
    assert not (tmp_path / "_calkit").exists()
    # A mistake fails before rendering, naming where it is
    (tmp_path / "called.txt").unlink()
    (tmp_path / "report.qmd").write_text(
        "\nRMS is {{< ckvalue results.json nope >}}.\n"
    )
    res = render("-e", "_system", "report.qmd")
    assert res.returncode != 0
    assert "has no key 'nope'" in res.stdout + res.stderr
    assert "report.qmd:2" in res.stdout + res.stderr
    assert not (tmp_path / "called.txt").exists()
    # From a stage's working directory, the project is found above it and
    # values are checked from there, with the extension written in the
    # document's Quarto project
    (tmp_path / "pub").mkdir()
    (tmp_path / "pub" / "_quarto.yml").write_text(
        "project:\n  type: default\n"
    )
    (tmp_path / "pub" / "pages").mkdir()
    (tmp_path / "pub" / "pages" / "index.qmd").write_text(
        "{{< ckvalue results.json rms .1f >}}\n"
    )
    res = render("-e", "_system", "index.qmd", cwd="pub/pages")
    assert res.returncode == 0, res.stdout + res.stderr
    assert (tmp_path / "pub/_extensions/calkit/calkit.lua").is_file()
    # And in an environment, which is defined relative to the project, with
    # Quarto from the environment
    (tmp_path / "called.txt").unlink()
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "name": "test",
                "environments": {
                    "py": {
                        "kind": "venv",
                        "path": "requirements.txt",
                        "prefix": ".venv",
                    }
                },
            },
            f,
        )
    (tmp_path / "requirements.txt").write_text("")
    subprocess.check_call([sys.executable, "-m", "venv", ".venv"])
    # The machine's isn't, unless allowed, e.g., by a stage requiring it
    res = render("-e", "py", "--no-check", "index.qmd", cwd="pub/pages")
    assert res.returncode != 0
    assert "'quarto' isn't in environment 'py'" in res.stdout + res.stderr
    assert not (tmp_path / "called.txt").exists()
    res = render(
        "-e",
        "py",
        "--no-check",
        "--allow-machine-quarto",
        "index.qmd",
        cwd="pub/pages",
    )
    assert res.returncode == 0, res.stdout + res.stderr
    (tmp_path / "called.txt").unlink()
    env_quarto = tmp_path / ".venv" / "bin" / "quarto"
    env_quarto.write_text(quarto.read_text())
    env_quarto.chmod(0o755)
    res = render("-e", "py", "--no-check", "index.qmd", cwd="pub/pages")
    assert res.returncode == 0, res.stdout + res.stderr
    assert (tmp_path / "called.txt").read_text().split() == [
        "render",
        "index.qmd",
    ]


def test_render_as_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from calkit.cli.main.core import app

    monkeypatch.chdir(tmp_path)
    calkit.save_calkit_info(
        {
            "name": "test",
            "pipeline": {
                "stages": {
                    "pub": {
                        "kind": "quarto",
                        "environment": "_system",
                        "wdir": "pub",
                        "target_path": "index.qmd",
                        "to": "html",
                        "args": ["--execute"],
                    },
                }
            },
        }
    )
    os.makedirs("pub")
    Path("pub/index.qmd").write_text("Hi\n")
    Path("other.qmd").write_text("Hi\n")
    calls: list[tuple[list[str], str]] = []
    monkeypatch.setattr(
        subprocess,
        "check_call",
        lambda cmd, **kwargs: calls.append((cmd[1:], os.getcwd())),
    )
    # Rendered as the stage is, from its working directory, wherever it's
    # run from, with extra arguments after the stage's
    for cwd, args in [
        (".", ["pub/index.qmd", "--as-stage"]),
        ("pub", ["index.qmd", "--as-stage", "--", "--no-cache"]),
    ]:
        monkeypatch.chdir(tmp_path / cwd)
        calls.clear()
        result = CliRunner().invoke(app, ["quarto", "render", *args])
        assert result.exit_code == 0, result.output
        cmd, ran_in = calls[0]
        assert cmd == ["render", "index.qmd", "--to", "html", "--execute"] + (
            ["--no-cache"] if "--no-cache" in args else []
        )
        assert os.path.samefile(ran_in, tmp_path / "pub")
        assert os.path.samefile(os.getcwd(), tmp_path / cwd)
    # The stage says how, and there has to be one
    monkeypatch.chdir(tmp_path)
    for args, expected in [
        (["pub/index.qmd", "--as-stage", "-e", "py"], "from the stage"),
        (["other.qmd", "--as-stage"], "No quarto stage renders other.qmd"),
        (
            [str(tmp_path.parent / "x.qmd"), "--as-stage"],
            "isn't in a Calkit project",
        ),
    ]:
        result = CliRunner().invoke(app, ["quarto", "render", *args])
        assert result.exit_code != 0, args
        assert expected in result.output, (args, result.output)
