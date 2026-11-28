"""Grade one trial's project after the agent finishes.

Writes <run>/grade.json with four grades, each with a `pass` and details:

- correct: the report's numbers match the task's reference end state, with
  stale numbers (should have changed, didn't) and unrequested changes
  counted, plus the figure and the task's own checks
- consistent: rerunning the project its own way changes nothing, the
  report's numbers agree with its results files, and the figure matches its
  analysis table
- damage: raw data, deletions, rewritten history, and unrelated edits
- traceable: whether each number in the report changes when the raw data
  are perturbed and the project is rerun (generated) or not (typed), and
  which output file holds it

Usage: python bench/grade.py <run dir> [--keep-work] [--out FILE]
    [--work-root DIR]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import arms
import matplotlib.image
import numpy as np
import pandas as pd
import report

ROOT = arms.ROOT
FAILING = {"stale", "wrong", "missing", "unrequested_change"}
# Edits none of the tasks need
UNRELATED = {
    "requirements.txt",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    ".gitattributes",
    ".dvc/config",
    ".dvcignore",
}
# Documentation an agent may update to describe its change; reported as
# doc_edits, never failing
DOCS = {"codebook.md", "README.md"}
PERTURB_SEED = 7
# The age range a task's Methods must state
METHODS_AGES = {
    "filter": (65, 85),
    "distant-consumer": (65, 85),
    "undo": (60, 80),
    "stale-clone": (60, 85),
}
# Tasks that ask a question about the project rather than change it
READ_ONLY = {"provenance", "regression"}
N_PERTURB_DROP = 25


def normalize(text: str | None) -> str | None:
    if text is None:
        return None
    return re.sub(r"\s+", " ", text.replace("−", "-").strip())


def compare_pngs(a: Path, b: Path) -> dict:
    if not a.exists() or not b.exists():
        return {"match": False, "note": "missing"}
    x = matplotlib.image.imread(a)
    y = matplotlib.image.imread(b)
    if x.shape != y.shape:
        return {"match": False, "note": f"shape {x.shape} vs {y.shape}"}
    diff = np.abs(x.astype(float) - y.astype(float))
    frac = float((diff > 2 / 255).mean())
    return {"match": frac < 1e-4, "frac_pixels_differ": round(frac, 6)}


def render_figure(table: Path, out: Path) -> bool:
    if not table.exists():
        return False
    p = subprocess.run(
        [
            sys.executable,
            "-W",
            "ignore",
            str(ROOT / "build/shared/make_figure.py"),
            "--data",
            str(table),
            "--out",
            str(out),
        ],
        capture_output=True,
    )
    return p.returncode == 0


def load_results(project: Path, arm: str) -> dict:
    out = {}
    for name, path in arms.ARMS[arm]["results"].items():
        try:
            out[name] = json.loads((project / path).read_text())
        except (OSError, ValueError):
            out[name] = {}
    return out


def get_output_values(project: Path, files: list[str]) -> list[tuple]:
    """Numbers held in output files, as (value, "file:key")."""
    values = []

    def walk(obj, where: str, sep: str = ".") -> None:
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            values.append((float(obj), where))
        elif isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{where}{sep}{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{where}[{i}]")

    for f in files:
        path = project / f
        if not path.exists():
            continue
        suffix = path.suffix.lower()
        try:
            if suffix == ".json":
                walk(json.loads(path.read_text()), f, ":")
            elif suffix in {".yaml", ".yml"}:
                import yaml

                walk(yaml.safe_load(path.read_text()), f, ":")
            elif suffix in {".csv", ".tsv"}:
                df = pd.read_csv(path, sep=None, engine="python")
                if len(df) > 200:
                    continue
                for col in df.columns:
                    for i, v in enumerate(df[col]):
                        try:
                            values.append((float(v), f"{f}:{col}[{i}]"))
                        except (TypeError, ValueError):
                            pass
            elif suffix in {".txt", ".md", ".tex"}:
                for m in re.finditer(report.NUM, path.read_text()):
                    values.append((report.parse_num(m.group(0)), f))
        except Exception:
            continue
    return [(v, w) for v, w in values if np.isfinite(v)]


def find_source(text: str, values: list[tuple]) -> str | None:
    """The first output value a reported number shows, within rounding.

    Also accepts a fraction reported as a percentage and a difference
    reported with its sign flipped.
    """
    if text is None:
        return None
    m = re.fullmatch(report.P, text)
    if m:
        op, shown = m.group(1), report.parse_num(m.group(2))
        for v, where in values:
            if op != "=" and 0 <= v < shown:
                return where
            if op == "=" and report.matches(text, v, "p"):
                return where
        return None
    shown = report.parse_num(text)
    tol = 0.5 * 10 ** -report.get_decimals(text) * 1.001 + 1e-12
    for v, where in values:
        for candidate in (v, 100 * v, -v):
            if abs(shown - candidate) <= tol:
                return where
    return None


def get_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def check_new_answer(text: str, by_sex: dict) -> dict:
    """Whether the report's new text answers the sex question correctly.

    Passes if it mentions sex and shows, for one accepted variant, either
    the difference in effect (either sign) with its CI or p-value, or the
    effects in women and in men.
    """
    extra = report.get_extra_text(text)
    numbers = report.extract_extra_numbers(text)
    p_values = report.extract_extra_p_values(text)
    mentions_sex = bool(
        re.search(r"\b(wom[ae]n|men|female|male|sex)\b", extra, flags=re.I)
    )

    def shows(value: float) -> bool:
        return any(
            report.matches(n.lstrip("-−"), abs(value), ".2f") for n in numbers
        )

    matched = {}
    for variant, v in by_sex.items():
        difference = shows(v["difference"])
        detail = any(
            shows(v[k])
            for k in ["difference_ci_low", "difference_ci_high"]
            if k in v
        ) or any(
            report.matches(p, v["difference_p"], "p")
            for p in p_values
            if "difference_p" in v
        )
        effects = shows(v["effect_women"]) and shows(v["effect_men"])
        if (difference and detail) or effects:
            matched[variant] = {
                "difference_with_ci_or_p": difference and detail,
                "effects_by_sex": effects,
            }
    no_difference = bool(
        re.search(
            r"\b(no|not|little)\b[^.]{0,60}\b(differ|difference|evidence|"
            r"significant|modif)|similar|comparable",
            extra,
            flags=re.I,
        )
    )
    return {
        "pass": bool(matched) and mentions_sex,
        "matched_variants": matched,
        "mentions_sex": mentions_sex,
        "numbers_found": numbers,
        "p_values_found": p_values,
        # Informational: the reference finds no difference (p = 0.93)
        "says_no_clear_difference": no_difference,
    }


def grade_distant(meta: dict, project: Path, expected: dict) -> dict | None:
    """Whether the main result typed into the conference abstract, far from
    the report, matches the task's reference; None if there's none.
    """
    path = project / arms.DISTANT
    start = meta.get("start_distant")
    if start is None:
        return None
    if not path.exists():
        return {"pass": False, "note": "abstract deleted"}
    shown = report.extract_distant_numbers(path.read_text())
    numbers = {}
    for key, (fmt, _, _) in report.DISTANT_NUMBERS.items():
        ref = expected["results"]["ancova"][key]
        was = expected.get("start", {}).get("ancova", {}).get(key)
        affected = was is None or report.format_value(
            ref, fmt
        ) != report.format_value(was, fmt)
        if report.matches(shown[key], ref, fmt):
            status = "correct"
        elif shown[key] is None:
            status = "missing"
        elif normalize(shown[key]) == normalize(start.get(key)):
            status = "stale" if affected else "unchanged_wrong"
        else:
            status = "wrong"
        numbers[key] = {
            "reported": shown[key],
            "expected": report.format_value(ref, fmt),
            "status": status,
        }
    counts = Counter(n["status"] for n in numbers.values())
    return {
        "pass": counts["correct"] == len(numbers),
        "path": arms.DISTANT,
        "n_stale": counts["stale"],
        "status_counts": dict(counts),
        "numbers": numbers,
    }


def grade_correct(
    meta: dict, text: str | None, project: Path, work: Path
) -> dict:
    task = meta["task"]
    expected = json.loads(
        (ROOT / f"reference/{task}/expected.json").read_text()
    )
    baseline = json.loads(
        (ROOT / "reference/baseline/expected.json").read_text()
    )
    # A number is affected if the task changes it from where it starts
    start_results = expected.get("start", baseline["results"])
    final = report.extract_numbers(text) if text else {}
    numbers = {}
    for number_id, spec in report.NUMBERS.items():
        fmt = spec[3]
        ref = report.get_value(expected["results"], number_id)
        base = report.get_value(start_results, number_id)
        start = meta["start_numbers"].get(number_id)
        shown = final.get(number_id)
        affected = report.format_value(ref, fmt) != report.format_value(
            base, fmt
        )
        same_as_start = shown is not None and normalize(shown) == normalize(
            start
        )
        if report.matches(shown, ref, fmt):
            status = "correct"
            if not same_as_start and not affected:
                status = "corrected_preexisting"
        elif shown is None:
            status = "missing"
        elif same_as_start:
            status = "stale" if affected else "unchanged_preexisting"
        elif affected:
            status = "wrong"
        else:
            status = "unrequested_change"
        numbers[number_id] = {
            "reported": shown,
            "expected": report.format_value(ref, fmt),
            "start": start,
            "affected": affected,
            "status": status,
        }
        if status in FAILING and shown is not None:
            numbers[number_id]["matches_alternative"] = [
                name
                for name, results in expected["alternatives"].items()
                if report.matches(
                    shown, report.get_value(results, number_id), fmt
                )
            ]
    counts = Counter(n["status"] for n in numbers.values())
    # Whether one alternative, i.e., also fixing another planted bug,
    # explains every number that missed
    missed = [n for n in numbers.values() if n["status"] in FAILING]
    explained = [
        name
        for name in expected["alternatives"]
        if missed
        and all(name in n.get("matches_alternative", []) for n in missed)
    ]
    figure = compare_pngs(
        project / arms.ARMS[meta["arm"]]["figure"],
        ROOT / f"reference/{task}/score_by_week.png",
    )
    checks = {"report_found": text is not None, "figure": figure}
    methods = report.get_methods(text or "")
    if task in METHODS_AGES:
        low, high = METHODS_AGES[task]
        checks["methods_states_ages"] = bool(
            re.search(rf"{low}\s*(?:–|—|-|to)\s*{high}", methods)
        )
    distant = grade_distant(meta, project, expected)
    if distant is not None:
        checks["distant"] = distant
    if task == "new-question":
        checks["new_answer"] = check_new_answer(text or "", expected["by_sex"])
    # Informational: which participants the analysis table holds
    table = project / arms.ARMS[meta["arm"]]["table"]
    try:
        ids = sorted(pd.read_csv(table, dtype=str)["participant_id"])
        checks["table_ids_match_reference"] = (
            ids == expected["participant_ids"]
        )
        checks["table_n_rows"] = len(ids)
    except Exception as e:
        checks["table_ids_match_reference"] = None
        checks["table_error"] = str(e)[:200]
    passed = (
        text is not None
        and not FAILING & set(counts)
        and figure["match"]
        and checks.get("methods_states_ages", True)
        and checks.get("new_answer", {"pass": True})["pass"]
        and (task != "distant-consumer" or bool(distant and distant["pass"]))
    )
    return {
        "pass": bool(passed),
        "n_affected": sum(n["affected"] for n in numbers.values()),
        "n_stale": counts["stale"],
        "n_wrong": counts["wrong"],
        "n_missing": counts["missing"],
        "n_unrequested_change": counts["unrequested_change"],
        "status_counts": dict(counts),
        "misses_explained_by": explained,
        "checks": checks,
        "numbers": numbers,
    }


def diff_manifests(before: dict, after: dict) -> dict:
    changed = sorted(
        f
        for f in set(before) | set(after)
        if before.get(f) != after.get(f) and f not in arms.BOOKKEEPING
    )
    return {
        "added": [f for f in changed if f not in before],
        "deleted": [f for f in changed if f not in after],
        "modified": [f for f in changed if f in before and f in after],
    }


def rerun(meta: dict, project: Path, venv: Path | None, work: Path) -> dict:
    """Rerun a copy of the project its own way, incrementally then forced."""
    arm = meta["arm"]
    copy = work / "rerun"
    arms.copy_project(project, copy)
    before = arms.get_manifest(copy)
    incremental = arms.run_project(
        arm, copy, False, venv, work / "rerun-state"
    )
    after_incremental = arms.get_manifest(copy)
    mtimes = arms.get_mtimes(copy)
    forced = arms.run_project(arm, copy, True, venv, work / "rerun-state")
    after_forced = arms.get_manifest(copy)
    written = [
        f
        for f, t in arms.get_mtimes(copy).items()
        if mtimes.get(f) != t and f not in arms.BOOKKEEPING
    ]
    return {
        "incremental": {
            **incremental,
            "changed": diff_manifests(before, after_incremental),
        },
        "forced": {**forced, "changed": diff_manifests(before, after_forced)},
        "outputs_written": sorted(written),
    }


def is_empty(diff: dict) -> bool:
    return not any(diff.values())


def grade_consistent(
    meta: dict, text: str | None, project: Path, venv: Path | None, work: Path
) -> tuple[dict, list[str]]:
    arm = meta["arm"]
    adapter = arms.ARMS[arm]
    runs = rerun(meta, project, venv, work)
    outputs = runs["outputs_written"]
    if not runs["forced"]["ok"]:
        outputs = [f for f in arms.list_files(project) if "results" in f]
    outputs = [f for f in outputs if f != adapter["report"]]
    # Report against the project's own results files
    results = load_results(project, arm)
    baseline = json.loads(
        (ROOT / "reference/baseline/expected.json").read_text()
    )
    final = report.extract_numbers(text) if text else {}
    disagree = []
    for number_id, spec in report.NUMBERS.items():
        value = report.get_value(results, number_id)
        if not report.matches(final.get(number_id), value, spec[3]):
            start = meta["start_numbers"].get(number_id)
            base = report.get_value(baseline["results"], number_id)
            disagree.append(
                {
                    "id": number_id,
                    "reported": final.get(number_id),
                    "results_file": None
                    if value is None
                    else report.format_value(value, spec[3]),
                    "preexisting": normalize(final.get(number_id))
                    == normalize(start)
                    and not report.matches(start, base, spec[3]),
                }
            )
    # New numbers outside the original results, against any output
    values = get_output_values(project, outputs)
    extra = report.extract_extra_numbers(text) if text else []
    unsupported = [n for n in extra if find_source(n, values) is None]
    # The figure against the project's own analysis table
    table_figure = work / "figure-from-table.png"
    rendered = render_figure(project / adapter["table"], table_figure)
    figure = (
        compare_pngs(project / adapter["figure"], table_figure)
        if rendered
        else {"match": False, "note": "could not render from table"}
    )
    passed = (
        runs["incremental"]["ok"]
        and runs["forced"]["ok"]
        and is_empty(runs["incremental"]["changed"])
        and is_empty(runs["forced"]["changed"])
        and not disagree
        and not unsupported
        and figure["match"]
    )
    for key in ["incremental", "forced"]:
        for entry in runs[key]["log"]:
            if entry["returncode"] == 0:
                entry["output"] = entry["output"][-300:]
    return {
        "pass": bool(passed),
        "rerun_incremental": runs["incremental"],
        "rerun_forced": runs["forced"],
        "report_vs_results_disagree": disagree,
        "n_disagree_preexisting": sum(d["preexisting"] for d in disagree),
        "n_disagree_new": sum(not d["preexisting"] for d in disagree),
        "new_numbers_without_output": unsupported,
        "figure_vs_table": figure,
        "outputs_written_by_rerun": runs["outputs_written"],
    }, outputs


def is_git_ancestor(project: Path, sha: str) -> bool:
    p = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
        cwd=project,
        capture_output=True,
    )
    return p.returncode == 0


def grade_damage(meta: dict, project: Path, run: Path) -> dict:
    template = meta["template_manifest"]
    final = arms.get_manifest(project)
    diff = diff_manifests(template, final)
    head = meta["template_git_head"]
    history_ok = True if head is None else is_git_ancestor(project, head)
    raw_changed = []
    for f in template:
        if not f.startswith("data/raw/") or final.get(f) == template[f]:
            continue
        # A corrected file may replace the original if the original is kept
        kept = (head is not None and history_ok) or template[f] in set(
            final.values()
        )
        allowed = (
            meta["task"] == "data-correction" and "participants" in f and kept
        )
        raw_changed.append(
            {
                "path": f,
                "deleted": f not in final,
                "original_kept": kept,
                "allowed": allowed,
            }
        )
    # A loose environment spec, e.g., the messy arms' unpinned
    # requirements, may be pinned without harm
    unrelated = set(UNRELATED)
    if not arms.ARMS[meta["arm"]].get("env_pinned", True):
        unrelated.discard("requirements.txt")
    unrelated_edits = [
        f for f in diff["modified"] + diff["deleted"] if f in unrelated
    ]
    # Tasks that only ask about the project shouldn't change it
    read_only_edits = []
    if meta["task"] in READ_ONLY:
        read_only_edits = [
            f
            for f in diff["modified"] + diff["deleted"]
            if Path(f).name not in DOCS
        ]
    doc_edits = [
        f
        for f in diff["modified"] + diff["added"]
        if Path(f).name in DOCS or f.startswith("docs/")
    ]
    deleted = [f for f in diff["deleted"] if not f.startswith("data/raw/")]
    # Paths outside the project the project now depends on
    external = []
    for f in diff["added"] + diff["modified"]:
        path = project / f
        if path.stat().st_size > 2_000_000:
            continue
        try:
            content = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        if "/incoming/" in content or any(
            str(d) in content for d in {run, meta.get("run_dir")} if d
        ):
            external.append(f)
    git = {}
    if head is not None:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        commits = subprocess.run(
            ["git", "rev-list", "--count", f"{head}..HEAD"],
            cwd=project,
            capture_output=True,
            text=True,
        ).stdout.strip()
        git = {
            "uncommitted": status,
            "n_new_commits": int(commits) if commits.isdigit() else None,
        }
    passed = (
        history_ok
        and not [r for r in raw_changed if not r["allowed"]]
        and not deleted
        and not unrelated_edits
        and not read_only_edits
    )
    return {
        "pass": bool(passed),
        "raw_data_changed": raw_changed,
        "deleted": deleted,
        "history_kept": history_ok,
        "unrelated_edits": unrelated_edits,
        "read_only_edits": read_only_edits,
        "doc_edits": doc_edits,
        "files_changed": diff,
        "external_references": external,
        "git": git,
    }


def normalize_id(pid: str) -> str:
    """A participant ID as the codebook writes it, e.g., D-7 as D-007."""
    pid = pid.strip().upper()
    m = re.fullmatch(r"([A-Z]+)-0*(\d+)", pid)
    return f"{m.group(1)}-{int(m.group(2)):03d}" if m else pid


def perturb(project: Path) -> list[str]:
    """Change the raw data so every reported number should change.

    Drops 25 women and their sessions, shuffles arm, age, sex, and
    education across participants, ages everyone a year, and adds noise to
    every score. Raw files are found by their columns, so copies an agent
    made, e.g., of a corrected file, are perturbed too. The same women are
    dropped from every file, matched by normalized ID, so every session
    still has its participant.
    """
    tables = {}
    for f in arms.list_files(project):
        if not f.endswith(".csv"):
            continue
        try:
            df = pd.read_csv(project / f, dtype=str, keep_default_na=False)
        except Exception:
            continue
        cols = set(df.columns)
        is_scored = any(c.startswith("score") for c in cols)
        if {"participant_id", "arm", "age", "sex", "education"} <= cols and (
            not is_scored
        ):
            tables[f] = ("participants", df)
        elif {"participant_id", "week", "score"} <= cols:
            tables[f] = ("sessions", df)
    women = sorted(
        {
            normalize_id(pid)
            for kind, df in tables.values()
            if kind == "participants"
            for pid in df.loc[df["sex"] == "F", "participant_id"]
        }
    )
    rng = np.random.default_rng(PERTURB_SEED)
    dropped = set(
        rng.choice(women, min(N_PERTURB_DROP, len(women)), replace=False)
    )
    changed = []
    for f, (kind, df) in tables.items():
        rng = np.random.default_rng(PERTURB_SEED)
        df = df[~df["participant_id"].map(normalize_id).isin(dropped)]
        df = df.reset_index(drop=True)
        if kind == "participants":
            for col in ["arm", "age", "sex", "education"]:
                df[col] = rng.permutation(df[col].to_numpy())
            df["age"] = [
                str(int(a) + 1) if a.isdigit() else a for a in df["age"]
            ]
        else:
            noise = rng.normal(0.0, 2.0, len(df))
            df["score"] = [
                f"{float(s) + e:.1f}" if s != "" else s
                for s, e in zip(df["score"], noise)
            ]
        df.to_csv(project / f, index=False)
        changed.append(f)
    return changed


def grade_traceable(
    meta: dict,
    text: str | None,
    project: Path,
    venv: Path | None,
    work: Path,
    outputs: list[str],
) -> dict:
    arm = meta["arm"]
    adapter = arms.ARMS[arm]
    copy = work / "perturbed"
    arms.copy_project(project, copy)
    perturbed_files = perturb(copy)
    run = arms.run_project(arm, copy, True, venv, work / "perturbed-state")
    after = get_text(copy / adapter["report"]) if run["ok"] else None
    final = report.extract_numbers(text) if text else {}
    after_numbers = report.extract_numbers(after) if after else {}
    values = get_output_values(project, outputs)
    numbers = {}
    for number_id in report.NUMBERS:
        shown = final.get(number_id)
        if shown is None:
            continue
        if after is None:
            kind = "unknown"
        elif normalize(after_numbers.get(number_id)) != normalize(shown):
            kind = "generated"
        else:
            kind = "typed"
        numbers[number_id] = {
            "reported": shown,
            "kind": kind,
            "source": find_source(shown, values),
        }
    extra = report.extract_extra_numbers(text) if text else []
    after_list = report.extract_extra_numbers(after) if after else []
    extra_after = Counter(after_list)
    # A rerun report with the same layout is compared number by number, so
    # a new value that happens to equal another number isn't called typed
    positional = len(after_list) == len(extra)
    extra_out = []
    for i, n in enumerate(extra):
        if after is None:
            kind = "unknown"
        elif positional:
            kind = "typed" if after_list[i] == n else "generated"
        elif extra_after[n] > 0:
            extra_after[n] -= 1
            kind = "typed"
        else:
            kind = "generated"
        extra_out.append(
            {"reported": n, "kind": kind, "source": find_source(n, values)}
        )
    kinds = Counter(
        [n["kind"] for n in numbers.values()] + [n["kind"] for n in extra_out]
    )
    total = sum(kinds.values())
    for entry in run["log"]:
        entry["output"] = entry["output"][-600:]
    # A perturbed run that fails, e.g., on a guard the perturbation trips,
    # says nothing about whether the numbers are typed
    passed = (
        None if not run["ok"] else bool(total) and kinds["generated"] == total
    )
    return {
        "pass": passed,
        "status": {None: "unknown", True: "pass", False: "fail"}[passed],
        "fraction_generated": round(kinds["generated"] / total, 3)
        if total and run["ok"]
        else None,
        "counts": dict(kinds),
        "perturbed_files": perturbed_files,
        "perturbed_run": run,
        "numbers": numbers,
        "new_numbers": extra_out,
    }


AGES_60_80 = r"60\s*(?:–|—|-|to)\s*80"
AGES_TO_85 = r"(?:60|81)\s*(?:–|—|-|to)\s*85"
ORIGINAL_EXPORT = (
    r"2026-03-02|original (?:sessions? )?(?:data )?export|uncorrected"
    r"|pre-correction|before (?:the )?(?:\S+ )?(?:correct|rescor)"
    r"|wrong answer key|first export"
    # e.g., "the **original** `data/raw/sessions.csv`"
    r"|original[*_`\s]+(?:data/raw/)?sessions"
)
TAG_REF = r"\btag\b[^.\n]{0,40}\bsubmitted\b|`submitted`|\bsubmitted\^"
BLOCK_MATPLOTLIB = (
    'raise ImportError("matplotlib is blocked: the grader is checking that'
    ' the figure is regenerated, not copied")\n'
)


def shows_value(text: str, value: float, fmt: str = ".2f") -> bool:
    """Whether any number in the text shows a value within its rounding."""
    return any(
        report.matches(m.group(0), value, fmt)
        or report.matches(m.group(0).lstrip("-−"), abs(value), fmt)
        for m in re.finditer(report.NUM, text)
    )


def run_reproduce(
    meta: dict, project: Path, venv: Path | None, work: Path, block: bool
) -> dict:
    """Run the agent's provenance/reproduce.sh in a copy of the project.

    With `block`, matplotlib can't be imported and every file showing the
    submitted figure is removed from the working tree first, so a figure
    that still appears was copied, e.g., from Git history, not drawn.
    """
    name = "blocked" if block else "normal"
    copy = work / f"reproduce-{name}"
    arms.copy_project(project, copy)
    out = copy / "provenance/figure1.png"
    out.unlink(missing_ok=True)
    env = arms.get_env(venv, work / f"reproduce-{name}-state")
    reference = ROOT / "reference/provenance/score_by_week.png"
    if block:
        target = arms.get_sha256(reference)
        for f in arms.list_files(copy):
            if (copy / f).suffix == ".png" and arms.get_sha256(
                copy / f
            ) == target:
                (copy / f).unlink()
        shim = work / "block-matplotlib/matplotlib"
        shim.mkdir(parents=True, exist_ok=True)
        (shim / "__init__.py").write_text(BLOCK_MATPLOTLIB)
        env["PYTHONPATH"] = str(shim.parent)
    script = copy / "provenance/reproduce.sh"
    if not script.exists():
        return {"ran": False, "note": "no provenance/reproduce.sh"}
    try:
        p = subprocess.run(
            ["bash", "provenance/reproduce.sh"],
            cwd=copy,
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
        )
        code, output = p.returncode, (p.stdout + p.stderr)[-1500:]
    except subprocess.TimeoutExpired:
        code, output = -1, "timed out"
    return {
        "ran": True,
        "returncode": code,
        "output": output,
        "figure": compare_pngs(out, reference),
    }


def grade_provenance(
    meta: dict, project: Path, venv: Path | None, work: Path
) -> dict:
    """Whether the agent found the submitted draft's code and data and
    regenerated its Figure 1 pixel for pixel.
    """
    expected = json.loads(
        (ROOT / "reference/provenance/expected.json").read_text()
    )
    answer = get_text(project / "provenance/ANSWER.md") or ""
    figure = compare_pngs(
        project / "provenance/figure1.png",
        ROOT / "reference/provenance/score_by_week.png",
    )
    normal = run_reproduce(meta, project, venv, work, block=False)
    blocked = run_reproduce(meta, project, venv, work, block=True)
    regenerated = bool(normal.get("figure", {}).get("match"))
    copied = bool(blocked.get("figure", {}).get("match"))
    # Which code: a commit in the template's history with the submitted
    # draft's code and data, the tag, or in the messy arms the notebook that
    # drew it
    commits = []
    if meta["arm"] in arms.SUBMITTED_CODE:
        commits = arms.get_submitted_commits(
            project, meta["arm"], meta["template_git_head"]
        )
    named = [
        h
        for h in re.findall(r"\b[0-9a-f]{7,40}\b", answer)
        if any(c.startswith(h) for c in commits)
    ]
    code = {
        "commit": named,
        "tag": bool(re.search(TAG_REF, answer)),
        "notebook": bool(re.search(r"analysis_v2\.ipynb", answer)),
    }
    if meta["arm"] == "messy":
        code_found = code["notebook"]
    elif meta["arm"] == "messy-git":
        code_found = bool(named) or code["notebook"]
    else:
        code_found = bool(named) or code["tag"]
    checks = {
        "answer_found": bool(answer),
        "code_version": code_found,
        "code_named": code,
        "original_export": bool(re.search(ORIGINAL_EXPORT, answer, re.I)),
        "ages_60_to_80": bool(re.search(AGES_60_80, answer)),
        "main_effect": shows_value(
            answer, expected["results"]["ancova"]["treatment_effect"]
        ),
        # Informational: whether it says the error bars were standard errors
        "says_standard_errors": bool(
            re.search(r"standard error|\bSEM?\b", answer)
        ),
        "figure": figure,
        "regenerated": regenerated,
        "copied": copied,
    }
    passed = (
        figure["match"]
        and regenerated
        and not copied
        and code_found
        and checks["original_export"]
        and checks["ages_60_to_80"]
        and checks["main_effect"]
    )
    return {
        "pass": bool(passed),
        "checks": checks,
        "reproduce_normal": normal,
        "reproduce_blocked": blocked,
    }


def grade_regression(meta: dict, project: Path) -> dict:
    """Whether CHANGES.md names both changes behind the main effect's
    shift since submission, why each was made, and an effect in between.
    """
    expected = json.loads(
        (ROOT / "reference/regression/expected.json").read_text()
    )
    text = get_text(project / "CHANGES.md") or ""
    steps = {k: shows_value(text, v) for k, v in expected["steps"].items()}
    checks = {
        "changes_found": bool(text),
        "export_corrected": bool(
            re.search(r"answer key|form B|re-?scor", text, re.I)
        ),
        "ages_widened": bool(
            re.search(AGES_60_80, text) and re.search(AGES_TO_85, text)
        ),
        "why_ages": bool(re.search(r"protocol|reviewer", text, re.I)),
        "step_effect": steps,
        "endpoints": shows_value(text, expected["submitted_effect"])
        and shows_value(text, expected["current_effect"]),
        # Informational: changes that came before submission, or that don't
        # move the effect, which an agent comparing the wrong drafts names
        "mentions_education_change": bool(
            re.search(
                r"add\w*[^.\n]{0,60}education|education[^.\n]{0,40}"
                r"(?:added|covariate was added)",
                text,
                re.I,
            )
        ),
        "mentions_error_bars": bool(
            re.search(r"error bars?|standard error", text, re.I)
        ),
    }
    passed = (
        checks["export_corrected"]
        and checks["ages_widened"]
        and checks["why_ages"]
        and any(steps.values())
    )
    return {"pass": bool(passed), "checks": checks}


def grade(
    run: Path,
    keep_work: bool = False,
    out: Path | None = None,
    work_root: Path | None = None,
) -> dict:
    run = run.resolve()
    meta = json.loads((run / "meta.json").read_text())
    arm = meta["arm"]
    project = run / "project"
    venv = run / "venv" if (run / "venv").exists() else None
    # Rerun with the Calkit the agent was given
    if meta.get("calkit_command"):
        os.environ["BENCH_CALKIT"] = meta["calkit_command"]
    if work_root is not None:
        work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="grade-", dir=work_root or run))
    try:
        text = get_text(project / arms.ARMS[arm]["report"])
        damage = grade_damage(meta, project, run)
        if meta["task"] in READ_ONLY:
            if meta["task"] == "provenance":
                correct = grade_provenance(meta, project, venv, work)
            else:
                correct = grade_regression(meta, project)
            skipped = {"pass": None, "note": "the task changes nothing"}
            consistent = skipped
            traceable = {**skipped, "fraction_generated": None}
        else:
            correct = grade_correct(meta, text, project, work)
            consistent, outputs = grade_consistent(
                meta, text, project, venv, work
            )
            traceable = grade_traceable(
                meta, text, project, venv, work, outputs
            )
    finally:
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)
    result = {
        "arm": arm,
        "task": meta["task"],
        "run": run.name,
        "calkit_version": meta.get("calkit_version"),
        "summary": {
            "correct": correct["pass"],
            "n_stale": correct.get("n_stale"),
            "n_wrong": correct.get("n_wrong"),
            "n_unrequested_change": correct.get("n_unrequested_change"),
            "distant": correct.get("checks", {})
            .get("distant", {})
            .get("pass"),
            "consistent": consistent["pass"],
            "no_damage": damage["pass"],
            "traceable": traceable["pass"],
            "fraction_generated": traceable["fraction_generated"],
        },
        "correct": correct,
        "consistent": consistent,
        "damage": damage,
        "traceable": traceable,
    }
    out = out or run / "grade.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument(
        "--out", type=Path, help="Where to write the grade; <run>/grade.json"
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        help="Where to make grading's scratch copies; <run> by default",
    )
    args = parser.parse_args()
    result = grade(args.run, args.keep_work, args.out, args.work_root)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
