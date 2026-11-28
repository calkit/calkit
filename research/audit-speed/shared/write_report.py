"""Write the study report from the model results."""

import argparse
from pathlib import Path
import json

MISSING_SES_SENTENCES = {
    "drop": "Participants with missing SES were excluded from the analysis.",
    "category": "Missing SES was analyzed as its own category.",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--figure", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--missing-ses", choices=["drop", "category"], default="drop"
    )
    args = parser.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.results) as f:
        results = json.load(f)
    with open(args.template) as f:
        template = f.read()
    report = template.format(
        **results,
        r_squared_pct=100 * results["r_squared"],
        missing_ses_sentence=MISSING_SES_SENTENCES[args.missing_ses],
        figure=args.figure,
    )
    with open(args.out, "w") as f:
        f.write(report)


if __name__ == "__main__":
    main()
