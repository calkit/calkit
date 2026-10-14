"""Time 'calkit status' and an up-to-date 'calkit run' with DVC's YAML parsed
by ruamel.yaml, with its C loader from ruamel.yaml.clib, and by PyYAML's
libyaml, which Calkit patches DVC to use.

The project is generated rather than taken from a real one, so anyone can
rerun this, sized like a large project's pipeline: a chain of stages, each
making files the next reads. It's run once before timing, so every timed
command finds it up to date.

Each command runs in a fresh interpreter, which imports Calkit, so DVC is
patched, then puts ruamel.yaml's parser back for the clib case. Each also
adds up the time spent in that parser and how often it's called, so how much
of the command is parsing is measured rather than inferred. The cases take
turns so a busy machine slows each alike, both wall and CPU time are
recorded, and both parsers must print the same status.

Writes the medians, every sample, and the machine to the given path.
"""

import argparse
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from importlib.metadata import version

parser = argparse.ArgumentParser()
parser.add_argument("--stages", type=int, default=150)
parser.add_argument("--files-per-stage", type=int, default=24)
parser.add_argument("--repeats", type=int, default=10)
parser.add_argument("--out", required=True)
args = parser.parse_args()

# Run in each fresh interpreter: the parser to use, then the command
SCRIPT = """
import atexit
import json
import sys
import time

import dvc.utils.serialize
import dvc.utils.serialize._yaml
import dvc.utils.strictyaml

modules = [dvc.utils.serialize._yaml, dvc.utils.serialize, dvc.utils.strictyaml]
original = dvc.utils.serialize._yaml.parse_yaml

import calkit.dvc.core

patched = dvc.utils.serialize._yaml.parse_yaml
assert patched is not original, "Calkit didn't patch DVC"
use = {"clib": original, "libyaml": patched}[sys.argv[1]]
spent = {"s": 0.0, "calls": 0}


def timed(*args, **kwargs):
    t = time.perf_counter()
    try:
        return use(*args, **kwargs)
    finally:
        spent["s"] += time.perf_counter() - t
        spent["calls"] += 1


for module in modules:
    module.parse_yaml = timed
atexit.register(lambda: print(json.dumps(spent), file=sys.stderr))
sys.argv = ["calkit", *sys.argv[2:]]
from calkit.cli import run

run()
"""
COMMANDS = {"status": ["status", "--json"], "run": ["run"]}
PARSERS = ["clib", "libyaml"]


def calkit(wdir: str, parser: str, command: list[str]) -> dict:
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    t = time.perf_counter()
    out = subprocess.run(
        [sys.executable, "-c", SCRIPT, parser, *command],
        cwd=wdir,
        capture_output=True,
        text=True,
    )
    wall = time.perf_counter() - t
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    if out.returncode != 0:
        raise RuntimeError(out.stderr)
    spent = json.loads(out.stderr.strip().splitlines()[-1])
    return dict(
        wall_s=wall,
        cpu_s=(after.ru_utime - before.ru_utime)
        + (after.ru_stime - before.ru_stime),
        parse_s=spent["s"],
        parse_calls=spent["calls"],
        stdout=out.stdout,
    )


with tempfile.TemporaryDirectory() as wdir:
    # Each stage writes its files from the previous stage's
    n = args.files_per_stage
    with open(os.path.join(wdir, "make.py"), "w") as f:
        f.write(
            "import sys\n"
            "i = int(sys.argv[1])\n"
            f"for j in range({n}):\n"
            "    with open(f'results/{i:03d}/{j:02d}.txt', 'w') as f:\n"
            "        f.write(f'{i} {j}\\n')\n"
        )
    os.makedirs(os.path.join(wdir, "data"))
    for j in range(n):
        with open(os.path.join(wdir, "data", f"{j:02d}.txt"), "w") as f:
            f.write(f"{j}\n")
    lines = ["name: generated", "pipeline:", "  stages:"]
    for i in range(args.stages):
        os.makedirs(os.path.join(wdir, "results", f"{i:03d}"))
        before = "data" if i == 0 else f"results/{i - 1:03d}"
        lines += [
            f"    stage-{i:03d}:",
            "      kind: shell-command",
            "      environment: _system",
            f"      command: python make.py {i}",
            "      inputs:",
            "        - make.py",
            *[f"        - {before}/{j:02d}.txt" for j in range(n)],
            "      outputs:",
            *[f"        - results/{i:03d}/{j:02d}.txt" for j in range(n)],
        ]
    with open(os.path.join(wdir, "calkit.yaml"), "w") as f:
        f.write("\n".join(lines) + "\n")
    for cmd in [
        ["git", "init", "-q"],
        ["git", "add", "."],
        ["git", "commit", "-qm", "Generate"],
    ]:
        subprocess.run(cmd, cwd=wdir, check=True, capture_output=True)
    calkit(wdir, "clib", ["run"])
    sizes = {
        name: os.path.getsize(os.path.join(wdir, name))
        for name in ["dvc.yaml", "dvc.lock"]
    }
    load_before = os.getloadavg()
    samples: dict = {c: {p: [] for p in PARSERS} for c in COMMANDS}
    statuses: dict = {p: set() for p in PARSERS}
    for _ in range(args.repeats):
        for command, command_args in COMMANDS.items():
            for p in PARSERS:
                sample = calkit(wdir, p, command_args)
                stdout = sample.pop("stdout")
                if command == "status":
                    statuses[p].add(stdout)
                samples[command][p].append(sample)
    load_after = os.getloadavg()
if len(statuses["clib"] | statuses["libyaml"]) != 1:
    raise RuntimeError("The parsers' statuses differed")
medians = {
    command: {
        p: {
            key: statistics.median(s[key] for s in by_parser[p])
            for key in ["wall_s", "cpu_s", "parse_s", "parse_calls"]
        }
        for p in PARSERS
    }
    for command, by_parser in samples.items()
}
result = {
    "project": {
        "stages": args.stages,
        "paths": args.stages * args.files_per_stage * 2 + args.stages,
        "kb": {
            name.replace(".", "_"): size / 1000 for name, size in sizes.items()
        },
    },
    "medians": medians,
    "saved_s": {
        command: m["clib"]["wall_s"] - m["libyaml"]["wall_s"]
        for command, m in medians.items()
    },
    "saved_fraction": {
        command: 1 - m["libyaml"]["wall_s"] / m["clib"]["wall_s"]
        for command, m in medians.items()
    },
    "samples": samples,
    "repeats": args.repeats,
    "packages": {
        name: version(name)
        for name in ["dvc", "ruamel.yaml", "ruamel.yaml.clib", "pyyaml"]
    },
    "machine": {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "cpus": os.cpu_count(),
        # How busy it was, since that still nudges the timings
        "load_average": [load_before, load_after],
    },
}
os.makedirs(os.path.dirname(args.out), exist_ok=True)
with open(args.out, "w") as f:
    json.dump(result, f, indent=2)
    f.write("\n")
