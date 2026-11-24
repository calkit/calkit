"""Values quoted from references, and finding them in the references' PDFs.

A value a document quotes from a reference is declared on the entry it
comes from, in ``calkit.yaml``, with where in the reference it appears::

    references:
      - path: references.bib
        values:
          liu2025:
            noise-sigma:
              value: 0.1
              page: 4
              context: "positions perturbed by Gaussian noise with σ = 0.1"

The document cites it with ``\\ckrefval{liu2025}{noise-sigma}``, or its
Quarto and Markdown counterparts. This module finds the reference's PDF,
reads its text, and checks the value and its context against it, or searches it
for a number a document typed in.

PDFs are never stored in the project. They come from, in order: a file the
collection's ``files`` names for the key, Zotero desktop, the Calkit Cloud for a collection linked to
Zotero, and open-access copies downloaded into ``.calkit/local``.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

#: Where downloaded PDFs are kept, under the gitignored local directory
PDF_CACHE_DIR = os.path.join(".calkit", "local", "references")
#: Zotero desktop's local API, which mirrors its web API
ZOTERO_LOCAL_URL = "http://localhost:23119/api"
#: Seconds to wait for Zotero desktop, which answers at once or not at all
ZOTERO_LOCAL_TIMEOUT_S = 2
#: Where the Calkit Cloud records which collections are linked to Zotero,
#: and each entry's Zotero item and attachment keys
ZOTERO_SYNC_INFO_PATH = os.path.join(".calkit", "zotero", "sync.json")
ZOTERO_ITEMS_PATH = os.path.join(".calkit", "zotero", "items.json")
#: How much of a page to show on either side of a number found on it
QUOTE_CHARS = 70


@dataclass
class PdfSource:
    """A reference's PDF, and where it came from."""

    path: Path
    source: str


@dataclass
class Match:
    """A number found on a page of a reference's PDF, 1-based."""

    page: int
    text: str
    context: str


@dataclass
class PdfSearch:
    """What was tried to get a reference's PDF, for saying why none was."""

    tried: list[str] = field(default_factory=list)


def normalize_text(text: str) -> str:
    """Text as it's compared: compatibility forms folded, e.g., ligatures,
    minus signs and dashes as hyphens, and whitespace collapsed.
    """
    text = unicodedata.normalize("NFKC", text)
    text = (
        text.replace("−", "-")
        .replace("–", "-")
        .replace("‐", "-")
        .replace("‑", "-")
        .replace("­", "")
    )
    return re.sub(r"\s+", " ", text).strip()


