"""Merge participants with their assessment scores into one analysis table."""

import argparse
from pathlib import Path

import pandas as pd

EDUCATION_LEVELS = ["secondary", "college", "graduate"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--participants", required=True)
    parser.add_argument("--sessions", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    participants = pd.read_csv(
        args.participants, dtype={"participant_id": str}
    )
    sessions = pd.read_csv(args.sessions, dtype={"participant_id": str})
    # IDs are typed in at the sites, so normalize case and stray whitespace
    for df in (participants, sessions):
        df["participant_id"] = df["participant_id"].str.strip().str.upper()
    participants = participants[participants["age"].between(60, 85)]
    # One score per participant and week, from complete assessments only
    sessions = sessions[sessions["status"] == "complete"]
    scores = sessions.pivot(
        index="participant_id", columns="week", values="score"
    )
    scores.columns = [f"score_w{week}" for week in scores.columns]
    df = participants.merge(
        scores.reset_index(), on="participant_id", how="inner"
    )
    df = df.dropna(subset=["score_w0", "score_w12"])
    df["treated"] = (df["arm"] == "training").astype(int)
    # Order education levels lowest first
    df["education"] = pd.Categorical(
        df["education"], categories=EDUCATION_LEVELS
    )
    df = df.sort_values("participant_id")
    df.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
