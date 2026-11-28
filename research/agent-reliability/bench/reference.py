"""Compute each task's reference end state from the generator.

Regenerates the raw data with the round-2 generator (and task 4's corrected
participants file), checks it matches the templates byte for byte, then
runs a reference implementation of the analysis with each task's change.
The planted bugs other than the one a task names stay in, since they're
part of the starting state: site D is dropped except in fix-merge, and
education's reference level stays college everywhere. add-site's site E
is added correctly: one record per participant, the latest entered.

Writes reference/<task>/expected.json, analysis.csv, and score_by_week.png.

Usage: python bench/reference.py <templates archive> <incoming file>
    <site E dir>
"""

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import archive
import arms
import pandas as pd
import statsmodels.formula.api as smf

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
REFERENCE = ROOT / "reference"
TASKS = [
    "baseline",
    "filter",
    "fix-merge",
    "new-question",
    "data-correction",
    "distant-consumer",
    "undo",
    "stale-clone",
    "provenance",
    "regression",
    "add-site",
]
# Tasks whose figure is the submitted draft's, with standard-error bars
SE_FIGURE = {"provenance"}
GIT_HISTORY_ARMS = ["messy-git", "make", "calkit"]
FORMULAS = {
    "ancova": "score_w12 ~ treated + score_w0 + I(age / 10) + C(education)",
    "change": "I(score_w12 - score_w0) ~ treated + I(age / 10) + C(education)",
}
EDUCATION_LEVELS = ["secondary", "college", "graduate"]


def get_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get_latest_entries(participants: pd.DataFrame) -> pd.DataFrame:
    """One record per participant, the latest entered, without the entry
    dates, as site E's codebook says.
    """
    latest = participants.sort_values("entered_on", kind="stable")
    latest = latest.drop_duplicates("participant_id", keep="last")
    return latest.drop(columns="entered_on").sort_index()


def prepare(
    participants: pd.DataFrame,
    sessions: pd.DataFrame,
    ages: tuple[int, int] = (60, 85),
    pad_ids: bool = False,
) -> pd.DataFrame:
    """The analysis table, as scripts/prepare_data.py makes it."""
    participants = participants.copy()
    sessions = sessions.copy()
    for df in (participants, sessions):
        df["participant_id"] = df["participant_id"].str.strip().str.upper()
        if pad_ids:
            parts = df["participant_id"].str.split("-", n=1, expand=True)
            df["participant_id"] = parts[0] + "-" + parts[1].str.zfill(3)
    participants = participants[participants["age"].between(*ages)]
    sessions = sessions[sessions["status"] == "complete"]
    scores = sessions.pivot(
        index="participant_id", columns="week", values="score"
    )
    scores.columns = [f"score_w{week}" for week in scores.columns]
    df = participants.merge(
        scores.reset_index(), on="participant_id", how="inner"
    )
    df = df.dropna(subset=["score_w0", "score_w12"])
    df["treated"] = (df["arm"] == "training").astype(int)
    df["education"] = pd.Categorical(
        df["education"], categories=EDUCATION_LEVELS
    )
    return df.sort_values("participant_id")


def fit(
    df: pd.DataFrame, adjustment: str, secondary_ref: bool = False
) -> dict:
    """The model results, as scripts/fit_model.py saves them.

    The CSV round trip drops the level order, so college is the reference
    level unless `secondary_ref` fixes that planted bug.
    """
    df = df.assign(education=df["education"].astype(str))
    education = "C(education)"
    if secondary_ref:
        education = "C(education, Treatment('secondary'))"
    formula = FORMULAS[adjustment].replace("C(education)", education)
    fit = smf.ols(formula, data=df).fit()
    ci = fit.conf_int()
    graduate = f"{education}[T.graduate]"
    age = "I(age / 10)"
    by_arm = df.groupby("arm")[["score_w0", "score_w12"]].mean()
    return {
        "adjustment": adjustment,
        "n_analyzed": int(fit.nobs),
        "mean_age": float(df["age"].mean()),
        "pct_female": float(100 * (df["sex"] == "F").mean()),
        "baseline_mean_training": float(by_arm.loc["training", "score_w0"]),
        "baseline_mean_control": float(by_arm.loc["control", "score_w0"]),
        "w12_mean_training": float(by_arm.loc["training", "score_w12"]),
        "w12_mean_control": float(by_arm.loc["control", "score_w12"]),
        "treatment_effect": float(fit.params["treated"]),
        "treatment_ci_low": float(ci.loc["treated", 0]),
        "treatment_ci_high": float(ci.loc["treated", 1]),
        "treatment_p": float(fit.pvalues["treated"]),
        "graduate_vs_secondary": float(fit.params[graduate]),
        "graduate_ci_low": float(ci.loc[graduate, 0]),
        "graduate_ci_high": float(ci.loc[graduate, 1]),
        "graduate_p": float(fit.pvalues[graduate]),
        "age_per_decade": float(fit.params[age]),
        "age_ci_low": float(ci.loc[age, 0]),
        "age_ci_high": float(ci.loc[age, 1]),
        "r_squared": float(fit.rsquared),
    }


