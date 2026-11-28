"""Generate the synthetic participant dataset for the study."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261127)
    parser.add_argument("--n", type=int, default=300)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    n = args.n
    # Randomize half the participants to each condition
    condition = rng.permutation(np.repeat(["control", "treatment"], n // 2))
    age = rng.integers(18, 66, size=n)
    ses_level = rng.choice([1, 2, 3], size=n, p=[0.35, 0.40, 0.25])
    ses_shift = np.select([ses_level == 2, ses_level == 3], [4.0, 9.0], 0.0)
    outcome = (
        50.0
        + 5.0 * (condition == "treatment")
        + ses_shift
        + 0.1 * (age - 40)
        + rng.normal(0.0, 8.0, size=n)
    )
    # Survey nonresponse on the SES item is exported as code 9
    p_nonresponse = np.select(
        [ses_level == 1, ses_level == 2], [0.30, 0.10], 0.03
    )
    nonresponse = rng.random(n) < p_nonresponse
    ses_code = np.where(nonresponse, 9, ses_level)
    df = pd.DataFrame(
        {
            "participant_id": np.arange(1, n + 1),
            "condition": condition,
            "age": age,
            "ses_code": ses_code,
            "outcome": outcome.round(1),
        }
    )
    df.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
