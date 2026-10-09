"""Comments on a LaTeX document's PDF, kept in the document's source.

The source is the record: threads are ``% COMMENT`` blocks above the
paragraph they're about, in the Calkit LaTeX comment schema, so they work
from a clone with the CLI or any editor and travel with the project. None
of a thread is stored here. A read takes the threads from the source at
the ref being viewed and places them on the PDF built from it, and a
change is a commit to the source. Mirroring a thread to a GitHub issue is
optional, and linked from the source with its ``issue`` attribute.
"""

import logging
import posixpath
import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

import git
import requests
from fastapi import APIRouter, HTTPException
from git.exc import GitCommandError
from pydantic import BaseModel
from sqlmodel import Session, col, select

import app.projects
import calkit.latex
from app import pdftext
from app.api.deps import CurrentUser, CurrentUserOptional, SessionDep
from app.api.routes.projects.core import (
    DEFAULT_REPO_TTL,
    _github_token_for_repo,
    _make_comment_artifact_link,
    _make_comment_title,
    _try_close_github_issue,
    _try_create_github_issue,
    _try_post_github_issue_comment,
    _try_reopen_github_issue,
)
from app.core import ryaml
from app.git import (
    commit_to_branch,
    get_default_branch,
    get_repo,
    get_repo_tree_for_ref,
    resolve_commit_sha,
)
from app.models import CommentHighlight, Project, ProjectComment, User

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter()

Read = Callable[[str], str | None]


class LatexCommentMessage(BaseModel):
    author: str
    email: str | None = None
    date: str | None = None
    text: str


class LatexCommentThread(BaseModel):
    # The thread's ID, or for one without, its file and line
    key: str
    id: str | None = None
    path: str
    line: int
    resolved: bool
    issue: str | None = None
    highlight: str | None = None
    # Where it goes on the PDF, as react-pdf-highlighter's ScaledPosition,
    # if its paragraph was found there
    position: dict | None = None
    messages: list[LatexCommentMessage]


class LatexComments(BaseModel):
    # The PDF and the document it's built from
    path: str
    source: str
    rev: str
    # Where changes are committed: the branch being viewed, or None when a
    # tag or commit is, in which case they go to a branch of their own with
    # a pull request
    branch: str | None
    can_comment: bool
    threads: list[LatexCommentThread]


class LatexCommentPost(BaseModel):
    path: str
    ref: str | None = None
    comment: str
    # Without one, the comment is on the document as a whole
    highlight: CommentHighlight | None = None
    create_github_issue: bool = False


class LatexCommentReplyPost(BaseModel):
    path: str
    ref: str | None = None
    key: str
    body: str


class LatexCommentPatch(BaseModel):
    path: str
    ref: str | None = None
    key: str
    resolved: bool


@dataclass
class _Document:
    project: Project
    repo: git.Repo
    path: str
    source: str
    rev: str
    branch: str | None

    def reader(self, rev: str) -> Read:
        tree = get_repo_tree_for_ref(self.repo, rev)

        def read(p: str) -> str | None:
            p = posixpath.normpath(p)
            if not tree.is_file(p):
                return None
            return bytes(tree.read_bytes(p)).decode("utf-8")

        return read


def _open_document(
    owner_name: str,
    project_name: str,
    path: str,
    ref: str | None,
    session: Session,
    current_user: User | None,
    write: bool,
) -> _Document:
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="write" if write else "read",
    )
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=DEFAULT_REPO_TTL,
        ref=ref,
        read_only=not write,
    )
    if ref is None:
        branch: str | None = get_default_branch(repo)
        # Where the remote's default branch is, which commits here move
        # without touching the checkout
        rev = resolve_commit_sha(repo, f"origin/{branch}") or (
            resolve_commit_sha(repo, None)
        )
    else:
        rev = resolve_commit_sha(repo, ref)
        try:
            repo.commit(f"origin/{ref}")
            branch = ref
        except Exception:
            branch = None
    if rev is None:
        raise HTTPException(404, f"Git ref '{ref}' was not found")
    # The document a latex stage builds this PDF from
    tree = get_repo_tree_for_ref(repo, rev)
    ck_info = (
        ryaml.load(bytes(tree.read_bytes("calkit.yaml")).decode("utf-8"))
        if tree.is_file("calkit.yaml")
        else None
    ) or {}
    source = None
    for stage in (ck_info.get("pipeline") or {}).get("stages", {}).values():
        if not isinstance(stage, dict) or stage.get("kind") != "latex":
            continue
        target = posixpath.normpath(
            posixpath.join(stage.get("wdir") or "", stage["target_path"])
        )
        if re.sub(r"\.tex$", ".pdf", target) == path:
            source = target
            break
    if source is None:
        raise HTTPException(404, f"No LaTeX stage builds '{path}'")
    return _Document(project, repo, path, source, rev, branch)


