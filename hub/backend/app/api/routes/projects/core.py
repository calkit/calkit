"""Main routes for projects."""

import base64
import concurrent.futures
import io
import json
import logging
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from copy import deepcopy
from datetime import datetime, timedelta
from fnmatch import fnmatch
from io import StringIO
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, NamedTuple, Optional, cast
from urllib.parse import quote, urlparse

import bibtexparser
import git
import requests
import sqlalchemy
import yaml
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from git.exc import GitCommandError
from pydantic import BaseModel, ValidationError
from sqlmodel import Session, and_, col, func, not_, or_, select
from TexSoup import TexSoup

import app.projects
import calkit
import calkit.detect
import calkit.latex
from app import (
    arxiv,
    github,
    messaging,
    mixpanel,
    orgs,
    pdftext,
    users,
    zotero,
)
from app.api.deps import (
    CurrentUser,
    CurrentUserOptional,
    SessionDep,
)
from app.api.routes.orgs import OrgPost, post_org
from app.config import settings
from app.core import (
    CATEGORIES_PLURAL_TO_SINGULAR,
    CATEGORIES_SINGULAR_TO_PLURAL,
    params_from_url,
    ryaml,
    utcnow,
)
from app.dvc import (
    expand_dvc_lock_outs,
    get_data_fpath_for_md5,
    make_mermaid_diagram,
    output_from_pipeline,
    run_dvc_command,
)
from app.git import (
    RepoTree,
    get_ck_info,
    get_ck_info_from_repo,
    get_commit_history,
    get_file_history,
    get_overleaf_repo,
    get_repo,
    get_zip_path_map_from_repo,
    resolve_commit_sha,
    search_refs,
)
from app.models import (
    Account,
    ContentsItem,
    Dataset,
    DatasetForImport,
    Figure,
    FileLock,
    GitRef,
    Message,
    Notebook,
    Notification,
    Org,
    OrgSubscription,
    OverleafLink,
    Pipeline,
    PipelineStage,
    PipelineStageEdit,
    PipelineStageEdited,
    PipelineStagePut,
    Presentation,
    Project,
    ProjectComment,
    ProjectCommentPatch,
    ProjectCommentPost,
    ProjectInvitation,
    ProjectInvitationCreated,
    ProjectInvitationPost,
    ProjectInvitationPublic,
    ProjectInvitationRedeemed,
    ProjectPost,
    ProjectPublic,
    ProjectsPublic,
    Publication,
    Question,
    QuestionEvidence,
    QuestionPublic,
    QuestionPut,
    Result,
    StageStatus,
    User,
    UserOrgMembership,
    UserProjectAccess,
)
from app.models.core import ROLE_IDS, ROLE_NAMES
from app.models.projects import (
    Showcase,
    ShowcaseFigure,
    ShowcaseFigureInput,
    ShowcaseInput,
    ShowcaseMarkdown,
    ShowcaseMarkdownFileInput,
    ShowcaseNotebook,
    ShowcaseNotebookInput,
    ShowcasePublication,
    ShowcasePublicationInput,
    ShowcaseText,
    ShowcaseYaml,
    ShowcaseYamlFileInput,
)
from app.pipeline import (
    calc_overall_pipeline_status,
    color_mermaid_by_status,
    compute_stage_statuses,
    find_stage_for_path,
)
from app.security import generate_refresh_token, hash_refresh_token
from app.storage import (
    get_object_fs,
    get_object_url,
    make_data_fpath,
    remove_gcs_content_type,
)
from calkit.check import ReproCheck, check_reproducibility
from calkit.models import ProjectStatus
from calkit.models.pipeline import LatexStage as CkLatexStage
from calkit.models.pipeline import Pipeline as CkPipeline
from calkit.models.pipeline import Stage as CkStage
from calkit.notebooks import get_executed_notebook_path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_REPO_TTL = 60  # Seconds
FULL_HISTORY_REPO_TTL = 10 * 60  # Seconds; history changes infrequently

FIGURE_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".pdf"}
FIGURE_DIRS = {"figures", "figure", "figs", "fig", "plots", "images"}

# Mirrors calkit-python's result detection (calkit/detect.py): data-like files
# under a results-style directory that aren't already figures.
RESULT_EXTS = {
    ".json",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
    ".parquet",
    ".h5",
    ".hdf5",
    ".txt",
    ".html",
}
RESULT_DIRS = {"results", "result"}


def _title_from_path(path: str) -> str:
    """Derive a human-readable title from an artifact's file name."""
    # Repo paths are always Posix, so parse them as such regardless of host OS.
    stem = PurePosixPath(path).stem
    return stem.replace("_", " ").replace("-", " ").capitalize()


PRESENTATION_EXTS = {".pdf", ".pptx", ".ppt", ".key", ".odp"}
PRESENTATION_DIRS = {
    "slides",
    "slide",
    "presentation",
    "presentations",
    "talks",
    "talk",
    "decks",
    "deck",
}


@router.get("/projects")
def get_projects(
    session: SessionDep,
    current_user: CurrentUserOptional,
    limit: int = 100,
    offset: int = 0,
    search_for: str | None = None,
    owner_name: str | None = None,
    github_repo: str | None = None,
    min_access_level: Literal["read", "write"] = "read",
) -> ProjectsPublic:
    if current_user is None:
        if min_access_level != "read":
            raise HTTPException(403, "User is not authenticated")
        where_clause = Project.is_public
    elif min_access_level == "write":
        # GitHub-derived access is only present once it has been resolved
        # and cached for this user, so a GitHub collaborator who has never
        # opened the project won't appear until they do.
        where_clause = app.projects.writable_project_clause(current_user)
    else:
        where_clause = or_(
            Project.is_public,
            Project.owner_account_id == current_user.account.id,
            # A row in the unified access table with either a native Calkit
            # grant (role_id, e.g. an invite redemption) or GitHub-derived
            # access. A row with both null is a cached "no access" result.
            and_(
                UserProjectAccess.user_id == current_user.id,
                or_(
                    UserProjectAccess.role_id.is_not(None),  # type: ignore
                    UserProjectAccess.github_access.is_not(None),  # type: ignore
                ),
            ),
            Project.owner_account.has(  # type: ignore
                and_(
                    Account.org_id.is_not(None),  # type: ignore
                    select(UserOrgMembership)
                    .where(
                        UserOrgMembership.user_id == current_user.id,
                        UserOrgMembership.org_id == Account.org_id,
                    )
                    .exists(),
                )
            ),
        )
    if owner_name is not None:
        where_clause = and_(
            where_clause,
            Project.owner_account.has(Account.name == owner_name.lower()),  # type: ignore
        )
    if github_repo is not None:
        # An exact repo lookup, e.g. for resolving the project behind a
        # GitHub page. The repo URL is stored with or without the .git
        # suffix depending on how the project was created.
        repo_url = f"https://github.com/{github_repo.strip('/')}"
        where_clause = and_(
            where_clause,
            or_(
                func.lower(Project.git_repo_url) == repo_url.lower(),
                func.lower(Project.git_repo_url) == f"{repo_url.lower()}.git",
            ),
        )
    if search_for is not None:
        search_for = f"%{search_for}%"
        where_clause = and_(
            where_clause,
            or_(
                Project.name.ilike(search_for),  # type: ignore
                Project.title.ilike(search_for),  # type: ignore
                Project.description.ilike(search_for),  # type: ignore
                Project.git_repo_url.ilike(search_for),  # type: ignore
            ),
        )
    count_query = (
        select(func.count())
        .select_from(Project)
        .distinct()
        .join(Project.user_access_records, isouter=True)  # type: ignore
        .where(where_clause)
    )
    count = session.exec(count_query).one()
    select_query = (
        select(Project)
        .distinct()
        .join(Project.user_access_records, isouter=True)  # type: ignore
        .where(where_clause)
        .order_by(sqlalchemy.desc(Project.created))  # type: ignore
        .limit(limit)
        .offset(offset)
    )
    projects = session.exec(select_query).all()
    return ProjectsPublic(data=projects, count=count)  # type: ignore


@router.get("/user/projects")
def get_owned_projects(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = 100,
    offset: int = 0,
    search_for: str | None = None,
) -> ProjectsPublic:
    where_clause = or_(
        Project.owner_account_id == current_user.account.id,
        # A native Calkit grant (role_id), e.g. an invite redemption, the only
        # access path for GitHub-less collaborators.
        Project.user_access_records.any(  # type: ignore
            and_(
                UserProjectAccess.user_id == current_user.id,
                UserProjectAccess.role_id.is_not(None),
            )
        ),
        Project.owner_account.has(  # type: ignore
            and_(
                Account.org_id.is_not(None),  # type: ignore
                select(UserOrgMembership)
                .where(
                    UserOrgMembership.user_id == current_user.id,
                    UserOrgMembership.org_id == Account.org_id,
                )
                .exists(),
            )
        ),
    )
    if search_for is not None:
        search_for = f"%{search_for}%"
        where_clause = and_(
            where_clause,
            or_(
                Project.name.ilike(search_for),  # type: ignore
                Project.title.ilike(search_for),  # type: ignore
                Project.description.ilike(search_for),  # type: ignore
                Project.git_repo_url.ilike(search_for),  # type: ignore
            ),
        )
    count_statement = (
        select(func.count()).select_from(Project).where(where_clause)
    )
    count = session.exec(count_statement).one()
    statement = (
        select(Project)
        .where(where_clause)
        .order_by(sqlalchemy.desc(Project.created))  # type: ignore
        .offset(offset)
        .limit(limit)
    )
    projects = session.exec(statement).all()
    return ProjectsPublic(data=projects, count=count)  # type: ignore


@router.post("/projects")
def post_project(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_in: ProjectPost,
) -> ProjectPublic:
    """Create new project."""
    # Project owners must have a linked GitHub account until git hosting is
    # decoupled from GitHub. GitHub-less users can still collaborate.
    if current_user.account.github_name is None:
        raise HTTPException(
            403,
            "A linked GitHub account is required to create or own projects.",
        )
    project_in.name = project_in.name.lower()
    if project_in.git_repo_exists and project_in.git_repo_url is None:
        raise HTTPException(
            400, "Git repo URL must be specified if Git repo exists"
        )
    if project_in.git_repo_url is None:
        project_in.git_repo_url = (
            f"https://github.com/{current_user.account.name}/{project_in.name}"
        )
    # First check if template even exists, if specified
    if project_in.template is not None:
        template_owner_name, template_project_name = project_in.template.split(
            "/"
        )
        template_project = app.projects.get_project(
            session=session,
            owner_name=template_owner_name,
            project_name=template_project_name,
            current_user=current_user,
            min_access_level="read",
        )
    # Validate the git repo URL is on github.com to prevent SSRF
    parsed_git_url = urlparse(project_in.git_repo_url)
    if parsed_git_url.hostname not in ("github.com", "www.github.com"):
        raise HTTPException(400, "Git repo URL must be on github.com")
    # Detect owner and repo name from Git repo URL
    # TODO: This should be generalized to not depend on GitHub?
    owner_name, repo_name = project_in.git_repo_url.split("/")[-2:]
    # Validate that the owner is either the current user or an org they belong
    # to before retrieving their GitHub token
    # This prevents users from using their token to make API calls for repos
    # they don't own
    is_user_org = False
    if owner_name != current_user.github_username:
        # Check if it's an org the user belongs to
        for membership in current_user.org_memberships:
            if (
                membership.org.account.github_name.lower()
                == owner_name.lower()
            ) and membership.role_name in ["owner", "admin", "write"]:
                is_user_org = True
                break
        if not is_user_org:
            raise HTTPException(
                403,
                "Can only create projects for yourself or organizations you "
                "belong to",
            )
    # Check if this user has exceeded their private projects limit if this one
    # is private
    if not project_in.git_repo_exists and not project_in.is_public:
        logger.info(f"Checking private project count for {owner_name}")
        if current_user.account.name == owner_name.lower():
            # Count private projects for user
            account_id = current_user.account.id
            subscription = current_user.subscription
        else:
            # Count private projects for an org
            # First check if this org exists in Calkit
            org = orgs.get_org_by_github_name(
                session=session, github_name=owner_name
            )
            if org is None:
                logger.info(f"Org '{owner_name}' does not exist in DB")
                # Try to create the org
                post_org(
                    req=OrgPost(github_name=owner_name),
                    session=session,
                    current_user=current_user,
                )
                org = orgs.get_org_by_github_name(
                    session=session, github_name=owner_name
                )
            assert isinstance(org, Org)
            account_id = org.account.id
            subscription = org.subscription
            if subscription is None:
                logger.info(f"Org '{owner_name}' does not have a subscription")
                # Give the org a free subscription
                org.subscription = OrgSubscription(
                    plan_id=0,
                    n_users=1,
                    price=0.0,
                    period_months=1,
                    subscriber_user_id=current_user.id,
                    org_id=org.id,
                )
                session.add(org.subscription)
                session.commit()
                session.refresh(org.subscription)
                subscription = org.subscription
        count_query = (
            select(func.count())
            .select_from(Project)
            .where(
                and_(
                    not_(Project.is_public),
                    Project.owner_account_id == account_id,
                )
            )
        )
        count = session.exec(count_query).one()
        limit = subscription.private_projects_limit  # type: ignore
        logger.info(f"{owner_name} has {count}/{limit} private projects")
        if limit is not None and count >= limit:
            raise HTTPException(400, "Private projects limit exceeded")
    # Check if this user already owns this repo on GitHub
    token = users.get_github_token(session=session, user=current_user)
    headers = {"Authorization": f"Bearer {token}"}
    repo_html_url = f"https://github.com/{owner_name}/{repo_name}"
    repo_api_url = f"https://api.github.com/repos/{owner_name}/{repo_name}"
    resp = requests.get(repo_api_url, headers=headers)
    # Check if the repo is already associated with a project
    query = select(Project).where(Project.git_repo_url == repo_html_url)
    project = session.exec(query).first()
    git_repo_url_is_occupied = project is not None
    if git_repo_url_is_occupied:
        logger.info("Git repo is already occupied by another project")
        raise HTTPException(409, "Repos can only be associated with 1 project")
    elif resp.status_code == 404:
        if project_in.git_repo_exists:
            raise HTTPException(404, "GitHub repo not found")
        # If not owned, create it
        logger.info(f"Creating GitHub repo for {owner_name}: {repo_name}")
        body = {
            "name": repo_name,
            "description": project_in.description,
            "homepage": (
                f"{settings.frontend_host}/{owner_name}/{project_in.name}"
            ),
            "private": not project_in.is_public,
            "has_discussions": True,
            "has_issues": True,
            "has_wiki": True,
        }
        # If creating from a template repo, we want it to be empty
        if project_in.template is None:
            body["gitignore_template"] = "Python"
        if is_user_org:
            post_url = f"https://api.github.com/orgs/{owner_name}/repos"
        else:
            post_url = "https://api.github.com/user/repos"
        resp = requests.post(post_url, json=body, headers=headers)
        if not resp.status_code == 201:
            not_installed_message = (
                "Calkit GitHub App not enabled for this account or repo."
            )
            logger.warning(f"Failed to create: {resp.json()}")
            try:
                message = resp.json()["errors"][0]["message"].capitalize()
                if message.lower().startswith("name already exists"):
                    message = not_installed_message
            except Exception:
                try:
                    message = resp.json()["message"]
                    if message.lower().startswith("resource not accessible"):
                        message = not_installed_message
                except Exception:
                    message = "Failed to create GitHub repo"
            raise HTTPException(resp.status_code, message)
        resp_json = resp.json()
        logger.info(f"Created GitHub repo with URL: {resp_json['html_url']}")
        # If this is an org, we need to get it's account ID
        if is_user_org:
            owner_org = orgs.get_org_by_github_name(
                session=session, github_name=owner_name
            )
            if owner_org is None:
                raise HTTPException(400, "Org not found")
            owner_account_id = owner_org.account.id
        else:
            owner_account_id = current_user.account.id
        add_info = {"owner_account_id": owner_account_id}
        if project_in.template is not None:
            add_info["parent_project_id"] = template_project.id
        project = Project.model_validate(project_in, update=add_info)
        logger.info("Adding project to database")
        session.add(project)
        session.commit()
        session.refresh(project)
        try:
            # Clone the repo and set up the Calkit DVC remote
            repo = get_repo(
                project=project,
                session=session,
                user=current_user,
                fresh=True,
            )
            # If we have a template, set as upstream and pull from it
            if project_in.template is not None:
                template_git_repo_url = template_project.git_repo_url
                repo.git.remote(["add", "upstream", template_git_repo_url])
                repo.git.pull(["upstream", repo.active_branch.name])
                # Remove upstream remote so we don't have any confusion later
                repo.git.remote(["remove", "upstream"])
                template_repo = get_repo(
                    project=template_project,
                    session=session,
                    user=current_user,
                    fresh=True,
                )
                # Delete files that don't belong in a template
                delete_files = ["dvc.lock"]
                for f in delete_files:
                    if os.path.isfile(os.path.join(repo.working_dir, f)):
                        repo.git.rm(f, "-f")
            # Add a calkit.yaml file
            # First existing info, which is empty unless we're using a template
            ck_info = calkit.load_calkit_info(wdir=repo.working_dir)  # type: ignore
            _ = ck_info.pop("questions", None)
            ck_info |= {
                "owner": owner_name,
                "name": project.name,
                "title": project.title,
                "description": project.description,
                # The hub this project belongs to; makes bare ck:// paths
                # resolvable against a known instance
                "hub": settings.frontend_host,
                "git_repo_url": project.git_repo_url,
            }
            if project_in.template is not None:
                ck_info["derived_from"] = dict(
                    project=project_in.template,
                    git_repo_url=template_git_repo_url,
                    git_rev=template_repo.git.rev_parse("HEAD"),
                )
            with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
                ryaml.dump(ck_info, f)
            repo.git.add("calkit.yaml")
            if project_in.template is None:
                # Create devcontainer spec
                dc_url = (
                    "https://raw.githubusercontent.com/calkit/devcontainer/"
                    "refs/heads/main/devcontainer.json"
                )
                # A dev container spec is a nice-to-have, and can be added
                # later with the dev container endpoint, so don't fail project
                # creation if GitHub is slow or the file has moved. Writing a
                # non-200 body would put an error page in devcontainer.json.
                try:
                    dc_resp = requests.get(dc_url, timeout=15)
                    dc_resp.raise_for_status()
                except requests.RequestException as e:
                    logger.warning(f"Failed to fetch dev container spec: {e}")
                    dc_resp = None
                if dc_resp is not None:
                    dc_dir = os.path.join(repo.working_dir, ".devcontainer")
                    os.makedirs(dc_dir, exist_ok=True)
                    dc_fpath = os.path.join(dc_dir, "devcontainer.json")
                    with open(dc_fpath, "w") as f:
                        f.write(dc_resp.text)
                    repo.git.add(".devcontainer")
            # Create the README
            logger.info("Creating README.md")
            with open(os.path.join(repo.working_dir, "README.md"), "w") as f:
                txt = f"# {project_in.title}\n\n"
                if project_in.description is not None:
                    txt += f"\n{project_in.description}\n"
                f.write(txt)
            repo.git.add("README.md")
            # Setup the DVC remote
            logger.info("Running DVC init")
            run_dvc_command(
                ["init", "--force", "-q"],
                wdir=str(repo.working_dir),
                check=True,
            )
            logger.info("Enabling DVC autostage")
            run_dvc_command(
                ["config", "core.autostage", "true"],
                wdir=str(repo.working_dir),
                check=True,
            )
            logger.info("Setting up default DVC remote")
            calkit.dvc.configure_remote(
                wdir=str(repo.working_dir), use_ck=True
            )
            repo.git.add(".dvc")
            if project_in.template is not None:
                commit_msg = f"Create new project from {project_in.template}"
            else:
                commit_msg = "Create README.md, DVC config, and calkit.yaml"
            repo.git.commit(["-m", commit_msg])
            repo.git.push(["origin", repo.active_branch.name])
        except Exception as e:
            # The project row is already committed, and it would block a retry
            # since a Git repo can only back one project, so remove it and let
            # the user try again with the repo that was created on GitHub.
            logger.exception(f"Failed to set up repo for new project: {e}")
            session.rollback()
            session.delete(project)
            session.commit()
            if isinstance(e, (HTTPException, GitCommandError)):
                raise
            raise HTTPException(
                500,
                (
                    "Failed to set up the project repo. The GitHub repo was "
                    "created, so try creating the project again as an "
                    "existing repo."
                ),
            )
    # Repo exists on GitHub
    elif resp.status_code == 200:
        logger.info(f"Repo exists on GitHub as {owner_name}/{repo_name}")
        if not project_in.git_repo_exists:
            raise HTTPException(400, "GitHub repo already exists")
        if project_in.template is not None:
            raise HTTPException(
                400, "Templates can only be used with new repos"
            )
        repo = resp.json()
        if owner_name != current_user.github_username:
            # This is either an org repo, or someone else's that we shouldn't
            # be able to import
            if repo["owner"]["type"] != "Organization":
                raise HTTPException(400, "Non-user repos must be from an org")
            # This org must exist in Calkit and the user must have access to it
            # First check if this org exists in Calkit and try to create it
            # if it doesn't
            org = orgs.get_org_by_github_name(
                session=session, github_name=owner_name
            )
            if org is None:
                logger.info(f"Org '{owner_name}' does not exist in DB")
                # Try to create the org
                post_org(
                    req=OrgPost(github_name=owner_name),
                    session=session,
                    current_user=current_user,
                )
                org = orgs.get_org_by_github_name(
                    session=session, github_name=owner_name
                )
            assert isinstance(org, Org)
            account_id = org.account.id
            subscription = org.subscription
            if subscription is None:
                logger.info(f"Org '{owner_name}' does not have a subscription")
                # Give the org a free subscription
                org.subscription = OrgSubscription(
                    plan_id=0,
                    n_users=1,
                    price=0.0,
                    period_months=1,
                    subscriber_user_id=current_user.id,
                    org_id=org.id,
                )
                session.add(org.subscription)
                session.commit()
                session.refresh(org.subscription)
                subscription = org.subscription
            # Check access to the org
            role = None
            for membership in current_user.org_memberships:
                if membership.org.account.name.lower() == owner_name.lower():
                    role = membership.role_name
            # TODO: If we have no role defined, check on GitHub
            if role not in ["owner", "admin"]:
                logger.info("User is not an admin or owner of this org")
                raise HTTPException(
                    403,
                    (
                        "Must be an owner or admin of an org to create "
                        "projects for it"
                    ),
                )
            owner_account_id = org.account.id
        else:
            owner_account_id = current_user.account.id
        # Make public visibility match that on GitHub
        project_in.is_public = not repo.get("private", True)
        if not project_in.description:
            project_in.description = repo.get("description", None)
        project = Project.model_validate(
            project_in, update={"owner_account_id": owner_account_id}
        )
        logger.info("Adding project to database")
        session.add(project)
        session.commit()
        session.refresh(project)
    return project  # type: ignore


class ProjectOptionalExtended(ProjectPublic):
    calkit_info_keys: list[str] | None = None
    readme_content: str | None = None


@router.get("/projects/{owner_name}/{project_name}")
def get_project(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
    get_extended_info: bool = False,
    ref: str | None = None,
) -> ProjectOptionalExtended:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    resp = ProjectOptionalExtended.model_validate(project)
    # Get some more information about the project, e.g., its status, what
    # attributes are defined in calkit.yaml, its README content, questions,
    # etc., so we don't need to make other calls for these?
    if get_extended_info:
        logger.info(f"Getting extended info for {owner_name}/{project_name}")
        repo = get_repo(
            project=project,
            user=current_user,
            session=session,
            ttl=DEFAULT_REPO_TTL,
            ref=ref,
        )
        # Read at the requested ref. get_repo only fetches a ref, it does
        # not check it out, so get_ck_info_from_repo (working tree) would
        # report the default branch's calkit.yaml keys instead.
        ck_info = app.projects.get_ck_info_for_ref(
            project=project, repo=repo, ref=ref
        )
        resp.calkit_info_keys = list(ck_info.keys())
        # Read status if present
        status_fpath = os.path.join(repo.working_dir, ".calkit", "status.csv")
        if os.path.isfile(status_fpath):
            logger.info("Reading latest status")
            last_line = app.read_last_line_from_csv(status_fpath)
            if len(last_line) >= 3:
                # Insert status into database so it can be searched on
                logger.info("Updating status in database")
                updated = last_line[0]
                status = last_line[1]
                message = last_line[2]
                project.status = status
                project.status_updated = updated
                project.status_message = message
                session.commit()
                # TODO: Detect the Git email used to create the status?
    return resp


class ProjectPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    is_public: bool | None = None


@router.patch("/projects/{owner_name}/{project_name}")
def patch_project(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUser,
    req: ProjectPatch,
) -> ProjectPublic:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    if req.title is not None:
        project.title = req.title
    project.description = req.description
    if req.is_public is not None:
        project.is_public = req.is_public
        visibility = "public" if req.is_public else "private"
        # Make call to GitHub API to change repo visibility
        gh_owner, gh_repo = project.git_repo_url.split("/")[-2:]
        url = f"https://api.github.com/repos/{gh_owner}/{gh_repo}"
        token = users.get_github_token(session=session, user=current_user)
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.patch(
            url,
            json={"visibility": visibility},
            headers=headers,
        )
        if resp.status_code != 200:
            logger.warning(
                "Failed to change repo visibility for "
                f"{owner_name}/{project_name}: {resp.text}"
            )
            raise HTTPException(
                resp.status_code, "Failed to change GitHub repo visibility"
            )
    session.commit()
    session.refresh(project)
    return ProjectPublic.model_validate(project)


@router.delete("/projects/{owner_name}/{project_name}")
def delete_project(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="owner",
    )
    session.delete(project)
    session.commit()
    return Message(message="success")


@router.delete("/projects/{project_id}")
def delete_project_by_id(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404)
    # TODO: Check for collaborator access
    if project.owner != current_user:
        raise HTTPException(403)
    session.delete(project)
    session.commit()
    return Message(message="success")


@router.get("/projects/{owner_name}/{project_name}/git/repo")
def get_project_git_repo(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict:
    token = users.get_github_token(session=session, user=current_user)
    project = get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
    )
    repo_name = project.git_repo_url.removeprefix("https://github.com/")
    resp = requests.get(
        f"https://api.github.com/repos/{repo_name}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()


class GitRemoteHead(BaseModel):
    branch: str
    sha: str | None


@router.get("/projects/{owner_name}/{project_name}/git/remote-head")
def get_project_git_remote_head(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUser,
    branch: str | None = None,
) -> GitRemoteHead:
    """Return origin's current HEAD commit SHA for a branch.

    Lets the LaTeX editor detect that someone else has pushed (concurrent
    editing) by polling, without pulling or resetting the working tree. Uses
    ``git ls-remote`` (a cheap live query) on the cached clone, reusing its auth.
    """
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=FULL_HISTORY_REPO_TTL,
    )
    branch_name = branch or repo.active_branch.name
    try:
        out = repo.git.ls_remote(["origin", branch_name])
    except GitCommandError:
        out = ""
    sha = out.split()[0].strip() if out.strip() else None
    return GitRemoteHead(branch=branch_name, sha=sha)


@router.get("/projects/{owner_name}/{project_name}/git/refs")
def search_project_refs(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
    q: Optional[str] = Query(None, description="Search query for refs"),
) -> list[GitRef]:
    """Get git refs (branches, tags, commits) in a project.

    Parameters
    ----------
    owner_name:
        Owner of the project.
    project_name:
        Name of the project.
    q:
        Optional search query to filter refs by branch name, tag name,
        commit message, or author.

    Returns
    -------
    list[GitRef]
        List of matching GitRef objects with name, kind, message, author,
        timestamp.
    """
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=FULL_HISTORY_REPO_TTL,
    )
    refs = search_refs(repo, query=q)
    return cast(list[GitRef], refs)


@router.get("/projects/{owner_name}/{project_name}/git/history")
def get_project_history(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
    limit: int = Query(
        50, le=200, description="Max number of commits to return"
    ),
    offset: int = Query(0, description="Number of commits to skip"),
    ref: Optional[str] = Query(
        None, description="Branch, tag, or commit to read history from"
    ),
) -> list[dict]:
    """Get paginated git commit history for a project.

    Parameters
    ----------
    limit:
        Maximum number of commits to return.
    offset:
        Number of commits to skip from the newest commit.
    ref:
        Optional branch, tag, or commit to read history from.
    """
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=FULL_HISTORY_REPO_TTL,
    )
    history = get_commit_history(repo, max_count=limit + offset, ref=ref)
    return history[offset : offset + limit]


