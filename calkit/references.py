"""Checking that the references a document cites are real.

A citation can be wrong in three ways a build does not catch. The key can
be missing from every collection, which BibTeX mentions and a reader of
the PDF sees only as a question mark. The entry can exist and describe a
work that does not, which is what a language model produces when it
invents a plausible citation. Or the entry can carry an identifier that
resolves to a different work than its title and authors name, which is
the same mistake wearing a real DOI.

Keys are read from the documents the pipeline builds, and from the files
they input, rather than from the compiled PDF, since that is where a key
is written and where it has to be fixed. Each is resolved against the
collections ``calkit.yaml`` declares, and each entry is then looked for in
Crossref, OpenAlex, and arXiv, by identifier when it has one and by title
when it does not. A candidate is compared on title, first author, and
year, so an entry whose DOI resolves to something else is reported rather
than trusted.

The check is deliberately quiet about what it cannot know. A title search
always returns its nearest neighbor, so a candidate that does not
resemble the title it was found with is a failed search rather than a
disagreement to report. A work in a venue these services do not index,
e.g., anything in PMLR, which registers no DOIs, looks exactly like a
work that does not exist; those are reported as not found, with the venue
named, and they do not fail the check. What fails it is decidable: a key
in no collection, read locally, and an identifier that resolves to
another work, which carries the record it disagrees with.

Reports are written per document, to ``.calkit/reference-checks``, so
each is a pipeline output with its own dependencies. They carry no
timestamp, so a report is a function of the sources that produced it and
can be checked for staleness like any other output. Answers from the
services are cached under ``.calkit/local``, which is not tracked, so a
rerun needs no network and ``--offline`` still reports everything that
does not.
"""

from __future__ import annotations

import re
import unicodedata
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
)

CITE_RE = re.compile(
    r"\\(?:no)?cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]*)\}",
)

# Pandoc citations, e.g., [@key; @other] or a bare @key, for Markdown
# documents. The lookbehind keeps an email address from reading as one,
# and a key may contain internal punctuation but not end with it, so a
# citation at the end of a sentence doesn't swallow the period.
MARKDOWN_CITE_RE = re.compile(r"(?<![\w.])@([A-Za-z][\w:.#$%&+?<>~/-]*[\w])")


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


