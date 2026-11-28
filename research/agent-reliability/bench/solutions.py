"""Reference solutions: what a careful agent would do for each task and arm.

Used only to check the graders, by applying a solution to a fresh run and
grading it, which should pass. The analysis edits are the same in every
arm; each arm then updates its outputs its own way: the none arm reruns the
README's commands and the notebook and retypes the report, the make arm
edits the Makefile and runs make, and the Calkit arm edits calkit.yaml and
runs calkit run. The Git arms commit at the end.

Usage: python bench/solutions.py <run dir>
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import arms
import report

ROOT = arms.ROOT
sys.path.insert(0, str(ROOT / "build"))
import build_history  # noqa: E402

FILTER = (
    'participants = participants[participants["age"].between(60, 85)]',
    'participants = participants[participants["age"].between(65, 85)]',
)
PAD = (
    '        df["participant_id"] = df["participant_id"].str.strip().str.upper()\n',
    '        df["participant_id"] = df["participant_id"].str.strip().str.upper()\n'
    "    # Site D's export drops the zero padding, e.g., D-7 for D-007\n"
    "    for df in (participants, sessions):\n"
    '        parts = df["participant_id"].str.split("-", n=1, expand=True)\n'
    '        df["participant_id"] = parts[0] + "-" + parts[1].str.zfill(3)\n',
)
METHODS_FILTER = (
    "Eligible participants were aged 60–85.",
    "Eligible participants were aged 60–85; this analysis is restricted to"
    " those aged 65–85.",
)
METHODS_UNDO = (
    "Eligible participants were aged 60–85.",
    "Eligible participants were aged 60–80.",
)
METHODS_SEX = (
    "score from baseline to week 12 on arm, age, and education.",
    "score from baseline to week 12 on arm, age, and education. To test"
    " whether the training effect differed between women and men, we added"
    " an arm-by-sex interaction to the primary model.",
)
ITEM_8 = "(R² = {r_squared:.3f})."
ITEM_9 = (
    "\n9. The training effect {sex_conclusion} between women and men: it"
    " was {effect_women:.2f} points in women and {effect_men:.2f} points in"
    " men (difference, men minus women, {difference:.2f} points; 95% CI"
    " {difference_ci_low:.2f} to {difference_ci_high:.2f};"
    " {difference_p_text})."
)
BY_SEX_SCRIPT = '''"""Test whether the training effect differs between women and men."""

import argparse
import json
from pathlib import Path

import pandas as pd
import statsmodels.formula.api as smf

# The primary ANCOVA model with an arm-by-sex interaction
FORMULA = (
    "score_w12 ~ treated * C(sex) + score_w0 + I(age / 10) + C(education)"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.data)
    fit = smf.ols(FORMULA, data=df).fit()
    term = "treated:C(sex)[T.M]"
    ci = fit.conf_int()
    men = fit.t_test(f"treated + {term} = 0")
    men_ci = men.conf_int()[0]
    results = {
        "n": int(fit.nobs),
        "difference": float(fit.params[term]),
        "difference_ci_low": float(ci.loc[term, 0]),
        "difference_ci_high": float(ci.loc[term, 1]),
        "difference_p": float(fit.pvalues[term]),
        "effect_women": float(fit.params["treated"]),
        "effect_men": float(men.effect[0]),
        "effect_men_ci_low": float(men_ci[0]),
        "effect_men_ci_high": float(men_ci[1]),
    }
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
'''
WRITE_REPORT_ARG = (
    '    parser.add_argument("--out", required=True)\n',
    '    parser.add_argument("--out", required=True)\n'
    '    parser.add_argument("--by-sex")\n',
)
WRITE_REPORT_FORMAT = (
    "    report = template.format(\n",
    "    by_sex = {}\n"
    "    if args.by_sex:\n"
    "        with open(args.by_sex) as f:\n"
    "            by_sex = json.load(f)\n"
    '        by_sex["difference_p_text"] = format_p(by_sex["difference_p"])\n'
    '        by_sex["sex_conclusion"] = (\n'
    '            "did not differ clearly"\n'
    '            if by_sex["difference_p"] >= 0.05\n'
    '            else "differed"\n'
    "        )\n"
    "    report = template.format(\n"
    "        **by_sex,\n",
)


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert text.count(old) == 1, (path, old)
    path.write_text(text.replace(old, new))


def run(cmd: list[str], project: Path, env: dict) -> None:
    p = subprocess.run(
        cmd, cwd=project, env=env, capture_output=True, text=True
    )
    if p.returncode != 0:
        raise RuntimeError(f"{cmd} failed:\n{p.stdout}\n{p.stderr}")


def get_sex_values(project: Path, path: str) -> dict:
    by_sex = json.loads((project / path).read_text())
    by_sex["difference_p_text"] = report.format_p(by_sex["difference_p"])
    by_sex["sex_conclusion"] = (
        "did not differ clearly"
        if by_sex["difference_p"] >= 0.05
        else "differed"
    )
    return by_sex


def edit_template(text: str, task: str) -> str:
    """The report template's text after a task's edits."""
    if task in {"filter", "distant-consumer"}:
        assert text.count(METHODS_FILTER[0]) == 1
        text = text.replace(*METHODS_FILTER)
    if task == "undo":
        assert text.count(METHODS_UNDO[0]) == 1
        text = text.replace(*METHODS_UNDO)
    if task == "new-question":
        assert text.count(METHODS_SEX[0]) == 1 and text.count(ITEM_8) == 1
        text = text.replace(*METHODS_SEX).replace(ITEM_8, ITEM_8 + ITEM_9)
    return text


def type_report(
    project: Path,
    task: str,
    template: str | None = None,
    prefix: str = "results/model_",
    figure: str = "figures/score_by_week.png",
    out: str = "report.md",
) -> None:
    """Retype a plain-folder report from its results, as a person would."""
    if template is None:
        template = (ROOT / "build/shared/report_template.md").read_text()
    template = edit_template(template, task)
    ancova = json.loads((project / f"{prefix}ancova.json").read_text())
    change = json.loads((project / f"{prefix}change.json").read_text())
    by_sex = {}
    if task == "new-question":
        by_sex = get_sex_values(project, f"{prefix}by_sex.json")
    text = template.format(
        **ancova,
        **by_sex,
        treatment_p_text=report.format_p(ancova["treatment_p"]),
        graduate_p_text=report.format_p(ancova["graduate_p"]),
        change_treatment_effect=change["treatment_effect"],
        change_treatment_ci_low=change["treatment_ci_low"],
        change_treatment_ci_high=change["treatment_ci_high"],
        change_treatment_p_text=report.format_p(change["treatment_p"]),
        r_squared_pct=100 * ancova["r_squared"],
        figure=figure,
    )
    (project / out).write_text(text)


def solve_none(run_dir: Path, project: Path, task: str, env: dict) -> None:
    readme = project / "README.md"
    if task == "new-question":
        (project / "scripts/fit_by_sex.py").write_text(BY_SEX_SCRIPT)
        replace_once(
            readme,
            "--out results/model_change.json\n",
            "--out results/model_change.json\n"
            "python scripts/fit_by_sex.py --data data/merged_final.csv"
            " --out results/model_by_sex.json\n",
        )
    if task == "data-correction":
        name = "participants_2026-05-20_corrected.csv"
        shutil.copy2(run_dir / "incoming" / name, project / "data/raw" / name)
        replace_once(
            readme,
            "--participants data/raw/participants.csv",
            f"--participants data/raw/{name}",
        )
        replace_once(
            readme,
            "replaces the original one.\n",
            "replaces the original one, and the corrected participants file"
            " (2026-05-20) replaces `participants.csv`.\n",
        )
    result = arms.run_project(
        "none", project, True, run_dir / "venv", run_dir / "solution-state"
    )
    assert result["ok"], result
    type_report(project, task)


# The history arms' code edits, in utils.py, which every script imports
UTILS_FILTER = ("MIN_AGE = 60", "MIN_AGE = 65")
UTILS_UNDO = ("MAX_AGE = 85", "MAX_AGE = 80")
UTILS_PAD = (
    '    df["participant_id"] = df["participant_id"].str.strip().str.upper()\n',
    '    df["participant_id"] = df["participant_id"].str.strip().str.upper()\n'
    "    # Site D's export drops the zero padding, e.g., D-7 for D-007\n"
    '    parts = df["participant_id"].str.split("-", n=1, expand=True)\n'
    '    df["participant_id"] = parts[0] + "-" + parts[1].str.zfill(3)\n',
)
CORRECTED = "participants_2026-05-20_corrected.csv"
# Where each history arm's code lives
SCRIPTS = {
    "messy": "",
    "messy-git": "",
    "make": "scripts/",
    "calkit": "scripts/",
}


def edit_code(project: Path, arm: str, task: str) -> None:
    """A task's edits to the analysis code, the same in every history arm."""
    utils = project / f"{SCRIPTS[arm]}utils.py"
    if task in {"filter", "distant-consumer"}:
        replace_once(utils, *UTILS_FILTER)
    if task == "fix-merge":
        replace_once(utils, *UTILS_PAD)
    if task == "undo":
        replace_once(utils, *UTILS_UNDO)


