"""Fit the outcome model and save its estimates and descriptive statistics."""

import argparse
import json
from pathlib import Path

import pandas as pd
import statsmodels.formula.api as smf

FORMULAS = {
    # Week-12 score adjusted for baseline score (ANCOVA)
    "ancova": "score_w12 ~ treated + score_w0 + I(age / 10)",
    # Change from baseline to week 12
    "change": "I(score_w12 - score_w0) ~ treated + I(age / 10)",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument(
        "--adjustment", choices=sorted(FORMULAS), default="ancova"
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.data)
    fit = smf.ols(FORMULAS[args.adjustment], data=df).fit()
    ci = fit.conf_int()
    age = "I(age / 10)"
    by_arm = df.groupby("arm")[["score_w0", "score_w12"]].mean()
    results = {
        "adjustment": args.adjustment,
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
        "age_per_decade": float(fit.params[age]),
        "age_ci_low": float(ci.loc[age, 0]),
        "age_ci_high": float(ci.loc[age, 1]),
        "r_squared": float(fit.rsquared),
    }
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
