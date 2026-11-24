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
              quote: "positions perturbed by Gaussian noise with σ = 0.1"

The document cites it with ``\\ckrefval{liu2025}{noise-sigma}``, or its
Quarto and Markdown counterparts. This module finds the reference's PDF,
reads its text, and checks the value and quote against it, or searches it
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
    quote: str


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


def _to_decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def get_number_pattern(value: Any) -> re.Pattern | None:
    """A pattern matching a number as a document or a PDF might write it.

    Leading and trailing zeros may differ, e.g., 0.1 matches ".1" and
    "0.10", as may a thousands separator, e.g., 10000 and "10,000", and a
    percentage keeps its sign, e.g., "12.5 %". Scientific notation matches
    "1e-3", "1 × 10-3", and "10-3", as text extraction flattens exponents.
    A number never matches part of a longer one: 0.1 doesn't match 0.15.
    """
    text = normalize_text(str(value)).replace(",", "")
    percent = text.endswith("%")
    text = text.rstrip("%").strip()
    number = _to_decimal(text)
    if number is None:
        return None
    sign = "-" if number < 0 else ""
    number = abs(number)
    before = r"(?<![\w.,])"
    after = r"(?![\d]|[.,]\d)"
    if number != 0 and (number < Decimal("0.001") or number >= 10**7):
        mantissa, exponent = f"{number:e}".split("e")
        mantissa = mantissa.rstrip("0").rstrip(".")
        exponent = int(exponent)
        exp = ("[-−]" if exponent < 0 else "[+]?") + str(abs(exponent))
        variants = [rf"{re.escape(mantissa)}0*\s*[eE]\s*{exp}"]
        times = r"\s*(?:×|x|\\times|·)\s*10\s*\^?\s*\{?"
        variants.append(rf"{re.escape(mantissa)}0*{times}{exp}\}}?")
        if mantissa == "1":
            variants.append(rf"10\s*\^?\s*\{{?{exp}\}}?")
        body = "(?:" + "|".join(variants) + ")"
    else:
        integer, _, fraction = f"{number:f}".partition(".")
        fraction = fraction.rstrip("0")
        if len(integer) > 3:
            # 10000, 10,000, or 10 000, but not 1,0000
            groups = []
            while len(integer) > 3:
                groups.insert(0, integer[-3:])
                integer = integer[:-3]
            groups.insert(0, integer)
            int_part = groups[0] + "".join(rf"[,\s ]?{g}" for g in groups[1:])
        elif integer == "0" and fraction:
            int_part = "0?"
        else:
            int_part = re.escape(integer)
        if fraction:
            body = rf"{int_part}\.{fraction}0*"
        else:
            body = rf"{int_part}(?:\.0+)?"
    if sign:
        body = rf"[-−]\s*{body}"
    if percent:
        body = rf"{body}\s*%"
    return re.compile(before + body + (after if not percent else ""))


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
    pattern = get_number_pattern(value)
    if pattern is None:
        return []
    matches = []
    for n, text in enumerate(pages, start=1):
        for m in pattern.finditer(text):
            matches.append(
                Match(
                    page=n,
                    text=m.group(0),
                    quote=_context(text, m.start(), m.end()),
                )
            )
    return matches


def check_value(
    pages: list[str],
    value: Any,
    page: int | None = None,
    quote: str | None = None,
) -> str | None:
    """Why a declared value doesn't match its reference's PDF, if it
    doesn't: the quote must be on the page, and the value in the quote, or
    without a quote, the value on the page.
    """
    pattern = get_number_pattern(value)
    if pattern is None:
        return f"{value!r} isn't a number"
    if page is not None and not 1 <= page <= len(pages):
        return f"the PDF has {len(pages)} pages, not {page}"
    if quote:
        wanted = normalize_text(quote)
        if not pattern.search(wanted):
            return f"the quote doesn't contain {value}"
        folded = wanted.casefold()
        on = [
            n
            for n, text in enumerate(pages, start=1)
            if folded in text.casefold()
        ]
        if not on:
            return "the quote isn't in the PDF"
        if page is not None and page not in on:
            return f"the quote is on page {on[0]}, not {page}"
        return None
    where = [pages[page - 1]] if page is not None else pages
    if not any(pattern.search(text) for text in where):
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