@router.get("/projects/{owner_name}/{project_name}/git/commits/{commit_hash}")
def get_project_commit(
    owner_name: str,
    project_name: str,
    commit_hash: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
) -> dict:
    """Get details for a specific commit including changed files.

    Parameters
    ----------
    commit_hash:
        Full or short commit hash to inspect.
    """
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=FULL_HISTORY_REPO_TTL,
    )
    try:
        commit = repo.commit(commit_hash)
    except Exception:
        raise HTTPException(404, "Commit not found")
    # Cap response size so a single giant commit (e.g., a large generated
    # file or a wide merge) can't balloon memory or the JSON payload.
    MAX_FILES = 500
    MAX_PATCH_BYTES = 100_000
    changed_files: list[dict] = []
    files_truncated = False
    if commit.parents:
        parent = commit.parents[0]
        diff = parent.diff(commit, create_patch=True)
        for d in diff:
            if len(changed_files) >= MAX_FILES:
                files_truncated = True
                break
            change_type = d.change_type  # A, D, M, R, etc.
            patch_bytes = d.diff if d.diff else b""
            if not isinstance(patch_bytes, bytes):
                patch_bytes = str(patch_bytes).encode(
                    "utf-8", errors="replace"
                )
            # Binary files: skip decoding the patch entirely.
            is_binary = b"\x00" in patch_bytes[:8192]
            patch_truncated = False
            if is_binary:
                patch = None
            else:
                if len(patch_bytes) > MAX_PATCH_BYTES:
                    patch_bytes = patch_bytes[:MAX_PATCH_BYTES]
                    patch_truncated = True
                patch = patch_bytes.decode("utf-8", errors="replace")
            if patch is None:
                insertions = None
                deletions = None
            else:
                insertions = sum(
                    1
                    for line in patch.splitlines()
                    if line.startswith("+") and not line.startswith("+++")
                )
                deletions = sum(
                    1
                    for line in patch.splitlines()
                    if line.startswith("-") and not line.startswith("---")
                )
            changed_files.append(
                {
                    "path": d.b_path or d.a_path,
                    "old_path": d.a_path if change_type == "R" else None,
                    "change_type": change_type,
                    "insertions": insertions,
                    "deletions": deletions,
                    "patch": patch,
                    "is_binary": is_binary,
                    "patch_truncated": patch_truncated,
                }
            )
    else:
        # Initial commit--list all files
        for item in commit.tree.traverse():
            if len(changed_files) >= MAX_FILES:
                files_truncated = True
                break
            if item.type == "blob":  # type: ignore[union-attr]
                changed_files.append(
                    {
                        "path": item.path,  # type: ignore[union-attr]
                        "old_path": None,
                        "change_type": "A",
                        "insertions": None,
                        "deletions": None,
                        "patch": None,
                        "is_binary": False,
                        "patch_truncated": False,
                    }
                )
    message = (
        commit.message
        if isinstance(commit.message, str)
        else bytes(commit.message).decode("utf-8", errors="replace")
    )
    return {
        "hash": commit.hexsha,
        "short_hash": commit.hexsha[:7],
        "message": message,
        "summary": message.split("\n")[0],
        "author": commit.author.name,
        "author_email": commit.author.email,
        "timestamp": commit.committed_datetime.isoformat(),
        "parent_hashes": [p.hexsha[:7] for p in commit.parents],
        "changed_files": changed_files,
        "files_truncated": files_truncated,
    }


@router.get("/projects/{owner_name}/{project_name}/git/file-history")
def get_project_file_history(
    owner_name: str,
    project_name: str,
    path: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
    limit: int = Query(
        100, le=200, description="Max number of commits to return"
    ),
    storage: Optional[Literal["git", "dvc", "dvc-zip"]] = Query(
        None,
        description=(
            "Artifact storage class; when supplied, limits the lookup to "
            "relevant sources (e.g., skips the dvc.lock scan for git files)."
        ),
    ),
) -> list[dict]:
    """Get git commit history for a specific file path.

    Returns commits that touched the file directly, its DVC pointer (.dvc),
    or dvc.lock (for pipeline outputs), so DVC-tracked artifacts are covered.
    Pass ``storage`` when the caller knows the artifact's storage class so
    irrelevant lookups are skipped.
    """
    # Prevent path traversal
    if os.path.isabs(path):
        raise HTTPException(400, "Absolute paths are not allowed")
    if ".." in path.split(os.sep):
        raise HTTPException(400, "Path traversal is not allowed")
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=FULL_HISTORY_REPO_TTL,
    )
    return get_file_history(repo, path=path, max_count=limit, storage=storage)


class GitItem(BaseModel):
    name: str
    path: str
    sha: str
    size: int
    url: str
    html_url: str
    git_url: str
    download_url: str | None
    type: str


class GitItemWithContents(GitItem):
    encoding: str
    content: str


@router.get("/projects/{owner_name}/{project_name}/git/contents/{path:path}")
@router.get("/projects/{owner_name}/{project_name}/git/contents")
def get_project_git_contents(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUser,
    path: str | None = None,
    astype: Literal["", ".raw", ".html", ".object"] = "",
    ref: str | None = None,
) -> list[GitItem] | GitItemWithContents | str:
    app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    token = users.get_github_token(session=session, user=current_user)
    url = f"https://api.github.com/repos/{owner_name}/{project_name}/contents"
    if path is not None:
        url += "/" + path
    logger.info(f"Making request to: {url}")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": f"application/vnd.github{astype}+json",
    }
    params = {"ref": ref} if ref is not None else None
    resp = requests.get(url, headers=headers, params=params)
    logger.info(f"Response status code from GitHub: {resp.status_code}")
    if resp.status_code >= 400:
        logger.info(f"GitHub API call failed: {resp.text}")
        if astype in ["", ".object"]:
            raise HTTPException(resp.status_code, resp.json()["message"])
    if astype in ["", ".object"]:
        return resp.json()
    else:
        return resp.text


@router.get("/projects/{owner_name}/{project_name}/contents/{path:path}")
@router.get("/projects/{owner_name}/{project_name}/contents")
def get_project_contents(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
    path: str | None = None,
    ttl: int | None = DEFAULT_REPO_TTL,
    ref: str | None = None,
) -> ContentsItem:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    # Get the repo
    # TODO: Stop using a TTL and rely on latest commit hash
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=ttl,
        ref=ref,
    )
    return app.projects.get_contents_from_repo(
        project=project,
        repo=repo,
        path=path,
        ref=ref,
    )


class DvcOutput(BaseModel):
    """A DVC-tracked output as it stands at one Git ref."""

    path: str
    name: str
    type: str = "file"
    size: int | None = None
    md5: str | None = None
    storage: str = "dvc"
    # Presigned, and specific to this ref's version of the artifact. None
    # when the object was never pushed to storage, or for a directory.
    url: str | None = None


@router.get("/projects/{owner_name}/{project_name}/dvc-outputs")
def get_project_dvc_outputs(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
    ref: str | None = None,
    ttl: int | None = DEFAULT_REPO_TTL,
) -> list[DvcOutput]:
    """List every DVC-tracked output in the project at a given ref.

    The contents endpoint lists one directory at a time, and only
    presigns a URL when asked for a single path. Comparing two refs --
    a pull request against its base -- would mean walking the whole tree
    twice and then fetching each artifact individually, so the whole set
    comes back here at once, each with the URL of that ref's version.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=ttl,
        ref=ref,
    )
    tree = app.projects.get_repo_tree_for_ref(repo, ref)
    outs = app.projects.dvc_outputs_from_tree(project=project, tree=tree)
    zip_path_map = app.projects.get_ck_info_and_dvc_outs_from_tree(
        project=project, tree=tree
    ).zip_path_map
    fs = get_object_fs()
    resp = []
    for path, out in sorted(outs.items()):
        md5 = out.get("md5") or ""
        is_dir = out.get("type") == "dir" or md5.endswith(".dir")
        url = None
        if md5 and not is_dir:
            fpath = get_data_fpath_for_md5(
                owner_name=project.owner_account_name,
                project_name=project.name,
                md5=md5,
                fs=fs,
            )
            if fpath is not None:
                url = get_object_url(
                    fpath, fname=os.path.basename(path), fs=fs
                )
        resp.append(
            DvcOutput(
                path=path,
                name=os.path.basename(path),
                type="dir" if is_dir else "file",
                size=out.get("size"),
                md5=md5 or None,
                storage="dvc-zip" if path in zip_path_map else "dvc",
                url=url,
            )
        )
    return resp


@router.get("/projects/{owner_name}/{project_name}/dvc-outputs/text-diff")
def get_project_dvc_output_text_diff(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
    path: str,
    base: str,
    head: str,
    ttl: int | None = DEFAULT_REPO_TTL,
) -> pdftext.TextDiff:
    """Compare the words in a PDF output at two refs.

    Looking at two builds of a paper side by side answers "did the
    figures move" well and "did the wording change" badly. This reads the
    text out of both and diffs it, which the browser can't do without
    shipping a PDF parser.
    """
    if not path.lower().endswith(".pdf"):
        raise HTTPException(422, "Only PDFs can be compared as text")
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    fs = get_object_fs()

    def read(ref: str) -> tuple[str, bool]:
        repo = get_repo(
            project=project,
            user=current_user,
            session=session,
            ttl=ttl,
            ref=ref,
        )
        tree = app.projects.get_repo_tree_for_ref(repo, ref)
        outs = app.projects.dvc_outputs_from_tree(project=project, tree=tree)
        out = outs.get(path)
        if out is None or not out.get("md5"):
            raise HTTPException(404, f"'{path}' is not DVC-tracked at {ref}")
        size = out.get("size")
        if size is not None and size > pdftext.MAX_PDF_BYTES:
            raise HTTPException(413, f"'{path}' is too large to compare")
        fpath = get_data_fpath_for_md5(
            owner_name=project.owner_account_name,
            project_name=project.name,
            md5=out["md5"],
            fs=fs,
        )
        if fpath is None:
            raise HTTPException(
                404, f"'{path}' has not been pushed to storage at {ref}"
            )
        with fs.open(fpath, "rb") as f:
            data = f.read(pdftext.MAX_PDF_BYTES + 1)
        if len(data) > pdftext.MAX_PDF_BYTES:
            raise HTTPException(413, f"'{path}' is too large to compare")
        try:
            return pdftext.extract_text(data)
        except Exception as e:
            logger.warning(f"Failed to read text from {path} at {ref}: {e}")
            raise HTTPException(422, f"Could not read the text of '{path}'")

    base_text, base_truncated = read(base)
    head_text, head_truncated = read(head)
    diff = pdftext.diff(
        base=base_text,
        head=head_text,
        path=path,
        base_ref=base,
        head_ref=head,
    )
    diff.truncated = base_truncated or head_truncated
    return diff


@router.get("/projects/{owner_name}/{project_name}/contents-paths")
def get_project_content_paths(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
    ref: str | None = None,
    ttl: int | None = DEFAULT_REPO_TTL,
) -> list[str]:
    """Flat list of all selectable file paths in the project.

    Powers fuzzy path search (e.g., the release path picker) without walking the
    tree one directory at a time. Includes Git-tracked files and DVC-tracked
    outputs, preferring an output's real path over its ``.dvc`` pointer file.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=ttl, ref=ref
    )
    tree = app.projects.get_repo_tree_for_ref(repo, ref)
    dvc_lock_outs = app.projects.get_ck_info_and_dvc_outs_from_tree(
        project=project, tree=tree
    ).dvc_lock_outs
    dvc_files = {
        p for p, obj in dvc_lock_outs.items() if obj.get("type") != "dir"
    }
    paths = set(dvc_files)
    for f in repo.git.ls_files().split("\n"):
        if not f or f.startswith(".dvc/"):
            continue
        # Prefer a DVC output's real path over its tracked ``.dvc`` pointer.
        if f.endswith(".dvc") and f[:-4] in dvc_files:
            continue
        paths.add(f)
    return sorted(paths)


def _valid_file_size(content_length: int = Header(lt=1_000_000)):
    """Check content length header.

    From https://github.com/fastapi/fastapi/issues/362#issuecomment-584104025
    """
    return content_length


@router.put(
    "/projects/{owner_name}/{project_name}/contents/{path:path}",
    dependencies=[Depends(_valid_file_size)],
)
def put_project_contents(
    owner_name: str,
    project_name: str,
    path: str,
    file: Annotated[UploadFile, File()],
    session: SessionDep,
    current_user: CurrentUser,
    message: Annotated[str | None, Form()] = None,
) -> ContentsItem:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    locked_paths = [lock.path for lock in project.file_locks]
    if path in locked_paths:
        raise HTTPException(400, "Path is currently locked")
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    dirname = os.path.dirname(path)
    os.makedirs(os.path.join(repo.working_dir, dirname), exist_ok=True)
    with open(os.path.join(repo.working_dir, path), "wb") as f:
        f.write(file.file.read())
    repo.git.add(path)
    if repo.git.diff(["--staged", path]):
        commit_message = message or f"Upload {path} from web"
        repo.git.commit(["-m", commit_message])
        repo.git.push(["origin", repo.active_branch.name])
    else:
        raise HTTPException(
            400,
            (
                "File is either not different or ignored by Git "
                "and/or tracked in DVC"
            ),
        )
    return ContentsItem(
        name=os.path.basename(path),
        path=path,
        type="file",
        size=os.path.getsize(os.path.join(repo.working_dir, path)),
        in_repo=True,
    )


class ContentPatch(BaseModel):
    kind: (
        Literal[
            "figure", "dataset", "publication", "environment", "references"
        ]
        | None
    )
    attrs: dict = {}


