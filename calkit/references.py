"""Checking that the references a document cites are real.

A citation can be wrong in three ways a build does not catch. The key can
be missing from every collection, which BibTeX mentions and a reader of
the PDF sees only as a question mark. The entry can exist and describe a
work that does not, which is what a language model produces when it
invents a plausible citation. Or the entry can carry an identifier that
resolves to a different work than its title and authors name, which is
the same mistake wearing a real DOI.

Keys are read from a document and the files it inputs rather than from
the compiled PDF, since that is where a key is written and where it has
to be fixed, so a PDF is checked by reading the source it is built from.
A bibliography can also be checked on its own, every entry in it. Each is resolved against the
bibliographies the document names, or the collections ``calkit.yaml``
declares when it names none, and each entry is then looked for in
Crossref, OpenAlex, and arXiv, by identifier when it has one and by title
when it does not. A candidate is compared on title, first author, and
year, so an entry whose DOI resolves to something else is reported rather
than trusted, even when a search for its title finds the right work.

The check is deliberately quiet about what it cannot know. A title search
always returns its nearest neighbor, so a candidate that does not
resemble the title it was found with is a failed search rather than a
disagreement to report. A work in a venue these services do not index,
e.g., anything in PMLR, which registers no DOIs, looks exactly like a
work that does not exist; those are reported as not found, with the venue
named, and they do not fail the check. What fails it is decidable: a key
in no collection, read locally, and an identifier that resolves to
another work, which carries the record it disagrees with.

A ``references-check`` stage writes one report per document, by default
to ``.calkit/reference-checks``, so each is a pipeline output with its own
dependencies. Reports carry no timestamp, so a report is a function of the
sources that produced it and can be checked for staleness like any other
output. Answers from the services are cached under ``.calkit/local``,
which is not tracked, so a rerun needs no network and ``--offline`` still
reports everything that does not. A request that fails, e.g., without a
network, is not cached, and what it would have answered is reported as
unchecked rather than as not found.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

OUT_DIR = ".calkit/reference-checks"
CACHE_PATH = ".calkit/local/reference-check-cache.json"

# Named without a contact address on purpose: the polite pools ask for an
# email, and the user's is not ours to hand to a third party.
USER_AGENT = "calkit-reference-check (+https://github.com/calkit/calkit)"

# Seconds between requests, since these services are free and anonymous.
REQUEST_DELAY_S = 0.4

# Above this, two titles are the same work cited loosely; below the
# plausible threshold, a search result is the nearest neighbor of a query
# that matched nothing, and reporting it would accuse the entry of
# describing an unrelated paper.
TITLE_MATCH = 0.90
TITLE_PLAUSIBLE = 0.60

# A title this short cannot discriminate, so it is left uncompared.
MIN_TITLE_CHARS = 12

# Venues the services index thinly or not at all. An entry naming one and
# not found needs a person to look rather than a correction.
THIN_VENUES = (
    "machine learning research",
    "conference on machine learning",
    "pmlr",
    "neural information processing systems",
    "neurips",
    "nips",
    "learning representations",
    "iclr",
)

Status = Literal[
    "verified",
    "doi-not-registered",
    "mismatch",
    "not-found",
    "unchecked",
    "not-checkable",
    "missing-from-bib",
]

# Everything that fails the check. ``not-found`` is left out: a work
# nobody indexes is indistinguishable from one that does not exist. The
# rest are decidable -- a key in no collection is read locally, an
# unregistered DOI is settled by the handle system, and a mismatch
# carries the record it disagrees with.
BLOCKING: tuple[Status, ...] = (
    "missing-from-bib",
    "doi-not-registered",
    "mismatch",
)

# Everything worth a reader's attention, failing or not, worst first.
SUSPECT: tuple[Status, ...] = (
    "missing-from-bib",
    "doi-not-registered",
    "mismatch",
    "not-found",
    "unchecked",
)

# Commands that cite, from LaTeX, natbib, biblatex, and apacite, named
# explicitly so that, e.g., \citestyle isn't read as one. Each takes its
# keys in its last brace group, except biblatex's multicite forms, which
# take one group per citation.
_CITE_COMMANDS = (
    "cite Cite citet Citet citep Citep citealt Citealt citealp Citealp "
    "citeauthor Citeauthor citeyear citeyearpar citenum citetitle "
    "Citetitle citedate citeurl parencite Parencite footcite Footcite "
    "footcitetext textcite Textcite smartcite Smartcite autocite Autocite "
    "supercite fullcite footfullcite nocite citeA citeNP shortcite "
    "citeasnoun"
).split()
_MULTICITE_COMMANDS = (
    "cites Cites parencites Parencites footcites footcitetexts textcites "
    "Textcites smartcites Smartcites autocites Autocites supercites"
).split()
_CITE_COMMAND_RE = re.compile(
    r"\\(" + "|".join(_CITE_COMMANDS + _MULTICITE_COMMANDS) + r")"
    r"(?![A-Za-z@])\*?"
)
# One citation's arguments: multicite's (pre)(post) notes, then [pre][post]
# notes, then the keys, each allowed to start on the next line.
_CITE_ARGS_RE = re.compile(
    r"(?:\s*\([^)]*\))*(?:\s*\[[^\]]*\])*\s*\{([^}]*)\}"
)
# Keys an inline bibliography defines with \bibitem, rather than a .bib.
_BIBITEM_RE = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
# Commands naming the .bib files a LaTeX document's bibliography reads.
_BIB_RE = re.compile(
    r"\\(?:bibliography|addbibresource|addglobalbib|addsectionbib)"
    r"\s*(?:\[[^\]]*\])*\s*\{([^}]*)\}"
)

# Pandoc citations, e.g., [@key; @other], a bare @key, or @{key}, for
# Markdown documents. The lookbehind keeps an email address from reading
# as one, and a key may contain internal punctuation but not end with it,
# so a citation at the end of a sentence doesn't swallow the period.
MARKDOWN_CITE_RE = re.compile(
    r"(?<![\w.@])@(?:\{([^}\s]+)\}|([\w][\w:.#$%&+?<>~/-]*[\w]|\w))"
)
# Quarto's and pandoc-crossref's cross-references, e.g., @fig-results or
# @tbl:summary, which are written like citations but aren't.
CROSSREF_RE = re.compile(
    r"^(?:fig|tbl|eq|sec|lst|thm|lem|cor|prp|cnj|def|exm|exr|nte|tip|wrn|"
    r"imp|cau)[-:]"
)
# Markdown that doesn't render as text, so a citation in it isn't one.
_MD_SKIP_RE = re.compile(
    r"<!--.*?-->|(`+)[^\n]*?(?<!`)\1(?!`)|<https?://[^>\s]*>|https?://\S+",
    re.S,
)
_MD_FENCE_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})")


class Found(BaseModel):
    """A work a service returned for an entry, and how well it fits.

    Working state rather than output: what it says about the work is
    already in the entry, so only the part of it that is evidence about
    the entry, i.e., :class:`Evidence`, is reported.
    """

    source: str
    id: str | None = None
    doi: str | None = None
    title: str | None = None
    year: int | None = None
    first_author: str | None = None
    title_similarity: float | None = None
    title_matches: bool | None = None
    year_matches: bool | None = None
    author_matches: bool | None = None


class Evidence(BaseModel):
    """That an entry was found, and where to go and see it.

    This is what the report keeps instead of the record itself. Repeating
    the title, authors, and year back would only copy the collection the
    check just read them from, so what is kept is how the work was found,
    a link to it, and which fields were compared. Values appear only
    where they disagree, since there the record is the finding.
    """

    matched_by: Literal["doi", "arxiv", "title"] = Field(
        description="What the work was found by: its DOI, its arXiv "
        "identifier, or a search for its title."
    )
    source: str = Field(description="The service that had it.")
    url: str | None = Field(
        default=None, description="Where to see the record."
    )
    agrees_on: list[str] = Field(
        default_factory=list,
        description="Fields compared that agree with the entry.",
    )
    differs: dict[str, str | int | None] = Field(
        default_factory=dict,
        description="Fields compared that disagree, and what the record "
        "says instead.",
    )
    title_similarity: float | None = Field(
        default=None,
        description="How close the titles are, where the work was found "
        "by searching for one.",
    )


class Reference(BaseModel):
    """One cited key, where it is defined, and what was confirmed.

    The entry's own metadata is read from the collection and kept here
    while the check runs, but excluded from the report: it is already in
    the collection, and a report that copied it would go stale against
    the file it was copied from.
    """

    key: str = Field(
        exclude=True,
        description="The citation key, which a report carries as the key "
        "of the mapping this sits in rather than as a field.",
    )
    cited_at: list[str] = Field(default_factory=list)
    collection: str | None = Field(
        default=None,
        description="The collection whose entry was used, or None if the "
        "key is in none of them.",
    )
    also_in: list[str] = Field(
        default_factory=list,
        description="Other collections defining the same key, which is "
        "the only case where more than one matters.",
    )
    status: Status = "not-checkable"
    evidence: Evidence | None = None
    notes: list[str] = Field(default_factory=list)
    entry_type: str | None = Field(default=None, exclude=True)
    title: str | None = Field(default=None, exclude=True)
    first_author: str | None = Field(default=None, exclude=True)
    year: int | None = Field(default=None, exclude=True)
    venue: str | None = Field(default=None, exclude=True)
    doi: str | None = Field(default=None, exclude=True)
    arxiv: str | None = Field(default=None, exclude=True)
    url: str | None = Field(default=None, exclude=True)
    doi_registered: bool | None = Field(
        default=None,
        exclude=True,
        description="Whether the DOI exists in the global handle system, "
        "which is registrar-agnostic, or None if it was not asked.",
    )
    found: Found | None = Field(default=None, exclude=True)
    alternative: Found | None = Field(
        default=None,
        exclude=True,
        description="A work that agrees with the entry where the one its "
        "identifier names doesn't, i.e., what the identifier should be.",
    )
    nearest: Found | None = Field(
        default=None,
        exclude=True,
        description="The closest title a search found where none matched.",
    )
    unanswered: Literal["offline", "unreachable"] | None = Field(
        default=None,
        exclude=True,
        description="Why a lookup it needed got no answer, if one didn't.",
    )


class DocumentCheck(BaseModel):
    """Every reference one document cites."""

    path: str
    sources: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    offline: bool = False
    n_cited: int = 0
    n_by_status: dict[str, int] = Field(default_factory=dict)
    references: dict[str, Reference] = Field(
        default_factory=dict,
        description="Each cited key and what was found for it, in the "
        "order the document cites them.",
    )

    @property
    def suspect(self) -> list[Reference]:
        return [r for r in self.references.values() if r.status in SUSPECT]

    @property
    def blocking(self) -> list[Reference]:
        return [r for r in self.references.values() if r.status in BLOCKING]

    @property
    def ok(self) -> bool:
        return not self.blocking


def output_path(document_path: str) -> str:
    """Report path for a document.

    Parameters
    ----------
    document_path : str
        Project-relative path of the document whose citations were
        checked, e.g., ``paper/main.tex``.

    Returns
    -------
    str
        Path of its report, so each document's check is an output of its
        own and goes stale on its own.
    """
    return f"{OUT_DIR}/{document_path}.json"


def clean_tex(value: str) -> str:
    """Readable text from a BibTeX field value.

    Parameters
    ----------
    value : str
        Field value, possibly carrying braces and accent commands.

    Returns
    -------
    str
        The value with TeX markup removed.
    """
    # An accent command keeps its letter, e.g., M{\"u}ller reads as Muller,
    # which is what a record's Müller folds to.
    out = re.sub(r"\\[`'^\"~=.]", "", value)
    out = re.sub(r"\\[a-zA-Z]+\s*", "", out)
    out = out.replace("{", "").replace("}", "").replace("\\", "")
    out = out.replace("--", "-").replace("~", " ")
    return " ".join(out.split())


def normalize_title(value: str | None) -> str:
    """A title reduced to what two records have to agree on.

    Parameters
    ----------
    value : str or None
        Title as stored or as a service returned it.

    Returns
    -------
    str
        Lowercased alphanumerics with accents folded.
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", clean_tex(value))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def first_author_surname(value: str | None) -> str | None:
    """Surname of the first name in a BibTeX author list.

    Parameters
    ----------
    value : str or None
        Contents of an ``author`` or ``editor`` field.

    Returns
    -------
    str or None
        The surname, or None if there is no such field.
    """
    if not value:
        return None
    first = re.split(r"\s+and\s+", clean_tex(value))[0].strip()
    if "," in first:
        return first.split(",")[0].strip() or None
    parts = first.split()
    return parts[-1] if parts else None


