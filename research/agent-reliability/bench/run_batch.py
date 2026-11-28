"""Run a batch of agent trials and archive each into runs/<batch>/<run>/.

Reads batches/<batch>.csv (arm, task, rep, model), unpacks the templates and
snapshots Calkit at the given commit into a scratch folder outside the repo
(AGENT_RELIABILITY_SCRATCH, or a temporary one), so agents can't read the
reference answers, and runs each trial there as its own headless Claude Code
session in the run's project: only project settings (so no user plugins,
CLAUDE.md, or memories), auto permission mode, and, for the Calkit arm only,
the agent plugin from the snapshot. Grading is separate
(bench/regrade.py), so a grader fix doesn't rerun agents.

The batch's archive has manifest.csv, a copy of the manifest, and each
run's has prompt.txt, env.sh, meta.json (with the batch, rep,
model, `claude --version`, and Calkit commit), transcript.jsonl (stream-json),
agent-stderr.txt, agent-seconds.txt, and project.tgz, the project as the
agent left it, without environments or local caches.

Usage: python bench/run_batch.py <batch> --templates FILE --calkit-rev REV
    [--jobs N]
"""

import argparse
import csv
import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import archive
import arms
import new_run

ROOT = arms.ROOT
FILES = [
    "prompt.txt",
    "env.sh",
    "meta.json",
    "transcript.jsonl",
    "agent-stderr.txt",
    "agent-seconds.txt",
]


def get_trial_env() -> dict[str, str]:
    """This process's environment without anything that points an agent at
    this repo: PATH entries and other variables naming it, e.g., the
    harness's venv the pipeline runs this in, and a parent Claude Code
    session's variables, which would make a trial a child of that session,
    sharing its scratchpad.
    """
    repo = str(arms.CALKIT_REPO)
    keep = {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"}
    env = {
        k: v
        for k, v in os.environ.items()
        if repo not in v
        and (
            k in keep
            or k.startswith("CLAUDE_CODE_USE_")
            or not (k.startswith("CLAUDE") or k == "AI_AGENT")
        )
    }
    env["PATH"] = os.pathsep.join(
        p for p in os.environ["PATH"].split(os.pathsep) if repo not in p
    )
    return env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch")
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--calkit-rev", required=True)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()

    def run_trial(row: dict) -> str:
        arm, task, model = row["arm"], row["task"], row["model"]
        name = f"{arm}__{task}__{row['rep']}"
        run = new_run.create_run(
            arm,
            task,
            name,
            scratch / "runs",
            extra_meta={
                "batch": args.batch,
                "rep": row["rep"],
                "model": model,
                "claude_version": claude_version,
                "calkit_rev": calkit_rev,
            },
        )
        plugin = []
        if arm == "calkit":
            plugin = ["--plugin-dir", str(scratch / "calkit" / "plugin")]
        claude = [
            "claude",
            "-p",
            (run / "prompt.txt").read_text(),
            "--setting-sources",
            "project",
            "--permission-mode",
            "auto",
            "--model",
            model,
            *plugin,
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        start = time.time()
        with (
            open(run / "transcript.jsonl", "w") as stdout,
            open(run / "agent-stderr.txt", "w") as stderr,
        ):
            p = subprocess.run(
                ["bash", "-c", 'source ../env.sh && exec "$@"', "--", *claude],
                cwd=run / "project",
                env=get_trial_env(),
                stdout=stdout,
                stderr=stderr,
            )
        if p.returncode != 0:
            with open(run / "agent-stderr.txt", "a") as f:
                f.write(f"agent exited {p.returncode}\n")
        (run / "agent-seconds.txt").write_text(
            f"{round(time.time() - start)}\n"
        )
        dest = out / run.name
        dest.mkdir(parents=True)
        for name in FILES:
            shutil.copy2(run / name, dest / name)
        archive.pack(
            run / "project", dest / "project.tgz", skip=archive.skip_run_path
        )
        shutil.rmtree(run)
        return run.name

    manifest = ROOT / "batches" / f"{args.batch}.csv"
    with open(manifest) as f:
        rows = [r for r in csv.DictReader(f) if r.get("arm")]
    # The archive starts with the manifest it ran from, so a batch not yet
    # filled in still has an output
    out = ROOT / "runs" / args.batch
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    shutil.copy2(manifest, out / "manifest.csv")
    if not rows:
        print(f"batches/{args.batch}.csv lists no trials")
        return
    for row in rows:
        if not new_run.applies(row["arm"], row["task"]):
            raise SystemExit(f"{row['task']} doesn't apply to {row['arm']}")
    scratch = Path(
        tempfile.mkdtemp(
            prefix=f"{args.batch}-",
            dir=os.environ.get("AGENT_RELIABILITY_SCRATCH"),
        )
    ).resolve()
    # Agents mustn't be able to find the repo, which holds the answers
    if scratch.is_relative_to(arms.CALKIT_REPO):
        raise SystemExit(f"{scratch} is inside the repo")
    try:
        archive.unpack(args.templates.resolve(), scratch / "templates")
        os.environ["BENCH_TEMPLATES"] = str(scratch / "templates")
        os.environ["BENCH_CALKIT"] = arms.snapshot_calkit(
            args.calkit_rev, scratch / "calkit"
        )
        calkit_rev = subprocess.run(
            ["git", "rev-parse", "--verify", f"{args.calkit_rev}^{{commit}}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        claude_version = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, check=True
        ).stdout.strip()
        with ThreadPoolExecutor(args.jobs) as pool:
            for name in pool.map(run_trial, rows):
                print(name)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
