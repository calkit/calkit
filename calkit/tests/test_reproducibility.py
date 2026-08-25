"""Tests for ``calkit.reproducibility``."""

import os
import subprocess

import calkit
from calkit.dvc import run_dvc_command
from calkit.reproducibility import ReproCheck, check_reproducibility


def test_check_reproducibility(tmp_dir):
    res = check_reproducibility()
    assert not res.is_git_repo
    subprocess.run(["git", "init"])
    res = check_reproducibility()
    assert res.is_git_repo
    assert not res.is_dvc_repo
    assert not res.has_readme
    assert "no README.md" in res.recommendation  # type: ignore
    run_dvc_command(["init"])
    res = check_reproducibility()
    assert res.is_dvc_repo
    assert res.n_dvc_remotes == 0
    assert not res.has_calkit_info
    assert not res.has_dev_container
    assert not res.has_pipeline
    print(res.to_pretty())
    with open("README.md", "w") as f:
        f.write("Simply execute `calkit run` to reproduce.")
    res = check_reproducibility()
    assert res.has_readme
    assert res.instructions_in_readme
    # Attribution counts as provenance alongside a stage or an import, for
    # datasets, figures, publications, and misc alike; an entry with none
    # of them is what gets flagged
    ck_info: dict = {
        "datasets": [
            {"path": "raw.csv", "created_by": {"email": "me@x.edu"}},
            {"path": "pub.csv", "imported_from": {"doi": "10.1234/x"}},
            {"path": "out.csv", "stage": "make"},
            {"path": "mystery.csv"},
        ],
        "figures": [
            {"path": "schematic.png", "created_by": {"email": "me@x.edu"}},
            {"path": "mystery.png"},
        ],
        "publications": [
            {"path": "paper.pdf", "imported_from": {"doi": "10.1234/y"}}
        ],
        "misc": [
            {"path": "rig.jpg", "created_by": {"email": "me@x.edu"}},
            {"path": "solver.toml", "imported_from": {"url": "https://x"}},
            {"path": "mystery.bin"},
        ],
        "tables": [
            {"path": "results.csv", "stage": "summarize"},
            {"path": "mystery.csv"},
        ],
        "presentations": [
            {"path": "talk.pdf", "stage": "build-talk"},
        ],
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    res = check_reproducibility()
    assert res.n_datasets == 4
    assert res.n_datasets_no_import_or_stage == 1
    assert res.n_datasets_with_import_or_stage == 3
    assert res.n_figures == 2
    assert res.n_figures_no_import_or_stage == 1
    assert res.n_publications_no_import_or_stage == 0
    assert res.n_misc == 3
    assert res.n_misc_no_import_or_stage == 1
    assert res.n_misc_with_import_or_stage == 2
    assert res.n_tables == 2
    assert res.n_tables_no_import_or_stage == 1
    assert res.n_tables_with_import_or_stage == 1
    assert res.n_presentations == 1
    assert res.n_presentations_no_import_or_stage == 0
    assert res.n_presentations_with_import_or_stage == 1
    assert "Misc with provenance recorded" in res.to_pretty()
    assert "Tables with provenance recorded" in res.to_pretty()
    # Nothing tracked yet, so no scripts to flag, and the mystery misc
    # artifact isn't of a kind that's hard to make by hand
    assert res.scripts_not_in_pipeline == []
    assert res.misc_needing_provenance == []
    # A PNG or a docx with nothing recorded is flagged on its own: nobody
    # makes one by hand, so there's a stage, an export, or a person to name
    ck_info["misc"] += [
        {"path": "plot.png"},
        {"path": "notes.md"},
        {"path": "report.docx", "created_by": {"email": "me@x.edu"}},
        {"path": "slides.PPTX"},
    ]
    # Scripts are the tracked ones no stage names, in either pipeline;
    # tooling and environment directories don't count, nor do untracked
    # files, and a nested project's files are relative to it
    ck_info["environments"] = {
        "py": {"kind": "venv", "path": "requirements.txt", "prefix": "myenv"}
    }
    ck_info["pipeline"] = {
        "stages": {
            "nb": {
                "kind": "jupyter-notebook",
                "notebook_path": "analysis.ipynb",
                "environment": "py",
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("dvc.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "stages": {
                    "plot": {
                        "cmd": "calkit xenv -n py -- python scripts/plot.py",
                        "deps": ["./scripts/load.py"],
                    }
                }
            },
            f,
        )
    for path in [
        "scripts/plot.py",
        "scripts/load.py",
        "scripts/orphan.py",
        "analysis.ipynb",
        "explore.R",
        "renv/activate.R",
        ".devcontainer/setup.sh",
        "myenv/hook.sh",
        "requirements.txt",
        "untracked.py",
    ]:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write("")
    subprocess.check_call(
        [
            "git",
            "add",
            "--",
            "scripts",
            "analysis.ipynb",
            "explore.R",
            "renv",
            ".devcontainer",
            "myenv",
            "requirements.txt",
        ]
    )
    res = check_reproducibility()
    assert res.misc_needing_provenance == ["plot.png", "slides.PPTX"]
    assert res.n_misc_needing_provenance == 2
    assert res.n_misc_no_import_or_stage == 4
    assert res.scripts_not_in_pipeline == ["explore.R", "scripts/orphan.py"]
    assert res.n_scripts_not_in_pipeline == 2
    assert "Scripts not run by any pipeline stage: 2" in res.to_pretty()
    assert "lacking provenance: 2" in res.to_pretty()
    # Both make it into the recommendation once the basics are in place,
    # scripts first, since an unrun script is a gap in the pipeline itself
    good = res.model_dump(exclude={"recommendation"}) | {
        "n_dvc_remotes": 1,
        "has_pipeline": True,
        "stages_without_env": [],
    }
    rec = ReproCheck.model_validate(good).recommendation
    assert "2 scripts (explore.R, scripts/orphan.py)" in rec  # type: ignore
    rec = ReproCheck.model_validate(
        good | {"scripts_not_in_pipeline": []}
    ).recommendation
    assert "2 misc artifacts (plot.png, slides.PPTX)" in rec  # type: ignore
    rec = ReproCheck.model_validate(
        good | {"scripts_not_in_pipeline": [], "misc_needing_provenance": []}
    ).recommendation
    assert "datasets with no provenance" in rec  # type: ignore


def test_check_call():
    out = (
        subprocess.check_output(
            ["calkit", "check", "call", "echo sup", "--if-error", "echo yo"]
        )
        .decode()
        .strip()
        .split("\n")
    )
    out = [v.strip() for v in out]
    assert "sup" in out
    assert "yo" not in out
    out = (
        subprocess.check_output(
            ["calkit", "check", "call", "sup", "--if-error", "echo yo"]
        )
        .decode()
        .strip()
        .split("\n")
    )
    out = [v.strip() for v in out]
    assert "yo" in out