def _read_layout(
    doc: _Document, rev: str, session: Session, current_user: User | None
) -> pdftext.PdfLayout | None:
    """Where the text is in the PDF as built at a revision, if it can be
    read."""
    try:
        return pdftext.PdfLayout(
            app.projects.read_project_file(
                doc.project,
                get_repo_tree_for_ref(doc.repo, rev),
                doc.path,
                pdftext.MAX_PDF_BYTES,
                session=session,
                current_user=current_user,
            )
        )
    except Exception as e:
        logger.info(f"Could not read the text of {doc.path} at {rev}: {e}")
        return None


def _locate_selection(
    doc: _Document,
    layout: pdftext.PdfLayout,
    rev: str,
    highlight: dict,
) -> tuple[str, str | None, int] | None:
    """The source paragraph a selection in the PDF is in, as rendered
    text, with the selected text and which time it appears in the
    paragraph, from the highlight a viewer made of it."""
    content = highlight.get("content") or {}
    text = pdftext.normalize_selection(str(content.get("text") or "")) or None
    selection = layout.selection(highlight.get("position") or {})
    if selection is None:
        return None
    start, context = selection
    blk = calkit.latex.locate_block(
        doc.source, text=context, read=doc.reader(rev)
    )
    if blk is None:
        return None
    # A display's text is its math, roughly as it reads
    paragraph = blk.text or calkit.latex.display_text(blk)
    occ = 0
    span = layout.paragraph(paragraph)
    if text and span is not None:
        occ = len(layout.find(text, span[0], (start[0], start[1] - 1)))
    return paragraph, text, occ


def _read_comments(
    doc: _Document, rev: str, session: Session, current_user: User | None
) -> LatexComments:
    read = doc.reader(rev)
    threads = calkit.latex.list_comments(doc.source, read)
    # The threads are still worth listing without their places
    layout = _read_layout(doc, rev, session, current_user)
    out = []
    for t in threads:
        position = None
        if layout is not None and t["anchor"]:
            highlight = t["highlight"] or {}
            position = layout.place(
                t["anchor"]["text"],
                highlight.get("text"),
                highlight.get("occ", 0),
            )
        out.append(
            LatexCommentThread(
                key=t["id"] or f"{t['path']}:{t['line']}",
                id=t["id"],
                path=t["path"],
                line=t["line"],
                resolved=t["resolved"],
                issue=t["issue"],
                highlight=(t["highlight"] or {}).get("text"),
                position=position,
                messages=[LatexCommentMessage(**m) for m in t["messages"]],
            )
        )
    return LatexComments(
        path=doc.path,
        source=doc.source,
        rev=rev,
        branch=doc.branch,
        can_comment=doc.project.current_user_access
        in ("write", "admin", "owner"),
        threads=out,
    )


def _author(user: User) -> tuple[str, str]:
    email = user.email or f"{user.github_username}@users.noreply.github.com"
    return (user.full_name or user.github_username or user.email, email)


def _new_entry(user: User, text: str) -> calkit.latex.Entry:
    name, email = _author(user)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return calkit.latex.Entry(name, text, email, date)


