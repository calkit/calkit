"""Summarize the coded real-world errors in real-world-errors/errors.csv.

The file holds three samples with different selection biases, so each is
summarized on its own and never pooled: human-era general research
(``general``), computational physics and engineering errata
(``physics_engineering``), and errors made by AI agents (``agent``).

For each sample, counts errors by type and impact, with a weighted count
(changed 3, weakened 1, unclear 0.5, none 0), and, for errors that changed
a conclusion, the stage that introduced them and how they were found. Also
gives the share of weighted impact from types a generic data profile could
catch: sentinel or missing-value codes, merges or joins, and duplicate
rows, and separately with unit or conversion errors added, since a profile
sees a unit error only when it pushes values outside a column's usual
range.

Writes results/real-world-errors.json, for answers to cite, and
results/real-world-errors.md, a table per sample.
"""

import collections
import csv
import json
from pathlib import Path

WEIGHTS = {"changed": 3, "weakened": 1, "unclear": 0.5, "none": 0}
IMPACTS = list(WEIGHTS)
SAMPLES = {
    "general": "Human era, general research",
    "physics_engineering": "Human era, computational physics and engineering",
    "agent": "Agent era",
}
PROFILE_TYPES = ["sentinel_or_missing_code", "merge_or_join", "duplicate_rows"]
PROFILE_TYPES_WITH_UNITS = PROFILE_TYPES + ["unit_or_conversion"]
# Ways of finding an error that rest on a person rather than a tool
PERSON_FOUND = ["author_self_check", "reader_report", "domain_knowledge"]
# A wrong model, formula, or reading of results, not of the data's values
MODELING_TYPES = [
    "calculation_error",
    "numerical_method",
    "leakage",
    "interpretation_error",
    "wrong_variable",
    "inference",
]


def get_sample(row: dict) -> str:
    """Get the sample a row belongs to."""
    if row["era"] == "agent":
        return "agent"
    if row["field_group"] == "computational_physics_engineering":
        return "physics_engineering"
    return "general"


def count_weighted(counts: dict[str, int]) -> float:
    """Weight counts by impact."""
    return sum(WEIGHTS[impact] * n for impact, n in counts.items())


