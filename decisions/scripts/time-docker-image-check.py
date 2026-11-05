"""Time checking whether a Docker image exists, through Docker's socket and
through its CLI.

``calkit.docker.image_exists`` runs ``docker image inspect``. #1817 had it
ask Docker's socket instead, and that check is copied here as it was, so
this can be rerun without that branch: finding the socket the way Docker
does, from DOCKER_HOST, then the current context, then the default.

Each is timed for an image that's there and one that isn't, the two taking
turns so a busy machine slows each alike. Wall time is recorded, since most
of either is waiting on Docker.

Writes the medians, every sample, and the machine to the given path.
"""

import argparse
import hashlib
import http.client
import json
import os
import platform
import socket
import statistics
import subprocess
import time
import urllib.parse
from pathlib import Path

from calkit.docker import image_exists

parser = argparse.ArgumentParser()
parser.add_argument("--image", default="ghcr.io/calkit/latex:0.1.6")
parser.add_argument("--missing", default="calkit/no-such-image:0")
parser.add_argument("--repeats", type=int, default=30)
parser.add_argument("--out", required=True)
args = parser.parse_args()


def socket_path() -> str:
    # Docker's own order: DOCKER_HOST, then the current context
    host = os.environ.get("DOCKER_HOST")
    if not host:
        config_dir = Path(
            os.environ.get("DOCKER_CONFIG") or Path.home() / ".docker"
        )
        context = os.environ.get("DOCKER_CONTEXT")
        if not context:
            try:
                with open(config_dir / "config.json") as f:
                    context = json.load(f).get("currentContext")
            except (OSError, ValueError):
                pass
        if context and context != "default":
            meta = (
                config_dir
                / "contexts"
                / "meta"
                / hashlib.sha256(context.encode()).hexdigest()
                / "meta.json"
            )
            with open(meta) as f:
                host = json.load(f)["Endpoints"]["docker"]["Host"]
        else:
            host = "unix:///var/run/docker.sock"
    # #1817 left anything else to the CLI, which isn't what's timed here
    if not host.startswith("unix://"):
        raise SystemExit(f"Docker isn't on a Unix socket here: {host}")
    return host.removeprefix("unix://")


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str) -> None:
        super().__init__("localhost", timeout=5)
        self.socket_path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def through_socket(ref: str) -> bool:
    # Finding the socket every time, as #1817 did
    conn = UnixConnection(socket_path())
    try:
        quoted = urllib.parse.quote(ref, safe="/:")
        conn.request("GET", f"/images/{quoted}/json")
        code = conn.getresponse().status
    finally:
        conn.close()
    if code not in (200, 404):
        raise SystemExit(f"Docker answered {code} for {ref}")
    return code == 200


load_before = os.getloadavg()
samples: dict[str, dict[str, list[float]]] = {
    "present": {"socket": [], "cli": []},
    "missing": {"socket": [], "cli": []},
}
for _ in range(args.repeats):
    for case, ref in [("present", args.image), ("missing", args.missing)]:
        for way, check in [("socket", through_socket), ("cli", image_exists)]:
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
    "saved_ms": {
        case: ways["cli"] - ways["socket"] for case, ways in ms.items()
    },
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
