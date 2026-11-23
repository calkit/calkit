"""Check whether TeX Live environments can give Matplotlib its TeX and fonts.

Matplotlib's ``text.usetex`` runs ``latex``, ``dvipng``, and ``kpsewhich``
from PATH, so a Python script gets them by running with a TeX Live
environment's programs first on PATH, as composing it into the script's
environment would. Each check runs Matplotlib in a new interpreter, with
other TeX installations taken off PATH, and a new config directory unless
it says otherwise:

- ``usetex``: a figure with usetex labels, saved as PNG and PDF, with the
  ``mpl-tex`` environment's TeX, and where the fonts embedded in the PDF
  come from. Seconds are for building Matplotlib's font list, which a new
  config directory does first, the median of rendering with a new one
  holding only that list, and rendering again from its cache.
- ``tex_cache``: the same PNG with the ``mpl-fonts`` environment's TeX,
  which has none of the packages usetex needs, nor dvipng, once with the
  config directory the usetex render used, and once with a new one.
  Matplotlib keys its TeX cache by the source alone, not by the TeX that
  made it.
- ``missing_tex_font``: a usetex figure in Helvetica, whose LaTeX package
  isn't in the environment.
- ``missing_font``: a figure without usetex whose font family isn't on the
  machine.
- ``env_fonts``: whether Matplotlib finds the ``mpl-fonts`` environment's
  fonts, through fontconfig, with a new config directory and with one whose
  font list was built without the environment.
- ``composed``: the usetex figure through ``calkit xenv`` in the
  ``calkit-tex`` environment, which has ``mpl-tex`` composed into it with
  ``with``: where ``latex`` came from, whether Matplotlib got a config
  directory of its own, and how many fonts fontconfig found from the
  system and from the store.

Writes the results and the machine to the given path.
"""

import argparse
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from importlib.metadata import version

import calkit
from calkit.environments import texlive

parser = argparse.ArgumentParser()
parser.add_argument("--repeats", type=int, default=3)
parser.add_argument("--out", required=True)
args = parser.parse_args()
FIGURE = r"""
import json, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
plt.rcParams.update(json.loads(sys.argv[1]))
fig, ax = plt.subplots(figsize=(3, 2))
ax.plot([0, 1], [0, 1])
ax.set_xlabel(sys.argv[2])
for ext in sys.argv[3:]:
    fig.savefig("fig." + ext, bbox_inches="tight")
family = plt.rcParams["font.family"]
print(font_manager.findfont(font_manager.FontProperties(family=family)))
"""
FIND_FONTS = r"""
import sys
from matplotlib import font_manager
for name in sys.argv[1:]:
    try:
        print(font_manager.findfont(name, fallback_to_default=False))
    except ValueError:
        print("")
"""
TEX_LABEL = r"$\alpha < \beta$, 50\% of $x_1$, $\frac{\partial u}{\partial t}$"
COMPOSED = r"""
import json, os, shutil, subprocess, sys, tempfile
os.chdir(tempfile.mkdtemp())
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update(json.loads(sys.argv[1]))
fig, ax = plt.subplots()
ax.set_xlabel(sys.argv[2])
fig.savefig("fig.png")
fonts = []
if shutil.which("fc-list"):
    fonts = subprocess.run(
        ["fc-list"], capture_output=True, text=True
    ).stdout.splitlines()
print(json.dumps({
    "latex": shutil.which("latex"),
    "mplconfigdir": os.environ.get("MPLCONFIGDIR", ""),
    "n_fonts": len(fonts),
    "n_store_fonts": sum(sys.argv[3] in f for f in fonts),
}))
"""
USETEX = {"text.usetex": True, "font.family": "serif"}
TEX_PROGRAMS = ["latex", "dvipng", "kpsewhich"]


