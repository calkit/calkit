"""Reference collection routes.

A reference lives in a ``.bib`` file inside a project, so reading them
means cloning projects and parsing their collections. That cost is why the
search is scoped rather than global: see ``get_references``.
"""

import logging
import os
import re
from typing import Annotated, Literal

import bibtexparser
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select

import app.projects
from app import arxiv, zotero
from app.api.deps import CurrentUser, SessionDep
from app.api.routes.projects.core import DEFAULT_REPO_TTL
from app.git import get_ck_info_from_repo, get_repo
from app.models import Project

logger = logging.getLogger(__name__)
router = APIRouter()


def _normalize_doi(value: str | None) -> str | None:
    """Reduce a DOI to a bare, comparable form, e.g. ``10.1234/abcd``."""
    if not value:
        return None
    doi = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi.strip("/ ") or None


def _normalize_arxiv_id(value: str | None) -> str | None:
    """Reduce an arXiv ID to a bare, version-less form, e.g. ``2301.01234``."""
    if not value:
        return None
    arxiv_id = value.strip().lower()
    for prefix in (
        "https://arxiv.org/abs/",
        "http://arxiv.org/abs/",
        "arxiv:",
    ):
        if arxiv_id.startswith(prefix):
            arxiv_id = arxiv_id[len(prefix) :]
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id.strip("/ "))
    return arxiv_id or None


def _normalize_title(value: str | None) -> str | None:
    """Reduce a title to letters and digits so punctuation, case, and LaTeX
    braces don't defeat a comparison.
    """
    if not value:
        return None
    return re.sub(r"[^a-z0-9]+", "", value.lower()) or None


class ReferenceSearchMatch(BaseModel):
    project_owner_name: str
    project_name: str
    project_title: str
    path: str
    key: str
    type: str
    title: str | None = None
    doi: str | None = None
    note_count: int = 0
    # Null when the caller passed no filter, so every entry came back and
    # nothing in particular was matched against
    matched_on: Literal["doi", "arxiv_id", "title"] | None = None


@router.get("/references")
def get_references(
    current_user: CurrentUser,
    session: SessionDep,
    # Singular on the wire, because each occurrence names one project:
    # ?project=a/b&project=c/d. Plural in here, because it is a list.
    projects: Annotated[list[str] | None, Query(alias="project")] = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
    title: str | None = None,
    max_projects: int = 10,
) -> list[ReferenceSearchMatch]:
    """Read reference collections across projects the user can write to.

    Write access only. Reading a reference needs no more than read access,
    so this is narrower than the resource allows, and deliberately: every
    project searched has to be cloned and its collections parsed, so
    answering across everything readable would mean cloning arbitrary
    public projects. There is no ``min_access_level`` parameter because it
    would ship with one usable value.

    Every filter is optional. With none, this lists every entry it finds;
    with ``doi``, ``arxiv_id``, or ``title``, only entries matching one of
    them, which is how a client asks "is this paper already filed?".

    ``project`` narrows the search to the given ``owner/name`` pairs, and
    may be repeated: ``?project=me/one&project=me/two``.

    ``max_projects`` bounds the cloning. Projects beyond it are not
    searched, and the response does not say so.
    """
    target_doi = _normalize_doi(doi)
    target_arxiv_id = _normalize_arxiv_id(arxiv_id)
    target_title = _normalize_title(title)
    filtering = any([target_doi, target_arxiv_id, target_title])
    if max_projects < 1:
        raise HTTPException(422, "max_projects must be at least 1")
    project_specs: list[str] = []
    if projects is None:
        owned = session.exec(
            select(Project)
            .where(app.projects.writable_project_clause(current_user))
            .order_by(Project.updated.desc())  # type: ignore[union-attr]
            .limit(max_projects)
        ).all()
        project_specs = [f"{p.owner_account_name}/{p.name}" for p in owned]
    else:
        for project_spec in projects:
            if project_spec.count("/") != 1:
                raise HTTPException(
                    422,
                    f"Invalid project '{project_spec}'; expected owner/name",
                )
            project_specs.append(project_spec)
        if len(project_specs) > max_projects:
            raise HTTPException(
                422, f"At most {max_projects} projects can be searched"
            )
    resp = []
    for project_spec in project_specs:
        spec_owner_name, spec_project_name = project_spec.split("/")
        try:
            project = app.projects.get_project(
                owner_name=spec_owner_name,
                project_name=spec_project_name,
                session=session,
                current_user=current_user,
                min_access_level="read",
            )
            repo = get_repo(
                project=project,
                user=current_user,
                session=session,
                ttl=DEFAULT_REPO_TTL,
            )
        except HTTPException as e:
            # One inaccessible project shouldn't sink the whole lookup
            logger.info(f"Skipping project '{project_spec}': {e.detail}")
            continue
        ck_info = get_ck_info_from_repo(repo)
        bib_paths = {
            rc["path"]
            for rc in (ck_info.get("references") or [])
            if isinstance(rc, dict) and "path" in rc
        }
        try:
            for blob in repo.head.commit.tree.traverse():
                if blob.type != "blob":  # type: ignore[union-attr]
                    continue
                blob_path = str(blob.path)  # type: ignore[union-attr]
                if not blob_path.lower().endswith(".bib"):
                    continue
                if any(p.startswith(".") for p in blob_path.split("/")):
                    continue
                bib_paths.add(blob_path)
        except Exception as e:
            logger.warning(f"Failed to scan for .bib files: {e}")
        for bib_path in sorted(bib_paths):
            full_path = os.path.join(repo.working_dir, bib_path)
            if not os.path.isfile(full_path):
                continue
            try:
                with open(full_path) as f:
                    bib_db = bibtexparser.loads(f.read())
            except Exception as e:
                logger.warning(f"Failed to parse BibTeX file {bib_path}: {e}")
                continue
            for entry in bib_db.entries:
                entry_doi = _normalize_doi(entry.get("doi"))
                entry_arxiv_id = _normalize_arxiv_id(
                    arxiv.id_from_bib_attrs(entry)
                )
                entry_title = _normalize_title(entry.get("title"))
                if not filtering:
                    matched_on = None
                elif target_doi and entry_doi == target_doi:
                    matched_on = "doi"
                elif target_arxiv_id and entry_arxiv_id == target_arxiv_id:
                    matched_on = "arxiv_id"
                elif target_title and entry_title == target_title:
                    matched_on = "title"
                else:
                    continue
                comment = entry.get(zotero.NOTE_FIELD)
                resp.append(
                    ReferenceSearchMatch(
                        project_owner_name=project.owner_account_name,
                        project_name=project.name,
                        project_title=project.title,
                        path=bib_path,
                        key=entry.get("ID", ""),
                        type=entry.get("ENTRYTYPE", "misc"),
                        title=entry.get("title"),
                        doi=entry.get("doi"),
                        note_count=len(
                            zotero.parse_notes_markdown(comment or "")
                        ),
                        matched_on=matched_on,  # type: ignore[arg-type]
                    )
                )
    return resp
