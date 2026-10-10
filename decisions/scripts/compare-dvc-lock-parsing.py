"""Compare DVC's dvc.lock parsing with and without ruamel.yaml's C loader.

Refuses to compare timings unless both parsed the same text to the same
data, with the C loader in only one of them, and on the same machine.

Writes results/ruamel-yaml-clib.json.
"""

import json

with open("results/ruamel-yaml-clib/pure.json") as f:
    pure = json.load(f)
with open("results/ruamel-yaml-clib/clib.json") as f:
    clib = json.load(f)
if pure["lock"] != clib["lock"]:
    raise ValueError(
        "The two runs didn't parse the same lock to the same data"
    )
if pure["c_loader"] or not clib["c_loader"]:
    raise ValueError("Only the clib environment should have the C loader")
if pure["machine"] != clib["machine"]:
    raise ValueError("The two runs were on different machines")
result = {
    "lock": pure["lock"] | {"kb": pure["lock"]["bytes"] / 1000},
    "seconds": {"pure": pure["seconds"], "clib": clib["seconds"]},
    "speedup": pure["seconds"] / clib["seconds"],
    "packages": {"pure": pure["packages"], "clib": clib["packages"]},
    "machine": pure["machine"],
}
with open("results/ruamel-yaml-clib.json", "w") as f:
    json.dump(result, f, indent=2)
    f.write("\n")