with open("real-world-errors/errors.csv", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))
summary: dict = {
    "weights": WEIGHTS,
    "profile_types": PROFILE_TYPES,
    "profile_types_with_units": PROFILE_TYPES_WITH_UNITS,
    "person_found": PERSON_FOUND,
    "modeling_types": MODELING_TYPES,
    "n_rows": len(rows),
    "n_low_or_medium_confidence": sum(
        row["confidence"] != "high" for row in rows
    ),
    "samples": {},
}
lines = []
for sample, title in SAMPLES.items():
    sample_rows = [row for row in rows if get_sample(row) == sample]
    errors = [row for row in sample_rows if row["error_type"] != "none_found"]
    changed = [row for row in errors if row["impact"] == "changed"]
    # Counts by type and impact
    by_type: dict[str, dict] = {}
    for row in errors:
        counts = by_type.setdefault(
            row["error_type"], {impact: 0 for impact in IMPACTS}
        )
        counts[row["impact"]] += 1
    for counts in by_type.values():
        counts["weighted"] = count_weighted(
            {impact: counts[impact] for impact in IMPACTS}
        )
    by_type = dict(
        sorted(
            by_type.items(),
            key=lambda item: (-item[1]["weighted"], -item[1]["changed"]),
        )
    )
    weighted = sum(counts["weighted"] for counts in by_type.values())
    unspecified = by_type.get("unspecified", {}).get("weighted", 0)
    # Changed errors by stage, way found, and type
    how_found: collections.Counter = collections.Counter()
    for row in changed:
        how_found.update(h.strip() for h in row["how_found"].split(";"))
    n_changed_by_person = sum(
        any(h.strip() in PERSON_FOUND for h in row["how_found"].split(";"))
        for row in changed
    )
    changed_types = collections.Counter(row["error_type"] for row in changed)
    # Share of weighted impact from types a profile could catch
    profile = {}
    for key, types in [
        ("core", PROFILE_TYPES),
        ("with_units", PROFILE_TYPES_WITH_UNITS),
    ]:
        catchable = sum(by_type.get(t, {}).get("weighted", 0) for t in types)
        profile[key] = {
            "weighted": catchable,
            "share": catchable / weighted,
            "share_of_specified": catchable / (weighted - unspecified),
            "n_changed": sum(changed_types[t] for t in types),
        }
    stale = [
        row
        for row in errors
        if row["error_type"] == "stale_result"
        or row["mismatch_cause"] == "stale"
    ]
    top_changed_type = changed_types.most_common(1)[0][0]
    summary["samples"][sample] = {
        "title": title,
        "n_rows": len(sample_rows),
        "n_errors": len(errors),
        "n_none_found": len(sample_rows) - len(errors),
        "n_low_or_medium_confidence": sum(
            row["confidence"] != "high" for row in sample_rows
        ),
        "selections": dict(
            collections.Counter(row["selection"] for row in sample_rows)
        ),
        "impact": {
            impact: sum(row["impact"] == impact for row in errors)
            for impact in IMPACTS
        },
        "weighted": weighted,
        "unspecified_weighted": unspecified,
        "by_type": by_type,
        "changed": {
            "n": len(changed),
            "n_specified": len(changed) - changed_types["unspecified"],
            "top_type": top_changed_type,
            "top_type_n": changed_types[top_changed_type],
            "n_modeling": sum(changed_types[t] for t in MODELING_TYPES),
            "n_found_by_person": n_changed_by_person,
            "by_type": dict(changed_types.most_common()),
            "by_stage": dict(
                collections.Counter(
                    row["stage_introduced"] for row in changed
                ).most_common()
            ),
            "by_how_found": dict(how_found.most_common()),
        },
        "n_writing_stage": sum(
            row["stage_introduced"] == "writing"
            and row["impact"] in ("changed", "weakened")
            for row in errors
        ),
        "n_overclaim_or_fabricated": sum(
            row["error_type"] in ("overclaim", "fabricated_result")
            for row in errors
        ),
        "profile_catchable": profile,
        "stale": {
            "n": len(stale),
            "n_changed": sum(row["impact"] == "changed" for row in stale),
            "ids": [row["id"] for row in stale],
        },
    }
    # Markdown table for the sample
    lines += [
        f"## {title}",
        "",
        f"{len(sample_rows)} rows, {len(errors)} errors; "
        f"weighted impact {weighted:g}.",
        "",
        "| Error type | Changed | Weakened | Unclear | None | Weighted |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for error_type, counts in by_type.items():
        lines.append(
            f"| {error_type} | {counts['changed']} | {counts['weakened']} "
            f"| {counts['unclear']} | {counts['none']} "
            f"| {counts['weighted']:g} |"
        )
    stages = summary["samples"][sample]["changed"]["by_stage"]
    found = summary["samples"][sample]["changed"]["by_how_found"]
    lines += [
        "",
        "Changed errors by stage introduced: "
        + ", ".join(f"{k} {v}" for k, v in stages.items())
        + ".",
        "",
        "Changed errors by how found (an error can have several): "
        + ", ".join(f"{k} {v}" for k, v in found.items())
        + ".",
        "",
        "Share of weighted impact a data profile could catch: "
        f"{profile['core']['share']:.0%} "
        f"({', '.join(PROFILE_TYPES)}), "
        f"{profile['with_units']['share']:.0%} with unit_or_conversion.",
        "",
    ]
Path("results").mkdir(exist_ok=True)
with open("results/real-world-errors.json", "w") as f:
    json.dump(summary, f, indent=2)
    f.write("\n")
with open("results/real-world-errors.md", "w") as f:
    f.write("\n".join(lines).rstrip() + "\n")
