"""Tally every graded batch into results/agent-reliability.json and .md.

For each batch, arm, and task, and for each arm over all batches: passes of
each check, counting a check that doesn't apply or couldn't be decided as
neither pass nor fail, and the mean cost, minutes, and turns per trial,
from each run's transcript. Also:

- noticing: whether a trial whose task isn't fix-merge mentions site D's
  dropped participants (IDs without zero padding, so the merge loses the
  site), unprompted, in the agent's final message, by a strict,
  case-sensitive pattern, with a one-sided Fisher exact test of the messy
  arms against the others without the checking guidance; and whether an
  add-site trial's final message mentions site E's re-entered records
- interventions: noticing per arm in the batches the checking-guidance
  arms ran in, with Fisher exact tests of calkit-hint against calkit
  (one-sided: more) and against make-hint (two-sided)
- isolation: tool inputs that mention the benchmark itself (this folder,
  its reference answers, the audit studies) or any absolute path outside
  the run's own folder and the Calkit snapshot it was given
- templates: which files of each run's starting template differ from the
  templates the build stage makes now

Usage: python bench/summarize.py <batch> [<batch> ...]
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import arms
from scipy.stats import fisher_exact

ROOT = arms.ROOT
RESULTS = ROOT.parent / "results"
CHECKS = ("correct", "consistent", "damage", "traceable", "distant")
ARMS = [
    "none",
    "messy",
    "messy-git",
    "make",
    "make-hint",
    "calkit",
    "calkit-hint",
]
MESSY = {"messy", "messy-git"}
INTERVENTION_ARMS = ["messy-git", "make", "make-hint", "calkit", "calkit-hint"]
NOTICE = re.compile(r"site D|leading zero|zero-pad|\bD-\d+")
# Site E's planted problem: four participants entered twice
NOTICE_SITE_E = re.compile(
    r"[Dd]uplicat|[Rr]e-?enter(?:ed|s)?\b|[Rr]e-?entr(?:y|ies)\b"
    r"|entered (?:twice|again)|entered_on|(?:latest|most recent) (?:entry|record)"
)
BENCHMARK = re.compile(
    r"agent-reliability/(?!envs/calkit-)|/reference/|audit-compare"
    r"|audit-private|" + re.escape(str(arms.CALKIT_REPO)) + r"(?![\w-])"
)
ABS_PATH = re.compile(
    r"(?<![\w.~-])/(?:Users|private|var|tmp|home|Volumes)(?:/[^\s\"'`;|&<>()\\]*)?"
)


def read_transcript(path: Path, allowed: list[str]) -> dict:
    """Cost, turns, final message, and paths outside the run, from a
    stream-json transcript.
    """
    out: dict = {
        "cost_usd": None,
        "turns": None,
        "final_message": None,
        "benchmark_access": [],
        "outside_paths": set(),
        # Where the checking guidance would reach the agent, if given
        "loaded_conventions": False,
        "named_readme": False,
    }
    for line in path.read_text().splitlines():
        e = json.loads(line)
        if e.get("type") == "assistant":
            for c in e["message"]["content"]:
                if c.get("type") != "tool_use":
                    continue
                text = json.dumps(c["input"])
                out["benchmark_access"] += BENCHMARK.findall(text)
                if c.get("name") == "Skill" and "conventions" in text:
                    out["loaded_conventions"] = True
                if re.search(r"(?<![\w/])README\.md", text):
                    out["named_readme"] = True
                for m in ABS_PATH.finditer(text):
                    p = m.group(0).rstrip(".,:")
                    if not any(
                        p == a or p.startswith(a + "/") for a in allowed
                    ):
                        out["outside_paths"].add(p)
        elif e.get("type") == "result":
            out["cost_usd"] = e.get("total_cost_usd")
            out["turns"] = e.get("num_turns")
            out["final_message"] = e.get("result")
    out["benchmark_access"] = sorted(set(out["benchmark_access"]))
    out["outside_paths"] = sorted(out["outside_paths"])
    return out


def read_run(batch: str, run: Path, templates: dict) -> dict:
    meta = json.loads((run / "meta.json").read_text())
    grade = json.loads(
        (ROOT / "grades" / batch / f"{run.name}.json").read_text()
    )
    source = meta.get("run_dir")
    if (run / "import.json").exists():
        source = json.loads((run / "import.json").read_text())["source"]
    allowed = [source]
    if meta.get("calkit_command"):
        allowed.append(str(Path(meta["calkit_command"]).parent.parent))
    t = read_transcript(run / "transcript.jsonl", allowed)
    noticed = None
    if meta["task"] != "fix-merge" and t["final_message"] is not None:
        noticed = sorted(set(NOTICE.findall(t["final_message"])))
    noticed_e = None
    if meta["task"] == "add-site" and t["final_message"] is not None:
        noticed_e = sorted(set(NOTICE_SITE_E.findall(t["final_message"])))
    key = ("stale/" if meta["task"] == "stale-clone" else "") + (
        arms.get_template_name(meta["arm"])
    )
    current = templates[key]
    start = meta["template_manifest"]
    row = {
        "batch": batch,
        "run": run.name,
        "arm": meta["arm"],
        "task": meta["task"],
        **{
            c: grade["summary"]["no_damage" if c == "damage" else c]
            for c in CHECKS
        },
        "n_stale": grade["summary"].get("n_stale"),
        "n_wrong": grade["summary"].get("n_wrong"),
        # Other planted bugs the agent also fixed, which explain its misses
        "also_fixed": grade["correct"].get("misses_explained_by") or [],
        "cost_usd": t["cost_usd"],
        "minutes": int((run / "agent-seconds.txt").read_text()) / 60,
        "turns": t["turns"],
        "noticed_site_d": None if noticed is None else bool(noticed),
        "notice_matches": noticed,
        "noticed_site_e": None if noticed_e is None else bool(noticed_e),
        "notice_site_e_matches": noticed_e,
        "site_e": grade["summary"].get("site_e"),
        "benchmark_access": t["benchmark_access"],
        "outside_paths": t["outside_paths"],
        "loaded_conventions": t["loaded_conventions"],
        "named_readme": t["named_readme"],
        "template": {
            "no_git": meta["template_git_head"] is None,
            "same_git_head": meta["template_git_head"] == current["git_head"],
            "files_differing": sorted(
                f
                for f in set(start) | set(current["files"])
                if start.get(f) != current["files"].get(f)
            ),
        },
    }
    return row


def tally(rows: list[dict]) -> dict:
    """Passes per check and mean cost, minutes, and turns."""

    def mean(key: str) -> float | None:
        values = [r[key] for r in rows if r[key] is not None]
        return round(sum(values) / len(values), 3) if values else None

    checks = {}
    for c in CHECKS:
        decided = [r[c] for r in rows if r[c] is not None]
        checks[c] = {"pass": sum(decided), "n": len(decided)}
    return {
        "n": len(rows),
        "n_all_pass": sum(
            all(r[c] is not False for c in CHECKS if c != "distant")
            for r in rows
        ),
        **checks,
        "n_incorrect_from_also_fixing": sum(
            r["correct"] is False and bool(r["also_fixed"]) for r in rows
        ),
        "mean_cost_usd": mean("cost_usd"),
        "total_cost_usd": round(sum(r["cost_usd"] or 0 for r in rows), 2),
        "mean_minutes": mean("minutes"),
        "mean_turns": mean("turns"),
    }


def count_noticed(rows: list[dict], key: str = "noticed_site_d") -> dict:
    decided = [r for r in rows if r[key] is not None]
    return {"noticed": sum(r[key] for r in decided), "n": len(decided)}


def test_noticed(a: dict, b: dict, alternative: str) -> float:
    """Fisher exact p of arm a noticing more than (or other than) arm b."""
    _, p = fisher_exact(
        [
            [a["noticed"], a["n"] - a["noticed"]],
            [b["noticed"], b["n"] - b["noticed"]],
        ],
        alternative=alternative,
    )
    return float(p)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batches", nargs="+")
    args = parser.parse_args()
    templates = json.loads((ROOT / "templates.json").read_text())["templates"]
    rows = []
    for batch in args.batches:
        for run in sorted((ROOT / "runs" / batch).iterdir()):
            if (run / "meta.json").exists():
                rows.append(read_run(batch, run, templates))
    by_batch: dict = {}
    for batch in args.batches:
        b = [r for r in rows if r["batch"] == batch]
        by_batch[batch] = {"all": tally(b)}
        for arm in ARMS:
            a = [r for r in b if r["arm"] == arm]
            if not a:
                continue
            tasks = sorted({r["task"] for r in a})
            by_batch[batch][arm] = {
                "all": tally(a),
                "tasks": {
                    t: tally([r for r in a if r["task"] == t]) for t in tasks
                },
            }
    by_arm = {}
    for arm in ARMS:
        a = [r for r in rows if r["arm"] == arm]
        if a:
            tasks = sorted({r["task"] for r in a})
            by_arm[arm] = {
                "all": tally(a),
                "tasks": {
                    t: tally([r for r in a if r["task"] == t]) for t in tasks
                },
            }
    # Noticing site D, unprompted
    noticing: dict = {"pattern": NOTICE.pattern, "arms": {}}
    for arm in ARMS:
        a = [r for r in rows if r["arm"] == arm]
        if not a:
            continue
        tasks = sorted({r["task"] for r in a} - {"fix-merge"})
        noticing["arms"][arm] = {
            **count_noticed(a),
            "tasks": {
                t: count_noticed([r for r in a if r["task"] == t])
                for t in tasks
            },
            "site_e": count_noticed(a, "noticed_site_e"),
        }
    # The messy arms against the others the guidance wasn't given to
    messy = count_noticed([r for r in rows if r["arm"] in MESSY])
    rest = count_noticed(
        [r for r in rows if r["arm"] not in MESSY | set(arms.BASES)]
    )
    noticing.update(
        messy=messy,
        rest=rest,
        fisher_p_one_sided=test_noticed(messy, rest, "greater"),
        site_e_pattern=NOTICE_SITE_E.pattern,
    )
    noticing["runs"] = {
        r["run"]: r["notice_matches"] for r in rows if r["noticed_site_d"]
    }
    noticing["runs_site_e"] = {
        r["run"]: r["notice_site_e_matches"]
        for r in rows
        if r["noticed_site_e"]
    }
    # The checking guidance, within the batches its arms ran in, so every
    # arm compared took the same tasks
    batches = sorted({r["batch"] for r in rows if r["arm"] in arms.BASES})
    compared = [r for r in rows if r["batch"] in batches]
    guidance_arms: dict[str, dict] = {}
    for arm in INTERVENTION_ARMS:
        a = [r for r in compared if r["arm"] == arm]
        add_site = [r for r in a if r["task"] == "add-site"]
        guidance_arms[arm] = {
            "n": len(a),
            "n_loaded_conventions": sum(r["loaded_conventions"] for r in a),
            "n_named_readme": sum(r["named_readme"] for r in a),
            "site_d": count_noticed(a),
            "site_e": count_noticed(a, "noticed_site_e"),
            "add_site_correct": {
                "pass": sum(r["correct"] is True for r in add_site),
                "n": sum(r["correct"] is not None for r in add_site),
            },
            "site_e_handling": dict(
                Counter(r["site_e"] or "unknown" for r in add_site)
            ),
        }
    tests: dict[str, dict] = {}
    for name, other, alternative in [
        ("hint_vs_calkit", "calkit", "greater"),
        ("hint_vs_make_hint", "make-hint", "two-sided"),
    ]:
        tests[name] = {"vs": other, "alternative": alternative}
        for measure in ["site_d", "site_e"]:
            tests[name][f"{measure}_p"] = test_noticed(
                guidance_arms["calkit-hint"][measure],
                guidance_arms[other][measure],
                alternative,
            )
    noticing["interventions"] = {
        "batches": batches,
        "arms": guidance_arms,
        "tests": tests,
    }
    isolation = {
        "n_benchmark_access": sum(bool(r["benchmark_access"]) for r in rows),
        "n_outside_paths": sum(bool(r["outside_paths"]) for r in rows),
        "runs": {
            r["run"]: {
                "benchmark_access": r["benchmark_access"],
                "outside_paths": r["outside_paths"],
            }
            for r in rows
            if r["benchmark_access"] or r["outside_paths"]
        },
    }
    starting: dict = {}
    for batch in args.batches:
        starting[batch] = {}
        for r in rows:
            if r["batch"] != batch:
                continue
            key = ("stale/" if r["task"] == "stale-clone" else "") + (
                arms.get_template_name(r["arm"])
            )
            starting[batch].setdefault(key, r["template"])
    summary = {
        "batches": args.batches,
        "n_runs": len(rows),
        "by_batch": by_batch,
        "arms": by_arm,
        "noticing": noticing,
        "isolation": isolation,
        "templates_vs_current": starting,
        "runs": rows,
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "agent-reliability.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    (RESULTS / "agent-reliability.md").write_text(
        format_markdown(summary) + "\n"
    )


def format_markdown(s: dict) -> str:
    def cell(t: dict, check: str) -> str:
        return f"{t[check]['pass']}/{t[check]['n']}" if t[check]["n"] else "–"

    def fmt(value: float | None, spec: str) -> str:
        return "–" if value is None else format(value, spec)

    lines = [
        "# Agent reliability",
        "",
        "Passes out of trials where the check applies; – where none do."
        " All four: trials that failed none of correct, consistent, damage,"
        " and traceable, counting those that don't apply as not failed."
        " Also fixed: trials that failed correct only because the agent also"
        " fixed a planted bug the task didn't name, e.g., site D's IDs.",
        "",
        "## By arm, all batches",
        "",
        "| Arm | Trials | All four | Correct | Consistent | Damage"
        " | Traceable | Distant | Also fixed | $/trial | Min | Turns |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
        " ---: | ---: |",
    ]
    for arm, a in s["arms"].items():
        t = a["all"]
        lines.append(
            f"| {arm} | {t['n']} | {t['n_all_pass']} | "
            + " | ".join(cell(t, c) for c in CHECKS)
            + f" | {t['n_incorrect_from_also_fixing']}"
            + f" | {fmt(t['mean_cost_usd'], '.2f')}"
            f" | {fmt(t['mean_minutes'], '.1f')}"
            f" | {fmt(t['mean_turns'], '.0f')} |"
        )
    lines += [
        "",
        "## By batch, arm, and task",
        "",
        "| Batch | Arm | Task | Trials | Correct | Consistent | Damage"
        " | Traceable | Distant | Also fixed | $/trial | Min | Turns |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
        " ---: | ---: | ---: |",
    ]
    for batch, b in s["by_batch"].items():
        for arm, a in b.items():
            if arm == "all":
                continue
            for task, t in a["tasks"].items():
                lines.append(
                    f"| {batch} | {arm} | {task} | {t['n']} | "
                    + " | ".join(cell(t, c) for c in CHECKS)
                    + f" | {t['n_incorrect_from_also_fixing']}"
                    + f" | {fmt(t['mean_cost_usd'], '.2f')}"
                    f" | {fmt(t['mean_minutes'], '.1f')}"
                    f" | {fmt(t['mean_turns'], '.0f')} |"
                )
    n = s["noticing"]
    lines += [
        "",
        "## Site D noticed unprompted",
        "",
        "Trials whose task isn't fix-merge whose final message matches"
        f" `{n['pattern']}`.",
        "",
        "| Arm | Task | Noticed |",
        "| --- | --- | ---: |",
    ]
    for arm, a in n["arms"].items():
        for task, t in a["tasks"].items():
            lines.append(f"| {arm} | {task} | {t['noticed']}/{t['n']} |")
        lines.append(f"| {arm} | all | {a['noticed']}/{a['n']} |")
    lines += [
        "",
        f"Messy arms {n['messy']['noticed']}/{n['messy']['n']}, the others"
        " without the checking guidance"
        f" {n['rest']['noticed']}/{n['rest']['n']}; one-sided Fisher exact"
        f" p = {n['fisher_p_one_sided']:.2g}.",
        "",
        "## Checking guidance",
        "",
        "In the batches the checking-guidance arms ran in"
        f" ({', '.join(n['interventions']['batches']) or 'none yet'}):"
        " site D noticed as above, and site E's re-entered records"
        " noticed in add-site trials whose final message matches"
        f" `{n['site_e_pattern']}`. Skill: trials that loaded the"
        " conventions skill, where calkit-hint's guidance is. README:"
        " trials whose tool inputs name README.md, where make-hint's is."
        " Site E handling: how the analysis table holds site E's"
        " re-entered participants.",
        "",
        "| Arm | Trials | Skill | README | Site D noticed | Site E noticed"
        " | add-site correct | Site E handling |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for arm, a in n["interventions"]["arms"].items():
        handling = ", ".join(
            f"{k} {v}" for k, v in sorted(a["site_e_handling"].items())
        )
        lines.append(
            f"| {arm} | {a['n']} | {a['n_loaded_conventions']}"
            f" | {a['n_named_readme']}"
            f" | {a['site_d']['noticed']}/{a['site_d']['n']}"
            f" | {a['site_e']['noticed']}/{a['site_e']['n']}"
            f" | {a['add_site_correct']['pass']}/{a['add_site_correct']['n']}"
            f" | {handling or '–'} |"
        )
    lines += ["", "| calkit-hint against | Test | Site D p | Site E p |"]
    lines.append("| --- | --- | ---: | ---: |")
    for test in n["interventions"]["tests"].values():
        lines.append(
            f"| {test['vs']} | Fisher exact, {test['alternative']}"
            f" | {test['site_d_p']:.2g} | {test['site_e_p']:.2g} |"
        )
    lines += [
        "",
        "## Isolation",
        "",
        f"Trials whose tool inputs mention the benchmark itself:"
        f" {s['isolation']['n_benchmark_access']}; that name any path"
        " outside their run and Calkit snapshot:"
        f" {s['isolation']['n_outside_paths']}.",
        "",
        "| Run | Benchmark | Outside paths |",
        "| --- | --- | --- |",
    ]
    for run, r in s["isolation"]["runs"].items():
        outside = ", ".join(f"`{p}`" for p in r["outside_paths"][:4])
        if len(r["outside_paths"]) > 4:
            outside += f", and {len(r['outside_paths']) - 4} more"
        bench = ", ".join(f"`{p}`" for p in r["benchmark_access"])
        lines.append(f"| {run} | {bench} | {outside} |")
    lines += [
        "",
        "## Starting templates against the current build",
        "",
        "| Batch | Template | Same Git head | Files differing |",
        "| --- | --- | --- | --- |",
    ]
    for batch, b in s["templates_vs_current"].items():
        for key, t in sorted(b.items()):
            files = ", ".join(f"`{f}`" for f in t["files_differing"][:6])
            if len(t["files_differing"]) > 6:
                files += f", and {len(t['files_differing']) - 6} more"
            head = "yes" if t["same_git_head"] else "no"
            if t["no_git"]:
                head = "no Git"
            lines.append(f"| {batch} | {key} | {head} | {files or 'none'} |")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