def _commit(
    doc: _Document,
    current_user: User,
    session: Session,
    edit: Callable[[Read], dict[str, str]],
    message: str,
) -> str:
    """Make an edit to the source and commit it, returning the commit.

    On a branch, the edit goes on its tip, which may be ahead of what's
    being viewed. A tag or commit can't take one, so the edit goes on a
    branch of the user's own from it, with a pull request to the default
    branch, where it can be reviewed like any other change.
    """
    if doc.branch:
        target = doc.branch
    else:
        slug = re.sub(
            r"[^a-z0-9-]+", "-", current_user.account.name.lower()
        ).strip("-")
        target = f"calkit/comments/{slug}-{doc.rev[:7]}"
    for attempt in range(2):
        try:
            doc.repo.git.fetch(
                [
                    "origin",
                    f"+refs/heads/{target}:refs/remotes/origin/{target}",
                ]
            )
            base = doc.repo.commit(f"origin/{target}").hexsha
        except (GitCommandError, ValueError):
            # A new branch for comments on a tag or commit
            base = doc.rev
        files = edit(doc.reader(base))
        try:
            commit = commit_to_branch(
                doc.project,
                doc.repo,
                base,
                files,
                message,
                _author(current_user),
                target,
            )
            break
        except GitCommandError as e:
            logger.info(f"Push of comments to {target} was refused: {e}")
            # Someone else moved the branch in between, so start again from
            # where it is now. Anything else, e.g., a protected branch,
            # won't change by trying again.
            if not re.search(r"non-fast-forward|fetch first", str(e)):
                raise HTTPException(
                    502, f"Couldn't commit the comment to {target}"
                )
            if attempt:
                raise HTTPException(
                    409, "The document changed while saving; try again"
                )
    if not doc.branch:
        _ensure_pull_request(doc, current_user, session, target)
    return commit


def _ensure_pull_request(
    doc: _Document, current_user: User, session: Session, branch: str
) -> None:
    """Open a pull request for comments on a tag or commit, if there isn't
    one already."""
    github_repo = doc.project.github_repo
    if not github_repo:
        return
    token = _github_token_for_repo(session, current_user, github_repo)
    if token is None:
        return
    owner = github_repo.split("/")[0]
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    try:
        existing = requests.get(
            f"https://api.github.com/repos/{github_repo}/pulls",
            params={"head": f"{owner}:{branch}", "state": "open"},
            headers=headers,
            timeout=10,
        )
        if existing.ok and existing.json():
            return
        resp = requests.post(
            f"https://api.github.com/repos/{github_repo}/pulls",
            json={
                "title": f"Comments on {doc.path} at {doc.rev[:7]}",
                "head": branch,
                "base": get_default_branch(doc.repo),
                "body": (
                    f"Comments made on {doc.path} as built at {doc.rev[:7]}, "
                    f"in its source, {doc.source}."
                ),
            },
            headers=headers,
            timeout=10,
        )
        if not resp.ok:
            logger.warning(
                f"Could not open a pull request for {branch}: "
                f"{resp.status_code} {resp.text}"
            )
    except requests.RequestException as e:
        logger.warning(f"Could not open a pull request for {branch}: {e}")


def _find_thread(
    read: Read, source: str, key: str, like: dict | None = None
) -> dict | None:
    """A thread by its key, or one without an ID by its first message, in
    case its line moved."""
    threads = calkit.latex.list_comments(source, read)
    for t in threads:
        if t["id"] == key or f"{t['path']}:{t['line']}" == key:
            return t
    if like is not None and like["id"] is None:
        for t in threads:
            if (
                t["path"] == like["path"]
                and t["messages"][0] == like["messages"][0]
            ):
                return t
    return None


def _edit_thread(
    doc: _Document,
    key: str,
    change: Callable[[calkit.latex.TexComment], None] | None,
) -> tuple[Callable[[Read], dict[str, str]], dict]:
    """An edit to one thread, or deleting it with no change, and the thread
    as it's being viewed."""
    viewed = _find_thread(doc.reader(doc.rev), doc.source, key)
    if viewed is None:
        raise HTTPException(404, "No such comment thread")

    def edit(read: Read) -> dict[str, str]:
        t = _find_thread(read, doc.source, key, viewed)
        if t is None:
            raise HTTPException(404, "The comment thread is no longer there")
        lines = (read(t["path"]) or "").split("\n")
        tc = calkit.latex.find_comment(lines, lineno=t["line"])
        assert tc is not None
        if change is None:
            del lines[tc.lineno - 1 : tc.lineno - 1 + tc.nlines]
        else:
            change(tc)
            tc.id = tc.id or calkit.latex.new_comment_id()
            calkit.latex.write_comment(lines, tc)
        return {t["path"]: "\n".join(lines)}

    return edit, viewed


