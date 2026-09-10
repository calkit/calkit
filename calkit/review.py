"""Merging a reviewed Word document back into its LaTeX source.

Two steps, so the decisions can be made anywhere: ``plan`` reads the
document and works out, per changed paragraph and per comment thread,
what merging would do to the source; ``apply`` does it for the items
the caller accepted. The CLI accepts everything Word already settled;
the hub shows the plan and lets the lead decide item by item. Both
write the same merge record, and a decision to reject is remembered
there so the next run doesn't offer it again.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass, field
from pathlib import Path

import calkit
import calkit.docx
import calkit.latex
from calkit.models.docx import (
    LatexDocxComment,
    LatexDocxCommentEntry,
    LatexDocxEdit,
    LatexDocxMerge,
    LatexDocxMergeChange,
    LatexDocxMergeComment,
)


class NotAnExportError(ValueError):
    """The document wasn't exported by Calkit, or lost its metadata."""


@dataclass
class MergePlan:
    export_id: str
    source: str
    rev: str | None
    docx: str
    wdir: str
    edits: list[LatexDocxEdit]
    comments: list[LatexDocxComment]
    media_changed: list[str]
    authors: list[str]
    last_modified_by: str | None
    files: dict[str, list[str]] = field(default_factory=dict, repr=False)
    _blocks: dict[str, calkit.latex.Block] = field(
        default_factory=dict, repr=False
    )
    _threads: dict[str, calkit.latex.TexComment] = field(
        default_factory=dict, repr=False
    )

    @property
    def paths(self) -> list[str]:
        return sorted(self.files)


def previous_decisions(
    export_id: str, wdir: str | None = None
) -> tuple[set[str], set[str]]:
    """Edits rejected and comments dismissed in earlier merges of an
    export, by key."""
    merges_dir = os.path.join(wdir or ".", calkit.latex.DOCX_MERGES_DIR)
    rejected: set[str] = set()
    dismissed: set[str] = set()
    if not os.path.isdir(merges_dir):
        return rejected, dismissed
    for name in sorted(os.listdir(merges_dir)):
        if not name.startswith(export_id + "-") or not name.endswith(".json"):
            continue
        try:
            record = LatexDocxMerge.model_validate_json(
                Path(merges_dir, name).read_text(encoding="utf-8")
            )
        except Exception:
            continue
        rejected |= {
            c.key for c in record.changes if c.status == "rejected" and c.key
        }
        dismissed |= {
            c.key for c in record.comments if c.status == "dismissed"
        }
    return rejected, dismissed