@router.patch("/projects/{owner_name}/{project_name}/contents/{path:path}")
def patch_project_contents(
    owner_name: str,
    project_name: str,
    path: str,
    req: ContentPatch,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict | None:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    if "path" in req.attrs:
        raise HTTPException(501, "Object path change not supported")
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    ck_fpath = os.path.join(repo.working_dir, "calkit.yaml")
    if os.path.isfile(ck_fpath):
        with open(ck_fpath) as f:
            ck_info = ryaml.load(f)
    else:
        ck_info = {}
    # See if this path exists in any category, in case we are going to change
    # its category
    current_category = None
    current_object = None
    current_index = None
    updated = False
    for category, objlist in ck_info.items():
        if not isinstance(objlist, list):
            continue
        for obj in objlist:
            # TODO: We need a better way to say which categories have objects
            # with paths
            if not isinstance(obj, dict):
                continue
            if obj["path"] == path:
                current_category = category
                current_category_singular = CATEGORIES_PLURAL_TO_SINGULAR[
                    current_category
                ]
                current_index = objlist.index(obj)
                # If we're not changing categories, we can update in place
                if req.kind == current_category_singular:
                    obj |= req.attrs
                    current_object = obj
                    updated = True
                else:
                    current_object = objlist.pop(current_index)
                break
    if not updated and req.kind is not None:
        if current_object is None:
            current_object = dict(path=path)
        current_object |= req.attrs
        target_category = CATEGORIES_SINGULAR_TO_PLURAL[req.kind]
        if target_category in ck_info:
            ck_info[target_category].append(current_object)
        else:
            ck_info[target_category] = [current_object]
    # Now it's time to write and commit
    with open(ck_fpath, "w") as f:
        ryaml.dump(ck_info, f)
    git_diff = repo.git.diff("calkit.yaml")
    if not git_diff:
        logger.info("No changes to calkit.yaml detected")
        return current_object
    logger.info("Adding and committing changes to calkit.yaml")
    repo.git.add("calkit.yaml")
    if req.kind is None:
        message = f"Remove {path} from {current_category}"
    elif updated:
        message = f"Update {current_category_singular} {path}"
    else:
        message = f"Add {path} to {target_category}"
    repo.git.commit(["-m", message])
    logger.info("Pushing Git repo")
    repo.git.push(["origin", repo.branches[0].name])
    return current_object


def _extract_question_text(question: str | dict) -> str:
    """Extract the question text from a calkit.yaml question entry.

    A question may be a plain string or an object with a ``question`` field.
    Any other/unexpected type (e.g. a list) yields an empty string rather than
    a coerced repr, so a non-string never reaches the DB model's ``question``
    field (and the empty text signals to the user that something is off).
    """
    if isinstance(question, dict):
        value = question.get("question", "")
    else:
        value = question
    return value if isinstance(value, str) else ""


def _sync_questions_with_db(
    ck_info: dict, project: Project, session: Session
) -> Project:
    questions_ck = list(ck_info.get("questions", []))
    questions = deepcopy(questions_ck)
    logger.info(f"Found {len(questions)} questions in Calkit info")
    # Put these in the database idempotently
    existing_questions = project.questions
    logger.info(f"Found {len(existing_questions)} existing questions in DB")
    for n, (new, existing) in enumerate(zip(questions_ck, existing_questions)):
        logger.info(f"Updating existing question number {n + 1}")
        existing.question = _extract_question_text(questions.pop(0))
        existing.number = n + 1  # Should already be done, but just in case
    start_number = len(existing_questions) + 1
    logger.info(f"Adding {len(questions)} new questions to DB")
    for n, new in enumerate(questions):
        number = start_number + n
        logger.info(f"Appending new question with number: {number}")
        project.questions.append(
            Question(
                project_id=project.id,
                number=number,
                question=_extract_question_text(new),
            )
        )
    # Delete extra questions in DB
    while len(project.questions) > len(questions_ck):
        q = project.questions.pop(-1)
        logger.info(f"Deleting question number {q.number}")
        session.delete(q)
    session.commit()
    session.refresh(project)
    return project


def _resolve_result_value(
    project: Project,
    repo: git.Repo,
    ref: str | None,
    path: str,
    key: str,
    cache: dict[str, dict | None],
) -> str | None:
    """Read a result file and return the value at ``key`` as a string.

    Supports JSON and YAML result files and dot-separated nested keys (e.g.
    ``metrics.mean``). ``cache`` memoizes parsed files across evidence items.
    Returns None if the file or key cannot be resolved.
    """
    if path not in cache:
        data: dict | None = None
        try:
            item = app.projects.get_contents_from_repo(
                project=project, repo=repo, path=path, ref=ref
            )
            if item.content is not None:
                text = base64.b64decode(item.content).decode("utf-8")
                lower = path.lower()
                if lower.endswith(".json"):
                    data = json.loads(text)
                elif lower.endswith((".yaml", ".yml")):
                    data = ryaml.load(text)
        except Exception as e:
            logger.warning(f"Failed to read result {path}: {e}")
        cache[path] = data if isinstance(data, dict) else None
    data = cache[path]
    if data is None:
        return None
    value: object = data
    for part in key.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    if isinstance(value, (dict, list)):
        return None
    return str(value)


def _build_question_evidence(
    project: Project,
    repo: git.Repo,
    ref: str | None,
    evidence_ck: list,
    figures_by_path: dict[str, Figure],
    results_by_path: dict[str, Result],
    publications_by_path: dict[str, Publication],
    result_value_cache: dict[str, dict | None],
) -> list[QuestionEvidence]:
    """Turn calkit.yaml evidence entries into resolved QuestionEvidence."""
    evidence = []
    for ev in evidence_ck:
        if not isinstance(ev, dict) or ev.get("kind") not in (
            "figure",
            "result",
            "publication",
        ):
            continue
        path = ev.get("path", "")
        item = QuestionEvidence(
            kind=ev["kind"],
            path=path,
            key=ev.get("key"),
            explanation=ev.get("explanation"),
        )
        if item.kind == "figure":
            item.figure = figures_by_path.get(path)
        elif item.kind == "publication":
            item.publication = publications_by_path.get(path)
        else:
            item.result = results_by_path.get(path)
            if item.key:
                item.value = _resolve_result_value(
                    project=project,
                    repo=repo,
                    ref=ref,
                    path=path,
                    key=item.key,
                    cache=result_value_cache,
                )
        evidence.append(item)
    return evidence


def _build_questions_public(
    project: Project,
    repo: git.Repo,
    session: Session,
    ref: str | None,
    ck_info: dict,
) -> list[QuestionPublic]:
    """Merge synced DB questions (for id/number) with the richer calkit.yaml
    question objects, resolving any figure/result evidence.
    """
    questions_ck = ck_info.get("questions", [])

    def _evidence_of(q: str | dict) -> list:
        return q.get("evidence") or [] if isinstance(q, dict) else []

    kinds = {
        ev.get("kind")
        for q in questions_ck
        for ev in _evidence_of(q)
        if isinstance(ev, dict)
    }
    figures_by_path: dict[str, Figure] = {}
    if "figure" in kinds:
        # Only the figures actually cited as evidence need their content
        # resolved; resolving every figure in the project would make this
        # scale with the project rather than with the questions.
        evidence_fig_paths = {
            ev.get("path")
            for q in questions_ck
            for ev in _evidence_of(q)
            if isinstance(ev, dict) and ev.get("kind") == "figure"
        }
        fig_ctx = _discover_figures(project=project, repo=repo, ref=ref)
        cited = [f for f in fig_ctx.figures if f["path"] in evidence_fig_paths]
        figures_by_path = {
            fig.path: fig
            for fig in _resolve_figures(
                project=project,
                repo=repo,
                session=session,
                ref=ref,
                ctx=fig_ctx,
                figures=cited,
            )
        }
    results_by_path: dict[str, Result] = {}
    if "result" in kinds:
        results_by_path = {
            res.path: res
            for res in _build_results(project=project, repo=repo, ref=ref)
        }
    publications_by_path: dict[str, Publication] = {}
    if "publication" in kinds:
        publications_by_path = {
            pub.path: pub
            for pub in _build_publications(project=project, repo=repo, ref=ref)
        }
    db_questions = sorted(project.questions, key=lambda q: q.number)
    result_value_cache: dict[str, dict | None] = {}
    questions_public = []
    for q_ck, q_db in zip(questions_ck, db_questions):
        hypothesis = q_ck.get("hypothesis") if isinstance(q_ck, dict) else None
        answer = q_ck.get("answer") if isinstance(q_ck, dict) else None
        evidence = _build_question_evidence(
            project=project,
            repo=repo,
            ref=ref,
            evidence_ck=_evidence_of(q_ck),
            figures_by_path=figures_by_path,
            results_by_path=results_by_path,
            publications_by_path=publications_by_path,
            result_value_cache=result_value_cache,
        )
        questions_public.append(
            QuestionPublic(
                id=q_db.id,
                project_id=q_db.project_id,
                number=q_db.number,
                question=q_db.question,
                hypothesis=hypothesis,
                answer=answer,
                evidence=evidence,
            )
        )
    return questions_public


@router.get("/projects/{owner_name}/{project_name}/questions")
def get_project_questions(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> list[QuestionPublic]:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    # Read at the requested ref. get_ck_info reads the working tree, which
    # get_repo never checks out to the ref, so it would return the default
    # branch's questions instead.
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    ck_info = app.projects.get_ck_info_for_ref(
        project=project, repo=repo, ref=ref
    )
    project = _sync_questions_with_db(
        ck_info=ck_info, project=project, session=session
    )
    # TODO: Maybe questions don't belong in the Calkit file?
    return _build_questions_public(
        project=project,
        repo=repo,
        session=session,
        ref=ref,
        ck_info=ck_info,
    )


class QuestionPost(BaseModel):
    question: str


@router.post("/projects/{owner_name}/{project_name}/questions")
def post_project_question(
    owner_name: str,
    project_name: str,
    req: QuestionPost,
    current_user: CurrentUser,
    session: SessionDep,
) -> Question:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    ck_info = app.projects.get_ck_info_from_repo(
        repo=repo,
        process_includes=True,
    )
    ck_questions = ck_info.get("questions", [])
    ck_questions.append(req.question)
    ck_info["questions"] = ck_questions
    with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    repo.git.commit(["-m", "Add question"])
    repo.git.push(["origin", repo.active_branch.name])
    project = _sync_questions_with_db(
        ck_info=ck_info, project=project, session=session
    )
    return project.questions[-1]


def _apply_question_update(
    existing: str | dict, req: "QuestionPut"
) -> str | dict:
    """Apply a QuestionPut to a calkit.yaml question entry.

    Normalizes the entry to object form, sets provided fields (dropping an
    empty hypothesis/answer/evidence so calkit.yaml stays clean), and collapses
    back to a bare string when only the question text remains.
    """
    if isinstance(existing, str):
        question: dict = {"question": existing}
    elif isinstance(existing, dict):
        question = dict(existing)
    else:
        raise HTTPException(422, "Invalid question entry")
    if req.question:
        question["question"] = req.question
    if req.hypothesis:
        question["hypothesis"] = req.hypothesis
    else:
        question.pop("hypothesis", None)
    if req.answer:
        question["answer"] = req.answer
    else:
        question.pop("answer", None)
    evidence = []
    for ev in req.evidence:
        entry: dict = {"kind": ev.kind, "path": ev.path}
        if ev.kind == "result" and ev.key:
            entry["key"] = ev.key
        if ev.explanation:
            entry["explanation"] = ev.explanation
        evidence.append(entry)
    if evidence:
        question["evidence"] = evidence
    else:
        question.pop("evidence", None)
    # Collapse back to a bare string if nothing but the question text remains.
    if set(question.keys()) == {"question"}:
        return question["question"]
    return question


@router.put("/projects/{owner_name}/{project_name}/questions/{number}")
def put_project_question(
    owner_name: str,
    project_name: str,
    number: int,
    req: QuestionPut,
    current_user: CurrentUser,
    session: SessionDep,
) -> QuestionPublic:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    ck_info = app.projects.get_ck_info_from_repo(
        repo=repo,
        process_includes=True,
    )
    ck_questions = ck_info.get("questions", [])
    if number < 1 or number > len(ck_questions):
        raise HTTPException(404, "Question not found")
    idx = number - 1
    ck_questions[idx] = _apply_question_update(ck_questions[idx], req)
    ck_info["questions"] = ck_questions
    with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    if repo.is_dirty():
        repo.git.commit(["-m", f"Update question {number}"])
        repo.git.push(["origin", repo.active_branch.name])
    project = _sync_questions_with_db(
        ck_info=ck_info, project=project, session=session
    )
    return _build_questions_public(
        project=project,
        repo=repo,
        session=session,
        ref=None,
        ck_info=ck_info,
    )[idx]


class _FigureContext(NamedTuple):
    """Everything needed to resolve figure content, computed once per request.

    ``figures`` holds every discovered figure entry (declared and
    auto-detected) with only the cheap tree-derived fields filled in. The
    expensive per-figure work happens in ``_resolve_figures``.
    """

    figures: list[dict[str, Any]]
    tree: RepoTree
    ck_info_full: dict[str, Any]
    dvc_lock_outs: dict[str, Any]
    zip_path_map: dict[str, Any]
    dvc_lock: dict[str, Any]


def _discover_figures(
    project: Project,
    repo: git.Repo,
    ref: str | None,
) -> _FigureContext:
    """Find every project figure, declared and auto-detected, without
    resolving any content.

    Split out from content resolution so callers that only need a subset (a
    page of the listing, or the few figures a question cites as evidence)
    don't pay to download and base64-encode every figure in the project.
    """
    ck_info = app.projects.get_ck_info_for_ref(
        project=project,
        repo=repo,
        ref=ref,
    )
    figures = ck_info.get("figures", [])
    # Declared figures (from calkit.yaml) may omit a title; fill one in so
    # they validate against the Figure model.
    for fig in figures:
        if not fig.get("title"):
            fig["title"] = _title_from_path(fig["path"])
    declared_paths = {fig["path"] for fig in figures}

    def _maybe_add_figure(path: str) -> None:
        """Add `path` to figures if it looks like a figure and is not yet
        known.
        """
        parts = path.split("/")
        if any(p.startswith(".") for p in parts):
            return
        ext = "." + parts[-1].rsplit(".", 1)[-1] if "." in parts[-1] else ""
        dir_parts = [p.lower() for p in parts[:-1]]
        if ext.lower() in FIGURE_EXTS and any(
            d in FIGURE_DIRS for d in dir_parts
        ):
            if path not in declared_paths:
                figures.append({"path": path, "title": _title_from_path(path)})
                declared_paths.add(path)

    # Auto-detect figures from the repo tree
    try:
        commit = repo.commit(ref) if ref else repo.head.commit
        for blob in commit.tree.traverse():
            if blob.type != "blob":  # type: ignore[union-attr]
                continue
            blob_path: str = blob.path  # type: ignore[union-attr]
            _maybe_add_figure(blob_path)
            # Also detect figures stored via standalone .dvc pointer files
            # (tracked with `dvc add`, not via a DVC pipeline stage).
            if blob_path.endswith(".dvc"):
                try:
                    dvc_data = yaml.safe_load(blob.data_stream.read())  # type: ignore[union-attr]
                    outs = (
                        dvc_data.get("outs")
                        if isinstance(dvc_data, dict)
                        else None
                    )
                    out = outs[0] if isinstance(outs, list) and outs else None
                    out_path = (
                        out.get("path") if isinstance(out, dict) else None
                    )
                    if isinstance(out_path, str) and out_path:
                        actual_path = os.path.normpath(
                            os.path.join(os.path.dirname(blob_path), out_path)
                        )
                    else:
                        actual_path = blob_path[:-4]
                    if actual_path:
                        _maybe_add_figure(actual_path)
                except Exception:
                    actual_path = blob_path[:-4]
                    if actual_path:
                        _maybe_add_figure(actual_path)
    except Exception:
        pass
    # Pre-compute calkit.yaml / dvc.lock metadata once for the tree so we
    # don't re-read and re-expand on every iteration.
    tree = app.projects.get_repo_tree_for_ref(repo, ref)
    (
        ck_info_full,
        dvc_lock_outs,
        zip_path_map,
        _,
    ) = app.projects.get_ck_info_and_dvc_outs_from_tree(project, tree)
    # Also auto-detect figures from DVC lock outs (files stored with DVC)
    for dvc_path, dvc_out in dvc_lock_outs.items():
        if dvc_out.get("type") == "dir":
            continue
        _maybe_add_figure(dvc_path)
    dvc_lock: dict[str, Any] = {}
    if figures:
        try:
            if tree.is_file("dvc.lock"):
                dvc_lock = (
                    ryaml.load(tree.read_bytes("dvc.lock").decode()) or {}
                )
        except Exception as e:
            logger.warning(f"Failed to read dvc.lock for figures: {e}")
    return _FigureContext(
        figures=figures,
        tree=tree,
        ck_info_full=ck_info_full,
        dvc_lock_outs=dvc_lock_outs,
        zip_path_map=zip_path_map,
        dvc_lock=dvc_lock,
    )


def _resolve_figures(
    project: Project,
    repo: git.Repo,
    session: Session,
    ref: str | None,
    ctx: _FigureContext,
    figures: list[dict[str, Any]],
) -> list[Figure]:
    """Resolve content, comment counts and stage status for ``figures``.

    ``figures`` is normally a slice of ``ctx.figures``. Content resolution
    hits object storage once per figure, so the figures are resolved
    concurrently rather than one at a time.
    """
    if not figures:
        return []
    tree = ctx.tree
    dvc_lock = ctx.dvc_lock
    # Build comment count map from DB, restricted to the figures we're
    # actually returning.
    paths = [fig["path"] for fig in figures]
    comment_counts = dict(
        session.exec(
            select(ProjectComment.artifact_path, func.count())
            .where(
                ProjectComment.project_id == project.id,
                ProjectComment.artifact_type == "figure",
                ProjectComment.parent_id == None,  # noqa: E711
                ProjectComment.resolved == None,  # noqa: E711
                col(ProjectComment.artifact_path).in_(paths),
            )
            .group_by(ProjectComment.artifact_path)
        ).all()
    )
    # Staleness is best-effort: never let it block the figure listing.
    stage_statuses = {}
    try:
        dvc_yaml: dict[str, Any] = {}
        if tree.is_file("dvc.yaml"):
            dvc_yaml = ryaml.load(tree.read_bytes("dvc.yaml").decode()) or {}
        stage_statuses = compute_stage_statuses(
            dvc_yaml=dvc_yaml,
            dvc_lock=dvc_lock,
            tree=tree,
            owner_name=project.owner_account_name,
            project_name=project.name,
            fs=get_object_fs(),
            cache_token=resolve_commit_sha(repo, ref),
        )
    except Exception as e:
        logger.warning(f"Failed to compute pipeline status for figures: {e}")

    def _resolve(fig: dict[str, Any]) -> dict[str, Any]:
        item = app.projects.get_contents_from_tree(
            project=project,
            tree=tree,
            path=fig["path"],
            ck_info=ctx.ck_info_full,
            dvc_lock_outs=ctx.dvc_lock_outs,
            zip_path_map=ctx.zip_path_map,
        )
        fig["content"] = item.content
        fig["url"] = item.url
        fig["comment_count"] = comment_counts.get(fig["path"], 0)
        if not fig.get("stage"):
            auto_stage = find_stage_for_path(fig["path"], dvc_lock)
            if auto_stage is not None:
                fig["stage"] = auto_stage
        if fig.get("stage") and fig["stage"] in stage_statuses:
            fig["stage_status"] = stage_statuses[fig["stage"]].model_dump()
        fig["storage"] = item.storage
        return fig

    # Each figure's content is an independent download, so fan them out. The
    # cap keeps a single request from monopolizing object-storage connections.
    if len(figures) > 1:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(8, len(figures))
        ) as pool:
            resolved = list(pool.map(_resolve, figures))
    else:
        resolved = [_resolve(figures[0])]
    return [Figure.model_validate(fig) for fig in resolved]


class FiguresPage(BaseModel):
    """A page of project figures, with the total available for paging."""

    items: list[Figure]
    total: int
    limit: int
    offset: int


@router.get("/projects/{owner_name}/{project_name}/figures")
def get_project_figures(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
    limit: int = Query(
        20, ge=1, le=100, description="Max number of figures to return"
    ),
    offset: int = Query(0, ge=0, description="Number of figures to skip"),
) -> FiguresPage:
    """Get a page of the project's figures.

    Figure content is downloaded from object storage and inlined, so this is
    paginated: a project with hundreds of figures would otherwise take
    minutes and return a payload measured in hundreds of megabytes.
    """
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    ctx = _discover_figures(project=project, repo=repo, ref=ref)
    page = ctx.figures[offset : offset + limit]
    items = _resolve_figures(
        project=project,
        repo=repo,
        session=session,
        ref=ref,
        ctx=ctx,
        figures=page,
    )
    return FiguresPage(
        items=items,
        total=len(ctx.figures),
        limit=limit,
        offset=offset,
    )


def _build_results(
    project: Project,
    repo: git.Repo,
    ref: str | None,
) -> list[Result]:
    """Build the list of project results, declared and auto-detected.

    Mirrors figure auto-detection: data-like files under a results-style
    directory that aren't already figures. Results carry no base64 content.
    """
    ck_info = app.projects.get_ck_info_for_ref(
        project=project,
        repo=repo,
        ref=ref,
    )
    results = ck_info.get("results", [])
    for res in results:
        if not res.get("title"):
            res["title"] = _title_from_path(res["path"])
    declared_paths = {res["path"] for res in results}

    def _is_result_path(path: str) -> bool:
        parts = path.split("/")
        if any(p.startswith(".") for p in parts):
            return False
        name = PurePosixPath(path)
        ext = name.suffix.lower()
        dir_parts = [p.lower() for p in parts[:-1]]
        if ext not in RESULT_EXTS:
            return False
        is_figure = ext in FIGURE_EXTS and any(
            d in FIGURE_DIRS for d in dir_parts
        )
        if is_figure:
            return False
        # A data-like file under a results-style directory, or one named
        # ``results.<ext>`` anywhere (e.g. a top-level ``results.json``).
        return (
            any(d in RESULT_DIRS for d in dir_parts) or name.stem == "results"
        )

    def _maybe_add_result(path: str) -> None:
        if path not in declared_paths and _is_result_path(path):
            results.append({"path": path, "title": _title_from_path(path)})
            declared_paths.add(path)

    # Auto-detect results from the repo tree
    try:
        commit = repo.commit(ref) if ref else repo.head.commit
        for blob in commit.tree.traverse():
            if blob.type != "blob":  # type: ignore[union-attr]
                continue
            _maybe_add_result(blob.path)  # type: ignore[union-attr]
    except Exception:
        pass
    # Also auto-detect results from DVC lock outs (files stored with DVC)
    tree = app.projects.get_repo_tree_for_ref(repo, ref)
    dvc_lock_outs = app.projects.get_ck_info_and_dvc_outs_from_tree(
        project, tree
    ).dvc_lock_outs
    for dvc_path, dvc_out in dvc_lock_outs.items():
        if dvc_out.get("type") == "dir":
            continue
        _maybe_add_result(dvc_path)
    return [Result.model_validate(res) for res in results]


def _build_publications(
    project: Project,
    repo: git.Repo,
    ref: str | None,
) -> list[Publication]:
    """Build the list of declared project publications (path/title/type),
    without base64 content, for resolving question evidence.
    """
    ck_info = app.projects.get_ck_info_for_ref(
        project=project,
        repo=repo,
        ref=ref,
    )
    publications = ck_info.get("publications", [])
    for pub in publications:
        if not pub.get("title"):
            pub["title"] = _title_from_path(pub["path"])
    return [Publication.model_validate(pub) for pub in publications]


@router.get("/projects/{owner_name}/{project_name}/results")
def get_project_results(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> list[Result]:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    return _build_results(project=project, repo=repo, ref=ref)


# ``figure_path`` takes the path convertor because figures live in nested
# directories ("figures/sub/plot.png"); without it the route only matches
# single-segment names, whether or not the client percent-encodes slashes.
@router.get("/projects/{owner_name}/{project_name}/figures/{figure_path:path}")
def get_project_figure(
    owner_name: str,
    project_name: str,
    figure_path: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ttl: int | None = DEFAULT_REPO_TTL,
    ref: str | None = None,
) -> Figure:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=ttl,
        ref=ref,
    )
    return app.projects.get_figure_from_repo(
        project=project,
        repo=repo,
        path=figure_path,
        ref=ref,
    )


@router.post("/projects/{owner_name}/{project_name}/figures")
def post_project_figure(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
    path: Annotated[str, Form()],
    title: Annotated[str, Form()],
    description: Annotated[str, Form()],
    stage: Optional[Annotated[str, Form()]] = Form(None),
    file: Optional[Annotated[UploadFile, File()]] = Form(None),
) -> Figure:
    file_data: bytes | None = None
    full_fig_path: str | None = None
    if file is not None:
        logger.info(
            f"Received figure file {path} with content type: "
            f"{file.content_type}"
        )
    else:
        logger.info(f"Received request to create figure from {path}")
    if file is not None and stage is not None:
        raise HTTPException(
            400, "DVC outputs should be uploaded with `dvc push`"
        )
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    # Handle projects that aren't yet Calkit projects
    ck_fpath = os.path.join(repo.working_dir, "calkit.yaml")
    if os.path.isfile(ck_fpath):
        ck_info = ryaml.load(Path(ck_fpath))
    else:
        ck_info = {}
    figures = ck_info.get("figures", [])
    # Make sure a figure with this path doesn't already exist
    figpaths = [fig["path"] for fig in figures]
    if path in figpaths:
        raise HTTPException(400, "A figure already exists at this path")
    if file is not None:
        # Add the file to the repo(s)
        # Save the file to the desired path
        os.makedirs(
            os.path.join(repo.working_dir, os.path.dirname(path)),
            exist_ok=True,
        )
        file_data = file.file.read()
        full_fig_path = os.path.join(repo.working_dir, path)
        with open(full_fig_path, "wb") as f:
            f.write(file_data)
        # Either git add {path} or dvc add {path}
        # If we DVC add, we'll get output like
        # To track the changes with git, run:

        #         git add figures/.gitignore figures/my-figure.png.dvc

        # To enable auto staging, run:

        #         dvc config core.autostage true
        # Initialize DVC if it's never been
        if not os.path.isdir(os.path.join(repo.working_dir, ".dvc")):
            logger.info("Calling dvc init since .dvc directory is missing")
            run_dvc_command(["init"], wdir=str(repo.working_dir), check=True)
        logger.info(f"Running dvc add {path}")
        run_dvc_command(["add", path], wdir=str(repo.working_dir), check=True)
        files_to_stage = [path + ".dvc"]
        gitignore = os.path.join(os.path.dirname(path), ".gitignore")
        if os.path.isfile(os.path.join(repo.working_dir, gitignore)):
            files_to_stage.append(gitignore)
        logger.info(f"Git-adding {files_to_stage}")
        repo.git.add(files_to_stage)
    elif not os.path.isfile(os.path.join(repo.working_dir, path)):
        raise HTTPException(
            400, "File must exist in repo if not being uploaded"
        )
    # Update figures
    figures.append(
        dict(path=path, title=title, description=description, stage=stage)
    )
    ck_info["figures"] = figures
    with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    # Make a commit
    repo.git.commit(["-m", f"Add figure {path}"])
    # Push to GitHub, and optionally DVC remote if we used it
    repo.git.push(["origin", repo.branches[0].name])
    url = None
    if file is not None:
        if file_data is None or full_fig_path is None:
            raise HTTPException(500, "Figure upload data missing")
        # If using the DVC remote, we can just put it in the expected location
        # since we'll have the md5 hash in the dvc file
        with open(os.path.join(repo.working_dir, path + ".dvc")) as f:
            dvc_yaml = yaml.safe_load(f)
        md5 = dvc_yaml["outs"][0]["md5"]
        fs = get_object_fs()
        fpath = make_data_fpath(
            owner_name=owner_name,
            project_name=project_name,
            idx=md5[:2],
            md5=md5[2:],
        )
        with fs.open(fpath, "wb") as f:
            f.write(file_data)  # type: ignore[arg-type]
        if settings.ENVIRONMENT != "local":
            remove_gcs_content_type(fpath)
        url = get_object_url(fpath=fpath, fname=os.path.basename(path))
        # Finally, remove the figure from the cached repo
        os.remove(full_fig_path)
    return Figure(
        path=path,
        title=title,
        description=description,
        stage=stage,
        content=None,
        url=url,
    )


class CommentReply(BaseModel):
    body: str


@router.get("/projects/{owner_name}/{project_name}/comments")
def get_project_comments(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    artifact_type: str | None = None,
    artifact_path: str | None = None,
) -> list[ProjectComment]:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    query = select(ProjectComment).where(
        ProjectComment.project_id == project.id
    )
    if artifact_type is not None:
        query = query.where(ProjectComment.artifact_type == artifact_type)
    if artifact_path is not None:
        query = query.where(ProjectComment.artifact_path == artifact_path)
    comments = list(session.exec(query).all())
    _sync_github_issue_resolutions(session, comments, current_user)
    return comments


def _make_comment_artifact_link(
    owner_name: str,
    project_name: str,
    artifact_type: str | None,
    artifact_path: str,
) -> str:
    """Frontend-relative deep link to the artifact a comment is about.

    Releases live at a path segment (``/releases/{name}``); other artifacts use
    a ``?path=`` query on their section page.
    """
    base = f"/{owner_name}/{project_name}"
    # Encode so paths/names with spaces, #, ?, /, etc. don't break the link.
    encoded = quote(artifact_path, safe="")
    if artifact_type == "release":
        return f"{base}/releases/{encoded}"
    route_map = {
        "figure": "figures",
        "publication": "publications",
        "presentation": "presentations",
        "notebook": "notebooks",
        "references": "references",
        "file": "files",
    }
    route = route_map.get(artifact_type or "", "files")
    return f"{base}/{route}?path={encoded}"


@router.post("/projects/{owner_name}/{project_name}/comments")
def post_project_comment(
    owner_name: str,
    project_name: str,
    comment_in: ProjectCommentPost,
    current_user: CurrentUser,
    session: SessionDep,
) -> ProjectComment:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
    )
    # For figure comments, verify the path exists in the repo
    if comment_in.artifact_type == "figure" and comment_in.artifact_path:
        ck_info = get_ck_info_from_repo(repo)
        fig_paths = {fig["path"] for fig in ck_info.get("figures", [])}
        if comment_in.artifact_path not in fig_paths:
            try:
                repo.head.commit.tree[comment_in.artifact_path]
            except KeyError:
                raise HTTPException(404)
    # Resolve the commit hash for the git context at comment time
    try:
        if comment_in.git_ref:
            git_rev = repo.commit(comment_in.git_ref).hexsha
        else:
            git_rev = repo.head.commit.hexsha
    except Exception:
        logger.info(
            f"Failed to resolve Git ref {comment_in.git_ref} for comment; "
            "storing without Git rev"
        )
        git_rev = None
    comment = ProjectComment(
        project_id=project.id,
        artifact_path=comment_in.artifact_path,
        artifact_type=comment_in.artifact_type,
        comment=comment_in.comment,
        highlight=comment_in.highlight.model_dump()
        if comment_in.highlight
        else None,
        user_id=current_user.id,
        parent_id=comment_in.parent_id,
        git_ref=comment_in.git_ref,
        git_rev=git_rev,
    )
    session.add(comment)
    session.flush()
    if comment_in.create_github_issue and comment_in.artifact_path:
        app_base = settings.frontend_host.rstrip("/")
        artifact_link = app_base + _make_comment_artifact_link(
            owner_name,
            project_name,
            comment_in.artifact_type,
            comment_in.artifact_path,
        )
        body_lines = [
            f"Comment on [{comment_in.artifact_path}]({artifact_link}):",
            "",
            comment_in.comment,
        ]
        if comment_in.highlight:
            highlighted_text = comment_in.highlight.content.get("text", "")
            if highlighted_text:
                body_lines += ["", f"> {highlighted_text}"]
        issue_url = _try_create_github_issue(
            session=session,
            current_user=current_user,
            project=project,
            title=_make_comment_title(comment_in.comment),
            body="\n".join(body_lines),
        )
        if issue_url:
            comment.external_url = issue_url
    commenter_name = current_user.full_name or current_user.account.github_name
    if comment_in.artifact_path:
        _fan_out_notifications(
            session=session,
            project=project,
            commenter_id=current_user.id,
            message=f"{commenter_name} commented on {comment_in.artifact_path}",
            link=_make_comment_artifact_link(
                owner_name,
                project_name,
                comment_in.artifact_type,
                comment_in.artifact_path,
            ),
        )
    session.commit()
    session.refresh(comment)
    mixpanel.track(
        current_user,
        "Posted project comment",
        {
            "owner_name": owner_name,
            "project_name": project_name,
            "artifact_type": comment_in.artifact_type,
            "has_highlight": bool(comment_in.highlight),
        },
    )
    return comment


@router.patch("/projects/{owner_name}/{project_name}/comments/{comment_id}")
def patch_project_comment(
    owner_name: str,
    project_name: str,
    comment_id: uuid.UUID,
    patch: ProjectCommentPatch,
    current_user: CurrentUser,
    session: SessionDep,
) -> ProjectComment:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    comment = session.get(ProjectComment, comment_id)
    if comment is None or comment.project_id != project.id:
        raise HTTPException(404)
    now = utcnow() if patch.resolved else None
    comment.resolved = now
    session.add(comment)
    # Cascade resolve/unresolve to all descendants
    queue = [comment_id]
    while queue:
        parent_id = queue.pop()
        children = session.exec(
            select(ProjectComment).where(ProjectComment.parent_id == parent_id)
        ).all()
        for child in children:
            child.resolved = now
            session.add(child)
            if child.id:
                queue.append(child.id)
    session.commit()
    session.refresh(comment)
    if patch.resolved:
        _try_close_github_issue(session, current_user, comment.external_url)
    else:
        _try_reopen_github_issue(session, current_user, comment.external_url)
    mixpanel.user_resolved_comment(
        current_user,
        owner_name,
        project_name,
        comment.artifact_type or "project",
        patch.resolved,
    )
    return comment


@router.delete("/projects/{owner_name}/{project_name}/comments/{comment_id}")
def delete_project_comment(
    owner_name: str,
    project_name: str,
    comment_id: uuid.UUID,
    current_user: CurrentUser,
    session: SessionDep,
) -> None:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    comment = session.get(ProjectComment, comment_id)
    if comment is None or comment.project_id != project.id:
        raise HTTPException(404)
    if comment.user_id != current_user.id:
        raise HTTPException(403)
    session.delete(comment)
    session.commit()


@router.post(
    "/projects/{owner_name}/{project_name}/comments/{comment_id}/replies"
)
def post_project_comment_reply(
    owner_name: str,
    project_name: str,
    comment_id: uuid.UUID,
    reply: CommentReply,
    current_user: CurrentUser,
    session: SessionDep,
) -> ProjectComment:
    # Requires write (like posting a top-level comment): a reply can be
    # mirrored to the project's GitHub issue via the App installation token, so
    # a read-only collaborator must not be able to trigger it.
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    comment = session.get(ProjectComment, comment_id)
    if comment is None or comment.project_id != project.id:
        raise HTTPException(404)
    # Enforce one-level threading: if the target comment is itself a reply,
    # attach the new reply to its parent so the thread stays flat.
    thread_root_id = comment.parent_id if comment.parent_id else comment_id
    thread_root = (
        session.get(ProjectComment, thread_root_id)
        if thread_root_id != comment_id
        else comment
    )
    if thread_root and thread_root.external_url:
        _try_post_github_issue_comment(
            session, current_user, thread_root.external_url, reply.body
        )
    elif comment.external_url:
        _try_post_github_issue_comment(
            session, current_user, comment.external_url, reply.body
        )
    reply_comment = ProjectComment(
        project_id=project.id,
        artifact_path=comment.artifact_path,
        artifact_type=comment.artifact_type,
        comment=reply.body,
        user_id=current_user.id,
        parent_id=thread_root_id,
    )
    session.add(reply_comment)
    session.commit()
    session.refresh(reply_comment)
    return reply_comment


def _github_token_for_repo(
    session: Session,
    current_user: User,
    owner_repo: str,
) -> str | None:
    """Return a token for GitHub API calls on ``owner/repo``.

    Prefers the user's personal token; for GitHub-less collaborators (e.g.
    invite-link members) falls back to the Calkit GitHub App installation
    token so they can still open, close, and comment on issues. Returns None
    if neither is available.
    """
    try:
        return users.get_github_token(session, current_user)
    except HTTPException:
        pass
    try:
        owner_name, repo_name = owner_repo.split("/", 1)
        return github.get_app_installation_token(owner_name, repo_name)
    except (github.GitHubAppNotConfigured, HTTPException) as e:
        logger.info(
            f"No GitHub token for {current_user.email} on {owner_repo}: {e}"
        )
        return None


def _make_github_authorship_prefix(user: User) -> str:
    """A one-line attribution to prepend to issues/comments a GitHub-less user
    posts through the Calkit App.

    GitHub users author under their own GitHub account, so the content already
    shows who wrote it; GitHub-less users post via the App (authored as the
    bot), so name them in the body. Returns "" for GitHub users.
    """
    if user.account.github_name is not None:
        return ""
    name = user.full_name or user.account.name
    return f"_Posted by {name} ({user.email}) via Calkit._\n\n"


def _sync_github_issue_resolutions(
    session: Session,
    comments: list[ProjectComment],
    current_user: CurrentUserOptional,
) -> None:
    """Check GitHub issue status for unresolved comments with an external_url.

    If the linked issue is closed, mark the comment resolved. Silently ignores
    any errors (rate limits, missing token, unexpected URL shape, etc.) so this
    never breaks a read request.
    """
    unresolved_with_url = [
        c for c in comments if c.external_url and c.resolved is None
    ]
    if not unresolved_with_url:
        return
    changed = False
    # Resolve a token per repo (personal token, else App install token for
    # GitHub-less users), cached so we don't re-mint per comment. Falls back to
    # unauthenticated (60 req/hr) for public repos when neither is available.
    token_by_repo: dict[str, str | None] = {}
    for comment in unresolved_with_url:
        url = str(comment.external_url)
        # Parse owner/repo/number from
        # https://github.com/{owner}/{repo}/issues/{n}
        try:
            parts = url.rstrip("/").split("/")
            issue_number = int(parts[-1])
            repo = f"{parts[-4]}/{parts[-3]}"
        except Exception:
            continue
        if repo not in token_by_repo:
            token_by_repo[repo] = (
                _github_token_for_repo(session, current_user, repo)
                if current_user is not None
                else None
            )
        headers = {"Accept": "application/vnd.github+json"}
        token = token_by_repo[repo]
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            resp = requests.get(
                f"https://api.github.com/repos/{repo}/issues/{issue_number}",
                headers=headers,
                timeout=5,
            )
            if (
                resp.status_code == 200
                and resp.json().get("state") == "closed"
            ):
                comment.resolved = utcnow()
                session.add(comment)
                changed = True
        except Exception as exc:
            logger.debug(f"GitHub issue sync failed for {url}: {exc}")
    if changed:
        session.commit()


def _make_comment_title(comment: str) -> str:
    """Extract a GitHub issue title from the first sentence of a comment.

    Strips trailing ``.`` and ``!`` but preserves ``?`` so questions read
    naturally as titles.
    """

    m = re.search(r"([.!?])\s", comment)
    if m:
        sentence = comment[: m.start() + 1]
    else:
        sentence = comment.split("\n")[0]
    sentence = sentence.rstrip()
    if sentence.endswith(".") or sentence.endswith("!"):
        sentence = sentence[:-1]
    return sentence[:256]


def _try_create_github_issue(
    session: Session,
    current_user: User,
    project: Project,
    title: str,
    body: str,
) -> str | None:
    """Create a GitHub issue on the project repo and return its URL.

    Returns None if the project has no GitHub repo or the user has no token.
    Never raises--failures are logged and silently swallowed so a missing
    token doesn't prevent the comment from being saved.
    """
    github_repo = project.github_repo
    if not github_repo:
        return None
    token = _github_token_for_repo(session, current_user, github_repo)
    if token is None:
        logger.info(
            f"Skipping GitHub issue creation for {current_user.email}: "
            "no GitHub token"
        )
        return None
    resp = requests.post(
        f"https://api.github.com/repos/{github_repo}/issues",
        json={
            "title": title,
            "body": f"{_make_github_authorship_prefix(current_user)}{body}",
        },
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=10,
    )
    if not resp.ok:
        logger.warning(
            f"GitHub issue creation failed for {github_repo}: "
            f"{resp.status_code} {resp.text}"
        )
        return None
    return resp.json().get("html_url")


def _try_post_github_issue_comment(
    session: Session,
    current_user: User,
    external_url: str,
    body: str,
) -> str | None:
    """Post a comment to the linked GitHub issue. Returns the comment URL or None."""
    try:
        parts = external_url.rstrip("/").split("/")
        issue_number = int(parts[-1])
        repo = f"{parts[-4]}/{parts[-3]}"
    except Exception:
        return None
    token = _github_token_for_repo(session, current_user, repo)
    if token is None:
        logger.debug("Skipping GitHub issue comment: no token")
        return None
    try:
        resp = requests.post(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
            json={
                "body": f"{_make_github_authorship_prefix(current_user)}{body}"
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=10,
        )
        if not resp.ok:
            logger.warning(
                f"GitHub issue comment failed for {external_url}: "
                f"{resp.status_code} {resp.text}"
            )
            return None
        return resp.json().get("html_url")
    except Exception as exc:
        logger.debug(f"GitHub issue comment failed for {external_url}: {exc}")
        return None


def _try_reopen_github_issue(
    session: Session,
    current_user: User,
    external_url: str | None,
) -> None:
    """Reopen the linked GitHub issue if one exists.

    Silently ignores any errors so a missing token or unexpected URL never
    prevents the comment from being unresolved.
    """
    if not external_url:
        return
    try:
        parts = external_url.rstrip("/").split("/")
        issue_number = int(parts[-1])
        repo = f"{parts[-4]}/{parts[-3]}"
    except Exception:
        return
    token = _github_token_for_repo(session, current_user, repo)
    if token is None:
        logger.debug("Skipping GitHub issue reopen: no token")
        return
    try:
        resp = requests.patch(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}",
            json={"state": "open"},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=10,
        )
        if not resp.ok:
            logger.warning(
                f"GitHub issue reopen failed for {external_url}: "
                f"{resp.status_code} {resp.text}"
            )
    except Exception as exc:
        logger.debug(f"GitHub issue reopen failed for {external_url}: {exc}")


def _try_close_github_issue(
    session: Session,
    current_user: User,
    external_url: str | None,
) -> None:
    """Close the linked GitHub issue if one exists.

    Silently ignores any errors so a missing token or unexpected URL never
    prevents the comment from being resolved.
    """
    if not external_url:
        return
    try:
        parts = external_url.rstrip("/").split("/")
        issue_number = int(parts[-1])
        repo = f"{parts[-4]}/{parts[-3]}"
    except Exception:
        return
    token = _github_token_for_repo(session, current_user, repo)
    if token is None:
        logger.debug("Skipping GitHub issue close: no token")
        return
    try:
        resp = requests.patch(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}",
            json={"state": "closed"},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=10,
        )
        if not resp.ok:
            logger.warning(
                f"GitHub issue close failed for {external_url}: "
                f"{resp.status_code} {resp.text}"
            )
    except Exception as exc:
        logger.debug(f"GitHub issue close failed for {external_url}: {exc}")


def _fan_out_notifications(
    session: Session,
    project: Project,
    commenter_id: uuid.UUID,
    message: str,
    link: str,
) -> None:
    """Create Notification rows for all project members except the commenter."""
    # Collect user IDs: project owner + anyone with explicit access
    recipient_ids: set[uuid.UUID] = set()
    owner_account = session.get(Account, project.owner_account_id)
    if owner_account and owner_account.user_id:
        recipient_ids.add(owner_account.user_id)
    access_rows = session.exec(
        select(UserProjectAccess).where(
            UserProjectAccess.project_id == project.id,
            or_(
                UserProjectAccess.role_id.is_not(None),
                UserProjectAccess.github_access.is_not(None),
            ),
        )
    ).fetchall()
    for row in access_rows:
        recipient_ids.add(row.user_id)
    recipient_ids.discard(commenter_id)
    for uid in recipient_ids:
        session.add(
            Notification(
                user_id=uid,
                project_id=project.id,
                message=message,
                link=link,
            )
        )


