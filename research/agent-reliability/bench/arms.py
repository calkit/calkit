"""Per-arm adapters: where each arm keeps its outputs and how it runs.

Grading is the same for every arm; this module is the only place that
knows an arm's layout or its own way of running.
"""

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The Calkit repo this benchmark lives in, at research/agent-reliability
CALKIT_REPO = ROOT.parents[1]
# What a Calkit user's agent is told to run; BENCH_CALKIT overrides it,
# e.g., with a snapshot from build/snapshot_calkit.sh
DEFAULT_CALKIT = f"uv run --project {CALKIT_REPO} calkit"
# Who commits: the builder in the templates' history, the agent in a trial
BUILDER = ("Research Builder", "builder@example.org")
AGENT = ("Trial Agent", "agent@example.org")
ARMS: dict[str, dict] = {
    "none": {
        "report": "report.md",
        "results": {
            "ancova": "results/model_ancova.json",
            "change": "results/model_change.json",
        },
        "figure": "figures/score_by_week.png",
        "table": "data/merged_final.csv",
    },
    "make": {
        "report": "results/report.md",
        "results": {
            "ancova": "results/model-ancova.json",
            "change": "results/model-change.json",
        },
        "figure": "results/score_by_week.png",
        "table": "data/analysis.csv",
    },
}
ARMS["calkit"] = dict(ARMS["make"])
# The arms built from the research history (build/build_history.py)
MESSY = {
    "report": "paper/draft.md",
    "results": {
        "ancova": "results/model_ancova.json",
        "change": "results/model_change.json",
    },
    "figure": "figures/fig1_FINAL_revised.png",
    "table": "data/merged_final.csv",
    # How its researcher reruns the current analysis; the README is out of
    # date and says nothing runnable
    "recipe": [
        "python prepare_data.py",
        "python fit_model.py",
        "NOTEBOOK analysis_v2_final.ipynb",
    ],
    "env_pinned": False,
}
ARMS["messy"] = {**MESSY, "git": False}
ARMS["messy-git"] = {**MESSY, "git": True}
for _arm in ["none", "make", "calkit"]:
    ARMS[_arm]["git"] = _arm != "none"
    ARMS[_arm]["env_pinned"] = True
# Where the history arms type the main effect a second time
DISTANT = "talks/GSA2026_abstract.md"
HISTORY_ARMS = ["messy", "messy-git", "make", "calkit"]
# Where each Git history arm keeps Figure 1 and the code behind it
SUBMITTED_FIGURES = {
    "messy-git": "figures/fig1_FINAL.png",
    "make": "results/score_by_week.png",
    "calkit": "results/score_by_week.png",
}
SUBMITTED_CODE = {
    "messy-git": ["utils.py", "prepare_data.py", "analysis_v2.ipynb"],
    "make": ["scripts", "Makefile"],
    "calkit": ["scripts", "pyproject.toml"],
}
# Never part of a project's content: VCS internals, caches, environments
SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".ipynb_checkpoints",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
}
SKIP_PATHS = {".dvc/cache", ".dvc/tmp", ".calkit/local"}
SKIP_FILES = {".DS_Store"}
# Rewritten by every run even when nothing changes, e.g., timestamps
BOOKKEEPING = {".calkit/stage-runs.json"}


def get_templates_dir() -> Path:
    """Where the built templates are, unpacked from the build's archive."""
    return Path(os.environ.get("BENCH_TEMPLATES", ROOT / "templates"))


def get_calkit_command() -> str:
    return os.environ.get("BENCH_CALKIT") or DEFAULT_CALKIT


def snapshot_calkit(rev: str, dest: Path) -> str:
    """Snapshot Calkit at a commit into dest, returning its command."""
    p = subprocess.run(
        ["bash", str(ROOT / "build/snapshot_calkit.sh"), rev, str(dest)],
        capture_output=True,
        text=True,
        check=True,
    )
    return p.stdout.strip().splitlines()[-1]


def get_git_identity_env(identity: tuple[str, str]) -> dict[str, str]:
    name, email = identity
    return {
        f"GIT_{role}_{key}": value
        for role in ["AUTHOR", "COMMITTER"]
        for key, value in [("NAME", name), ("EMAIL", email)]
    }


def get_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def list_files(project: Path) -> list[str]:
    """Project-relative paths of the project's content files."""
    out = []
    for dirpath, dirnames, filenames in os.walk(project):
        rel_dir = Path(dirpath).relative_to(project)
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIRS
            and (rel_dir / d).as_posix() not in SKIP_PATHS
        ]
        for name in filenames:
            if name in SKIP_FILES:
                continue
            out.append((rel_dir / name).as_posix())
    return sorted(out)


def get_manifest(project: Path) -> dict[str, str]:
    return {f: get_sha256(project / f) for f in list_files(project)}


def get_mtimes(project: Path) -> dict[str, int]:
    return {f: (project / f).stat().st_mtime_ns for f in list_files(project)}


def copy_project(src: Path, dest: Path) -> None:
    """Copy a project with its history and timestamps, but no environment."""
    shutil.copytree(
        src,
        dest,
        symlinks=True,
        ignore=shutil.ignore_patterns(".venv", "__pycache__"),
    )