def update_abstract(project: Path, prefix: str) -> None:
    """Retype the conference abstract's numbers from the results."""
    ancova = json.loads((project / f"{prefix}ancova.json").read_text())
    path = project / arms.DISTANT
    path.write_text(build_history.format_abstract(ancova))


def solve_messy(
    run_dir: Path, project: Path, arm: str, task: str, env: dict
) -> None:
    """Edit the code, rerun the current scripts and figure notebook, and
    retype the draft and the abstract.
    """
    venv = run_dir / "venv"
    state = run_dir / "solution-state"
    if task == "data-correction":
        shutil.copy2(run_dir / "incoming" / CORRECTED, project / "data/raw")
        replace_once(
            project / "prepare_data.py",
            'PARTICIPANTS = "data/raw/participants.csv"',
            f'PARTICIPANTS = "data/raw/{CORRECTED}"',
        )
    edit_code(project, arm, task)
    result = arms.run_project(arm, project, True, venv, state)
    assert result["ok"], result
    if task == "new-question":
        # The new step needs writing down, so a script says how it all runs
        (project / "fit_by_sex.py").write_text(BY_SEX_SCRIPT)
        (project / "run_all.sh").write_text(RUN_ALL)
        run(["bash", "run_all.sh"], project, env)
    max_age = 80 if task == "undo" else 85
    template = build_history.get_report_template(85, True, True)
    type_report(
        project,
        task,
        template,
        figure="../figures/fig1_FINAL_revised.png",
        out="paper/draft.md",
    )
    if max_age == 80:
        assert "aged 60–80" in (project / "paper/draft.md").read_text()
    update_abstract(project, "results/model_")
    if arm == "messy-git":
        commit(project, task, env)