def _sync_closed_issues(
    doc: _Document,
    comments: LatexComments,
    session: Session,
    current_user: User | None,
) -> LatexComments:
    """Resolve threads whose GitHub issue was closed, in the source.

    Only that flows back from GitHub: the thread is the record, and the
    issue a mirror of it.
    """
    can_write = comments.can_comment and comments.branch is not None
    open_with_issue = [
        t for t in comments.threads if t.issue and not t.resolved
    ]
    if current_user is None or not can_write or not open_with_issue:
        return comments
    closed = []
    for t in open_with_issue:
        try:
            parts = str(t.issue).rstrip("/").split("/")
            repo_name, number = f"{parts[-4]}/{parts[-3]}", int(parts[-1])
            token = _github_token_for_repo(session, current_user, repo_name)
            headers = {"Accept": "application/vnd.github+json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            resp = requests.get(
                f"https://api.github.com/repos/{repo_name}/issues/{number}",
                headers=headers,
                timeout=5,
            )
            if resp.ok and resp.json().get("state") == "closed":
                closed.append(t.key)
        except Exception as e:
            logger.debug(f"Could not check issue {t.issue}: {e}")
    if not closed:
        return comments
    doc = _open_document(
        doc.project.owner_account.name,
        doc.project.name,
        doc.path,
        comments.branch,
        session,
        current_user,
        write=True,
    )

    def edit(read: Read) -> dict[str, str]:
        files: dict[str, str] = {}
        for key in closed:
            t = _find_thread(read, doc.source, key)
            if t is None:
                continue
            lines = (files.get(t["path"]) or read(t["path"]) or "").split("\n")
            tc = calkit.latex.find_comment(lines, lineno=t["line"])
            if tc is not None:
                tc.resolved = True
                tc.id = tc.id or calkit.latex.new_comment_id()
                calkit.latex.write_comment(lines, tc)
                files[t["path"]] = "\n".join(lines)
        return files

    try:
        commit = _commit(
            doc,
            current_user,
            session,
            edit,
            f"Resolve comments on {doc.path} closed on GitHub",
        )
    except HTTPException as e:
        logger.info(f"Could not resolve comments closed on GitHub: {e}")
        return comments
    return _read_comments(doc, commit, session, current_user)


@router.get("/projects/{owner_name}/{project_name}/latex-comments")
def get_project_latex_comments(
    owner_name: str,
    project_name: str,
    path: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
    ref: str | None = None,
) -> LatexComments:
    """The comment threads in the source of a PDF a latex stage builds."""
    doc = _open_document(
        owner_name, project_name, path, ref, session, current_user, write=False
    )
    comments = _read_comments(doc, doc.rev, session, current_user)
    return _sync_closed_issues(doc, comments, session, current_user)


