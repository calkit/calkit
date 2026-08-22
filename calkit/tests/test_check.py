"""Tests for ``calkit.check``."""

import subprocess

import calkit
from calkit.check import check_reproducibility
from calkit.dvc import run_dvc_command


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
    ck_info = {
        "datasets": [
            {"path": "raw.csv", "collected_by": {"email": "me@x.edu"}},
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
