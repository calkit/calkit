"""Time checking whether a Docker image exists, through Docker's socket and
through its CLI.

``calkit.docker.image_exists`` asks the socket, and falls back to running
``docker image inspect``, which is how it checked before. Each is timed for
an image that's there and one that isn't, the two taking turns so a busy
machine slows each alike. Wall time is recorded, since most of either is
waiting on Docker.

Writes the medians, every sample, and the machine to the given path.
"""

import argparse
import json
import os
import platform
import statistics
import subprocess
import time

from calkit.docker import image_exists

parser = argparse.ArgumentParser()
parser.add_argument("--image", default="ghcr.io/calkit/latex:0.1.6")
parser.add_argument("--missing", default="calkit/no-such-image:0")
parser.add_argument("--repeats", type=int, default=30)
parser.add_argument("--out", required=True)
args = parser.parse_args()


def through_cli(ref: str) -> bool:
    # As image_exists did before, and still does when there's no socket
    try:
        subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", ref],
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return False
    return True


load_before = os.getloadavg()
samples: dict[str, dict[str, list[float]]] = {
    "present": {"socket": [], "cli": []},
    "missing": {"socket": [], "cli": []},
}
for _ in range(args.repeats):
    for case, ref in [("present", args.image), ("missing", args.missing)]:
        for way, check in [("socket", image_exists), ("cli", through_cli)]:
            start = time.perf_counter()
            found = check(ref)
            samples[case][way].append((time.perf_counter() - start) * 1000)
            # Both have to give the right answer for the timing to count
            assert found == (case == "present"), (way, ref)
ms = {
    case: {way: statistics.median(t) for way, t in ways.items()}
    for case, ways in samples.items()
}
result = {
    "ms": ms,
    "speedup": {
        case: ways["cli"] / ways["socket"] for case, ways in ms.items()
    },
    "samples": samples,
    "repeats": args.repeats,
    "image": args.image,
    "docker": subprocess.check_output(
        ["docker", "version", "--format", "{{.Server.Version}}"], text=True
    ).strip(),
    "machine": {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "cpus": os.cpu_count(),
        # How busy it was, since that slows both
        "load_average": [load_before, os.getloadavg()],
    },
}
os.makedirs(os.path.dirname(args.out), exist_ok=True)
with open(args.out, "w") as f:
    json.dump(result, f, indent=2)
    f.write("\n")