def similarity(left: str, right: str) -> float:
    """Ratio between two normalized titles, from 0 to 1."""
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def normalize_doi(value: str | None) -> str | None:
    """A DOI as the services take it, from however an entry writes it.

    Parameters
    ----------
    value : str or None
        A ``doi`` field, e.g., ``https://doi.org/10.1000/a\\_b``.

    Returns
    -------
    str or None
        The bare DOI, e.g., ``10.1000/a_b``, or None if there isn't one.
    """
    if not value:
        return None
    doi = re.sub(r"\\([_&%#$])", r"\1", value).replace("{", "")
    doi = doi.replace("}", "").strip()
    doi = re.sub(
        r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I
    )
    return doi.strip() or None


def _fold_name(value: str | None) -> str:
    """A surname reduced to its letters, accents folded."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _joined(lines: list[Any]) -> tuple[str, list[int]]:
    """A flattened document as one text, citations being free to span
    lines, with each line's offset into it."""
    from calkit.latex import _strip_comments, is_markdown

    texts: list[str] = []
    fence: str | None = None
    for i, line in enumerate(lines):
        text = line.text
        if not is_markdown(line.path):
            # A commented citation is not one
            text = _strip_comments(text)
        else:
            # Front matter and code blocks don't render as text, so are
            # blanked, keeping offsets
            first = i == 0 or lines[i - 1].path != line.path
            if first and text.strip() == "---":
                fence = "---"
                text = ""
            elif fence == "---":
                if text.strip() in ("---", "..."):
                    fence = None
                text = ""
            else:
                m = _MD_FENCE_RE.match(text)
                if fence is None and m:
                    fence = m.group(1)
                    text = ""
                elif fence is not None:
                    if m and m.group(1)[0] == fence[0]:
                        if len(m.group(1)) >= len(fence):
                            fence = None
                    text = ""
        texts.append(text)
    starts = []
    offset = 0
    for text in texts:
        starts.append(offset)
        offset += len(text) + 1
    return "\n".join(texts), starts