RUN_ALL = """#!/usr/bin/env bash
# Rerun the current analysis, from the raw data to the figure
set -euo pipefail
python prepare_data.py
python fit_model.py
python fit_by_sex.py --data data/merged_final.csv \\
  --out results/model_by_sex.json
jupyter nbconvert --to notebook --execute --output-dir "$(mktemp -d)" \\
  analysis_v2_final.ipynb
"""


def add_make_by_sex(project: Path) -> None:
    (project / "scripts/fit_by_sex.py").write_text(BY_SEX_SCRIPT)
    makefile = project / "Makefile"
    replace_once(
        makefile,
        "RESULTS := results/model-ancova.json results/model-change.json",
        "RESULTS := results/model-ancova.json results/model-change.json \\\n"
        "\tresults/model-by-sex.json",
    )
    replace_once(
        makefile,
        "results/score_by_week.png: ",
        "results/model-by-sex.json: scripts/fit_by_sex.py"
        " data/analysis.csv\n"
        "\t$(PYTHON) scripts/fit_by_sex.py --data data/analysis.csv"
        " --out $@\n\n"
        "results/score_by_week.png: ",
    )
    replace_once(
        makefile,
        "--figure score_by_week.png --out $@",
        "--by-sex results/model-by-sex.json --figure score_by_week.png"
        " --out $@",
    )


