"""Merge part CSVs into errors.csv, validate codes, and print summary tables."""

import collections
import csv
import glob
import os
import sys

WORK = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(WORK), "error-dataset", "errors.csv")
FIELDS = (
    "id,citation,doi,field,year,source,source_url,selection,error_type,"
    "stage_introduced,impact,how_found,package_available,notes,confidence,mismatch_cause,field_group,era"
).split(",")
TYPES = set(
    "transcription stale_result sentinel_or_missing_code unit_or_conversion "
    "merge_or_join duplicate_rows recode_error wrong_variable sample_filter "
    "spec_mismatch inference leakage environment missing_step other "
    "none_found unspecified fabricated_result fabricated_citation scope_drift "
    "overclaim unrecorded_decision reward_hacking unrequested_change "
    "stale_context forking_paths_at_scale calculation_error "
    "interpretation_error design_or_measurement upstream_data_error "
    "numerical_method".split()
)
STAGES = set(
    "data collection,import,cleaning,merge,transformation,modeling,"
    "inference,figure,writing,n/a,unknown".split(",")
)
IMPACTS = {"changed", "weakened", "none", "unclear"}
HOW = set(
    "reran_code read_code profiled_data compared_text_to_output "
    "rederived_from_raw domain_knowledge new_data reanalysis_alt_spec "
    "author_self_check reader_report reference_check unknown".split()
)
WEIGHT = {"changed": 3, "weakened": 1, "none": 0, "unclear": 0.5}
# Recodes from the stale-vs-typo review; (error_type or None, mismatch_cause,
# note to append or None).
RECODE = {
    "I4R-127": (
        "unspecified",
        "unclear",
        "Reproducers say the total may be a calculation error or typo; cause not determined.",
    ),
    "I4R-135-b": (None, "typo", None),
    "I4R-140-b": (None, "unclear", None),
    "I4R-142": (None, "unclear", None),
    "I4R-155-b": (
        None,
        "typo",
        "Reproducers attribute these to typing or rounding.",
    ),
    "I4R-157-a": (None, "unclear", None),
    "I4R-157-b": (None, "typo", "Reproducers call it a typo."),
    "I4R-158-d": (None, "unclear", None),
    "I4R-175-a": (None, "typo", "Reproducers call them typos."),
    "AG-S-14": (
        None,
        "stale",
        "Source says the agent failed to rerun the k-fold baseline.",
    ),
    "AG-S-15": (
        "unspecified",
        "unclear",
        "Source says incorrect or hallucinated, without separating the two.",
    ),
    "AG-A-2": (None, "unclear", None),
    "AG-A-4": (None, "unclear", None),
    "AG-A-18": (None, "unclear", None),
    "AG-A-19": ("unspecified", "unclear", None),
    "RW-56277": ("calculation_error", "", None),
    "RW-68779": ("calculation_error", "", None),
    "RW-47238-a": ("calculation_error", "", None),
    "RW-49982": ("calculation_error", "", None),
    "RW-37681-a": ("calculation_error", "", None),
    "RW-37681-b": ("calculation_error", "", None),
    "RW-47668": ("calculation_error", "", None),
    "RW-49665-b": ("calculation_error", "", None),
    "RW-47570": ("interpretation_error", "", None),
    "RW-38075": ("interpretation_error", "", None),
    "RW-45866": ("interpretation_error", "", None),
    "RW-52573-a": ("interpretation_error", "", None),
    "RW-63958-a": ("interpretation_error", "", None),
    "RW-37218": ("design_or_measurement", "", None),
    "RW-57232": ("design_or_measurement", "", None),
    "RW-38237": ("design_or_measurement", "", None),
    "I4R-148-d": ("design_or_measurement", "", None),
    "RW-63958-b": ("upstream_data_error", "", None),
    "I4R-116-e": ("upstream_data_error", "", None),
    "CPE-1": ("calculation_error", "", None),
    "CPE-2": ("calculation_error", "", None),
    "CPE-6": ("calculation_error", "", None),
    "CPE-7": ("calculation_error", "", None),
    "CPE-11": ("calculation_error", "", None),
    "CPE-13": ("calculation_error", "", None),
    "CPE-14": ("calculation_error", "", None),
    "CPE-20": ("calculation_error", "", None),
    "CPE-23": ("calculation_error", "", None),
    "CPE-27": ("calculation_error", "", None),
    "CPE-30": ("calculation_error", "", None),
    "CPE-34": ("calculation_error", "", None),
    "CPE-35": ("calculation_error", "", None),
    "CPE-36": ("calculation_error", "", None),
    "CPE-37": ("calculation_error", "", None),
    "CPE-41": ("calculation_error", "", None),
    "CPE-42": ("calculation_error", "", None),
    "CPE-49": ("calculation_error", "", None),
    "CPE-50": ("calculation_error", "", None),
    "CPE-54": ("calculation_error", "", None),
    "CPE-56": ("calculation_error", "", None),
    "CPE-61": ("calculation_error", "", None),
    "CPE-66": ("calculation_error", "", None),
    "CPE-70": ("calculation_error", "", None),
    "CPE-71": ("calculation_error", "", None),
    "CPE-19": ("numerical_method", "", None),
    "CPE-25": ("numerical_method", "", None),
    "CPE-55": ("numerical_method", "", None),
    "CPE-60": ("numerical_method", "", None),
    "CPE-68": ("design_or_measurement", "", None),
}
MISMATCH = {"", "stale", "typo", "unclear"}
rows = []
problems = []
for path in sorted(glob.glob(os.path.join(WORK, "part_*.csv"))):
    era = "agent" if "agent" in os.path.basename(path) else "human"
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            r["era"] = r.get("era") or era
            r["impact"] = r["impact"].lower()
            r.setdefault("mismatch_cause", "")
            r["field_group"] = r.get("field_group") or (
                "agent" if era == "agent" else "general"
            )
            if r["id"] in RECODE:
                t, m, note = RECODE[r["id"]]
                r["error_type"] = t or r["error_type"]
                r["mismatch_cause"] = m or r["mismatch_cause"]
                if note:
                    r["notes"] = r["notes"].rstrip() + " " + note
            if r["mismatch_cause"] not in MISMATCH:
                problems.append(
                    (path, r["id"], "mismatch", r["mismatch_cause"])
                )
            if r["error_type"] not in TYPES:
                problems.append((path, r["id"], "type", r["error_type"]))
            if r["stage_introduced"] not in STAGES:
                problems.append(
                    (path, r["id"], "stage", r["stage_introduced"])
                )
            if r["impact"] not in IMPACTS:
                problems.append((path, r["id"], "impact", r["impact"]))
            for h in r["how_found"].split(";"):
                if h.strip() not in HOW:
                    problems.append((path, r["id"], "how", h))
            if not r["source_url"].startswith("http"):
                problems.append((path, r["id"], "url", r["source_url"]))
            rows.append({k: r.get(k, "") for k in FIELDS})
