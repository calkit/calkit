"""Functionality for working with Zotero.

Zotero uses OAuth 1.0a, so requests must be signed with our client key and
secret, and the flow needs three legs: fetch a temporary request token, send
the user to Zotero to approve it, then trade the approved token plus a verifier
for a permanent API key. The signing means the browser can't drive this the way
it does for our OAuth 2 providers.
"""

import html as html_lib
import json
import logging
import os
import re
from collections.abc import Iterator
from urllib.parse import parse_qsl, urlencode

import bibtexparser
import requests
from fastapi import HTTPException
from requests_oauthlib import OAuth1Session

from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://api.zotero.org"
REQUEST_TOKEN_URL = "https://www.zotero.org/oauth/request"
AUTHORIZE_URL = "https://www.zotero.org/oauth/authorize"
ACCESS_TOKEN_URL = "https://www.zotero.org/oauth/access"
# Preselect full read/write access to the user's own library, their notes, and
# every group they belong to on Zotero's approval page. The user can still dial
# any of these back before approving.
AUTHORIZE_PARAMS = dict(
    library_access="1",
    notes_access="1",
    write_access="1",
    all_groups="write",
)


def fetch_request_token(callback_uri: str) -> dict[str, str]:
    """Fetch a temporary request token to start the authorization flow."""
    session = OAuth1Session(
        client_key=settings.ZOTERO_CLIENT_KEY,
        client_secret=settings.ZOTERO_CLIENT_SECRET,
        callback_uri=callback_uri,
    )
    resp = session.post(REQUEST_TOKEN_URL, timeout=15)
    logger.info(f"Zotero request token status code: {resp.status_code}")
    # Never log response bodies from the token endpoints, since they carry
    # secrets. Log the keys that came back instead.
    if resp.status_code != 200:
        logger.error("Failed to fetch Zotero request token")
        raise HTTPException(resp.status_code, "Failed to reach Zotero")
    token = dict(parse_qsl(resp.text))
    if "oauth_token" not in token or "oauth_token_secret" not in token:
        logger.error(f"Zotero request token response keys: {sorted(token)}")
        raise HTTPException(502, "Unexpected response from Zotero")
    return token


def create_authorize_url(oauth_token: str) -> str:
    """Create the URL to send the user to in order to approve access."""
    params = AUTHORIZE_PARAMS | dict(oauth_token=oauth_token)
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def fetch_access_token(
    oauth_token: str, oauth_token_secret: str, oauth_verifier: str
) -> dict[str, str]:
    """Trade an approved request token for a permanent API key.

    Zotero returns the API key in ``oauth_token_secret``, alongside the
    ``userID`` and ``username`` of the account that approved access.
    """
    session = OAuth1Session(
        client_key=settings.ZOTERO_CLIENT_KEY,
        client_secret=settings.ZOTERO_CLIENT_SECRET,
        resource_owner_key=oauth_token,
        resource_owner_secret=oauth_token_secret,
        verifier=oauth_verifier,
    )
    resp = session.post(ACCESS_TOKEN_URL, timeout=15)
    logger.info(f"Zotero access token status code: {resp.status_code}")
    if resp.status_code != 200:
        logger.error("Failed to fetch Zotero access token")
        raise HTTPException(
            resp.status_code, "Failed to authenticate with Zotero"
        )
    token = dict(parse_qsl(resp.text))
    if "oauth_token_secret" not in token or "userID" not in token:
        logger.error(f"Zotero access token response keys: {sorted(token)}")
        raise HTTPException(502, "Unexpected response from Zotero")
    return token


# The Web API is versioned; pin it so response shapes don't shift under us.
API_VERSION = "3"
# Zotero caps a page at 100 items. We paginate to gather everything.
PAGE_LIMIT = 100
# The BibTeX field reference notes live in (Markdown, ``---``-separated).
NOTE_FIELD = "comment"


def _headers(api_key: str) -> dict[str, str]:
    return {"Zotero-API-Key": api_key, "Zotero-API-Version": API_VERSION}


def _library_prefix(library_type: str, library_id: str) -> str:
    """Build the API path prefix for a library, e.g. ``users/12345``."""
    if library_type == "user":
        return f"users/{library_id}"
    if library_type == "group":
        return f"groups/{library_id}"
    raise HTTPException(400, "library_type must be 'user' or 'group'")


def _get_paginated(url: str, api_key: str, params: dict) -> list[dict]:
    """Follow Zotero's ``Link: rel="next"`` headers, gathering all rows."""
    params = dict(params, limit=PAGE_LIMIT)
    results: list[dict] = []
    next_url: str | None = url
    while next_url is not None:
        resp = requests.get(
            next_url,
            headers=_headers(api_key),
            # Params only apply to the first request; the next URL carries its
            # own query string.
            params=params if next_url == url else None,
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"Zotero GET {url} status {resp.status_code}")
            raise HTTPException(resp.status_code, "Failed to reach Zotero")
        results.extend(resp.json())
        next_url = resp.links.get("next", {}).get("url")
    return results