def plan(docx_path: str, wdir: str | None = None) -> MergePlan:
    """What merging ``docx_path`` would do to the source as it is now.

    Paths are relative to ``wdir``, the project root, which defaults to
    the current directory.
    """
    root = wdir or "."
    doc = calkit.docx.Document(os.path.join(root, docx_path))
    original = doc.read_original()
    if original is None:
        raise NotAnExportError(
            f"{docx_path} was not exported by Calkit, or its metadata was "
            "stripped by another application"
        )
    if not os.path.isfile(os.path.join(root, original.source)):
        raise FileNotFoundError(f"Source {original.source} does not exist")
    rejected, dismissed = previous_decisions(original.id, wdir)
    # Figures come from the pipeline, so a picture swapped or edited in
    # Word can't be merged
    media = doc.media_hashes
    media_changed = sorted(
        name
        for name in set(media) | set(original.media)
        if media.get(name) != original.media.get(name)
    )
    lines = calkit.latex.flatten(original.source, wdir=wdir)
    blks = calkit.latex.blocks(lines)
    path_for_hash = {
        calkit.latex.make_bookmark_name(p, 0).split("_")[1]: p
        for p in {ln.path for ln in lines}
    }

    def locate(bookmark: str) -> tuple[str, int]:
        parts = bookmark.split("_")
        return path_for_hash.get(parts[1], ""), int(parts[2])

    plan = MergePlan(
        export_id=original.id,
        source=original.source,
        rev=original.rev,
        docx=Path(docx_path).as_posix(),
        wdir=root,
        edits=[],
        comments=[],
        media_changed=media_changed,
        authors=[],
        last_modified_by=doc.last_modified_by,
        files={
            p: Path(root, p).read_text(encoding="utf-8").split("\n")
            for p in {ln.path for ln in lines}
        },
    )
    paragraphs = doc.paragraphs
    for para in paragraphs:
        if para.bookmark is None or para.bookmark not in original.paragraphs:
            continue
        sent = original.paragraphs[para.bookmark]
        if para.text == sent:
            continue
        path, lineno = locate(para.bookmark)
        item = LatexDocxEdit(
            key=para.bookmark,
            path=path,
            lineno=lineno,
            status="unplaced",
            sent=sent,
            proposed=para.text,
            authors=list(para.authors),
        )
        plan.edits.append(item)
        blk = calkit.latex.find_block(
            blks, path, lineno, sent
        ) or calkit.latex.find_block(blks, path, lineno, para.text)
        if blk is None:
            item.reason = "The paragraph can't be found in the source"
            continue
        item.path, item.lineno = blk.path, blk.lineno
        item.source = [ln.text for ln in blk.lines]
        plan._blocks[item.key] = blk
        if para.bookmark in rejected:
            item.status = "rejected"
            continue
        sent_tex = calkit.latex.from_word_text(sent)
        new_tex = calkit.latex.from_word_text(para.text)
        if calkit.latex.already_applied(blk, sent_tex, new_tex):
            item.status = "already-applied"
            continue
        item.result = calkit.latex.apply_edit(blk, sent_tex, new_tex)
        if item.result is None:
            item.reason = "The edit touches markup the reviewer couldn't see"
            continue
        item.status = "pending" if para.pending else "applicable"
    # Threads keyed by root, anchored through the root's bookmark
    comments = doc.comments
    by_id = {c.para_id: c for c in comments}
    for root in comments:
        if root.parent_id:
            continue
        thread = [root] + [
            c
            for c in comments
            if c.parent_id and by_id.get(c.parent_id) is root
        ]
        tc = calkit.latex.TexComment(
            [
                calkit.latex.Entry(
                    c.author, c.text, date=calkit.latex.word_date(c.date)
                )
                for c in thread
            ],
            highlight=root.highlight,
            highlight_occ=root.highlight_occ,
            resolved=root.done,
        )
        item = LatexDocxComment(
            key=root.para_id,
            path="",
            lineno=0,
            status="unplaced",
            entries=[
                LatexDocxCommentEntry(
                    author=e.author, text=e.text, date=e.date
                )
                for e in tc.entries
            ],
            highlight=root.highlight,
            resolved=root.done,
        )
        plan.comments.append(item)
        if root.bookmark is None:
            continue
        path, lineno = locate(root.bookmark)
        item.path, item.lineno = path, lineno
        blk = calkit.latex.find_block(
            blks, path, lineno, original.paragraphs.get(root.bookmark, "")
        )
        if blk is None:
            continue
        item.path, item.lineno = blk.path, blk.lineno
        item.source = [ln.text for ln in blk.lines]
        plan._blocks[item.key] = blk
        plan._threads[item.key] = tc
        if root.para_id in dismissed:
            item.status = "dismissed"
            continue
        existing = _existing_thread(plan.files[blk.path], tc)
        if existing is None:
            item.status = "new"
        elif (
            existing.messages() == tc.messages()
            and existing.resolved == tc.resolved
        ):
            item.status = "unchanged"
        else:
            item.status = "updated"
    seen = {a for p in paragraphs for a in p.authors}
    seen |= {c.author for c in comments}
    plan.authors = sorted(seen)
    return plan


def _existing_thread(
    content: list[str], tc: calkit.latex.TexComment
) -> calkit.latex.TexComment | None:
    return next(
        (
            e
            for e in calkit.latex.parse_comments(content)
            if e.author == tc.author and e.text == tc.text
        ),
        None,
    )


