"""Tests for ``calkit.reproducibility``."""

import json
import os
import subprocess

import pytest

import calkit
from calkit.dvc import run_dvc_command
from calkit.reproducibility import (
    ReproCheck,
    check_reproducibility,
    find_literals_in_project,
    find_retyped_values,
    find_scripts_not_in_pipeline,
    find_unattributed_numbers,
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
            {"path": "schematic.svg", "created_by": {"email": "me@x.edu"}},
            {"path": "mystery.png"},
            # Exported, so a person can't be its origin
            {"path": "exported.png", "created_by": {"email": "me@x.edu"}},
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
    assert res.n_figures == 3
    assert res.n_figures_no_import_or_stage == 2
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
    # A hand-written misc file is its own record, so one with nothing
    # recorded is advice
    assert "Other misc artifacts with no provenance recorded: 1" in (
        res.to_pretty()
    )
    assert "Tables with provenance recorded" in res.to_pretty()
    # What's shown is followed back to its sources: a figure or table with
    # nothing behind it is a gap, while one whose stage isn't compiled yet
    # is taken at its word
    assert res.provenance_gaps == [
        "origin not defined for mystery.png",
        "origin not defined for exported.png",
        "origin not defined for mystery.csv",
    ]
    assert "with origin not defined: 3" in res.to_pretty()
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
    # files, and a nested project's files are relative to it. A folder a
    # stage reads or writes covers the scripts in it, e.g., a package's
    # modules or data written as Python
    ck_info["environments"] = {
        "py": {"kind": "venv", "path": "requirements.txt", "prefix": "myenv"}
    }
    ck_info["pipeline"] = {
        "stages": {
            "nb": {
                "kind": "jupyter-notebook",
                "notebook_path": "analysis.ipynb",
                "environment": "py",
                "inputs": ["src/pkg"],
                "outputs": ["data"],
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
        "src/pkg/mod.py",
        "data/params.py",
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
            "src",
            "data",
        ]
    )
    res = check_reproducibility()
    assert res.misc_needing_provenance == ["plot.png", "slides.PPTX"]
    assert res.n_misc_needing_provenance == 2
    assert res.n_misc_no_import_or_stage == 4
    assert res.scripts_not_in_pipeline == ["explore.R", "scripts/orphan.py"]
    assert res.n_scripts_not_in_pipeline == 2
    assert "Scripts not run by any pipeline stage: 2" in res.to_pretty()
    # A folder that's only named, e.g., like the environment, isn't read or
    # written, so it doesn't cover what's in it
    os.makedirs("py")
    with open("py/tool.py", "w") as f:
        f.write("")
    subprocess.check_call(["git", "add", "py/tool.py"])
    assert "py/tool.py" in find_scripts_not_in_pipeline()
    subprocess.check_call(["git", "rm", "-q", "--cached", "py/tool.py"])
    assert "lacking provenance: 2" in res.to_pretty()
    # Both make it into the recommendation once the basics are in place,
    # problems first: a file nobody makes by hand with nothing recorded is
    # one, while an unrun script is only advice
    good = res.model_dump(exclude={"recommendation"}) | {
        "n_dvc_remotes": 1,
        "has_pipeline": True,
        "stages_without_env": [],
    }
    rec = ReproCheck.model_validate(good).recommendation
    assert "2 misc artifacts (plot.png, slides.PPTX)" in rec  # type: ignore
    good |= {"misc_needing_provenance": []}
    rec = ReproCheck.model_validate(good).recommendation
    assert "e.g., origin not defined for mystery.png" in rec  # type: ignore
    rec = ReproCheck.model_validate(
        good | {"provenance_gaps": []}
    ).recommendation
    assert "datasets with no provenance" in rec  # type: ignore
    rec = ReproCheck.model_validate(
        good
        | {
            "provenance_gaps": [],
            "n_datasets_no_import_or_stage": 0,
            "n_figures_no_import_or_stage": 0,
            "n_tables_no_import_or_stage": 0,
        }
    ).recommendation
    assert "2 scripts (explore.R, scripts/orphan.py)" in rec  # type: ignore
    # What a LaTeX document shows is followed too, whether cited with
    # \\ckfigure or included plainly, and a plain include is fine wherever
    # the pipeline made the file, e.g., copied in by a map-paths stage or
    # written by a json-to-latex one
    ck_info["pipeline"]["stages"]["paper"] = {
        "kind": "latex",
        "target_path": "paper/main.tex",
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("dvc.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "stages": {
                    "plot": {
                        "cmd": "calkit xenv -n py -- python scripts/plot.py",
                        "deps": ["scripts/plot.py"],
                        "outs": ["figures/fit.png", "results/fit.json"],
                    },
                    "copy-figs": {
                        "cmd": "calkit map-paths",
                        "deps": ["figures/fit.png"],
                        "outs": ["paper/figs/fit.png"],
                    },
                    "table": {
                        "cmd": "calkit latex from-json results/fit.json",
                        "deps": ["results/fit.json"],
                        "outs": ["paper/table.tex"],
                    },
                }
            },
            f,
        )
    os.makedirs("paper/figs")
    for path in ["paper/figs/fit.png", "paper/table.tex", "paper/drawn.png"]:
        with open(path, "w") as f:
            f.write("")
    with open("paper/main.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n\\usepackage{calkit}\n"
            "\\begin{document}\n"
            "\\includegraphics{figs/fit}\n\\input{table}\n"
            "\\includegraphics[width=1cm]{drawn.png}\n"
            "\\ckfigure{figures/pasted.png}\n"
            "\\end{document}\n"
        )
    res = check_reproducibility()
    expected = [
        "origin not defined for figures/pasted.png",
        "origin not defined for paper/drawn.png",
    ]
    assert [
        g
        for g in res.provenance_gaps
        if "mystery" not in g and "exported" not in g
    ] == expected
    # The same paper, named relative to its stage's working directory
    ck_info["pipeline"]["stages"]["paper"] = {
        "kind": "latex",
        "wdir": "paper",
        "target_path": "main.tex",
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    res = check_reproducibility()
    assert [
        g
        for g in res.provenance_gaps
        if "mystery" not in g and "exported" not in g
    ] == expected
    # Files outside the project that pipeline scripts and notebooks read or
    # write only exist on one machine, which is found from anywhere, e.g.,
    # by the hub, which doesn't run from the project
    assert res.paths_outside_project == []
    ck_info["pipeline"]["stages"]["fit"] = {
        "kind": "python-script",
        "script_path": "scripts/fit.py",
        "environment": "py",
    }
    # One named relative to its working directory is found there
    ck_info["pipeline"]["stages"]["wake"] = {
        "kind": "python-script",
        "wdir": "analysis",
        "script_path": "wake.py",
        "environment": "py",
    }
    os.makedirs("analysis", exist_ok=True)
    with open("analysis/wake.py", "w") as f:
        f.write('open("/Users/me/Box/wake.csv")\n')
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("scripts/fit.py", "w") as f:
        f.write(
            "import pandas as pd\n"
            'df = pd.read_csv("/Users/me/Box/runs.csv")\n'
            'df.to_csv("data/fit.csv")\n'
            'df.to_csv("../shared/fit.csv")\n'
        )
    with open("analysis.ipynb", "w") as f:
        json.dump(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "source": ['open("~/Desktop/notes.txt")'],
                    }
                ],
                "metadata": {},
            },
            f,
        )
    wdir = os.getcwd()
    os.chdir("paper")
    try:
        res = check_reproducibility(wdir=wdir)
    finally:
        os.chdir(wdir)
    assert sorted(res.paths_outside_project) == [
        "analysis.ipynb reads ~/Desktop/notes.txt",
        "analysis/wake.py reads /Users/me/Box/wake.csv",
        "scripts/fit.py reads /Users/me/Box/runs.csv",
        "scripts/fit.py writes ../shared/fit.csv",
    ]
    assert "outside the project used by pipeline scripts: 4" in (
        res.to_pretty()
    )
    assert "outside" in res.categories_with_detail
    # Read from the code, so they're advice, after any problem
    rec = ReproCheck.model_validate(
        good
        | {
            "paths_outside_project": res.paths_outside_project,
            "provenance_gaps": [],
            "n_datasets_no_import_or_stage": 0,
            "n_figures_no_import_or_stage": 0,
            "n_tables_no_import_or_stage": 0,
        }
    ).recommendation
    assert "4 files outside the project" in rec  # type: ignore