def read_pdf_pages(path: str | Path) -> list[str]:
    """The text of each page of a PDF, normalized, with words split over
    lines joined back together.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        pages = []
        for page in pdf:
            text = page.get_textpage().get_text_range()
            # pdfium marks a hyphen that splits a word over lines as ￾
            text = re.sub(r"￾\s*", "", text)
            pages.append(normalize_text(text))
        return pages
    finally:
        pdf.close()


# A number as text: digits, optionally grouped in thousands with commas or
# thin or non-breaking spaces, a fraction, and an exponent, as "1e-8",
# "1 × 10−8", or a bare "10^-8" or "10−8", which is how text extraction
# flattens a superscript, then a percent sign. A bare "10" and digits isn't
# read as a power, since "107" is as often a page number. Never the middle
# of a word or of a longer number, e.g., not 2.0 in "2.0.1".
_NUMBER_RE = re.compile(
    r"(?<![\w.])"
    r"(?:"
    r"(?P<pow>10)\s*(?:\^\s*\{?\s*(?P<pexp>[-−+]?\d+)\s*\}?|(?P<nexp>[-−]\d+))"
    r"|(?P<num>(?:\d{1,3}(?:[,\u202f\u00a0]\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
    r"(?:\s*[eE]\s*(?P<eexp>[-−+]?\d+)"
    r"|\s*(?:×|x|·|\\times)\s*10\s*"
    r"(?:\^\s*\{?\s*(?P<texp>[-−+]?\d+)\s*\}?|(?P<tnexp>[-−]\d+)))?"
    r")"
    r"(?P<pct>\s*%)?"
    r"(?!\d|\.\d)"
)


@dataclass(frozen=True)
class Number:
    """A number found in text, with where it is."""

    start: int
    end: int
    text: str
    value: Decimal
    percent: bool


def _exponent(text: str) -> int:
    return int(text.replace("−", "-"))


def find_numbers(text: str) -> list[Number]:
    """Every number in some text, in order.

    A minus sign counts as the number's own after a space, an opening
    bracket, or an operator, e.g., "σ = −0.1", and not after a letter,
    digit, or closing bracket, where it's a hyphen or a subtraction, e.g.,
    "r−1.9".
    """
    out = []
    for m in _NUMBER_RE.finditer(text):
        try:
            if m.group("pow"):
                exp = m.group("pexp") or m.group("nexp")
                value = Decimal(1).scaleb(_exponent(exp))
            else:
                digits = re.sub(r"[,\u202f\u00a0]", "", m.group("num"))
                value = Decimal(digits)
                exp = m.group("eexp") or m.group("texp") or m.group("tnexp")
                if exp:
                    value = value.scaleb(_exponent(exp))
        except (InvalidOperation, ValueError):
            continue
        start = m.start()
        before = text[start - 1] if start > 0 else ""
        if before and before in "-−+":
            ahead = text[start - 2] if start > 1 else ""
            if not (ahead and (ahead.isalnum() or ahead in ")]}")):
                if before != "+":
                    value = -value
                start -= 1
        out.append(
            Number(
                start=start,
                end=m.end(),
                text=text[start : m.end()],
                value=value,
                percent=bool(m.group("pct")),
            )
        )
    return out


def parse_number(value: Any) -> tuple[Decimal, bool] | None:
    """A recorded value as a number, and whether it's a percentage, if it's
    one finite number, e.g., 0.1, "12.5%", "1e-8", or "10,000".
    """
    if isinstance(value, bool):
        return None
    text = normalize_text(str(value))
    found = find_numbers(text)
    if len(found) != 1 or (found[0].start, found[0].end) != (0, len(text)):
        return None
    if not found[0].value.is_finite():
        return None
    return found[0].value, found[0].percent


def _matches(number: Number, wanted: tuple[Decimal, bool]) -> bool:
    return number.value == wanted[0] and number.percent == wanted[1]


def has_number(text: str, value: Any) -> bool:
    """Whether some text has a number, written any of the ways
    ``find_numbers`` reads, e.g., 0.1 as ".1" or "0.10", and 10000 as
    "10,000".
    """
    wanted = parse_number(value)
    if wanted is None:
        return False
    return any(_matches(n, wanted) for n in find_numbers(normalize_text(text)))


def _context(text: str, start: int, end: int) -> str:
    """The part of a page around a match, cut at word boundaries."""
    begin = max(0, start - QUOTE_CHARS)
    stop = min(len(text), end + QUOTE_CHARS)
    if begin > 0:
        space = text.find(" ", begin)
        begin = space + 1 if 0 <= space < start else begin
    if stop < len(text):
        space = text.rfind(" ", end, stop)
        stop = space if space > end else stop
    return text[begin:stop].strip()


def find_number(pages: list[str], value: Any) -> list[Match]:
    """Every place a number appears in a PDF's pages."""
    wanted = parse_number(value)
    if wanted is None:
        return []
    matches = []
    for n, text in enumerate(pages, start=1):
        for number in find_numbers(text):
            if _matches(number, wanted):
                matches.append(
                    Match(
                        page=n,
                        text=number.text,
                        context=_context(text, number.start, number.end),
                    )
                )
    return matches


def _context_pattern(context: str) -> re.Pattern:
    """A pattern finding a context in a page, whatever the spacing and case,
    since text extraction spaces things its own way, e.g., a subscript run
    into what it's on.
    """
    chars = [c for c in normalize_text(context) if not c.isspace()]
    return re.compile(r"\s*".join(re.escape(c) for c in chars), re.IGNORECASE)


def check_value(
    pages: list[str],
    value: Any,
    page: int | None = None,
    context: str | None = None,
) -> str | None:
    """Why a declared value doesn't match its reference's PDF, if it
    doesn't: the context must be on the page, with the value in it, as a
    whole number, so 0.1 doesn't match a context reading 0.15, or without
    a context, the value on the page.
    """
    wanted = parse_number(value)
    if wanted is None:
        return f"{value!r} isn't a number"
    if page is not None and not 1 <= page <= len(pages):
        return f"the PDF has {len(pages)} pages, not {page}"
    if context:
        if not has_number(context, value):
            return f"the context doesn't contain {value}"
        # The pages end to end, since a context can run onto the next one,
        # and it's on the page where it starts
        import bisect

        starts = []
        offset = 0
        for text in pages:
            starts.append(offset)
            offset += len(text) + 1
        whole = " ".join(pages)
        numbers = find_numbers(whole)
        found: list[tuple[int, list[str]]] = []
        for m in _context_pattern(context).finditer(whole):
            n = bisect.bisect_right(starts, m.start())
            inside = [
                x
                for x in numbers
                if x.start >= m.start() - 1 and x.end <= m.end()
            ]
            # The context's own number has to be a whole number there, not
            # the start of a longer one
            if any(_matches(x, wanted) for x in inside):
                if page is None or page == n:
                    return None
                found.append((n, []))
            else:
                overlapping = [
                    x.text
                    for x in numbers
                    if x.start < m.end() and x.end > m.start()
                ]
                found.append((n, overlapping))
        if not found:
            return "the context isn't in the PDF"
        right = [n for n, numbers_there in found if not numbers_there]
        if right:
            return f"the context is on page {right[0]}, not {page}"
        n, numbers_there = found[0]
        return (
            f"on page {n}, the context reads {', '.join(numbers_there)}, "
            f"not {value}"
        )
    where = [pages[page - 1]] if page is not None else pages
    if not any(has_number(text, value) for text in where):
        return (
            f"{value} isn't on page {page}"
            if page is not None
            else f"{value} isn't in the PDF"
        )
    return None


