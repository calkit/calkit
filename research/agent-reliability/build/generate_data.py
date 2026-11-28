"""Generate round 2's synthetic raw data: the files each arm receives.

Stands in for data collection, so it isn't copied into any arm. Writes
participants.csv, the original sessions export (v1), and the corrected
export (v2), which rescored week-12 form B sessions that v1 scored with
the wrong answer key.

Planted here: site D's sessions export writes participant IDs without zero
padding ("D-7" rather than "D-007"), which the shared prepare_data.py doesn't
handle, so its inner join drops site D.
"""

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SEED = 20261127
SITE_SIZES = {"A": 150, "B": 152, "C": 142, "D": 36}
EDUCATION = ["secondary", "college", "graduate"]
EDUCATION_P = {"A": [0.40, 0.35, 0.25], "D": [0.65, 0.25, 0.10]}
EDUCATION_SHIFT = {"secondary": 0.0, "college": 1.5, "graduate": 4.0}
# Extra gain by week 12, larger with more education
EDUCATION_GAIN = {"secondary": 0.0, "college": 2.5, "graduate": 4.5}
# Training effect at week 12, larger at site D, whose staff coached
# sessions; site E joins later (build/make_site_e.py)
EFFECT = {"A": 3.0, "B": 3.0, "C": 3.0, "D": 7.0, "E": 3.0}
WEEKS = [0, 4, 8, 12]
FORM_B_KEY_ERROR = -2.5


def simulate_sessions(p: Any, rng: np.random.Generator) -> list[dict]:
    """One participant's assessment sessions, as their site exports them."""
    sessions = []
    u = rng.normal(0.0, 7.0)
    age_c = p.age - 72
    treated = p.arm == "training"
    # Dropout: about 6% miss week 12, half of those also week 8
    last_week = 12
    if rng.random() < 0.06:
        last_week = 8 if rng.random() < 0.5 else 4
    for week in WEEKS:
        if week > last_week:
            continue
        true = (
            50.0
            + EDUCATION_SHIFT[p.education]
            + u
            - 0.25 * age_c
            - (0.1 / 12) * age_c * week
            + 0.1 * week
            + EDUCATION_GAIN[p.education] * week / 12
            + treated * EFFECT[p.site] * week / 12
            + rng.normal(0.0, 4.0)
        )
        form = "A" if rng.random() < 0.5 else "B"
        complete = rng.random() > 0.015
        date = p.enrolled_on + np.timedelta64(
            7 * week + int(rng.integers(-2, 3)) + 2, "D"
        )
        pid = p.participant_id
        if p.site == "D":
            pid = f"D-{int(pid.split('-')[1])}"
        sessions.append(
            {
                "participant_id": pid,
                "week": week,
                "session_date": date,
                "form": form,
                "status": "complete" if complete else "incomplete",
                "score_true": round(true, 1) if complete else np.nan,
            }
        )
    return sessions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    # Participants, randomized within site
    rows = []
    start = np.datetime64("2025-09-01")
    for site, n in SITE_SIZES.items():
        arms = rng.permutation(np.repeat(["training", "control"], n // 2))
        p_edu = EDUCATION_P.get(site, EDUCATION_P["A"])
        for i in range(n):
            rows.append(
                {
                    "participant_id": f"{site}-{i + 1:03d}",
                    "site": site,
                    "enrolled_on": start
                    + np.timedelta64(int(rng.integers(0, 130)), "D"),
                    "arm": arms[i],
                    "age": int(rng.integers(60, 86)),
                    "sex": "F" if rng.random() < 0.6 else "M",
                    "education": EDUCATION[rng.choice(3, p=p_edu)],
                }
            )
    participants = pd.DataFrame(rows)
    # A few screening errors outside the eligible ages
    bad = rng.choice(len(participants), size=3, replace=False)
    participants.loc[bad, "age"] = [58, 59, 87]
    # Sessions
    sessions = []
    for p in participants.itertuples():
        sessions += simulate_sessions(p, rng)
    sessions = pd.DataFrame(sessions)
    sessions = sessions.sort_values(
        ["session_date", "participant_id"], kind="stable"
    ).reset_index(drop=True)
    v2 = sessions.rename(columns={"score_true": "score"})
    v1 = v2.copy()
    keyed = (v1["week"] == 12) & (v1["form"] == "B") & v1["score"].notna()
    v1.loc[keyed, "score"] = (v1.loc[keyed, "score"] + FORM_B_KEY_ERROR).round(
        1
    )
    participants.to_csv(out / "participants.csv", index=False)
    v1.to_csv(out / "sessions_v1.csv", index=False)
    v2.to_csv(out / "sessions_v2.csv", index=False)
    print(
        f"{len(participants)} participants, {len(v2)} sessions,"
        f" {int(keyed.sum())} week-12 form B sessions rescored in v2"
    )


if __name__ == "__main__":
    main()
