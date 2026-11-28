"""Profile tabular data, flagging values outside each column's pattern.

Two generic rules per numeric column, knowing nothing about the data:

- negative: a few negatives in an otherwise non-negative column, e.g., a
  missing-data code like -9 or -3105 among counts or scale points
- far: values far outside the 1st-99th percentile span, e.g., a code like
  999 among values from 1 to 8

Takes CSV files, or zip archives, whose CSVs are all profiled, and writes
a JSON of flags by file and column.
"""

import argparse
import io
import json
import zipfile
from pathlib import Path

import pandas as pd

# A rule only flags values that are rare in the column, as a share of it
MAX_NEGATIVE_SHARE = 0.05
MAX_FAR_SHARE = 0.02
# How many 1st-99th percentile spans past either end count as far
FAR_SPANS = 10
N_EXAMPLES = 4


def get_examples(values: pd.Series) -> list[float | int]:
    """Get a few distinct flagged values, as plain numbers."""
    examples = sorted(values.unique())[:N_EXAMPLES]
    return [int(v) if float(v).is_integer() else float(v) for v in examples]


def get_flags(df: pd.DataFrame) -> dict[str, list[dict]]:
    """Get each numeric column's flags."""
    flags: dict[str, list[dict]] = {}
    for column in df.select_dtypes("number").columns:
        values = df[column].dropna()
        if values.empty:
            continue
        column_flags = []
        negative = values[values < 0]
        if 0 < len(negative) < MAX_NEGATIVE_SHARE * len(values):
            column_flags.append(
                {
                    "rule": "negative",
                    "n": len(negative),
                    "n_values": len(values),
                    "examples": get_examples(negative),
                }
            )
        low, high = values.quantile(0.01), values.quantile(0.99)
        span = max(high - low, 1)
        far = values[
            (values > high + FAR_SPANS * span)
            | (values < low - FAR_SPANS * span)
        ]
        if 0 < len(far) < MAX_FAR_SHARE * len(values):
            column_flags.append(
                {
                    "rule": "far",
                    "n": len(far),
                    "n_values": len(values),
                    "examples": get_examples(far),
                }
            )
        if column_flags:
            flags[str(column)] = column_flags
    return flags


parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("paths", nargs="+", help="CSV files or zip archives.")
parser.add_argument("--output", required=True, help="JSON file to write.")
args = parser.parse_args()
# Every CSV given, by its name, or its path in an archive
tables: dict[str, pd.DataFrame] = {}
for path in args.paths:
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if name.endswith(".csv") and not name.startswith("__MACOSX"):
                    tables[name] = pd.read_csv(
                        io.BytesIO(archive.read(name)), low_memory=False
                    )
    else:
        tables[Path(path).name] = pd.read_csv(path, low_memory=False)
files: dict[str, dict] = {}
for name, df in tables.items():
    flags = get_flags(df)
    files[name] = {
        "n_rows": len(df),
        "n_numeric_columns": len(df.select_dtypes("number").columns),
        "n_flags": sum(len(column) for column in flags.values()),
        "flags": flags,
    }
profile = {
    "rules": {
        "negative": (
            "negatives in an otherwise non-negative column, under "
            f"{MAX_NEGATIVE_SHARE:.0%} of its values"
        ),
        "far": (
            f"values over {FAR_SPANS} 1st-99th percentile spans past either "
            f"end, under {MAX_FAR_SHARE:.0%} of its values"
        ),
    },
    "n_files": len(files),
    "n_files_flagged": sum(bool(f["flags"]) for f in files.values()),
    "n_columns_flagged": sum(len(f["flags"]) for f in files.values()),
    "n_flags": sum(f["n_flags"] for f in files.values()),
    "files": files,
}
Path(args.output).parent.mkdir(parents=True, exist_ok=True)
with open(args.output, "w") as f:
    json.dump(profile, f, indent=2)
    f.write("\n")