def _read_json(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get_zotero_link(
    collection_path: str, key: str, wdir: str | None = None
) -> tuple[dict, dict] | None:
    """A collection's Zotero link and an entry's Zotero item, as the Calkit
    Cloud records them in the project, if the collection is linked.
    """
    base = wdir or "."
    link = _read_json(os.path.join(base, ZOTERO_SYNC_INFO_PATH)).get(
        collection_path
    )
    items = _read_json(os.path.join(base, ZOTERO_ITEMS_PATH))
    item = (items.get(collection_path) or {}).get(key)
    if not isinstance(link, dict) or not isinstance(item, dict):
        return None
    return link, item


def get_zotero_local_pdf(link: dict, item: dict) -> Path | None:
    """An entry's PDF from Zotero desktop's local API, if it's running with
    the API turned on and has the file.

    The local API gives the path of an attachment on disk, so this covers
    files Zotero syncs elsewhere, e.g., with WebDAV, or links, which the web
    API can't serve.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    if link.get("library_type") == "group":
        prefix = f"groups/{link.get('library_id')}"
    else:
        # The local API calls the user's own library 0
        prefix = "users/0"
    for attachment in item.get("pdf_attachment_keys") or []:
        url = f"{ZOTERO_LOCAL_URL}/{prefix}/items/{attachment}/file/view/url"
        try:
            with urllib.request.urlopen(
                url, timeout=ZOTERO_LOCAL_TIMEOUT_S
            ) as response:
                file_url = response.read().decode().strip()
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            # Not running, turned off, or no such file: no other attachment
            # will do better unless it's only this file that's missing
            continue
        parsed = urllib.parse.urlparse(file_url)
        if parsed.scheme != "file":
            continue
        path = Path(urllib.request.url2pathname(parsed.path))
        if path.is_file():
            return path
    return None


def get_cloud_pdf(
    collection_path: str, key: str, dest: Path, wdir: str | None = None
) -> Path | None:
    """An entry's Zotero PDF through the Calkit Cloud, saved to ``dest``,
    for a project linked to Zotero there, when logged in.
    """
    import calkit
    from calkit.hub.core import _request

    try:
        project = calkit.detect_project_name(wdir=wdir)
        response = _request(
            "get",
            f"/projects/{project}/zotero/items/{key}/pdf",
            params={"path": collection_path},
            as_json=False,
            max_retries=1,
            allow_login=False,
        )
    except Exception:
        return None
    content = getattr(response, "content", None)
    if not content or not content.startswith(b"%PDF"):
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return dest


def get_open_access_urls(entry: dict, lookup: Any) -> list[str]:
    """Where an open-access copy of a reference might be: arXiv for a
    preprint, and the PDF OpenAlex lists for its DOI.
    """
    import urllib.parse

    urls = []
    arxiv = None
    if (entry.get("archiveprefix") or "").lower() == "arxiv":
        arxiv = (entry.get("eprint") or "").strip()
    doi = (entry.get("doi") or "").strip()
    m = re.match(r"10\.48550/arxiv\.(.+)$", doi, re.I)
    if not arxiv and m:
        arxiv = m.group(1)
    if not arxiv:
        m = re.search(
            r"arxiv\.org/(?:abs|pdf)/([\w./-]+?)(?:v\d+)?(?:\.pdf)?$",
            entry.get("url") or "",
            re.I,
        )
        arxiv = m.group(1) if m else None
    if arxiv:
        urls.append(f"https://arxiv.org/pdf/{arxiv}")
    if doi and lookup is not None:
        record = lookup.get_json(
            "https://api.openalex.org/works/doi:"
            + urllib.parse.quote(doi, safe="/")
        )
        if isinstance(record, dict):
            for location in [
                record.get("best_oa_location"),
                *(record.get("oa_locations") or []),
            ]:
                if isinstance(location, dict) and location.get("pdf_url"):
                    if location["pdf_url"] not in urls:
                        urls.append(location["pdf_url"])
    return urls


def download_pdf(url: str, dest: Path) -> Path | None:
    """Save a PDF from a URL, if what it serves is one."""
    import urllib.error
    import urllib.request

    from calkit.references import USER_AGENT

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if not content.startswith(b"%PDF"):
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return dest


def get_cache_path(
    collection_path: str, key: str, entry: dict | None, wdir: str | None
) -> Path:
    """Where a downloaded copy of a reference's PDF is kept, named for its
    collection, key, and identifiers, so two works sharing a key, or an
    entry that now names another work, don't share one.
    """
    import hashlib

    entry = entry or {}
    ident = "\n".join(
        [
            collection_path,
            key,
            str(entry.get("doi") or ""),
            str(entry.get("eprint") or ""),
            str(entry.get("url") or ""),
        ]
    )
    digest = hashlib.sha256(ident.encode()).hexdigest()[:12]
    safe_key = re.sub(r"[^\w.-]", "_", key)[:60]
    return Path(wdir or ".") / PDF_CACHE_DIR / f"{safe_key}-{digest}.pdf"


def _in_project(path: Path, base: Path) -> bool:
    """Whether a path, links followed, is inside the project."""
    try:
        return path.resolve().is_relative_to(base.resolve())
    except OSError:
        return False


def get_pdf(
    collection_path: str,
    key: str,
    entry: dict | None = None,
    file: str | None = None,
    wdir: str | None = None,
    download: bool = False,
    lookup: Any = None,
    search: PdfSearch | None = None,
    zotero_desktop: bool = True,
) -> PdfSource | None:
    """A reference's PDF, from the first source that has it.

    ``file`` is the one the collection names for the key in ``calkit.yaml``,
    which has to be inside the project. Then Zotero desktop, which is on
    this machine, is asked for a collection linked to Zotero, then a copy
    downloaded before is used. With ``download``, which is what goes on the
    network, the Calkit Cloud is asked for a collection linked to Zotero,
    and then open-access copies are fetched. What's fetched is kept in
    ``.calkit/local`` for next time, never in the project.
    """
    base = Path(wdir or ".")
    search = search if search is not None else PdfSearch()

    def tried(where: str) -> None:
        search.tried.append(where)

    if file:
        path = base / file
        tried(file)
        # A path outside the project, e.g., absolute, with .., or a link,
        # isn't the project's to read
        if path.is_file() and _in_project(path, base):
            return PdfSource(path=path, source=file)
    linked = get_zotero_link(collection_path, key, wdir=wdir)
    if linked is not None and zotero_desktop:
        tried("Zotero desktop")
        path = get_zotero_local_pdf(*linked)
        if path is not None:
            return PdfSource(path=path, source="Zotero desktop")
    cached = get_cache_path(collection_path, key, entry, wdir)
    if cached.is_file():
        return PdfSource(path=cached, source="downloaded")
    if not download:
        return None
    # What's fetched goes in the local directory, which keeps itself out of
    # Git, since most papers can't be redistributed
    from calkit.core import ensure_local_dir

    def make_cache_dir() -> None:
        ensure_local_dir(str(base))
        cached.parent.mkdir(parents=True, exist_ok=True)

    if linked is not None:
        tried("the Calkit Cloud's Zotero link")
        make_cache_dir()
        path = get_cloud_pdf(collection_path, key, cached, wdir=wdir)
        if path is not None:
            return PdfSource(path=path, source="Zotero, through the Cloud")
    if entry is not None:
        for url in get_open_access_urls(entry, lookup):
            tried(url)
            make_cache_dir()
            path = download_pdf(url, cached)
            if path is not None:
                return PdfSource(path=path, source=url)
    return None


class PdfFinder:
    """Finds and reads references' PDFs, once each per run, including the
    ones it can't find, so a reference quoted many times is looked up, and
    downloaded, once.
    """

    def __init__(
        self,
        ck_info: dict,
        wdir: str | None = None,
        download: bool = True,
        lookup: Any = None,
        read: Callable[[Path], list[str]] | None = None,
        zotero_desktop: bool = True,
    ) -> None:
        from calkit.references import (
            get_declared_collection_paths,
            load_collections,
        )

        self.wdir = wdir
        self.download = download
        self.zotero_desktop = zotero_desktop
        self.lookup = lookup
        self.read = read or read_pdf_pages
        self.paths = get_declared_collection_paths(ck_info)
        self.loaded = load_collections(wdir=wdir, paths=self.paths)
        self.collections = {
            c["path"]: c
            for c in ck_info.get("references") or []
            if isinstance(c, dict) and c.get("path")
        }
        self.found: dict[tuple[str, str], tuple] = {}

    def get(
        self, collection_path: str, key: str
    ) -> tuple[PdfSource | None, list[str] | None, list[str]]:
        """A reference's PDF, its pages' text, and what was tried, with
        ``None`` for the pages if it couldn't be read or has no text, e.g.,
        a scan.
        """
        cache_key = (collection_path, key)
        if cache_key in self.found:
            return self.found[cache_key]
        search = PdfSearch()
        source = get_pdf(
            collection_path,
            key,
            entry=self.loaded.get(collection_path, {}).get(key),
            file=get_entry_file(
                self.collections.get(collection_path, {}), key
            ),
            wdir=self.wdir,
            download=self.download,
            lookup=self.lookup,
            search=search,
            zotero_desktop=self.zotero_desktop,
        )
        pages = None
        if source is not None:
            try:
                pages = self.read(source.path)
            except Exception as e:
                search.tried.append(f"{source.source}: {e}")
                pages = None
            if pages is not None and not any(p.strip() for p in pages):
                search.tried.append(f"{source.source}, which has no text")
                pages = None
        self.found[cache_key] = (source, pages, search.tried)
        return self.found[cache_key]

    def get_by_key(
        self, key: str
    ) -> tuple[PdfSource | None, list[str] | None, list[str]]:
        """A reference's PDF from the first collection defining the key."""
        for path in self.paths:
            if key in self.loaded.get(path, {}):
                return self.get(path, key)
        return None, None, []


def iter_declared_values(ck_info: dict) -> list[tuple[str, str, str, dict]]:
    """Every value declared on a reference, as ``(collection path, key,
    name, value info)``.
    """
    out = []
    for collection in ck_info.get("references") or []:
        if not isinstance(collection, dict):
            continue
        path = collection.get("path")
        by_key = collection.get("values") or {}
        if not path or not isinstance(by_key, dict):
            continue
        for key, values in by_key.items():
            if not isinstance(values, dict):
                continue
            for name, info in values.items():
                if isinstance(info, dict):
                    out.append((path, str(key), str(name), info))
    return out


def get_reference_files(collection: dict) -> dict[str, str]:
    """A collection's PDFs by citation key, from its ``files``, which maps
    keys to paths, or is a list of key and path, as Calkit wrote before.
    """
    files = collection.get("files") or {}
    if isinstance(files, dict):
        return {
            str(key): path
            for key, path in files.items()
            if isinstance(path, str)
        }
    out = {}
    for item in files if isinstance(files, list) else []:
        if (
            isinstance(item, dict)
            and isinstance(item.get("key"), str)
            and isinstance(item.get("path"), str)
        ):
            out[item["key"]] = item["path"]
    return out


def get_entry_file(collection: dict, key: str) -> str | None:
    """The PDF a collection's ``files`` names for a key, if any."""
    return get_reference_files(collection).get(key)


def cached_pages(
    reader: Callable[[Path], list[str]] = read_pdf_pages,
) -> Callable[[Path], list[str]]:
    """A PDF reader that reads each file once."""
    cache: dict[Path, list[str]] = {}

    def read(path: Path) -> list[str]:
        if path not in cache:
            cache[path] = reader(path)
        return cache[path]

    return read


def find_collections_with_key(
    ck_info: dict, key: str, wdir: str | None = None
) -> list[str]:
    """The declared collections that define a citation key."""
    from calkit.references import (
        get_declared_collection_paths,
        load_collections,
    )

    paths = get_declared_collection_paths(ck_info)
    collections = load_collections(wdir=wdir, paths=paths)
    return [path for path in paths if key in collections.get(path, {})]


def add_value(
    ck_info: dict,
    key: str,
    name: str,
    value: Any,
    page: int | None = None,
    context: str | None = None,
    description: str | None = None,
    collection: str | None = None,
    wdir: str | None = None,
) -> str:
    """Declare a value quoted from a reference in ``ck_info``, returning
    the collection it was added to. Raises a ``ValueError`` saying what's
    wrong.
    """
    from calkit.models.core import ReferenceValue

    collections = [
        c
        for c in ck_info.get("references") or []
        if isinstance(c, dict) and c.get("path")
    ]
    if not collections:
        raise ValueError("The project has no reference collections")
    if collection is None:
        defining = find_collections_with_key(ck_info, key, wdir=wdir)
        if not defining:
            raise ValueError(f"No reference collection defines '{key}'")
        if len(defining) > 1:
            raise ValueError(
                f"'{key}' is in {', '.join(defining)}; say which with "
                "--collection"
            )
        collection = defining[0]
    target = next((c for c in collections if c["path"] == collection), None)
    if target is None:
        raise ValueError(f"'{collection}' isn't a reference collection")
    if parse_number(value) is None:
        raise ValueError(f"{value!r} isn't a number")
    info: dict[str, Any] = {"value": value}
    if page is not None:
        info["page"] = page
    if context:
        info["context"] = context
    if description:
        info["description"] = description
    ReferenceValue.model_validate(info)
    values = target.setdefault("values", {}).setdefault(key, {})
    if name in values:
        raise ValueError(f"'{key}' already has a value named '{name}'")
    values[name] = info
    return collection


#: Where Calkit writes the values quoted from references, from
#: calkit.yaml, one file per citation key, so a document depends on the
#: references it quotes rather than on all of calkit.yaml, or on every value
VALUES_DIR = ".calkit/reference-values"


def get_values_path(key: str) -> str:
    """The file a reference's values are written to, its citation key
    percent-encoded, so any key makes a safe and distinct file name.
    BibTeX keys don't differ only by case, so neither do these.
    """
    import urllib.parse

    return f"{VALUES_DIR}/{urllib.parse.quote(key, safe='')}.json"


def is_values_path(path: str) -> bool:
    """Whether a path is one of the files of values quoted from references."""
    return Path(path).as_posix().startswith(VALUES_DIR + "/")


def get_values_by_key(ck_info: dict) -> dict[str, dict[str, Any]]:
    """The values documents can quote, by citation key, then name."""
    data: dict[str, dict[str, Any]] = {}
    for _, key, name, info in iter_declared_values(ck_info):
        data.setdefault(key, {})[name] = info.get("value")
    return data


def get_values_data(ck_info: dict) -> dict[str, dict[str, Any]]:
    """What each values file holds, by its path."""
    return {
        get_values_path(key): values
        for key, values in get_values_by_key(ck_info).items()
    }


def write_values_file(ck_info: dict, wdir: str | None = None) -> bool:
    """Write the files of values from ``calkit.yaml``, one per reference,
    removing any for a reference with none, and returning whether there
    are any.

    Each is only rewritten when what it holds changes, so what depends on
    it isn't made out of date by rewriting it.
    """
    folder = Path(wdir or ".") / VALUES_DIR
    data = get_values_data(ck_info)
    wanted = set()
    for rel, values in data.items():
        path = Path(wdir or ".") / rel
        wanted.add(path.name)
        text = json.dumps(values, indent=2, sort_keys=True, ensure_ascii=False)
        text += "\n"
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
    if folder.is_dir():
        for path in folder.glob("*.json"):
            if path.name not in wanted:
                path.unlink()
        if not any(folder.iterdir()):
            folder.rmdir()
    return bool(data)


@dataclass
class Use:
    """A document quoting a value from a reference: the document, which
    names the bibliographies and cites, and the ``file`` and 1-based
    ``line`` it's on, which differ for a file a LaTeX document inputs, and
    are a line of a notebook's Markdown and raw cells for a notebook.
    """

    document: str
    file: str
    line: int
    key: str
    name: str


def is_markdown_like(path: str) -> bool:
    """Whether a document is Markdown, including Quarto's and notebooks."""
    return path.lower().endswith(
        (".md", ".markdown", ".qmd", ".rmd", ".ipynb")
    )


def read_markdown_lines(path: str) -> list[str]:
    """A Markdown document's lines, or a notebook's Markdown and raw cells',
    which is where its prose and front matter are.
    """
    from calkit.quarto import read_document_text

    text = read_document_text(path)
    return text.splitlines() if text is not None else []


# Inline code, whose text is an example, not a use
_MD_INLINE_CODE_RE = re.compile(r"(`+)[^\n]*?(?<!`)\1(?!`)")
_MD_FENCE_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})")
# LaTeX environments and commands whose text is shown as is
_TEX_VERBATIM_ENVS = (
    "verbatim",
    "Verbatim",
    "lstlisting",
    "minted",
    "comment",
    "alltt",
)
_TEX_VERB_RE = re.compile(r"\\verb\*?(.).*?\1|\\lstinline\*?(.).*?\2")


