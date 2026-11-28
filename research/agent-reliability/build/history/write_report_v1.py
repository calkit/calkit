"""Write the study report from the model results."""

import argparse
import json
from pathlib import Path


def format_p(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.2g}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", required=True)
    parser.add_argument("--sensitivity", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--figure", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.primary) as f:
        primary = json.load(f)
    with open(args.sensitivity) as f:
        change = json.load(f)
    with open(args.template) as f:
        template = f.read()
    report = template.format(
        **primary,
        treatment_p_text=format_p(primary["treatment_p"]),
        change_treatment_effect=change["treatment_effect"],
        change_treatment_ci_low=change["treatment_ci_low"],
        change_treatment_ci_high=change["treatment_ci_high"],
        change_treatment_p_text=format_p(change["treatment_p"]),
        r_squared_pct=100 * primary["r_squared"],
        figure=args.figure,
    )
    with open(args.out, "w") as f:
        f.write(report)


if __name__ == "__main__":
    main()