def test_repro_check_summary() -> None:
    # As written before the summary existed, e.g., cached by the hub
    base = {
        "has_pipeline": True,
        "has_readme": True,
        "instructions_in_readme": True,
        "is_dvc_repo": True,
        "is_git_repo": True,
        "has_calkit_info": True,
        "has_dev_container": False,
        "n_environments": 1,
        "n_stages": 1,
        "stages_with_env": ["a"],
        "stages_without_env": [],
        "n_datasets": 0,
        "n_datasets_no_import_or_stage": 0,
        "n_figures": 0,
        "n_figures_no_import_or_stage": 0,
        "n_publications": 0,
        "n_publications_no_import_or_stage": 0,
        "n_dvc_remotes": 0,
    }
    # Without the checks that need the working tree, nothing is claimed
    check = ReproCheck.model_validate(base)
    assert check.passed is None
    assert "Passed" not in check.to_pretty()
    audited = base | {"audited": True}
    check = ReproCheck.model_validate(audited)
    # Nothing declared or read, so only what was checked is shown passing,
    # and advice doesn't fail it
    assert [line.text for line in check.summary if line.ok is not None] == [
        "Is a Git repo"
    ]
    assert [line.text for line in check.summary if line.ok is None] == [
        "No dev container spec"
    ]
    assert check.passed
    assert "Passed" in check.to_pretty()
    # A remote is only advised for what's stored with DVC
    assert "remote" not in check.to_pretty()
    assert "dev container" in check.recommendation  # type: ignore
    check = ReproCheck.model_validate(audited | {"stores_in_dvc": True})
    assert check.passed
    assert (
        "No DVC remote, though files are stored with DVC\n"
        in (check.to_pretty().split("Advice:")[1])
    )
    assert "no DVC remote" in check.recommendation  # type: ignore
    # A project with no pipeline, e.g., of data, isn't failed for it
    check = ReproCheck.model_validate(audited | {"has_pipeline": False})
    assert check.passed
    assert "  No pipeline\n" in check.to_pretty().split("Advice:")[1]
    # What's guessed or doesn't make anything wrong is advice: a script no
    # stage runs is often tooling, e.g., a site's build script, and what it
    # made would be caught on its own; a path outside the project is read
    # from the code, e.g., a system font; and a stage with nothing recorded
    # may have been run with DVC alone
    for field, category in [
        ("scripts_not_in_pipeline", "scripts"),
        ("paths_outside_project", "outside"),
        ("stage_runs_unrecorded", "unrecorded-runs"),
        ("absent_stages", "not-present"),
        ("misc_no_provenance", "misc"),
        ("not_checked", "not-checked"),
        ("eol_rewritten", "rewritten-line-endings"),
    ]:
        check = ReproCheck.model_validate(audited | {field: ["x"]})
        assert check.passed, field
        assert (
            f": 1 [-c {category}]\n" in (check.to_pretty().split("Advice:")[1])
        )
    # Line endings this checkout rewrote are fixed by pinning them, not by
    # rerunning what they made stale
    check = ReproCheck.model_validate(audited | {"eol_rewritten": ["a.py"]})
    assert "calkit fix line-endings" in check.recommendation  # type: ignore
    # Each problem fails it, under its category
    for field, category in [
        ("pipeline_errors", "pipeline-errors"),
        ("stale_stages", "stale"),
        ("uncompiled_stages", "uncompiled"),
        ("stage_run_problems", "stage-runs"),
        ("storage_problems", "storage"),
        ("citation_problems", "citations"),
        ("question_problems", "questions"),
    ]:
        check = ReproCheck.model_validate(audited | {field: ["x"]})
        assert not check.passed
        dumped = json.loads(check.model_dump_json())
        assert not dumped["passed"]
        assert [
            line["category"]
            for line in dumped["summary"]
            if line["ok"] is False
        ] == [category]
        assert check.details(category) == ["x"]
        assert f"[-c {category}]" in check.to_pretty()
        assert "Failed: 1 problem\n" in check.to_pretty()
        assert check.recommendation and "x" in check.recommendation
        # The usage hint names a problem before any advice
        check = ReproCheck.model_validate(
            audited | {field: ["x"], "scripts_not_in_pipeline": ["s.py"]}
        )
        assert check.categories_with_detail[0] == category
        # Checked with nothing wrong, it passes, with nothing to list
        check = ReproCheck.model_validate(audited | {field: []})
        assert check.passed
        if field != "pipeline_errors":
            assert ": 0 " in check.to_pretty()
        assert f"[-c {category}]" not in check.to_pretty()
    # Storage is only fixed with --fix where that fixes it
    check = ReproCheck.model_validate(
        audited | {"storage_problems": ["x."], "storage_fixable": True}
    )
    assert "--fix" in check.recommendation  # type: ignore
    check = ReproCheck.model_validate(audited | {"storage_problems": ["x."]})
    assert "--fix" not in check.recommendation  # type: ignore
    # Declared artifacts are counted, and the ones with nothing recorded
    # are listed
    check = ReproCheck.model_validate(
        audited
        | {
            "n_figures": 2,
            "n_figures_no_import_or_stage": 1,
            "artifacts_no_provenance": ["figures: a.png"],
        }
    )
    assert not check.passed
    assert (
        "Figures with provenance recorded (stage, import, or attribution): 1/2"
    ) in check.to_pretty()
    assert "[-c artifacts]" in check.to_pretty()
    assert "Datasets with provenance" not in check.to_pretty()