def get_groups(api_key: str, user_id: str) -> list[dict]:
    """List the groups a user belongs to, each usable as a library."""
    rows = _get_paginated(
        f"{BASE_URL}/users/{user_id}/groups", api_key, params={}
    )
    groups = []
    for row in rows:
        data = row.get("data", {})
        groups.append(
            {
                "library_type": "group",
                "library_id": str(row.get("id") or data.get("id")),
                "name": data.get("name"),
            }
        )
    return groups


def get_collections(
    api_key: str, library_type: str, library_id: str
) -> list[dict]:
    """List a library's collections for the import picker."""
    prefix = _library_prefix(library_type, library_id)
    rows = _get_paginated(
        f"{BASE_URL}/{prefix}/collections", api_key, params={}
    )
    collections = []
    for row in rows:
        data = row.get("data", {})
        collections.append(
            {
                "collection_key": data.get("key"),
                "collection_name": data.get("name"),
                "parent_collection": data.get("parentCollection") or None,
            }
        )
    return collections


def search_items(
    api_key: str,
    library_type: str,
    library_id: str,
    q: str | None = None,
    collection_key: str | None = None,
) -> list[dict]:
    """Search top-level items in a library for the selection UI."""
    prefix = _library_prefix(library_type, library_id)
    if collection_key:
        url = f"{BASE_URL}/{prefix}/collections/{collection_key}/items/top"
    else:
        url = f"{BASE_URL}/{prefix}/items/top"
    params: dict = {}
    if q:
        params["q"] = q
    rows = _get_paginated(url, api_key, params=params)
    items = []
    for row in rows:
        data = row.get("data", {})
        creators = data.get("creators", [])
        first_author = None
        if creators:
            c = creators[0]
            first_author = c.get("lastName") or c.get("name")
        items.append(
            {
                "item_key": data.get("key"),
                "title": data.get("title"),
                "item_type": data.get("itemType"),
                "year": (data.get("date") or "")[:4] or None,
                "first_author": first_author,
            }
        )
    return items