def _sync_datasets_with_db(
    ck_info: dict, project: Project, session: Session
) -> Project:
    datasets_ck = list(ck_info.get("datasets", []))
    datasets = deepcopy(datasets_ck)
    # Convert imported_from from dict to str for saving in the database
    for ds in datasets:
        if "imported_from" in ds:
            if isinstance(ds["imported_from"], dict):
                prj = ds["imported_from"].get("project")
                path = ds["imported_from"].get("path")
                if prj is None:
                    ds["imported_from"] = None
                else:
                    imported_from = prj
                    if path is not None:
                        imported_from += "/" + path
                    ds["imported_from"] = imported_from
    logger.info(f"Found {len(datasets)} datasets in Calkit info")
    # Put these in the database idempotently
    existing_datasets = project.datasets
    logger.info(f"Found {len(existing_datasets)} existing datasets in DB")
    # First update any existing datasets, identified by path
    existing_keyed_by_path = {ds.path: ds for ds in existing_datasets}
    update_keyed_by_path = {ds["path"]: ds for ds in datasets}
    for path, ds in existing_keyed_by_path.items():
        if path in update_keyed_by_path:
            logger.info(f"Updating dataset with path: {path}")
            ds.sqlmodel_update(update_keyed_by_path[path])
        else:
            logger.info(f"Deleting dataset with path: {path}")
            session.delete(ds)
    # Now add any new ones missing
    for path, ds in update_keyed_by_path.items():
        if path not in existing_keyed_by_path:
            logger.info(f"Adding new dataset at path: {path}")
            project.datasets.append(
                Dataset.model_validate(ds, update=dict(project_id=project.id))
            )
    session.commit()
    session.refresh(project)
    return project


