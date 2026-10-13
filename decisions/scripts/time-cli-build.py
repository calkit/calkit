"""Time how long Typer takes to build Calkit's CLI, all of it and just the
command being run.

``calkit.cli.run`` narrows the app to the command its arguments name before
Typer builds it, and builds everything for ``--help``. Each case runs in a
fresh interpreter, since Typer and ``inspect`` cache some of the work, after
importing the CLI, which isn't timed. The cases take turns so a busy
machine slows each alike, and CPU time is recorded, since it's less
affected by whatever else is running.

Writes the medians, every sample, and the machine to the given path.
"""

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
from importlib.metadata import version

parser = argparse.ArgumentParser()
parser.add_argument("--repeats", type=int, default=25)
parser.add_argument("--out", required=True)
args = parser.parse_args()

# The arguments narrowed on, or None to build everything as before
CASES = {"all": None, "status": ["status"], "help": ["--help"]}
SCRIPT = """
import sys
import time

import typer.main

from calkit.cli import _only_invoked
from calkit.cli.main import app

args = {args!r}
t = time.process_time()
group = typer.main.get_command(app if args is None else _only_invoked(app, args))
ms = (time.process_time() - t) * 1000


def count(cmd):
    subs = getattr(cmd, "commands", None)
    return 1 if subs is None else sum(count(c) for c in subs.values())


print(ms, count(group))
"""


def run(case_args: list[str] | None) -> tuple[float, int]:
    out = subprocess.run(
        [sys.executable, "-c", SCRIPT.format(args=case_args)],
        capture_output=True,
        text=True,
        check=True,
    )
    ms, commands = out.stdout.split()[-2:]
    return float(ms), int(commands)


load_before = os.getloadavg()
samples: dict[str, list[float]] = {name: [] for name in CASES}
commands: dict[str, int] = {}
for _ in range(args.repeats):
    for name, case_args in CASES.items():
        ms, commands[name] = run(case_args)
        samples[name].append(ms)
cpu = {name: statistics.median(ms) for name, ms in samples.items()}
result = {
    "cpu_ms": cpu,
    "saved_ms": cpu["all"] - cpu["status"],
    "commands": commands,
    "samples": samples,
    "repeats": args.repeats,
    "packages": {name: version(name) for name in ["typer"]},
    "machine": {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "cpus": os.cpu_count(),
        # How busy it was, since that still nudges CPU time
        "load_average": [load_before, os.getloadavg()],
    },
}
os.makedirs(os.path.dirname(args.out), exist_ok=True)
with open(args.out, "w") as f:
    json.dump(result, f, indent=2)
    f.write("\n")