def _markdown_prose_lines(path: str) -> list[tuple[int, str]]:
    """A Markdown document's lines that are prose, numbered from 1, with
    inline code blanked, leaving out code blocks.
    """
    out = []
    fence: str | None = None
    for n, line in enumerate(read_markdown_lines(path), start=1):
        m = _MD_FENCE_RE.match(line)
        if fence is not None:
            if (
                m
                and m.group(1)[0] == fence[0]
                and len(m.group(1)) >= len(fence)
            ):
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        out.append(
            (n, _MD_INLINE_CODE_RE.sub(lambda c: " " * len(c.group()), line))
        )
    return out


def find_uses(documents: list[str], wdir: str | None = None) -> list[Use]:
    """Every ``ckrefval`` in the documents, in LaTeX, Quarto, or Markdown,
    with project-relative paths, leaving out examples in code.
    """
    from calkit.latex import _CK_REFVAL_RE, _strip_comments, flatten
    from calkit.markdown import (
        _CKVALUE_RE,
        MarkdownParseError,
        _ckvalue_args,
    )
    from calkit.quarto import _REFVAL_SHORTCODE_RE

    base = wdir or "."
    uses = []
    for document in documents:
        full = os.path.join(base, document)
        if is_markdown_like(document):
            for n, line in _markdown_prose_lines(full):
                found = [
                    m.group("args")
                    for m in _REFVAL_SHORTCODE_RE.finditer(line)
                ] + [
                    m.group("args")
                    for m in _CKVALUE_RE.finditer(line)
                    if m.group("cmd") == "ckrefval"
                ]
                for args in found:
                    try:
                        got = _ckvalue_args(args, document, n)
                    except MarkdownParseError:
                        continue
                    uses.append(
                        Use(document, document, n, got["source"], got["key"])
                    )
            continue
        verbatim: str | None = None
        for line in flatten(full):
            text = _strip_comments(line.text)
            if verbatim is not None:
                if f"\\end{{{verbatim}}}" in text:
                    verbatim = None
                continue
            begin = re.search(
                r"\\begin\{(" + "|".join(_TEX_VERBATIM_ENVS) + r")\*?\}", text
            )
            if begin and f"\\end{{{begin.group(1)}}}" not in text:
                verbatim = begin.group(1)
                text = text[: begin.start()]
            text = _TEX_VERB_RE.sub(" ", text)
            for m in _CK_REFVAL_RE.finditer(text):
                key, name = m.group("first").strip(), m.group("second").strip()
                if "#" in key + name:
                    continue
                rel = os.path.relpath(line.path, base).replace(os.sep, "/")
                uses.append(Use(document, rel, line.lineno, key, name))
    return uses


