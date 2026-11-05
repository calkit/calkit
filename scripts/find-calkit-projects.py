"""Find Calkit projects in the wild, i.e., repos with a calkit.yaml.

Candidates come from GitHub code search, the Calkit hub's public projects,
and DataCite records of Calkit archives (Zenodo, CaltechDATA, figshare).
Each candidate owner's other recent repos are checked too, since code search
only indexes some of them, and other branches of the candidates themselves,
to catch Calkit being tried out on one. GitHub API requests use the GitHub
CLI's token. calkit.yaml files are read from raw.githubusercontent.com,
which doesn't count against the API's rate limit.

Writes data/calkit-projects/projects.csv.
"""

import csv
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests
import yaml

# Accounts whose projects are Pete's, e.g., a test account and Calkit's org
PETE_ACCOUNTS = {"petebachant", "pwbachant", "calkit"}
# Projects that are tests for now, though not named like one
TEST_PROJECTS = {"petebachant/boundary-layer-turbulence-modeling"}
# Calkit's first release; repos not pushed to since can't have a calkit.yaml
PUSHED_SINCE = "2024-06-01"
token = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
gh_session = requests.Session()
gh_session.headers.update(
    {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "calkit",
    }
)
repo_url_re = re.compile(r"github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/|$)")


def gh(path: str, **params: Any) -> Any:
    """GET from the GitHub API, returning None for a 404 or 409 (empty)."""
    while True:
        resp = gh_session.get(
            f"https://api.github.com/{path}", params=params, timeout=60
        )
        if resp.status_code in (404, 409, 451):
            return None
        rate_limited = resp.status_code in (403, 429) and (
            resp.headers.get("x-ratelimit-remaining") == "0"
            or "retry-after" in resp.headers
        )
        if rate_limited:
            reset = int(resp.headers.get("x-ratelimit-reset", time.time()))
            retry_after = int(resp.headers.get("retry-after", 0))
            time.sleep(max(reset - time.time(), retry_after, 1) + 1)
            continue
        resp.raise_for_status()
        return resp.json()


def gh_pages(path: str, max_pages: int = 10, **params: Any) -> list:
    items = []
    for page in range(1, max_pages + 1):
        data = gh(path, per_page=100, page=page, **params)
        if not data:
            break
        batch = data["items"] if isinstance(data, dict) else data
        items.extend(batch)
        if len(batch) < 100:
            break
    return items


def full_name(url: str | None) -> str | None:
    m = repo_url_re.search(url or "")
    return f"{m.group(1)}/{m.group(2)}".lower() if m else None


# Candidates, keyed by lowercase owner/name, with where each was found
found_via: dict[str, set[str]] = {}
hub_projects: dict[str, dict] = {}
for query in [
    "filename:calkit.yaml",
    "path:/ filename:calkit.yaml",
    '"calkit run" path:.github/workflows',
    '"uses: calkit"',
]:
    # Code search allows 10 requests a minute
    for hit in gh_pages("search/code", q=query):
        name = hit["repository"]["full_name"].lower()
        found_via.setdefault(name, set()).add("github-search")
    time.sleep(7)
offset = 0
while True:
    resp = requests.get(
        "https://api.calkit.io/projects",
        params={"limit": 100, "offset": offset},
        timeout=60,
    )
    resp.raise_for_status()
    batch = resp.json()["data"]
    for p in batch:
        key = full_name(p["git_repo_url"]) or (
            f"{p['owner_account_name']}/{p['name']}".lower()
        )
        hub_projects[key] = p
        found_via.setdefault(key, set()).add("hub")
    if len(batch) < 100:
        break
    offset += 100