@router.post("/projects/{owner_name}/{project_name}/latex-comments")
def post_project_latex_comment(
    owner_name: str,
    project_name: str,
    req: LatexCommentPost,
    session: SessionDep,
    current_user: CurrentUser,
) -> LatexComments:
    """Start a thread on some text selected in the PDF, in its source above
    the paragraph it's in, or on the whole document without a selection."""
    doc = _open_document(
        owner_name,
        project_name,
        req.path,
        req.ref,
        session,
        current_user,
        True,
    )
    highlight_text = None
    occ = 0
    paragraph = None
    if req.highlight is not None:
        layout = _read_layout(doc, doc.rev, session, current_user)
        located = (
            _locate_selection(doc, layout, doc.rev, req.highlight.model_dump())
            if layout is not None
            else None
        )
        if located is None:
            raise HTTPException(
                422, "Couldn't find where that is in the LaTeX source"
            )
        paragraph, highlight_text, occ = located
    tc = calkit.latex.TexComment(
        [_new_entry(current_user, req.comment)],
        highlight=highlight_text,
        highlight_occ=occ,
        id=calkit.latex.new_comment_id(),
    )
    if req.create_github_issue:
        link = _make_comment_artifact_link(
            owner_name, project_name, "publication", req.path
        )
        body = f"Comment on [{req.path}]({link}):\n\n{req.comment}"
        if highlight_text:
            body += f"\n\n> {highlight_text}"
        tc.issue = _try_create_github_issue(
            session,
            current_user,
            doc.project,
            _make_comment_title(req.comment),
            body,
        )

    def edit(read: Read) -> dict[str, str]:
        if paragraph is None:
            # On the whole document, at the top of it
            path, lineno = doc.source, 1
        else:
            blk = calkit.latex.locate_block(
                doc.source, text=paragraph, read=read
            )
            if blk is None:
                raise HTTPException(
                    409, "That paragraph changed since the PDF was built"
                )
            path, lineno = blk.path, blk.lineno
        lines = (read(path) or "").split("\n")
        calkit.latex.add_comment(lines, lineno, tc)
        return {path: "\n".join(lines)}

    commit = _commit(
        doc, current_user, session, edit, f"Comment on {req.path}"
    )
    return _read_comments(doc, commit, session, current_user)


@router.post("/projects/{owner_name}/{project_name}/latex-comments/replies")
def post_project_latex_comment_reply(
    owner_name: str,
    project_name: str,
    req: LatexCommentReplyPost,
    session: SessionDep,
    current_user: CurrentUser,
) -> LatexComments:
    doc = _open_document(
        owner_name,
        project_name,
        req.path,
        req.ref,
        session,
        current_user,
        True,
    )
    entry = _new_entry(current_user, req.body)
    edit, viewed = _edit_thread(
        doc, req.key, lambda tc: tc.entries.append(entry)
    )
    commit = _commit(
        doc, current_user, session, edit, f"Reply to a comment on {req.path}"
    )
    if viewed["issue"]:
        _try_post_github_issue_comment(
            session, current_user, viewed["issue"], req.body
        )
    return _read_comments(doc, commit, session, current_user)


@router.patch("/projects/{owner_name}/{project_name}/latex-comments")
def patch_project_latex_comment(
    owner_name: str,
    project_name: str,
    req: LatexCommentPatch,
    session: SessionDep,
    current_user: CurrentUser,
) -> LatexComments:
    """Resolve a thread, or reopen it."""
    doc = _open_document(
        owner_name,
        project_name,
        req.path,
        req.ref,
        session,
        current_user,
        True,
    )

    def change(tc: calkit.latex.TexComment) -> None:
        tc.resolved = req.resolved

    edit, viewed = _edit_thread(doc, req.key, change)
    verb = "Resolve" if req.resolved else "Reopen"
    commit = _commit(
        doc, current_user, session, edit, f"{verb} a comment on {req.path}"
    )
    if req.resolved:
        _try_close_github_issue(session, current_user, viewed["issue"])
    else:
        _try_reopen_github_issue(session, current_user, viewed["issue"])
    return _read_comments(doc, commit, session, current_user)


@router.delete("/projects/{owner_name}/{project_name}/latex-comments")
def delete_project_latex_comment(
    owner_name: str,
    project_name: str,
    path: str,
    key: str,
    session: SessionDep,
    current_user: CurrentUser,
    ref: str | None = None,
) -> LatexComments:
    """Delete a thread and its replies from the source."""
    doc = _open_document(
        owner_name, project_name, path, ref, session, current_user, True
    )
    edit, _ = _edit_thread(doc, key, None)
    commit = _commit(
        doc, current_user, session, edit, f"Delete a comment on {path}"
    )
    return _read_comments(doc, commit, session, current_user)


class LatexCommentsMove(BaseModel):
    path: str
    ref: str | None = None