def cited_keys(lines: list[Any]) -> dict[str, list[str]]:
    """Citation keys in a flattened document, and where each appears.

    Parameters
    ----------
    lines : list of calkit.latex.SourceLine
        The document's lines with their file and number, as
        ``calkit.latex.flatten`` returns them.

    Returns
    -------
    dict
        Key to the ``path:lineno`` locations citing it, in source order.
        ``\\nocite{*}`` appears as the key ``*``.
    """
    import bisect

    from calkit.latex import is_markdown

    if not lines:
        return {}
    text, starts = _joined(lines)
    # flatten inputs nothing into Markdown, so a document is one or other
    markdown = is_markdown(lines[0].path)
    if markdown:
        # Blank what doesn't render as text, keeping offsets
        text = _MD_SKIP_RE.sub(
            lambda m: re.sub(r"[^\n]", " ", m.group()), text
        )

    def where(offset: int) -> str:
        line = lines[bisect.bisect_right(starts, offset) - 1]
        return f"{line.path}:{line.lineno}"

    found: list[tuple[int, str]] = []
    for match in _CITE_COMMAND_RE.finditer(text):
        multi = match.group(1) in _MULTICITE_COMMANDS
        pos = match.end()
        while True:
            args = _CITE_ARGS_RE.match(text, pos)
            if args is None:
                break
            start = args.start(1)
            for part in args.group(1).split(","):
                key = part.strip()
                # A macro's parameter, e.g., #1, or a key built from
                # macros, can't be looked up
                if key and "#" not in key and "\\" not in key:
                    found.append((start + part.index(key[0]), key))
                start += len(part) + 1
            pos = args.end()
            if not multi:
                break
    if markdown:
        for match in MARKDOWN_CITE_RE.finditer(text):
            found.append((match.start(), match.group(1) or match.group(2)))
    out: dict[str, list[str]] = {}
    for offset, key in sorted(found):
        locations = out.setdefault(key, [])
        if where(offset) not in locations:
            locations.append(where(offset))
    return out


def defined_keys(lines: list[Any]) -> dict[str, str]:
    """Keys an inline ``thebibliography`` defines, and where.

    Parameters
    ----------
    lines : list of calkit.latex.SourceLine
        The document's lines, as ``calkit.latex.flatten`` returns them.

    Returns
    -------
    dict
        Key to the path of the file whose ``\\bibitem`` defines it.
    """
    from calkit.latex import _strip_comments, is_markdown

    out: dict[str, str] = {}
    for line in lines:
        if is_markdown(line.path):
            continue
        for match in _BIBITEM_RE.finditer(_strip_comments(line.text)):
            out.setdefault(match.group(1).strip(), line.path)
    return out


def document_collections(
    document: str, lines: list[Any], wdir: str | Path | None = None
) -> list[str]:
    """The bibliographies a document names, in the order it names them.

    A LaTeX document names them with ``\\bibliography`` or biblatex's
    ``\\addbibresource``, and a Markdown one in its front matter's
    ``bibliography``. Each is resolved like ``calkit.latex.detect_inputs``
    resolves inputs: against the document's folder, then the folder of the
    file naming it.

    Parameters
    ----------
    document : str
        Project-relative path of the document.
    lines : list of calkit.latex.SourceLine
        Its lines, as ``calkit.latex.flatten`` returns them.
    wdir : str or Path, optional
        Project working directory, defaulting to the current one.

    Returns
    -------
    list of str
        Project-relative paths, which may not exist, or an empty list if
        the document names none, e.g., because pandoc is given them on its
        command line instead.
    """
    import posixpath

    from calkit.latex import _strip_comments, is_markdown

    base = Path(wdir or ".")
    named: list[tuple[str, str]] = []
    if is_markdown(document):
        import ruamel.yaml

        head = [ln.text for ln in lines if ln.path == document]
        if head and head[0].strip() == "---":
            end = next(
                (
                    i
                    for i, t in enumerate(head[1:], 1)
                    if t.strip() in ("---", "...")
                ),
                None,
            )
            try:
                meta = ruamel.yaml.YAML(typ="safe").load(
                    "\n".join(head[1:end])
                )
            except Exception:
                meta = None
            value = (
                meta.get("bibliography") if isinstance(meta, dict) else None
            )
            values = value if isinstance(value, list) else [value]
            named += [(str(v), document) for v in values if v]
        parents = [posixpath.dirname(document), ""]
    else:
        for line in lines:
            for match in _BIB_RE.finditer(_strip_comments(line.text)):
                for name in match.group(1).split(","):
                    named.append((name.strip(), line.path))
        parents = [posixpath.dirname(document)]
    out: list[str] = []
    for name, named_in in named:
        if not name or "#" in name or "\\" in name:
            continue
        names = [name]
        if not is_markdown(document) and not name.endswith(".bib"):
            names = [name + ".bib", name]
        folders = list(dict.fromkeys(parents + [posixpath.dirname(named_in)]))
        candidates = [
            posixpath.normpath(posixpath.join(folder, n))
            for n in names
            for folder in folders
        ]
        path = next(
            (c for c in candidates if (base / c).is_file()), candidates[0]
        )
        if path not in out:
            out.append(path)
    return out


