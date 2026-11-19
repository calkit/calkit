"""Tests for ``calkit.pipeline.detect``."""

import subprocess

import pytest

from calkit.pipeline.detect import detect_stage, normalize_command


def test_detect_stage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.check_call(["git", "init", "-q"])
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'p'\n")
    # A uv run prefix names the environment, unless one's given
    assert normalize_command(["uv", "run", "plot.py"]) == (
        ["plot.py"],
        "pyproject.toml",
    )
    assert normalize_command(["uv", "run", "plot.py"], "py") == (
        ["plot.py"],
        "py",
    )
    with pytest.raises(ValueError, match="No command"):
        normalize_command(["uv", "run"])
    # A script's stage, with a new environment from what it imports, and
    # the paths it reads and writes, without writing anything
    (tmp_path / "pyproject.toml").unlink()
    (tmp_path / "plot.py").write_text(
        "import pandas as pd\n"
        "df = pd.read_csv('data/raw.csv')\n"
        "df.to_csv('results/out.csv')\n"
    )
    ck_info: dict = {}
    detection = detect_stage(["plot.py"], ck_info)
    assert detection.stage.name == "plot"
    assert detection.stage.stage["kind"] == "python-script"
    assert detection.stage.stage["inputs"] == ["data/raw.csv"]
    assert [o["path"] for o in detection.stage.stage["outputs"]] == [
        "results/out.csv"
    ]
    assert not detection.environment.exists
    assert "pandas" in detection.environment.dependencies
    assert detection.language == "python"
    assert sorted(p.name for p in tmp_path.iterdir()) == [".git", "plot.py"]
    # Shaped as 'calkit xr --dry-run --json' prints it
    assert set(detection.model_dump()) == {
        "environment",
        "stage",
        "external_inputs",
    }
    # Whatever the case of its extension
    for name, kind in [("other.r", "r-script"), ("Other.PY", "python-script")]:
        (tmp_path / name).write_text("x = 1\n")
        assert detect_stage([name], ck_info).stage.stage["kind"] == kind
    # Declared paths are kept, and none found without looking
    detection = detect_stage(
        ["plot.py"], ck_info, inputs=["data"], detect_paths=False
    )
    assert detection.stage.stage["inputs"] == ["data"]
    assert "outputs" not in detection.stage.stage
    # A stage already by that name has to be like it
    ck_info = {
        "pipeline": {
            "stages": {"plot": {"kind": "shell-command", "command": "echo hi"}}
        }
    }
    with pytest.raises(ValueError, match="already exists"):
        detect_stage(["plot.py"], ck_info, stage_name="plot")
    # Otherwise it gets the next free name
    detection = detect_stage(["plot.py"], ck_info)
    assert detection.stage.name == "plot-2"
    assert detection.notes