def get_env(venv: Path | None, scratch: Path) -> dict[str, str]:
    """The environment projects run in: the run's venv first on PATH."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONPATH"}
    }
    if venv is not None:
        env["PATH"] = f"{venv / 'bin'}{os.pathsep}{env['PATH']}"
    # A Calkit wrapper must be on PATH for stages' own calkit commands
    calkit = shlex.split(get_calkit_command())[0]
    if os.path.isfile(calkit):
        env["PATH"] = f"{Path(calkit).parent}{os.pathsep}{env['PATH']}"
    # Keep Jupyter and IPython state out of the real home directory
    for name in ["JUPYTER_DATA_DIR", "JUPYTER_RUNTIME_DIR", "IPYTHONDIR"]:
        env[name] = str(scratch / name.lower())
    env["JUPYTER_CONFIG_DIR"] = str(scratch / "jupyter_config_dir")
    env["MPLCONFIGDIR"] = str(scratch / "mplconfig")
    return env


def get_readme_commands(project: Path) -> list[str]:
    """Shell commands from the README's code blocks, then its notebooks.

    Package installs are skipped, since the run's environment has the
    packages already.
    """
    readme = project / "README.md"
    if not readme.exists():
        return []
    text = readme.read_text()
    commands = []
    for block in re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.S):
        block = block.replace("\\\n", " ")
        for line in block.splitlines():
            line = line.strip()
            line = line.removeprefix("$ ")
            if not line or line.startswith("#"):
                continue
            if re.search(
                r"pip install|-m venv|^source |conda |uv venv|"
                r"^jupyter (notebook|lab)\b",
                line,
            ):
                continue
            commands.append(line)
    # Notebooks the README says to run that no command already runs
    run_by_commands = " ".join(commands)
    for notebook in dict.fromkeys(re.findall(r"[\w./-]+\.ipynb", text)):
        if notebook in run_by_commands or not (project / notebook).exists():
            continue
        commands.append(f"NOTEBOOK {notebook}")
    return commands


def get_run_lines(arm: str, project: Path) -> list[str]:
    """How a plain-folder arm runs: its README's commands, or else, in the
    messy arms, a run script or Makefile an agent added, or else the
    researcher's own recipe.
    """
    lines = get_readme_commands(project)
    if arm == "none" or any(
        not line.startswith("NOTEBOOK ") for line in lines
    ):
        return lines
    for script in ["run_all.sh", "run.sh", "run_analysis.sh"]:
        if (project / script).exists():
            return [f"bash {script}"]
    if (project / "Makefile").exists():
        return ["MAKE"]
    return list(ARMS[arm]["recipe"])


def run_project(
    arm: str,
    project: Path,
    force: bool,
    venv: Path | None,
    scratch: Path,
    timeout: int = 900,
) -> dict:
    """Run the project its own way; `force` reruns even up-to-date steps.

    The none arm has no notion of up to date, so it always runs everything.
    """
    scratch.mkdir(parents=True, exist_ok=True)
    env = get_env(venv, scratch)
    if arm == "calkit":
        calkit = shlex.split(get_calkit_command())
        commands = [calkit + ["run"] + (["--force"] if force else [])]
    elif arm == "make":
        commands = [["make"] + (["-B"] if force else [])]
    else:
        commands = []
        for line in get_run_lines(arm, project):
            if line.startswith("MAKE"):
                commands.append(["make"] + (["-B"] if force else []))
                continue
            if line.startswith("NOTEBOOK "):
                notebook = line.split(" ", 1)[1]
                out_dir = scratch / "executed-notebooks"
                commands.append(
                    [
                        "jupyter",
                        "nbconvert",
                        "--to",
                        "notebook",
                        "--execute",
                        "--output-dir",
                        str(out_dir),
                        notebook,
                    ]
                )
            else:
                commands.append(["bash", "-c", line])
    log = []
    start = time.time()
    ok = bool(commands)
    for cmd in commands:
        try:
            p = subprocess.run(
                cmd,
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            code = p.returncode
            output = (p.stdout + p.stderr)[-3000:]
        except subprocess.TimeoutExpired:
            code, output = -1, "timed out"
        log.append({"command": cmd, "returncode": code, "output": output})
        if code != 0:
            ok = False
            break
    return {"ok": ok, "seconds": round(time.time() - start, 1), "log": log}


def get_submit_ref(project: Path, rev: str = "HEAD") -> str:
    """The commit the submitted draft came from, in rev's history: the
    `submitted` tag, or the commit that added the submitted copy.
    """
    tags = subprocess.run(
        ["git", "tag", "--merged", rev],
        cwd=project,
        capture_output=True,
        text=True,
    ).stdout.split()
    if "submitted" in tags:
        return "submitted"
    return subprocess.run(
        [
            "git",
            "log",
            "--format=%H",
            "--diff-filter=A",
            rev,
            "--",
            "paper/draft_submitted.md",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()[-1]


def get_submitted_commits(project: Path, arm: str, rev: str) -> list[str]:
    """The commits in rev's history whose code and raw data are the
    submitted draft's, any of which answers which version produced it.
    """
    paths = SUBMITTED_CODE[arm] + ["data/raw"]

    def get_tree(commit: str) -> str:
        return subprocess.run(
            ["git", "ls-tree", "-r", commit, "--", *paths],
            cwd=project,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    target = get_tree(get_submit_ref(project, rev))
    commits = subprocess.run(
        ["git", "rev-list", rev],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [c for c in commits if get_tree(c) == target]