def declared_collections(ck_info: dict) -> list[str]:
    """Paths of the collections ``calkit.yaml`` declares, in order."""
    out = []
    for item in ck_info.get("references") or []:
        path = item.get("path") if isinstance(item, dict) else item
        if isinstance(path, str) and path and path not in out:
            out.append(path)
    return out


def load_collections(
    wdir: str | Path | None = None, paths: list[str] | None = None
) -> dict[str, dict[str, dict]]:
    """Reference collections, parsed.

    Parameters
    ----------
    wdir : str or Path, optional
        Project working directory, defaulting to the current one.
    paths : list of str, optional
        Project-relative paths of the collections to read, defaulting to
        every one the project declares. One that doesn't exist is skipped.

    Returns
    -------
    dict
        Collection path to its entries, by citation key.
    """
    import calkit
    from calkit.releases import parse_bibtex

    if paths is None:
        ck_info = calkit.load_calkit_info(wdir=wdir, read_only=True)
        paths = declared_collections(ck_info)
    out: dict[str, dict[str, dict]] = {}
    for path in paths:
        full = Path(wdir or ".") / path
        if not full.exists():
            continue
        text = full.read_text(encoding="utf-8", errors="replace")
        entries = {}
        for entry in parse_bibtex(text):
            key = entry.get("ID")
            if key:
                entries[key] = entry
        out[path] = entries
    return out


def _fill_from_entry(reference: Reference, entry: dict) -> None:
    """Copy the fields the check needs out of a BibTeX entry."""
    reference.entry_type = entry.get("ENTRYTYPE")
    reference.title = clean_tex(entry.get("title", "")) or None
    reference.first_author = first_author_surname(
        entry.get("author") or entry.get("editor")
    )
    year = re.search(r"\d{4}", entry.get("year", "") or "")
    reference.year = int(year.group()) if year else None
    reference.venue = (
        clean_tex(
            entry.get("journal")
            or entry.get("booktitle")
            or entry.get("series")
            or entry.get("publisher")
            or ""
        )
        or None
    )
    reference.doi = normalize_doi(entry.get("doi"))
    if (entry.get("archiveprefix") or "").lower() == "arxiv":
        reference.arxiv = (entry.get("eprint") or "").strip() or None
    # howpublished is where a software or web citation puts its link,
    # usually wrapped in \url{}.
    link = entry.get("url") or entry.get("howpublished") or ""
    url = re.search(r"https?://\S+", clean_tex(link))
    reference.url = url.group().rstrip(".,;") if url else None


def compare(reference: Reference, found: Found) -> Found:
    """Score a candidate against an entry, filling its match fields.

    Parameters
    ----------
    reference : Reference
        The entry as its collection has it.
    found : Found
        A candidate record from a service.

    Returns
    -------
    Found
        The candidate with its comparison fields set. A field neither
        record can settle is left None rather than False.
    """
    ours = normalize_title(reference.title)
    theirs = normalize_title(found.title)
    found.title_similarity = round(similarity(ours, theirs), 4)
    if len(ours) < MIN_TITLE_CHARS or len(theirs) < MIN_TITLE_CHARS:
        found.title_matches = None
    else:
        found.title_matches = found.title_similarity >= TITLE_MATCH
    # An entry citing the published version, matched to its preprint, has
    # a different year for a reason that says nothing about the work.
    ours_preprint = (reference.doi or "").lower().startswith("10.48550/")
    theirs_preprint = (found.doi or "").lower().startswith("10.48550/")
    if reference.year is None or found.year is None:
        found.year_matches = None
    elif theirs_preprint and not ours_preprint:
        found.year_matches = None
    else:
        # Off by one is the usual online-ahead-of-print gap.
        found.year_matches = abs(reference.year - found.year) <= 1
    ours_author = _fold_name(reference.first_author)
    theirs_author = _fold_name(found.first_author)
    # A record can give a whole name, in either order
    theirs_names = {
        _fold_name(part) for part in (found.first_author or "").split()
    }
    if not ours_author or not theirs_author:
        found.author_matches = None
    else:
        found.author_matches = (
            ours_author in theirs_names
            or similarity(ours_author, theirs_author) >= 0.85
            or ours_author in theirs_author
            or theirs_author in ours_author
        )
    return found


def _evidence(reference: Reference, found: Found) -> Evidence:
    """What a candidate record is evidence of, without copying it.

    Parameters
    ----------
    reference : Reference
        The entry the record was found for.
    found : Found
        The record, already compared against the entry.

    Returns
    -------
    Evidence
        How the work was found, where to see it, and which of the three
        compared fields agree. A field the record disagrees on carries
        what the record says, since that is the finding; one neither
        record can settle is left out of both lists.
    """
    matched_by: Literal["doi", "arxiv", "title"] = (
        "doi"
        if found.source.endswith("-doi")
        else "arxiv"
        if found.source == "arxiv"
        else "title"
    )
    url: str | None
    if found.source == "arxiv" and found.id:
        url = f"https://arxiv.org/abs/{found.id.removeprefix('arXiv:')}"
    elif found.source == "openalex":
        url = found.id
    elif found.doi:
        url = f"https://doi.org/{found.doi}"
    else:
        url = None
    agrees: list[str] = []
    differs: dict[str, str | int | None] = {}
    for name, ok, value in (
        ("title", found.title_matches, found.title),
        ("first-author", found.author_matches, found.first_author),
        ("year", found.year_matches, found.year),
    ):
        if ok is True:
            agrees.append(name)
        elif ok is False:
            differs[name] = value
    return Evidence(
        matched_by=matched_by,
        source=found.source.removesuffix("-doi"),
        url=url,
        agrees_on=agrees,
        differs=differs,
        title_similarity=(
            found.title_similarity if matched_by == "title" else None
        ),
    )


