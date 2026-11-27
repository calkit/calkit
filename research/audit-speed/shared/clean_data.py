"""Clean the raw participant data for analysis."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

SES_LABELS = ["low", "middle", "high"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--missing-ses", choices=["drop", "category"], default="drop"
    )
    args = parser.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.raw)
    df = df[df["age"].between(18, 65)].copy()
    df["ses"] = pd.cut(
        df["ses_code"], bins=[0, 1, 2, np.inf], labels=SES_LABELS
    )
    if args.missing_ses == "drop":
        df = df.dropna(subset=["ses"])
    else:
        df["ses"] = df["ses"].cat.add_categories("missing").fillna("missing")
    df["treated"] = (df["condition"] == "treatment").astype(int)
    cols = ["participant_id", "condition", "treated", "age", "ses", "outcome"]
    df[cols].to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