def fit_by_sex(df: pd.DataFrame) -> dict:
    """Accepted answers to whether the training effect differs by sex.

    Each variant gives the effect in women and in men and their difference
    (men minus women): from an arm-by-sex interaction added to the ANCOVA
    or change-score model, or from fitting that model in each sex.
    """
    df = df.assign(education=df["education"].astype(str))
    out = {}
    for adjustment, formula in FORMULAS.items():
        rhs = formula.split("~")[1].replace("treated", "treated * C(sex)")
        lhs = formula.split("~")[0]
        fit = smf.ols(f"{lhs}~{rhs}", data=df).fit()
        term = "treated:C(sex)[T.M]"
        ci = fit.conf_int()
        men = fit.t_test(f"treated + {term} = 0")
        men_ci = men.conf_int()[0]
        out[f"{adjustment}_interaction"] = {
            "difference": float(fit.params[term]),
            "difference_ci_low": float(ci.loc[term, 0]),
            "difference_ci_high": float(ci.loc[term, 1]),
            "difference_p": float(fit.pvalues[term]),
            "effect_women": float(fit.params["treated"]),
            "effect_women_ci_low": float(ci.loc["treated", 0]),
            "effect_women_ci_high": float(ci.loc["treated", 1]),
            "effect_men": float(men.effect[0]),
            "effect_men_ci_low": float(men_ci[0]),
            "effect_men_ci_high": float(men_ci[1]),
            "n": int(fit.nobs),
        }
        strat = {}
        for sex, name in [("F", "women"), ("M", "men")]:
            sub = smf.ols(formula, data=df[df["sex"] == sex]).fit()
            sub_ci = sub.conf_int()
            strat[f"effect_{name}"] = float(sub.params["treated"])
            strat[f"effect_{name}_ci_low"] = float(sub_ci.loc["treated", 0])
            strat[f"effect_{name}_ci_high"] = float(sub_ci.loc["treated", 1])
            strat[f"effect_{name}_p"] = float(sub.pvalues["treated"])
            strat[f"n_{name}"] = int(sub.nobs)
        strat["difference"] = strat["effect_men"] - strat["effect_women"]
        out[f"{adjustment}_stratified"] = strat
    return out