def add_calkit_by_sex(project: Path) -> None:
    from ruamel.yaml import YAML

    (project / "scripts/fit_by_sex.py").write_text(BY_SEX_SCRIPT)
    yaml = YAML()
    yaml.width = 10_000
    path = project / "calkit.yaml"
    config = yaml.load(path.read_text())
    stages = config["pipeline"]["stages"]
    stages.insert(
        2,
        "fit-by-sex",
        {
            "kind": "python-script",
            "environment": "main",
            "script_path": "scripts/fit_by_sex.py",
            "args": [
                "--data",
                "data/analysis.csv",
                "--out",
                "results/model-by-sex.json",
            ],
            "inputs": ["data/analysis.csv"],
            "outputs": [
                {"path": "results/model-by-sex.json", "storage": "git"}
            ],
        },
    )
    report_stage = stages["write-report"]
    report_stage["inputs"].append("results/model-by-sex.json")
    i = list(report_stage["args"]).index("--figure")
    report_stage["args"].insert(i, "results/model-by-sex.json")
    report_stage["args"].insert(i, "--by-sex")
    config["questions"].append(
        {
            "question": "Does the training effect differ between women and men?",
            "approach": "Arm-by-sex interaction added to the ANCOVA model.",
            "answer": (
                "Training raised week-12 scores by {women:.2f} points in"
                " women and {men:.2f} points in men (difference, men"
                " minus women, {diff:.2f} points; 95% CI {lo:.2f} to"
                " {hi:.2f}; p = {p:.2g})."
            ),
            "evidence": [
                {
                    "kind": "result",
                    "path": "results/model-by-sex.json",
                    "values": {
                        "women": "effect_women",
                        "men": "effect_men",
                        "diff": "difference",
                        "lo": "difference_ci_low",
                        "hi": "difference_ci_high",
                        "p": "difference_p",
                    },
                },
                {
                    "kind": "document",
                    "path": "results/report.md",
                    "section": "Results",
                },
            ],
        }
    )
    with open(path, "w") as f:
        yaml.dump(config, f)


def run_careful(arm: str, project: Path, env: dict, force: bool) -> None:
    if arm == "calkit":
        calkit = shlex.split(arms.get_calkit_command())
        run(calkit + ["run"] + (["--force"] if force else []), project, env)
        run(calkit + ["check", "questions"], project, env)
    else:
        run(["make"] + (["-B"] if force else []), project, env)


def get_commit_sha(project: Path, message: str) -> str:
    """The commit whose subject starts with `message`."""
    p = subprocess.run(
        ["git", "log", "--format=%H %s"],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    )
    for line in p.stdout.splitlines():
        sha, subject = line.split(" ", 1)
        if subject.startswith(message):
            return sha
    raise ValueError(message)


def solve_careful(
    run_dir: Path,
    project: Path,
    arm: str,
    task: str,
    env: dict,
    abstract: bool = True,
) -> None:
    """Edit the code and the report template, or revert a commit, rerun
    the pipeline its own way, retype the abstract, and commit.
    """
    if task == "new-question":
        (add_calkit_by_sex if arm == "calkit" else add_make_by_sex)(project)
        script = project / "scripts/write_report.py"
        replace_once(script, *WRITE_REPORT_ARG)
        replace_once(script, *WRITE_REPORT_FORMAT)
    if task == "data-correction":
        shutil.copy2(
            run_dir / "incoming" / CORRECTED,
            project / "data/raw/participants.csv",
        )
    if task == "undo":
        sha = get_commit_sha(project, "Widen eligible ages")
        run(["git", "revert", "--no-edit", sha], project, git_env(env))
    else:
        edit_code(project, arm, task)
        template = project / "report_template.md"
        template.write_text(edit_template(template.read_text(), task))
    # A fresh clone's timestamps say nothing, so stale-clone forces a rerun
    run_careful(arm, project, env, force=task == "stale-clone")
    if abstract and (project / arms.DISTANT).exists():
        update_abstract(project, "results/model-")
    commit(project, task, env)


def solve_stale_messy_git(project: Path, run_dir: Path, env: dict) -> None:
    result = arms.run_project(
        "messy-git", project, True, run_dir / "venv", run_dir / "state"
    )
    assert result["ok"], result
    type_report(
        project,
        "stale-clone",
        build_history.get_report_template(85, True, True),
        figure="../figures/fig1_FINAL_revised.png",
        out="paper/draft.md",
    )
    commit(project, "stale-clone", env)