class ReferenceCheck(BaseModel):
    """The whole project's citation check."""

    documents: list[DocumentCheck] = Field(default_factory=list)
    n_requests: int = 0

    @property
    def ok(self) -> bool:
        return all(d.ok for d in self.documents)


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
    out = re.sub(r"\\[a-zA-Z]+\s*", "", value)
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
    """
    from calkit.latex import _strip_comments, is_markdown

    out: dict[str, list[str]] = {}
    for line in lines:
        markdown = is_markdown(line.path)
        # A commented citation is not one, and in Markdown the comment
        # syntax is HTML, which flatten leaves alone.
        text = line.text if markdown else _strip_comments(line.text)
        keys = []
        for match in CITE_RE.finditer(text):
            keys += [k.strip() for k in match.group(1).split(",")]
        if markdown:
            keys += MARKDOWN_CITE_RE.findall(text)
        for key in keys:
            if key:
                out.setdefault(key, []).append(f"{line.path}:{line.lineno}")
    return out


def load_collections(
    wdir: str | Path | None = None,
) -> dict[str, dict[str, dict]]:
    """Every reference collection the project declares, parsed.

    Parameters
    ----------
    wdir : str or Path, optional
        Project working directory, defaulting to the current one.

    Returns
    -------
    dict
        Collection path to its entries, by citation key.
    """
    import calkit
    from calkit.releases import parse_bibtex

    ck_info = calkit.load_calkit_info(wdir=wdir, read_only=True)
    out: dict[str, dict[str, dict]] = {}
    for item in ck_info.get("references") or []:
        path = item.get("path") if isinstance(item, dict) else item
        if not path:
            continue
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
    reference.doi = (entry.get("doi") or "").strip() or None
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
    ours_author = (reference.first_author or "").lower()
    theirs_author = (found.first_author or "").lower()
    if not ours_author or not theirs_author:
        found.author_matches = None
    else:
        found.author_matches = (
            similarity(ours_author, theirs_author) >= 0.85
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
        if found.source == "crossref-doi"
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
        source="crossref" if found.source == "crossref-doi" else found.source,
        url=url,
        agrees_on=agrees,
        differs=differs,
        title_similarity=(
            found.title_similarity if matched_by == "title" else None
        ),
    )


def classify(reference: Reference) -> None:
    """Set a reference's status and notes from what was found."""
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
            "entry is used depends on the order the collections are "
            "declared in"
        )
    if reference.doi_registered is False:
        reference.status = "doi-not-registered"
        reference.notes.append(
            f"the DOI ({reference.doi}) does not exist in the handle system "
            "that registers every DOI, so it cannot be a real identifier"
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
            f"found a work, but {', '.join(disagrees)} disagrees with the "
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
        reference.notes.append(
            "no work with this title was found in the services checked"
        )
        venue = (reference.venue or "").lower()
        if any(thin in venue for thin in THIN_VENUES):
            reference.notes.append(
                f"the venue ({reference.venue}) is indexed thinly or not at "
                "all by these services, so this is as likely a coverage gap "
                "as a bad entry and needs checking by hand"
            )


def check_references(
    wdir: str | Path | None = None,
    paths: list[str] | None = None,
    offline: bool = False,
    refresh: bool = False,
) -> ReferenceCheck:
    """Check that every reference a project's documents cite is real.

    Parameters
    ----------
    wdir : str or Path, optional
        Project working directory, defaulting to the current one.
    paths : list of str, optional
        Documents to check. Defaults to every one the pipeline builds
        into a PDF.
    offline : bool, optional
        Use only cached answers, and report the rest as unchecked.
    refresh : bool, optional
        Ignore the cache and ask the services again.

    Returns
    -------
    ReferenceCheck
        One report per document checked.
    """
    import calkit
    from calkit.latex import comment_documents, flatten

    ck_info = calkit.load_calkit_info(wdir=wdir, read_only=True)
    collections = load_collections(wdir=wdir)
    lookup = Lookup(wdir=wdir, offline=offline, refresh=refresh)
    out = ReferenceCheck()

    # flatten names paths relative to the project, so read them there
    # rather than changing the working directory.
    def read(path: str) -> str | None:
        full = Path(wdir or ".") / path
        return (
            full.read_text(encoding="utf-8", errors="replace")
            if full.is_file()
            else None
        )

    for document in paths or comment_documents(ck_info):
        lines = flatten(document, read=read)
        if not lines:
            continue
        check = DocumentCheck(
            path=document,
            sources=list(dict.fromkeys(line.path for line in lines)),
            collections=list(collections),
            offline=offline,
        )
        for key, locations in cited_keys(lines).items():
            reference = Reference(key=key, cited_at=locations)
            defining = []
            for name, entries in collections.items():
                if key in entries:
                    defining.append(name)
            if defining:
                # The first wins, as BibTeX takes them in order.
                reference.collection = defining[0]
                reference.also_in = defining[1:]
                _fill_from_entry(reference, collections[defining[0]][key])
                verify(reference, lookup)
            classify(reference)
            check.references[key] = reference
        check.n_cited = len(check.references)
        counts: dict[str, int] = {}
        for reference in check.references.values():
            counts[reference.status] = counts.get(reference.status, 0) + 1
        check.n_by_status = dict(sorted(counts.items()))
        out.documents.append(check)
    lookup.save()
    out.n_requests = lookup.calls
    return out


def verify(reference: Reference, lookup: Lookup) -> None:
    """Look an entry up, trying its identifier before its title.

    Parameters
    ----------
    reference : Reference
        The entry to look for, updated in place with the best candidate.
    lookup : Lookup
        The cached service reader to ask.
    """
    candidates: list[Found] = []
    if reference.doi:
        hit = lookup.crossref_doi(reference.doi)
        if hit is not None:
            candidates.append(compare(reference, hit))
        else:
            # Crossref is one registrar of several, so an entry it lacks
            # is not yet evidence of anything; the handle system is.
            reference.doi_registered = lookup.doi_registered(reference.doi)
    if reference.arxiv and not any(
        c.title_matches is not False for c in candidates
    ):
        hit = lookup.arxiv(reference.arxiv)
        if hit is not None:
            candidates.append(compare(reference, hit))
    if (
        not [c for c in candidates if c.title_matches is not False]
        and reference.title
    ):
        for hit in (
            lookup.crossref_title(reference.title),
            lookup.openalex_title(reference.title),
        ):
            if hit is not None:
                candidates.append(compare(reference, hit))
    # A candidate found by title has to at least resemble the title it was
    # found with; one found by identifier is kept whatever its title says,
    # since a DOI resolving to another work is the finding.
    plausible = [
        c
        for c in candidates
        if c.source in ("crossref-doi", "arxiv")
        or (c.title_similarity or 0.0) >= TITLE_PLAUSIBLE
    ]
    if not plausible:
        return
    reference.found = max(plausible, key=_rank)


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
    return Found(
        source=source,
        id=item.get("DOI"),
        doi=item.get("DOI"),
        title=titles[0] if titles else None,
        year=int(year) if isinstance(year, int) else None,
        first_author=surname,
    )


def _from_openalex(item: dict) -> Found:
    """A ``Found`` from an OpenAlex work record."""
    authorships = item.get("authorships") or []
    surname = None
    if authorships:
        name = (authorships[0].get("author") or {}).get("display_name") or ""
        parts = name.split()
        surname = parts[-1] if parts else None
    doi = item.get("doi") or ""
    return Found(
        source="openalex",
        id=item.get("id"),
        doi=doi.replace("https://doi.org/", "") or None,
        title=item.get("display_name"),
        year=item.get("publication_year"),
        first_author=surname,
    )


class Lookup:
    """Cached, rate-limited reads of the citation services.

    A failed request is cached as a miss so one unreachable record does
    not make every rerun pay for it again; ``refresh`` clears that.
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
        self.cache: dict[str, Any] = {}
        self.calls = 0
        if self.path.exists() and not refresh:
            try:
                self.cache = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                self.cache = {}

    def save(self) -> None:
        """Write the cache, so the next run needs no network."""
        import json

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
        if isinstance(cached, str) or (url in self.cache and cached is None):
            return cached
        if self.offline:
            return None
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT}
        )
        text = None
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            # An error status can still carry the answer: doi.org replies
            # 404 with the JSON saying the handle doesn't exist.
            try:
                text = e.read().decode("utf-8", errors="replace")
            except OSError:
                text = None
        except (urllib.error.URLError, TimeoutError, OSError):
            text = None
        self.calls += 1
        time.sleep(REQUEST_DELAY_S)
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


def write_reports(
    check: ReferenceCheck, wdir: str | Path | None = None
) -> list[str]:
    """Write one report per document and return where they went.

    Parameters
    ----------
    check : ReferenceCheck
        The check to write.
    wdir : str or Path, optional
        Project working directory, defaulting to the current one.

    Returns
    -------
    list of str
        Project-relative paths written, in document order.
    """
    import json

    out = []
    for document in check.documents:
        path = output_path(document.path)
        full = Path(wdir or ".") / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(
            json.dumps(compact(document.model_dump(mode="json")), indent=2)
            + "\n"
        )
        out.append(path)
    return out


def format_check(check: ReferenceCheck, verbose: bool = False) -> str:
    """Render a check as text, worst first.

    Parameters
    ----------
    check : ReferenceCheck
        The check to render.
    verbose : bool, optional
        List every reference, not only the ones needing attention.

    Returns
    -------
    str
        The report.
    """
    lines = []
    for document in check.documents:
        counts = ", ".join(
            f"{n} {status}" for status, n in document.n_by_status.items()
        )
        lines.append(f"{document.path}: {document.n_cited} cited ({counts})")
        shown = (
            list(document.references.values()) if verbose else document.suspect
        )
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
                    f"{name} {value!r}"
                    for name, value in evidence.differs.items()
                )
                lines.append(f"    the record at {where} says {says}")
            else:
                lines.append(
                    f"    found by {evidence.matched_by} at {where}, "
                    f"agreeing on {', '.join(evidence.agrees_on) or 'nothing'}"
                )
    if not check.documents:
        lines.append("No documents with citations to check.")
    elif check.ok:
        lines.append(
            "✅ Every cited reference resolves to an entry, and none "
            "contradicts the record it was found in."
        )
    else:
        n = sum(len(d.blocking) for d in check.documents)
        lines.append(f"❌ {n} reference(s) cannot be accounted for.")
    return "\n".join(lines)


def document_inputs(
    ck_info: dict, document: str, wdir: str | Path | None = None
) -> list[str]:
    """Files a check of one document reads: it, its inputs, collections.

    Parameters
    ----------
    ck_info : dict
        The project's ``calkit.yaml`` contents.
    document : str
        Project-relative path of the document being checked.
    wdir : str or Path, optional
        Project working directory, defaulting to the current one.

    Returns
    -------
    list of str
        Project-relative paths, deduplicated and sorted.
    """
    from calkit.latex import flatten

    def read(path: str) -> str | None:
        full = Path(wdir or ".") / path
        return (
            full.read_text(encoding="utf-8", errors="replace")
            if full.is_file()
            else None
        )

    # The document and everything it inputs, so a generated table that
    # grew a citation is seen, and the document itself even when it does
    # not exist yet, so the check runs once it does.
    out = {document}
    for line in flatten(document, read=read):
        out.add(line.path)
    for item in ck_info.get("references") or []:
        path = item.get("path") if isinstance(item, dict) else item
        if path:
            out.add(path)
    return sorted(out)


def expand_reference_check_stages(
    ck_info: dict, wdir: str | Path | None = None
) -> dict:
    """Give each ``references-check`` stage the files it reads and writes.

    A stage names the document it checks, and the check reads that
    document, the files it inputs, and the project's reference
    collections, so it has to rerun when any of them changes. All of that
    is derived here, from the project itself, rather than repeated by
    hand in the stage. Its output is that document's report, so editing
    one paper rechecks that paper and leaves another project document's
    report alone.
    """
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    if not any(
        isinstance(st, dict) and st.get("kind") == "references-check"
        for st in stages.values()
    ):
        return ck_info
    expanded = {}
    for name, stage in stages.items():
        if isinstance(stage, dict) and stage.get("kind") == "references-check":
            document = stage.get("target_path")
            if not document:
                # Let the model's own validation report the missing path
                # rather than guessing one here.
                expanded[name] = stage
                continue
            stage = dict(stage)
            derived = [
                "calkit.yaml",
                *document_inputs(ck_info, document, wdir=wdir),
            ]
            declared = list(stage.get("inputs") or [])
            stage["inputs"] = declared + [
                p for p in derived if p not in declared
            ]
            declared_outs = list(stage.get("outputs") or [])
            declared_paths = {
                o.get("path") if isinstance(o, dict) else o
                for o in declared_outs
            }
            report = output_path(document)
            if report not in declared_paths:
                stage["outputs"] = declared_outs + [
                    {"path": report, "storage": "git"}
                ]
        expanded[name] = stage
    out = dict(ck_info)
    out["pipeline"] = {**ck_info["pipeline"], "stages": expanded}
    return out
