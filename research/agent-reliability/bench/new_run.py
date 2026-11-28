"""Make a fresh working copy of one arm's template for one trial.

Creates runs/<arm>__<task>__<stamp>/ with:

- project/: a copy of templates/<arm>, with its Git history and timestamps;
  for stale-clone, a fresh clone of templates/stale/<arm> instead
- venv/: a new Python environment with the pinned packages, at the
  versions the harness's uv.lock gives them (every arm but calkit)
- incoming/: files the task's prompt names (data-correction and add-site)
- prompt.txt: the arm's preamble and the task's prompt
- env.sh: source it before starting the agent, from project/; it also
  gives the agent's commits the benchmark's identity, not this machine's
- meta.json: what the grader needs to know about the starting state

Templates come from BENCH_TEMPLATES, unpacked from the
build stage's archive.

Usage: python bench/new_run.py <arm> <task> [--name NAME] [--runs-dir DIR]
"""

import argparse
import datetime
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import arms
import report

ROOT = arms.ROOT
TASKS = [
    "filter",
    "fix-merge",
    "new-question",
    "data-correction",
    "provenance",
    "regression",
    "undo",
    "stale-clone",
    "distant-consumer",
    "add-site",
]
# Tasks that need the research history, and the Git arms for stale-clone
HISTORY_TASKS = {"provenance", "regression", "undo", "distant-consumer"}
GIT_HISTORY_ARMS = ["messy-git", "make", "make-hint", "calkit", "calkit-hint"]
# A time every file in a fresh clone gets, as if checked out at once
CLONE_TIME = 1_795_000_000


def applies(arm: str, task: str) -> bool:
    """Whether a task makes sense in an arm."""
    if task == "stale-clone":
        return arm in GIT_HISTORY_ARMS
    if task in HISTORY_TASKS:
        return arm in arms.HISTORY_ARMS
    return True


def clone_stale(arm: str, project: Path) -> None:
    """A fresh clone of the stale template, as a collaborator would get it.

    Every file gets the same time, as a checkout gives them, so timestamps
    say nothing about what's out of date. DVC-tracked outputs come along,
    as a pull from the project's remote would bring them.
    """
    src = arms.get_templates_dir() / "stale" / arms.get_template_name(arm)
    subprocess.run(
        ["git", "clone", "-q", str(src), str(project)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "remote",
            "set-url",
            "origin",
            "https://github.com/example-lab/cognitive-training.git",
        ],
        cwd=project,
        check=True,
    )
    if (src / ".dvc" / "cache").exists():
        shutil.copytree(src / ".dvc" / "cache", project / ".dvc" / "cache")
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=src, capture_output=True, text=True
        ).stdout.split()
        for f in arms.list_files(src):
            if f not in tracked and not (project / f).exists():
                (project / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src / f, project / f)
    for f in arms.list_files(project):
        os.utime(project / f, (CLONE_TIME, CLONE_TIME))


def get_versions() -> dict[str, str]:
    out = {}
    for line in (ROOT / "versions.env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            out[key] = value.strip('"')
    return out


def create_venv(path: Path) -> None:
    versions = get_versions()
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    # Every package at the version the harness's lock gives it
    constraints = path.parent / f"{path.name}-constraints.txt"
    subprocess.run(
        [
            "uv",
            "export",
            "-q",
            "--frozen",
            "--no-hashes",
            "--no-emit-project",
            "--project",
            str(ROOT),
            "-o",
            str(constraints),
        ],
        check=True,
        env=env,
    )
    subprocess.run(
        [
            "uv",
            "venv",
            "-q",
            "--python-preference",
            "only-managed",
            "--python",
            versions["PYTHON_VERSION"],
            str(path),
        ],
        check=True,
        env=env,
    )
    packages = (
        versions["PACKAGES"].split() + versions["NOTEBOOK_PACKAGES"].split()
    )
    subprocess.run(
        ["uv", "pip", "install", "-q", "-c", str(constraints), *packages],
        check=True,
        env={**env, "VIRTUAL_ENV": str(path)},
    )
    constraints.unlink()


def get_git_head(project: Path) -> str | None:
    if not (project / ".git").exists():
        return None
    p = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        capture_output=True,
        text=True,
    )
    return p.stdout.strip() or None


