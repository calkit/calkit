"""Working with arXiv papers."""

import re

# An arXiv identifier, new style (2301.01234) or old (math.GT/0309136),
# either optionally carrying a version suffix.
ID_RE = re.compile(
    r"\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?",
    re.IGNORECASE,
)
# arXiv mints its DOIs under this prefix, so a bare DOI can name a preprint.
DOI_PREFIX = "10.48550/arxiv."


def is_id(value: str) -> bool:
    """Whether a string is an arXiv ID and nothing else."""
    return bool(ID_RE.fullmatch(value.strip()))


def pdf_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}"


def id_from_bib_attrs(attrs: dict) -> str | None:
    """Find the arXiv ID in a BibTeX entry's fields, if it has one.

    Which field carries it depends on who wrote the entry: arXiv's own
    export uses ``eprint``, Zotero tends to put the abs page in ``url``,
    and a publisher's entry may only carry the minted DOI. Any of the
    three identifies the same paper.

    A version suffix is kept when present -- it names the exact PDF the
    citation refers to, and arXiv serves the latest one without it.
    """
    lowered = {k.lower(): str(v) for k, v in attrs.items() if v}
    eprint_type = lowered.get("archiveprefix") or lowered.get("eprinttype")
    eprint = (lowered.get("eprint") or "").strip()
    if eprint and (not eprint_type or "arxiv" in eprint_type.lower()):
        if is_id(eprint):
            return eprint
    for field in ("url", "howpublished", "note"):
        value = lowered.get(field, "")
        lower_value = value.lower()
        if "arxiv.org" in lower_value or "arxiv:" in lower_value:
            m = ID_RE.search(value)
            if m:
                return m.group(0)
    doi = (lowered.get("doi") or "").strip().lower()
    doi = doi.removeprefix("https://doi.org/").removeprefix("doi:")
    if doi.startswith(DOI_PREFIX):
        candidate = doi[len(DOI_PREFIX) :]
        if is_id(candidate):
            return candidate
    return None
