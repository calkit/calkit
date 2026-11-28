# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pyyaml>=6.0.4",
#     "requests>=2.34.2",
# ]
# ///
"""Find Calkit projects in the wild, i.e., repos with a calkit.yaml.

Candidates come from GitHub code search, the Calkit hub's public projects,
and DataCite records of Calkit archives (Zenodo, CaltechDATA, figshare).
Each candidate owner's other recent repos are checked too, since code search
only indexes some of them, and other branches of the candidates themselves,
to catch Calkit being tried out on one. GitHub API requests use the GitHub
CLI's token, and GraphQL to read many repos' calkit.yaml files in each one.

Writes data/calkit-projects/projects.csv.
"""

import csv
import json
import os
import re
import subprocess
import time
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
# Named like the REST API's, which the rows below were first written for
REPO_FIELDS = (
    "full_name: nameWithOwner name html_url: url description"
    " fork: isFork created_at: createdAt pushed_at: pushedAt"
    " owner { login } parent { full_name: nameWithOwner } isPrivate"
)
repo_url_re = re.compile(r"github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/|$)")


def send(method: str, path: str, **kwargs: Any) -> requests.Response:
    """Send a GitHub API request, waiting out rate limits."""
    while True:
        resp = gh_session.request(
            method, f"https://api.github.com/{path}", timeout=60, **kwargs
        )
        rate_limited = resp.status_code in (403, 429) and (
            resp.headers.get("x-ratelimit-remaining") == "0"
            or "retry-after" in resp.headers
        )
        if not rate_limited:
            return resp
        wait_for_reset(resp)


def wait_for_reset(resp: requests.Response) -> None:
    reset = int(resp.headers.get("x-ratelimit-reset", time.time()))
    retry_after = int(resp.headers.get("retry-after", 0))
    time.sleep(max(reset - time.time(), retry_after, 1) + 1)


def gh(path: str, **params: Any) -> Any:
    """GET from the GitHub API, returning None for a 404 or 409 (empty)."""
    resp = send("GET", path, params=params)
    if resp.status_code in (404, 409, 451):
        return None
    resp.raise_for_status()
    return resp.json()