def classify(reference: Reference) -> None:
    """Set a reference's status and notes from what was found."""

    def note_alternative() -> None:
        alt = reference.alternative
        if alt is not None:
            where = _evidence(reference, alt).url or alt.source
            reference.notes.append(
                f"a work matching the entry's title, authors, and year is at "
                f"{where}, so the identifier is likely wrong"
            )

    if reference.collection is None:
        reference.status = "missing-from-bib"
        reference.notes.append(
            "cited but defined in no declared reference collection, so the "
            "citation cannot resolve"
        )
        return
    if reference.also_in:
        reference.notes.append(
            f"also defined in {', '.join(reference.also_in)}, so which "
            "entry is used depends on the order the bibliographies are "
            "named in"
        )
    if reference.doi_registered is False:
        reference.status = "doi-not-registered"
        reference.notes.append(
            f"the DOI ({reference.doi}) does not exist in the handle system "
            "that registers every DOI, so it cannot be a real identifier"
        )
        note_alternative()
        return
    if reference.entry_type == "bibitem":
        reference.status = "not-checkable"
        reference.notes.append(
            "defined by a \\bibitem in the document, which has no fields to "
            "look up; check it by hand"
        )
        return
    found = reference.found
    if found is not None:
        reference.evidence = _evidence(reference, found)
        disagrees = [
            name
            for name, ok in (
                ("title", found.title_matches),
                ("first author", found.author_matches),
                ("year", found.year_matches),
            )
            if ok is False
        ]
        if not disagrees:
            reference.status = "verified"
            return
        reference.status = "mismatch"
        reference.notes.append(
            f"found a work, but its {', '.join(disagrees)} "
            f"{'disagrees' if len(disagrees) == 1 else 'disagree'} with the "
            "entry; see what the record says under evidence"
        )
        if (
            reference.doi
            and found.doi
            and reference.doi.lower() == found.doi.lower()
        ):
            reference.notes.append(
                "the DOI resolves, but to a different work than this entry "
                "describes"
            )
        note_alternative()
        return
    # Nothing was found, which means different things depending on what
    # there was to look for.
    if not reference.title and not reference.doi:
        reference.status = "not-checkable"
        reference.notes.append("no title or identifier to look up")
    elif reference.url and not reference.doi and not reference.arxiv:
        reference.status = "not-checkable"
        reference.notes.append(
            "cites a URL rather than a registered work, so there is nothing "
            "to look up; check the link by hand"
        )
    elif reference.unanswered is not None:
        # Not finding a work only means something if every service asked
        # gave an answer
        reference.status = "unchecked"
        reference.notes.append(
            "not looked up, since the check ran offline and nothing is "
            "cached for it"
            if reference.unanswered == "offline"
            else "a service could not be reached, so it could not be "
            "looked up; run the check again to retry"
        )
    elif reference.doi:
        reference.status = "not-found"
        reference.notes.append(
            "the DOI is registered but no record of this work was found in "
            "the services checked, so its metadata could not be confirmed"
            if reference.doi_registered
            else "the DOI could not be resolved and no work with this title "
            "was found, which is what a fabricated entry looks like"
        )
    else:
        reference.status = "not-found"
        near = reference.nearest
        if near is not None and near.title_matches:
            where = _evidence(reference, near).url or near.source
            differs = [
                f"{name} {value!r}"
                for name, value, ok in (
                    ("first author", near.first_author, near.author_matches),
                    ("year", near.year, near.year_matches),
                )
                if ok is False
            ]
            reference.notes += [
                "no work matching the entry's title, first author, and year "
                "was found in the services checked",
                f"one with this title is at {where}, but with "
                f"{' and '.join(differs)}, so it may be another edition, a "
                "reprint, or a review of it, or the entry's details are wrong",
            ]
        else:
            reference.notes.append(
                "no work with this title was found in the services checked"
            )
        if near is not None and not near.title_matches:
            where = _evidence(reference, near).url or near.source
            reference.notes.append(
                f"the closest title found is {near.title!r}, at {where}"
            )
        venue = (reference.venue or "").lower()
        if any(thin in venue for thin in THIN_VENUES):
            reference.notes.append(
                f"the venue ({reference.venue}) is indexed thinly or not at "
                "all by these services, so this is as likely a coverage gap "
                "as a bad entry and needs checking by hand"
            )


def source_document(path: str, wdir: str | Path | None = None) -> str:
    """The document a path's citations are read from.

    A PDF's are read from the source it's built from: the document of the
    ``latex`` or ``markdown`` stage that outputs it, or else a ``.tex`` or
    Markdown file beside it with the same name. Any other path is its own.

    Parameters
    ----------
    path : str
        Project-relative path, e.g., ``paper/main.pdf``.
    wdir : str or Path, optional
        Project working directory, defaulting to the current one.

    Returns
    -------
    str
        Project-relative path of the source document.

    Raises
    ------
    FileNotFoundError
        If a PDF has no source.
    """
    import posixpath

    import calkit
    from calkit.models.pipeline import LatexStage

    if not path.lower().endswith(".pdf"):
        return path
    want = posixpath.normpath(path)
    ck_info = calkit.load_calkit_info(wdir=wdir, read_only=True)
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    for stage in stages.values():
        if not isinstance(stage, dict) or not stage.get("target_path"):
            continue
        target = str(stage["target_path"])
        pdf = stage.get("pdf")
        if stage.get("kind") == "latex":
            # Paths are relative to the stage's working directory
            try:
                built = LatexStage.model_validate(stage).pdf_path
            except ValueError:
                continue
            stage_wdir = stage.get("wdir") or ""
            built = posixpath.join(stage_wdir, built)
            target = posixpath.join(stage_wdir, target)
        elif stage.get("kind") == "markdown" and isinstance(pdf, dict):
            built = pdf.get("output_path") or (
                posixpath.splitext(target)[0] + ".pdf"
            )
        else:
            continue
        if posixpath.normpath(built) == want:
            return posixpath.normpath(target)
    stem = posixpath.splitext(path)[0]
    for ext in (".tex", ".md", ".markdown"):
        if (Path(wdir or ".") / (stem + ext)).is_file():
            return stem + ext
    raise FileNotFoundError(
        f"No stage builds {path}, and there's no .tex or Markdown file "
        "beside it to read citations from"
    )


