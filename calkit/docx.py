"""Reading and writing Word documents for LaTeX review round trips."""

from __future__ import annotations

import copy
import hashlib
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
DC = "http://purl.org/dc/elements/1.1/"
CK_NS = "https://calkit.org/review"
# Where Word looks up a comment's thread and resolved state
COMMENTS_EX_TYPE = (
    "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"
)
COMMENTS_EX_CT = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml"
    ".commentsExtended+xml"
)
COMMENTS_CT = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml"
    ".comments+xml"
)
BOOKMARK_PREFIX = "ck_"

for _p, _u in [
    ("w", W),
    ("w14", W14),
    ("w15", W15),
    ("r", REL),
    ("dc", DC),
    (
        "cp",
        "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    ),
    ("dcterms", "http://purl.org/dc/terms/"),
    ("xsi", "http://www.w3.org/2001/XMLSchema-instance"),
    ("mc", "http://schemas.openxmlformats.org/markup-compatibility/2006"),
]:
    ET.register_namespace(_p, _u)


def _tag(ns: str, name: str) -> str:
    return f"{{{ns}}}{name}"


_XMLNS_RE = re.compile(r'xmlns:(\w+)="([^"]*)"')


def _parse(data: bytes) -> ET.Element:
    """Parse a part, keeping its prefixes so Word gets them back."""
    for prefix, uri in _XMLNS_RE.findall(data.decode()[:4000]):
        if not re.fullmatch(r"ns\d+", prefix):
            ET.register_namespace(prefix, uri)
    return ET.fromstring(data)


def _dump(root: ET.Element, original: bytes | None) -> bytes:
    """Serialize a part, restoring declarations ElementTree drops.

    Word lists prefixes in ``mc:Ignorable`` and refuses a part that doesn't
    declare them, even when nothing uses them.
    """
    out: str = ET.tostring(
        root, xml_declaration=True, encoding="UTF-8"
    ).decode()
    if original is not None:
        start = out.index("<", out.index("?>"))
        end = out.index(">", start)
        tag = out[start:end]
        missing = [
            f' xmlns:{p}="{u}"'
            for p, u in _XMLNS_RE.findall(original.decode()[:4000])
            if f"xmlns:{p}=" not in tag
        ]
        out = out[:end] + "".join(missing) + out[end:]
    return out.encode()


@dataclass
class Paragraph:
    """A body paragraph: its accept-all text and any bookmark it carries."""

    text: str
    bookmark: str | None = None
    pending: bool = False
    authors: list[str] = field(default_factory=list)
    element: ET.Element | None = field(default=None, repr=False)


@dataclass
class Comment:
    author: str
    date: str | None
    text: str
    para_id: str
    parent_id: str | None = None
    done: bool = False
    bookmark: str | None = None
    highlight: str | None = None


@dataclass
class Original:
    """What the custom XML part records about the export."""

    uuid: str
    rev: str | None
    source: str
    paragraphs: dict[str, str]
    media: dict[str, str] = field(default_factory=dict)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _in(el_parents: dict, el: ET.Element, stop: ET.Element, tag: str) -> bool:
    node = el_parents.get(el)
    while node is not None and node is not stop:
        if node.tag == tag:
            return True
        node = el_parents.get(node)
    return False


class Document:
    """A .docx package, edited in place and written back out."""

    def __init__(self, path: str):
        self.path = path
        with zipfile.ZipFile(path) as z:
            self.parts = {n: z.read(n) for n in z.namelist()}
        self.doc = _parse(self.parts["word/document.xml"])
        self._parents = {c: p for p in self.doc.iter() for c in p}

    def save(self, path: str | None = None) -> None:
        self.parts["word/document.xml"] = _dump(
            self.doc, self.parts["word/document.xml"]
        )
        with zipfile.ZipFile(
            path or self.path, "w", zipfile.ZIP_DEFLATED
        ) as z:
            for name, data in self.parts.items():
                z.writestr(name, data)

    def paragraphs(self) -> list[Paragraph]:
        out = []
        for p in self.doc.iter(_tag(W, "p")):
            if _in(self._parents, p, self.doc, _tag(W, "txbxContent")):
                continue
            texts, pending = [], False
            authors: list[str] = []
            for el in p.iter():
                if _in(self._parents, el, p, _tag(W, "del")):
                    continue
                if el.tag == _tag(W, "t"):
                    texts.append(el.text or "")
                elif el.tag in (_tag(W, "tab"), _tag(W, "br"), _tag(W, "cr")):
                    texts.append(" ")
                elif el.tag in (_tag(W, "ins"), _tag(W, "del")):
                    pending = True
                    author = el.get(_tag(W, "author"))
                    if author and author not in authors:
                        authors.append(author)
            bookmark = None
            for b in p.iter(_tag(W, "bookmarkStart")):
                name = b.get(_tag(W, "name"), "")
                if name.startswith(BOOKMARK_PREFIX):
                    bookmark = name
            text = normalize("".join(texts))
            if text or bookmark:
                out.append(Paragraph(text, bookmark, pending, authors, p))
        return out

    def add_bookmark(self, para: ET.Element, name: str, bid: int) -> None:
        start = ET.Element(_tag(W, "bookmarkStart"))
        start.set(_tag(W, "id"), str(bid))
        start.set(_tag(W, "name"), name)
        end = ET.Element(_tag(W, "bookmarkEnd"))
        end.set(_tag(W, "id"), str(bid))
        idx = 1 if len(para) and para[0].tag == _tag(W, "pPr") else 0
        para.insert(idx, end)
        para.insert(idx, start)

    # Custom XML part carrying the original text and export identity
    def write_original(self, original: Original) -> None:
        root = ET.Element(_tag(CK_NS, "review"))
        root.set("uuid", original.uuid)
        root.set("source", original.source)
        if original.rev:
            root.set("rev", original.rev)
        for name, text in original.paragraphs.items():
            p = ET.SubElement(root, _tag(CK_NS, "p"))
            p.set("id", name)
            p.text = text
        for name, digest in original.media.items():
            m = ET.SubElement(root, _tag(CK_NS, "media"))
            m.set("name", name)
            m.set("sha1", digest)
        self.parts["customXml/item1.xml"] = ET.tostring(
            root, xml_declaration=True, encoding="UTF-8"
        )
        self.parts["customXml/itemProps1.xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<ds:datastoreItem ds:itemID="{%s}" xmlns:ds="http://schemas.'
            'openxmlformats.org/officeDocument/2006/customXml"><ds:schemaRefs>'
            '<ds:schemaRef ds:uri="%s"/></ds:schemaRefs></ds:datastoreItem>'
            % (original.uuid.upper(), CK_NS)
        ).encode()
        self.parts["customXml/_rels/item1.xml.rels"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%s/'
            'customXmlProps" Target="itemProps1.xml"/></Relationships>'
            % (PKG_REL, REL)
        ).encode()
        self._add_rel("customXml", "../customXml/item1.xml")
        self._ensure_default_ct("xml", "application/xml")

    def read_original(self) -> Original | None:
        data = self.parts.get("customXml/item1.xml")
        if data is None:
            return None
        root = ET.fromstring(data)
        if root.tag != _tag(CK_NS, "review"):
            return None
        return Original(
            uuid=root.get("uuid", ""),
            rev=root.get("rev"),
            source=root.get("source", ""),
            paragraphs={
                p.get("id", ""): p.text or ""
                for p in root.iter(_tag(CK_NS, "p"))
            },
            media={
                m.get("name", ""): m.get("sha1", "")
                for m in root.iter(_tag(CK_NS, "media"))
            },
        )

    def media_hashes(self) -> dict[str, str]:
        """Images and other embedded media, by part name."""
        return {
            name: hashlib.sha1(data).hexdigest()
            for name, data in self.parts.items()
            if name.startswith("word/media/")
        }

    def last_modified_by(self) -> str | None:
        core = ET.fromstring(self.parts["docProps/core.xml"])
        el = core.find(
            "{http://schemas.openxmlformats.org/package/2006/metadata/"
            "core-properties}lastModifiedBy"
        )
        return el.text if el is not None else None

    def set_identifier(self, value: str) -> None:
        core = _parse(self.parts["docProps/core.xml"])
        el = core.find(_tag(DC, "identifier"))
        if el is None:
            el = ET.SubElement(core, _tag(DC, "identifier"))
        el.text = value
        self.parts["docProps/core.xml"] = _dump(
            core, self.parts["docProps/core.xml"]
        )

    def _settings_insert(self, el: ET.Element) -> None:
        """Add a settings element in schema order, replacing any of its
        kind: after w:zoom and friends, before w:defaultTabStop."""
        settings = _parse(self.parts["word/settings.xml"])
        for old in settings.findall(el.tag):
            settings.remove(old)
        idx = len(settings)
        for i, child in enumerate(settings):
            if child.tag == _tag(W, "defaultTabStop"):
                idx = i
                break
        settings.insert(idx, el)
        self.parts["word/settings.xml"] = _dump(
            settings, self.parts["word/settings.xml"]
        )

    def track_changes(self) -> None:
        """Turn Track Changes on, so it's on when the document opens."""
        self._settings_insert(ET.Element(_tag(W, "trackRevisions")))

    def tracking(self) -> bool:
        settings = ET.fromstring(self.parts["word/settings.xml"])
        return settings.find(_tag(W, "trackRevisions")) is not None

    def show_all_markup(self) -> None:
        """Force the "All Markup" display mode when the document opens.

        Without this, Word falls back to its own app-wide display
        preference (often "Simple Markup"), which hides inline insertions
        and deletions a reviewer needs to see. Appended rather than run
        through ``_settings_insert``: unlike trackRevisions/
        documentProtection, w:revisionView belongs near the very end of
        CT_Settings' schema order, well after w:defaultTabStop.
        """
        settings = _parse(self.parts["word/settings.xml"])
        for old in settings.findall(_tag(W, "revisionView")):
            settings.remove(old)
        el = ET.SubElement(settings, _tag(W, "revisionView"))
        for attr in ("insDel", "formatting", "inkAnnotations", "markup"):
            el.set(_tag(W, attr), "1")
        self.parts["word/settings.xml"] = _dump(
            settings, self.parts["word/settings.xml"]
        )

    def protect(self, edit: str) -> None:
        """Lock the document to comments or tracked changes (no password)."""
        el = ET.Element(_tag(W, "documentProtection"))
        el.set(_tag(W, "edit"), edit)
        el.set(_tag(W, "enforcement"), "1")
        self._settings_insert(el)

    def protection(self) -> str | None:
        """The edit restriction in force, or None if none or unenforced."""
        settings = ET.fromstring(self.parts["word/settings.xml"])
        el = settings.find(_tag(W, "documentProtection"))
        if el is None or el.get(_tag(W, "enforcement")) != "1":
            return None
        return el.get(_tag(W, "edit"))

    def comments(self) -> list[Comment]:
        data = self.parts.get("word/comments.xml")
        if data is None:
            return []
        threads: dict[str, tuple[str | None, bool]] = {}
        ex = self.parts.get("word/commentsExtended.xml")
        if ex is not None:
            for c in ET.fromstring(ex).iter(_tag(W15, "commentEx")):
                threads[c.get(_tag(W15, "paraId"), "")] = (
                    c.get(_tag(W15, "paraIdParent")),
                    c.get(_tag(W15, "done")) == "1",
                )
        # Which bookmark each comment range lands in: the paragraph's own,
        # else the last one seen
        anchors: dict[str, str | None] = {}
        ranges: dict[str, list[str]] = {}
        whole: dict[str, str] = {}
        current = None
        for p in self.doc.iter(_tag(W, "p")):
            own = next(
                (
                    b.get(_tag(W, "name"))
                    for b in p.iter(_tag(W, "bookmarkStart"))
                    if b.get(_tag(W, "name"), "").startswith(BOOKMARK_PREFIX)
                ),
                None,
            )
            current = own or current
            open_ids: set[str] = set()
            para_text: list[str] = []
            for el in p.iter():
                cid = el.get(_tag(W, "id"), "")
                if el.tag == _tag(W, "commentRangeStart"):
                    anchors[cid] = current
                    open_ids.add(cid)
                    ranges.setdefault(cid, [])
                elif el.tag == _tag(W, "commentRangeEnd"):
                    open_ids.discard(cid)
                elif el.tag == _tag(W, "commentReference"):
                    anchors.setdefault(cid, current)
                elif el.tag == _tag(W, "t") and not _in(
                    self._parents, el, p, _tag(W, "del")
                ):
                    para_text.append(el.text or "")
                    for oid in open_ids:
                        ranges[oid].append(el.text or "")
            for oid in list(ranges):
                whole.setdefault(oid, normalize("".join(para_text)))
        out = []
        for c in ET.fromstring(data).iter(_tag(W, "comment")):
            first = c.find(_tag(W, "p"))
            para_id = (
                first.get(_tag(W14, "paraId"), "") if first is not None else ""
            )
            parent, done = threads.get(para_id, (None, False))
            text = normalize(
                " ".join(
                    "".join(t.text or "" for t in p.iter(_tag(W, "t")))
                    for p in c.iter(_tag(W, "p"))
                )
            )
            cid = c.get(_tag(W, "id"), "")
            # A range covering the whole paragraph says nothing extra
            highlight = normalize("".join(ranges.get(cid, []))) or None
            if highlight == whole.get(cid):
                highlight = None
            out.append(
                Comment(
                    author=c.get(_tag(W, "author"), ""),
                    date=c.get(_tag(W, "date")),
                    text=text,
                    para_id=para_id,
                    parent_id=parent,
                    done=done,
                    bookmark=anchors.get(cid),
                    highlight=highlight,
                )
            )
        # Resolved is recorded on the root; replies inherit it
        by_id = {cm.para_id: cm for cm in out}
        for cm in out:
            top = cm
            while top.parent_id and top.parent_id in by_id:
                top = by_id[top.parent_id]
            cm.done = top.done
        return out

    def _split_run(self, para: ET.Element, offset: int) -> int:
        """Split the run containing text offset ``offset`` so a marker can
        go there; returns the child index the marker goes at."""
        pos = 0
        for i, run in enumerate(list(para)):
            if run.tag != _tag(W, "r"):
                continue
            text = "".join(t.text or "" for t in run.iter(_tag(W, "t")))
            if pos + len(text) <= offset:
                pos += len(text)
                continue
            if pos == offset:
                return i
            cut = offset - pos
            first = copy.deepcopy(run)
            for t in first.iter(_tag(W, "t")):
                t.text = (t.text or "")[:cut]
                t.set(
                    "{http://www.w3.org/XML/1998/namespace}space", "preserve"
                )
            for t in run.iter(_tag(W, "t")):
                t.text = (t.text or "")[cut:]
                t.set(
                    "{http://www.w3.org/XML/1998/namespace}space", "preserve"
                )
            para.insert(i, first)
            return i + 1
        return len(para)

    def add_comments(
        self,
        threads: list[list[tuple[str, str]]],
        paras: list[ET.Element],
        highlights: list[str | None] | None = None,
        resolved: list[bool] | None = None,
    ) -> None:
        """Attach comment threads, each a list of (author, text), to
        paragraphs; ``paras[i]`` anchors ``threads[i]``, around
        ``highlights[i]`` if that text is found, else the whole paragraph."""
        if not threads:
            return
        highlights = highlights or [None] * len(threads)
        resolved = resolved or [False] * len(threads)
        # Append to whatever comments the document already has
        existing = self.parts.get("word/comments.xml")
        comments = (
            _parse(existing)
            if existing is not None
            else ET.Element(_tag(W, "comments"))
        )
        existing_ex = self.parts.get("word/commentsExtended.xml")
        extended = (
            _parse(existing_ex)
            if existing_ex is not None
            else ET.Element(_tag(W15, "commentsEx"))
        )
        cid = 1 + max(
            (
                int(c.get(_tag(W, "id"), "0"))
                for c in comments.iter(_tag(W, "comment"))
            ),
            default=-1,
        )
        for thread, para, highlight, done in zip(
            threads, paras, highlights, resolved
        ):
            parent_pid = None
            para_text = "".join(t.text or "" for t in para.iter(_tag(W, "t")))
            at = para_text.find(highlight) if highlight else -1
            for author, text in thread:
                pid = f"{0x7C000000 + cid:08X}"
                c = ET.SubElement(comments, _tag(W, "comment"))
                c.set(_tag(W, "id"), str(cid))
                c.set(_tag(W, "author"), author)
                p = ET.SubElement(c, _tag(W, "p"))
                p.set(_tag(W14, "paraId"), pid)
                r = ET.SubElement(p, _tag(W, "r"))
                ET.SubElement(r, _tag(W, "annotationRef"))
                r = ET.SubElement(p, _tag(W, "r"))
                t = ET.SubElement(r, _tag(W, "t"))
                t.text = text
                ex = ET.SubElement(extended, _tag(W15, "commentEx"))
                ex.set(_tag(W15, "paraId"), pid)
                if parent_pid:
                    ex.set(_tag(W15, "paraIdParent"), parent_pid)
                ex.set(_tag(W15, "done"), "1" if done else "0")
                # Range around the paragraph's runs
                start = ET.Element(_tag(W, "commentRangeStart"))
                start.set(_tag(W, "id"), str(cid))
                end = ET.Element(_tag(W, "commentRangeEnd"))
                end.set(_tag(W, "id"), str(cid))
                ref_run = ET.Element(_tag(W, "r"))
                ref = ET.SubElement(ref_run, _tag(W, "commentReference"))
                ref.set(_tag(W, "id"), str(cid))
                if at >= 0 and highlight:
                    para.insert(
                        self._split_run(para, at + len(highlight)), end
                    )
                    para.insert(self._split_run(para, at), start)
                    para.append(ref_run)
                else:
                    # After the paragraph properties and any bookmarks
                    idx = 0
                    for i, child in enumerate(para):
                        if child.tag in (
                            _tag(W, "pPr"),
                            _tag(W, "bookmarkStart"),
                            _tag(W, "bookmarkEnd"),
                        ):
                            idx = i + 1
                    para.insert(idx, start)
                    para.append(end)
                    para.append(ref_run)
                parent_pid = parent_pid or pid
                cid += 1
        self.parts["word/comments.xml"] = _dump(comments, existing)
        self.parts["word/commentsExtended.xml"] = _dump(extended, existing_ex)
        self._add_rel("comments", "comments.xml")
        self._add_rel(COMMENTS_EX_TYPE, "commentsExtended.xml", full=True)
        self._ensure_override("/word/comments.xml", COMMENTS_CT)
        self._ensure_override("/word/commentsExtended.xml", COMMENTS_EX_CT)

    def _add_rel(self, kind: str, target: str, full: bool = False) -> None:
        name = "word/_rels/document.xml.rels"
        rels = _parse(self.parts[name])
        rtype = kind if full else f"{REL}/{kind}"
        for r in rels:
            if r.get("Type") == rtype and r.get("Target") == target:
                return
        rel = ET.SubElement(rels, _tag(PKG_REL, "Relationship"))
        rel.set("Id", f"rIdCk{len(rels)}")
        rel.set("Type", rtype)
        rel.set("Target", target)
        self.parts[name] = _dump(rels, self.parts[name])

    def _content_types(self) -> ET.Element:
        return _parse(self.parts["[Content_Types].xml"])

    def _save_content_types(self, root: ET.Element) -> None:
        self.parts["[Content_Types].xml"] = _dump(
            root, self.parts["[Content_Types].xml"]
        )

    def _ensure_default_ct(self, ext: str, ctype: str) -> None:
        ns = "http://schemas.openxmlformats.org/package/2006/content-types"
        root = self._content_types()
        if any(
            d.get("Extension") == ext for d in root.iter(_tag(ns, "Default"))
        ):
            return
        el = ET.SubElement(root, _tag(ns, "Default"))
        el.set("Extension", ext)
        el.set("ContentType", ctype)
        self._save_content_types(root)

    def _ensure_override(self, part: str, ctype: str) -> None:
        ns = "http://schemas.openxmlformats.org/package/2006/content-types"
        root = self._content_types()
        if any(
            o.get("PartName") == part for o in root.iter(_tag(ns, "Override"))
        ):
            return
        el = ET.SubElement(root, _tag(ns, "Override"))
        el.set("PartName", part)
        el.set("ContentType", ctype)
        self._save_content_types(root)


def pdf_to_docx(pdf_path: str, docx_path: str) -> None:
    """Convert a PDF to .docx with Word's own importer."""
    pdf_path, docx_path = os.path.abspath(pdf_path), os.path.abspath(docx_path)
    # Word won't save over a document it has open, so write beside the
    # target and move into place
    tmp_path = docx_path[: -len(".docx")] + ".tmp.docx"
    if sys.platform == "darwin":
        script = (
            'tell application "Microsoft Word"\n'
            "set display alerts to alerts none\n"
            f'open (POSIX file "{pdf_path}")\n'
            # The import runs after open returns; wait for the document
            "repeat 1200 times\n"
            f'if exists document "{os.path.basename(pdf_path)}" then '
            "exit repeat\n"
            "delay 0.1\n"
            "end repeat\n"
            f'set doc to document "{os.path.basename(pdf_path)}"\n'
            f'save as doc file name "{tmp_path}" file format format document\n'
            f'close document "{os.path.basename(tmp_path)}" saving no\n'
            "end tell"
        )
        res = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True
        )
        if res.returncode != 0:
            raise RuntimeError(
                "Word could not convert the PDF: "
                + res.stderr.strip().split(": ", 1)[-1]
            )
    elif sys.platform == "win32":
        import win32com.client  # type: ignore[import-not-found]

        word = win32com.client.Dispatch("Word.Application")
        word.DisplayAlerts = 0
        doc = word.Documents.Open(pdf_path, ConfirmConversions=False)
        # Word's PDF reconstruction leaves the doc protected/marked final,
        # which blocks editing and commenting; macOS's import doesn't.
        if doc.ProtectionType != -1:  # wdNoProtection
            doc.Unprotect()
        doc.Final = False
        doc.ReadOnlyRecommended = False
        doc.SaveAs2(tmp_path, FileFormat=12)
        doc.Close(False)
    else:
        raise RuntimeError(
            "Converting PDF to Word requires Word on macOS or Windows"
        )
    os.replace(tmp_path, docx_path)