def get_document_bibliographies(
    document: str, wdir: str | None = None
) -> list[str]:
    """The project-relative bibliographies a document names."""
    import yaml

    from calkit.latex import flatten
    from calkit.references import get_named_collection_paths

    base = wdir or "."
    full = os.path.join(base, document)
    if not is_markdown_like(document):
        try:
            return get_named_collection_paths(
                document, flatten(full), wdir=wdir
            )
        except Exception:
            return []
    lines = read_markdown_lines(full)
    if not lines or lines[0].strip() != "---":
        return []
    try:
        end = next(
            i
            for i, line in enumerate(lines[1:], start=1)
            if line.strip() in ("---", "...")
        )
        meta = yaml.safe_load("\n".join(lines[1:end])) or {}
    except (StopIteration, yaml.YAMLError):
        return []
    named = meta.get("bibliography") if isinstance(meta, dict) else None
    if isinstance(named, str):
        named = [named]
    folder = os.path.dirname(document)
    return [
        Path(os.path.normpath(os.path.join(folder, str(p)))).as_posix()
        for p in named or []
    ]


def get_cited_keys(document: str, wdir: str | None = None) -> set[str]:
    """The citation keys a document cites in its text, including the files
    a LaTeX one inputs, not counting ``\\nocite``, Pandoc's ``nocite`` in
    front matter, or a Quarto cross-reference.
    """
    from calkit.latex import flatten
    from calkit.references import (
        _MD_SKIP_RE,
        CROSSREF_RE,
        MARKDOWN_CITE_RE,
        find_cited_keys,
    )

    full = os.path.join(wdir or ".", document)
    if not is_markdown_like(document):
        try:
            return set(find_cited_keys(flatten(full), include_nocite=False))
        except Exception:
            return set()
    lines = [line for _, line in _markdown_prose_lines(full)]
    # Front matter, e.g., nocite, isn't text
    if lines and lines[0].strip() == "---":
        end = next(
            (
                i
                for i, line in enumerate(lines[1:], start=1)
                if line.strip() in ("---", "...")
            ),
            0,
        )
        lines = lines[end + 1 :]
    text = _MD_SKIP_RE.sub(" ", "\n".join(lines))
    keys = set()
    for m in MARKDOWN_CITE_RE.finditer(text):
        key = m.group(1) or m.group(2)
        if not CROSSREF_RE.match(key):
            keys.add(key)
    return keys