REPRODUCE = {
    "messy": """#!/usr/bin/env bash
# The submitted draft's Figure 1: analysis_v2.ipynb on data/merged.csv,
# which prepare_data_old.py made from the original sessions export with
# utils.py's MAX_AGE at 80, as it was then
set -euo pipefail
out="$(pwd)/provenance/figure1.png"
tmp="$(mktemp -d)"
rsync -a --exclude provenance ./ "$tmp/"
cd "$tmp"
sed -i.bak 's/^MAX_AGE = .*/MAX_AGE = 80/' utils.py
rm -f data/merged.csv figures/fig1_FINAL.png
python prepare_data_old.py
jupyter nbconvert --to notebook --execute --output-dir "$tmp/run" \\
  analysis_v2.ipynb > /dev/null 2>&1
cp figures/fig1_FINAL.png "$out"
""",
    "messy-git": """#!/usr/bin/env bash
# The submitted draft's Figure 1, from the commit that added it
set -euo pipefail
out="$(pwd)/provenance/figure1.png"
tmp="$(mktemp -d)"
git archive {sha} | tar -x -C "$tmp"
cd "$tmp"
rm -f data/merged.csv figures/fig1_FINAL.png
python prepare_data.py
jupyter nbconvert --to notebook --execute --output-dir "$tmp/run" \\
  analysis_v2.ipynb > /dev/null 2>&1
cp figures/fig1_FINAL.png "$out"
""",
    "make": """#!/usr/bin/env bash
# The submitted draft's Figure 1, rebuilt from the tagged commit
set -euo pipefail
here="$(pwd)"
out="$here/provenance/figure1.png"
tmp="$(mktemp -d)"
git archive submitted | tar -x -C "$tmp"
cd "$tmp"
@SCRIPT_EDIT@make -B PYTHON=python > /dev/null
cp results/score_by_week.png "$out"
""",
    "calkit": """#!/usr/bin/env bash
# The submitted draft's Figure 1, rebuilt from the tagged commit
set -euo pipefail
out="$(pwd)/provenance/figure1.png"
tmp="$(mktemp -d)"
git clone -q . "$tmp"
cd "$tmp"
git checkout -q submitted
calkit run --force > /dev/null
cp results/score_by_week.png "$out"
""",
}


def solve_provenance(
    run_dir: Path, project: Path, arm: str, env: dict, flaw: str | None = None
) -> None:
    expected = json.loads(
        (ROOT / "reference/provenance/expected.json").read_text()
    )
    effect = expected["results"]["ancova"]
    sha = "none"
    if arm in arms.SUBMITTED_CODE:
        meta = json.loads((run_dir / "meta.json").read_text())
        sha = arms.get_submitted_commits(
            project, arm, meta["template_git_head"]
        )[0]
    script = REPRODUCE[arm].replace("{sha}", sha)
    script = script.replace(
        "@SCRIPT_EDIT@",
        # The flaw: the submitted data and code, but today's figure script
        'git -C "$here" show HEAD:scripts/make_figure.py'
        " > scripts/make_figure.py\n"
        if flaw == "current-figure-code"
        else "",
    )
    if flaw == "copied-figure":
        script = (
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            f"git show {sha}:figures/fig1_FINAL.png > provenance/figure1.png\n"
        )
    (project / "provenance").mkdir(exist_ok=True)
    (project / "provenance/reproduce.sh").write_text(script)
    run(["bash", "provenance/reproduce.sh"], project, env)
    where = (
        "`analysis_v2.ipynb` run on `data/merged.csv`, which"
        " `prepare_data_old.py` made"
        if arm == "messy"
        else f"commit {sha[:10]} (`analysis_v2.ipynb` and `prepare_data.py`"
        " there)"
        if arm == "messy-git"
        else f"commit {sha[:10]}, tagged `submitted`"
    )
    (project / "provenance/ANSWER.md").write_text(
        f"Figure 1 and the main effect in the submitted draft came from"
        f" {where}, from `participants.csv` and the original sessions"
        " export (received 2026-03-02, before the 2026-04-14 correction"
        " rescored week-12 form B sessions), with eligible ages 60–80 and"
        " the ANCOVA adjusted for education. Figure 1's error bars are"
        " standard errors.\n\nThe main effect, reproduced: training raised"
        f" week-12 scores by {effect['treatment_effect']:.2f} points (95% CI"
        f" {effect['treatment_ci_low']:.2f} to"
        f" {effect['treatment_ci_high']:.2f}).\n"
    )