for query in ["calkit", '"Calkit project"']:
    page = 1
    while True:
        params: dict[str, Any] = {"query": query, "page[size]": 100}
        resp = requests.get(
            "https://api.datacite.org/dois",
            params=params | {"page[number]": page},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        for record in data["data"]:
            for rel in record["attributes"].get("relatedIdentifiers") or []:
                name = full_name(rel.get("relatedIdentifier"))
                if name:
                    found_via.setdefault(name, set()).add("datacite")
        if page >= data["meta"].get("totalPages", 1):
            break
        page += 1
# Every candidate owner's recent repos
owners = {name.split("/")[0] for name in found_via}
with ThreadPoolExecutor(8) as pool:
    owner_repos = dict(
        zip(
            owners,
            pool.map(
                lambda o: gh_pages(f"users/{o}/repos", type="owner"), owners
            ),
        )
    )
repos: dict[str, dict] = {}
for owner_list in owner_repos.values():
    for repo in owner_list:
        if repo["pushed_at"] >= PUSHED_SINCE:
            repos[repo["full_name"].lower()] = repo
for name in found_via:
    if name not in repos and name not in hub_projects:
        repo = gh(f"repos/{name}")
        if repo:
            repos[name] = repo


def find_calkit_yaml(repo: dict) -> tuple[str | None, dict | None]:
    """Return the ref holding a root calkit.yaml, and its contents."""

    def read(ref: str) -> dict | None:
        resp = requests.get(
            f"https://raw.githubusercontent.com/{repo['full_name']}/{ref}"
            "/calkit.yaml",
            timeout=60,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        try:
            content = yaml.safe_load(resp.text)
        except yaml.YAMLError:
            content = None
        return content if isinstance(content, dict) else {}

    ref = repo["default_branch"]
    content = read(ref)
    if content is not None:
        return ref, content
    # Listing branches costs API requests, so only for repos found to be
    # Calkit projects some other way, e.g., on the hub
    if repo["full_name"].lower() not in found_via:
        return None, None
    for branch in gh_pages(f"repos/{repo['full_name']}/branches", max_pages=1):
        if branch["name"] != ref:
            content = read(branch["name"])
            if content is not None:
                return branch["name"], content
    return None, None


with ThreadPoolExecutor(16) as pool:
    calkit_yamls = dict(zip(repos, pool.map(find_calkit_yaml, repos.values())))
projects = {
    name: repos[name] for name, (ref, _) in calkit_yamls.items() if ref
}
# A fork is the same project as its parent, if that's here too
for name, repo in list(projects.items()):
    if repo["fork"]:
        parent = (gh(f"repos/{name}") or {}).get("parent") or {}
        if parent.get("full_name", "").lower() in projects:
            del projects[name]


def is_pete(name: str) -> bool:
    if name.split("/")[0] in PETE_ACCOUNTS:
        return True
    contributors = gh(f"repos/{name}/contributors", per_page=1) or []
    return bool(contributors) and (
        contributors[0]["login"].lower() in PETE_ACCOUNTS
    )


rows = []
example_re = re.compile(
    r"example|test|demo|tutorial|template|sandbox|scratch", re.IGNORECASE
)
for name in sorted(set(projects) | set(hub_projects)):
    repo = projects.get(name)
    hub = hub_projects.get(name)
    # Hub-only projects have no GitHub repo to describe them
    item: dict = repo or hub_projects[name]
    ref, content = calkit_yamls.get(name, (None, None))
    title = (content or {}).get("title") or (hub or {}).get("title")
    if repo:
        url = repo["html_url"]
        owner, repo_name = repo["owner"]["login"], repo["name"]
        description = repo["description"] or ""
    else:
        url = item["git_repo_url"] or ""
        owner, repo_name = item["owner_account_name"], item["name"]
        description = item["description"] or ""
    rows.append(
        {
            "url": url,
            "owner": owner,
            "name": repo_name,
            # Collapsed, since a folded YAML string ends in a newline
            "title": " ".join(str(title or "").split()),
            "found_via": "+".join(sorted(found_via.get(name, {"owner-scan"}))),
            "calkit_yaml_ref": ref or "",
            "on_hub": hub is not None,
            "is_fork": bool(repo and repo["fork"]),
            "created": item.get("created_at", item.get("created"))[:10],
            "last_pushed": item.get("pushed_at", item.get("updated"))[:10],
            "is_pete": is_pete(name.lower()),
            "is_example_or_test": bool(
                owner.lower() == "calkit"
                or name in TEST_PROJECTS
                or example_re.search(
                    f"{repo_name} {title or ''} {description}"
                )
            ),
        }
    )
os.makedirs("data/calkit-projects", exist_ok=True)
with open(
    "data/calkit-projects/projects.csv", "w", newline="", encoding="utf-8"
) as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys(), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
print(f"Found {len(rows)} Calkit projects")
