"""Time how long DVC takes to parse a large dvc.lock.

The lock is generated rather than taken from a real project, so anyone can
rerun this: one stage per simulated pipeline stage, each with the deps and
outs DVC records, sized like a large project's, about 4,500 paths and
620 KB. It's the same text every time, and its hash is recorded so a
comparison can check it parsed the same file.

Parsing goes through dvc.utils.serialize.parse_yaml, which is what DVC uses
to load dvc.lock, so whether ruamel.yaml's C loader is used depends only on
what's installed in the environment this runs in.

Writes the timings, what was parsed, and the machine to the given path.
"""

import argparse
import hashlib
import json
import os
import platform
import time
from importlib.metadata import PackageNotFoundError, version

from dvc.utils.serialize import parse_yaml
from ruamel.yaml.main import CParser

parser = argparse.ArgumentParser()
parser.add_argument("--stages", type=int, default=300)
parser.add_argument("--paths-per-stage", type=int, default=15)
parser.add_argument("--repeats", type=int, default=5)
parser.add_argument("--out", required=True)
args = parser.parse_args()


def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


# One lock entry per stage, its paths split between deps and outs
lines = ["schema: '2.0'", "stages:"]
for i in range(args.stages):
    lines += [f"  stage-{i:04d}:", f"    cmd: python scripts/stage-{i}.py"]
    for kind in ["deps", "outs"]:
        lines.append(f"    {kind}:")
        for j in range(args.paths_per_stage // 2 + (kind == "outs")):
            path = f"results/stage-{i:04d}/{kind}-{j:02d}.csv"
            lines += [
                f"    - path: {path}",
                "      hash: md5",
                f"      md5: {md5(path)}",
                f"      size: {len(path) * 997}",
            ]
text = "\n".join(lines) + "\n"
# Best of several, so a busy machine slows one rather than the result
times = []
for _ in range(args.repeats):
    start = time.perf_counter()
    data = parse_yaml(text, "dvc.lock")
    times.append(time.perf_counter() - start)


def installed(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


result = {
    "lock": {
        "md5": md5(text),
        "bytes": len(text.encode()),
        "stages": len(data["stages"]),
        "paths": sum(
            len(s["deps"]) + len(s["outs"]) for s in data["stages"].values()
        ),
        # Of what was parsed, so a comparison can check both got the same
        "parsed_md5": md5(json.dumps(data, sort_keys=True)),
    },
    "c_loader": CParser is not None,
    "seconds": min(times),
    "repeats": args.repeats,
    "packages": {
        name: installed(name)
        for name in ["dvc", "ruamel.yaml", "ruamel.yaml.clib"]
    },
    "machine": {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "cpus": os.cpu_count(),
    },
}
os.makedirs(os.path.dirname(args.out), exist_ok=True)
with open(args.out, "w") as f:
    json.dump(result, f, indent=2)
    f.write("\n")
