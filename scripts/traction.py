"""Fetch Calkit's usage numbers for the one-pager.

The stage only reruns when this script changes, so the numbers stay frozen
as of the date recorded with them.

Writes results/traction.json.
"""

import argparse
import datetime
import json
import subprocess
import urllib.request
from typing import Any

parser = argparse.ArgumentParser()
# Registered users on calkit.io, read off the hub, which has no public API
# for it; some users don't use the hub at all
parser.add_argument("--hub-users", type=int, required=True)
args = parser.parse_args()


def get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "calkit"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


repo = get_json("https://api.github.com/repos/calkit/calkit")
pypi = get_json("https://pypistats.org/api/packages/calkit-python/recent")
tags = subprocess.check_output(["git", "tag", "-l", "v*"], text=True).split()
results = {
    "date": datetime.date.today().isoformat(),
    "hub_users": args.hub_users,
    "github_stars": repo["stargazers_count"],
    "github_forks": repo["forks_count"],
    "pypi_downloads_last_month": pypi["data"]["last_month"],
    "releases": len(tags),
}
with open("results/traction.json", "w") as f:
    json.dump(results, f, indent=2)
    f.write("\n")