def check_references(
    path: str,
    wdir: str | Path | None = None,
    offline: bool = False,
    refresh: bool = False,
) -> DocumentCheck:
    """Check that every reference a document cites is real.

    Parameters
    ----------
    path : str
        Project-relative path of what to check: a document, whose
        citations are checked, a PDF, whose source's are, or a ``.bib``
        file, whose every entry is.
    wdir : str or Path, optional
        Project working directory, defaulting to the current one.
    offline : bool, optional
        Use only cached answers, and report the rest as unchecked.
    refresh : bool, optional
        Ignore the cache and ask the services again.

    Returns
    -------
    DocumentCheck
        The document's report.

    Raises
    ------
    FileNotFoundError
        If the path, or a PDF's source, doesn't exist.
    """
    import calkit
    from calkit.latex import flatten, is_markdown

    # flatten names paths relative to the project, so read them there
    # rather than changing the working directory.
    def read(name: str) -> str | None:
        full = Path(wdir or ".") / name
        return (
            full.read_text(encoding="utf-8", errors="replace")
            if full.is_file()
            else None
        )

    document = source_document(path, wdir=wdir)
    if not (Path(wdir or ".") / document).is_file():
        raise FileNotFoundError(f"No such file: {document}")
    lookup = Lookup(wdir=wdir, offline=offline, refresh=refresh)
    # A bibliography is checked whole, as if each entry were cited
    if document.lower().endswith(".bib"):
        names = [document]
        sources = [document]
        collections = load_collections(wdir=wdir, paths=names)
        cited: dict[str, list[str]] = {
            key: [] for key in collections.get(document, {})
        }
        inline: dict[str, str] = {}
    else:
        lines = flatten(document, read=read)
        # The bibliographies the document names are the ones its citations
        # resolve against, and the declared ones only stand in for them
        ck_info = calkit.load_calkit_info(wdir=wdir, read_only=True)
        names = document_collections(
            document, lines, wdir=wdir
        ) or declared_collections(ck_info)
        sources = list(dict.fromkeys(line.path for line in lines))
        collections = load_collections(wdir=wdir, paths=names)
        inline = defined_keys(lines)
        cited = cited_keys(lines)
        # \nocite{*} puts every entry in the bibliography, so each is cited
        everything = cited.pop("*", None)
        if everything is not None:
            for entries in collections.values():
                for key in entries:
                    cited.setdefault(key, list(everything))
    check = DocumentCheck(
        path=document, sources=sources, collections=names, offline=offline
    )
    for key, locations in cited.items():
        defining = [n for n, entries in collections.items() if key in entries]
        # Quarto and pandoc-crossref write a cross-reference like a
        # citation, e.g., @fig-results
        if (
            not defining
            and CROSSREF_RE.match(key)
            and all(is_markdown(loc.rsplit(":", 1)[0]) for loc in locations)
        ):
            continue
        reference = Reference(key=key, cited_at=locations)
        if defining:
            # The first wins, as BibTeX takes them in the order named
            reference.collection = defining[0]
            reference.also_in = defining[1:]
            _fill_from_entry(reference, collections[defining[0]][key])
            verify(reference, lookup)
        elif key in inline:
            reference.collection = inline[key]
            reference.entry_type = "bibitem"
        classify(reference)
        check.references[key] = reference
    check.n_cited = len(check.references)
    counts: dict[str, int] = {}
    for reference in check.references.values():
        counts[reference.status] = counts.get(reference.status, 0) + 1
    check.n_by_status = dict(sorted(counts.items()))
    lookup.save()
    return check


def verify(reference: Reference, lookup: Lookup) -> None:
    """Look an entry up, trying its identifier before its title.

    Parameters
    ----------
    reference : Reference
        The entry to look for, updated in place with the best candidate.
    lookup : Lookup
        The cached service reader to ask.

    Notes
    -----
    An identifier is authoritative: the work it resolves to is the one a
    reader following it gets, so it is what the entry is compared with,
    even where a search for the title finds a work that agrees better.
    That search is still made, so a report can say where the right work
    is.
    """
    unanswered = lookup.unanswered
    by_id: Found | None = None
    if reference.doi:
        # Crossref and DataCite, e.g., Zenodo, register most DOIs, and
        # the handle system behind doi.org knows every one
        by_id = lookup.crossref_doi(reference.doi) or lookup.datacite_doi(
            reference.doi
        )
        if by_id is None:
            reference.doi_registered = lookup.doi_registered(reference.doi)
    if by_id is None and reference.arxiv:
        by_id = lookup.arxiv(reference.arxiv)
    if by_id is not None:
        compare(reference, by_id)
    by_title: list[Found] = []
    if reference.title and (by_id is None or not _agrees(by_id)):
        for hit in (
            lookup.crossref_title(reference.title),
            lookup.openalex_title(reference.title),
        ):
            # A search always returns its nearest neighbor, so only a hit
            # with the same title is the work; one that merely resembles it
            # is a failed search, worth pointing at but not accusing with
            if hit is not None:
                compare(reference, hit)
                if hit.title_matches:
                    by_title.append(hit)
                elif (hit.title_similarity or 0.0) >= TITLE_PLAUSIBLE and (
                    reference.nearest is None
                    or (hit.title_similarity or 0.0)
                    > (reference.nearest.title_similarity or 0.0)
                ):
                    reference.nearest = hit
    # A work with the same title but another author or year may be
    # another edition, a reprint, or a review of it, so it's pointed at
    # rather than taken for the entry
    agreeing = [hit for hit in by_title if _agrees(hit)]
    best_by_title = max(agreeing, key=_rank) if agreeing else None
    if by_title and not agreeing:
        reference.nearest = max(by_title, key=_rank)
    if by_id is not None:
        reference.found = by_id
    elif reference.doi_registered is not False:
        # An unregistered DOI is the finding, whatever the title finds
        reference.found = best_by_title
    # Where the identifier names the wrong work, or none, say where the
    # right one is
    if best_by_title is not None and best_by_title is not reference.found:
        reference.alternative = best_by_title
    if reference.found is not None:
        reference.nearest = None
    if reference.found is None and lookup.unanswered > unanswered:
        reference.unanswered = "offline" if lookup.offline else "unreachable"


def _agrees(found: Found) -> bool:
    """Whether no compared field disagrees."""
    return _rank(found)[0] == 1


def _rank(found: Found) -> tuple[int, float]:
    """Sort key putting a fully agreeing candidate first."""
    agrees = all(
        ok is not False
        for ok in (
            found.title_matches,
            found.author_matches,
            found.year_matches,
        )
    )
    return (1 if agrees else 0, found.title_similarity or 0.0)


def _from_crossref(item: dict, source: str = "crossref") -> Found:
    """A ``Found`` from a Crossref work record."""
    titles = item.get("title") or []
    authors = item.get("author") or []
    issued = (item.get("issued") or {}).get("date-parts") or [[None]]
    year = issued[0][0] if issued and issued[0] else None
    surname = None
    if authors:
        surname = authors[0].get("family") or authors[0].get("name")
    # Titles can carry JATS markup, e.g., <i>L</i>, over several lines
    title = (
        " ".join(re.sub(r"<[^>]+>", " ", titles[0]).split()) if titles else ""
    )
    return Found(
        source=source,
        id=item.get("DOI"),
        doi=item.get("DOI"),
        title=title or None,
        year=int(year) if isinstance(year, int) else None,
        first_author=surname,
    )