@router.post("/projects/{owner_name}/{project_name}/latex-comments/move")
def post_project_latex_comments_move(
    owner_name: str,
    project_name: str,
    req: LatexCommentsMove,
    session: SessionDep,
    current_user: CurrentUser,
) -> LatexComments:
    """Move the comments on a PDF that are kept here into its LaTeX source,
    in one commit, so the source holds all of its discussion.

    Each goes above the paragraph it was made on, found from where it was
    selected in the PDF as built when it was made, with its replies, its
    authors, whether it's resolved, and its GitHub issue. One whose
    paragraph is gone goes at the top of the document, quoting what it was
    about.
    """
    doc = _open_document(
        owner_name,
        project_name,
        req.path,
        req.ref,
        session,
        current_user,
        True,
    )
    rows = list(
        session.exec(
            select(ProjectComment)
            .where(ProjectComment.project_id == doc.project.id)
            .where(ProjectComment.artifact_type == "publication")
            .where(ProjectComment.artifact_path == req.path)
            .where(col(ProjectComment.moved_to_source).is_(None))
        ).all()
    )
    roots = sorted(
        (c for c in rows if c.parent_id is None), key=lambda c: c.created
    )
    if not roots:
        raise HTTPException(400, "There are no comments here to move")
    layouts: dict[str, pdftext.PdfLayout | None] = {}
    moving: list[tuple[str | None, str | None, calkit.latex.TexComment]] = []
    for root in roots:
        thread = [root] + sorted(
            (c for c in rows if c.parent_id == root.id),
            key=lambda c: c.created,
        )
        entries = [
            calkit.latex.Entry(
                c.user_full_name or c.user_github_username or c.user_email,
                c.comment,
                c.user_email,
                c.created.strftime("%Y-%m-%d %H:%M"),
            )
            for c in thread
        ]
        located = None
        if root.highlight:
            rev = (
                resolve_commit_sha(doc.repo, root.git_rev)
                if root.git_rev
                else None
            ) or doc.rev
            if rev not in layouts:
                layouts[rev] = _read_layout(doc, rev, session, current_user)
            layout = layouts[rev]
            if layout is not None:
                located = _locate_selection(doc, layout, rev, root.highlight)
        paragraph, text, occ = located or (None, None, 0)
        quote = ((root.highlight or {}).get("content") or {}).get("text")
        moving.append(
            (
                paragraph,
                pdftext.normalize_selection(str(quote)) if quote else None,
                calkit.latex.TexComment(
                    entries,
                    highlight=text,
                    highlight_occ=occ,
                    resolved=root.resolved is not None,
                    id=calkit.latex.new_comment_id(),
                    issue=root.external_url,
                ),
            )
        )

    def edit(read: Read) -> dict[str, str]:
        placed = []
        for i, (paragraph, quote, original) in enumerate(moving):
            tc = deepcopy(original)
            blk = (
                calkit.latex.locate_block(
                    doc.source, text=paragraph, read=read
                )
                if paragraph is not None
                else None
            )
            if blk is None and quote:
                # Keep what it was about, since where can't be found
                tc.entries[0].text = f'On "{quote}": {tc.entries[0].text}'
                tc.highlight, tc.highlight_occ = None, 0
            # Without a place, it's on the whole document, at the top of it
            path, lineno = (blk.path, blk.lineno) if blk else (doc.source, 1)
            placed.append((path, lineno, i, tc))
        files: dict[str, list[str]] = {}
        # From the bottom up, so the places above don't move, and in order
        # on one paragraph, since each goes below those already above it
        for path, lineno, _, tc in sorted(
            placed, key=lambda x: (x[0], -x[1], x[2])
        ):
            if path not in files:
                files[path] = (read(path) or "").split("\n")
            calkit.latex.add_comment(files[path], lineno, tc)
        return {path: "\n".join(lines) for path, lines in files.items()}

    commit = _commit(
        doc,
        current_user,
        session,
        edit,
        f"Move {len(roots)} comments on {req.path} into its source",
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for c in rows:
        c.moved_to_source = now
        session.add(c)
    session.commit()
    return _read_comments(doc, commit, session, current_user)