def get_pdf(
    collection_path: str,
    key: str,
    entry: dict | None = None,
    file: str | None = None,
    wdir: str | None = None,
    download: bool = False,
    lookup: Any = None,
    search: PdfSearch | None = None,
) -> PdfSource | None:
    """A reference's PDF, from the first source that has it.

    ``file`` is the one the collection names for the key in ``calkit.yaml``. Without one, Zotero
    desktop and the Calkit Cloud are asked for a collection linked to
    Zotero, and with ``download``, open-access copies are fetched. What's
    fetched is kept in ``.calkit/local`` for next time, never in the
    project.
    """
    base = Path(wdir or ".")
    search = search if search is not None else PdfSearch()

    def tried(where: str) -> None:
        search.tried.append(where)

    if file:
        path = base / file
        tried(file)
        if path.is_file():
            return PdfSource(path=path, source=file)
    safe_key = re.sub(r"[^\w.-]", "_", key)
    cached = base / PDF_CACHE_DIR / f"{safe_key}.pdf"
    if cached.is_file():
        return PdfSource(path=cached, source="downloaded")
    # What's fetched goes in the local directory, which keeps itself out of
    # Git, since most papers can't be redistributed
    from calkit.core import ensure_local_dir

    def make_cache_dir() -> None:
        ensure_local_dir(str(base))
        cached.parent.mkdir(parents=True, exist_ok=True)

    linked = get_zotero_link(collection_path, key, wdir=wdir)
    if linked is not None:
        tried("Zotero desktop")
        path = get_zotero_local_pdf(*linked)
        if path is not None:
            return PdfSource(path=path, source="Zotero desktop")
        tried("the Calkit Cloud's Zotero link")
        make_cache_dir()
        path = get_cloud_pdf(collection_path, key, cached, wdir=wdir)
        if path is not None:
            return PdfSource(path=path, source="Zotero, through the Cloud")
    if download and entry is not None:
        for url in get_open_access_urls(entry, lookup):
            tried(url)
            make_cache_dir()
            path = download_pdf(url, cached)
            if path is not None:
                return PdfSource(path=path, source=url)
    return None


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


def get_entry_file(collection: dict, key: str) -> str | None:
    """The PDF a collection's ``files`` names for a key, if any."""
    for item in collection.get("files") or []:
        if isinstance(item, dict) and item.get("key") == key:
            return item.get("path")
    return None


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
    quote: str | None = None,
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
    info: dict[str, Any] = {"value": value}
    if page is not None:
        info["page"] = page
    if quote:
        info["quote"] = quote
    if description:
        info["description"] = description
    ReferenceValue.model_validate(info)
    values = target.setdefault("values", {}).setdefault(key, {})
    if name in values:
        raise ValueError(f"'{key}' already has a value named '{name}'")
    values[name] = info
    return collection


#: Every value quoted from a reference, by citation key and then name,
#: which Calkit writes from calkit.yaml for documents to read, so one that
#: quotes them depends on this rather than on all of calkit.yaml
VALUES_PATH = ".calkit/reference-values.json"


def get_values_data(ck_info: dict) -> dict[str, dict[str, Any]]:
    """The values documents can quote, by citation key, then name."""
    data: dict[str, dict[str, Any]] = {}
    for _, key, name, info in iter_declared_values(ck_info):
        data.setdefault(key, {})[name] = info.get("value")
    return data


def write_values_file(ck_info: dict, wdir: str | None = None) -> bool:
    """Write the values file from ``calkit.yaml``, if it declares any, and
    remove it otherwise, returning whether it's there.

    It's only rewritten when what it holds changes, so what depends on it
    isn't made out of date by rewriting it.
    """
    path = Path(wdir or ".") / VALUES_PATH
    data = get_values_data(ck_info)
    if not data:
        if path.is_file():
            path.unlink()
        return False
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    text += "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return True


@dataclass
class Use:
    """A document quoting a value from a reference, on a 1-based line, or a
    line of a notebook's Markdown and raw cells.
    """

    document: str
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