def _from_openalex(item: dict) -> Found:
    """A ``Found`` from an OpenAlex work record."""
    authorships = item.get("authorships") or []
    # The whole name, since which part is the surname isn't marked, and
    # some records put it first
    name = None
    if authorships:
        name = (authorships[0].get("author") or {}).get("display_name")
    doi = item.get("doi") or ""
    return Found(
        source="openalex",
        id=item.get("id"),
        doi=doi.replace("https://doi.org/", "") or None,
        title=item.get("display_name"),
        year=item.get("publication_year"),
        first_author=name or None,
    )


class Lookup:
    """Cached, rate-limited reads of the citation services.

    An answer, including a service saying it has no such record, is cached
    so a rerun needs no network. A request that gets no answer, e.g.,
    without a network, or one the service turns away, is not, so the next
    run asks again, and is counted in ``unanswered``.
    """

    def __init__(
        self,
        wdir: str | Path | None = None,
        offline: bool = False,
        refresh: bool = False,
    ) -> None:
        import json

        self.path = Path(wdir or ".") / CACHE_PATH
        self.offline = offline
        # Refreshing asks again for what this run needs, keeping the rest
        self.refresh = refresh
        self.asked: set[str] = set()
        self.cache: dict[str, Any] = {}
        self.calls = 0
        self.unanswered = 0
        if self.path.exists():
            try:
                self.cache = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                self.cache = {}

    def save(self) -> None:
        """Write the cache, so the next run needs no network."""
        import json

        if not self.asked:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cache, indent=2, sort_keys=True))

    def get_text(self, url: str) -> str | None:
        """Fetch a URL as text, remembering the answer."""
        import time
        import urllib.error
        import urllib.request

        # A cached entry written by another version may not be text, in
        # which case treat it as a miss and overwrite it.
        cached = self.cache.get(url)
        fresh = not self.refresh or url in self.asked
        if fresh and (
            isinstance(cached, str) or (url in self.cache and cached is None)
        ):
            return cached
        if self.offline:
            self.unanswered += 1
            return None
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT}
        )
        text = None
        answered = False
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8", errors="replace")
            answered = True
        except urllib.error.HTTPError as e:
            # An error status can still carry the answer: doi.org replies
            # 404 with the JSON saying the handle doesn't exist. Being
            # rate limited or a server error is no answer at all.
            answered = e.code < 500 and e.code != 429
            try:
                text = e.read().decode("utf-8", errors="replace")
            except OSError:
                text = None
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        self.calls += 1
        time.sleep(REQUEST_DELAY_S)
        if not answered:
            self.unanswered += 1
            return None
        self.asked.add(url)
        self.cache[url] = text
        return text

    def get_json(self, url: str) -> Any:
        """Fetch a URL and decode it as JSON."""
        import json

        text = self.get_text(url)
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def crossref_doi(self, doi: str) -> Found | None:
        """The work Crossref has for a DOI, if any."""
        import urllib.parse

        quoted = urllib.parse.quote(doi, safe="")
        payload = self.get_json(f"https://api.crossref.org/works/{quoted}")
        if not payload or "message" not in payload:
            return None
        return _from_crossref(payload["message"], source="crossref-doi")

    def datacite_doi(self, doi: str) -> Found | None:
        """The work DataCite has for a DOI, if any, e.g., a Zenodo one."""
        import urllib.parse

        quoted = urllib.parse.quote(doi, safe="/")
        payload = self.get_json(f"https://api.datacite.org/dois/{quoted}")
        attrs = ((payload or {}).get("data") or {}).get("attributes")
        if not isinstance(attrs, dict):
            return None
        titles = attrs.get("titles") or [{}]
        creators = attrs.get("creators") or [{}]
        year = attrs.get("publicationYear")
        kind = (attrs.get("types") or {}).get("resourceTypeGeneral")
        return Found(
            source="datacite-doi",
            id=attrs.get("doi"),
            doi=attrs.get("doi"),
            title=titles[0].get("title"),
            # A concept DOI for software or data is dated by its latest
            # version, so its year says nothing about the one cited
            year=(
                int(str(year))
                if str(year).isdigit() and kind not in ("Software", "Dataset")
                else None
            ),
            first_author=creators[0].get("familyName")
            or creators[0].get("name"),
        )

    def doi_registered(self, doi: str) -> bool | None:
        """Whether the handle system knows a DOI.

        Asked of doi.org rather than of a single registrar, so a DataCite
        or mEDRA DOI that Crossref has never heard of still resolves. An
        unknown handle is the one unambiguous sign of an invented
        identifier.

        Parameters
        ----------
        doi : str
            The DOI to resolve, without a URL prefix.

        Returns
        -------
        bool or None
            True if registered, False if the handle does not exist, and
            None if doi.org could not be reached.
        """
        import urllib.parse

        quoted = urllib.parse.quote(doi.strip(), safe="/")
        payload = self.get_json(f"https://doi.org/api/handles/{quoted}")
        if not payload or "responseCode" not in payload:
            return None
        # 1 is success and 100 is "handle not found"; anything else is the
        # service having trouble rather than an answer about the DOI.
        code = payload.get("responseCode")
        if code == 1:
            return True
        return False if code == 100 else None

    def crossref_title(self, title: str) -> Found | None:
        """Crossref's closest bibliographic match for a title."""
        import urllib.parse

        query = urllib.parse.urlencode(
            {
                "query.bibliographic": title,
                "rows": "3",
                "select": "DOI,title,author,issued",
            }
        )
        payload = self.get_json(f"https://api.crossref.org/works?{query}")
        items = (payload or {}).get("message", {}).get("items") or []
        return self._closest(title, [_from_crossref(item) for item in items])

    def openalex_title(self, title: str) -> Found | None:
        """OpenAlex's closest title match."""
        import urllib.parse

        query = urllib.parse.urlencode(
            {"filter": f"title.search:{title}", "per-page": "3"}
        )
        payload = self.get_json(f"https://api.openalex.org/works?{query}")
        results = (payload or {}).get("results") or []
        return self._closest(title, [_from_openalex(item) for item in results])

    def arxiv(self, eprint: str) -> Found | None:
        """The arXiv record for an eprint identifier.

        arXiv answers in Atom, so this reads the fields that matter out of
        the feed rather than parsing it as XML.
        """
        import urllib.parse

        url = (
            "http://export.arxiv.org/api/query?id_list="
            f"{urllib.parse.quote(eprint)}"
        )
        text = self.get_text(url) or ""
        if "<entry>" not in text:
            return None
        title = re.search(r"<entry>.*?<title>(.*?)</title>", text, re.S)
        author = re.search(r"<entry>.*?<name>(.*?)</name>", text, re.S)
        published = re.search(r"<entry>.*?<published>(\d{4})", text, re.S)
        surname = None
        if author:
            parts = " ".join(author.group(1).split()).split()
            surname = parts[-1] if parts else None
        return Found(
            source="arxiv",
            id=f"arXiv:{eprint}",
            doi=f"10.48550/arXiv.{eprint}",
            title=" ".join(title.group(1).split()) if title else None,
            year=int(published.group(1)) if published else None,
            first_author=surname,
        )

    @staticmethod
    def _closest(title: str, candidates: list[Found]) -> Found | None:
        """The candidate whose title is nearest the one searched for."""
        best, score = None, 0.0
        for candidate in candidates:
            ratio = similarity(
                normalize_title(title), normalize_title(candidate.title)
            )
            if ratio > score:
                best, score = candidate, ratio
        return best


