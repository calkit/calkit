"""Find papers built with the Calkit projects in the wild.

A project's calkit.yaml lists its publications, which are published once they
have a DOI, and archived once a release covers them, i.e., a release of the
publication itself or of the whole project. DataCite adds what calkit.yaml
doesn't record, e.g., an arXiv preprint whose abstract names the repo. Records
of Calkit's own archives are left out, since the releases already count them.

Writes data/calkit-projects/papers.csv.
"""

import csv
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests
import yaml

# Publication kinds that aren't papers
not_paper_kinds = {"proposal", "blog", "presentation", "poster"}
# DataCite resource types that are papers, as opposed to, e.g., software
paper_types = {
    "Book",
    "BookChapter",
    "ConferencePaper",
    "ConferenceProceeding",
    "Dissertation",
    "JournalArticle",
    "Preprint",
    "Report",
    "Text",
}


def get_json(url: str, **params: Any) -> Any:
    resp = requests.get(
        url, params=params, headers={"User-Agent": "calkit"}, timeout=60
    )
    return resp.json() if resp.ok else None


def doi_date(doi: str) -> str:
    """When a DOI was published, as precisely as is known, e.g., '2024-10'."""
    work = get_json(f"https://api.crossref.org/works/{doi}")
    if work:
        parts = work["message"]["issued"]["date-parts"][0]
        return "-".join(f"{p:02d}" for p in parts)
    record = get_json(f"https://api.datacite.org/dois/{doi}")
    return (
        str(record["data"]["attributes"]["publicationYear"]) if record else ""
    )


def find_papers(project: dict) -> list[dict]:
    full_name = f"{project['owner']}/{project['name']}"
    common = {
        "project": project["url"],
        "is_pete": project["is_pete"],
        "is_example_or_test": project["is_example_or_test"],
    }
    papers = []
    # What calkit.yaml records
    ck: dict = {}
    if project["calkit_yaml_ref"]:
        resp = requests.get(
            f"https://raw.githubusercontent.com/{full_name}"
            f"/{project['calkit_yaml_ref']}/calkit.yaml",
            timeout=60,
        )
        # Gone since the projects were found, e.g., with its branch
        if resp.status_code != 404:
            resp.raise_for_status()
            try:
                ck = yaml.safe_load(resp.text) or {}
            except yaml.YAMLError:
                ck = {}
    releases = ck.get("releases") or {}
    releases = releases.values() if isinstance(releases, dict) else []
    for pub in ck.get("publications") or []:
        if (
            not isinstance(pub, dict)
            or pub.get("kind") in not_paper_kinds
            or pub.get("imported_from")
        ):
            continue
        archives = sorted(
            (
                r
                for r in releases
                if isinstance(r, dict)
                and r.get("doi")
                and (
                    r.get("kind") == "project"
                    or (
                        r.get("kind") == "publication"
                        and r.get("path") == pub.get("path")
                    )
                )
            ),
            key=lambda r: str(r.get("date") or ""),
        )
        if pub.get("doi"):
            date = doi_date(pub["doi"])
            # Published before the project existed, so not built with it,
            # e.g., a paper being reproduced
            if date and date < project["created"][: len(date)]:
                status = "predates-project"
            else:
                status = "published"
            year = date[:4]
        elif archives:
            status, year = "archived", str(archives[-1].get("date", ""))[:4]
        else:
            status, year = "in-progress", ""
        papers.append(
            common
            | {
                "title": pub.get("title") or pub.get("path") or "",
                "kind": pub.get("kind") or "",
                "status": status,
                "year": year,
                "doi": pub.get("doi") or "",
                "archive_doi": archives[-1]["doi"] if archives else "",
                "found_via": "calkit.yaml",
            }
        )
    # What DataCite has that names the repo
    if "github.com" in project["url"]:
        data = get_json(
            "https://api.datacite.org/dois",
            query=f'"{full_name}"',
            **{"page[size]": 100},
        )
        known = {p["doi"].lower() for p in papers if p["doi"]}
        titles = set()
        for record in (data or {}).get("data", []):
            a = record["attributes"]
            descriptions = " ".join(
                d.get("description") or "" for d in a.get("descriptions") or []
            )
            title = (a.get("titles") or [{}])[0].get("title", "")
            if (
                a["types"].get("resourceTypeGeneral") not in paper_types
                or "from the Calkit project" in descriptions
                or a["doi"].lower() in known
                or title.lower() in titles
            ):
                continue
            titles.add(title.lower())
            kind = a["types"]["resourceTypeGeneral"]
            papers.append(
                common
                | {
                    "title": title,
                    "kind": kind.lower(),
                    "status": "preprint"
                    if kind == "Preprint"
                    else "published",
                    "year": str(a.get("publicationYear") or ""),
                    "doi": a["doi"],
                    "archive_doi": "",
                    "found_via": "datacite",
                }
            )
    return papers


with open("data/calkit-projects/projects.csv", encoding="utf-8") as f:
    projects = list(csv.DictReader(f))
with ThreadPoolExecutor(8) as pool:
    rows = [p for papers in pool.map(find_papers, projects) for p in papers]
with open(
    "data/calkit-projects/papers.csv", "w", newline="", encoding="utf-8"
) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "project",
            "title",
            "kind",
            "status",
            "year",
            "doi",
            "archive_doi",
            "found_via",
            "is_pete",
            "is_example_or_test",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
