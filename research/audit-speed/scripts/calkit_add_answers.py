"""Write answers and evidence into the Calkit project's questions.

Stands in for the agent editing calkit.yaml by hand after the pipeline ran.
"""

import sys

from ruamel.yaml import YAML

ANSWERS = [
    {
        "answer": (
            "Yes. Adjusting for SES, treatment raised outcome scores by"
            " {effect:.2f} points (95% CI {effect_lo:.2f} to"
            " {effect_hi:.2f}; p = {effect_p:.2g}; N = {n})."
        ),
        "evidence": [
            {
                "kind": "result",
                "path": "results/model.json",
                "values": {
                    "effect": "treatment_effect",
                    "effect_lo": "treatment_ci_low",
                    "effect_hi": "treatment_ci_high",
                    "effect_p": "treatment_p",
                    "n": "n_analyzed",
                },
            },
            {"kind": "figure", "path": "results/outcome_by_ses.png"},
            {
                "kind": "document",
                "path": "results/report.md",
                "section": "Results",
            },
        ],
    },
    {
        "answer": (
            "Adjusting for condition, high-SES participants scored"
            " {ses_high:.2f} points higher than low-SES participants"
            " (95% CI {ses_high_lo:.2f} to {ses_high_hi:.2f};"
            " p = {ses_high_p:.2g})."
        ),
        "evidence": [
            {
                "kind": "result",
                "path": "results/model.json",
                "values": {
                    "ses_high": "ses_high_vs_low",
                    "ses_high_lo": "ses_high_ci_low",
                    "ses_high_hi": "ses_high_ci_high",
                    "ses_high_p": "ses_high_p",
                },
            },
            {"kind": "figure", "path": "results/outcome_by_ses.png"},
            {
                "kind": "document",
                "path": "results/report.md",
                "section": "Results",
            },
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
