"""Tests for ``calkit.reproducibility``."""

import os
import subprocess

import calkit
from calkit.dvc import run_dvc_command
from calkit.reproducibility import (
    ReproCheck,
    check_reproducibility,
    find_untraceable_literals,
)


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


def test_find_untraceable_literals():
    def values(tex, from_json=None):
        return [
            f["value"]
            for f in find_untraceable_literals(tex, "main.tex", from_json)
        ]

    # A result-like number typed into the document, in each of the forms
    # one gets written in
    assert values("Here is a hardcoded decimal: 3.14.") == ["3.14"]
    assert values("And another one in math mode: $0.42$.") == ["0.42"]
    assert values(r"Uncertainty $0.42 \pm 0.03$ is flagged.") == [
        r"0.42 \pm 0.03"
    ]
    assert values("Scientific $1.2e-3$ is flagged.") == ["1.2e-3"]
    assert values(r"But this 12.7\% is flagged.") == [r"12.7\%"]
    # The check under-flags on purpose: a false positive on a number that
    # belongs in the text as written costs more than a missed one. So a
    # reference, a citation, a link, a year, a page range, a layout length
    # and a bare integer are all left alone.
    for tex in [
        r"reported \resultCd in the text",
        r"\cite{smith2020}",
        r"\href{https://example.com}{the value 1.2}",
        r"\url{http://9.8.7.6/data}",
        "10.1017/jfm.2020.123",
        "2023",
        r"pp.\ 123--145",
        "we ran 12 simulations",
        "% ... 9.81 ...",
        r"\begin{thebibliography} 4.56 \end{thebibliography}",
        r"\includegraphics[width=0.8\textwidth]{fig.pdf}",
        r"\setlength{\parindent}{0.5in}",
        r"\geometry{margin=1.5cm}",
        r"See Fig.~\ref{fig:1} and Eq.~\eqref{eq:2}",
    ]:
        assert values(tex) == [], tex
    # A value the project computes is accounted for, whatever spacing the
    # document wrote it with, and whether it is offered as a set or a dict
    assert values("... 1.23 ...", {"1.23": None}) == []
    assert values("... 1.23 ...", {"1.23"}) == []
    assert values(r"$0.42 \pm 0.03$", {r"0.42\pm0.03"}) == []
    # A finding says what it is and where, so an editor can jump to it
    findings = find_untraceable_literals(
        "line one\nand then 3.14 here\n", "paper/main.tex"
    )
    assert len(findings) == 1
    assert findings[0]["value"] == "3.14"
    assert findings[0]["file"] == "paper/main.tex"
    assert findings[0]["line"] == 2
    assert findings[0]["column"] == 10
    assert findings[0]["context"] == "and then 3.14 here"
    assert findings[0]["reason"]
    # The fix points at the stage kind, not at a hand-written DVC command
    assert "json-to-latex" in findings[0]["suggestion"]
    # Reported in the order someone reads the file
    assert [
        f["line"]
        for f in find_untraceable_literals("9.99\n1.11\n", "main.tex")
    ] == [1, 2]


def test_unpinned_git_imports_are_reported(tmp_dir):
    # An import that names a branch to follow but no commit says where the
    # file comes from without saying which version is here, so it can't
    # count as full provenance the way a pinned one does
    import subprocess

    import calkit
    from calkit.reproducibility import check_reproducibility

    subprocess.run(["calkit", "init"], check=True)
    # So the recommendation isn't dominated by something more basic
    with open("README.md", "w") as f:
        f.write("# Project\n\nHow to reproduce: run `calkit run`.\n")
    sha = "0123456789abcdef0123456789abcdef01234567"
    repo_url = "https://github.com/o/r.git"
    ck_info = calkit.load_calkit_info()
    ck_info["misc"] = [
        {
            "path": "unpinned.sh",
            "imported_from": {
                "git": {"repo_url": repo_url, "path": "a.sh", "ref": "main"}
            },
        },
        {
            "path": "pinned.sh",
            "imported_from": {
                "git": {"repo_url": repo_url, "path": "a.sh", "rev": sha}
            },
        },
        # Not a Git source, so there is no commit to be missing
        {
            "path": "downloaded.csv",
            "imported_from": {"url": "https://example.invalid/a.csv"},
        },
    ]
    calkit.save_calkit_info(ck_info)
    check = check_reproducibility(wdir=".")
    assert check.unpinned_imports == ["unpinned.sh"]
    assert check.n_unpinned_imports == 1
    assert "not pinned to a commit" in check.to_pretty()
    # The recommendation is ordered, so a project with more basic problems
    # is told about those first. Asked directly, it names the fix.
    assert (
        "calkit update path"
        in check.model_copy(
            update={
                "has_readme": True,
                "instructions_in_readme": True,
                "n_dvc_remotes": 1,
                "has_pipeline": True,
                "has_calkit_info": True,
                "n_environments": 1,
            }
        ).recommendation
    )
