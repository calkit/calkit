"""Write answers and evidence into the Calkit project's questions.

Stands in for the agent editing calkit.yaml by hand after the pipeline ran,
following the calkit:conventions skill: numbers come from results files
through placeholders rather than being typed.
"""

import sys

from ruamel.yaml import YAML

MODEL = "results/model-ancova.json"
CHANGE = "results/model-change.json"
FIGURE = {"kind": "figure", "path": "results/score_by_week.png"}
REPORT = {"kind": "document", "path": "results/report.md", "section": "Results"}
ANSWERS = [
    {
        "answer": (
            "Yes. Adjusting for baseline score, age, and education, training"
            " raised week-12 scores by {effect:.2f} points (95% CI"
            " {effect_lo:.2f} to {effect_hi:.2f}; p = {effect_p:.2g};"
            " N = {n}). Mean week-12 score was {w12_training:.1f} in the"
            " training group and {w12_control:.1f} in the control group,"
            " from baseline means of {w0_training:.1f} and {w0_control:.1f}."
        ),
        "evidence": [
            {
                "kind": "result",
                "path": MODEL,
                "values": {
                    "effect": "treatment_effect",
                    "effect_lo": "treatment_ci_low",
                    "effect_hi": "treatment_ci_high",
                    "effect_p": "treatment_p",
                    "n": "n_analyzed",
                    "w12_training": "w12_mean_training",
                    "w12_control": "w12_mean_control",
                    "w0_training": "baseline_mean_training",
                    "w0_control": "baseline_mean_control",
                },
            },
            FIGURE,
            REPORT,
        ],
    },
    {
        "answer": (
            "Modeling change from baseline to week 12 instead, training"
            " raised scores by {effect:.2f} points (95% CI {effect_lo:.2f}"
            " to {effect_hi:.2f}; p = {effect_p:.2g}), against"
            " {ancova:.2f} points in the ANCOVA."
        ),
        "evidence": [
            {
                "kind": "result",
                "path": CHANGE,
                "values": {
                    "effect": "treatment_effect",
                    "effect_lo": "treatment_ci_low",
                    "effect_hi": "treatment_ci_high",
                    "effect_p": "treatment_p",
                },
            },
            {
                "kind": "result",
                "path": MODEL,
                "values": {"ancova": "treatment_effect"},
            },
            REPORT,
        ],
    },
    {
        "answer": (
            "Adjusting for arm, baseline score, and age, participants with"
            " graduate education scored {grad:.2f} points higher at week 12"
            " than those with secondary education (95% CI {grad_lo:.2f} to"
            " {grad_hi:.2f}; p = {grad_p:.2g}). Each additional 10 years of"
            " age was associated with a change of {age:.2f} points (95% CI"
            " {age_lo:.2f} to {age_hi:.2f}). The model explained"
            " {r2:.3f} of the variance in week-12 scores (R²)."
        ),
        "evidence": [
            {
                "kind": "result",
                "path": MODEL,
                "values": {
                    "grad": "graduate_vs_secondary",
                    "grad_lo": "graduate_ci_low",
                    "grad_hi": "graduate_ci_high",
                    "grad_p": "graduate_p",
                    "age": "age_per_decade",
                    "age_lo": "age_ci_low",
                    "age_hi": "age_ci_high",
                    "r2": "r_squared",
                },
            },
            REPORT,
        ],
    },
]


def main() -> None:
    path = sys.argv[1]
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    with open(path) as f:
        ck = yaml.load(f)
    for question, update in zip(ck["questions"], ANSWERS):
        question["answer"] = update["answer"]
        question["evidence"] = update["evidence"]
    with open(path, "w") as f:
        yaml.dump(ck, f)


if __name__ == "__main__":
    main()