def apply(
    plan: MergePlan,
    accept: set[str] | None = None,
    reject: set[str] | None = None,
    dismiss: set[str] | None = None,
    write_comments: bool = True,
) -> LatexDocxMerge:
    """Write the accepted edits and the comments to the source.

    With ``accept`` unset, every ``applicable`` edit is written and
    ``pending`` ones are left alone, which is the CLI's reading of a
    document the lead already went through in Word. Given explicitly, it
    names the edits to write, pending or not, and ``reject`` those to
    decline for good. ``dismiss`` names comment threads to keep out of
    the source. Everything else is left for another run.
    """
    reject = reject or set()
    dismiss = dismiss or set()
    edits: dict[str, list[tuple[int, int, list[str]]]] = {}
    changes: list[LatexDocxMergeChange] = []
    for item in plan.edits:
        author = ", ".join(item.authors) or None
        change = LatexDocxMergeChange(
            key=item.key,
            path=item.path,
            lineno=item.lineno,
            status=item.status,
            author=author,
        )
        if item.key in reject and item.status not in ("rejected",):
            change.status = "rejected"
        elif item.status in ("applicable", "pending") and (
            item.key in accept
            if accept is not None
            else item.status == "applicable"
        ):
            assert item.result is not None
            edits.setdefault(item.path, []).append(
                (item.lineno, len(item.source), item.result)
            )
            change.status = "applied"
        changes.append(change)
    files = {p: list(lines) for p, lines in plan.files.items()}
    for path, updates in edits.items():
        for lineno, count, new_lines in sorted(updates, reverse=True):
            files[path][lineno - 1 : lineno - 1 + count] = new_lines
    comments: list[LatexDocxMergeComment] = []
    placed: list[tuple[calkit.latex.Block, calkit.latex.TexComment, str]] = []
    for item in plan.comments:
        record = LatexDocxMergeComment(
            key=item.key,
            path=item.path,
            lineno=item.lineno,
            status=item.status,
            author=item.entries[0].author if item.entries else None,
        )
        comments.append(record)
        if item.key in dismiss and item.status != "dismissed":
            record.status = "dismissed"
            continue
        if not write_comments or item.status not in ("new", "updated"):
            continue
        placed.append(
            (plan._blocks[item.key], plan._threads[item.key], item.key)
        )
    # Edit each file from the bottom up so earlier line numbers stay valid
    status_for = {c.key: c for c in comments}
    for blk, tc, key in sorted(
        placed, key=lambda x: (x[0].path, x[0].lineno), reverse=True
    ):
        content = files[blk.path]
        at = blk.lineno
        existing = _existing_thread(content, tc)
        if existing is not None:
            # Word knows neither emails nor what the source already
            # recorded, so carry those over for unchanged messages
            known = {(e.author, e.text): e for e in existing.entries}
            for e in tc.entries:
                old_e = known.get((e.author, e.text))
                if old_e is not None:
                    e.email = old_e.email
                    e.date = old_e.date or e.date
            del content[
                existing.lineno - 1 : existing.lineno - 1 + existing.nlines
            ]
            if existing.lineno < at:
                at -= existing.nlines
        content[at - 1 : at - 1] = tc.render()
        status_for[key].status = "added" if existing is None else "updated"
    for path, content in files.items():
        new = "\n".join(content)
        full = Path(plan.wdir, path)
        if new != full.read_text(encoding="utf-8"):
            full.write_text(new, encoding="utf-8")
    rev = None
    try:
        import calkit.git

        rev = calkit.git.get_repo(plan.wdir).head.commit.hexsha
    except Exception:
        pass
    return LatexDocxMerge(
        export_id=plan.export_id,
        created=datetime.datetime.now(datetime.timezone.utc),
        docx=plan.docx,
        rev=rev,
        authors=plan.authors,
        last_modified_by=plan.last_modified_by,
        changes=changes,
        comments=comments,
        comments_added=sum(1 for c in comments if c.status == "added"),
        comments_updated=sum(1 for c in comments if c.status == "updated"),
        files={
            p: "md5:" + calkit.get_md5(os.path.join(plan.wdir, p))
            for p in sorted(set(plan.files) | {plan.docx})
        },
    )


def write_record(record: LatexDocxMerge, wdir: str | None = None) -> str:
    """Save a merge record where ``previous_decisions`` will find it,
    returning its path relative to the project."""
    stamp = record.created.strftime("%Y%m%dT%H%M%S.%fZ")
    rel = os.path.join(
        calkit.latex.DOCX_MERGES_DIR, f"{record.export_id}-{stamp}.json"
    )
    path = os.path.join(wdir or ".", rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(record.model_dump_json(indent=2))
    return rel


def summary(record: LatexDocxMerge) -> str:
    counts = {
        s: sum(1 for c in record.changes if c.status == s)
        for s in ("applied", "already-applied", "pending", "unplaced")
    }
    return (
        f"Applied {counts['applied']} edits ({counts['already-applied']} "
        f"already there, {counts['pending']} pending, {counts['unplaced']} "
        f"unplaced); {record.comments_added} comments added, "
        f"{record.comments_updated} updated"
    )
