"""Fetch Calkit's usage numbers for the one-pager, and count papers.

The stage only reruns when this script changes, so the numbers stay frozen
as of the date recorded with them. The hub's numbers need a superuser's
Calkit token.

Writes results/traction.json.
"""

import argparse
import csv
import datetime
import json
import subprocess
import urllib.request
from typing import Any

import calkit.hub

parser = argparse.ArgumentParser()
# Accounts whose projects aren't usage, on top of superusers', which the hub
# leaves out itself, e.g., test accounts and orgs holding examples
parser.add_argument("--exclude-hub-account", action="append", default=[])
args = parser.parse_args()


def get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "calkit"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


repo = get_json("https://api.github.com/repos/calkit/calkit")
hub = calkit.hub.get("/stats", params={"exclude": args.exclude_hub_account})
pypi = get_json("https://pypistats.org/api/packages/calkit-python/recent")
# Papers and theses out the door, i.e., published, submitted, or preprinted
with open("data/calkit-projects/papers.csv", encoding="utf-8") as f:
    papers = [
        row
        for row in csv.DictReader(f)
        if row["kind"] in ("paper", "thesis")
        and row["status"] in ("published", "submitted", "preprint")
    ]
tags = subprocess.check_output(["git", "tag", "-l", "v*"], text=True).split()
results = {
    "date": datetime.date.today().isoformat(),
    "hub_users": hub["users"]["total"],
    "hub_projects": hub["projects"]["total"],
    "hub_projects_worked_on": hub["projects"]["worked_on"],
    "hub_project_owners": hub["projects"]["owners"],
    "hub_excluded_accounts": hub["excluded_accounts"],
    "github_stars": repo["stargazers_count"],
    "github_forks": repo["forks_count"],
    "pypi_downloads_last_month": pypi["data"]["last_month"],
    "releases": len(tags),
    "papers_shipped": len(papers),
}
with open("results/traction.json", "w") as f:
    json.dump(results, f, indent=2)
    f.write("\n")