@router.get("/projects/{owner_name}/{project_name}/datasets")
def get_project_datasets(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> list[Dataset]:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    # Read the datasets file from the repo
    ck_info = get_ck_info(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    project = _sync_datasets_with_db(
        ck_info=ck_info, project=project, session=session
    )
    return project.datasets


@router.get("/projects/{owner_name}/{project_name}/datasets/{path:path}")
def get_project_dataset(
    path: str,
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    filter_paths: list[str] | None = Query(default=None),
    ref: str | None = None,
) -> DatasetForImport:
    logger.info(f"Received request to get dataset with path: {path}")
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    # Read the datasets file from the repo
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    git_rev = repo.git.rev_parse(["HEAD"])
    repo_dir = repo.working_dir
    ck_info = app.projects.get_ck_info_for_ref(
        project=project,
        repo=repo,
        ref=ref,
    )
    datasets = ck_info.get("datasets", [])
    # First check if this path is even a dataset
    ds = None
    for dsi in datasets:
        if dsi.get("path") == path:
            ds = dsi
            break
    if ds is None:
        raise HTTPException(404, f"Dataset at path {path} does not exist")
    # Is this dataset tracked with Git?
    # If so, our response will be different
    git_files = repo.git.ls_files(path)
    if git_files:
        git_files = git_files.split("\n")
    else:
        git_files = []
    if git_files:
        logger.info(f"Dataset at {path} is kept in Git")
        if filter_paths:
            logger.info(f"Filtering paths for patterns: {filter_paths}")
            filtered_git_files = []
            for f in git_files:
                for pattern in filter_paths:
                    if fnmatch(f, pattern) and f not in filtered_git_files:
                        filtered_git_files.append(f)
            git_files = filtered_git_files
        git_import = dict(files=git_files)
        return DatasetForImport.model_validate(
            ds | dict(git_import=git_import, git_rev=git_rev)
        )
    # The dataset is not in Git, so check DVC
    # Load DVC pipeline and lock files if they exist
    dvc_out = dict(
        remote=f"calkit:{owner_name}/{project_name}",
        push=False,
    )
    dvc_lock_fpath = os.path.join(repo_dir, "dvc.lock")
    dvc_lock = {}
    if os.path.isfile(dvc_lock_fpath):
        with open(dvc_lock_fpath) as f:
            dvc_lock = yaml.safe_load(f)
        # Expand all DVC lock outs
        fs = get_object_fs()
        dvc_lock_outs = expand_dvc_lock_outs(
            dvc_lock,
            owner_name=owner_name,
            project_name=project_name,
            fs=fs,
            get_sizes=True,
        )
        logger.info(f"Read {len(dvc_lock_outs)} DVC lock outputs")
    else:
        dvc_lock_outs = {}
    # Create the DVC import object
    # We need to know the MD5 hash
    stage_name = ds.get("stage")
    if stage_name is None:
        logger.info("No stage defined for dataset")
        dvc_fp = os.path.join(repo_dir, path + ".dvc")
        if os.path.isfile(dvc_fp):
            logger.info(f"Repo has a .dvc file for {path}")
            with open(dvc_fp) as f:
                dvo = yaml.safe_load(f)["outs"][0]
            dvc_out |= dvo
            ds["dvc_import"] = dict(outs=[dvc_out])
            ds["git_rev"] = git_rev
            return DatasetForImport.model_validate(ds)
        elif path in dvc_lock_outs:
            logger.info(f"Found {path} in DVC lock outputs")
            dvo = dvc_lock_outs[path]
            dvc_out |= dvo
            ds["dvc_import"] = dict(outs=[dvc_out])
            ds["git_rev"] = git_rev
            return DatasetForImport.model_validate(ds)
        else:
            # No stage and no .dvc file -- error
            logger.info("No stage nor .dvc file found")
            raise HTTPException(404)
    else:
        logger.info(f"Looking up contents based on stage {stage_name}")
        pipeline_fpath = os.path.join(repo_dir, "dvc.yaml")
        if not os.path.isfile(pipeline_fpath):
            logger.info("No dvc.yaml file")
            raise HTTPException(400, "dvc.yaml file missing")
        with open(pipeline_fpath) as f:
            pipeline = yaml.safe_load(f)
        dvc_lock_fpath = os.path.join(repo_dir, "dvc.lock")
        if not os.path.isfile(dvc_lock_fpath):
            logger.info("No dvc.lock file")
            raise HTTPException(400, "dvc.lock file missing")
        out = output_from_pipeline(
            path=path,
            stage_name=stage_name,
            pipeline=pipeline,
            lock=dvc_lock,
        )
        if out is None:
            logger.info("Searching through DVC lock outs")
            if path in dvc_lock_outs:
                logger.info(f"Found {path} in DVC lock outputs")
                if filter_paths is not None:
                    filtered_outs = []
                    filtered_paths = []
                    # The out should now be a list of outs
                    for fpath, out_i in dvc_lock_outs.items():
                        for pattern in filter_paths:
                            if (
                                fnmatch(fpath, pattern)
                                and fpath not in filtered_paths
                                and out_i.get("type") == "file"
                            ):
                                filtered_paths.append(fpath)
                                filtered_outs.append(out_i)
                    out = filtered_outs
                else:
                    out = dvc_lock_outs[path]
        if out is None:
            logger.info("Cannot find DVC object")
            raise HTTPException(400, "Cannot find DVC object")
        if isinstance(out, list):
            if not out:
                logger.info("Filtered data is empty")
                raise HTTPException(400, "Filtered data is empty")
            logger.info(f"Creating outs from filtered: {out}")
            dvc_outs = [dvc_out | out_i for out_i in out]
            ds["dvc_import"] = dict(outs=dvc_outs)
        else:
            dvc_out |= out
            ds["dvc_import"] = dict(outs=[dvc_out])
        ds["git_rev"] = git_rev
        return DatasetForImport.model_validate(ds)


class LabelDatasetPost(BaseModel):
    imported_from: str | None = None
    path: str
    title: str | None = None
    tabular: bool | None = None
    stage: str | None = None
    description: str | None = None


@router.post("/projects/{owner_name}/{project_name}/datasets/label")
def post_project_dataset_label(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
    req: LabelDatasetPost,
) -> Dataset:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    if not req.imported_from:
        if not req.title or not req.description:
            raise HTTPException(
                400, "Non-imported datasets must have titles and descriptions"
            )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    ck_info = app.projects.get_ck_info_from_repo(repo=repo)
    datasets = ck_info.get("datasets", [])
    ds_paths = [ds.get("path") for ds in datasets]
    if req.path in ds_paths:
        raise HTTPException(400, "Dataset already exists")
    local_path = os.path.join(repo.working_dir, req.path)
    zip_path_map = get_zip_path_map_from_repo(repo=repo)
    if not req.imported_from and not (
        os.path.isfile(local_path)
        or os.path.isdir(local_path)
        or os.path.isfile(local_path + ".dvc")
        or req.path in zip_path_map
    ):
        raise HTTPException(400, "Path does not exist in the repo")
    ds = dict(path=req.path)
    for k, v in req.model_dump().items():
        if k == "path":
            continue
        if v is not None:
            ds[k] = v
    datasets.append(ds)
    ck_info["datasets"] = datasets
    with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    # Make a commit
    repo.git.commit(["-m", f"Add dataset {req.path}"])
    repo.git.push(["origin", repo.active_branch.name])
    # TODO: Put datasets into database
    return Dataset.model_validate(
        ds | dict(project_id=project.id, id=uuid.uuid4())
    )


def _valid_dataset_size(content_length: int = Header(lt=50_000_000)):
    """Check content length header.

    From https://github.com/fastapi/fastapi/issues/362#issuecomment-584104025
    """
    return content_length


@router.post(
    "/projects/{owner_name}/{project_name}/datasets/upload",
    dependencies=[Depends(_valid_dataset_size)],
)
def post_project_dataset_upload(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
    path: Annotated[str, Form()],
    title: Annotated[str, Form()],
    description: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> Dataset:
    logger.info(
        f"Received dataset file {path} with content type: {file.content_type}"
    )
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    # Handle projects that aren't yet Calkit projects
    ck_info = get_ck_info_from_repo(repo)
    datasets = ck_info.get("datasets", [])
    # Make sure a dataset with this path doesn't already exist
    dspaths = [ds["path"] for ds in datasets]
    if path in dspaths:
        raise HTTPException(400, "A dataset already exists at this path")
    # Add the file to the repo(s)
    # Save the file to the desired path
    os.makedirs(
        os.path.join(repo.working_dir, os.path.dirname(path)),
        exist_ok=True,
    )
    file_data = file.file.read()
    full_ds_path = os.path.join(repo.working_dir, path)
    with open(full_ds_path, "wb") as f:
        f.write(file_data)
    # Either git add {path} or dvc add {path}
    # If we DVC add, we'll get output like
    # To track the changes with git, run:

    #         git add figures/.gitignore figures/my-figure.png.dvc

    # To enable auto staging, run:

    #         dvc config core.autostage true
    # Initialize DVC if it's never been
    if not os.path.isdir(os.path.join(repo.working_dir, ".dvc")):
        logger.info("Calling dvc init since .dvc directory is missing")
        run_dvc_command(["init"], wdir=str(repo.working_dir), check=True)
    logger.info(f"Running dvc add {path}")
    run_dvc_command(["add", path], wdir=str(repo.working_dir), check=True)
    files_to_stage = [path + ".dvc"]
    gitignore = os.path.join(os.path.dirname(path), ".gitignore")
    if os.path.isfile(os.path.join(repo.working_dir, gitignore)):
        files_to_stage.append(gitignore)
    logger.info(f"Git-adding {files_to_stage}")
    repo.git.add(files_to_stage)
    # Update figures
    datasets.append(dict(path=path, title=title, description=description))
    ck_info["datasets"] = datasets
    with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    # Make a commit
    repo.git.commit(["-m", f"Add dataset {path}"])
    # Push to GitHub, and optionally DVC remote if we used it
    repo.git.push(["origin", repo.active_branch.name])
    # If using the DVC remote, we can just put it in the expected location
    # since we'll have the md5 hash in the dvc file
    with open(os.path.join(repo.working_dir, path + ".dvc")) as f:
        dvc_yaml = yaml.safe_load(f)
    md5 = dvc_yaml["outs"][0]["md5"]
    fs = get_object_fs()
    fpath = make_data_fpath(
        owner_name=owner_name,
        project_name=project_name,
        idx=md5[:2],
        md5=md5[2:],
    )
    with fs.open(fpath, "wb") as f:
        f.write(file_data)  # type: ignore[arg-type]
    if settings.ENVIRONMENT != "local":
        remove_gcs_content_type(fpath)
    url = get_object_url(fpath=fpath, fname=os.path.basename(path))
    # Finally, remove the dataset from the cached repo
    os.remove(full_ds_path)
    # TODO: Put this dataset into the database
    return Dataset(
        project_id=project.id,
        id=uuid.uuid4(),  # TODO: Should be in DB
        path=path,
        title=title,
        description=description,
        content=None,  # type: ignore
        url=url,
    )


@router.get("/projects/{owner_name}/{project_name}/publications")
def get_project_publications(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> list[Publication]:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    # Read declared metadata at the requested ref. get_repo only fetches a
    # ref, it does not check it out, so reading the working tree would return
    # the default branch's publications/pipeline.
    ck_info = app.projects.get_ck_info_for_ref(
        project=project, repo=repo, ref=ref
    )
    pipeline = app.projects.get_dvc_pipeline_for_ref(repo, ref)
    publications = ck_info.get("publications", [])
    overleaf_info = calkit.overleaf.get_sync_info(
        wdir=repo.working_dir, ck_info=ck_info, fix_legacy=False
    )
    resp = []
    tree = app.projects.get_repo_tree_for_ref(repo, ref)
    (
        ck_info_full,
        dvc_lock_outs,
        zip_path_map,
        _,
    ) = app.projects.get_ck_info_and_dvc_outs_from_tree(project, tree)
    # Staleness is best-effort: never let it block the publication listing.
    dvc_lock: dict = {}
    stage_statuses = {}
    try:
        if tree.is_file("dvc.lock"):
            dvc_lock = ryaml.load(tree.read_bytes("dvc.lock").decode()) or {}
        stage_statuses = compute_stage_statuses(
            dvc_yaml=pipeline,
            dvc_lock=dvc_lock,
            tree=tree,
            owner_name=project.owner_account_name,
            project_name=project.name,
            fs=get_object_fs(),
            cache_token=resolve_commit_sha(repo, ref),
        )
    except Exception as e:
        logger.warning(
            f"Failed to compute pipeline status for publications: {e}"
        )
    for pub in publications:
        if not pub.get("stage") and pub.get("path"):
            auto_stage = find_stage_for_path(pub["path"], dvc_lock)
            if auto_stage is not None:
                pub["stage"] = auto_stage
        if pub.get("stage"):
            pub["stage_info"] = pipeline.get("stages", {}).get(pub["stage"])
            pub["calkit_stage"] = (
                (ck_info.get("pipeline") or {})
                .get("stages", {})
                .get(pub["stage"])
            )
            if pub["stage"] in stage_statuses:
                pub["stage_status"] = stage_statuses[pub["stage"]].model_dump()
        # See if we can fetch the content for this publication
        if "path" in pub:
            try:
                item = app.projects.get_contents_from_tree(
                    project=project,
                    tree=tree,
                    path=pub["path"],
                    ck_info=ck_info_full,
                    dvc_lock_outs=dvc_lock_outs,
                    zip_path_map=zip_path_map,
                )
                pub["content"] = item.content
                pub["storage"] = item.storage
                # Prioritize URL if already defined
                if "url" not in pub:
                    pub["url"] = item.url
                # Patch in Overleaf info if we have it
                if "overleaf" not in pub:
                    pubdir = Path(os.path.dirname(pub["path"])).as_posix()
                    if pubdir in overleaf_info:
                        pub["overleaf"] = overleaf_info[pubdir] | {
                            "wdir": pubdir
                        }
            except HTTPException as e:
                logger.warning(
                    f"Failed to get publication at path {pub['path']}: {e}"
                )
        resp.append(Publication.model_validate(pub))
    return resp


@router.get("/projects/{owner_name}/{project_name}/presentations")
def get_project_presentations(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> list[Presentation]:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    # Read declared metadata at the requested ref. get_repo only fetches a
    # ref, it does not check it out, so reading the working tree would return
    # the default branch's presentations/pipeline.
    ck_info = app.projects.get_ck_info_for_ref(
        project=project, repo=repo, ref=ref
    )
    pipeline = app.projects.get_dvc_pipeline_for_ref(repo, ref)
    presentations = ck_info.get("presentations", [])
    # Paths explicitly declared under ``presentations`` in calkit.yaml. These
    # are always respected (like figures/publications): they're never
    # filtered by the auto-detect heuristics or the PDF/source dedup below.
    declared_paths = {p["path"] for p in presentations if "path" in p}
    explicit_paths = set(declared_paths)

    def _maybe_add_presentation(path: str) -> None:
        """Add ``path`` if it looks like a presentation and isn't declared."""
        parts = path.split("/")
        if any(p.startswith(".") for p in parts):
            return
        ext = "." + parts[-1].rsplit(".", 1)[-1] if "." in parts[-1] else ""
        dir_parts = [p.lower() for p in parts[:-1]]
        if ext.lower() in PRESENTATION_EXTS and any(
            d in PRESENTATION_DIRS for d in dir_parts
        ):
            if path not in declared_paths:
                stem = (
                    parts[-1]
                    .rsplit(".", 1)[0]
                    .replace("_", " ")
                    .replace("-", " ")
                    .capitalize()
                )
                presentations.append({"path": path, "title": stem})
                declared_paths.add(path)

    # Auto-detect presentations from the repo tree
    try:
        commit = repo.commit(ref) if ref else repo.head.commit
        for blob in commit.tree.traverse():
            if blob.type != "blob":  # type: ignore[union-attr]
                continue
            blob_path: str = blob.path  # type: ignore[union-attr]
            _maybe_add_presentation(blob_path)
            # Also detect presentations stored via standalone .dvc pointer
            # files (tracked with `dvc add`, not via a DVC pipeline stage).
            if blob_path.endswith(".dvc"):
                try:
                    dvc_data = yaml.safe_load(blob.data_stream.read())  # type: ignore[union-attr]
                    outs = (
                        dvc_data.get("outs")
                        if isinstance(dvc_data, dict)
                        else None
                    )
                    out = outs[0] if isinstance(outs, list) and outs else None
                    out_path = (
                        out.get("path") if isinstance(out, dict) else None
                    )
                    if isinstance(out_path, str) and out_path:
                        actual_path = os.path.normpath(
                            os.path.join(os.path.dirname(blob_path), out_path)
                        )
                    else:
                        actual_path = blob_path[:-4]
                    if actual_path:
                        _maybe_add_presentation(actual_path)
                except Exception:
                    actual_path = blob_path[:-4]
                    if actual_path:
                        _maybe_add_presentation(actual_path)
    except Exception:
        pass
    tree = app.projects.get_repo_tree_for_ref(repo, ref)
    (
        ck_info_full,
        dvc_lock_outs,
        zip_path_map,
        _,
    ) = app.projects.get_ck_info_and_dvc_outs_from_tree(project, tree)
    # Also auto-detect presentations from DVC lock outs
    for dvc_path, dvc_out in dvc_lock_outs.items():
        if dvc_out.get("type") == "dir":
            continue
        _maybe_add_presentation(dvc_path)
    # Deduplicate auto-detected presentations that exist as both a PDF and a
    # source format (e.g. slides.pptx exported to slides.pdf). Keep the PDF,
    # since it renders and annotates natively, and drop the non-PDF sibling
    # sharing the same path stem. Explicitly declared presentations are
    # always kept.
    pdf_stems = {
        os.path.splitext(p["path"])[0].lower()
        for p in presentations
        if p.get("path", "").lower().endswith(".pdf")
    }
    presentations = [
        p
        for p in presentations
        if p.get("path", "") in explicit_paths
        or p.get("path", "").lower().endswith(".pdf")
        or os.path.splitext(p.get("path", ""))[0].lower() not in pdf_stems
    ]

    # Map each pipeline output path to the stage that produces it, so
    # auto-detected presentations (which aren't declared in calkit.yaml with
    # an explicit ``stage``) can still be associated with their pipeline
    # stage. We read both calkit.yaml's ``pipeline.stages`` (authoritative,
    # uses ``outputs``) and the generated dvc.yaml (uses ``outs``), since the
    # latter may be absent or stale. Output entries can be plain strings or
    # dicts ({path: {...}} in dvc.yaml, {path: ..., storage: ...} in
    # calkit.yaml); templated paths (iterate_over) are skipped.
    def _register_outs(stages: dict, key: str, dest: dict[str, str]) -> None:
        for stage_name, stage_def in (stages or {}).items():
            if not isinstance(stage_def, dict):
                continue
            for out in stage_def.get(key, []) or []:
                if isinstance(out, dict):
                    # dvc.yaml: {path: {...}}; calkit.yaml: {path: <str>}
                    out_paths = (
                        [out["path"]]
                        if "path" in out and isinstance(out["path"], str)
                        else list(out.keys())
                    )
                else:
                    out_paths = [out]
                for out_path in out_paths:
                    if not isinstance(out_path, str) or "{" in out_path:
                        continue
                    norm = os.path.normpath(out_path)
                    dest.setdefault(norm, stage_name)

    out_path_to_stage: dict[str, str] = {}
    _register_outs(
        (ck_info.get("pipeline") or {}).get("stages") or {},
        "outputs",
        out_path_to_stage,
    )
    _register_outs(pipeline.get("stages") or {}, "outs", out_path_to_stage)

    resp = []
    for pres in presentations:
        if "stage" not in pres and "path" in pres:
            # Match the path directly, or any ancestor directory (a stage may
            # declare a directory output containing the presentation file).
            norm_path = os.path.normpath(pres["path"])
            stage_name = out_path_to_stage.get(norm_path)
            while stage_name is None and norm_path not in (".", "/", ""):
                norm_path = os.path.dirname(norm_path)
                if not norm_path:
                    break
                stage_name = out_path_to_stage.get(norm_path)
            if stage_name is not None:
                pres["stage"] = stage_name
        if "stage" in pres:
            pres["stage_info"] = pipeline.get("stages", {}).get(pres["stage"])
        if "path" in pres:
            try:
                item = app.projects.get_contents_from_tree(
                    project=project,
                    tree=tree,
                    path=pres["path"],
                    ck_info=ck_info_full,
                    dvc_lock_outs=dvc_lock_outs,
                    zip_path_map=zip_path_map,
                )
                pres["content"] = item.content
                pres["storage"] = item.storage
                if "url" not in pres:
                    pres["url"] = item.url
            except HTTPException as e:
                logger.warning(
                    f"Failed to get presentation at path {pres['path']}: {e}"
                )
        resp.append(Presentation.model_validate(pres))
    return resp


@router.post("/projects/{owner_name}/{project_name}/publications")
def post_project_publication(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
    path: Annotated[str, Form()],
    kind: Annotated[
        Literal[
            "journal-article",
            "conference-paper",
            "presentation",
            "poster",
            "report",
            "book",
        ],
        Form(),
    ],
    title: Annotated[str, Form()],
    description: Optional[Annotated[str, Form()]] = Form(None),
    stage: Optional[Annotated[str, Form()]] = Form(None),
    template: Optional[Annotated[str, Form()]] = Form(None),
    environment: Optional[Annotated[str, Form()]] = Form(None),
    file: Optional[Annotated[UploadFile, File()]] = Form(None),
) -> Publication:
    if file is not None:
        logger.info(
            f"Received publication file {path} with content type: "
            f"{file.content_type}"
        )
    else:
        logger.info(f"Received request to create publication at {path}")
    if file is not None and stage is not None:
        raise HTTPException(
            400, "DVC outputs should be uploaded with `calkit push`"
        )
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    # Handle projects that aren't yet Calkit projects
    ck_info = get_ck_info_from_repo(repo)
    publications = ck_info.get("publications", [])
    # Make sure a publication with this path doesn't already exist
    pubpaths = [pub["path"] for pub in publications]
    if path in pubpaths:
        raise HTTPException(400, "A publication already exists at this path")
    if file is not None:
        # Add the file to the repo(s)
        # Save the file to the desired path
        os.makedirs(
            os.path.join(repo.working_dir, os.path.dirname(path)),
            exist_ok=True,
        )
        file_data = file.file.read()
        full_fig_path = os.path.join(repo.working_dir, path)
        with open(full_fig_path, "wb") as f:
            f.write(file_data)
        # Either git add {path} or dvc add {path}
        # If we DVC add, we'll get output like
        # To track the changes with git, run:

        #         git add figures/.gitignore figures/my-figure.png.dvc

        # To enable auto staging, run:

        #         dvc config core.autostage true
        # Initialize DVC if it's never been
        if not os.path.isdir(os.path.join(repo.working_dir, ".dvc")):
            logger.info("Calling dvc init since .dvc directory is missing")
            run_dvc_command(["init"], wdir=str(repo.working_dir), check=True)
        logger.info(f"Running dvc add {path}")
        run_dvc_command(["add", path], wdir=str(repo.working_dir), check=True)
        files_to_stage = [path + ".dvc"]
        gitignore = os.path.join(os.path.dirname(path), ".gitignore")
        if os.path.isfile(os.path.join(repo.working_dir, gitignore)):
            files_to_stage.append(gitignore)
        logger.info(f"Git-adding {files_to_stage}")
        repo.git.add(files_to_stage)
    elif template is not None:
        # TODO: Centralize template names
        if template not in ["latex/article", "latex/jfm"]:
            raise HTTPException(422, "Invalid template name")
        cmd = [
            "calkit",
            "new",
            "publication",
            path,
            "--no-commit",
            "--kind",
            kind,
            "--title",
            title,
            "--template",
            template,
        ]
        if description is not None:
            cmd += ["--description", description]
        if stage is not None:
            cmd += ["--stage", stage]
        if environment is not None:
            cmd += ["--environment", environment]
        result = subprocess.run(
            cmd, cwd=repo.working_dir, capture_output=True, text=True
        )
        if result.returncode != 0:
            # The CLI validates things like duplicate publication paths;
            # surface its message rather than a 500. Its errors go to
            # stderr as a final "Error: ..." line.
            lines = [
                line.strip()
                for line in result.stderr.splitlines()
                if line.strip()
            ]
            detail = lines[-1] if lines else "Failed to create publication"
            detail = detail.removeprefix("Error: ")
            logger.warning(f"calkit new publication failed: {detail}")
            raise HTTPException(400, detail)
    elif not os.path.isfile(os.path.join(repo.working_dir, path)):
        raise HTTPException(
            400, "File must exist in repo if not being uploaded"
        )
    # Only update publications if template is None, since when a template is
    # used, this was already done in `calkit new publication`
    if template is None:
        # Update figures
        publications.append(
            dict(
                path=path,
                type=kind,
                title=title,
                description=description,
                stage=stage,
            )
        )
        ck_info["publications"] = publications
        with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
            ryaml.dump(ck_info, f)
        repo.git.add("calkit.yaml")
    # Make a commit
    repo.git.commit(["-m", f"Add publication {path} ({kind})"])
    # Push to GitHub, and optionally DVC remote if we used it
    repo.git.push(["origin", repo.active_branch.name])
    url = None
    if file is not None:
        # If using the DVC remote, we can just put it in the expected location
        # since we'll have the md5 hash in the dvc file
        with open(os.path.join(repo.working_dir, path + ".dvc")) as f:
            dvc_yaml = yaml.safe_load(f)
        md5 = dvc_yaml["outs"][0]["md5"]
        fs = get_object_fs()
        fpath = make_data_fpath(
            owner_name=owner_name,
            project_name=project_name,
            idx=md5[:2],
            md5=md5[2:],
        )
        with fs.open(fpath, "wb") as f:
            f.write(file_data)  # type: ignore
        if settings.ENVIRONMENT != "local":
            remove_gcs_content_type(fpath)
        url = get_object_url(fpath=fpath, fname=os.path.basename(path))
        # Finally, remove the figure from the cached repo
        os.remove(full_fig_path)
    return Publication(
        path=path,
        title=title,
        description=description,
        stage=stage,
        content=None,
        url=url,
    )


@router.post("/projects/{owner_name}/{project_name}/publications/overleaf")
async def post_project_overleaf_publication(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
    path: Annotated[str, Form()],
    kind: Annotated[
        Literal[
            "journal-article",
            "conference-paper",
            "report",
            "book",
            "masters-thesis",
            "phd-thesis",
            "other",
        ],
        Form(),
    ],
    overleaf_project_url: Optional[Annotated[str, Form()]] = Form(None),
    title: Optional[Annotated[str, Form()]] = Form(None),
    description: Optional[Annotated[str, Form()]] = Form(None),
    target_path: Optional[Annotated[str, Form()]] = Form(None),
    stage_name: Optional[Annotated[str, Form()]] = Form(None),
    environment_name: Optional[Annotated[str, Form()]] = Form(None),
    overleaf_token: Optional[Annotated[str, Form()]] = Form(None),
    auto_build: Optional[Annotated[bool, Form()]] = Form(False),
    file: Optional[Annotated[UploadFile, File()]] = File(None),
) -> Publication:
    """Import a publication from Overleaf into a project.

    Supports two modes:
    1. Import and link via cloning the Overleaf Git repo.
       Requires an Overleaf token and performs sync setup.
    2. Import ZIP via user-provided downloaded archive.
       Skips linkage and sync info; just copies files into repo.

    Accepts multipart/form-data with an optional 'file' field
    (for the ZIP archive).
    """
    # Validate input: require either an Overleaf URL or a ZIP file
    if (
        overleaf_project_url is None or overleaf_project_url.strip() == ""
    ) and file is None:
        raise HTTPException(
            422, "Either Overleaf project URL or ZIP file must be provided"
        )
    # sync_paths and push_paths are always empty for now since we don't expose
    # them in the UI
    sync_paths: list[str] = []
    push_paths: list[str] = []
    # Basic path validation
    if path == ".":
        raise HTTPException(400, "Path cannot be parent directory")
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    if os.path.exists(os.path.join(repo.working_dir, path)):
        raise HTTPException(400, f"Path '{path}' already exists in the repo")
    # Make sure path is a posix path
    path = Path(path).as_posix()
    # Handle projects that aren't yet Calkit projects
    ck_info = get_ck_info_from_repo(repo)
    publications = ck_info.get("publications", [])
    # Make sure a publication with this path doesn't already exist
    pubpaths = [pub.get("path") for pub in publications]
    if path in pubpaths:
        raise HTTPException(400, "A publication already exists at this path")
    # Make sure we don't already have a stage with the same name
    pipeline = ck_info.get("pipeline", {})
    stages = pipeline.get("stages", {})
    if not stage_name:
        stage_name = f"build-{path.replace('/', '-')}"
    if stage_name and stage_name in stages:
        raise HTTPException(
            400, f"A stage named '{stage_name}' already exists; please provide"
        )
    # Check environment spec, auto-detecting a TeXlive env to use
    envs = ck_info.get("environments", {})
    env_name = environment_name
    if not env_name:
        for en, e in envs.items():
            if e.get("kind") == "docker" and "texlive" in e.get("image", ""):
                env_name = en
                logger.info(f"Detected TeXlive env '{en}'")
                break
    elif env_name and env_name in envs:
        env = envs[env_name]
        if env.get("kind") != "docker" and "texlive" not in env.get(
            "image", ""
        ):
            raise HTTPException(
                400,
                (
                    f"Environment {env_name} exists, "
                    "but is not a TeXLive Docker environment"
                ),
            )
    if not env_name:
        env_name = "tex"
        n = 1
        while env_name in envs:
            env_name = f"tex-{n}"
            n += 1
        env = {"kind": "docker", "image": "texlive/texlive:latest-full"}
        envs[env_name] = env
        ck_info["environments"] = envs
    # Determine mode: link vs zip
    import_zip_mode = file is not None
    overleaf_repo = None
    if import_zip_mode:
        overleaf_abs_path = os.path.join(repo.working_dir, path)
        logger.info("Importing Overleaf ZIP archive; skipping linkage")
        # Unzip the whole archive into the requested path
        os.makedirs(overleaf_abs_path, exist_ok=True)
        resolved_dest = os.path.realpath(overleaf_abs_path)
        with zipfile.ZipFile(io.BytesIO(await file.read()), "r") as zf:
            for member in zf.namelist():
                member_dest = os.path.realpath(
                    os.path.join(resolved_dest, member)
                )
                if not member_dest.startswith(resolved_dest + os.sep):
                    raise HTTPException(
                        400,
                        f"ZIP entry '{member}' would escape target directory",
                    )
            zf.extractall(overleaf_abs_path)
    elif overleaf_project_url is not None:
        overleaf_project_id = overleaf_project_url.split("/")[-1]
        # Handle token saving and validation for link mode
        if overleaf_token is not None:
            users.save_overleaf_token(
                session=session,
                user=current_user,
                token=overleaf_token,
                expires=None,
            )
        try:
            users.get_overleaf_token(session=session, user=current_user)
        except HTTPException:
            raise HTTPException(400, "No Overleaf token found")
        try:
            overleaf_repo = get_overleaf_repo(
                project=project,
                user=current_user,
                session=session,
                overleaf_project_id=overleaf_project_id,
            )
        except GitCommandError as e:
            logger.error(f"Failed to clone Overleaf repo: {e}")
            raise HTTPException(
                400,
                (
                    "Failed to fetch Overleaf project; check URL, token, "
                    "and that Git integration is enabled on Overleaf"
                ),
            )
        overleaf_abs_path = overleaf_repo.working_dir
    # Detect target path
    if not target_path:
        overleaf_files = os.listdir(overleaf_abs_path)
        for candidate in ["main.tex", "paper.tex", "report.tex"]:
            if candidate in overleaf_files:
                target_path = candidate
                break
    if not target_path:
        raise HTTPException(
            400, "Target path cannot be detected; please specify"
        )
    if not target_path.endswith(".tex"):
        raise HTTPException(400, "Target path must end with '.tex'")
    target_full_path = os.path.join(overleaf_abs_path, target_path)
    if not os.path.isfile(target_full_path):
        raise HTTPException(
            400,
            f"Target path '{target_path}' does not exist in Overleaf project",
        )
    # Detect title
    if not title:
        with open(target_full_path) as f:
            overleaf_target_text = f.read()
        texsoup = TexSoup(overleaf_target_text)
        title = str(texsoup.title.string) if texsoup.title else None
    if not title:
        raise HTTPException(400, "Title cannot be detected; please provide")
    # Build stage inputs
    overleaf_rel_paths = os.listdir(overleaf_abs_path)
    input_rel_paths = set(overleaf_rel_paths + sync_paths + push_paths)
    input_paths: list[str] = []
    for p in input_rel_paths:
        if (
            p == target_path
            or p.startswith(".")
            or p == target_path.removesuffix(".tex") + ".pdf"
        ):
            continue
        project_rel_path = os.path.join(path, p)
        if project_rel_path not in input_paths:
            input_paths.append(project_rel_path)
    stage = {
        "kind": "latex",
        "target_path": os.path.join(path, target_path),
        "environment": env_name,
        "inputs": input_paths,
    }
    stages[stage_name] = stage
    pipeline["stages"] = stages
    ck_info["pipeline"] = pipeline
    pdf_output_path = os.path.join(
        path, target_path.removesuffix(".tex") + ".pdf"
    )
    publication = {
        "path": pdf_output_path,
        "title": title,
        "description": description,
        "kind": kind,
        "stage": stage_name,
    }
    publications.append(publication)
    ck_info["publications"] = publications
    if not import_zip_mode and overleaf_repo is not None:
        overleaf_sync_in_ck_info = ck_info.get("overleaf_sync", {})
        overleaf_sync_in_ck_info[path] = {"url": overleaf_project_url}
        ck_info["overleaf_sync"] = overleaf_sync_in_ck_info
        last_overleaf_sync_commit = overleaf_repo.head.commit.hexsha
        calkit.overleaf.write_sync_info(
            synced_path=path,
            info={
                "project_id": overleaf_project_id,
                "last_sync_commit": last_overleaf_sync_commit,
            },
            wdir=repo.working_dir,
        )
    elif not import_zip_mode and overleaf_repo is None:
        raise HTTPException(500, "Failed to get Overleaf repo")
    # Copy files into repo
    dest_pub_dir = os.path.join(repo.working_dir, path)
    if not import_zip_mode:
        shutil.copytree(
            src=overleaf_abs_path,
            dst=dest_pub_dir,
            ignore=lambda src, names: [
                ".git",
                target_path.removesuffix(".tex") + ".pdf",
            ],
        )
    else:
        # Make sure the output PDF doesn't exist
        pdf_path = os.path.join(repo.working_dir, pdf_output_path)
        if os.path.isfile(pdf_path):
            logger.info("PDF was part of Overleaf ZIP; removing")
            os.remove(pdf_path)
    # Add publication-specific .gitignore
    gitignore_txt = (
        "\n".join(
            [
                "*.log",
                "*.synctex.gz",
                "*.aux",
                "*.toc",
                "*.out",
                "*.bbl",
                "*.fdb_latexmk",
                "*.blg",
                "*.rej",
                "*.tdo",
                "*.fls",
                "*.nav",
            ]
        )
        + "\n"
    )
    with open(os.path.join(dest_pub_dir, ".gitignore"), "w") as f:
        f.write(gitignore_txt)
    if not repo.ignored(".calkit/overleaf/"):
        with open(os.path.join(repo.working_dir, ".gitignore"), "a") as f:
            f.write("\n.calkit/overleaf/\n")
        repo.git.add(".gitignore")
    with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    if not import_zip_mode:
        repo.git.add(calkit.overleaf.get_sync_info_fpath())
    repo.git.add(path)
    subprocess.run(
        ["calkit", "check", "pipeline", "--compile"], cwd=repo.working_dir
    )
    repo.git.add("dvc.yaml")
    if auto_build:
        workflow_dir = os.path.join(repo.working_dir, ".github", "workflows")
        os.makedirs(workflow_dir, exist_ok=True)
        workflow_files = os.listdir(workflow_dir)
        has_calkit_workflow = False
        for fname in workflow_files:
            workflow_fpath = os.path.join(workflow_dir, fname)
            with open(workflow_fpath) as f:
                workflow_txt = f.read()
            if "calkit" in workflow_txt:
                has_calkit_workflow = True
                break
        if not has_calkit_workflow:
            download_url = (
                "https://raw.githubusercontent.com/calkit/"
                "run-action/refs/heads/main/example.yml"
            )
            download_resp = requests.get(download_url)
            workflow_rel_path = os.path.join(
                ".github", "workflows", "run-calkit.yml"
            )
            workflow_fpath = os.path.join(repo.working_dir, workflow_rel_path)
            with open(workflow_fpath, "w") as f:
                f.write(download_resp.text)
            repo.git.add(workflow_rel_path)
    commit_msg = (
        f"Import Overleaf project ID {overleaf_project_id} to '{path}'"
        if not import_zip_mode
        else f"Import Overleaf ZIP to '{path}'"
    )
    repo.git.commit(["-m", commit_msg])
    repo.git.push(["origin", repo.active_branch.name])
    if not import_zip_mode:
        app.projects.record_overleaf_links(
            session=session, project=project, repo=repo
        )
    return Publication.model_validate(publication)


class OverleafSyncPost(BaseModel):
    path: str


class OverleafSyncResponse(BaseModel):
    commits_from_overleaf: int
    overleaf_commit: str
    project_commit: str
    committed_overleaf: bool
    committed_project: bool


@router.post("/projects/{owner_name}/{project_name}/overleaf-syncs")
def post_project_overleaf_sync(
    owner_name: str,
    project_name: str,
    req: OverleafSyncPost,
    current_user: CurrentUser,
    session: SessionDep,
) -> OverleafSyncResponse:
    try:
        users.get_overleaf_token(session=session, user=current_user)
    except HTTPException:
        raise HTTPException(401, "Overleaf token not found")
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(project=project, user=current_user, session=session)
    ck_info = get_ck_info_from_repo(repo)
    overleaf_sync_info = calkit.overleaf.get_sync_info(
        wdir=repo.working_dir, ck_info=ck_info, fix_legacy=True
    )
    app.projects.record_overleaf_links(
        session=session, project=project, repo=repo
    )
    if Path(req.path).as_posix() in overleaf_sync_info:
        path_in_project = Path(req.path).as_posix()
    else:
        path_in_project = Path(os.path.dirname(req.path)).as_posix()
    if path_in_project not in overleaf_sync_info:
        raise HTTPException(404, "Overleaf sync info not found for path")
    overleaf_project_id = overleaf_sync_info[path_in_project]["project_id"]
    overleaf_repo = get_overleaf_repo(
        project=project,
        user=current_user,
        session=session,
        overleaf_project_id=overleaf_project_id,
    )
    try:
        res = calkit.overleaf.sync(
            main_repo=repo,
            overleaf_repo=overleaf_repo,
            path_in_project=path_in_project,
            sync_info_for_path=overleaf_sync_info[path_in_project],
            print_info=logger.info,
            no_commit=False,
        )
    except Exception as e:
        logger.info(f"Failed to sync: {e}")
        if "in the middle of an am session" in repo.git.status():
            repo.git.am("--abort")
        mixpanel.track(
            user=current_user,
            event_name="Overleaf sync failed",
            add_event_info={"path": path_in_project, "exception": str(e)},
        )
        raise HTTPException(
            400, "Overleaf sync failed; try locally with Calkit CLI"
        )
    # Push the main repo (Overleaf has already been pushed in sync)
    repo.git.push(["origin", repo.active_branch.name])
    # Get data from the result of the sync
    commits_since = res.get("commits_since_last_sync", [])
    last_overleaf_commit = res.get("overleaf_commit_after", "")
    last_project_commit = res.get("project_commit_after", "")
    committed_overleaf = res.get("committed_overleaf", False)
    committed_project = res.get("committed_project", False)
    mixpanel.track(
        user=current_user,
        event_name="Overleaf sync",
        add_event_info={
            "path": path_in_project,
            "commits_from_overleaf": len(commits_since),
            "committed_overleaf": committed_overleaf,
            "committed_project": committed_project,
        },
    )
    return OverleafSyncResponse(
        commits_from_overleaf=len(commits_since),
        overleaf_commit=last_overleaf_commit,
        project_commit=last_project_commit,
        committed_overleaf=committed_overleaf,
        committed_project=committed_project,
    )


class OverleafSyncStatusFile(BaseModel):
    path: str
    project_path: str
    state: Literal["new", "modified", "deleted"]
    figure: bool
    # Pipeline status of the stage that produces this path, if it has one,
    # so a figure that is stale in the project can be told apart from one
    # that is merely not yet pushed to Overleaf
    stage: str | None = None
    stage_status: StageStatus | None = None


class OverleafSyncStatus(BaseModel):
    path: str
    overleaf_project_id: str | None = None
    overleaf_url: str | None = None
    last_sync_commit: str | None = None
    project_commit: str
    overleaf_commit: str
    commits_from_overleaf: int
    files_to_push: list[OverleafSyncStatusFile]
    files_to_delete: list[OverleafSyncStatusFile]
    in_sync: bool


@router.get("/projects/{owner_name}/{project_name}/overleaf-syncs/status")
def get_project_overleaf_sync_status(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
    path: str | None = None,
    overleaf_project_id: str | None = None,
) -> list[OverleafSyncStatus]:
    """Report what an Overleaf sync would do, without doing it.

    Returns one status per synced folder, optionally narrowed to a single
    folder with ``path`` or to the folders synced with a single Overleaf
    project with ``overleaf_project_id``.
    """
    try:
        users.get_overleaf_token(session=session, user=current_user)
    except HTTPException:
        raise HTTPException(401, "Overleaf token not found")
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(project=project, user=current_user, session=session)
    ck_info = get_ck_info_from_repo(repo)
    sync_info = calkit.overleaf.get_sync_info(
        wdir=repo.working_dir, ck_info=deepcopy(ck_info)
    )
    # Reading the repo is the expensive part, so keep the link index fresh
    # while we have it, which is what makes the reverse lookup work
    app.projects.record_overleaf_links(
        session=session, project=project, repo=repo, ck_info=ck_info
    )
    if path is not None:
        path = Path(path).as_posix().rstrip("/")
        if path not in sync_info:
            raise HTTPException(404, "Overleaf sync info not found for path")
    # Stage statuses let us say whether a figure is stale in the project
    # itself, not just out of date on Overleaf. Best-effort: never fail the
    # status check over it.
    stage_statuses: dict = {}
    dvc_lock: dict = {}
    try:
        tree = app.projects.get_repo_tree_for_ref(repo, None)
        if tree.is_file("dvc.lock"):
            dvc_lock = ryaml.load(tree.read_bytes("dvc.lock").decode()) or {}
        dvc_yaml: dict = {}
        if tree.is_file("dvc.yaml"):
            dvc_yaml = ryaml.load(tree.read_bytes("dvc.yaml").decode()) or {}
        stage_statuses = compute_stage_statuses(
            dvc_yaml=dvc_yaml,
            dvc_lock=dvc_lock,
            tree=tree,
            owner_name=project.owner_account_name,
            project_name=project.name,
            fs=get_object_fs(),
            cache_token=resolve_commit_sha(repo, None),
        )
    except Exception as e:
        logger.warning(f"Failed to compute pipeline status for sync: {e}")

    def _to_status_file(file_info: dict) -> OverleafSyncStatusFile:
        stage = find_stage_for_path(file_info["project_path"], dvc_lock)
        stage_status = stage_statuses.get(stage) if stage else None
        return OverleafSyncStatusFile(
            path=file_info["path"],
            project_path=file_info["project_path"],
            state=file_info["state"],
            figure=file_info["figure"],
            stage=stage,
            stage_status=(
                StageStatus.model_validate(stage_status.model_dump())
                if stage_status is not None
                else None
            ),
        )

    resp = []
    for path_in_project, sync_info_for_path in sync_info.items():
        if path is not None and path_in_project != path:
            continue
        this_overleaf_project_id = sync_info_for_path.get("project_id")
        if (
            overleaf_project_id is not None
            and this_overleaf_project_id != overleaf_project_id
        ):
            continue
        if not this_overleaf_project_id:
            logger.info(f"No Overleaf project ID for '{path_in_project}'")
            continue
        overleaf_repo = get_overleaf_repo(
            project=project,
            user=current_user,
            session=session,
            overleaf_project_id=this_overleaf_project_id,
        )
        status = calkit.overleaf.get_sync_status(
            main_repo=repo,
            overleaf_repo=overleaf_repo,
            path_in_project=path_in_project,
            sync_info_for_path=sync_info_for_path,
            ck_info=ck_info,
        )
        resp.append(
            OverleafSyncStatus(
                path=status["path_in_project"],
                overleaf_project_id=status["overleaf_project_id"],
                overleaf_url=calkit.overleaf.project_id_to_url(
                    this_overleaf_project_id
                ),
                last_sync_commit=status["last_sync_commit"],
                project_commit=status["project_commit"],
                overleaf_commit=status["overleaf_commit"],
                commits_from_overleaf=status["commits_from_overleaf"],
                files_to_push=[
                    _to_status_file(f) for f in status["files_to_push"]
                ],
                files_to_delete=[
                    _to_status_file(f) for f in status["files_to_delete"]
                ],
                in_sync=status["in_sync"],
            )
        )
    return resp


class OverleafLinkPublic(BaseModel):
    overleaf_project_id: str
    path: str
    project_owner_name: str
    project_name: str
    project_title: str
    current_user_access: Literal["read", "write", "admin", "owner"] | None


def _indexed_overleaf_links(
    session: Session, current_user: User, overleaf_project_id: str
) -> list[OverleafLinkPublic]:
    """Read the index, dropping projects the user can't see."""
    links = session.exec(
        select(OverleafLink).where(
            OverleafLink.overleaf_project_id == overleaf_project_id
        )
    ).all()
    resp = []
    for link in links:
        project = link.project
        try:
            project = app.projects.get_project(
                owner_name=project.owner_account_name,
                project_name=project.name,
                session=session,
                current_user=current_user,
                min_access_level="read",
            )
        except HTTPException:
            continue
        resp.append(
            OverleafLinkPublic(
                overleaf_project_id=link.overleaf_project_id,
                path=link.path,
                project_owner_name=project.owner_account_name,
                project_name=project.name,
                project_title=project.title,
                current_user_access=project.current_user_access,
            )
        )
    return resp


class OverleafLookup(BaseModel):
    links: list[OverleafLinkPublic]
    # How much of the search happened, so a caller can tell "no project
    # syncs with this" apart from "not all of them have been looked at"
    projects_scanned: int
    projects_remaining: int


# A project's Overleaf links change about as often as its calkit.yaml, so
# a scan stays good for a day. ``refresh`` overrides it for the case where
# the link was only just added.
OVERLEAF_SCAN_TTL = timedelta(hours=24)
# Each unscanned project costs one GitHub request, so a single lookup does
# a bounded amount of work and reports what it left for the next one.
MAX_OVERLEAF_SCANS = 25


@router.get("/user/overleaf-syncs/{overleaf_project_id}")
def get_user_overleaf_sync(
    overleaf_project_id: str,
    current_user: CurrentUser,
    session: SessionDep,
    active_project: str | None = None,
    refresh: bool = False,
) -> OverleafLookup:
    """Find which of the user's projects syncs with an Overleaf project.

    The index answers immediately once a project has been looked at. When
    it doesn't, the user's projects are read one at a time until the one
    that syncs with this Overleaf project turns up, and what's found is
    indexed on the way so the next lookup is a single query.

    ``active_project`` is searched first, since the project someone is
    working in is overwhelmingly the one their Overleaf document belongs
    to, and finding it there avoids reading anything else.
    """
    if not refresh:
        links = _indexed_overleaf_links(
            session, current_user, overleaf_project_id
        )
        if links:
            return OverleafLookup(
                links=links, projects_scanned=0, projects_remaining=0
            )
    candidates = session.exec(
        select(Project)
        .distinct()
        .join(Project.user_access_records, isouter=True)  # type: ignore
        .where(app.projects.writable_project_clause(current_user))
        .order_by(sqlalchemy.desc(Project.created))  # type: ignore
    ).all()
    cutoff = utcnow() - OVERLEAF_SCAN_TTL
    to_scan = [
        project
        for project in candidates
        if refresh
        or project.overleaf_scanned is None
        or project.overleaf_scanned < cutoff
    ]
    if active_project and active_project.count("/") == 1:
        hint_owner, hint_name = active_project.split("/")
        to_scan.sort(
            key=lambda project: (
                project.owner_account_name.lower() != hint_owner.lower()
                or project.name.lower() != hint_name.lower()
            )
        )
    scanned = 0
    for project in to_scan[:MAX_OVERLEAF_SCANS]:
        app.projects.scan_overleaf_links(
            session=session, project=project, user=current_user
        )
        scanned += 1
        links = _indexed_overleaf_links(
            session, current_user, overleaf_project_id
        )
        if links:
            return OverleafLookup(
                links=links,
                projects_scanned=scanned,
                projects_remaining=max(len(to_scan) - scanned, 0),
            )
    return OverleafLookup(
        links=_indexed_overleaf_links(
            session, current_user, overleaf_project_id
        ),
        projects_scanned=scanned,
        projects_remaining=max(len(to_scan) - scanned, 0),
    )


@router.post("/projects/{owner_name}/{project_name}/syncs")
def post_project_sync(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> Message:
    """Synchronize a project with its Git repo.

    Do we actually need this? It will give us a way to operate if GitHub is
    down, at least in read-only mode.
    Or perhaps we can bidirectionally sync, allowing users to update Calkit
    entities and we'll commit them back on sync.
    It would probably be better to use Git for that, so we can handle
    asynchronous edits with merges.
    """
    # First refresh the local cache of the repo
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    get_repo(project=project, user=current_user, session=session, ttl=None)
    # Get and save project questions
    # Figures
    # Datasets
    # Publications
    # TODO: Update files in Git repo with IDs?
    return Message(message="success")


@router.get("/projects/{owner_name}/{project_name}/pipeline")
def get_project_pipeline(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> Pipeline | None:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    # Read files at the requested ref rather than the live checkout, which
    # always reflects the default branch (get_repo only fetches a ref, it
    # does not check it out).
    tree = app.projects.get_repo_tree_for_ref(repo, ref)
    # See if we can read a Calkit pipeline
    calkit_content = None
    ck_info = app.projects.get_ck_info_for_ref(
        project=project, repo=repo, ref=ref
    )
    if "pipeline" in ck_info:
        stream = io.StringIO()
        ryaml.dump({"pipeline": ck_info["pipeline"]}, stream)
        calkit_content = stream.getvalue()
    if tree.is_file("dvc.yaml"):
        dvc_content = tree.read_text("dvc.yaml")
        dvc_pipeline = ryaml.load(dvc_content)
    elif (ck_info.get("pipeline") or {}).get("stages"):
        # A Calkit pipeline can be declared before it has ever been run,
        # e.g., right after creating a publication from a template, in which
        # case no dvc.yaml has been compiled and committed yet. Compile in
        # memory so the pipeline still shows up.
        try:
            stages = calkit.pipeline.to_dvc(
                ck_info=ck_info,
                wdir=str(repo.working_dir),
                write=False,
                manage_gitignore=False,
            )
        except Exception as e:
            logger.warning(
                f"Failed to compile Calkit pipeline for "
                f"{owner_name}/{project_name}: {e}"
            )
            return None
        dvc_pipeline = {"stages": stages}
        stream = io.StringIO()
        ryaml.dump(dvc_pipeline, stream)
        dvc_content = stream.getvalue()
    else:
        return None
    # Pop off any private stages
    for stage_name in list(dvc_pipeline.get("stages", {}).keys()):
        if stage_name.startswith("_"):
            dvc_pipeline["stages"].pop(stage_name)
    if tree.is_file("params.yaml"):
        params = ryaml.load(tree.read_text("params.yaml"))
    else:
        params = None
    # Generate Mermaid diagram
    mermaid = make_mermaid_diagram(dvc_pipeline, params=params)
    logger.info(
        f"Created Mermaid diagram for {owner_name}/{project_name}:\n{mermaid}"
    )
    # Compute per-stage staleness against the committed dvc.lock
    stage_statuses: dict = {}
    overall_status = "unknown"
    try:
        dvc_lock: dict = {}
        if tree.is_file("dvc.lock"):
            dvc_lock = ryaml.load(tree.read_bytes("dvc.lock").decode()) or {}
        stage_statuses = compute_stage_statuses(
            dvc_yaml=dvc_pipeline,
            dvc_lock=dvc_lock,
            tree=tree,
            owner_name=project.owner_account_name,
            project_name=project.name,
            cache_token=resolve_commit_sha(repo, ref),
        )
        overall_status = calc_overall_pipeline_status(stage_statuses)
        mermaid = color_mermaid_by_status(mermaid, stage_statuses)
    except Exception as e:
        logger.warning(f"Failed to compute pipeline status: {e}")
    return Pipeline(
        dvc_stages=dvc_pipeline["stages"],
        mermaid=mermaid,
        dvc_yaml=dvc_content,
        calkit_yaml=calkit_content,
        ck_stages=list((ck_info.get("pipeline") or {}).get("stages") or {}),
        stage_statuses=stage_statuses,
        status=overall_status,
    )


def _abs_path_within(root: str, rel_path: str) -> str:
    """Resolve ``rel_path`` under ``root``, refusing anything that escapes it.

    Paths that reach us from a request body are only ever meant to name
    something inside the project's clone, so one that resolves outside it is
    a bad request rather than a file to go read.
    """
    root_real = os.path.realpath(root)
    resolved = os.path.realpath(os.path.join(root_real, rel_path))
    if resolved != root_real and not resolved.startswith(root_real + os.sep):
        raise HTTPException(422, f"Path is outside the project: {rel_path}")
    return resolved


def _load_ck_stage_map(stage_yaml: str) -> Any:
    """Parse one stage's YAML, keeping key order and comments.

    ``ryaml`` is round-trip, so what comes back is a CommentedMap that
    dumps in the order it was written. Everything here works on that map
    rather than on a model dump, which would come back in the model's
    field order and drop the author's comments.
    """
    try:
        stage_map = ryaml.load(stage_yaml)
    except Exception as e:
        raise HTTPException(422, f"Invalid YAML: {e}")
    if not isinstance(stage_map, dict):
        raise HTTPException(422, "A stage must be a YAML mapping")
    return stage_map


def _validate_ck_stage(stage_map: Any, stage_name: str) -> CkStage:
    """Check a stage against the models, returning the parsed stage.

    Validation goes through the same discriminated union the CLI uses, so
    an unknown kind or a missing required field is a 422 here rather than
    a broken pipeline later.
    """
    try:
        # Validating as a one-stage pipeline gets the kind-based dispatch
        # (and the name/key consistency check) for free.
        stage = CkPipeline(stages={stage_name: dict(stage_map)}).stages[
            stage_name
        ]
    except Exception as e:
        raise HTTPException(422, f"Invalid stage: {e}")
    # Pipeline validation fills in name from the key, which is redundant
    # with the key itself in calkit.yaml.
    stage.name = None
    return stage


def _dump_ck_stage_map(stage_map: Any) -> str:
    stream = io.StringIO()
    ryaml.dump(stage_map, stream)
    return stream.getvalue()


@router.get(
    "/projects/{owner_name}/{project_name}/pipeline/stages/{stage_name}"
)
def get_project_pipeline_stage(
    owner_name: str,
    project_name: str,
    stage_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> PipelineStage:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    ck_info = app.projects.get_ck_info_for_ref(
        project=project, repo=repo, ref=ref
    )
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    if stage_name not in stages:
        raise HTTPException(404, "Stage not found")
    # Handed back exactly as written, comments and all. Tidying it up is the
    # "Remove empty/default keys" action, not something a read does silently.
    return PipelineStage(
        name=stage_name, yaml=_dump_ck_stage_map(stages[stage_name])
    )


@router.post(
    "/projects/{owner_name}/{project_name}/pipeline/stages/{stage_name}"
    "/remove-defaults"
)
def remove_project_pipeline_stage_defaults(
    owner_name: str,
    project_name: str,
    stage_name: str,
    req: PipelineStageEdit,
    current_user: CurrentUser,
    session: SessionDep,
) -> PipelineStageEdited:
    """Drop keys the stage leaves at their default.

    Older versions of Calkit wrote every optional field out, so a stage
    can carry a dozen nulls that say nothing. Removing them is offered as
    an action rather than done on save, since it's the user's file and
    their call. Remaining keys keep the order and comments they had.
    """
    app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    stage_map = _load_ck_stage_map(req.yaml)
    stage = _validate_ck_stage(stage_map, stage_name)
    # to_ck_dict is exactly the non-default fields, so anything absent from
    # it is a default worth dropping. Deleting in place leaves every
    # surviving key where the author put it.
    keep = stage.to_ck_dict()
    # `slurm:` is renamed to `scheduler:` when the stage is loaded, so a stage
    # still using the legacy spelling has no `slurm` key in the dump and would
    # look like a default worth dropping -- dropping it would delete the
    # scheduler config outright. Keep it under the name the author wrote.
    if "slurm" in stage_map and "scheduler" in keep:
        keep["slurm"] = keep.pop("scheduler")
    removed = [key for key in stage_map if key not in keep]
    for key in removed:
        del stage_map[key]
    return PipelineStageEdited(
        yaml=_dump_ck_stage_map(stage_map), changed=removed
    )


@router.post(
    "/projects/{owner_name}/{project_name}/pipeline/stages/{stage_name}"
    "/detect-inputs"
)
def detect_project_pipeline_stage_inputs(
    owner_name: str,
    project_name: str,
    stage_name: str,
    req: PipelineStageEdit,
    current_user: CurrentUser,
    session: SessionDep,
) -> PipelineStageEdited:
    """Add the files a LaTeX stage's document reads to its inputs.

    LaTeX resolves its class, style, bibliography, and figure files itself,
    so they're invisible to the pipeline unless declared -- and undeclared,
    a change to the class file doesn't rebuild the paper and the in-browser
    editor can't compile it. Returns the stage with anything found merged
    in, so the user sees what would be added before saving.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    stage_map = _load_ck_stage_map(req.yaml)
    stage = _validate_ck_stage(stage_map, stage_name)
    if not isinstance(stage, CkLatexStage):
        raise HTTPException(
            422, "Inputs can only be detected for LaTeX stages"
        )
    # `wdir` and `target_path` come straight off the request body, and the
    # stage models type them as plain strings, so they can climb out of the
    # clone with `..`. Everything below reads files, so pin both inside the
    # project before touching the filesystem.
    root = str(repo.working_dir)
    wdir = _abs_path_within(root, stage.wdir or "")
    _abs_path_within(wdir, stage.target_path)
    # An input can be a directory, so anything already covered by one is
    # left off rather than listed again underneath it.
    added = calkit.detect.filter_covered_inputs(
        calkit.latex.detect_inputs(stage.target_path, wdir=wdir),
        [i for i in stage.inputs if isinstance(i, str)],
    )
    if added:
        # Appending to the existing list (rather than replacing the key)
        # keeps `inputs` where the author put it, with its comments.
        stage_map.setdefault("inputs", [])
        for path in added:
            stage_map["inputs"].append(path)
    return PipelineStageEdited(
        yaml=_dump_ck_stage_map(stage_map), changed=added
    )


@router.put(
    "/projects/{owner_name}/{project_name}/pipeline/stages/{stage_name}"
)
def put_project_pipeline_stage(
    owner_name: str,
    project_name: str,
    stage_name: str,
    req: PipelineStagePut,
    current_user: CurrentUser,
    session: SessionDep,
) -> PipelineStage:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    # Write into the file as it is on disk, not the include-processed view,
    # so a project that splits its pipeline across files keeps that split.
    ck_info = get_ck_info_from_repo(repo=repo, process_includes=False)
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    if stage_name not in stages:
        raise HTTPException(404, "Stage not found")
    stage_map = _load_ck_stage_map(req.yaml)
    # Validated but written as the user wrote it: same key order, same
    # comments. Tidying is the "remove defaults" action, not a side effect
    # of saving.
    _validate_ck_stage(stage_map, stage_name)
    stages[stage_name] = stage_map
    ck_info["pipeline"]["stages"] = stages
    with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    if repo.is_dirty():
        repo.git.commit(
            ["-m", req.message or f"Update pipeline stage {stage_name}"]
        )
        repo.git.push(["origin", repo.active_branch.name])
    return PipelineStage(name=stage_name, yaml=_dump_ck_stage_map(stage_map))


class Collaborator(BaseModel):
    user_id: uuid.UUID | None = None
    # None for native (GitHub-less) collaborators added by email.
    github_username: str | None = None
    # The Calkit account name, shown when there's no GitHub username.
    account_name: str | None = None
    full_name: str | None = None
    email: str | None = None
    access_level: str


@router.get("/projects/{owner_name}/{project_name}/collaborators")
def get_project_collaborators(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> list[Collaborator]:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    # TODO: GitHub requires higher permissions to get collaborators
    # Maybe for read-only people we should return contributors?
    collabs = []
    listed_user_ids: set[uuid.UUID] = set()
    github_repo = project.github_repo
    # GitHub repo collaborators (best-effort: a GitHub-less viewer uses the App
    # token; if listing fails we still return native members below rather than
    # erroring the whole page).
    token = (
        _github_token_for_repo(session, current_user, github_repo)
        if github_repo
        else None
    )
    if github_repo and token:
        url = f"https://api.github.com/repos/{github_repo}/collaborators"
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 200:
            for gh_user in resp.json():
                # TODO: Organization handling
                if gh_user["type"] != "User":
                    continue
                user = session.exec(
                    select(User).where(
                        User.github_username == gh_user["login"]
                    )
                ).first()
                obj = dict(
                    github_username=gh_user["login"],
                    access_level=gh_user["role_name"],
                )
                if user is not None:
                    obj["email"] = user.email
                    obj["full_name"] = user.full_name
                    obj["account_name"] = user.account.name
                    obj["user_id"] = user.id
                    listed_user_ids.add(user.id)
                collabs.append(Collaborator.model_validate(obj))
        else:
            logger.warning(
                f"Could not list GitHub collaborators for {github_repo}: "
                f"{resp.status_code}"
            )
    # Native (GitHub-less) members granted via an invite or a direct add.
    native = session.exec(
        select(User, UserProjectAccess.role_id)
        .join(UserProjectAccess, UserProjectAccess.user_id == User.id)  # type: ignore[arg-type]
        .where(UserProjectAccess.project_id == project.id)
        .where(UserProjectAccess.role_id.is_not(None))  # type: ignore
    ).all()
    for user, role_id in native:
        if user.id in listed_user_ids:
            continue
        collabs.append(
            Collaborator.model_validate(
                dict(
                    user_id=user.id,
                    github_username=user.github_username,
                    account_name=user.account.name,
                    full_name=user.full_name,
                    email=user.email,
                    access_level=ROLE_NAMES[role_id],
                )
            )
        )
    return collabs


@router.put(
    "/projects/{owner_name}/{project_name}/collaborators/{github_username}"
)
def put_project_collaborator(
    owner_name: str,
    project_name: str,
    github_username: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> Message:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="admin",
    )
    user = session.exec(
        select(User)
        .join(Account, Account.user_id == User.id)  # type: ignore[arg-type]
        .where(Account.github_name == github_username)
    ).first()
    if user is None:
        raise HTTPException(404, "User not found")
    logger.info(
        f"Fetched user account {user.email} with GitHub username "
        f"{github_username}"
    )
    token = users.get_github_token(session=session, user=current_user)
    url = (
        f"https://api.github.com/repos/{project.github_repo}/"
        f"collaborators/{github_username}"
    )
    resp = requests.put(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code >= 400:
        logger.error(
            f"Failed to put collaborator ({resp.status_code}): {resp.text}"
        )
        raise HTTPException(resp.status_code)
    access = session.exec(
        select(UserProjectAccess)
        .where(UserProjectAccess.user_id == user.id)
        .where(UserProjectAccess.project_id == project.id)
    ).first()
    if access is not None:
        access.github_access = "write"
    else:
        session.add(
            UserProjectAccess(
                user_id=user.id, project_id=project.id, github_access="write"
            )
        )
    session.commit()
    return Message(message="Success")


@router.delete(
    "/projects/{owner_name}/{project_name}/collaborators/{github_username}"
)
def delete_project_collaborator(
    owner_name: str,
    project_name: str,
    github_username: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> Message:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="admin",
    )
    user = session.exec(
        select(User)
        .join(Account, Account.user_id == User.id)  # type: ignore[arg-type]
        .where(Account.github_name == github_username)
    ).first()
    if user is None:
        raise HTTPException(404, "User not found")
    logger.info(
        f"Fetched user account {user.email} with GitHub username "
        f"{github_username}"
    )
    token = users.get_github_token(session=session, user=current_user)
    url = (
        f"https://api.github.com/repos/{project.github_repo}/"
        f"collaborators/{github_username}"
    )
    resp = requests.delete(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code >= 400:
        logger.error(
            f"Failed to delete collaborator ({resp.status_code}): {resp.text}"
        )
        raise HTTPException(resp.status_code)
    access = session.exec(
        select(UserProjectAccess)
        .where(UserProjectAccess.user_id == user.id)
        .where(UserProjectAccess.project_id == project.id)
    ).first()
    if access is not None:
        access.github_access = None
    else:
        session.add(
            UserProjectAccess(
                user_id=user.id, project_id=project.id, github_access=None
            )
        )
    session.commit()
    return Message(message="Success")


class NativeCollaboratorPost(BaseModel):
    email: str


@router.post("/projects/{owner_name}/{project_name}/collaborators/by-email")
def post_project_collaborator_by_email(
    owner_name: str,
    project_name: str,
    req: NativeCollaboratorPost,
    current_user: CurrentUser,
    session: SessionDep,
) -> Message:
    """Grant native (non-GitHub) write access to an existing Calkit user by
    email -- how a GitHub-less collaborator is added. For people who don't have
    a Calkit account yet, use an invite link instead.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="admin",
    )
    user = users.get_user_by_email(session=session, email=req.email)
    if user is None:
        raise HTTPException(
            404,
            "No Calkit user has that email. Send them an invite link to join.",
        )
    if user.id == project.owner_account.user_id:
        raise HTTPException(400, "That user already owns this project.")
    write_role = ROLE_IDS["write"]
    existing = session.exec(
        select(UserProjectAccess)
        .where(UserProjectAccess.project_id == project.id)
        .where(UserProjectAccess.user_id == user.id)
    ).first()
    if existing is None:
        session.add(
            UserProjectAccess(
                user_id=user.id,
                project_id=project.id,
                role_id=write_role,
                invited_by_user_id=current_user.id,
            )
        )
    elif existing.role_id is None or existing.role_id < write_role:
        existing.role_id = write_role
        if existing.invited_by_user_id is None:
            existing.invited_by_user_id = current_user.id
        session.add(existing)
    session.commit()
    return Message(message="Success")


@router.delete(
    "/projects/{owner_name}/{project_name}/collaborators/by-user/{user_id}"
)
def delete_project_native_collaborator(
    owner_name: str,
    project_name: str,
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: SessionDep,
) -> Message:
    """Revoke a native (non-GitHub) collaborator's access. GitHub collaborators
    are removed via the github-username endpoint instead.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="admin",
    )
    row = session.exec(
        select(UserProjectAccess)
        .where(UserProjectAccess.project_id == project.id)
        .where(UserProjectAccess.user_id == user_id)
    ).first()
    if row is None or row.role_id is None:
        raise HTTPException(404, "Collaborator not found")
    # Drop the native grant; any cached GitHub-derived access is left as-is.
    row.role_id = None
    row.invited_by_user_id = None
    session.add(row)
    session.commit()
    return Message(message="Success")


@router.post("/projects/{owner_name}/{project_name}/invitations")
def post_project_invitation(
    owner_name: str,
    project_name: str,
    req: ProjectInvitationPost,
    current_user: CurrentUser,
    session: SessionDep,
) -> ProjectInvitationCreated:
    """Create a shareable invite link granting native project membership.

    The raw token is returned only here; the DB stores its hash. Invite links
    grant collaborator access only (read or write) — never admin or ownership;
    admins must be added deliberately, not via a shareable link.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="admin",
    )
    token = generate_refresh_token()
    expires = (
        utcnow() + timedelta(days=req.expires_days)
        if req.expires_days is not None
        else None
    )
    invitation = ProjectInvitation(
        project_id=project.id,
        token_hash=hash_refresh_token(token),
        role_id=ROLE_IDS[req.role],
        name=req.name,
        email=req.email,
        created_by_user_id=current_user.id,
        expires=expires,
        max_uses=req.max_uses,
    )
    session.add(invitation)
    session.commit()
    session.refresh(invitation)
    url = f"{settings.frontend_host.rstrip('/')}/join/{token}"
    # Best-effort: email the link if a recipient was given and SMTP is set up.
    # Never fail the request over email; the creator still gets the copyable URL.
    emailed = False
    if req.email and settings.emails_enabled:
        inviter = current_user.full_name or current_user.email
        email_data = messaging.generate_project_invitation_email(
            email_to=req.email,
            project_name=project.name,
            link=url,
            inviter=inviter,
            role=req.role,
        )
        try:
            messaging.send_email(
                email_to=req.email,
                subject=email_data.subject,
                html_content=email_data.html_content,
            )
            emailed = True
        except Exception:
            logger.exception(f"Failed to send invite email to {req.email}")
    return ProjectInvitationCreated(
        id=invitation.id,
        name=invitation.name,
        email=invitation.email,
        role_name=invitation.role_name,
        created=invitation.created,
        expires=invitation.expires,
        max_uses=invitation.max_uses,
        use_count=invitation.use_count,
        revoked=invitation.revoked,
        token=token,
        url=url,
        emailed=emailed,
    )


@router.get("/projects/{owner_name}/{project_name}/invitations")
def get_project_invitations(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> list[ProjectInvitationPublic]:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="admin",
    )
    invitations = session.exec(
        select(ProjectInvitation)
        .where(ProjectInvitation.project_id == project.id)
        .order_by(sqlalchemy.desc(ProjectInvitation.created))  # type: ignore
    ).all()
    return list(invitations)  # type: ignore[return-value]


@router.delete(
    "/projects/{owner_name}/{project_name}/invitations/{invitation_id}"
)
def delete_project_invitation(
    owner_name: str,
    project_name: str,
    invitation_id: uuid.UUID,
    current_user: CurrentUser,
    session: SessionDep,
) -> Message:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="admin",
    )
    invitation = session.get(ProjectInvitation, invitation_id)
    if invitation is None or invitation.project_id != project.id:
        raise HTTPException(404, "Invitation not found")
    invitation.revoked = True
    session.add(invitation)
    session.commit()
    return Message(message="Invitation revoked")


@router.post("/project-invitations/{token}")
def post_project_invitation_redemption(
    token: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> ProjectInvitationRedeemed:
    """Redeem an invite link, granting the current user native membership."""
    # Lock the invitation row for the transaction so concurrent redemptions
    # serialize: without this, two redeems can both read the same use_count,
    # both pass is_valid, and both increment past max_uses.
    invitation = session.exec(
        select(ProjectInvitation)
        .where(ProjectInvitation.token_hash == hash_refresh_token(token))
        .with_for_update()
    ).first()
    if invitation is None:
        raise HTTPException(404, "Invitation not found")
    if not invitation.is_valid:
        raise HTTPException(410, "Invitation is no longer valid")
    project = session.get(Project, invitation.project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    # Project owners already have full access; don't create a lesser membership.
    if project.owner_account.user_id == current_user.id:
        return ProjectInvitationRedeemed(
            owner_name=project.owner_account.name,
            project_name=project.name,
            role_name="owner",
        )
    # Invite links never confer more than collaborator (write) access, even if
    # a legacy link was created with a higher role. Admins are added directly.
    granted_role_id = min(invitation.role_id, ROLE_IDS["write"])
    existing = session.exec(
        select(UserProjectAccess)
        .where(UserProjectAccess.project_id == project.id)
        .where(UserProjectAccess.user_id == current_user.id)
    ).first()
    if existing is None:
        session.add(
            UserProjectAccess(
                user_id=current_user.id,
                project_id=project.id,
                role_id=granted_role_id,
                invited_by_user_id=invitation.created_by_user_id,
            )
        )
    elif existing.role_id is None or granted_role_id > existing.role_id:
        # Grant, or upgrade if the invite confers more than they already have
        # (the row may have existed as GitHub-derived access with no role_id).
        existing.role_id = granted_role_id
        if existing.invited_by_user_id is None:
            existing.invited_by_user_id = invitation.created_by_user_id
        session.add(existing)
    invitation.use_count += 1
    session.add(invitation)
    session.commit()
    return ProjectInvitationRedeemed(
        owner_name=project.owner_account.name,
        project_name=project.name,
        role_name=invitation.role_name,
    )


class Issue(BaseModel):
    id: int
    number: int
    url: str
    user_github_username: str
    state: Literal["open", "closed"]
    title: str
    body: str | None
    artifact_type: str | None = None
    artifact_path: str | None = None


@router.get("/projects/{owner_name}/{project_name}/issues")
def get_project_issues(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    page: int = 1,
    per_page: int = 30,
    state: Literal["open", "closed", "all"] = "open",
) -> list[Issue]:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    github_repo = project.github_repo
    headers = None
    if github_repo is None:
        raise HTTPException(501)
    if current_user is not None:
        token = _github_token_for_repo(session, current_user, github_repo)
        if token is not None:
            headers = {"Authorization": f"Bearer {token}"}
    url = f"https://api.github.com/repos/{github_repo}/issues"
    resp = requests.get(
        url,
        headers=headers,
        params=dict(page=page, per_page=per_page, state=state),
    )
    if not resp.status_code == 200:
        raise HTTPException(resp.status_code, resp.json()["message"])
    resp_json = resp.json()
    # Build a map from GitHub issue URL → (artifact_type, artifact_path)
    # for issues that were created from project comments
    db_comments = session.exec(
        select(ProjectComment).where(
            ProjectComment.project_id == project.id,
            ProjectComment.external_url.is_not(None),  # type: ignore[union-attr]
        )
    ).all()
    comment_by_url: dict[str, ProjectComment] = {
        c.external_url: c for c in db_comments if c.external_url
    }
    resp_fmt = []
    for issue in resp_json:
        linked = comment_by_url.get(issue["html_url"])
        resp_fmt.append(
            Issue(
                id=issue["id"],
                number=issue["number"],
                url=issue["html_url"],
                user_github_username=issue["user"]["login"],
                state=issue["state"],
                title=issue["title"],
                body=issue["body"],
                artifact_type=linked.artifact_type if linked else None,
                artifact_path=linked.artifact_path if linked else None,
            )
        )
    return resp_fmt


class IssuePost(BaseModel):
    title: str
    body: str | None = None


@router.post("/projects/{owner_name}/{project_name}/issues")
def post_project_issue(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
    req: IssuePost,
) -> Issue:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    if project.github_repo is None:
        raise HTTPException(501)
    token = _github_token_for_repo(session, current_user, project.github_repo)
    if token is None:
        raise HTTPException(
            502, "Could not authenticate with GitHub to create the issue"
        )
    body = f"{_make_github_authorship_prefix(current_user)}{req.body or ''}"
    url = f"https://api.github.com/repos/{project.github_repo}/issues"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"title": req.title, "body": body},
    )
    if resp.status_code != 201:
        logger.error(f"Call to post issue failed ({resp.status_code})")
        raise HTTPException(resp.status_code)
    resp_json = resp.json()
    return Issue.model_validate(
        resp_json
        | dict(
            user_github_username=resp_json["user"]["login"],
            url=resp_json["html_url"],
        )
    )


class IssuePatch(BaseModel):
    state: Literal["open", "closed"]


@router.patch("/projects/{owner_name}/{project_name}/issues/{issue_number}")
def patch_project_issue(
    owner_name: str,
    project_name: str,
    issue_number: int,
    req: IssuePatch,
    current_user: CurrentUser,
    session: SessionDep,
) -> Message:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    if project.github_repo is None:
        raise HTTPException(501)
    # Use the App-token fallback so GitHub-less collaborators can close/reopen
    # issues too (consistent with creating and commenting on them).
    token = _github_token_for_repo(session, current_user, project.github_repo)
    if token is None:
        raise HTTPException(
            502, "Could not authenticate with GitHub to update the issue"
        )
    url = (
        f"https://api.github.com/repos/{project.github_repo}/"
        f"issues/{issue_number}"
    )
    resp = requests.patch(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=req.model_dump(),
    )
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, resp.json()["message"])
    return Message(message="Success")


class ImportInfo(BaseModel):
    project_owner: str
    project_name: str
    git_rev: str | None = None
    path: str


class ReferenceEntry(BaseModel):
    type: str
    key: str
    file_path: str | None = None
    url: str | None = None
    attrs: dict
    # Set when the entry is an arXiv paper, so the PDF can be fetched even
    # though nothing is stored in the repo.
    arxiv_id: str | None = None
    # Zotero linkage (populated for Zotero-linked collections).
    zotero_item_key: str | None = None
    has_pdf: bool = False
    note_count: int = 0


class ReferenceFile(BaseModel):
    path: str
    key: str


class ReferenceZoteroLink(BaseModel):
    library_type: Literal["user", "group"]
    library_id: str
    collection_key: str
    collection_name: str | None = None
    # Populated from .calkit/zotero/sync.json at read time, not calkit.yaml.
    last_sync_version: int | None = None
    last_synced: str | None = None


class References(BaseModel):
    path: str
    files: list[ReferenceFile] | None = None
    entries: list[ReferenceEntry] | None = None
    imported_from: ImportInfo | None = None
    raw_text: str | None = None
    zotero: ReferenceZoteroLink | None = None
    # Names of pipeline stages that consume this .bib as a dependency/input.
    stages: list[str] | None = None


@router.get("/projects/{owner_name}/{project_name}/references")
def get_project_references(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> list[References]:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    ck_info = get_ck_info_from_repo(repo)
    # An empty "references:" key in calkit.yaml parses to None.
    ref_collections = ck_info.get("references") or []
    declared_paths = {
        rc.get("path") for rc in ref_collections if isinstance(rc, dict)
    }
    # Auto-detect undeclared .bib files in the repo tree
    try:
        commit = repo.commit(ref) if ref else repo.head.commit
        for blob in commit.tree.traverse():
            if blob.type != "blob":  # type: ignore[union-attr]
                continue
            path: str = blob.path  # type: ignore[union-attr]
            parts = path.split("/")
            if any(p.startswith(".") for p in parts):
                continue
            if not path.lower().endswith(".bib"):
                continue
            if path in declared_paths:
                continue
            ref_collections.append({"path": path})
    except Exception as e:
        logger.warning(f"Failed to scan for undeclared references: {e}")
    # Map each pipeline dependency path to the stages that consume it, so we can
    # tell whether a .bib is actually used by the pipeline. Reads both
    # calkit.yaml's ``pipeline.stages`` (uses ``inputs``) and the generated
    # dvc.yaml (uses ``deps``), since either may be absent or stale.
    dep_path_to_stages: dict[str, list[str]] = {}

    def _register_deps(stages: dict, key: str) -> None:
        for stage_name, stage_def in (stages or {}).items():
            if not isinstance(stage_def, dict):
                continue
            for dep in stage_def.get(key, []) or []:
                dep_path = dep.get("path") if isinstance(dep, dict) else dep
                if not isinstance(dep_path, str) or "{" in dep_path:
                    continue
                norm = os.path.normpath(dep_path)
                dep_path_to_stages.setdefault(norm, [])
                if stage_name not in dep_path_to_stages[norm]:
                    dep_path_to_stages[norm].append(stage_name)

    try:
        dvc_pipeline = app.projects.get_dvc_pipeline_for_ref(repo, ref)
        _register_deps(
            (ck_info.get("pipeline") or {}).get("stages") or {}, "inputs"
        )
        _register_deps(dvc_pipeline.get("stages") or {}, "deps")
    except Exception as e:
        logger.warning(f"Failed to read pipeline deps for references: {e}")
    # Local Zotero state (sync version/timestamp, item map), merged into the
    # durable link read from calkit.yaml. Notes live in each entry's comment
    # field, not here.
    zotero_sync_info = zotero.read_sync_info(repo.working_dir)
    zotero_items_info = zotero.read_items_info(repo.working_dir)
    # For older links whose name wasn't cached, resolve it from Zotero once for
    # the signed-in owner so the panel shows a name, not the raw key. Best-effort
    # and not persisted here (a sync caches it for everyone).
    zotero_api_key: str | None = None
    zotero_key_tried = False
    resp = []
    for ref_collection in ref_collections:
        # Skip malformed YAML entries rather than 500ing on them.
        if (
            not isinstance(ref_collection, dict)
            or "path" not in ref_collection
        ):
            continue
        # Read entries
        path = ref_collection["path"]
        # The Zotero link is private (.calkit/zotero/sync.json), not in
        # calkit.yaml, which just lists the collection paths.
        state = zotero_sync_info.get(path)
        if isinstance(state, dict) and state.get("collection_key"):
            collection_name = state.get("collection_name")
            if not collection_name and current_user is not None:
                if not zotero_key_tried:
                    zotero_key_tried = True
                    try:
                        zotero_api_key, _ = (
                            users.get_zotero_api_key_and_user_id(
                                session=session, user=current_user
                            )
                        )
                    except HTTPException:
                        zotero_api_key = None
                if zotero_api_key:
                    try:
                        collection_name = zotero.get_collection_name(
                            api_key=zotero_api_key,
                            library_type=state["library_type"],
                            library_id=state["library_id"],
                            collection_key=state["collection_key"],
                        )
                    except HTTPException:
                        collection_name = None
            ref_collection["zotero"] = {
                "library_type": state.get("library_type"),
                "library_id": state.get("library_id"),
                "collection_key": state.get("collection_key"),
                "collection_name": collection_name,
                "last_sync_version": state.get("last_sync_version"),
                "last_synced": state.get("last_synced"),
            }
        else:
            ref_collection.pop("zotero", None)
        # Which pipeline stages use this .bib, matching the path itself or any
        # ancestor directory a stage may depend on.
        norm_path = os.path.normpath(path)
        stage_names: list[str] = []
        candidate = norm_path
        while candidate not in (".", "/", ""):
            for stage_name in dep_path_to_stages.get(candidate, []):
                if stage_name not in stage_names:
                    stage_names.append(stage_name)
            candidate = os.path.dirname(candidate)
        ref_collection["stages"] = sorted(stage_names)
        items_map = zotero_items_info.get(path, {})
        if os.path.isfile(os.path.join(repo.working_dir, path)):
            with open(os.path.join(repo.working_dir, path)) as f:
                raw_text = f.read()
            ref_collection["raw_text"] = raw_text
            try:
                refs = bibtexparser.loads(raw_text)
                entries = refs.entries
            except Exception as e:
                logger.warning(f"Failed to parse BibTeX file {path}: {e}")
                entries = []
            final_entries = []
            file_paths = {
                f["key"]: f["path"] for f in ref_collection.get("files", [])
            }
            for entry in entries:
                key = entry.pop("ID")
                reftype = entry.pop("ENTRYTYPE")
                file_path = file_paths.get(key)
                url = None
                item = items_map.get(key, {})
                # Notes live in the comment field; surface as a count, not a
                # raw attribute.
                comment = entry.pop(BIB_NOTE_FIELD, None)
                note_count = len(zotero.parse_notes_markdown(comment or ""))
                # If a file path is defined, read it and get the presigned URL
                if file_path is not None:
                    logger.info(f"Looking for reference file: {file_path}")
                    try:
                        contents_item = app.projects.get_contents_from_repo(
                            project=project,
                            repo=repo,
                            path=file_path,
                            ref=ref,
                        )
                        url = contents_item.url
                    except HTTPException as e:
                        logger.warning(
                            f"Could not find contents for {key}: {e}"
                        )
                final_entries.append(
                    ReferenceEntry.model_validate(
                        dict(
                            key=key,
                            type=reftype,
                            attrs=entry,
                            file_path=file_path,
                            url=url,
                            arxiv_id=arxiv.id_from_bib_attrs(entry),
                            zotero_item_key=item.get("item_key"),
                            has_pdf=bool(item.get("pdf_attachment_keys")),
                            note_count=note_count,
                        )
                    )
                )
            ref_collection["entries"] = final_entries
        resp.append(References.model_validate(ref_collection))
    return resp


class ReferencesPost(BaseModel):
    path: str
    # When True, register an existing ``.bib`` file rather than creating a new,
    # empty one. The file must already exist in the repo.
    label_existing: bool = False


@router.post("/projects/{owner_name}/{project_name}/references")
def post_project_references(
    owner_name: str,
    project_name: str,
    req: ReferencesPost,
    current_user: CurrentUser,
    session: SessionDep,
) -> References:
    """Register a references collection (a ``.bib`` file) in ``calkit.yaml``.

    Creates a new, empty file by default, or labels an existing one when
    ``label_existing`` is set.
    """
    if not req.path.lower().endswith(".bib"):
        raise HTTPException(422, "Path must end with '.bib'")
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(project=project, user=current_user, session=session)
    ck_info = get_ck_info_from_repo(repo)
    # An empty "references:" key in calkit.yaml parses to None, so coerce to a
    # list before iterating.
    references = ck_info.get("references") or []
    if any(
        isinstance(rc, dict) and rc.get("path") == req.path
        for rc in references
    ):
        raise HTTPException(
            409, "A references collection with that path exists"
        )
    bib_full_path = os.path.join(repo.working_dir, req.path)
    if req.label_existing:
        if not os.path.isfile(bib_full_path):
            raise HTTPException(404, f"'{req.path}' not found in the repo")
    else:
        if os.path.exists(bib_full_path):
            raise HTTPException(
                409, f"'{req.path}' already exists in the repo"
            )
        os.makedirs(os.path.dirname(bib_full_path) or ".", exist_ok=True)
        with open(bib_full_path, "w") as f:
            f.write("")
    references.append({"path": req.path})
    ck_info["references"] = references
    with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add(req.path)
    repo.git.add("calkit.yaml")
    verb = "Label" if req.label_existing else "Add"
    repo.git.commit(["-m", f"{verb} references collection '{req.path}'"])
    repo.git.push(["origin", repo.active_branch.name])
    mixpanel.track(
        user=current_user,
        event_name="Created references collection",
        add_event_info={
            "path": req.path,
            "label_existing": req.label_existing,
        },
    )
    return References.model_validate({"path": req.path})


@router.delete("/projects/{owner_name}/{project_name}/references")
def delete_project_references(
    owner_name: str,
    project_name: str,
    path: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> Message:
    """Delete a references collection.

    Removes its calkit.yaml entry, the ``.bib`` file, and all of its Zotero
    state under .calkit/zotero/ (sync link, item map, note anchors). The
    collection is only unlinked locally; the Zotero collection itself is left
    untouched.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(project=project, user=current_user, session=session)
    ck_info = get_ck_info_from_repo(repo)
    references = ck_info.get("references") or []
    kept = [
        rc
        for rc in references
        if not (isinstance(rc, dict) and rc.get("path") == path)
    ]
    bib_full_path = os.path.join(repo.working_dir, path)
    if len(kept) == len(references) and not os.path.isfile(bib_full_path):
        raise HTTPException(404, "References collection not found")
    ck_info["references"] = kept
    with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    if os.path.isfile(bib_full_path):
        os.remove(bib_full_path)
        repo.git.add(path)
    # Scrub the collection's Zotero state.
    all_items = zotero.read_items_info(repo.working_dir)
    item_map = all_items.pop(path, None)
    if item_map is not None:
        zotero.write_items_info(repo.working_dir, all_items)
        repo.git.add(["-f", zotero.ITEMS_REL_PATH])
        note_keys = {
            nk
            for info in item_map.values()
            for nk in (info.get("note_keys") or [])
        }
        if note_keys:
            anchors = zotero.read_note_anchors(repo.working_dir)
            if any(nk in anchors for nk in note_keys):
                for nk in note_keys:
                    anchors.pop(nk, None)
                zotero.write_note_anchors(repo.working_dir, anchors)
                repo.git.add(["-f", zotero.ANCHORS_REL_PATH])
    sync_info = zotero.read_sync_info(repo.working_dir)
    if sync_info.pop(path, None) is not None:
        zotero.write_sync_info(repo.working_dir, sync_info)
        repo.git.add(["-f", zotero.SYNC_INFO_REL_PATH])
    if repo.git.diff("--cached", "--name-only").strip():
        repo.git.commit(["-m", f"Delete references collection '{path}'"])
        repo.git.push(["origin", repo.active_branch.name])
    mixpanel.track(
        user=current_user,
        event_name="Deleted references collection",
        add_event_info={"path": path},
    )
    return Message(message="References collection deleted")


class ReferenceItemPost(BaseModel):
    path: str
    type: str = "article"
    key: str
    fields: dict[str, str] = {}


def _load_bib_db(repo, path: str, create: bool = False):
    """Parse a .bib file from the repo.

    With ``create``, a path that doesn't exist yet yields an empty
    database instead of a 404, so a project's first reference can be added
    without the user having to create the file first.
    """
    full_path = os.path.join(repo.working_dir, path)
    if not os.path.isfile(full_path):
        if not create:
            raise HTTPException(404, "References file not found")
        return bibtexparser.loads(""), full_path
    with open(full_path) as f:
        return bibtexparser.loads(f.read()), full_path


@router.post("/projects/{owner_name}/{project_name}/references/items")
def post_project_reference_item(
    owner_name: str,
    project_name: str,
    req: ReferenceItemPost,
    current_user: CurrentUser,
    session: SessionDep,
) -> Message:
    """Add a new entry to a references (.bib) collection.

    The entry is written to the ``.bib`` and committed. For a Zotero-linked
    collection it reaches Zotero on the next sync (which pushes local changes
    before pulling).
    """
    if not req.key.strip():
        raise HTTPException(422, "A citation key is required")
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(project=project, user=current_user, session=session)
    # Adding the first reference to a project shouldn't require creating
    # the collection by hand first
    db, full_path = _load_bib_db(repo, req.path, create=True)
    created = not os.path.isfile(full_path)
    if any(e.get("ID") == req.key for e in db.entries):
        raise HTTPException(409, f"An entry '{req.key}' already exists")
    entry = {"ENTRYTYPE": req.type, "ID": req.key}
    for field, value in req.fields.items():
        if value.strip():
            entry[field] = value.strip()
    db.entries.append(entry)
    # For a linked collection, create the item in Zotero first (records its
    # item mapping); a failure aborts before the local write so the two stay
    # consistent.
    link = _find_reference_link(repo, req.path)
    if link:
        api_key, _ = users.get_zotero_api_key_and_user_id(
            session=session, user=current_user
        )
        _push_added_reference(repo, api_key, link, req.path, req)
    os.makedirs(os.path.dirname(full_path) or ".", exist_ok=True)
    with open(full_path, "w") as f:
        f.write(zotero.format_bib(bibtexparser.dumps(db)))
    repo.git.add(req.path)
    # A brand new collection is declared in calkit.yaml too, so it shows up
    # as a real collection rather than only being found by the .bib scan
    if created:
        ck_info = get_ck_info_from_repo(repo)
        collections = ck_info.get("references") or []
        if not any(
            isinstance(c, dict) and c.get("path") == req.path
            for c in collections
        ):
            collections.append({"path": req.path})
            ck_info["references"] = collections
            with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
                ryaml.dump(ck_info, f)
            repo.git.add("calkit.yaml")
    if repo.git.diff("--cached", "--name-only").strip():
        message = (
            f"Add reference '{req.key}'"
            if not created
            else f"Add reference '{req.key}' in new collection '{req.path}'"
        )
        repo.git.commit(["-m", message])
        repo.git.push(["origin", repo.active_branch.name])
    mixpanel.track(
        user=current_user,
        event_name="Added reference item",
        add_event_info={"path": req.path},
    )
    return Message(message="Reference added")


class ReferenceItemPut(BaseModel):
    path: str
    type: str
    key: str
    fields: dict[str, str] = {}


@router.put("/projects/{owner_name}/{project_name}/references/items/{bib_key}")
def put_project_reference_item(
    owner_name: str,
    project_name: str,
    bib_key: str,
    req: ReferenceItemPut,
    current_user: CurrentUser,
    session: SessionDep,
) -> Message:
    """Edit an entry's type, key, and fields, preserving its notes.

    Provided fields are merged in (an empty value clears that field); fields not
    included are left as they are, so notes and other data survive the edit.
    """
    if not req.key.strip():
        raise HTTPException(422, "A citation key is required")
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(project=project, user=current_user, session=session)
    db, full_path = _load_bib_db(repo, req.path)
    entry = next((e for e in db.entries if e.get("ID") == bib_key), None)
    if entry is None:
        raise HTTPException(404, "Reference entry not found")
    if req.key != bib_key and any(e.get("ID") == req.key for e in db.entries):
        raise HTTPException(409, f"An entry '{req.key}' already exists")
    before = dict(entry)
    entry["ENTRYTYPE"] = req.type
    entry["ID"] = req.key
    for field, value in req.fields.items():
        if value.strip():
            entry[field] = value.strip()
        else:
            entry.pop(field, None)
    # Push the edit to Zotero first for a linked collection (this also follows a
    # key rename in the item map); a failure aborts before the local write.
    # Skip the push when nothing actually changed, so a redundant save doesn't
    # bump the Zotero version.
    link = _find_reference_link(repo, req.path)
    if link and entry != before:
        api_key, _ = users.get_zotero_api_key_and_user_id(
            session=session, user=current_user
        )
        _push_edited_reference(repo, api_key, link, req.path, bib_key, req)
    with open(full_path, "w") as f:
        f.write(zotero.format_bib(bibtexparser.dumps(db)))
    repo.git.add(req.path)
    # An edit that changes nothing leaves the working tree clean; skip the
    # commit rather than letting git error on an empty commit.
    if repo.git.diff("--cached", "--name-only").strip():
        repo.git.commit(["-m", f"Edit reference '{req.key}'"])
        repo.git.push(["origin", repo.active_branch.name])
    mixpanel.track(
        user=current_user,
        event_name="Edited reference item",
        add_event_info={"path": req.path},
    )
    return Message(message="Reference updated")


@router.delete(
    "/projects/{owner_name}/{project_name}/references/items/{bib_key}"
)
def delete_project_reference_item(
    owner_name: str,
    project_name: str,
    bib_key: str,
    path: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> Message:
    """Delete an entry from a references (.bib) collection.

    The entry is removed from the ``.bib`` and committed. For a Zotero-linked
    collection the item is deleted from Zotero too.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(project=project, user=current_user, session=session)
    db, full_path = _load_bib_db(repo, path)
    if not any(e.get("ID") == bib_key for e in db.entries):
        raise HTTPException(404, "Reference entry not found")
    db.entries = [e for e in db.entries if e.get("ID") != bib_key]
    # Delete from Zotero first for a linked collection; a failure aborts before
    # the local write so the two stay consistent.
    link = _find_reference_link(repo, path)
    if link:
        api_key, _ = users.get_zotero_api_key_and_user_id(
            session=session, user=current_user
        )
        _push_deleted_reference(repo, api_key, link, path, bib_key)
    with open(full_path, "w") as f:
        f.write(zotero.format_bib(bibtexparser.dumps(db)))
    repo.git.add(path)
    if repo.git.diff("--cached", "--name-only").strip():
        repo.git.commit(["-m", f"Delete reference '{bib_key}'"])
        repo.git.push(["origin", repo.active_branch.name])
    mixpanel.track(
        user=current_user,
        event_name="Deleted reference item",
        add_event_info={"path": path},
    )
    return Message(message="Reference deleted")


class ZoteroLibrary(BaseModel):
    library_type: Literal["user", "group"]
    library_id: str
    name: str


@router.get("/projects/{owner_name}/{project_name}/zotero/libraries")
def get_project_zotero_libraries(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> list[ZoteroLibrary]:
    """List the Zotero libraries the current user can import from."""
    app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    api_key, user_id = users.get_zotero_api_key_and_user_id(
        session=session, user=current_user
    )
    libraries = [
        ZoteroLibrary(
            library_type="user", library_id=user_id, name="My Library"
        )
    ]
    for group in zotero.get_groups(api_key=api_key, user_id=user_id):
        libraries.append(ZoteroLibrary.model_validate(group))
    return libraries


class ZoteroCollection(BaseModel):
    collection_key: str
    collection_name: str | None = None
    parent_collection: str | None = None


@router.get("/projects/{owner_name}/{project_name}/zotero/collections")
def get_project_zotero_collections(
    owner_name: str,
    project_name: str,
    library_type: Literal["user", "group"],
    library_id: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> list[ZoteroCollection]:
    """List a Zotero library's collections for the import picker."""
    app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    api_key, _ = users.get_zotero_api_key_and_user_id(
        session=session, user=current_user
    )
    collections = zotero.get_collections(
        api_key=api_key, library_type=library_type, library_id=library_id
    )
    return [ZoteroCollection.model_validate(c) for c in collections]


class ZoteroItem(BaseModel):
    item_key: str
    title: str | None = None
    item_type: str | None = None
    year: str | None = None
    first_author: str | None = None


@router.get("/projects/{owner_name}/{project_name}/zotero/items")
def get_project_zotero_items(
    owner_name: str,
    project_name: str,
    library_type: Literal["user", "group"],
    library_id: str,
    current_user: CurrentUser,
    session: SessionDep,
    q: str | None = None,
    collection_key: str | None = None,
) -> list[ZoteroItem]:
    """Search a Zotero library's items for the subset import picker."""
    app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    api_key, _ = users.get_zotero_api_key_and_user_id(
        session=session, user=current_user
    )
    items = zotero.search_items(
        api_key=api_key,
        library_type=library_type,
        library_id=library_id,
        q=q,
        collection_key=collection_key,
    )
    return [ZoteroItem.model_validate(i) for i in items]


class ZoteroImportPost(BaseModel):
    library_type: Literal["user", "group"]
    library_id: str
    # Whole-collection mode: link this existing collection directly.
    collection_key: str | None = None
    # Subset mode: create a dedicated collection seeded with these items.
    item_keys: list[str] | None = None
    bib_path: str = "references.bib"
    # Replace an existing .bib at bib_path instead of failing with 409.
    overwrite: bool = False


@router.post("/projects/{owner_name}/{project_name}/zotero/imports")
def post_project_zotero_import(
    owner_name: str,
    project_name: str,
    req: ZoteroImportPost,
    current_user: CurrentUser,
    session: SessionDep,
) -> References:
    """Import a Zotero collection into a project's references.

    Whole-collection mode links an existing collection; subset mode creates a
    dedicated "Calkit: {owner}/{project}" collection, seeds it with the chosen
    items, and links that. Either way the collection is pulled into a ``.bib``
    file and recorded in ``calkit.yaml`` for later sync.
    """
    if not req.bib_path.lower().endswith(".bib"):
        raise HTTPException(422, "bib_path must end with '.bib'")
    if bool(req.collection_key) == bool(req.item_keys):
        raise HTTPException(
            422, "Provide either collection_key or item_keys, not both"
        )
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    api_key, zotero_user_id = users.get_zotero_api_key_and_user_id(
        session=session, user=current_user
    )
    repo = get_repo(project=project, user=current_user, session=session)
    ck_info = get_ck_info_from_repo(repo)
    # Guard before any writes to Zotero, so a rejected import never leaves an
    # orphan collection behind. A .bib already on disk or declared in
    # calkit.yaml is only replaced when overwrite is set.
    references = ck_info.get("references") or []
    already_declared = any(
        isinstance(rc, dict) and rc.get("path") == req.bib_path
        for rc in references
    )
    bib_full_path = os.path.join(repo.working_dir, req.bib_path)
    if not req.overwrite and (
        already_declared or os.path.exists(bib_full_path)
    ):
        raise HTTPException(
            409,
            f"'{req.bib_path}' already exists; enable overwrite to replace",
        )
    if req.collection_key is not None:
        collection_key = req.collection_key
        collection_name = zotero.get_collection_name(
            api_key=api_key,
            library_type=req.library_type,
            library_id=req.library_id,
            collection_key=collection_key,
        )
    else:
        collection_name = f"Calkit: {owner_name}/{project_name}"
        collection_key = zotero.create_collection(
            api_key=api_key,
            library_type=req.library_type,
            library_id=req.library_id,
            name=collection_name,
        )
        zotero.add_items_to_collection(
            api_key=api_key,
            library_type=req.library_type,
            library_id=req.library_id,
            collection_key=collection_key,
            item_keys=req.item_keys or [],
        )
    library_version = _pull_zotero_collection(
        repo=repo,
        api_key=api_key,
        bib_path=req.bib_path,
        bib_full_path=bib_full_path,
        library_type=req.library_type,
        library_id=req.library_id,
        collection_key=collection_key,
    )
    # calkit.yaml just lists the collection path; the entire Zotero link is
    # private, kept in .calkit/zotero/sync.json.
    zotero_link = {
        "library_type": req.library_type,
        "library_id": req.library_id,
        "collection_key": collection_key,
    }
    for ref_collection in references:
        if (
            isinstance(ref_collection, dict)
            and ref_collection.get("path") == req.bib_path
        ):
            # Drop any link left in calkit.yaml by an older version.
            ref_collection.pop("zotero", None)
            break
    else:
        references.append({"path": req.bib_path})
    ck_info["references"] = references
    with open(os.path.join(repo.working_dir, "calkit.yaml"), "w") as f:
        ryaml.dump(ck_info, f)
    last_synced = _record_zotero_sync_info(
        repo=repo,
        bib_path=req.bib_path,
        zotero_link=zotero_link,
        user_id=zotero_user_id,
        library_version=library_version,
        collection_name=collection_name,
    )
    repo.git.add(req.bib_path)
    repo.git.add("calkit.yaml")
    repo.git.commit(["-m", f"Import Zotero collection into '{req.bib_path}'"])
    repo.git.push(["origin", repo.active_branch.name])
    mixpanel.track(
        user=current_user,
        event_name="Imported Zotero collection",
        add_event_info={
            "path": req.bib_path,
            "mode": "collection" if req.collection_key else "items",
        },
    )
    return References.model_validate(
        {
            "path": req.bib_path,
            "zotero": {
                **zotero_link,
                "collection_name": collection_name,
                "last_sync_version": library_version,
                "last_synced": last_synced,
            },
        }
    )


def _pull_zotero_collection(
    repo,
    api_key: str,
    bib_path: str,
    bib_full_path: str,
    library_type: str,
    library_id: str,
    collection_key: str,
) -> int:
    """Pull a Zotero collection into a formatted .bib and refresh the item map.

    Each item's Zotero notes are written into its BibTeX ``comment`` field as
    Markdown, so notes live in the .bib (the source of truth); the citekey->item
    map under .calkit/zotero/ resolves PDFs and the Zotero item key per entry.
    Returns the library version.
    """
    items, library_version = zotero.get_collection_items(
        api_key=api_key,
        library_type=library_type,
        library_id=library_id,
        collection_key=collection_key,
    )
    items_map, notes_map = zotero.build_item_maps(
        api_key=api_key,
        library_type=library_type,
        library_id=library_id,
        items=items,
    )
    # Inject each item's Zotero notes into its BibTeX comment field.
    db = bibtexparser.loads(
        "\n\n".join(i["bibtex"] for i in items if i["bibtex"]) + "\n"
    )
    for entry in db.entries:
        item_notes = notes_map.get(entry.get("ID"))
        if item_notes:
            markdown = zotero.serialize_notes_markdown(
                [
                    {"text": zotero.note_html_to_text(n["html"])}
                    for n in item_notes
                ]
            )
            if markdown:
                entry[BIB_NOTE_FIELD] = markdown
    bibtex = zotero.format_bib(bibtexparser.dumps(db))
    os.makedirs(os.path.dirname(bib_full_path) or ".", exist_ok=True)
    with open(bib_full_path, "w") as f:
        f.write(bibtex)
    # Keyed by .bib path, so multiple linked collections coexist. items.json is
    # committed (the reference->Zotero-item map is needed for PDFs and travels
    # with the repo); force-add in case an older clone gitignored the whole
    # .calkit/zotero/ directory.
    all_items = zotero.read_items_info(repo.working_dir)
    all_items[bib_path] = items_map
    zotero.write_items_info(repo.working_dir, all_items)
    repo.git.add(["-f", zotero.ITEMS_REL_PATH])
    return library_version


def _record_zotero_sync_info(
    repo,
    bib_path: str,
    zotero_link: dict,
    user_id: str,
    library_version: int,
    collection_name: str | None = None,
) -> str:
    """Persist Zotero sync state for a .bib and stage it for commit.

    Like Overleaf, sync state is stateful and travels with the repo, so it's
    committed (force-added in case an older clone gitignored .calkit/zotero/).
    The collection name is cached here (fetched from Zotero), not in
    calkit.yaml, since it's derived data. Returns the ISO ``last_synced``.
    """
    now_iso = utcnow().isoformat()
    sync_info = zotero.read_sync_info(repo.working_dir)
    sync_info[bib_path] = {
        "library_type": zotero_link["library_type"],
        "library_id": zotero_link["library_id"],
        "collection_key": zotero_link["collection_key"],
        "collection_name": collection_name,
        "user_id": user_id,
        "last_sync_version": library_version,
        "last_synced": now_iso,
    }
    zotero.write_sync_info(repo.working_dir, sync_info)
    repo.git.add(["-f", zotero.SYNC_INFO_REL_PATH])
    return now_iso


def _set_item_mapping(repo, path: str, bib_key: str, item_key: str) -> None:
    """Record a reference->Zotero-item mapping in items.json and stage it."""
    all_items = zotero.read_items_info(repo.working_dir)
    all_items.setdefault(path, {})[bib_key] = {
        "item_key": item_key,
        "pdf_attachment_keys": [],
        "note_keys": [],
    }
    zotero.write_items_info(repo.working_dir, all_items)
    repo.git.add(["-f", zotero.ITEMS_REL_PATH])


def _push_added_reference(
    repo, api_key: str, link: dict, path: str, req: "ReferenceItemPost"
) -> None:
    """Create a newly added reference in Zotero and record its item mapping."""
    item_key = zotero.create_item(
        api_key=api_key,
        library_type=link["library_type"],
        library_id=link["library_id"],
        item_type=req.type,
        fields=req.fields,
        collection_key=link["collection_key"],
    )
    _set_item_mapping(repo, path, req.key, item_key)


def _push_edited_reference(
    repo,
    api_key: str,
    link: dict,
    path: str,
    old_key: str,
    req: "ReferenceItemPut",
) -> None:
    """Update an edited reference in Zotero (or create it if not yet linked)."""
    all_items = zotero.read_items_info(repo.working_dir)
    item_map = all_items.get(path, {})
    info = item_map.get(old_key)
    if info and info.get("item_key"):
        zotero.update_item(
            api_key=api_key,
            library_type=link["library_type"],
            library_id=link["library_id"],
            item_key=info["item_key"],
            item_type=req.type,
            fields=req.fields,
        )
        if req.key != old_key:
            item_map[req.key] = item_map.pop(old_key)
            zotero.write_items_info(repo.working_dir, all_items)
            repo.git.add(["-f", zotero.ITEMS_REL_PATH])
    else:
        item_key = zotero.create_item(
            api_key=api_key,
            library_type=link["library_type"],
            library_id=link["library_id"],
            item_type=req.type,
            fields=req.fields,
            collection_key=link["collection_key"],
        )
        _set_item_mapping(repo, path, req.key, item_key)


def _push_deleted_reference(
    repo, api_key: str, link: dict, path: str, bib_key: str
) -> None:
    """Delete a removed reference from Zotero and drop its item mapping."""
    all_items = zotero.read_items_info(repo.working_dir)
    item_map = all_items.get(path, {})
    info = item_map.pop(bib_key, None)
    if info and info.get("item_key"):
        zotero.delete_item(
            api_key=api_key,
            library_type=link["library_type"],
            library_id=link["library_id"],
            item_key=info["item_key"],
        )
    zotero.write_items_info(repo.working_dir, all_items)
    repo.git.add(["-f", zotero.ITEMS_REL_PATH])


class ZoteroSyncPost(BaseModel):
    path: str


class ZoteroSyncResponse(BaseModel):
    path: str
    last_sync_version: int
    last_synced: str
    committed: bool


def _apply_notes_to_entry(entry: dict, notes: list, anchors: dict) -> None:
    """Set (or clear) a reference entry's ``comment`` from Zotero notes,
    re-attaching any highlight anchors stored by note key.
    """
    local_notes = zotero.zotero_notes_to_local(notes, anchors)
    markdown = (
        zotero.serialize_notes_markdown(local_notes) if local_notes else ""
    )
    if markdown:
        entry[BIB_NOTE_FIELD] = markdown
    else:
        entry.pop(BIB_NOTE_FIELD, None)


def _merge_zotero_changes_into_bib(
    repo, api_key: str, link: dict, path: str, since_version: int
) -> int:
    """Incrementally merge Zotero changes since ``since_version`` into the .bib.

    Items changed on Zotero are updated in place (preserving the local citation
    key) or added; items deleted on Zotero are removed. Note/attachment children
    are included too, so a note-only edit (which doesn't bump its parent item's
    version) still refreshes its parent's notes. Entries untouched on Zotero,
    including local-only ones added on Calkit, are left alone. Returns the new
    library version.
    """
    lt, lid = link["library_type"], link["library_id"]
    changed_items, new_version = zotero.get_collection_items(
        api_key=api_key,
        library_type=lt,
        library_id=lid,
        collection_key=link["collection_key"],
        since=since_version,
        include_children=True,
    )
    deleted_keys = set(
        zotero.get_deleted_item_keys(
            api_key=api_key,
            library_type=lt,
            library_id=lid,
            since=since_version,
        )
    )
    full_path = os.path.join(repo.working_dir, path)
    text = ""
    if os.path.isfile(full_path):
        with open(full_path) as f:
            text = f.read()
    db = bibtexparser.loads(text)
    all_items = zotero.read_items_info(repo.working_dir)
    item_map = all_items.get(path, {})
    itemkey_to_bibkey = {
        info["item_key"]: bk
        for bk, info in item_map.items()
        if info.get("item_key")
    }
    notekey_to_bibkey = {
        nk: bk
        for bk, info in item_map.items()
        for nk in info.get("note_keys", [])
    }
    anchors = zotero.read_note_anchors(repo.working_dir)
    entries_by_id = {e["ID"]: e for e in db.entries}
    # Item keys of changed top-level items (whose notes are refreshed inline),
    # and parent keys whose only change was to a child (note/attachment).
    changed_top_keys = set()
    parents_to_refresh = set()
    for it in changed_items:
        if (it.get("data") or {}).get("parentItem"):
            parents_to_refresh.add(it["data"]["parentItem"])
            continue
        changed_top_keys.add(it["item_key"])
        if not it["bibtex"]:
            continue
        parsed = bibtexparser.loads(it["bibtex"]).entries
        if not parsed:
            continue
        new_entry = parsed[0]
        info, notes = zotero.build_item_info(api_key, lt, lid, it)
        _apply_notes_to_entry(new_entry, notes, anchors)
        local_bibkey = itemkey_to_bibkey.get(it["item_key"])
        if local_bibkey and local_bibkey in entries_by_id:
            # Update in place, keeping the local citation key. Overwrite/add the
            # fields Zotero exports but keep local-only ones (e.g. a manual
            # ``file``) that its export doesn't include.
            target = entries_by_id[local_bibkey]
            for k, v in new_entry.items():
                if k != "ID":
                    target[k] = v
            # Notes are re-derived from Zotero each pull, so clear them when it
            # has none rather than leaving stale local notes.
            if BIB_NOTE_FIELD not in new_entry:
                target.pop(BIB_NOTE_FIELD, None)
            item_map[local_bibkey] = info
        else:
            # A Zotero-side addition: bring it in under its Zotero citekey,
            # disambiguating if that key already exists locally.
            key = new_entry.get("ID") or it["item_key"]
            if key in entries_by_id:
                key = f"{key}_{it['item_key']}"
                new_entry["ID"] = key
            db.entries.append(new_entry)
            entries_by_id[key] = new_entry
            item_map[key] = info
    # Deletions: a deleted top-level item drops its entry; a deleted note child
    # just refreshes its parent's notes.
    drop = set()
    for k in deleted_keys:
        if k in itemkey_to_bibkey:
            drop.add(itemkey_to_bibkey[k])
        elif k in notekey_to_bibkey:
            info = item_map.get(notekey_to_bibkey[k]) or {}
            if info.get("item_key"):
                parents_to_refresh.add(info["item_key"])
    if drop:
        db.entries = [e for e in db.entries if e.get("ID") not in drop]
        for bib_key in drop:
            item_map.pop(bib_key, None)
    # Refresh notes for parents whose only change was a child, unless the parent
    # was already updated as a top-level change or was just deleted.
    for parent_key in parents_to_refresh:
        if parent_key in changed_top_keys:
            continue
        bibkey = itemkey_to_bibkey.get(parent_key)
        if not bibkey or bibkey in drop or bibkey not in entries_by_id:
            continue
        info, notes = zotero.build_item_info(
            api_key, lt, lid, {"item_key": parent_key, "num_children": 1}
        )
        _apply_notes_to_entry(entries_by_id[bibkey], notes, anchors)
        item_map[bibkey] = info
    os.makedirs(os.path.dirname(full_path) or ".", exist_ok=True)
    with open(full_path, "w") as f:
        f.write(zotero.format_bib(bibtexparser.dumps(db)))
    all_items[path] = item_map
    zotero.write_items_info(repo.working_dir, all_items)
    repo.git.add(["-f", zotero.ITEMS_REL_PATH])
    return new_version


@router.post("/projects/{owner_name}/{project_name}/zotero/syncs")
def post_project_zotero_sync(
    owner_name: str,
    project_name: str,
    req: ZoteroSyncPost,
    current_user: CurrentUser,
    session: SessionDep,
) -> ZoteroSyncResponse:
    """Pull Zotero changes into a linked collection's ``.bib``, per item.

    Local edits already reach Zotero when they are made (add/edit/delete push
    immediately), so sync only pulls: it fetches the items changed on Zotero
    since the last sync and merges them into the ``.bib`` one at a time,
    updating changed entries in place, adding new ones, and removing deleted
    ones, while leaving untouched (including local-only) entries alone.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    api_key, zotero_user_id = users.get_zotero_api_key_and_user_id(
        session=session, user=current_user
    )
    repo = get_repo(project=project, user=current_user, session=session)
    link = _find_reference_link(repo, req.path)
    if not link:
        raise HTTPException(404, "No Zotero-linked collection at that path")
    # Merge incrementally. With no recorded version yet, since=0 pulls every
    # item but still merges per item (preserving local-only entries and local
    # citation keys), rather than regenerating the whole .bib.
    since = (
        zotero.read_sync_info(repo.working_dir)
        .get(req.path, {})
        .get("last_sync_version")
        or 0
    )
    library_version = _merge_zotero_changes_into_bib(
        repo=repo,
        api_key=api_key,
        link=link,
        path=req.path,
        since_version=since,
    )
    # Refresh the cached collection name from Zotero (it may have been renamed).
    collection_name = zotero.get_collection_name(
        api_key=api_key,
        library_type=link["library_type"],
        library_id=link["library_id"],
        collection_key=link["collection_key"],
    )
    last_synced = _record_zotero_sync_info(
        repo=repo,
        bib_path=req.path,
        zotero_link=link,
        user_id=zotero_user_id,
        library_version=library_version,
        collection_name=collection_name,
    )
    repo.git.add(req.path)
    committed = bool(repo.git.diff("--cached", "--name-only").strip())
    if committed:
        repo.git.commit(["-m", f"Sync Zotero collection into '{req.path}'"])
        repo.git.push(["origin", repo.active_branch.name])
    mixpanel.track(
        user=current_user,
        event_name="Synced Zotero collection",
        add_event_info={"path": req.path, "committed": committed},
    )
    return ZoteroSyncResponse(
        path=req.path,
        last_sync_version=library_version,
        last_synced=last_synced,
        committed=committed,
    )


def _resolve_zotero_item(repo, path: str, bib_key: str) -> tuple[dict, dict]:
    """Return ``(link, item)`` for a reference entry, or raise 404.

    ``link`` is the collection's Zotero link from .calkit/zotero/sync.json;
    ``item`` is the entry's record from .calkit/zotero/items.json.
    """
    link = _find_reference_link(repo, path)
    if not link:
        raise HTTPException(404, "No Zotero-linked collection at that path")
    item = zotero.read_items_info(repo.working_dir).get(path, {}).get(bib_key)
    if not item:
        raise HTTPException(404, "Reference item is not linked to Zotero")
    return link, item


@router.get("/projects/{owner_name}/{project_name}/zotero/items/{bib_key}/pdf")
def get_project_zotero_item_pdf(
    owner_name: str,
    project_name: str,
    bib_key: str,
    path: str,
    current_user: CurrentUser,
    session: SessionDep,
    index: int = Query(0, ge=0),
) -> Response:
    """Stream a reference item's Zotero PDF attachment."""
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    api_key, _ = users.get_zotero_api_key_and_user_id(
        session=session, user=current_user
    )
    repo = get_repo(project=project, user=current_user, session=session)
    link, item = _resolve_zotero_item(repo, path, bib_key)
    attachment_keys = item.get("pdf_attachment_keys") or []
    if index >= len(attachment_keys):
        raise HTTPException(404, "No PDF for this reference item")
    stream, content_type, content_length = zotero.stream_attachment(
        api_key=api_key,
        library_type=link["library_type"],
        library_id=link["library_id"],
        attachment_key=attachment_keys[index],
    )
    headers = {"Content-Length": content_length} if content_length else {}
    return StreamingResponse(stream, media_type=content_type, headers=headers)


class ReferenceNoteHighlight(BaseModel):
    # react-pdf-highlighter ScaledPosition, stored verbatim.
    position: dict
    quote: str = ""


# A reference note. Notes for every reference live in the BibTeX ``comment``
# field, ``---``-separated (see ``zotero.parse_notes_markdown``); a note may be
# anchored to a PDF highlight. Zotero-linked references additionally sync the
# note text to Zotero as note child items.
class ReferenceNote(BaseModel):
    text: str
    highlight: ReferenceNoteHighlight | None = None


class ReferenceNotesResponse(BaseModel):
    notes: list[ReferenceNote]


BIB_NOTE_FIELD = zotero.NOTE_FIELD


def _find_reference_link(repo, path: str) -> dict | None:
    """Return the Zotero link for the collection at ``path``, if any.

    The link is private, kept in .calkit/zotero/sync.json rather than
    calkit.yaml (which just lists collection paths).
    """
    info = zotero.read_sync_info(repo.working_dir).get(path)
    if isinstance(info, dict) and info.get("collection_key"):
        return info
    return None


def _read_bib_comment(repo, path: str, bib_key: str) -> str:
    """Read a reference entry's ``comment`` field from the .bib."""
    full_path = os.path.join(repo.working_dir, path)
    if not os.path.isfile(full_path):
        raise HTTPException(404, "References file not found")
    with open(full_path) as f:
        db = bibtexparser.loads(f.read())
    for entry in db.entries:
        if entry.get("ID") == bib_key:
            return entry.get(BIB_NOTE_FIELD, "")
    raise HTTPException(404, "Reference entry not found")


def _write_bib_comment(repo, path: str, bib_key: str, text: str) -> bool:
    """Set (or clear) a reference entry's ``comment`` field, returning whether
    the file changed.
    """
    full_path = os.path.join(repo.working_dir, path)
    if not os.path.isfile(full_path):
        raise HTTPException(404, "References file not found")
    with open(full_path) as f:
        db = bibtexparser.loads(f.read())
    found = False
    for entry in db.entries:
        if entry.get("ID") == bib_key:
            found = True
            if text.strip():
                entry[BIB_NOTE_FIELD] = text.strip()
            else:
                entry.pop(BIB_NOTE_FIELD, None)
    if not found:
        raise HTTPException(404, "Reference entry not found")
    new_text = zotero.format_bib(bibtexparser.dumps(db))
    with open(full_path) as f:
        if f.read() == new_text:
            return False
    with open(full_path, "w") as f:
        f.write(new_text)
    return True


def _sync_notes_to_zotero(
    repo, api_key: str, path: str, bib_key: str, link: dict, item_key: str
) -> None:
    """Push the notes stored in the .bib comment to Zotero note child items.

    Notes are mapped to Zotero notes by position: the Nth note updates the Nth
    existing child note (creating or deleting to match the count), so the .bib
    stays the source of truth. Note keys are recorded in items.json only for
    reference.
    """
    notes = zotero.parse_notes_markdown(_read_bib_comment(repo, path, bib_key))
    existing = [
        child
        for child in zotero.get_item_children(
            api_key=api_key,
            library_type=link["library_type"],
            library_id=link["library_id"],
            item_key=item_key,
        )
        if child.get("data", {}).get("itemType") == "note"
    ]
    # Zotero can't hold a highlight anchor, so track each note's anchor by its
    # Zotero note key here, to re-attach it when the note is pulled back.
    anchors = zotero.read_note_anchors(repo.working_dir)
    for i, note in enumerate(notes):
        html = zotero.note_zotero_html(note)
        if i < len(existing):
            note_key = existing[i]["key"]
            zotero.update_note(
                api_key=api_key,
                library_type=link["library_type"],
                library_id=link["library_id"],
                note_key=note_key,
                version=existing[i]["version"],
                html=html,
            )
        else:
            note_key = zotero.create_note(
                api_key=api_key,
                library_type=link["library_type"],
                library_id=link["library_id"],
                parent_item_key=item_key,
                html=html,
            )["key"]
        if note.get("highlight"):
            anchors[note_key] = note["highlight"]
        else:
            anchors.pop(note_key, None)
    for child in existing[len(notes) :]:
        zotero.delete_note(
            api_key=api_key,
            library_type=link["library_type"],
            library_id=link["library_id"],
            note_key=child["key"],
            version=child["version"],
        )
        anchors.pop(child["key"], None)
    zotero.write_note_anchors(repo.working_dir, anchors)
    repo.git.add(["-f", zotero.ANCHORS_REL_PATH])


@router.get(
    "/projects/{owner_name}/{project_name}/references/items/{bib_key}/notes"
)
def get_project_reference_notes(
    owner_name: str,
    project_name: str,
    bib_key: str,
    path: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> ReferenceNotesResponse:
    """Get a reference item's notes from its BibTeX ``comment`` field.

    The .bib is the source of truth for note content (Zotero-linked references
    have their Zotero notes written into it on sync), so reading is the same for
    every reference.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(project=project, user=current_user, session=session)
    notes = zotero.parse_notes_markdown(_read_bib_comment(repo, path, bib_key))
    return ReferenceNotesResponse(
        notes=[ReferenceNote.model_validate(n) for n in notes]
    )


class ReferenceNotesPut(BaseModel):
    path: str
    notes: list[ReferenceNote]


@router.put(
    "/projects/{owner_name}/{project_name}/references/items/{bib_key}/notes"
)
def put_project_reference_notes(
    owner_name: str,
    project_name: str,
    bib_key: str,
    req: ReferenceNotesPut,
    current_user: CurrentUser,
    session: SessionDep,
) -> ReferenceNotesResponse:
    """Set a reference item's notes in the BibTeX ``comment`` field.

    Notes are serialized to Markdown (untitled sections separated by ``---``,
    each optionally carrying a highlight anchor) and committed. For a
    Zotero-linked reference, the notes are also pushed to Zotero.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(project=project, user=current_user, session=session)
    markdown = zotero.serialize_notes_markdown(
        [n.model_dump() for n in req.notes]
    )
    changed = _write_bib_comment(repo, req.path, bib_key, markdown)
    link = _find_reference_link(repo, req.path)
    item = (
        zotero.read_items_info(repo.working_dir).get(req.path, {}).get(bib_key)
    )
    # Only push to Zotero when the notes actually changed, so a redundant save
    # doesn't churn Zotero note versions.
    if changed and link and item:
        api_key, _ = users.get_zotero_api_key_and_user_id(
            session=session, user=current_user
        )
        _sync_notes_to_zotero(
            repo, api_key, req.path, bib_key, link, item["item_key"]
        )
    if changed:
        repo.git.add(req.path)
        repo.git.commit(["-m", f"Edit notes on '{bib_key}'"])
        repo.git.push(["origin", repo.active_branch.name])
    mixpanel.track(
        user=current_user,
        event_name="Edited reference note",
        add_event_info={"path": req.path, "linked": bool(link and item)},
    )
    return ReferenceNotesResponse(
        notes=[ReferenceNote.model_validate(n) for n in req.notes]
    )


class Environment(BaseModel):
    name: str
    kind: str
    path: str | None = None
    description: str | None = None
    imported_from: str | None = None
    all_attrs: dict
    file_content: str | None = None


@router.get("/projects/{owner_name}/{project_name}/environments")
def get_project_environments(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> list[Environment]:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    ck_info = app.projects.get_ck_info_for_ref(
        project=project,
        repo=repo,
        ref=ref,
    )
    envs = ck_info.get("environments", {})
    resp = []
    for env_name, env in envs.items():
        env_resp = env | {"all_attrs": env}
        env_resp["name"] = env_name
        env_path = env.get("path")
        if env_path:
            fpath = os.path.join(repo.working_dir, env_path)
            if os.path.isfile(fpath):
                with open(fpath) as f:
                    env_resp["file_content"] = f.read()
        try:
            resp.append(Environment.model_validate(env_resp))
        except ValidationError as e:
            logger.warning(f"Invalid environment: {e}")
    return resp


@router.post("/projects/{owner_name}/{project_name}/environments")
def post_project_environment(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
    req: Environment,
    ref: str | None = None,
) -> Environment:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    ck_info = app.projects.get_ck_info_for_ref(
        project=project,
        repo=repo,
        ref=ref,
    )
    envs = ck_info.get("environments", {})
    if req.name in envs:
        raise HTTPException(400, "Environment with same name already exists")
    new_env = req.all_attrs
    if req.imported_from and "imported_from" not in new_env:
        new_env["imported_from"] = req.imported_from
    envs[req.name] = new_env
    ck_info["environments"] = envs
    fpath = os.path.join(repo.working_dir, "calkit.yaml")
    with open(fpath, "w") as f:
        ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    if req.path and req.file_content:
        fpath = os.path.join(repo.working_dir, req.path)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w") as f:
            f.write(req.file_content)
        repo.git.add(fpath)
    repo.git.commit(["-m", f"Add environment {req.name}"])
    repo.git.push(["origin", repo.active_branch])
    return Environment.model_validate(new_env | {"all_attrs": new_env})


class SoftwareItem(BaseModel):
    title: str
    path: str
    description: str | None = None


class Software(BaseModel):
    items: list[SoftwareItem]


@router.get("/projects/{owner_name}/{project_name}/software")
def get_project_software(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> Software:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    ck_info = app.projects.get_ck_info_for_ref(
        project=project,
        repo=repo,
        ref=ref,
    )
    raw = ck_info.get("software", [])
    items = []
    for entry in raw:
        try:
            items.append(SoftwareItem.model_validate(entry))
        except ValidationError as e:
            logger.warning(f"Invalid software entry: {e}")
    return Software(items=items)


@router.get("/projects/{owner_name}/{project_name}/file-locks")
def get_project_file_locks(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> list[FileLock]:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    return project.file_locks


class FileLockPost(BaseModel):
    path: str


@router.post("/projects/{owner_name}/{project_name}/file-locks")
def post_project_file_lock(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
    req: FileLockPost,
) -> FileLock:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    existing = project.file_locks
    for lock in existing:
        if lock.path == req.path:
            raise HTTPException(400, "File is already locked")
    lock = FileLock(
        project_id=project.id, user_id=current_user.id, path=req.path
    )
    session.add(lock)
    session.commit()
    session.refresh(lock)
    return lock


@router.delete("/projects/{owner_name}/{project_name}/file-locks")
def delete_project_file_lock(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
    req: FileLockPost,
) -> Message:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    existing = project.file_locks
    for lock in existing:
        if lock.path == req.path:
            if lock.user != current_user:
                raise HTTPException(403, "Cannot delete someone else's lock")
            session.delete(lock)
            session.commit()
            return Message(message="success")
    raise HTTPException(404, "Lock not found")


@router.get("/projects/{owner_name}/{project_name}/notebooks")
def get_project_notebooks(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> list[Notebook]:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    ck_info = app.projects.get_ck_info_for_ref(
        project=project,
        repo=repo,
        ref=ref,
    )
    notebooks = ck_info.get("notebooks", [])
    # Also detect undeclared .ipynb files not under hidden directories
    declared_paths = {nb["path"] for nb in notebooks}
    try:
        for root, dirs, files in os.walk(repo.working_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if fname.endswith(".ipynb"):
                    rel = os.path.relpath(
                        os.path.join(root, fname), repo.working_dir
                    )
                    if rel not in declared_paths:
                        notebooks.append({"path": rel})
                        declared_paths.add(rel)
    except Exception as e:
        logger.warning(f"Failed to scan for undeclared notebooks: {e}")
    if not notebooks:
        return notebooks
    # Detect stages from jupyter-notebook ``notebook_path`` items
    pipeline = ck_info.get("pipeline", {})
    stages = pipeline.get("stages", {})
    nb_path_to_stage_name = {}
    for stage_name, stage in stages.items():
        if stage.get("kind") == "jupyter-notebook":
            nb_path = stage.get("notebook_path")
            if nb_path:
                nb_path_to_stage_name[nb_path] = stage_name
    for nb in notebooks:
        nb_path = nb.get("path")
        if nb_path in nb_path_to_stage_name:
            nb["stage"] = nb_path_to_stage_name[nb_path]
    # Get the notebook content and base64 encode it
    tree = app.projects.get_repo_tree_for_ref(repo, ref)
    (
        ck_info_full,
        dvc_lock_outs,
        zip_path_map,
        _,
    ) = app.projects.get_ck_info_and_dvc_outs_from_tree(project, tree)
    for notebook in notebooks:
        try:
            item = app.projects.get_contents_from_tree(
                project=project,
                tree=tree,
                path=notebook["path"],
                ck_info=ck_info_full,
                dvc_lock_outs=dvc_lock_outs,
                zip_path_map=zip_path_map,
            )
        except HTTPException:
            continue
        try:
            # If the notebook has a pre-built HTML output, prefer that
            html_path = get_executed_notebook_path(
                notebook_path=notebook["path"], to="html"
            )
            html_item = app.projects.get_contents_from_tree(
                project=project,
                tree=tree,
                path=html_path,
                ck_info=ck_info_full,
                dvc_lock_outs=dvc_lock_outs,
            )
            item = html_item
            notebook["output_format"] = "html"
        except HTTPException as e:
            logger.info(f"Notebook HTML does not exist at {html_path}: {e}")
        notebook["url"] = item.url
        notebook["content"] = item.content
        notebook["storage"] = item.storage
        # Figure out the output format from the URL content disposition
        if item.url is not None:
            params = params_from_url(item.url)
            rcd = params.get("response-content-disposition")
            if rcd is not None:
                if rcd[0].endswith(".ipynb"):
                    notebook["output_format"] = "notebook"
                elif rcd[0].endswith(".html"):
                    notebook["output_format"] = "html"
        # Default: raw .ipynb content (no HTML version available)
        if not notebook.get("output_format") and item.content and not item.url:
            notebook["output_format"] = "notebook"
    return [Notebook.model_validate(nb) for nb in notebooks]


@router.get("/projects/{owner_name}/{project_name}/repro-check")
def get_project_repro_check(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> ReproCheck:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    res = check_reproducibility(wdir=str(repo.working_dir))
    return res


@router.put("/projects/{owner_name}/{project_name}/devcontainer")
def put_project_dev_container(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
) -> Message:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    subprocess.check_call(
        ["calkit", "update", "devcontainer"], cwd=repo.working_dir
    )
    repo.git.add(".devcontainer")
    if repo.git.diff("--staged"):
        repo.git.commit(["-m", "Add dev container spec"])
        repo.git.push(["origin", repo.active_branch])
    return Message(message="Success")


class ProjectApp(BaseModel):
    path: str | None = None
    url: str | None = None
    title: str | None = None
    description: str | None = None


@router.get("/projects/{owner_name}/{project_name}/app")
def get_project_app(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ref: str | None = None,
) -> ProjectApp | None:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    ck_info = get_ck_info(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
    )
    project_app = ck_info.get("app")
    if project_app is None:
        return
    return ProjectApp.model_validate(project_app)


@router.get("/projects/{owner_name}/{project_name}/showcase")
def get_project_showcase(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
    ttl: int | None = DEFAULT_REPO_TTL,
    ref: str | None = None,
) -> Showcase | None:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    incorrectly_defined = Showcase(
        elements=[ShowcaseText(text="Showcase is not correctly defined.")]
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=ttl,
        ref=ref,
    )
    ck_info = app.projects.get_ck_info_for_ref(
        project=project,
        repo=repo,
        ref=ref,
    )
    showcase = ck_info.get("showcase")
    if showcase is None:
        return
    try:
        inputs = ShowcaseInput.model_validate(dict(elements=showcase))
    except Exception:
        return incorrectly_defined
    # Iterate over showcase elements, fetching the contents to return
    # Set TTL very high since we already fetched the repo above
    if ttl is None:
        ttl = 3600
    else:
        ttl = 30 * ttl
    # Compute pipeline staleness once so publication elements can surface a
    # "stale" badge. Best-effort: never let it break the showcase.
    showcase_stage_statuses: dict = {}
    showcase_dvc_lock: dict = {}
    try:
        showcase_tree = app.projects.get_repo_tree_for_ref(repo, ref)
        if showcase_tree.is_file("dvc.lock"):
            showcase_dvc_lock = (
                ryaml.load(showcase_tree.read_bytes("dvc.lock").decode()) or {}
            )
        showcase_dvc_yaml: dict = {}
        if showcase_tree.is_file("dvc.yaml"):
            showcase_dvc_yaml = (
                ryaml.load(showcase_tree.read_bytes("dvc.yaml").decode()) or {}
            )
        showcase_stage_statuses = compute_stage_statuses(
            dvc_yaml=showcase_dvc_yaml,
            dvc_lock=showcase_dvc_lock,
            tree=showcase_tree,
            owner_name=project.owner_account_name,
            project_name=project.name,
            fs=get_object_fs(),
            cache_token=resolve_commit_sha(repo, ref),
        )
    except Exception as e:
        logger.warning(f"Failed to compute pipeline status for showcase: {e}")
    elements_out = []
    for element_in in inputs.elements:
        if isinstance(element_in, ShowcaseFigureInput):
            try:
                element_out = ShowcaseFigure(
                    figure=app.projects.get_figure_from_repo(
                        project=project,
                        repo=repo,
                        path=element_in.figure,
                        ref=ref,
                    )
                )
            except Exception as e:
                logger.warning(
                    f"Failed to get showcase figure from {element_in}: {e}"
                )
                element_out = ShowcaseText(
                    text=f"Figure at path '{element_in.figure}' not found"
                )
        elif isinstance(element_in, ShowcasePublicationInput):
            try:
                element_out = ShowcasePublication(
                    publication=app.projects.get_publication_from_repo(
                        project=project,
                        repo=repo,
                        path=element_in.publication,
                        ref=ref,
                    )
                )
                pub = element_out.publication
                if not pub.stage and pub.path:
                    auto_stage = find_stage_for_path(
                        pub.path, showcase_dvc_lock
                    )
                    if auto_stage is not None:
                        pub.stage = auto_stage
                if pub.stage and pub.calkit_stage is None:
                    # Auto-detected stages miss the calkit_stage lookup in
                    # get_publication_from_repo, so patch it in here
                    ck_info = app.projects.get_ck_info_for_ref(
                        project=project, repo=repo, ref=ref
                    )
                    pub.calkit_stage = (
                        (ck_info.get("pipeline") or {})
                        .get("stages", {})
                        .get(pub.stage)
                    )
                if pub.stage and pub.stage in showcase_stage_statuses:
                    pub.stage_status = showcase_stage_statuses[pub.stage]
            except Exception as e:
                logger.warning(
                    "Failed to get showcase publication from "
                    f"{element_in}: {e}"
                )
                element_out = ShowcaseText(
                    text=(
                        f"Publication at path '{element_in.publication}' "
                        "not found"
                    )
                )
        elif isinstance(element_in, ShowcaseMarkdownFileInput):
            fpath = os.path.join(repo.working_dir, element_in.markdown_file)
            if os.path.isfile(fpath):
                with open(fpath) as f:
                    md = f.read()
                element_out = ShowcaseMarkdown(markdown=md)
            else:
                element_out = ShowcaseText(
                    text=(
                        f"Markdown file at path '{element_in.markdown_file}' "
                        "not found"
                    )
                )
        elif isinstance(element_in, ShowcaseYamlFileInput):
            fpath = os.path.join(repo.working_dir, element_in.yaml_file)
            if os.path.isfile(fpath):
                if element_in.object_name is None:
                    with open(fpath) as f:
                        txt = f.read()
                else:
                    with open(fpath) as f:
                        content = ryaml.load(f)
                    if content is None:
                        content = {}
                    obj = content.get(
                        element_in.object_name,
                        f"YAML object {element_in.object_name} not found.",
                    )
                    stream = StringIO()
                    ryaml.dump(obj, stream)
                    txt = stream.getvalue()
                element_out = ShowcaseYaml(yaml=txt)
            else:
                element_out = ShowcaseText(
                    text=(
                        f"YAML file at path '{element_in.yaml_file}' not found"
                    )
                )
        elif isinstance(element_in, ShowcaseNotebookInput):
            try:
                element_out = ShowcaseNotebook(
                    notebook=app.projects.get_notebook_from_repo(
                        project=project,
                        repo=repo,
                        path=element_in.notebook,
                        ref=ref,
                    )
                )
            except Exception as e:
                logger.warning(
                    f"Failed to get showcase notebook from {element_in}: {e}"
                )
                element_out = ShowcaseText(
                    text=(
                        f"Notebook for path '{element_in.notebook}' not found"
                    )
                )
        else:
            element_out = element_in
        elements_out.append(element_out)
    return Showcase.model_validate(dict(elements=elements_out))


class GitHubRelease(BaseModel):
    url: str
    name: str
    tag_name: str
    body: str
    created: datetime
    published: datetime


class GithubPullRequest(BaseModel):
    number: int
    title: str
    head_ref: str
    base_ref: str
    head_sha: str
    base_sha: str


@router.get("/projects/{owner_name}/{project_name}/github-pulls/{pull_number}")
def get_project_github_pull(
    owner_name: str,
    project_name: str,
    pull_number: int,
    current_user: CurrentUser,
    session: SessionDep,
) -> GithubPullRequest:
    """Read a pull request's refs from GitHub.

    Proxied rather than read from the browser so a private repo works:
    the caller has read access to the project here, and the hub holds a
    GitHub token, where an unauthenticated request would only ever see
    public repos.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    if not project.github_repo:
        raise HTTPException(400, "Project is not backed by a GitHub repo")
    token = users.get_github_token(session=session, user=current_user)
    resp = requests.get(
        f"https://api.github.com/repos/{project.github_repo}"
        f"/pulls/{pull_number}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise HTTPException(
            resp.status_code, f"Could not read pull request #{pull_number}"
        )
    body = resp.json()
    return GithubPullRequest(
        number=body["number"],
        title=body.get("title") or "",
        head_ref=body["head"]["ref"],
        base_ref=body["base"]["ref"],
        head_sha=body["head"]["sha"],
        base_sha=body["base"]["sha"],
    )


@router.get("/projects/{owner_name}/{project_name}/github-releases")
def get_project_github_releases(
    owner_name: str,
    project_name: str,
    current_user: CurrentUserOptional,
    session: SessionDep,
) -> list[GitHubRelease]:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    if current_user is not None:
        token = users.get_github_token(session=session, user=current_user)
        headers = {"Authorization": f"Bearer {token}"}
    else:
        headers = None
    logger.info(f"Fetching GitHub releases for {owner_name}/{project_name}")
    url = f"https://api.github.com/repos/{project.github_repo}/releases"
    resp = requests.get(url, headers=headers)
    if resp.status_code >= 400:
        raise HTTPException(400, "Failed to fetch GitHub releases")
    resp2 = []
    for obj in resp.json():
        resp2.append(
            GitHubRelease(
                url=obj["html_url"],
                name=obj["name"],
                tag_name=obj["tag_name"],
                body=obj["body"],
                created=obj["created_at"],
                published=obj["published_at"],
            )
        )
    return resp2


class GitHubReleasePost(BaseModel):
    tag_name: str
    target_committish: str = "main"
    name: str | None = None
    body: str
    generate_release_notes: bool = True


@router.post("/projects/{owner_name}/{project_name}/github-releases")
def post_project_github_release(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
    req: GitHubReleasePost,
) -> GitHubRelease:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    token = users.get_github_token(session=session, user=current_user)
    headers = {"Authorization": f"Bearer {token}"}
    logger.info(
        f"Posting GitHub release {req.name} for {owner_name}/{project_name}"
    )
    if req.name is None:
        req.name = req.tag_name
    url = f"https://api.github.com/repos/{project.github_repo}/releases"
    resp = requests.post(url, json=req.model_dump(), headers=headers)
    if resp.status_code >= 400:
        raise HTTPException(400, "Failed to post GitHub release")
    obj = resp.json()
    return GitHubRelease(
        url=obj["html_url"],
        name=obj["name"],
        tag_name=obj["tag_name"],
        body=obj["body"],
        created=obj["created_at"],
        published=obj["published_at"],
    )


class ProjectStatusPost(BaseModel):
    status: Literal["in-progress", "on-hold", "completed"]
    message: str | None = None


@router.post("/projects/{owner_name}/{project_name}/status")
def post_project_status(
    owner_name: str,
    project_name: str,
    current_user: CurrentUser,
    session: SessionDep,
    req: ProjectStatusPost,
) -> ProjectStatus:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="write",
    )
    repo = get_repo(
        project=project, user=current_user, session=session, ttl=None
    )
    logger.info(f"{current_user.email} setting project status to {req.status}")
    cmd = ["calkit", "new", "status", req.status]
    if req.message is not None:
        cmd += ["-m", req.message]
    try:
        subprocess.check_call(cmd, cwd=repo.working_dir)
        logger.info("Git pushing")
        repo.git.push(["origin", repo.active_branch])
    except Exception as e:
        logger.error(f"Failed to set project status: {e}")
        raise HTTPException(400, f"Failed to set project status: {e}")
    project.status = req.status
    project.status_message = req.message
    project.status_updated = app.utcnow()
    session.commit()
    session.refresh(project)
    return ProjectStatus(
        status=project.status,
        message=project.status_message,
        timestamp=project.status_updated,
    )