def find_uses(documents: list[str], wdir: str | None = None) -> list[Use]:
    """Every ``ckrefval`` in the documents, in LaTeX, Quarto, or Markdown,
    with project-relative paths.
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
            for n, line in enumerate(read_markdown_lines(full), start=1):
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
                    uses.append(Use(document, n, got["source"], got["key"]))
            continue
        for line in flatten(full):
            for m in _CK_REFVAL_RE.finditer(_strip_comments(line.text)):
                key, name = m.group("first").strip(), m.group("second").strip()
                if "#" in key + name:
                    continue
                rel = os.path.relpath(line.path, base).replace(os.sep, "/")
                uses.append(Use(rel, line.lineno, key, name))
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
    """The citation keys a document cites in its text, not counting
    ``\\\\nocite``, or a Quarto cross-reference.
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
    text = _MD_SKIP_RE.sub(" ", "\n".join(read_markdown_lines(full)))
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
) -> dict[str, list[dict]]:
    """Check the values a project quotes from references.

    Returns ``problems``, each with the ``file`` and ``line`` it's about,
    the ``key`` and ``name``, and the ``problem``, and ``unchecked``, the
    values whose reference has no PDF to check them against.
    """
    from calkit.references import (
        get_declared_collection_paths,
        load_collections,
    )

    read = read or cached_pages()
    base = wdir or "."
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
    collections = {
        c["path"]: c
        for c in ck_info.get("references") or []
        if isinstance(c, dict) and c.get("path")
    }
    by_value: dict[tuple[str, str], list[str]] = {}
    for path, key, name, info in declared:
        by_value.setdefault((key, name), []).append(path)
        if path in loaded and key not in loaded[path]:
            problem(
                "calkit.yaml",
                0,
                key,
                name,
                f"{path} doesn't define {key}",
            )
            continue
        search = PdfSearch()
        source = get_pdf(
            path,
            key,
            entry=loaded.get(path, {}).get(key),
            file=get_entry_file(collections.get(path, {}), key),
            wdir=wdir,
            download=download,
            lookup=lookup,
            search=search,
        )
        if source is None:
            unchecked.append({"key": key, "name": name, "tried": search.tried})
            continue
        try:
            pages = read(source.path)
        except Exception as e:
            unchecked.append(
                {"key": key, "name": name, "tried": [f"{source.source}: {e}"]}
            )
            continue
        found = check_value(
            pages, info.get("value"), info.get("page"), info.get("quote")
        )
        if found is not None:
            problem(
                "calkit.yaml", 0, key, name, f"in {source.source}, {found}"
            )
    for use in uses:
        named = bibs.get(use.document) or []
        recorded = by_value.get((use.key, use.name), [])
        if not recorded:
            problem(
                use.document,
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
                    use.document,
                    use.line,
                    use.key,
                    use.name,
                    f"{use.key} isn't in the bibliographies it names "
                    f"({', '.join(named)})",
                )
            elif len(defining) > 1:
                first = loaded[defining[0]][use.key]
                if not all(
                    _same_entry(first, loaded[p][use.key]) for p in defining
                ):
                    problem(
                        use.document,
                        use.line,
                        use.key,
                        use.name,
                        f"{use.key} is a different entry in "
                        f"{' and '.join(defining)}",
                    )
            if recorded and not set(recorded) & set(named):
                problem(
                    use.document,
                    use.line,
                    use.key,
                    use.name,
                    f"'{use.name}' is recorded for {use.key} in "
                    f"{', '.join(recorded)}, which it doesn't use",
                )
        if len(recorded) > 1:
            problem(
                use.document,
                use.line,
                use.key,
                use.name,
                f"'{use.name}' is recorded for {use.key} in both "
                f"{' and '.join(recorded)}",
            )
        if use.key not in get_cited_keys(use.document, wdir=wdir):
            problem(
                use.document,
                use.line,
                use.key,
                use.name,
                f"it quotes {use.key} but never cites it",
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
) -> None:
    """For each typed number in a sentence citing a reference, look for it
    in the reference's PDF, adding where it was ``found``, or the keys
    ``searched`` without finding it.

    Each finding needs ``value`` and ``cited_keys``.
    """
    from calkit.references import (
        get_declared_collection_paths,
        load_collections,
    )

    read = read or cached_pages()
    paths = get_declared_collection_paths(ck_info)
    loaded = load_collections(wdir=wdir, paths=paths)
    collections = {
        c["path"]: c
        for c in ck_info.get("references") or []
        if isinstance(c, dict) and c.get("path")
    }
    pages_by_key: dict[str, tuple[str, list[str]] | None] = {}

    def get_pages(key: str) -> tuple[str, list[str]] | None:
        if key in pages_by_key:
            return pages_by_key[key]
        pages_by_key[key] = None
        for path in paths:
            if key not in loaded.get(path, {}):
                continue
            source = get_pdf(
                path,
                key,
                entry=loaded[path][key],
                file=get_entry_file(collections.get(path, {}), key),
                wdir=wdir,
                download=download,
                lookup=lookup,
            )
            if source is not None:
                try:
                    pages_by_key[key] = (source.source, read(source.path))
                except Exception:
                    pass
                break
        return pages_by_key[key]

    for finding in findings:
        found, searched = [], []
        for key in finding.get("cited_keys") or []:
            got = get_pages(key)
            if got is None:
                continue
            searched.append(key)
            for match in find_number(got[1], finding["value"]):
                found.append(
                    {
                        "key": key,
                        "page": match.page,
                        "quote": match.quote,
                        "source": got[0],
                    }
                )
        if found:
            finding["found"] = found
        elif searched:
            finding["searched"] = searched
