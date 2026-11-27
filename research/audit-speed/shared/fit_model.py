"""Fit a linear model of outcome on condition and SES."""

import argparse
from pathlib import Path
import json

import pandas as pd
import statsmodels.formula.api as smf


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.clean)
    fit = smf.ols(
        "outcome ~ treated + C(ses, Treatment('low'))", data=df
    ).fit()
    ci = fit.conf_int()
    ses_high = "C(ses, Treatment('low'))[T.high]"
    ses_middle = "C(ses, Treatment('low'))[T.middle]"
    by_condition = df.groupby("condition")["outcome"].mean()
    results = {
        "n_analyzed": int(fit.nobs),
        "mean_age": float(df["age"].mean()),
        "mean_outcome_treatment": float(by_condition["treatment"]),
        "mean_outcome_control": float(by_condition["control"]),
        "treatment_effect": float(fit.params["treated"]),
        "treatment_ci_low": float(ci.loc["treated", 0]),
        "treatment_ci_high": float(ci.loc["treated", 1]),
        "treatment_p": float(fit.pvalues["treated"]),
        "ses_middle_vs_low": float(fit.params[ses_middle]),
        "ses_high_vs_low": float(fit.params[ses_high]),
        "ses_high_ci_low": float(ci.loc[ses_high, 0]),
        "ses_high_ci_high": float(ci.loc[ses_high, 1]),
        "ses_high_p": float(fit.pvalues[ses_high]),
        "r_squared": float(fit.rsquared),
    }
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
