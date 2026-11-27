"""Compute the report's numbers with and without the planted cleaning error.

Runs the shared scripts on the shared raw data; the corrected run treats
SES code 9 as missing before cleaning, as the codebook says it is.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

SHARED = Path(__file__).resolve().parent.parent / "shared"


def run(script: str, *args: str) -> None:
    subprocess.run([sys.executable, str(SHARED / script), *args], check=True)


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    run("generate_data.py", "--out", f"{tmp}/raw.csv")
    raw = pd.read_csv(tmp / "raw.csv")
    print("ses_code counts:", raw["ses_code"].value_counts().sort_index().to_dict())
    raw[raw["ses_code"] != 9].to_csv(tmp / "raw_fixed.csv", index=False)
    out = {}
    for label, raw_path in [("as_built", "raw.csv"), ("corrected", "raw_fixed.csv")]:
        run("clean_data.py", "--raw", f"{tmp}/{raw_path}", "--out", f"{tmp}/{label}.csv")
        run("fit_model.py", "--clean", f"{tmp}/{label}.csv", "--out", f"{tmp}/{label}.json")
        out[label] = json.loads((tmp / f"{label}.json").read_text())
    for key in out["as_built"]:
        print(f"{key:24s} {out['as_built'][key]:>12.4g} {out['corrected'][key]:>12.4g}")


if __name__ == "__main__":
    main()