def solve_regression(project: Path, flaw: str | None = None) -> None:
    e = json.loads((ROOT / "reference/regression/expected.json").read_text())
    s, c = e["submitted_effect"], e["current_effect"]
    mid = e["steps"]["export_first"]
    if flaw == "wrong-draft":
        text = (
            "# Changes since the first draft\n\n1. Education was added to"
            f" the ANCOVA, which moved the effect to {s:.2f} points.\n2. The"
            " corrected sessions export rescored week-12 form B sessions,"
            f" giving {c:.2f}.\n"
        )
    else:
        text = (
            "# What changed between the submitted draft and now\n\n"
            f"The main effect went from {s:.2f} points to {c:.2f}, in two"
            " steps:\n\n1. The corrected sessions export (2026-04-14)"
            " replaced the original, which scored week-12 form B sessions"
            " with the wrong answer key. With ages still 60–80, the effect"
            f" is {mid:.2f}.\n2. The eligible ages went from 60–80 to"
            " 60–85, the protocol's range, as reviewer 2 asked. The effect"
            f" is then {c:.2f}.\n\nFigure 1's switch to 95% CIs doesn't"
            " change the effect.\n"
        )
    (project / "CHANGES.md").write_text(text)


def commit(project: Path, task: str, env: dict) -> None:
    run(["git", "add", "-A"], project, git_env(env))
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        run(
            ["git", "commit", "-q", "-m", f"Solve {task}"],
            project,
            git_env(env),
        )


def git_env(env: dict) -> dict:
    return {
        **env,
        "GIT_AUTHOR_NAME": "Reference Solution",
        "GIT_AUTHOR_EMAIL": "solution@example.org",
        "GIT_COMMITTER_NAME": "Reference Solution",
        "GIT_COMMITTER_EMAIL": "solution@example.org",
    }


def get_context(run_dir: Path) -> tuple[dict, str, str, Path, dict]:
    run_dir = run_dir.resolve()
    meta = json.loads((run_dir / "meta.json").read_text())
    arm, task = meta["arm"], meta["task"]
    project = run_dir / "project"
    venv = run_dir / "venv" if arm != "calkit" else None
    env = arms.get_env(venv, run_dir / "solution-state")
    return meta, arm, task, project, env


def solve(run_dir: Path) -> None:
    run_dir = run_dir.resolve()
    meta, arm, task, project, env = get_context(run_dir)
    if task == "provenance":
        solve_provenance(run_dir, project, arm, env)
    elif task == "regression":
        solve_regression(project)
    elif arm == "none":
        prepare = project / "scripts/prepare_data.py"
        if task == "filter":
            replace_once(prepare, *FILTER)
        if task == "fix-merge":
            replace_once(prepare, *PAD)
        solve_none(run_dir, project, task, env)
    elif task == "stale-clone" and arm == "messy-git":
        solve_stale_messy_git(project, run_dir, env)
    elif arm in {"messy", "messy-git"}:
        solve_messy(run_dir, project, arm, task, env)
    else:
        solve_careful(run_dir, project, arm, task, env)


