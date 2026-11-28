"""Compute round 2's report numbers as built and with each planted bug fixed.

Runs the shared scripts from audit-compare-r2/shared on freshly generated
raw data, and patched copies of them that fix bug 1 (site D's unpadded IDs
in the sessions export) and bug 2 (education's reference level), alone and
together. Also prints the stale value bug 3 types in: the training-arm
week-12 mean from the original (v1) sessions export.

Usage:
    uv run --no-project --python 3.12 --with numpy==2.5.5 \
        --with pandas==3.1.1 --with statsmodels==0.15.0 \
        python round-2-compute-key.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

R2 = Path(__file__).resolve().parent.parent / "audit-compare-r2"
SHARED = R2 / "shared"
BUG_1 = (
    '        df["participant_id"] = df["participant_id"].str.strip().str.upper()\n',
    '        df["participant_id"] = df["participant_id"].str.strip().str.upper()\n'
    '        parts = df["participant_id"].str.split("-", n=1, expand=True)\n'
    '        df["participant_id"] = parts[0] + "-" + parts[1].str.zfill(3)\n',
)
BUG_2 = ("C(education)", "C(education, Treatment('secondary'))")
KEYS = [
    "n_analyzed",
    "mean_age",
    "pct_female",
    "baseline_mean_training",
    "baseline_mean_control",
    "w12_mean_training",
    "w12_mean_control",
    "treatment_effect",
    "treatment_ci_low",
    "treatment_ci_high",
    "treatment_p",
    "graduate_vs_secondary",
    "graduate_ci_low",
    "graduate_ci_high",
    "graduate_p",
    "age_per_decade",
    "age_ci_low",
    "age_ci_high",
    "r_squared",
]


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    py = [sys.executable, "-W", "ignore"]
    subprocess.run(
        [*py, str(R2 / "scripts" / "generate_data.py"), "--out-dir", str(tmp)],
        check=True,
    )
    # Patched copies of the shared scripts
    prep = (SHARED / "prepare_data.py").read_text()
    fit = (SHARED / "fit_model.py").read_text()
    assert prep.count(BUG_1[0]) == 1 and fit.count(BUG_2[0]) == 3
    scripts = {}
    for name, fix_1, fix_2 in [
        ("as_built", False, False),
        ("fix_1", True, False),
        ("fix_2", False, True),
        ("fixed", True, True),
    ]:
        d = tmp / name
        d.mkdir()
        (d / "prepare_data.py").write_text(
            prep.replace(*BUG_1) if fix_1 else prep
        )
        (d / "fit_model.py").write_text(fit.replace(*BUG_2) if fix_2 else fit)
        scripts[name] = d
    out: dict = {}
    for name, d in scripts.items():
        for sessions in ["v1", "v2"]:
            data = tmp / f"{name}_{sessions}.csv"
            subprocess.run(
                [
                    *py,
                    str(d / "prepare_data.py"),
                    "--participants",
                    str(tmp / "participants.csv"),
                    "--sessions",
                    str(tmp / f"sessions_{sessions}.csv"),
                    "--out",
                    str(data),
                ],
                check=True,
            )
            for adj in ["ancova", "change"]:
                res = tmp / f"{name}_{sessions}_{adj}.json"
                subprocess.run(
                    [
                        *py,
                        str(d / "fit_model.py"),
                        "--data",
                        str(data),
                        "--adjustment",
                        adj,
                        "--out",
                        str(res),
                    ],
                    check=True,
                    capture_output=True,
                )
                out[f"{name}/{sessions}/{adj}"] = json.loads(res.read_text())
    # Enrollment and exclusions
    import pandas as pd

    participants = pd.read_csv(tmp / "participants.csv")
    print(f"enrolled: {len(participants)}")
    print("by site:", participants["site"].value_counts().sort_index().to_dict())
    for name in ["as_built", "fix_1"]:
        df = pd.read_csv(tmp / f"{name}_v2.csv")
        print(
            f"{name} analyzed: {len(df)}; by site:",
            df["site"].value_counts().sort_index().to_dict(),
        )
    cols = ["as_built", "fix_1", "fix_2", "fixed"]
    for adj in ["ancova", "change"]:
        print(f"\nv2 sessions, {adj}")
        print(f"{'key':24s}" + "".join(f"{c:>12s}" for c in cols))
        for key in KEYS:
            vals = [out[f"{c}/v2/{adj}"][key] for c in cols]
            print(f"{key:24s}" + "".join(f"{v:>12.4g}" for v in vals))
    stale = out["as_built/v1/ancova"]["w12_mean_training"]
    print(f"\nbug 3 stale value (v1, as built) w12_mean_training: {stale:.4f}")
    print(
        "v1 as built, ancova:",
        json.dumps(
            {k: round(v, 4) for k, v in out["as_built/v1/ancova"].items()
             if isinstance(v, float)}
        ),
    )
    (Path(__file__).parent / "round-2-key-values.json").write_text(
        json.dumps(out, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