def run_python(
    code: str,
    cli_args: list,
    env_vars: dict,
    config_dir: str | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess:
    env_vars = dict(env_vars)
    env_vars["MPLCONFIGDIR"] = config_dir or tempfile.mkdtemp()
    return subprocess.run(
        [sys.executable, "-c", code, *cli_args],
        cwd=cwd or tempfile.mkdtemp(),
        env=env_vars,
        capture_output=True,
        text=True,
    )


def get_path_without_tex(path: str) -> str:
    return os.pathsep.join(
        d
        for d in path.split(os.pathsep)
        if not any(shutil.which(p, path=d) for p in TEX_PROGRAMS)
    )


def get_env_vars(env_name: str) -> dict:
    view_dir = texlive.check(env_name, environments[env_name])
    env_vars = texlive.get_run_env_vars(view_dir)
    env_vars["PATH"] = (
        os.path.join(view_dir, "bin", texlive.get_platform())
        + os.pathsep
        + system_env_vars["PATH"]
    )
    return env_vars


def copy_font_list() -> str:
    config_dir = tempfile.mkdtemp()
    for fname in os.listdir(font_list_dir):
        if fname.startswith("fontlist"):
            shutil.copy(os.path.join(font_list_dir, fname), config_dir)
    return config_dir


environments = calkit.load_calkit_info()["environments"]
store_dir = texlive.get_store_dir()
system_env_vars = dict(os.environ)
system_env_vars["PATH"] = get_path_without_tex(os.environ["PATH"])
tex_env_vars = get_env_vars("mpl-tex")
other_env_vars = get_env_vars("mpl-fonts")
with open(texlive.get_lock_fpath("mpl-tex", environments["mpl-tex"])) as f:
    tex_lock = json.load(f)
results: dict = {"store_dir": store_dir}
# Matplotlib builds a font list in a new config directory before anything
# else, so that's timed apart and copied into the ones used for rendering
font_list_dir = tempfile.mkdtemp()
started = time.perf_counter()
run_python(FIND_FONTS, ["DejaVu Sans"], tex_env_vars, font_list_dir)
font_list_seconds = time.perf_counter() - started
# Matplotlib's usetex with only the environment's TeX
fig_args = [json.dumps(USETEX), TEX_LABEL, "png"]
config_dir = copy_font_list()
cwd = tempfile.mkdtemp()
out = run_python(FIGURE, fig_args + ["pdf"], tex_env_vars, config_dir, cwd)
samples = []
for _ in range(args.repeats):
    started = time.perf_counter()
    run_python(FIGURE, fig_args, tex_env_vars, copy_font_list())
    samples.append(time.perf_counter() - started)
started = time.perf_counter()
run_python(FIGURE, fig_args, tex_env_vars, config_dir)
cached_seconds = time.perf_counter() - started
packages = environments["mpl-tex"]["packages"]
sizes_kb = {n: tex_lock["packages"][n]["size"] / 1e3 for n in packages}
largest = max(sizes_kb, key=lambda n: sizes_kb[n])
results["usetex"] = {
    "ok": out.returncode == 0,
    "error": out.stderr[-2000:] if out.returncode else None,
    "packages": packages,
    "package_list": ", ".join(packages),
    "download_kb": {n: round(kb) for n, kb in sizes_kb.items()},
    "largest": {"name": largest, "mb": sizes_kb[largest] / 1e3},
    "rest_kb": sum(kb for n, kb in sizes_kb.items() if n != largest),
    "seconds": {
        "font_list": font_list_seconds,
        "render": statistics.median(samples),
        "cached": cached_seconds,
    },
    "samples": samples,
}
# Fonts in the PDF and where kpsewhich, as Matplotlib's PDF backend does,
# finds them
with open(os.path.join(cwd, "fig.pdf"), "rb") as f:
    pdf_fonts = sorted(
        set(re.findall(rb"/BaseFont /([A-Za-z0-9+-]+)", f.read()))
    )
font_fpaths = {}
for font in pdf_fonts:
    name = font.decode().split("+")[-1].lower() + ".pfb"
    font_fpaths[name] = subprocess.run(
        ["kpsewhich", name],
        env=tex_env_vars,
        capture_output=True,
        text=True,
    ).stdout.strip()
results["usetex"]["pdf_fonts"] = font_fpaths
results["usetex"]["pdf_fonts_from_store"] = all(
    os.path.abspath(p).startswith(store_dir) for p in font_fpaths.values()
)
# The same PNG with a TeX lacking every package usetex needs, and dvipng,
# with the config directory that rendered it and with a new one
results["tex_cache"] = {
    "other_tex_shared_config_ok": run_python(
        FIGURE, fig_args, other_env_vars, config_dir
    ).returncode
    == 0,
    "other_tex_new_config_ok": run_python(
        FIGURE, fig_args, other_env_vars, copy_font_list()
    ).returncode
    == 0,
}
# A usetex font whose package isn't in the environment
out = run_python(
    FIGURE,
    [
        json.dumps(
            USETEX
            | {"font.family": "sans-serif", "font.sans-serif": ["Helvetica"]}
        ),
        TEX_LABEL,
        "png",
    ],
    tex_env_vars,
    copy_font_list(),
)
missing = re.search(r"File `([^']+)' not found", out.stdout + out.stderr)
results["missing_tex_font"] = {
    "ok": out.returncode == 0,
    "missing_file": missing.group(1) if missing else None,
}
# A font family missing from the machine, without usetex
family = "Not A Real Font"
out = run_python(
    FIGURE,
    [json.dumps({"font.family": family}), "Some text", "png"],
    system_env_vars,
    copy_font_list(),
)
results["missing_font"] = {
    "family": family,
    "ok": out.returncode == 0,
    "used": os.path.basename(out.stdout.strip()),
    "warned": "not found" in out.stderr,
}
# Fonts from a TeX Live environment, without usetex, found by a new font
# list and by one built without the environment
names = ["Arimo", "CMU Serif"]
built_before = tempfile.mkdtemp()
run_python(FIND_FONTS, names, system_env_vars, built_before)
results["env_fonts"] = {"fontconfig": shutil.which("fc-list") is not None}
for label, config_dir in [
    ("new_config", None),
    ("built_before", built_before),
]:
    found = run_python(FIND_FONTS, names, other_env_vars, config_dir).stdout
    results["env_fonts"][label] = {
        name: os.path.abspath(p).startswith(store_dir) if p else False
        for name, p in zip(names, found.splitlines())
    }
# The usetex figure through Calkit itself, in an environment with mpl-tex
# composed into it
out = subprocess.run(
    [
        "calkit",
        "xenv",
        "-n",
        "calkit-tex",
        "--",
        "python",
        "-c",
        COMPOSED,
        json.dumps(USETEX),
        TEX_LABEL,
        store_dir,
    ],
    capture_output=True,
    text=True,
)
composed = (
    json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout else {}
)
results["composed"] = {
    "ok": out.returncode == 0,
    "error": out.stderr[-2000:] if out.returncode else None,
    "latex_from_store": os.path.abspath(
        composed.get("latex") or ""
    ).startswith(store_dir),
    "own_config_dir": os.path.abspath(
        composed.get("mplconfigdir") or os.sep
    ).startswith(os.path.join(calkit.get_user_home(), ".calkit", "composed")),
    "system_fonts": composed.get("n_fonts", 0)
    - composed.get("n_store_fonts", 0),
    "store_fonts": composed.get("n_store_fonts", 0),
}
results["release"] = tex_lock["release"]
results["machine"] = {
    "platform": platform.platform(),
    "machine": platform.machine(),
    "texlive_platform": texlive.get_platform(),
    "python": sys.version.split()[0],
    "matplotlib": version("matplotlib"),
    "calkit": version("calkit-python"),
}
os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
with open(args.out, "w") as f:
    json.dump(results, f, indent=2)
    f.write("\n")
