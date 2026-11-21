"""Time the CPU cost of importing Calkit's CLI and its models.

Each case runs in a fresh interpreter, since an import only costs anything
the first time, and the cases take turns so a busy machine slows each
alike. CPU time rather than wall time is recorded, since it's less affected
by whatever else is running.

The cases:

- ``cli``: importing the CLI, as every command does.
- ``cli_with_environments``: the same, with calkit.environments imported
  first, as the CLI did when calkit.cli.describe imported it at the top.
- ``models_deferred``: importing calkit.models, whose schemas are built
  when each model is first used.
- ``models_built``: the same, then building every model's schema, as
  defining them did before.

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

# Code before the clock starts, and code timed
CASES = {
    "cli": ("", "import calkit.cli.main"),
    "cli_with_environments": (
        "",
        "import calkit.environments\nimport calkit.cli.main",
    ),
    "models_deferred": ("import calkit, pydantic", "import calkit.models"),
    "models_built": (
        "import calkit, pydantic",
        "import calkit.models\n"
        "for model in CALKIT_MODELS():\n"
        "    model.model_rebuild(force=True)\n",
    ),
}
# Every Calkit model defined so far, each once
FIND = """
def CALKIT_MODELS():
    found, todo = set(), [pydantic.BaseModel]
    while todo:
        for sub in todo.pop().__subclasses__():
            if sub not in found:
                found.add(sub)
                todo.append(sub)
    return [m for m in found if m.__module__.startswith("calkit")]
"""


def cpu_ms(setup: str, code: str) -> float:
    script = (
        f"import time\n{setup}\n{FIND}\nt = time.process_time()\n{code}\n"
        "print((time.process_time() - t) * 1000)"
    )
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.split()[-1])


load_before = os.getloadavg()
samples: dict[str, list[float]] = {name: [] for name in CASES}
for _ in range(args.repeats):
    for name, (setup, code) in CASES.items():
        samples[name].append(cpu_ms(setup, code))
cpu = {name: statistics.median(ms) for name, ms in samples.items()}
result = {
    "cpu_ms": cpu,
    "saved_ms": {
        "environments": cpu["cli_with_environments"] - cpu["cli"],
        "models": cpu["models_built"] - cpu["models_deferred"],
    },
    "samples": samples,
    "repeats": args.repeats,
    "models": int(
        subprocess.check_output(
            [
                sys.executable,
                "-c",
                "import calkit.models, pydantic\n"
                f"{FIND}\nprint(len(CALKIT_MODELS()))",
            ],
            text=True,
        )
    ),
    "packages": {name: version(name) for name in ["pydantic", "typer"]},
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