def get_line_cited_keys(line: str, markdown: bool) -> list[str]:
    """The citation keys one line of a document cites, in order."""
    from calkit.latex import SourceLine
    from calkit.references import (
        CROSSREF_RE,
        MARKDOWN_CITE_RE,
        find_cited_keys,
    )

    if markdown:
        keys = []
        for m in MARKDOWN_CITE_RE.finditer(line):
            key = m.group(1) or m.group(2)
            if not CROSSREF_RE.match(key) and key not in keys:
                keys.append(key)
        return keys
    return list(
        find_cited_keys(
            [SourceLine(path="doc.tex", lineno=1, text=line)],
            include_nocite=False,
        )
    )


def _same_entry(a: dict, b: dict) -> bool:
    """Whether two collections' entries for a key are the same work."""
    from calkit.references import normalize_doi, normalize_title

    doi_a, doi_b = normalize_doi(a.get("doi")), normalize_doi(b.get("doi"))
    if doi_a and doi_b:
        return doi_a == doi_b
    return normalize_title(a.get("title")) == normalize_title(b.get("title"))


def _count_keys(path: str) -> dict[str, int]:
    """How many times each citation key is defined in a ``.bib`` file."""
    from calkit.releases import parse_bibtex

    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    counts: dict[str, int] = {}
    for entry in parse_bibtex(text):
        if entry.get("ID"):
            counts[entry["ID"]] = counts.get(entry["ID"], 0) + 1
    return counts