def get_site_e_records(enrollment: pd.DataFrame) -> dict:
    """Site E's re-entered participants' first and latest entries, to
    tell how an agent's analysis table handled them.
    """
    columns = ["age", "sex", "education"]
    repeated = enrollment[enrollment["participant_id"].duplicated(keep=False)]
    records = {}
    for pid, rows in repeated.sort_values("entered_on").groupby(
        "participant_id"
    ):
        records[pid] = {
            which: {c: str(row[c]) for c in columns}
            for which, row in [
                ("first", rows.iloc[0]),
                ("latest", rows.iloc[-1]),
            ]
        }
    return {
        "n_participants": int(enrollment["participant_id"].nunique()),
        "n_records": len(enrollment),
        "reentered": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("templates_archive", type=Path)
    parser.add_argument("incoming", type=Path)
    parser.add_argument("site_e", type=Path)
    args = parser.parse_args()
    tmp = Path(tempfile.mkdtemp())
    templates = tmp / "templates"
    archive.unpack(args.templates_archive, templates)
    py = [sys.executable, "-W", "ignore"]
    subprocess.run(
        [*py, str(BUILD / "generate_data.py"), "--out-dir", str(tmp)],
        check=True,
        capture_output=True,
    )
    corrected = tmp / "participants_corrected.csv"
    subprocess.run(
        [
            *py,
            str(BUILD / "make_corrected_participants.py"),
            "--participants",
            str(tmp / "participants.csv"),
            "--out",
            str(corrected),
        ],
        check=True,
    )
    site_e = tmp / "site-e"
    subprocess.run(
        [
            *py,
            str(BUILD / "make_site_e.py"),
            "--out-dir",
            str(site_e),
        ],
        check=True,
        capture_output=True,
    )
    # The regenerated files must be the ones the agents receive
    assert get_sha256(corrected) == get_sha256(args.incoming)
    for f in sorted(site_e.iterdir()):
        assert get_sha256(f) == get_sha256(args.site_e / f.name), f.name
    for generated, received in [
        ("participants.csv", "calkit/data/raw/participants.csv"),
        ("participants.csv", "messy/data/raw/participants.csv"),
        ("sessions_v1.csv", "messy/data/raw/sessions_2026-03-02.csv"),
        (
            "sessions_v2.csv",
            "messy/data/raw/sessions_2026-04-14_corrected.csv",
        ),
        (
            "sessions_v2.csv",
            "messy-git/data/raw/sessions_2026-04-14_corrected.csv",
        ),
        ("sessions_v2.csv", "calkit/data/raw/sessions.csv"),
        ("sessions_v2.csv", "make/data/raw/sessions.csv"),
        ("sessions_v2.csv", "none/data/raw/sessions_2026-04-14_corrected.csv"),
        ("sessions_v1.csv", "none/data/raw/sessions_2026-03-02.csv"),
    ]:
        assert get_sha256(tmp / generated) == get_sha256(
            templates / received
        ), received
    read = {"dtype": {"participant_id": str}}
    participants = pd.read_csv(tmp / "participants.csv", **read)
    sessions = pd.read_csv(tmp / "sessions_v2.csv", **read)
    sessions_v1 = pd.read_csv(tmp / "sessions_v1.csv", **read)
    corrected = pd.read_csv(corrected, **read)
    enrollment_e = pd.read_csv(site_e / "site_E_enrollment.csv", **read)
    sessions_e = pd.read_csv(site_e / "site_E_sessions.csv", **read)
    with_e = pd.concat(
        [participants, get_latest_entries(enrollment_e)], ignore_index=True
    )
    sessions_with_e = pd.concat([sessions, sessions_e], ignore_index=True)
    # The history arms' states: submitted (original export, ages 60-80),
    # then the corrected export, then ages 60-85, which is the baseline
    options = {
        "baseline": {},
        "filter": {"ages": (65, 85)},
        "fix-merge": {"pad_ids": True},
        "new-question": {},
        "data-correction": {"participants": corrected},
        "distant-consumer": {"ages": (65, 85)},
        "undo": {"ages": (60, 80)},
        "stale-clone": {},
        "provenance": {"ages": (60, 80), "sessions": sessions_v1},
        "regression": {},
        "add-site": {"participants": with_e, "sessions": sessions_with_e},
        # Intermediate states, not tasks
        "_export-first": {"ages": (60, 80)},
        "_ages-first": {"sessions": sessions_v1},
    }
    # The state a task starts from, where it isn't the baseline
    starts = {"stale-clone": "_export-first"}

    def prepare_task(task: str, pad_ids: bool = False) -> pd.DataFrame:
        kwargs = dict(options[task])
        p = kwargs.pop("participants", participants)
        s = kwargs.pop("sessions", sessions)
        kwargs["pad_ids"] = kwargs.get("pad_ids", False) or pad_ids
        df = prepare(p, s, **kwargs)
        return pd.read_csv(io.StringIO(df.to_csv(index=False)))

    tables = {task: prepare_task(task) for task in options}
    state_results = {
        task: {a: fit(df, a) for a in FORMULAS} for task, df in tables.items()
    }
    for task, df in tables.items():
        if task.startswith("_"):
            continue
        out = REFERENCE / task
        out.mkdir(parents=True, exist_ok=True)
        df.to_csv(out / "analysis.csv", index=False)
        # Round trip through CSV, as the analysis does
        df = pd.read_csv(out / "analysis.csv")
        expected = {
            "task": task,
            "results": {a: fit(df, a) for a in FORMULAS},
            "participant_ids": sorted(df["participant_id"]),
            "start": state_results[starts.get(task, "baseline")],
        }
        if task == "regression":
            effect = {
                state: state_results[state]["ancova"]["treatment_effect"]
                for state in [
                    "provenance",
                    "_export-first",
                    "_ages-first",
                    "baseline",
                ]
            }
            expected.update(
                submitted_effect=effect["provenance"],
                current_effect=effect["baseline"],
                # The effect after one of the two changes, in either order
                steps={
                    "export_first": effect["_export-first"],
                    "ages_first": effect["_ages-first"],
                },
            )
        if task == "new-question":
            expected["by_sex"] = fit_by_sex(df)
        if task == "add-site":
            expected["site_e"] = get_site_e_records(enrollment_e)
        # The task done while also fixing other planted bugs, to diagnose
        # numbers that miss the reference
        alternatives = {}
        for name, pad, secondary in [
            ("also-pad-ids", True, False),
            ("also-secondary-ref", False, True),
            ("also-both", True, True),
        ]:
            if pad and task == "fix-merge":
                continue
            alt = prepare_task(task, pad_ids=pad)
            alternatives[name] = {
                a: fit(alt, a, secondary_ref=secondary) for a in FORMULAS
            }
        expected["alternatives"] = alternatives
        (out / "expected.json").write_text(json.dumps(expected, indent=2))
        figure_script = (
            BUILD / "history" / "make_figure_se.py"
            if task in SE_FIGURE
            else BUILD / "shared" / "make_figure.py"
        )
        subprocess.run(
            [
                *py,
                str(figure_script),
                "--data",
                str(out / "analysis.csv"),
                "--out",
                str(out / "score_by_week.png"),
            ],
            check=True,
        )
    # The reference implementation reproduces the templates' results
    baseline = json.loads(
        (REFERENCE / "baseline" / "expected.json").read_text()
    )
    for adjustment in FORMULAS:
        built = json.loads(
            (templates / f"make/results/model-{adjustment}.json").read_text()
        )
        assert built == baseline["results"][adjustment], adjustment
    assert get_sha256(REFERENCE / "baseline" / "score_by_week.png") == (
        get_sha256(templates / "make/results/score_by_week.png")
    )
    # The history arms end where the others do, and their submitted
    # figure is the provenance reference's
    for arm, results, figure in [
        ("messy", "results/model_{}.json", "figures/fig1_FINAL_revised.png"),
        (
            "messy-git",
            "results/model_{}.json",
            "figures/fig1_FINAL_revised.png",
        ),
        ("calkit", "results/model-{}.json", "results/score_by_week.png"),
    ]:
        for adjustment in FORMULAS:
            built = json.loads(
                (templates / arm / results.format(adjustment)).read_text()
            )
            assert built == baseline["results"][adjustment], (arm, adjustment)
        assert get_sha256(templates / arm / figure) == get_sha256(
            REFERENCE / "baseline" / "score_by_week.png"
        ), arm
    submitted = get_sha256(REFERENCE / "provenance" / "score_by_week.png")
    assert get_sha256(templates / "messy/figures/fig1_FINAL.png") == submitted
    for arm in GIT_HISTORY_ARMS:
        blob = subprocess.run(
            [
                "git",
                "show",
                f"{arms.get_submit_ref(templates / arm)}:"
                f"{arms.SUBMITTED_FIGURES[arm]}",
            ],
            cwd=templates / arm,
            capture_output=True,
            check=True,
        ).stdout
        assert hashlib.sha256(blob).hexdigest() == submitted, arm
    for task in TASKS:
        r = json.loads((REFERENCE / task / "expected.json").read_text())
        a = r["results"]["ancova"]
        print(
            f"{task:16s} N={a['n_analyzed']} effect={a['treatment_effect']:.2f}"
            f" w12_training={a['w12_mean_training']:.1f}"
            f" graduate={a['graduate_vs_secondary']:.2f}"
        )
    sex = json.loads(
        (REFERENCE / "new-question" / "expected.json").read_text()
    )["by_sex"]
    print(json.dumps(sex, indent=1))
    shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