def test_check_reproducibility_without_audit(
    tmp_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("DVC work without audit")

    # The hub's check, of the files alone, asks DVC nothing and claims
    # nothing it didn't check
    for name in ["get_status", "get_stage_run_problems", "to_dvc"]:
        monkeypatch.setattr(calkit.pipeline, name, fail)
    subprocess.check_call(["calkit", "init"])
    res = check_reproducibility()
    assert res.passed is None
    assert not res.audited
    for field in [
        "stale_stages",
        "absent_stages",
        "pipeline_errors",
        "uncompiled_stages",
        "stage_run_problems",
        "stage_runs_unrecorded",
        "storage_problems",
        "citation_problems",
        "citations_unconfirmed",
        "question_problems",
        "changed_evidence",
        "not_checked",
    ]:
        assert getattr(res, field) is None, field


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


def test_find_retyped_values(tmp_dir):
    def values(tex, project_values=None):
        return [
            (f["value"], f["line"], f["column"])
            for f in find_retyped_values(tex, "main.tex", project_values)
        ]

    project = {"0.42": "results.json:Cd", "1.25e-05": "results.json:Nu"}
    # The problem worth solving: a value the pipeline produces, typed into
    # the prose, correct today and wrong the next time the stage runs
    assert values("The drag coefficient is 0.42.", project) == [
        ("0.42", 1, 25)
    ]
    assert values("$\\nu = 1.25e-05$", project) == [("1.25e-05", 1, 8)]
    # Every occurrence, since each one goes stale separately
    assert len(values("0.42 and again 0.42", project)) == 2
    # A number the project does not produce is not the paper's problem: a
    # quantity quoted from a reference, chosen by the author, or written
    # as prose has nothing to be traced to
    assert values("Others report 4.75 at that Reynolds number.", project) == []
    assert values("a coefficient of order 0.03", project) == []
    # Not a substring of a longer number
    assert values("10.425 and 0.4251", project) == []
    # Somewhere a number can appear without being a result: a citation, a
    # link, a label, and the options of a figure macro, Calkit's included
    widths = {"0.55": "results.json:Width"}
    assert values(r"\\ckfigure[width=0.55\\textwidth]{../f.pdf}", widths) == []
    assert (
        values(r"\\includegraphics[width=0.55\\textwidth]{f.pdf}", widths)
        == []
    )
    assert values(r"\\cite{smith0.42}", project) == []
    assert values(r"\\href{https://x.org/0.42}{link}", project) == []
    assert values("% a comment with 0.42", project) == []
    # Or on a line marked as not results, whatever else its comment says
    assert values("Cd is 0.42. % calkit: ignore, a coincidence", project) == []
    assert values("Cd is 0.42. \\% calkit: ignore", project) != []
    assert values(r"\\setlength{\\parindent}{0.55in}", widths) == []
    # A value has to be distinctive before its appearance means anything:
    # a small integer or a one-digit decimal turns up in every paper
    assert values("we ran 3 cases", {"3": "results.json:NCases"}) == []
    assert values("about 0.5 of them", {"0.5": "results.json:Frac"}) == []
    assert values("a value of 0.50", {"0.50": "results.json:Frac"}) == [
        ("0.50", 1, 12)
    ]
    # A larger integer is distinctive: a bare 500 in prose is very likely
    # the 500 the config names, where a bare 8 is not
    assert values("500 random restarts", {"500": "results.json:NRandom"}) == [
        ("500", 1, 1)
    ]
    assert values("we used 99 seeds", {"99": "results.json:NSeeds"}) == []
    # Nothing to compare against means nothing to say
    assert values("The drag coefficient is 0.42.") == []
    # A finding names where the value came from, so the fix is obvious
    findings = find_retyped_values(
        "line one\nand then 0.42 here\n", "paper/main.tex", project
    )
    assert len(findings) == 1
    assert findings[0]["source"] == "results.json:Cd"
    assert findings[0]["file"] == "paper/main.tex"
    assert findings[0]["line"] == 2
    assert findings[0]["context"] == "and then 0.42 here"
    assert "results.json:Cd" in findings[0]["reason"]
    # The fix is to read it with calkit.sty, unless the document already
    # reads it through a json-to-latex stage's commands
    assert "\\ckvalue{results.json}{Cd}" in findings[0]["suggestion"]
    assert "json-to-latex" not in findings[0]["suggestion"]
    findings = find_retyped_values(
        "and then 0.42 here", "main.tex", project, {"results.json:Cd"}
    )
    assert "json-to-latex" in findings[0]["suggestion"]
    # Calkit's own commands are masked, whatever their paths and options
    assert (
        values(
            r"\ckvalue[round-precision=0.42]{runs/0.42.json}{Cd}"
            r" \cktable{tables/0.42} \ckinclude{text/0.42}"
            "\n\\ckvalue [.2f] {runs/0.42.json}\n  {Cd} \\cktable {t/0.42}",
            project,
        )
        == []
    )
    # In a project, the results files a document reads with \ckvalue are
    # within its reach, every number a key names at any depth but not those
    # in lists, as are those a json-to-latex stage reads, while what
    # Calkit writes for calkit.sty and tables stages write, one by one or in
    # a folder, aren't manuscripts
    for path, data in {
        "results/drag.json": {
            "Cd": 0.42,
            "cases": {"a": {"cp": 0.7321}},
            "runs": [{"Re": 12500}],
            "history": list(range(3000)),
        },
        "results/lift.json": {"Cl": 1.234},
        "results/wake.json": {"St": 0.215},
    }.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
    files = {
        "paper/main.tex": (
            "\\documentclass{article}\n\\usepackage{calkit}\n"
            "\\begin{document}\n"
            "Read: \\ckvalue[.2f]{results/drag.json}{Cd}.\n"
            "Typed: 0.42 and 0.7321.\n"
            "Not typed: 1000 samples in 2019, run 12500.\n"
            "\\cktable{tables/summary}\n\\input{../gen/t2}\n"
            "\\end{document}\n"
        ),
        "paper/_calkit/values.tex": (
            "\\cksetvalue{results/drag.json}{Cd}{n}{0.42}\n"
        ),
        "tables/summary.tex": "0.42 & 0.7321 \\\\\n",
        "gen/t2.tex": "0.42 & 0.7321 \\\\\n",
        "other/main.tex": (
            "\\documentclass{article}\n\\begin{document}\n"
            "\\input{lift}\nTyped: 1.234 and 0.215.\n\\end{document}\n"
        ),
        "other/lift.tex": "\\newcommand\\lift[1][all]{1.234}\n",
    }
    for path, text in files.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    stages = {
        "table": {
            "cmd": "python table.py",
            "wdir": "scripts",
            "outs": ["../tables/summary.tex"],
        },
        "tables": {"cmd": "python tables.py", "outs": ["gen"]},
        "paper": {
            "cmd": "calkit latex build -e tex --no-check paper/main.tex",
            "deps": [
                "paper/main.tex",
                "results/drag.json",
                "paper/calkit.sty",
                "paper/_calkit/values.tex",
                "tables/summary.tex",
            ],
            "outs": ["paper/main.pdf"],
        },
        "lift": {
            "cmd": "calkit latex from-json results/lift.json "
            "--output other/lift.tex",
            "deps": ["results/lift.json"],
            "outs": ["other/lift.tex"],
        },
        # Its output isn't input by any document, so it isn't the fix
        "wake": {
            "cmd": "calkit latex from-json results/wake.json "
            "--output other/wake.tex",
            "deps": ["results/wake.json"],
            "outs": ["other/wake.tex"],
        },
        "other": {
            "cmd": "calkit latex build other/main.tex",
            "deps": ["other/main.tex"],
            "outs": ["other/main.pdf"],
        },
    }
    retyped = find_literals_in_project(".", {}, stages)["retyped"]
    assert [(f["file"], f["value"], f["source"]) for f in retyped] == [
        ("other/main.tex", "1.234", "results/lift.json:Cl"),
        ("other/main.tex", "0.215", "results/wake.json:St"),
        ("paper/main.tex", "0.42", "results/drag.json:Cd"),
        ("paper/main.tex", "0.7321", "results/drag.json:cases.a.cp"),
    ]
    suggestions = [f["suggestion"] for f in retyped]
    assert "json-to-latex" in suggestions[0]
    assert "\\ckvalue{results/wake.json}{St}" in suggestions[1]
    assert "\\ckvalue{results/drag.json}{cases.a.cp}" in suggestions[3]


def test_find_unattributed_numbers():
    def values(tex, project_values=None):
        return [
            (f["value"], f["line"], f["cited"])
            for f in find_unattributed_numbers(tex, "main.tex", project_values)
        ]

    tex = (
        "The deficit was 0.47.\n"
        "Smith~\\cite{smith} reports 0.52.\n"
        "The pump draws 1.25 kW. % calkit: ignore, from its datasheet\n"
    )
    assert values(tex) == [("0.47", 1, False), ("0.52", 2, True)]
    # One the project computes is left to find_retyped_values
    assert values(tex, {"0.47": "results.json:Deficit"}) == [("0.52", 2, True)]


def test_find_unattributed_numbers_markdown():
    def values(md):
        return [
            (f["value"], f["line"], f["cited"])
            for f in find_unattributed_numbers(md, "index.qmd", markdown=True)
        ]

    md = (
        "---\n"
        "title: Run 2.5\n"
        "---\n"
        "The rotation score exceeds $0.97$, and 12.5% of runs fail.\n"
        "The slope is `{python} f'{slope:.2f}'`, as `x = 0.33` shows.\n"
        "Liu et al. [@liu2025, p. 3.1] report 0.52, and @liu2025 0.61.\n"
        "See @fig-orbit-2.1 and [the data](https://example.com/v1.2).\n"
        "![Orbit](orbit.png){#fig-orbit width=50.5%}\n"
        "We used Python 3.13 and version 2.1 of it.\n"
        "The pump draws 1.25 kW. <!-- calkit: ignore, from its datasheet -->\n"
        "<!-- A note on 0.44 -->\n"
        "```python\n"
        "threshold = 0.25\n"
        "```\n"
        "It drifts by 0.003 ± 0.001 per step.\n"
        "The RMS is <!-- ckvalue r.json rms .4f -->0.2933<!-- /ckvalue -->.\n"
    )
    assert values(md) == [
        ("0.97", 4, False),
        ("12.5%", 4, False),
        ("0.52", 6, True),
        ("0.61", 6, True),
        ("0.003 ± 0.001", 15, False),
    ]
    # A long line, e.g., a Markdown paragraph, is shown around the number
    long = "Words " * 40 + "the score is 0.93 here " + "and more " * 40
    (finding,) = find_unattributed_numbers(long, "index.md", markdown=True)
    assert finding["context"].startswith("…")
    assert finding["context"].endswith("…")
    assert "the score is 0.93 here" in finding["context"]
    assert len(finding["context"]) < 140


def test_check_reproducibility_markdown_numbers(tmp_dir):
    # A notebook a Quarto stage renders is read cell by cell, and so is a
    # Markdown publication, but not a notebook a stage only executes
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {
                "cell_type": "markdown",
                "id": "a",
                "metadata": {},
                "source": ["# Results\n", "\n", "The score exceeds $0.97$."],
            },
            {
                "cell_type": "code",
                "id": "b",
                "metadata": {},
                "execution_count": None,
                "outputs": [],
                "source": "print(0.93)",
            },
        ],
    }
    for path in ["index.ipynb", "explore.ipynb"]:
        with open(path, "w") as f:
            json.dump(nb, f)
    with open("summary.md", "w") as f:
        f.write("Errors fell by 4.5%.\n")
    calkit.save_calkit_info(
        {
            "environments": {"py": {"kind": "uv", "path": "pyproject.toml"}},
            "publications": [{"path": "summary.md", "kind": "report"}],
            "pipeline": {
                "stages": {
                    "pub": {
                        "kind": "quarto",
                        "target_path": "index.ipynb",
                        "environment": "py",
                    },
                    "explore": {
                        "kind": "jupyter-notebook",
                        "notebook_path": "explore.ipynb",
                        "environment": "py",
                    },
                }
            },
        }
    )
    res = check_reproducibility()
    found = [
        (f["file"], f.get("cell"), f["line"], f["value"])
        for f in res.unattributed_numbers
    ]
    assert found == [
        ("index.ipynb", 0, 3, "0.97"),
        ("summary.md", None, 1, "4.5%"),
    ]
    # Its pipeline has never run, which fails the check, but the numbers
    # are listed all the same
    out = subprocess.run(
        ["calkit", "check", "repro", "-c", "numbers"],
        capture_output=True,
        text=True,
        env=os.environ | {"COLUMNS": "200"},
    ).stdout
    assert "index.ipynb cell 1, 3:" in out