def check_project(
    ck_info: dict,
    documents: list[str],
    wdir: str | None = None,
    download: bool = True,
    lookup: Any = None,
    read: Callable[[Path], list[str]] | None = None,
    finder: PdfFinder | None = None,
) -> dict[str, list[dict]]:
    """Check the values a project quotes from references.

    Returns ``problems``, each with the ``file`` and ``line`` it's about,
    the ``key`` and ``name``, and the ``problem``, and ``unchecked``, the
    values whose reference has no PDF with text to check them against.
    """
    from calkit.references import (
        get_declared_collection_paths,
        load_collections,
    )

    base = wdir or "."
    finder = finder or PdfFinder(
        ck_info, wdir=wdir, download=download, lookup=lookup, read=read
    )
    problems: list[dict] = []
    unchecked: list[dict] = []

    def problem(
        file: str, line: int, key: str, name: str | None, text: str
    ) -> None:
        problems.append(
            {
                "file": file,
                "line": line,
                "key": key,
                "name": name,
                "problem": text,
            }
        )

    declared = iter_declared_values(ck_info)
    uses = find_uses(documents, wdir=wdir)
    if not declared and not uses:
        return {"problems": [], "unchecked": []}
    bibs = {d: get_document_bibliographies(d, wdir=wdir) for d in documents}
    paths = list(
        dict.fromkeys(
            get_declared_collection_paths(ck_info)
            + [p for named in bibs.values() for p in named]
        )
    )
    loaded = load_collections(wdir=wdir, paths=paths)
    # A key defined twice in one file is one BibTeX would refuse, which
    # reading it hides by keeping the last
    for path in paths:
        for key, count in _count_keys(os.path.join(base, path)).items():
            if count > 1:
                problem(path, 0, key, None, f"{key} is defined {count} times")
    by_value: dict[tuple[str, str], list[str]] = {}
    for path, key, name, info in declared:
        by_value.setdefault((key, name), []).append(path)
        if path in loaded and key not in loaded[path]:
            problem(
                "calkit.yaml", 0, key, name, f"{path} doesn't define {key}"
            )
            continue
        if parse_number(info.get("value")) is None:
            problem(
                "calkit.yaml",
                0,
                key,
                name,
                f"{info.get('value')!r} isn't a number",
            )
            continue
        source, pages, tried = finder.get(path, key)
        if source is None or pages is None:
            unchecked.append({"key": key, "name": name, "tried": tried})
            continue
        found = check_value(
            pages, info.get("value"), info.get("page"), info.get("context")
        )
        if found is not None:
            problem(
                "calkit.yaml", 0, key, name, f"in {source.source}, {found}"
            )
    cited: dict[str, set[str]] = {}
    for use in uses:
        named = bibs.get(use.document) or []
        recorded = by_value.get((use.key, use.name), [])
        if not recorded:
            problem(
                use.file,
                use.line,
                use.key,
                use.name,
                f"calkit.yaml records no value '{use.name}' quoted from "
                f"'{use.key}'",
            )
        if named:
            defining = [p for p in named if use.key in loaded.get(p, {})]
            if not defining:
                problem(
                    use.file,
                    use.line,
                    use.key,
                    use.name,
                    f"{use.key} isn't in the bibliographies "
                    f"{use.document} names ({', '.join(named)})",
                )
            elif len(defining) > 1:
                first = loaded[defining[0]][use.key]
                if not all(
                    _same_entry(first, loaded[p][use.key]) for p in defining
                ):
                    problem(
                        use.file,
                        use.line,
                        use.key,
                        use.name,
                        f"{use.key} is a different entry in "
                        f"{' and '.join(defining)}",
                    )
            if recorded and not set(recorded) & set(named):
                problem(
                    use.file,
                    use.line,
                    use.key,
                    use.name,
                    f"'{use.name}' is recorded for {use.key} in "
                    f"{', '.join(recorded)}, which {use.document} doesn't use",
                )
        if len(recorded) > 1:
            problem(
                use.file,
                use.line,
                use.key,
                use.name,
                f"'{use.name}' is recorded for {use.key} in both "
                f"{' and '.join(recorded)}",
            )
        if use.document not in cited:
            cited[use.document] = get_cited_keys(use.document, wdir=wdir)
        if use.key not in cited[use.document]:
            problem(
                use.file,
                use.line,
                use.key,
                use.name,
                f"{use.document} quotes {use.key} but never cites it",
            )
    # One problem per thing wrong, though a value is quoted many times
    unique = list(
        {json.dumps(p, sort_keys=True): p for p in problems}.values()
    )
    return {"problems": unique, "unchecked": unchecked}


def search_cited(
    findings: list[dict],
    ck_info: dict,
    wdir: str | None = None,
    download: bool = True,
    lookup: Any = None,
    read: Callable[[Path], list[str]] | None = None,
    finder: PdfFinder | None = None,
) -> None:
    """For each typed number in a sentence citing a reference, look for it
    in the reference's PDF, adding where it was ``found``, or the keys
    ``searched`` without finding it.

    Each finding needs ``value`` and ``cited_keys``.
    """
    finder = finder or PdfFinder(
        ck_info, wdir=wdir, download=download, lookup=lookup, read=read
    )
    for finding in findings:
        if parse_number(finding["value"]) is None:
            continue
        found, searched = [], []
        for key in finding.get("cited_keys") or []:
            source, pages, _ = finder.get_by_key(key)
            if source is None or pages is None:
                continue
            searched.append(key)
            for match in find_number(pages, finding["value"]):
                found.append(
                    {
                        "key": key,
                        "page": match.page,
                        "context": match.context,
                        "source": source.source,
                    }
                )
        if found:
            finding["found"] = found
        elif searched:
            finding["searched"] = searched