def create_collection(
    api_key: str, library_type: str, library_id: str, name: str
) -> str:
    """Create a collection and return its key."""
    prefix = _library_prefix(library_type, library_id)
    resp = requests.post(
        f"{BASE_URL}/{prefix}/collections",
        headers=_headers(api_key),
        json=[{"name": name}],
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        logger.error(f"Zotero create collection status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to create collection")
    successful = resp.json().get("successful", {})
    if not successful:
        failed = resp.json().get("failed", {})
        logger.error(f"Zotero create collection failed keys: {sorted(failed)}")
        raise HTTPException(502, "Zotero did not create the collection")
    return successful["0"]["key"]


def add_items_to_collection(
    api_key: str,
    library_type: str,
    library_id: str,
    collection_key: str,
    item_keys: list[str],
) -> None:
    """Add existing items to a collection.

    Collection membership lives on each item, so we read each item's current
    version, append the collection key, and batch-write the updates. Zotero
    rejects a write whose version is stale, which guards against clobbering a
    concurrent edit.
    """
    prefix = _library_prefix(library_type, library_id)
    updates = []
    for item_key in item_keys:
        resp = requests.get(
            f"{BASE_URL}/{prefix}/items/{item_key}",
            headers=_headers(api_key),
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"Zotero get item status {resp.status_code}")
            raise HTTPException(resp.status_code, "Failed to read Zotero item")
        data = resp.json()["data"]
        collections = data.get("collections", [])
        if collection_key not in collections:
            collections = collections + [collection_key]
        updates.append(
            {
                "key": item_key,
                "version": data["version"],
                "collections": collections,
            }
        )
    if not updates:
        return
    resp = requests.post(
        f"{BASE_URL}/{prefix}/items",
        headers=_headers(api_key),
        json=updates,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        logger.error(f"Zotero add-to-collection status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to update Zotero items")
    failed = resp.json().get("failed", {})
    if failed:
        logger.error(f"Zotero add-to-collection failed keys: {sorted(failed)}")
        raise HTTPException(502, "Zotero rejected some item updates")


# Accent/symbol macros -> Unicode, mirroring the frontend display cleaner. Keys
# are the macro body after the backslash, e.g. `"o` for \"o (o-umlaut).
_LATEX_ACCENTS = {
    '"a': "ä", '"o': "ö", '"u': "ü", '"A': "Ä", '"O': "Ö", '"U': "Ü",
    "'a": "á", "'e": "é", "'i": "í", "'o": "ó", "'u": "ú", "'n": "ń",
    "'c": "ć", "`a": "à", "`e": "è", "`i": "ì", "`o": "ò", "`u": "ù",
    "^a": "â", "^e": "ê", "^i": "î", "^o": "ô", "^u": "û", "~n": "ñ",
    "~a": "ã", "~o": "õ", "c c": "ç", "c C": "Ç", "ss": "ß", "o": "ø",
    "O": "Ø", "aa": "å", "AA": "Å", "ae": "æ", "AE": "Æ",
}  # fmt: skip
# AAS journal abbreviation macros (e.g. \apjl) -> the journal name.
_JOURNAL_MACROS = {
    "aj": "Astronomical Journal",
    "araa": "Annual Review of Astronomy and Astrophysics",
    "apj": "Astrophysical Journal",
    "apjl": "Astrophysical Journal Letters",
    "apjs": "Astrophysical Journal Supplement",
    "aap": "Astronomy and Astrophysics",
    "mnras": "Monthly Notices of the Royal Astronomical Society",
    "pasp": "Publications of the Astronomical Society of the Pacific",
    "nat": "Nature",
    "science": "Science",
    "prd": "Physical Review D",
    "prl": "Physical Review Letters",
}


def latex_to_text(value: str) -> str:
    """Convert a BibTeX/LaTeX field value into plain Unicode text.

    Zotero stores plain text, so pushing LaTeX (protective braces like ``{2D}``,
    accent macros) makes it store the markup literally and re-escape it on
    export, which compounds into stray backslashes on every sync. This mirrors
    the frontend's display cleaner so what we send matches what we show.
    """
    s = value
    s = re.sub(r"\\href\{([^{}]*)\}\{([^{}]*)\}", r"\2", s)
    s = re.sub(r"\\url\{([^{}]*)\}", r"\1", s)
    for macro, repl in _LATEX_ACCENTS.items():
        body = re.escape(macro)
        boundary = r"(?![a-zA-Z])" if macro[:1].isalpha() else ""
        s = re.sub(r"\{\\" + body + r"\}|\\" + body + boundary, repl, s)
        s = re.sub(r"\\" + body + r"\{\}", repl, s)
    s = re.sub(
        r"\\(?:textbf|textit|textsc|emph|texttt|mathrm|mathit|text)"
        r"\{([^{}]*)\}",
        r"\1",
        s,
    )
    for macro, name in _JOURNAL_MACROS.items():
        s = re.sub(r"\\" + macro + r"(?![a-zA-Z])", name, s)
    # A literal backslash however it's encoded (Zotero exports \textbackslash).
    s = re.sub(r"\\textbackslash\s*(?:\{\})?", "\\\\", s)
    # Escaped punctuation, braces first so an escaped protective brace
    # (\{2D\}, from a Zotero round-trip) collapses cleanly.
    s = re.sub(r"\\([&%_#${}])", r"\1", s)
    s = re.sub(r"\\[,;: ]", " ", s)
    s = re.sub(r"\\[a-zA-Z]+ ?", "", s)
    s = s.replace("---", "—").replace("--", "–").replace("~", " ")
    s = re.sub(r"[{}]", "", s)
    return re.sub(r"\s+", " ", s).strip()


# BibTeX entry types mapped onto Zotero item types (the Web API creates items
# by JSON, not BibTeX). Unknown types fall back to a generic document.
_BIBTEX_TO_ZOTERO_TYPE = {
    "article": "journalArticle",
    "book": "book",
    "booklet": "book",
    "inbook": "bookSection",
    "incollection": "bookSection",
    "inproceedings": "conferencePaper",
    "conference": "conferencePaper",
    "proceedings": "conferencePaper",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "thesis": "thesis",
    "techreport": "report",
    "report": "report",
    "manual": "report",
    "unpublished": "manuscript",
    "online": "webpage",
    "electronic": "webpage",
    "misc": "document",
}
# BibTeX field -> candidate Zotero field names; the first one valid for the
# resolved item type wins. Fields absent from the type's template are dropped.
_BIBTEX_TO_ZOTERO_FIELD = {
    "title": ["title"],
    "journal": ["publicationTitle"],
    "booktitle": ["proceedingsTitle", "bookTitle", "publicationTitle"],
    "publisher": ["publisher"],
    "school": ["university", "publisher"],
    "institution": ["institution", "publisher"],
    "volume": ["volume"],
    "number": ["issue", "number", "seriesNumber", "reportNumber"],
    "pages": ["pages"],
    "doi": ["DOI"],
    "url": ["url"],
    "urldate": ["accessDate"],
    "abstract": ["abstractNote"],
    "isbn": ["ISBN"],
    "issn": ["ISSN"],
    "edition": ["edition"],
    "series": ["series"],
    "address": ["place"],
    "language": ["language"],
}


def _parse_creator(name: str, creator_type: str) -> dict:
    """Parse one BibTeX author/editor name into a Zotero creator object."""
    name = latex_to_text(name.strip())
    if "," in name:
        last, first = (p.strip() for p in name.split(",", 1))
        return {
            "creatorType": creator_type,
            "firstName": first,
            "lastName": last,
        }
    parts = name.split()
    if len(parts) < 2:
        # A single token (e.g. an organization) can't be split into first/last.
        return {"creatorType": creator_type, "name": name}
    return {
        "creatorType": creator_type,
        "firstName": " ".join(parts[:-1]),
        "lastName": parts[-1],
    }


def _bibtex_creators(fields: dict, valid_types: set[str]) -> list[dict]:
    """Build Zotero creators from a BibTeX entry's author/editor fields."""
    creators: list[dict] = []
    for role in ("author", "editor"):
        raw = (fields.get(role) or "").strip()
        if not raw:
            continue
        ctype = role if role in valid_types else next(iter(valid_types))
        for name in re.split(r"\s+and\s+", raw):
            if name.strip():
                creators.append(_parse_creator(name, ctype))
    return creators


def _item_template(api_key: str, item_type: str) -> dict:
    """Fetch a blank Zotero item template listing an item type's valid fields."""
    resp = requests.get(
        f"{BASE_URL}/items/new",
        headers=_headers(api_key),
        params={"itemType": item_type},
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error(f"Zotero item template status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to reach Zotero")
    return resp.json()


def _apply_bibtex_fields(item: dict, template: dict, fields: dict) -> None:
    """Map BibTeX-style ``fields`` onto a Zotero ``item`` in place.

    Only fields valid for the item type (present in ``template``) are set;
    creators come from author/editor and the date from year/month. Creators and
    date are only touched when their source fields are provided, so a partial
    update (e.g. an edit that changed only the year) doesn't wipe the authors.
    """
    if "author" in fields or "editor" in fields:
        valid_creator_types = {
            c.get("creatorType") for c in template.get("creators", [])
        } or {"author"}
        item["creators"] = _bibtex_creators(fields, valid_creator_types)
    if ("year" in fields or "month" in fields) and "date" in template:
        year = (fields.get("year") or "").strip()
        month = (fields.get("month") or "").strip()
        item["date"] = f"{month} {year}".strip()
    for bib_field, value in fields.items():
        if bib_field.lower() in ("author", "editor", "year", "month"):
            continue
        # Send plain text, never LaTeX: Zotero stores the value literally and
        # re-escapes it on export, so pushing braces/macros compounds backslashes
        # on every sync.
        text = latex_to_text((value or "").strip())
        for zotero_field in _BIBTEX_TO_ZOTERO_FIELD.get(
            bib_field.lower(), [bib_field]
        ):
            if zotero_field in template:
                # An empty value clears the field.
                item[zotero_field] = text
                break


def create_item(
    api_key: str,
    library_type: str,
    library_id: str,
    item_type: str,
    fields: dict,
    collection_key: str | None = None,
) -> str:
    """Create a bibliographic item in Zotero from BibTeX-style fields.

    Maps the BibTeX entry type and fields onto Zotero's schema, sending only
    fields valid for the resolved item type (per its template), and returns the
    new item's key.
    """
    zotero_type = _BIBTEX_TO_ZOTERO_TYPE.get(item_type.lower(), "document")
    template = _item_template(api_key, zotero_type)
    item = dict(template)
    _apply_bibtex_fields(item, template, fields)
    # A new item with no author shouldn't inherit the template's placeholder
    # creator.
    if "author" not in fields and "editor" not in fields:
        item["creators"] = []
    if collection_key:
        item["collections"] = [collection_key]
    prefix = _library_prefix(library_type, library_id)
    resp = requests.post(
        f"{BASE_URL}/{prefix}/items",
        headers=_headers(api_key),
        json=[item],
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        logger.error(f"Zotero create item status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to create Zotero item")
    body = resp.json()
    successful = body.get("successful", {})
    if not successful:
        logger.error(f"Zotero create item failed: {body.get('failed')}")
        raise HTTPException(502, "Zotero did not create the item")
    return successful["0"]["key"]


def update_item(
    api_key: str,
    library_type: str,
    library_id: str,
    item_key: str,
    item_type: str,
    fields: dict,
) -> None:
    """Update an existing Zotero item's type and fields from BibTeX fields.

    Fetches the item for its current version, maps the fields onto the resolved
    item type's template, and PATCHes it (version-guarded). Fields omitted from
    the form are left untouched; an empty value clears its field.
    """
    prefix = _library_prefix(library_type, library_id)
    resp = requests.get(
        f"{BASE_URL}/{prefix}/items/{item_key}",
        headers=_headers(api_key),
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error(f"Zotero get item status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to read Zotero item")
    data = resp.json()["data"]
    version = data["version"]
    zotero_type = _BIBTEX_TO_ZOTERO_TYPE.get(
        item_type.lower(), data.get("itemType", "document")
    )
    template = _item_template(api_key, zotero_type)
    patch: dict = {}
    if zotero_type != data.get("itemType"):
        patch["itemType"] = zotero_type
    _apply_bibtex_fields(patch, template, fields)
    resp = requests.patch(
        f"{BASE_URL}/{prefix}/items/{item_key}",
        headers={
            **_headers(api_key),
            "If-Unmodified-Since-Version": str(version),
        },
        json=patch,
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        logger.error(f"Zotero update item status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to update Zotero item")


def delete_item(
    api_key: str, library_type: str, library_id: str, item_key: str
) -> None:
    """Delete an item from Zotero, tolerating an already-deleted item."""
    prefix = _library_prefix(library_type, library_id)
    resp = requests.get(
        f"{BASE_URL}/{prefix}/items/{item_key}",
        headers=_headers(api_key),
        timeout=30,
    )
    if resp.status_code == 404:
        return
    if resp.status_code != 200:
        logger.error(f"Zotero get item status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to read Zotero item")
    version = resp.json()["data"]["version"]
    resp = requests.delete(
        f"{BASE_URL}/{prefix}/items/{item_key}",
        headers={
            **_headers(api_key),
            "If-Unmodified-Since-Version": str(version),
        },
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        logger.error(f"Zotero delete item status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to delete Zotero item")


def get_collection_name(
    api_key: str, library_type: str, library_id: str, collection_key: str
) -> str:
    """Fetch a single collection's display name."""
    prefix = _library_prefix(library_type, library_id)
    resp = requests.get(
        f"{BASE_URL}/{prefix}/collections/{collection_key}",
        headers=_headers(api_key),
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error(f"Zotero get collection status {resp.status_code}")
        raise HTTPException(
            resp.status_code, "Failed to read Zotero collection"
        )
    return resp.json()["data"]["name"]


def get_collection_items(
    api_key: str,
    library_type: str,
    library_id: str,
    collection_key: str,
    since: int | None = None,
    include_children: bool = False,
) -> tuple[list[dict], int]:
    """Fetch a collection's top-level items with their BibTeX and data.

    Requesting ``format=json&include=bibtex,data`` returns, per item, its Zotero
    key alongside its rendered BibTeX entry, which is how a BibTeX citekey is
    tied back to its Zotero item (attachments, notes). With ``since`` set, only
    items modified after that library version are returned (an incremental
    pull); with ``include_children`` set, note/attachment children are included
    too (so a note-only edit, which doesn't bump its parent's version, is still
    seen). Returns ``(items, library_version)`` where each item is
    ``{item_key, bibtex, data, num_children}``.
    """
    prefix = _library_prefix(library_type, library_id)
    suffix = "items" if include_children else "items/top"
    url = f"{BASE_URL}/{prefix}/collections/{collection_key}/{suffix}"
    items: list[dict] = []
    library_version = 0
    start = 0
    while True:
        params = {
            "format": "json",
            "include": "bibtex,data",
            "limit": PAGE_LIMIT,
            "start": start,
        }
        if since is not None:
            params["since"] = since
        resp = requests.get(
            url, headers=_headers(api_key), params=params, timeout=60
        )
        if resp.status_code != 200:
            logger.error(f"Zotero items fetch status {resp.status_code}")
            raise HTTPException(resp.status_code, "Failed to read from Zotero")
        version_header = resp.headers.get("Last-Modified-Version")
        if version_header is not None:
            library_version = int(version_header)
        for row in resp.json():
            items.append(
                {
                    "item_key": row.get("key"),
                    "bibtex": (row.get("bibtex") or "").strip(),
                    "data": row.get("data") or {},
                    "num_children": (row.get("meta") or {}).get(
                        "numChildren", 0
                    ),
                }
            )
        total = int(resp.headers.get("Total-Results", 0))
        start += PAGE_LIMIT
        if start >= total:
            break
    return items, library_version


def get_deleted_item_keys(
    api_key: str, library_type: str, library_id: str, since: int
) -> list[str]:
    """List keys of items deleted from the library since a library version."""
    prefix = _library_prefix(library_type, library_id)
    resp = requests.get(
        f"{BASE_URL}/{prefix}/deleted",
        headers=_headers(api_key),
        params={"since": since},
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error(f"Zotero deleted fetch status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to read from Zotero")
    return resp.json().get("items", [])


def bib_key_of(bibtex_entry: str) -> str | None:
    """Parse the citekey from a single BibTeX entry string."""
    try:
        entries = bibtexparser.loads(bibtex_entry).entries
    except Exception:
        return None
    return entries[0]["ID"] if entries else None


def _wrap_field(key: str, value: str, width: int = 80) -> list[str]:
    """Render one BibTeX field, hard-wrapping the value at ``width`` columns."""
    opening = f"  {key} = {{"
    indent = " " * len(opening)
    lines: list[str] = []
    cur = opening
    for word in value.split():
        add = word if cur.endswith("{") else " " + word
        # Don't break a single long token (e.g. a URL); only wrap between words.
        if len(cur) + len(add) > width and cur not in (opening, indent):
            lines.append(cur)
            cur = indent + word
        else:
            cur += add
    lines.append(cur + "},")
    return lines


def format_bib(bibtex_text: str) -> str:
    """Reformat BibTeX with 2-space indentation and 80-column wrapping."""
    try:
        db = bibtexparser.loads(bibtex_text)
    except Exception as e:
        logger.warning(f"Failed to parse BibTeX for formatting: {e}")
        return bibtex_text
    blocks: list[str] = []
    for entry in db.entries:
        entry_type = entry.get("ENTRYTYPE", "misc")
        key = entry.get("ID", "")
        lines = [f"@{entry_type}{{{key},"]
        # bibtexparser reverses a source entry's field order on parse, so
        # reversing here restores it, keeping formatting idempotent instead of
        # flipping field order (and churning the diff) on every rewrite.
        fields = [f for f in entry if f not in ("ENTRYTYPE", "ID")]
        for field in reversed(fields):
            value = entry[field]
            text = str(value)
            if field == NOTE_FIELD and "\n" in text:
                # The note/comment field holds Markdown whose newlines are
                # meaningful; preserve it verbatim rather than wrapping it.
                lines.append(f"  {field} = {{{text}}},")
            else:
                # Collapse any incidental whitespace (including newlines left by
                # a previous wrap) so re-formatting is idempotent and doesn't
                # churn untouched entries.
                lines.extend(_wrap_field(field, text))
        lines.append("}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def note_text_to_html(text: str) -> str:
    """Convert plain text into the simple HTML Zotero stores for notes."""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    return "".join(
        f"<p>{html_lib.escape(p).replace(chr(10), '<br/>')}</p>"
        for p in paragraphs
    )


def note_html_to_text(html: str) -> str:
    """Convert Zotero note HTML into plain text for editing and display."""
    s = re.sub(r"<\s*br\s*/?>", "\n", html, flags=re.IGNORECASE)
    s = re.sub(r"</\s*p\s*>", "\n\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    return html_lib.unescape(s).strip()


# Reference notes are stored in this BibTeX field, one note per ``---``
# separated section (Zotero notes have no titles). A note may be anchored to a
# PDF highlight, encoded self-contained at the top of its section as an HTML
# comment carrying the anchor position plus a Markdown blockquote of the
# highlighted text:
#
#     <!-- calkit-highlight: {"boundingRect":{...},...} -->
#     > the highlighted quote
#
#     the note body
#
_HIGHLIGHT_RE = re.compile(
    r"^\s*<!--\s*calkit-highlight:\s*(?P<json>.*?)\s*-->\s*\n(?P<rest>.*)$",
    re.S,
)


def parse_notes_markdown(comment: str) -> list[dict]:
    """Parse the ``comment`` field into ``[{text, highlight}]`` notes."""
    if not comment or not comment.strip():
        return []
    notes = []
    for chunk in re.split(r"(?m)^\s*-{3,}\s*$", comment):
        if not chunk.strip():
            continue
        notes.append(_parse_note(chunk.strip()))
    return notes


def _parse_note(chunk: str) -> dict:
    match = _HIGHLIGHT_RE.match(chunk)
    if not match:
        return {"text": chunk.strip(), "highlight": None}
    try:
        position = json.loads(match.group("json"))
    except Exception:
        # Malformed anchor: keep the whole section as plain text.
        return {"text": chunk.strip(), "highlight": None}
    quote_lines = []
    body_lines = []
    for line in match.group("rest").split("\n"):
        if not body_lines and line.startswith(">"):
            quote_lines.append(line[1:].lstrip())
        elif not body_lines and not line.strip():
            continue
        else:
            body_lines.append(line)
    return {
        "text": "\n".join(body_lines).strip(),
        "highlight": {
            "position": position,
            "quote": "\n".join(quote_lines).strip(),
        },
    }


def serialize_notes_markdown(notes: list[dict]) -> str:
    """Serialize ``[{text, highlight}]`` into ``---``-separated sections."""
    parts = [p for p in (_serialize_note(n) for n in notes) if p]
    return "\n\n---\n\n".join(parts).strip()


def note_zotero_html(note: dict) -> str:
    """Render a note as HTML for Zotero: the highlighted quote (if any) as a
    blockquote, then the body. The Calkit anchor is intentionally omitted, since
    Zotero can't store it.
    """
    body = note_text_to_html(note.get("text", ""))
    highlight = note.get("highlight") or {}
    quote = (highlight.get("quote") or "").strip()
    if quote:
        return f"<blockquote>{note_text_to_html(quote)}</blockquote>{body}"
    return body


def _serialize_note(note: dict) -> str:
    text = (note.get("text") or "").strip()
    highlight = note.get("highlight")
    if not highlight:
        return text
    position = highlight.get("position")
    if not position:
        return text
    lines = [
        "<!-- calkit-highlight: "
        + json.dumps(position, separators=(",", ":"))
        + " -->"
    ]
    quote = (highlight.get("quote") or "").strip()
    if quote:
        lines.extend(f"> {line}" for line in quote.split("\n"))
    lines.append("")
    lines.append(text)
    return "\n".join(lines).strip()


def get_item_children(
    api_key: str, library_type: str, library_id: str, item_key: str
) -> list[dict]:
    """Fetch an item's child items (attachments and notes)."""
    prefix = _library_prefix(library_type, library_id)
    resp = requests.get(
        f"{BASE_URL}/{prefix}/items/{item_key}/children",
        headers=_headers(api_key),
        params={"format": "json"},
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error(f"Zotero children fetch status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to read Zotero item")
    return resp.json()


def build_item_info(
    api_key: str, library_type: str, library_id: str, it: dict
) -> tuple[dict, list[dict]]:
    """Build one item's ``(info, notes)``.

    ``info`` records the Zotero item key plus its PDF attachment and note keys;
    ``notes`` carries each note's HTML for editing. Children are only fetched
    when the item reports having any.
    """
    info = {
        "item_key": it["item_key"],
        "pdf_attachment_keys": [],
        "note_keys": [],
    }
    notes: list[dict] = []
    if it["num_children"]:
        for child in get_item_children(
            api_key, library_type, library_id, it["item_key"]
        ):
            data = child.get("data", {})
            if (
                data.get("itemType") == "attachment"
                and data.get("contentType") == "application/pdf"
            ):
                info["pdf_attachment_keys"].append(child["key"])
            elif data.get("itemType") == "note":
                info["note_keys"].append(child["key"])
                notes.append(
                    {
                        "key": child["key"],
                        "version": child.get("version"),
                        "html": data.get("note", ""),
                    }
                )
    return info, notes


def build_item_maps(
    api_key: str, library_type: str, library_id: str, items: list[dict]
) -> tuple[dict, dict]:
    """Build the citekey->item map and citekey->notes map for a collection.

    Only items reporting children are queried, so most items cost no extra
    request. ``items_map`` records the Zotero item key plus its PDF attachment
    and note keys; ``notes_map`` carries each note's HTML for editing.
    """
    items_map: dict = {}
    notes_map: dict = {}
    for it in items:
        bib_key = bib_key_of(it["bibtex"])
        if not bib_key:
            continue
        info, notes = build_item_info(api_key, library_type, library_id, it)
        if notes:
            notes_map[bib_key] = notes
        items_map[bib_key] = info
    return items_map, notes_map


def download_attachment(
    api_key: str, library_type: str, library_id: str, attachment_key: str
) -> tuple[bytes, str]:
    """Download an attachment's file, returning ``(bytes, content_type)``."""
    prefix = _library_prefix(library_type, library_id)
    resp = requests.get(
        f"{BASE_URL}/{prefix}/items/{attachment_key}/file",
        headers=_headers(api_key),
        timeout=120,
        allow_redirects=True,
    )
    if resp.status_code != 200:
        logger.error(f"Zotero attachment download status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to download attachment")
    content_type = resp.headers.get("Content-Type", "application/octet-stream")
    return resp.content, content_type


def stream_attachment(
    api_key: str,
    library_type: str,
    library_id: str,
    attachment_key: str,
    chunk_size: int = 65536,
) -> tuple[Iterator[bytes], str, str | None]:
    """Stream an attachment's file, yielding ``(chunks, content_type, length)``.

    The upstream response is streamed rather than read into memory, so a large
    PDF isn't fully buffered on the server before reaching the client. ``length``
    is the upstream ``Content-Length`` when known, else ``None``.
    """
    prefix = _library_prefix(library_type, library_id)
    resp = requests.get(
        f"{BASE_URL}/{prefix}/items/{attachment_key}/file",
        headers=_headers(api_key),
        timeout=120,
        allow_redirects=True,
        stream=True,
    )
    if resp.status_code != 200:
        resp.close()
        logger.error(f"Zotero attachment download status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to download attachment")
    content_type = resp.headers.get("Content-Type", "application/octet-stream")
    content_length = resp.headers.get("Content-Length")

    def iterator() -> Iterator[bytes]:
        with resp:
            yield from resp.iter_content(chunk_size=chunk_size)

    return iterator(), content_type, content_length


def create_note(
    api_key: str,
    library_type: str,
    library_id: str,
    parent_item_key: str,
    html: str,
) -> dict:
    """Create a note child item under ``parent_item_key``."""
    prefix = _library_prefix(library_type, library_id)
    resp = requests.post(
        f"{BASE_URL}/{prefix}/items",
        headers=_headers(api_key),
        json=[
            {"itemType": "note", "parentItem": parent_item_key, "note": html}
        ],
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        logger.error(f"Zotero create note status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to create Zotero note")
    successful = resp.json().get("successful", {})
    if not successful:
        raise HTTPException(502, "Zotero did not create the note")
    created = successful["0"]
    return {"key": created["key"], "version": created["version"]}


def update_note(
    api_key: str,
    library_type: str,
    library_id: str,
    note_key: str,
    version: int,
    html: str,
) -> None:
    """Update a note's HTML, guarding against a stale version."""
    prefix = _library_prefix(library_type, library_id)
    resp = requests.patch(
        f"{BASE_URL}/{prefix}/items/{note_key}",
        headers={
            **_headers(api_key),
            "If-Unmodified-Since-Version": str(version),
        },
        json={"note": html},
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        logger.error(f"Zotero update note status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to update Zotero note")


def delete_note(
    api_key: str,
    library_type: str,
    library_id: str,
    note_key: str,
    version: int,
) -> None:
    """Delete a note child item."""
    prefix = _library_prefix(library_type, library_id)
    resp = requests.delete(
        f"{BASE_URL}/{prefix}/items/{note_key}",
        headers={
            **_headers(api_key),
            "If-Unmodified-Since-Version": str(version),
        },
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        logger.error(f"Zotero delete note status {resp.status_code}")
        raise HTTPException(resp.status_code, "Failed to delete Zotero note")


# Committed Zotero state under .calkit/zotero/ (like Overleaf's
# .calkit/overleaf/). The durable link lives in calkit.yaml; these files hold
# sync bookkeeping and cached item/note metadata and are force-added and
# committed by the import/sync routes so the state stays with the repo.
ZOTERO_DIR = os.path.join(".calkit", "zotero")
SYNC_INFO_REL_PATH = os.path.join(ZOTERO_DIR, "sync.json")
ITEMS_REL_PATH = os.path.join(ZOTERO_DIR, "items.json")
# Highlight anchors keyed by Zotero note key. Zotero can't store a Calkit PDF
# highlight anchor, so it's kept here and re-attached when a note is pulled
# back, instead of being lost each sync.
ANCHORS_REL_PATH = os.path.join(ZOTERO_DIR, "note-anchors.json")


def _read_json(working_dir: str, rel_path: str) -> dict:
    fpath = os.path.join(working_dir, rel_path)
    if not os.path.isfile(fpath):
        return {}
    try:
        with open(fpath) as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read {rel_path}: {e}")
        return {}


def _write_json(working_dir: str, rel_path: str, data: dict) -> None:
    fpath = os.path.join(working_dir, rel_path)
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, "w") as f:
        json.dump(data, f, indent=2)


def read_sync_info(working_dir: str) -> dict:
    return _read_json(working_dir, SYNC_INFO_REL_PATH)


def write_sync_info(working_dir: str, sync_info: dict) -> None:
    _write_json(working_dir, SYNC_INFO_REL_PATH, sync_info)


def read_items_info(working_dir: str) -> dict:
    return _read_json(working_dir, ITEMS_REL_PATH)


def write_items_info(working_dir: str, items_info: dict) -> None:
    _write_json(working_dir, ITEMS_REL_PATH, items_info)


def read_note_anchors(working_dir: str) -> dict:
    return _read_json(working_dir, ANCHORS_REL_PATH)


def write_note_anchors(working_dir: str, anchors: dict) -> None:
    _write_json(working_dir, ANCHORS_REL_PATH, anchors)


def zotero_notes_to_local(notes: list[dict], anchors: dict) -> list[dict]:
    """Convert Zotero note children into ``[{text, highlight}]`` local notes.

    A stored anchor (keyed by note key) is re-attached, and the leading
    blockquote that mirrors its quote is stripped so the quote isn't duplicated
    when the note is re-serialized.
    """
    result = []
    for n in notes:
        html = n.get("html", "")
        anchor = anchors.get(n.get("key"))
        if anchor:
            html = re.sub(
                r"^\s*<blockquote>.*?</blockquote>",
                "",
                html,
                count=1,
                flags=re.S | re.I,
            )
        result.append({"text": note_html_to_text(html), "highlight": anchor})
    return result
