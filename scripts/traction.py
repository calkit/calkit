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
import time
import urllib.error
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
    # pypistats.org rate limits, so back off and retry
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4:
                raise
            time.sleep(int(e.headers.get("retry-after") or 2**attempt * 10))


repo = get_json("https://api.github.com/repos/calkit/calkit")
hub = calkit.hub.get("/stats", params={"exclude": args.exclude_hub_account})
pypi = get_json("https://pypistats.org/api/packages/calkit-python/recent")
# Papers out the door, i.e., published, preprinted, or archived, leaving out
# examples' and tests'
with open("data/calkit-projects/papers.csv", encoding="utf-8") as f:
    papers = [
        row
        for row in csv.DictReader(f)
        if row["status"] in ("published", "preprint", "archived")
        and row["is_example_or_test"] == "False"
    ]
tags = subprocess.check_output(["git", "tag", "-l", "v*"], text=True).split()
results = {
    "date": datetime.date.today().isoformat(),
    "hub_users": hub["users"]["total"],
    "hub_projects": hub["projects"]["total"],
    "hub_projects_worked_on": hub["projects"]["worked_on"],
    "hub_project_owners": hub["projects"]["owners"],
    "hub_excluded_accounts": hub["excluded_accounts"],
    # Signed-in users active in the last 30 days, from Mixpanel via the hub,
    # if it's set up to read it
    "hub_monthly_active_users": (
        (hub.get("analytics") or {}).get("active_users") or {}
    ).get("last_30_days"),
    "github_stars": repo["stargazers_count"],
    "github_forks": repo["forks_count"],
    "pypi_downloads_last_month": pypi["data"]["last_month"],
    "releases": len(tags),
    # By title, since a paper can be in more than one repo, e.g., a copy
    "papers_shipped": len(
        {" ".join(p["title"].lower().split()) for p in papers}
    ),
}
with open("results/traction.json", "w") as f:
    json.dump(results, f, indent=2)
    f.write("\n")
