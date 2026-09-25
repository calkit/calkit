"""Tests for what a project started from a template looks like."""


def test_clear_template_pipeline_outputs(tmp_path) -> None:
    # A project started from a template hasn't run the pipeline yet.
    from app.api.routes.projects.core import _clear_template_pipeline_outputs

    repo_dir = tmp_path / "repo"
    (repo_dir / "figures").mkdir(parents=True)
    (repo_dir / "results").mkdir()
    (repo_dir / "paper").mkdir()
    (repo_dir / "figures" / "plot.png").write_bytes(b"png")
    (repo_dir / "results" / "summary.json").write_text("{}")
    (repo_dir / "paper" / "paper.tex").write_text("\\documentclass{a}")
    # The template's own source, which the project is meant to keep
    (repo_dir / "scripts").mkdir()
    (repo_dir / "scripts" / "plot.py").write_text("print('hi')")
    (repo_dir / "dvc.lock").write_text(
        "schema: '2.0'\n"
        "stages:\n"
        "  plot:\n"
        "    cmd: python scripts/plot.py\n"
        "    deps:\n"
        "      - path: scripts/plot.py\n"
        "    outs:\n"
        "      - path: figures/plot.png\n"
        "        hash: md5\n"
        "      - path: results\n"
        "        hash: md5\n"
        "  paper:\n"
        "    cmd: latexmk paper/paper.tex\n"
        "    outs:\n"
        "      - path: paper/paper.pdf\n"
        "        hash: md5\n"
    )
    removed = _clear_template_pipeline_outputs(str(repo_dir))
    # The record of the template's run goes, which is what says this
    # project's pipeline hasn't been run
    assert not (repo_dir / "dvc.lock").exists()
    assert "dvc.lock" in removed
    # So do its results, file or directory
    assert not (repo_dir / "figures" / "plot.png").exists()
    assert not (repo_dir / "results").exists()
    # An output that was never in the tree (DVC-tracked, so not cloned)
    # is simply nothing to remove
    assert "paper/paper.pdf" not in removed
    # The source the project is starting from stays
    assert (repo_dir / "scripts" / "plot.py").read_text() == "print('hi')"
    assert (repo_dir / "paper" / "paper.tex").exists()
    # Nothing to do for a project not started from a template
    assert _clear_template_pipeline_outputs(str(repo_dir)) == []