def get_graphql_results(
    fields: dict[str, str], batch_size: int
) -> dict[str, Any]:
    """Query GraphQL for aliased fields, many per request.

    Returns each alias's result, which is None for a missing repo or owner.
    A batch that times out is split in half and retried.
    """
    results: dict[str, Any] = {}
    aliases = list(fields)
    batches = [
        aliases[i : i + batch_size] for i in range(0, len(aliases), batch_size)
    ]
    while batches:
        batch = batches.pop()
        body = " ".join(f"{alias}: {fields[alias]}" for alias in batch)
        resp = send("POST", "graphql", json={"query": f"query {{ {body} }}"})
        if resp.status_code in (502, 504) and len(batch) > 1:
            batches += [batch[: len(batch) // 2], batch[len(batch) // 2 :]]
            continue
        resp.raise_for_status()
        data = resp.json()
        error_types = {e.get("type") for e in data.get("errors") or []}
        if "RATE_LIMITED" in error_types:
            wait_for_reset(resp)
            batches.append(batch)
            continue
        # Missing repos, owners, and files come back as null
        if error_types - {"NOT_FOUND"}:
            raise RuntimeError(data["errors"])
        results.update(data["data"])
    return results


def get_repo_field(name: str, fields: str) -> str:
    owner, repo_name = (json.dumps(part) for part in name.split("/"))
    return f"repository(owner: {owner}, name: {repo_name}) {{ {fields} }}"


def load_calkit_yaml(text: str | None) -> dict:
    try:
        content = yaml.safe_load(text or "")
    except yaml.YAMLError:
        content = None
    return content if isinstance(content, dict) else {}


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
        # Searches the token can see include private repos, which aren't ours
        # to list
        if hit["repository"]["private"]:
            continue
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
# Every candidate owner's recent repos, newest first, so paging stops at the
# first one pushed before PUSHED_SINCE
owners = sorted({name.split("/")[0] for name in found_via})
print(f"Listing repos of {len(owners)} owners")
repos: dict[str, dict] = {}
cursors: dict[str, str | None] = dict.fromkeys(owners)
n_pages = 0
while cursors and n_pages < 10:
    n_pages += 1
    owner_aliases = {f"o{i}": owner for i, owner in enumerate(cursors)}
    results = get_graphql_results(
        {
            alias: f"repositoryOwner(login: {json.dumps(owner)})"
            " { repositories(first: 100,"
            f" after: {json.dumps(cursors[owner])},"
            " privacy: PUBLIC, ownerAffiliations: [OWNER],"
            " orderBy: {field: PUSHED_AT, direction: DESC})"
            " { pageInfo { hasNextPage endCursor }"
            f" nodes {{ {REPO_FIELDS} }} }} }}"
            for alias, owner in owner_aliases.items()
        },
        batch_size=5,
    )
    cursors = {}
    for alias, owner in owner_aliases.items():
        repos_page = (results.get(alias) or {}).get("repositories")
        if not repos_page:
            continue
        recent = [
            r
            for r in repos_page["nodes"]
            if (r["pushed_at"] or "") >= PUSHED_SINCE
        ]
        for repo in recent:
            repos[repo["full_name"].lower()] = repo
        if repos_page["pageInfo"]["hasNextPage"] and len(recent) == len(
            repos_page["nodes"]
        ):
            cursors[owner] = repos_page["pageInfo"]["endCursor"]
missing = [
    name
    for name in found_via
    if name not in repos and name not in hub_projects
]
results = get_graphql_results(
    {
        f"r{i}": get_repo_field(name, REPO_FIELDS)
        for i, name in enumerate(missing)
    },
    batch_size=50,
)
# A repo on DataCite or the hub may have been made private since
for repo in results.values():
    if repo and not repo["isPrivate"]:
        repos[repo["full_name"].lower()] = repo
# Each repo's root calkit.yaml on its default branch
print(f"Reading calkit.yaml from {len(repos)} repos")
names = list(repos)
results = get_graphql_results(
    {
        f"r{i}": get_repo_field(
            name,
            'object(expression: "HEAD:calkit.yaml") { ... on Blob { text } }',
        )
        for i, name in enumerate(names)
    },
    batch_size=50,
)
texts = {
    name: results[f"r{i}"]["object"].get("text")
    for i, name in enumerate(names)
    if (results.get(f"r{i}") or {}).get("object") is not None
}
# Default branch names only for those, since each is a slow Git lookup
names = list(texts)
results = get_graphql_results(
    {
        f"r{i}": get_repo_field(name, "defaultBranchRef { name }")
        for i, name in enumerate(names)
    },
    batch_size=50,
)
calkit_yamls: dict[str, tuple[str | None, dict | None]] = {
    name: (
        results[f"r{i}"]["defaultBranchRef"]["name"],
        load_calkit_yaml(texts[name]),
    )
    for i, name in enumerate(names)
}
# Other branches, only of repos found to be Calkit projects some other way,
# e.g., on the hub, since a branch is another Git lookup
names = [
    name for name in repos if name in found_via and name not in calkit_yamls
]
print(f"Reading calkit.yaml from other branches of {len(names)} repos")
results = get_graphql_results(
    {
        f"r{i}": get_repo_field(
            name,
            'refs(refPrefix: "refs/heads/", first: 100) { nodes { name target'
            ' { ... on Commit { file(path: "calkit.yaml") { object'
            " { ... on Blob { text } } } } } } }",
        )
        for i, name in enumerate(names)
    },
    batch_size=10,
)
for i, name in enumerate(names):
    branches = ((results.get(f"r{i}") or {}).get("refs") or {}).get(
        "nodes", []
    )
    for branch in branches:
        file = (branch["target"] or {}).get("file")
        if file:
            calkit_yamls[name] = (
                branch["name"],
                load_calkit_yaml((file["object"] or {}).get("text")),
            )
            break
projects = {name: repos[name] for name in calkit_yamls}
# A fork is the same project as its parent, if that's here too
for name, repo in list(projects.items()):
    parent = (repo["parent"] or {}).get("full_name", "").lower()
    if repo["fork"] and parent in projects:
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
