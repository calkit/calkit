"""Record findings in astra.yaml from the materialized outputs.

Stands in for the agent reading the results and writing findings by hand.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import yaml


def main() -> None:
    spec_path, results_path, report_path = sys.argv[1:4]
    with open(results_path) as f:
        r = json.load(f)
    with open(report_path) as f:
        report = " ".join(f.read().split())
    results_dir = os.path.dirname(results_path)
    commit_shas = {}
    for name in os.listdir(results_dir):
        if name.startswith("."):
            continue
        commit_shas[name.split(".")[0]] = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", f"{results_dir}/{name}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def get_quote(start: str) -> str:
        i = report.index(start)
        return report[i : report.index(")", i) + 1]

    treatment_quote = get_quote("Adjusting for SES, treatment raised")
    ses_quote = get_quote("Adjusting for condition, high-SES")
    findings = {
        "treatment_effect": {
            "label": "Treatment effect",
            "claim": (
                f"Adjusting for SES, treatment raised outcome scores by"
                f" {r['treatment_effect']:.2f} points (95% CI"
                f" {r['treatment_ci_low']:.2f} to"
                f" {r['treatment_ci_high']:.2f}; p ="
                f" {r['treatment_p']:.2g}; N = {r['n_analyzed']})."
            ),
            "created_at": created_at,
            "scope": "Baseline universe (missing SES excluded).",
            "evidence": [
                {
                    "id": "ev_model",
                    "artifact": "model_results",
                    "source_commit": commit_shas["model_results"],
                },
                {
                    "id": "ev_report",
                    "artifact": "report",
                    "source_commit": commit_shas["report"],
                    "quote": {"exact": treatment_quote},
                },
            ],
        },
        "ses_gap": {
            "label": "High vs. low SES",
            "claim": (
                f"Adjusting for condition, high-SES participants scored"
                f" {r['ses_high_vs_low']:.2f} points higher than low-SES"
                f" participants (95% CI {r['ses_high_ci_low']:.2f} to"
                f" {r['ses_high_ci_high']:.2f}; p = {r['ses_high_p']:.2g})."
            ),
            "created_at": created_at,
            "scope": "Baseline universe (missing SES excluded).",
            "evidence": [
                {
                    "id": "ev_model",
                    "artifact": "model_results",
                    "source_commit": commit_shas["model_results"],
                },
                {
                    "id": "ev_figure",
                    "artifact": "outcome_by_ses",
                    "source_commit": commit_shas["outcome_by_ses"],
                },
                {
                    "id": "ev_report",
                    "artifact": "report",
                    "source_commit": commit_shas["report"],
                    "quote": {"exact": ses_quote},
                },
            ],
        },
    }
    with open(spec_path) as f:
        text = f.read()
    text = text.rstrip() + "\n\n" + yaml.safe_dump(
        {"findings": findings}, sort_keys=False, width=79, allow_unicode=True
    )
    with open(spec_path, "w") as f:
        f.write(text)


if __name__ == "__main__":
    main()
