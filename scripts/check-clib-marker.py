"""Check that the ruamel.yaml.clib marker matches its wheels on PyPI.

Calkit depends on ruamel.yaml.clib only where it has wheels, since anywhere
else it would need a compiler to install. A release can add wheels, e.g., for
a new Python, or drop them, so this lists where the marker in pyproject.toml
and the newest release's wheels disagree, and exits with 3 if they do.
"""

import json
import re
import sys
import urllib.request

import tomllib
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import parse_wheel_filename

# Where a wheel's platform tag installs, as sys_platform and platform_machine
LINUX = r"(?:many|musl)linux\w*?_(x86_64|aarch64|i686|ppc64le|s390x|armv7l)"
MACHINES = {
    "darwin": ["x86_64", "arm64"],
    "linux": ["x86_64", "aarch64", "i686", "ppc64le", "s390x", "armv7l"],
    "win32": ["AMD64", "x86", "ARM64"],
}


def platforms(tag: str) -> list[tuple[str, str]]:
    if m := re.fullmatch(r"macosx_\d+_\d+_(x86_64|arm64|universal2)", tag):
        arch = m.group(1)
        return [
            ("darwin", a)
            for a in MACHINES["darwin"]
            if arch in (a, "universal2")
        ]
    if m := re.fullmatch(LINUX, tag):
        return [("linux", m.group(1))]
    windows = {"win_amd64": "AMD64", "win32": "x86", "win_arm64": "ARM64"}
    if tag in windows:
        return [("win32", windows[tag])]
    return []


with open("pyproject.toml", "rb") as f:
    project = tomllib.load(f)["project"]
req = next(
    Requirement(r)
    for r in project["dependencies"]
    if Requirement(r).name == "ruamel.yaml.clib"
)
assert req.marker is not None
with urllib.request.urlopen(
    "https://pypi.org/pypi/ruamel.yaml.clib/json", timeout=30
) as resp:
    pypi = json.load(resp)
version = pypi["info"]["version"]
# Python versions and platforms the newest release has a wheel for, leaving
# out free-threaded builds, which a marker can't tell apart
wheels: set[tuple[str, str, str]] = set()
for f in pypi["releases"][version]:
    if not f["filename"].endswith(".whl"):
        continue
    for tag in parse_wheel_filename(f["filename"])[3]:
        m = re.fullmatch(r"cp3(\d+)", tag.interpreter)
        if m is None or tag.abi.endswith("t"):
            continue
        for plat in platforms(tag.platform):
            wheels.add((f"3.{m.group(1)}", *plat))
# Every Calkit-supported Python up to one past the newest with a wheel, so a
# cap left too high shows up too
newest = max(int(py.split(".")[1]) for py, _, _ in wheels)
pythons = [
    f"3.{n}"
    for n in range(newest + 2)
    if SpecifierSet(project["requires-python"]).contains(f"3.{n}")
]
missed, unbuildable = [], []
for py in pythons:
    for system, machines in MACHINES.items():
        for machine in machines:
            env = {
                "implementation_name": "cpython",
                "platform_python_implementation": "CPython",
                "python_version": py,
                "python_full_version": f"{py}.0",
                "sys_platform": system,
                "platform_machine": machine,
                "os_name": "nt" if system == "win32" else "posix",
            }
            included = req.marker.evaluate(env)
            has_wheel = (py, system, machine) in wheels
            if has_wheel and not included:
                missed.append(f"Python {py}, {system} {machine}")
            elif included and not has_wheel:
                unbuildable.append(f"Python {py}, {system} {machine}")
if not missed and not unbuildable:
    print(f"The marker matches ruamel.yaml.clib {version}'s wheels.")
    sys.exit(0)
print(
    f"The `ruamel.yaml.clib` marker in `pyproject.toml` doesn't match the "
    f"wheels of its newest release, {version}, on PyPI.\n\n"
    f"Marker: `{req.marker}`\n"
)
if missed:
    print("Has a wheel, but the marker leaves it out:\n")
    print("\n".join(f"- {m}" for m in missed) + "\n")
if unbuildable:
    print(
        "The marker includes it, but there's no wheel, so installing would "
        "need a compiler:\n"
    )
    print("\n".join(f"- {m}" for m in unbuildable) + "\n")
sys.exit(3)
