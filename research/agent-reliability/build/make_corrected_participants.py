"""Write the coordinator's corrected participants file for task 4.

Three ages were mistyped at enrollment (the three outside 60-85, which the
analysis excluded) and five participants' sex was entered wrong. Nothing
else changes.
"""

import argparse

import pandas as pd

AGE_FIXES = {"A-091": 78, "C-002": 69, "C-135": 68}
SEX_FIXES = ["A-033", "A-120", "B-017", "B-088", "C-041"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--participants", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    df = pd.read_csv(args.participants, dtype=str, keep_default_na=False)
    for pid, age in AGE_FIXES.items():
        assert (df["participant_id"] == pid).sum() == 1
        df.loc[df["participant_id"] == pid, "age"] = str(age)
    for pid in SEX_FIXES:
        row = df["participant_id"] == pid
        assert row.sum() == 1
        df.loc[row, "sex"] = df.loc[row, "sex"].map({"F": "M", "M": "F"})
    df.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