def test_get_stage_from_script_plan(tmp_path):
    from calkit.pipeline import write_stage_from_script
    from calkit.pipeline.detect import get_stage_from_script_plan

    subprocess.check_call(["git", "init", "-q"], cwd=tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "raw.csv").write_text("x\n1\n")
    (tmp_path / "paper" / "figures").mkdir(parents=True)
    (tmp_path / "paper" / "paper.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includegraphics{figures/fit.png}\n\\end{document}\n"
    )
    # The copy uploaded to Overleaf, which the document shows now
    (tmp_path / "paper" / "figures" / "fit.png").write_bytes(b"png")
    subprocess.check_call(["git", "add", "-A"], cwd=tmp_path)
    subprocess.check_call(
        ["git", "-c", "user.name=a", "-c", "user.email=a@b.c", "commit"]
        + ["-qm", "Init"],
        cwd=tmp_path,
    )
    detected = {
        "environment": {
            "name": "py",
            "exists": False,
            "created_from_dependencies": True,
            "env": {"kind": "uv", "path": "pyproject.toml"},
            "spec_path": "pyproject.toml",
            "spec_content": "[project]\nname = 'p'\n",
            "dependencies": ["pandas"],
        },
        "stage": {
            "name": "plot",
            "stage": {
                "kind": "python-script",
                "script_path": "scripts/plot.py",
                "environment": "py",
                "inputs": ["data/raw.csv", "data/new.csv", "data/up.csv"],
                "outputs": ["figures/fit.png"],
            },
        },
        "external_inputs": ["/Users/me/runs"],
    }
    ck_info = {"overleaf_sync": {"paper": {}}}
    # What a document shows is matched to the output with its file name,
    # with the document changed to show it from there
    plan = get_stage_from_script_plan(
        "scripts/plot.py",
        detected,
        ck_info,
        wdir=str(tmp_path),
        shows="paper/figures/fit.png",
        data_paths=["data/up.csv"],
    )
    assert plan["produces"] == "figures/fit.png"
    assert list(plan["included"]) == ["paper/paper.tex"]
    assert "\\ckfigure{figures/fit.png}" in plan["included"]["paper/paper.tex"]
    # Nothing needs the copy once the document shows the stage's output,
    # unless calkit.yaml says something about it
    assert plan["replaced"] == "paper/figures/fit.png"
    kept = get_stage_from_script_plan(
        "scripts/plot.py",
        detected,
        ck_info | {"figures": [{"path": "paper/figures/fit.png"}]},
        wdir=str(tmp_path),
        shows="paper/figures/fit.png",
    )
    assert kept["replaced"] is None
    # Nor if it has changes Git doesn't have, or another file names it
    for change in ["edit", "mention"]:
        if change == "edit":
            (tmp_path / "paper" / "figures" / "fit.png").write_bytes(b"new")
        else:
            (tmp_path / "slides.md").write_text("![](paper/figures/fit.png)\n")
            subprocess.check_call(["git", "add", "slides.md"], cwd=tmp_path)
        assert (
            get_stage_from_script_plan(
                "scripts/plot.py",
                detected,
                ck_info,
                wdir=str(tmp_path),
                shows="paper/figures/fit.png",
            )["replaced"]
            is None
        )
        subprocess.check_call(
            ["git", "checkout", "-q", "HEAD", "--", "paper"], cwd=tmp_path
        )
        subprocess.check_call(
            ["git", "rm", "-q", "--cached", "--ignore-unmatch", "slides.md"],
            cwd=tmp_path,
        )
        (tmp_path / "slides.md").unlink(missing_ok=True)
    # Only what isn't here, made, or uploaded with it is missing
    assert plan["missing_inputs"] == ["data/new.csv"]
    assert plan["external_inputs"] == ["/Users/me/runs"]
    assert plan["environment_spec_path"] == "pyproject.toml"
    # An output it doesn't write can't be picked
    with pytest.raises(ValueError, match="doesn't write 'other.png'"):
        get_stage_from_script_plan(
            "scripts/plot.py",
            detected,
            ck_info,
            wdir=str(tmp_path),
            shows="paper/figures/fit.png",
            produces="other.png",
        )
    # Not shown anywhere it can be shown from, so it's made where it's shown
    plan_here = get_stage_from_script_plan(
        "scripts/plot.py",
        detected,
        ck_info,
        wdir=str(tmp_path),
        shows="paper/figures/drawn.png",
    )
    assert plan_here["produces"] == "paper/figures/drawn.png"
    assert plan_here["replaced"] is None
    assert "paper/figures/drawn.png" in plan_here["outputs"]
    assert not plan_here["included"]
    # A stage already running it keeps what it declares
    existing = {
        "pipeline": {
            "stages": {
                "plot": {
                    **detected["stage"]["stage"],
                    "inputs": [{"kind": "env-var", "name": "SEED"}],
                    "outputs": ["figures/extra.png"],
                }
            }
        }
    }
    merged = get_stage_from_script_plan(
        "scripts/plot.py", detected, existing, wdir=str(tmp_path)
    )
    assert merged["outputs"] == ["figures/extra.png", "figures/fit.png"]
    assert merged["stage"]["inputs"][0] == {"kind": "env-var", "name": "SEED"}
    # By whatever name, and in the environment it runs in, rather than a
    # second stage for the same script in a new one
    existing["pipeline"]["stages"] = {
        "figures": existing["pipeline"]["stages"]["plot"]
        | {"environment": "main"}
    }
    existing["environments"] = {"main": {"kind": "uv", "path": "uv.lock"}}
    merged = get_stage_from_script_plan(
        "scripts/plot.py", detected, existing, wdir=str(tmp_path)
    )
    assert merged["stage_name"] == "figures"
    assert merged["environment"] == "main"
    assert not merged["environment_is_new"]
    assert merged["stage"]["environment"] == "main"
    # Written: the stage, the environment, its spec, and the document
    written = write_stage_from_script(plan, ck_info, wdir=str(tmp_path))
    assert sorted(written) == [
        "paper/figures/fit.png",
        "paper/paper.tex",
        "pyproject.toml",
    ]
    assert not (tmp_path / "paper" / "figures" / "fit.png").exists()
    assert ck_info["pipeline"]["stages"]["plot"] == plan["stage"]
    assert ck_info["environments"]["py"] == detected["environment"]["env"]
    assert (tmp_path / "pyproject.toml").read_text().startswith("[project]")
    assert "\\ckfigure" in (tmp_path / "paper" / "paper.tex").read_text()
    # An invalid stage isn't written
    bad = plan | {"stage": {"kind": "nope"}, "included": {}}
    with pytest.raises(ValueError, match="Invalid stage"):
        write_stage_from_script(bad, {}, wdir=str(tmp_path))