ids = collections.Counter(r["id"] for r in rows)
problems += [("dup", i, "id", n) for i, n in ids.items() if n > 1]
for p in problems:
    print("PROBLEM", p, file=sys.stderr)
if "--write" in sys.argv:
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print("wrote", len(rows), "rows to", OUT)


def get_paper(r):
    i = r["id"]
    return i[:-2] if len(i) > 2 and i[-2] == "-" and i[-1].isalpha() else i


GROUPS = [
    (
        "human-general",
        lambda r: r["era"] == "human" and r["field_group"] == "general",
    ),
    (
        "human-cpe",
        lambda r: r["field_group"] == "computational_physics_engineering",
    ),
    ("human-all", lambda r: r["era"] == "human"),
    ("agent", lambda r: r["era"] == "agent"),
]
for era, pred in GROUPS:
    sub = [r for r in rows if pred(r)]
    if not sub:
        continue
    print(
        f"\n===== era={era}: {len(sub)} rows, "
        f"{len({get_paper(r) for r in sub})} papers/cases"
    )
    print("by selection (rows / papers):")
    for s in sorted({r["selection"] for r in sub}):
        ss = [r for r in sub if r["selection"] == s]
        print(f"  {s}: {len(ss)} / {len({get_paper(r) for r in ss})}")
    print("\ntype | changed weakened none unclear | total | weighted")
    t = collections.defaultdict(collections.Counter)
    for r in sub:
        t[r["error_type"]][r["impact"]] += 1
    order = sorted(
        t, key=lambda k: -sum(WEIGHT[i] * n for i, n in t[k].items())
    )
    for k in order:
        c = t[k]
        wsum = sum(WEIGHT[i] * n for i, n in c.items())
        print(
            f"  {k} | {c['changed']} {c['weakened']} {c['none']} "
            f"{c['unclear']} | {sum(c.values())} | {wsum:g}"
        )
    ch = [r for r in sub if r["impact"] == "changed"]
    print(
        "\nstage of changed:",
        collections.Counter(r["stage_introduced"] for r in ch).most_common(),
    )
    hf = collections.Counter()
    for r in ch:
        for h in r["how_found"].split(";"):
            hf[h.strip()] += 1
    print("how_found of changed:", hf.most_common())
    hf = collections.Counter()
    for r in sub:
        if r["error_type"] != "none_found":
            for h in r["how_found"].split(";"):
                hf[h.strip()] += 1
    print("how_found of all errors:", hf.most_common())
    print(
        "package of changed:",
        collections.Counter(r["package_available"] for r in ch).most_common(),
    )
    print("impact by selection:")
    for s in sorted({r["selection"] for r in sub}):
        print(
            "  ",
            s,
            collections.Counter(
                r["impact"] for r in sub if r["selection"] == s
            ).most_common(),
        )
    print(
        "mismatch_cause:",
        collections.Counter(
            (r["mismatch_cause"], r["impact"])
            for r in sub
            if r["mismatch_cause"]
        ).most_common(),
    )
    print(
        "confidence:",
        collections.Counter(r["confidence"] for r in sub).most_common(),
    )