def create_run(
    arm: str,
    task: str,
    name: str | None,
    runs_dir: Path,
    extra_meta: dict | None = None,
) -> Path:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run = runs_dir.resolve() / (name or f"{arm}__{task}__{stamp}")
    if run.exists():
        raise SystemExit(f"{run} exists")
    run.mkdir(parents=True)
    project = run / "project"
    if not applies(arm, task):
        raise SystemExit(f"{task} doesn't apply to the {arm} arm")
    if task == "stale-clone":
        clone_stale(arm, project)
    else:
        template = arms.get_templates_dir() / arms.get_template_name(arm)
        arms.copy_project(template, project)
    base = arms.get_base(arm)
    venv = run / "venv"
    if base != "calkit":
        create_venv(venv)
    fields_extra = {}
    if task == "regression":
        expected = json.loads(
            (ROOT / "reference/regression/expected.json").read_text()
        )
        fields_extra = {
            "submitted_effect": f"{expected['submitted_effect']:.2f}",
            "current_effect": f"{expected['current_effect']:.2f}",
        }
    incoming = run / "incoming"
    if task == "data-correction":
        incoming.mkdir()
        shutil.copy2(
            ROOT / "incoming/participants_2026-05-20_corrected.csv",
            incoming,
        )
    if task == "add-site":
        shutil.copytree(ROOT / "incoming/site-e", incoming)
    calkit = arms.get_calkit_command()
    fields = {
        "project": project,
        "venv": venv,
        "incoming": incoming,
        "calkit": calkit,
        **fields_extra,
    }
    # An intervention arm's agent is told what its base arm's is
    preamble = (ROOT / "preambles" / f"{base}.txt").read_text().strip()
    prompt = (ROOT / "tasks" / f"{task}.txt").read_text().strip()
    (run / "prompt.txt").write_text(
        preamble.format(**fields) + "\n\n" + prompt.format(**fields) + "\n"
    )
    scratch = run / "agent-state"
    lines = ["unset VIRTUAL_ENV CONDA_PREFIX PYTHONPATH"]
    if base != "calkit":
        lines.append(f'export PATH="{venv}/bin:$PATH"')
    elif os.path.isfile(shlex.split(calkit)[0]):
        lines.append(
            f'export PATH="{Path(shlex.split(calkit)[0]).parent}:$PATH"'
        )
    for key, value in arms.get_env(None, scratch).items():
        if key.startswith(("JUPYTER", "IPYTHON", "MPL")):
            lines.append(f'export {key}="{value}"')
    for key, value in arms.get_git_identity_env(arms.AGENT).items():
        lines.append(f'export {key}="{value}"')
    (run / "env.sh").write_text("\n".join(lines) + "\n")
    adapter = arms.ARMS[arm]
    report_text = (project / adapter["report"]).read_text()
    calkit_version = None
    if base == "calkit":
        calkit_version = subprocess.run(
            [*shlex.split(calkit), "--version"],
            capture_output=True,
            text=True,
            env=arms.get_env(None, scratch),
        ).stdout.strip()
    meta = {
        "arm": arm,
        "task": task,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run),
        "calkit_command": calkit if base == "calkit" else None,
        "intervention": arms.get_intervention(arm),
        "calkit_version": calkit_version,
        "template_git_head": get_git_head(project),
        "template_manifest": arms.get_manifest(project),
        "start_numbers": report.extract_numbers(report_text),
        "start_extra_numbers": report.extract_extra_numbers(report_text),
        "start_distant": report.extract_distant_numbers(
            (project / arms.DISTANT).read_text()
        )
        if (project / arms.DISTANT).exists()
        else None,
        **(extra_meta or {}),
    }
    (run / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm", choices=sorted(arms.ARMS))
    parser.add_argument("task", choices=TASKS)
    parser.add_argument("--name")
    parser.add_argument(
        "--runs-dir",
        type=Path,
        required=True,
        help="Where to put the run, outside this repo, to keep the agent"
        " away from the reference answers",
    )
    args = parser.parse_args()
    run = create_run(args.arm, args.task, args.name, args.runs_dir)
    print(run)


if __name__ == "__main__":
    main()