def compact(value: Any) -> Any:
    """Drop what a report says nothing with: nulls and empty containers.

    A reference that was found and agrees on everything should read as
    four lines, not as a form with blanks left in it.

    Parameters
    ----------
    value : Any
        Already dumped to JSON-compatible types.

    Returns
    -------
    Any
        The same, without keys whose value is None, an empty list, or an
        empty dict.
    """
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            item = compact(item)
            if item is None or (isinstance(item, (list, dict)) and not item):
                continue
            out[key] = item
        return out
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


def write_report(
    document: DocumentCheck, path: str, wdir: str | Path | None = None
) -> None:
    """Write one document's report.

    Parameters
    ----------
    document : DocumentCheck
        The document's check.
    path : str
        Where to write it, relative to ``wdir``.
    wdir : str or Path, optional
        Project working directory, defaulting to the current one.
    """
    import json

    full = Path(wdir or ".") / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(
        json.dumps(compact(document.model_dump(mode="json")), indent=2) + "\n"
    )


def format_check(document: DocumentCheck, verbose: bool = False) -> str:
    """Render a document's check as text, worst first.

    Parameters
    ----------
    document : DocumentCheck
        The check to render.
    verbose : bool, optional
        List every reference, not only the ones needing attention.

    Returns
    -------
    str
        The report.
    """
    from calkit.core import check_or_x

    references = list(document.references.values())
    if not references:
        return f"{document.path}: no references to check."
    counts = ", ".join(
        f"{n} {status}" for status, n in document.n_by_status.items()
    )
    lines = [f"{document.path}: {document.n_cited} references ({counts})"]
    shown = references if verbose else document.suspect
    order = {s: i for i, s in enumerate(SUSPECT)}
    for reference in sorted(
        shown, key=lambda r: order.get(r.status, len(order))
    ):
        lines.append(f"  {reference.status}: {reference.key}")
        if reference.cited_at:
            lines.append(f"    cited at {reference.cited_at[0]}")
        for note in reference.notes:
            lines.append(f"    {note}")
        evidence = reference.evidence
        if evidence is None:
            continue
        where = evidence.url or evidence.source
        if evidence.differs:
            says = ", ".join(
                f"{name} {value!r}" for name, value in evidence.differs.items()
            )
            lines.append(f"    the record at {where} says {says}")
        else:
            lines.append(
                f"    found by {evidence.matched_by} at {where}, "
                f"agreeing on {', '.join(evidence.agrees_on) or 'nothing'}"
            )
    lines.append("")

    def n(*statuses: str) -> int:
        return sum(1 for r in references if r.status in statuses)

    missing = n("missing-from-bib")
    bad_doi = n("doi-not-registered")
    mismatch = n("mismatch")
    lines += [
        f"References checked: {len(references)}",
        f"Defined in a bibliography: {len(references) - missing}/"
        f"{len(references)} {check_or_x(not missing)}",
        f"With a DOI that isn't registered: {bad_doi} {check_or_x(not bad_doi)}",
        f"Contradicting the record found for them: {mismatch} "
        f"{check_or_x(not mismatch)}",
        f"Verified against a record: {n('verified')}/{len(references)}",
    ]
    return "\n".join(lines)


def document_inputs(
    document: str,
    project_dir: str | Path | None = None,
    is_output: Callable[[str], bool] | None = None,
) -> list[str]:
    """Files a check of one document reads: it, its inputs, collections.

    Parameters
    ----------
    document : str
        Project-relative path of what's being checked, as
        ``check_references`` takes it.
    project_dir : str or Path, optional
        Project working directory, defaulting to the current one.
    is_output : callable, optional
        Whether a stage makes a project path, so a file the document inputs
        is depended on before it's first made, and the check runs after.

    Returns
    -------
    list of str
        Project-relative paths, starting with the document, which is
        depended on even when it does not exist yet, and then a PDF's
        source.
    """
    import posixpath

    import calkit
    from calkit.latex import detect_inputs, flatten, is_markdown

    base = Path(project_dir or ".")

    def read(path: str) -> str | None:
        full = base / path
        return (
            full.read_text(encoding="utf-8", errors="replace")
            if full.is_file()
            else None
        )

    def is_input(path: str) -> bool:
        return (
            (base / path).is_file()
            or (base / (path + ".dvc")).is_file()
            or (is_output is not None and is_output(path))
        )

    out = [document]
    # The run reports a PDF with no source, so here it's only depended on
    try:
        document = source_document(document, wdir=base)
    except FileNotFoundError:
        return out
    out.append(document)
    if document.lower().endswith(".bib"):
        return list(dict.fromkeys(out))
    if not is_markdown(document):
        # Only what can carry a citation, not, e.g., figures
        out += [
            p
            for p in detect_inputs(
                document, wdir=str(base), is_output=is_output
            )
            if posixpath.splitext(p)[1] in (".tex", ".bib")
        ]
    named = document_collections(document, flatten(document, read=read), base)
    if named:
        out += [p for p in named if is_input(p)]
    else:
        ck_info = calkit.load_calkit_info(wdir=base, read_only=True)
        out += ["calkit.yaml"] + declared_collections(ck_info)
    return list(dict.fromkeys(out))
