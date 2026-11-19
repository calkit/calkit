"""Measure what ``calkit latex build`` adds to latexmk in a ready TeX Live
environment, and what each of the things that took from it cost.

Everything happens in a temporary Calkit home and project, so nothing on the
machine is touched or reused. A realistic article is built once, which adds
the packages it needs, and then, taking turns, each of these is run in a
fresh process several times:

- ``build_unchanged`` and ``latexmk_unchanged``: ``calkit latex build`` and
  latexmk itself, in the environment, with nothing to do.
- ``build_edited`` and ``latexmk_edited``: the same after an edit.
- ``xenv``: ``calkit xenv`` running nothing in the environment, i.e., the
  second Calkit process a build started to run latexmk before it ran
  latexmk itself.
- ``import_git``: importing ``calkit.git``, with GitPython, which a build
  did for every document before only those using Calkit's components did.
- ``pydantic_plugins``: pydantic looking for plugins, which it does before
  its first validator, i.e., in every command, since Typer validates
  options with it.

Each is the median of wall time and of CPU time, which the machine's load
moves less, but which leaves out waiting on files. Writes the results and the machine
to the given path.
"""

import argparse
import json
import os
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from importlib.metadata import version

parser = argparse.ArgumentParser()
parser.add_argument("--repeats", type=int, default=10)
parser.add_argument("--out", required=True)
args = parser.parse_args()
out_fpath = os.path.abspath(args.out)
home = tempfile.mkdtemp(prefix="calkit-latex-build-")
os.environ["CALKIT_USER_HOME"] = home
import calkit  # noqa: E402
from calkit.environments import texlive  # noqa: E402

DOC = r"""\documentclass{article}
\usepackage{amsmath}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{siunitx}
\usepackage{xcolor}
\usepackage[numbers]{natbib}
\usepackage{hyperref}
\usepackage{cleveref}
\begin{document}
\section{Introduction}\label{sec:intro}
See \cref{sec:intro} and \cite{a}. \SI{3}{\meter}, and
\begin{equation}
  \int_0^1 x^2 \, dx = \frac{1}{3}.
\end{equation}
\begin{table}[h]
  \centering
  \begin{tabular}{lr}\toprule a & 1 \\ \bottomrule\end{tabular}
  \caption{A table.}
\end{table}
\bibliographystyle{plainnat}
\bibliography{refs}
\end{document}
"""
BIB = "@article{a, author={A. Author}, title={T}, journal={J}, year={2020}}\n"


def get_child_cpu_s() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def run_timed(cmd: list[str], env: dict | None = None) -> tuple[float, float]:
    cpu_before = get_child_cpu_s()
    started = time.perf_counter()
    subprocess.run(cmd, env=env, capture_output=True, check=True)
    return time.perf_counter() - started, get_child_cpu_s() - cpu_before


def time_in_fresh_python(setup: str, timed: str) -> tuple[float, float]:
    code = (
        "import time\n"
        f"{setup}\n"
        "started = (time.perf_counter(), time.process_time())\n"
        f"{timed}\n"
        "print(time.perf_counter() - started[0])\n"
        "print(time.process_time() - started[1])\n"
    )
    out = subprocess.check_output([sys.executable, "-c", code], text=True)
    wall_s, cpu_s = out.split()
    return float(wall_s), float(cpu_s)


load_before = os.getloadavg()
project_dir = os.path.join(home, "project")
os.makedirs(os.path.join(project_dir, "paper"))
os.chdir(project_dir)
subprocess.run(["git", "init", "-q"], check=True)
calkit.save_calkit_info(
    {"name": "timing", "environments": {"tex": {"kind": "texlive"}}}
)
with open(os.path.join("paper", "main.tex"), "w") as f:
    f.write(DOC)
with open(os.path.join("paper", "refs.bib"), "w") as f:
    f.write(BIB)
build_cmd = ["calkit", "latex", "build", "-e", "tex", "paper/main.tex"]
started = time.perf_counter()
subprocess.run(build_cmd, capture_output=True, check=True)
first_build_s = time.perf_counter() - started
lock = texlive.read_lock(os.path.join(".calkit", "env-locks", "tex.json"))
assert lock is not None
view_dir = texlive.check("tex", {"kind": "texlive"})
tex_env = texlive.get_run_env_vars(view_dir)
latexmk_cmd = texlive.get_run_cmd(
    ["latexmk", "-pdf", "-cd", "-interaction=nonstopmode", "paper/main.tex"],
    tex_env,
)


def edit() -> None:
    with open(os.path.join("paper", "main.tex"), "a") as f:
        f.write(f"% edit {time.time_ns()}\n")


cases = {
    "build_unchanged": (None, lambda: run_timed(build_cmd)),
    "latexmk_unchanged": (None, lambda: run_timed(latexmk_cmd, tex_env)),
    "build_edited": (edit, lambda: run_timed(build_cmd)),
    "latexmk_edited": (edit, lambda: run_timed(latexmk_cmd, tex_env)),
    "xenv": (
        None,
        lambda: run_timed(["calkit", "xenv", "-n", "tex", "--", "true"]),
    ),
}
wall: dict[str, list[float]] = {name: [] for name in cases}
cpu: dict[str, list[float]] = {name: [] for name in cases}
imports: dict[str, list[tuple[float, float]]] = {
    "import_git": [],
    "pydantic_plugins": [],
}
for _ in range(args.repeats):
    for name, (prepare, measure) in cases.items():
        if prepare is not None:
            prepare()
        wall_s, cpu_s = measure()
        wall[name].append(wall_s)
        cpu[name].append(cpu_s)
    imports["import_git"].append(
        time_in_fresh_python("import calkit", "import calkit.git")
    )
    imports["pydantic_plugins"].append(
        time_in_fresh_python(
            "from pydantic.plugin import _loader",
            "list(_loader.get_plugins())",
        )
    )
results = {
    "seconds": {
        "first_build": first_build_s,
        "wall": {name: statistics.median(s) for name, s in wall.items()},
        "cpu": {name: statistics.median(s) for name, s in cpu.items()},
    },
    "ms": {
        "wall": {
            name: statistics.median(w for w, _ in s) * 1000
            for name, s in imports.items()
        },
        "cpu": {
            name: statistics.median(c for _, c in s) * 1000
            for name, s in imports.items()
        },
    },
    "samples": {"wall": wall, "cpu": cpu, "imports": imports},
    "packages": {"added": len(lock.get("added", []))},
    "release": lock["release"],
    "repeats": args.repeats,
    "machine": {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "texlive_platform": texlive.get_platform(),
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
        "calkit": version("calkit-python"),
        "load_before": load_before,
        "load_after": os.getloadavg(),
    },
}
os.chdir(os.path.dirname(out_fpath))
shutil.rmtree(home)
with open(out_fpath, "w") as f:
    json.dump(results, f, indent=2)
    f.write("\n")
