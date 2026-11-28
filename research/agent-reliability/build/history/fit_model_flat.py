# fit the ANCOVA and change-score models and save the results for the paper
import json

import pandas as pd
import statsmodels.formula.api as smf

DATA = "data/merged_final.csv"

FORMULAS = {
    "ancova": "score_w12 ~ treated + score_w0 + I(age / 10) + C(education)",
    "change": "I(score_w12 - score_w0) ~ treated + I(age / 10) + C(education)",
}

df = pd.read_csv(DATA)
by_arm = df.groupby("arm")[["score_w0", "score_w12"]].mean()
for name, formula in FORMULAS.items():
    fit = smf.ols(formula, data=df).fit()
    ci = fit.conf_int()
    graduate = "C(education)[T.graduate]"
    age = "I(age / 10)"
    results = {
        "adjustment": name,
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
    with open(f"results/model_{name}.json", "w") as f:
        json.dump(results, f, indent=2)
    print(name, round(results["treatment_effect"], 2))
