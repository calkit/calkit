"""Measure what a TeX Live environment costs to set up and use, against
Calkit's LaTeX Docker image.

Everything happens in a temporary Calkit home, so nothing on the machine is
touched or reused:

- ``cold``: checking a new environment with only the base packages, i.e.,
  locking, downloading, unpacking, and assembling it, formats included.
- ``second_project``: checking the same environment in another project,
  which finds it already assembled.
- ``add_package``: checking it again with a package added, which installs
  that one package and assembles a new environment from the store.
- ``ready_check``: checking an environment that's ready, as every
  ``calkit run`` and ``calkit xenv`` does.
- ``compile``: building a small article with latexmk, pdfLaTeX and
  LuaLaTeX, from clean each time, in the environment and, if Docker and
  the image are here, in the image. Medians of several runs, taking turns.

Sizes are what was downloaded and what the store holds on disk, counting a
hard-linked file once. Writes the results and the machine to the given path.
"""

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from importlib.metadata import version

parser = argparse.ArgumentParser()
parser.add_argument("--repeats", type=int, default=5)
parser.add_argument("--out", required=True)
args = parser.parse_args()
out_fpath = os.path.abspath(args.out)
home = tempfile.mkdtemp(prefix="calkit-texlive-")
os.environ["CALKIT_USER_HOME"] = home
import calkit  # noqa: E402
from calkit.environments import texlive  # noqa: E402
from calkit.latex import DEFAULT_LATEX_IMAGE  # noqa: E402

DOC = r"""\documentclass{article}
\usepackage{graphicx}
\begin{document}
\section{Introduction}
Some text with math, $E = mc^2$, and
\begin{equation}
  \int_0^1 x^2 \, dx = \frac{1}{3}.
\end{equation}
\end{document}
"""


def get_disk_mb(path: str) -> float:
    seen = set()
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for fname in filenames:
            st = os.lstat(os.path.join(dirpath, fname))
            if (st.st_dev, st.st_ino) not in seen:
                seen.add((st.st_dev, st.st_ino))
                total += (
                    st.st_blocks * 512
                    if hasattr(st, "st_blocks")
                    else (st.st_size)
                )
    return total / 1e6


def check_in_project(project_dir: str, env: dict) -> tuple[float, str]:
    os.makedirs(project_dir, exist_ok=True)
    os.chdir(project_dir)
    calkit.save_calkit_info({"environments": {"tex": env}})
    started = time.perf_counter()
    view_dir = texlive.check("tex", env)
    return time.perf_counter() - started, view_dir


load_before = os.getloadavg()
results: dict = {"seconds": {}, "mb": {}}
# A new environment, from nothing
cold_s, view_dir = check_in_project(
    os.path.join(home, "p1"), {"kind": "texlive"}
)
lock = texlive.read_lock(os.path.join(".calkit", "env-locks", "tex.json"))
assert lock is not None
here = texlive.get_platform_packages(lock, texlive.get_platform())
results["seconds"]["cold"] = cold_s
results["packages"] = {"locked": len(lock["packages"]), "here": len(here)}
results["mb"]["download"] = sum(i["size"] for i in here.values()) / 1e6
results["mb"]["store"] = get_disk_mb(texlive.get_store_dir())
results["mb"]["tlpdb_cache"] = get_disk_mb(
    os.path.join(texlive.get_store_dir(), "tlpdb")
)
# The same environment in another project
results["seconds"]["second_project"], _ = check_in_project(
    os.path.join(home, "p2"), {"kind": "texlive"}
)
# A package added
store_before = results["mb"]["store"]
results["seconds"]["add_package"], view2_dir = check_in_project(
    os.path.join(home, "p3"), {"kind": "texlive", "packages": ["booktabs"]}
)
results["mb"]["store_after_add"] = get_disk_mb(texlive.get_store_dir())
results["mb"]["add_package"] = results["mb"]["store_after_add"] - store_before
# A ready environment, as every run checks it
ready = []
for _ in range(50):
    started = time.perf_counter()
    texlive.check("tex", {"kind": "texlive", "packages": ["booktabs"]})
    ready.append(time.perf_counter() - started)
results["ms"] = {"ready_check": statistics.median(ready) * 1000}
# Compiling, in the environment and in the image, taking turns
doc_dir = os.path.join(home, "doc")
os.makedirs(doc_dir)
with open(os.path.join(doc_dir, "doc.tex"), "w") as f:
    f.write(DOC)
docker = shutil.which("docker") is not None and (
    subprocess.run(
        ["docker", "image", "inspect", DEFAULT_LATEX_IMAGE],
        capture_output=True,
    ).returncode
    == 0
)
if docker:
    inspect = json.loads(
        subprocess.check_output(
            ["docker", "image", "inspect", DEFAULT_LATEX_IMAGE]
        )
    )[0]
    results["mb"]["docker_image"] = inspect["Size"] / 1e6
    results["docker_image"] = DEFAULT_LATEX_IMAGE
cases = {}
for engine in ["-pdf", "-lualatex"]:
    cases[f"texlive{engine}"] = (
        texlive.get_run_env_vars(view_dir),
        [
            "latexmk",
            engine,
            "-interaction=nonstopmode",
            "doc.tex",
        ],
    )
    if docker:
        cases[f"docker{engine}"] = (
            None,
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{doc_dir}:/work",
                "-w",
                "/work",
                DEFAULT_LATEX_IMAGE,
                "latexmk",
                engine,
                "-interaction=nonstopmode",
                "doc.tex",
            ],
        )
samples: dict[str, list[float]] = {name: [] for name in cases}
for _ in range(args.repeats):
    for name, (env_vars, cmd) in cases.items():
        for fname in os.listdir(doc_dir):
            if fname != "doc.tex":
                os.remove(os.path.join(doc_dir, fname))
        if env_vars is not None:
            cmd = [shutil.which(cmd[0], path=env_vars["PATH"])] + cmd[1:]
        started = time.perf_counter()
        subprocess.run(
            cmd, cwd=doc_dir, env=env_vars, capture_output=True, check=True
        )
        samples[name].append(time.perf_counter() - started)
results["seconds"]["compile"] = {
    name: statistics.median(s) for name, s in samples.items()
}
results["samples"] = samples
results["release"] = lock["release"]
results["repository"] = lock["repository"]
results["repeats"] = args.repeats
results["machine"] = {
    "platform": platform.platform(),
    "machine": platform.machine(),
    "texlive_platform": texlive.get_platform(),
    "cpu_count": os.cpu_count(),
    "python": sys.version.split()[0],
    "calkit": version("calkit-python"),
    "load_before": load_before,
    "load_after": os.getloadavg(),
}
os.chdir(os.path.dirname(out_fpath))
shutil.rmtree(home)
with open(out_fpath, "w") as f:
    json.dump(results, f, indent=2)
    f.write("\n")
