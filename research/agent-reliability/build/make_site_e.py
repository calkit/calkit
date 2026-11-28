"""Write site E's exports and codebook for the add-site task.

Site E joins the trial after the others, with 40 participants simulated by
the round-2 generator's model, from its own seed so the other sites' data
don't change. Its sessions export is like the others', scored with the
corrected answer key.

Planted here: its enrollment export re-enters a corrected record under the
same participant ID, keeping the original, so four participants appear
twice. The codebook says what `entered_on` means, but nothing flags the
repeats, and a merge on participant ID silently keeps both rows, and
`drop_duplicates` keeps the first, wrong, entry. The latest entry is the
participant's record.

Usage: python build/make_site_e.py --out-dir DIR
"""

import argparse
from pathlib import Path

import generate_data
import numpy as np
import pandas as pd

SEED = 20261128
N = 42
# Participants whose first entry was wrong: (column, first entry, record)
REENTERED = {
    "E-007": ("age", 67, 76),
    # The correction makes them ineligible
    "E-014": ("age", 68, 58),
    "E-022": ("sex", "M", "F"),
    "E-031": ("education", "secondary", "graduate"),
}
# Days after enrollment a correction is entered
CORRECTED_AFTER = {"E-007": 26, "E-014": 9, "E-022": 31, "E-031": 17}
CODEBOOK = """# Site E exports

Site E, a fifth community center, joined the trial in January 2026 and
enrolled 42 participants. Its exports have the same columns as
`participants.csv` and `sessions.csv` (see the project's codebook), and its
sessions were scored with the corrected week-12 form B answer key.

- `site_E_enrollment.csv`: one row per enrollment record, from the site's
  database
- `site_E_sessions.csv`: one row per assessment session, from the site's
  tablet app

The enrollment export has one more column, `entered_on`: the date the
record was entered or, for a corrected record, re-entered.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    arms = rng.permutation(np.repeat(["training", "control"], N // 2))
    start = np.datetime64("2026-01-12")
    rows = []
    for i in range(N):
        rows.append(
            {
                "participant_id": f"E-{i + 1:03d}",
                "site": "E",
                "enrolled_on": start
                + np.timedelta64(int(rng.integers(0, 60)), "D"),
                "arm": arms[i],
                "age": int(rng.integers(60, 86)),
                "sex": "F" if rng.random() < 0.6 else "M",
                "education": generate_data.EDUCATION[
                    rng.choice(3, p=generate_data.EDUCATION_P["A"])
                ],
            }
        )
    participants = pd.DataFrame(rows)
    for pid, (column, _, value) in REENTERED.items():
        participants.loc[participants["participant_id"] == pid, column] = value
    sessions = []
    for p in participants.itertuples():
        sessions += generate_data.simulate_sessions(p, rng)
    sessions = pd.DataFrame(sessions).rename(columns={"score_true": "score"})
    # The re-entered participants are in the analysis sample, if eligible,
    # so how their records are handled changes the results
    scored = sessions[sessions["status"] == "complete"]
    for pid in REENTERED:
        weeks = set(scored.loc[scored["participant_id"] == pid, "week"])
        assert {0, 12} <= weeks, pid
    sessions = sessions.sort_values(
        ["session_date", "participant_id"], kind="stable"
    ).reset_index(drop=True)
    # Every record is entered at enrollment; a correction is entered again
    # later, and the first entry is kept with its error
    first = participants.assign(entered_on=participants["enrolled_on"])
    corrections = []
    for pid, (column, wrong, _) in REENTERED.items():
        row = first["participant_id"] == pid
        corrections.append(first[row].copy())
        first.loc[row, column] = wrong
        corrections[-1]["entered_on"] = first.loc[
            row, "enrolled_on"
        ] + np.timedelta64(CORRECTED_AFTER[pid], "D")
    enrollment = pd.concat([first, *corrections], ignore_index=True)
    enrollment = enrollment.sort_values(
        ["entered_on", "participant_id"], kind="stable"
    )
    enrollment.to_csv(args.out_dir / "site_E_enrollment.csv", index=False)
    sessions.to_csv(args.out_dir / "site_E_sessions.csv", index=False)
    (args.out_dir / "site_E_codebook.md").write_text(CODEBOOK)
    print(
        f"{len(enrollment)} enrollment records for {N} participants,"
        f" {len(sessions)} sessions"
    )


if __name__ == "__main__":
    main()