def apply_flaw(run_dir: Path, flaw: str) -> None:
    """A plausible agent mistake, to check a grader catches it.

    - stale-one: the full solution, then one retyped number left stale
    - no-rerun: the code and text edits, but outputs not regenerated
    - raw-edit: site D's IDs padded in the raw sessions file itself
    - typed-answer: the new answer typed into the report template
    - extra-fix: the full solution, also fixing education's reference level
    - wrong-notebook: a messy arm's analysis rerun with the submitted
      draft's notebook copy, analysis_v2.ipynb, instead of the current one
    - stale-csv: the new analysis fit to a cached table from older code
    - current-figure-code: the submitted figure redrawn from the submitted
      data but with today's figure code
    - copied-figure: the submitted figure copied out of Git history
    - missed-distant: the full solution, but the abstract left as it was
    - bundled-revert: the reviewer changes' commit reverted whole, which
      also reverts Figure 1's confidence intervals
    - incremental-only: make in a fresh clone, which sees nothing to do
    - wrong-draft: changes explained against the first draft, not the
      submitted one
    """
    run_dir = run_dir.resolve()
    meta, arm, task, project, env = get_context(run_dir)
    venv = run_dir / "venv" if arm != "calkit" else None
    report_path = project / arms.ARMS[arm]["report"]
    calkit = shlex.split(arms.get_calkit_command())
    if flaw == "stale-one":
        solve(run_dir)
        start = meta["start_numbers"]["w12_mean_training"]
        text = report_path.read_text()
        line = report.find_item_lines(text)[3]
        shown = report.extract_numbers(text)["w12_mean_training"]
        report_path.write_text(
            text.replace(line, line.replace(shown, start, 1))
        )
    elif flaw == "no-rerun":
        edit_code(project, arm, task)
        template = project / "report_template.md"
        template.write_text(edit_template(template.read_text(), task))
    elif flaw == "raw-edit":
        import pandas as pd

        path = project / "data/raw/sessions.csv"
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        parts = df["participant_id"].str.split("-", n=1, expand=True)
        df["participant_id"] = parts[0] + "-" + parts[1].str.zfill(3)
        df.to_csv(path, index=False)
        run_careful(arm, project, env, force=False)
        commit(project, task, env)
    elif flaw == "typed-answer":
        template = project / "report_template.md"
        text = template.read_text()
        typed = (
            "\n9. The training effect did not differ clearly between women"
            " and men: it was 3.94 points in women and 3.84 points in men"
            " (difference, men minus women, -0.10 points; 95% CI -2.22 to"
            " 2.02; p = 0.93)."
        )
        template.write_text(text.replace(ITEM_8, ITEM_8 + typed))
        run(calkit + ["run"] if arm == "calkit" else ["make"], project, env)
        commit(project, task, env)
    elif flaw == "extra-fix":
        script = project / "scripts/fit_model.py"
        text = script.read_text()
        script.write_text(
            text.replace(
                "C(education)", "C(education, Treatment('secondary'))"
            )
        )
        solve(run_dir)
    elif flaw == "wrong-notebook":
        edit_code(project, arm, task)
        run(["python", "prepare_data.py"], project, env)
        run(["python", "fit_model.py"], project, env)
        run(
            [
                "jupyter",
                "nbconvert",
                "--to",
                "notebook",
                "--execute",
                "--inplace",
                "analysis_v2.ipynb",
            ],
            project,
            env,
        )
        type_report(
            project,
            task,
            build_history.get_report_template(85, True, True),
            figure="../figures/fig1_FINAL_revised.png",
            out="paper/draft.md",
        )
        update_abstract(project, "results/model_")
    elif flaw == "stale-csv":
        (project / "fit_by_sex.py").write_text(BY_SEX_SCRIPT)
        run(
            [
                "python",
                "fit_by_sex.py",
                "--data",
                "data/merged.csv",
                "--out",
                "results/model_by_sex.json",
            ],
            project,
            env,
        )
        type_report(
            project,
            task,
            build_history.get_report_template(85, True, True),
            figure="../figures/fig1_FINAL_revised.png",
            out="paper/draft.md",
        )
    elif flaw in {"current-figure-code", "copied-figure"}:
        solve_provenance(run_dir, project, arm, env, flaw)
    elif flaw == "missed-distant":
        solve_careful(run_dir, project, arm, task, env, abstract=False)
    elif flaw == "bundled-revert":
        sha = get_commit_sha(project, "reviewer comments")
        run(["git", "revert", "--no-edit", sha], project, git_env(env))
        result = arms.run_project(
            arm, project, True, venv, run_dir / "solution-state"
        )
        assert result["ok"], result
        commit(project, task, env)
    elif flaw == "incremental-only":
        run(["make"], project, env)
    elif flaw == "wrong-draft":
        solve_regression(project, flaw)
    else:
        raise ValueError(flaw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--flaw")
    args = parser.parse_args()
    if args.flaw:
        apply_flaw(args.run, args.flaw)
    else:
        solve(args.run)


if __name__ == "__main__":
    os.environ.pop("VIRTUAL_ENV", None)
    main()
