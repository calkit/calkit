# References

Each project can contain one or more reference collections.
These are typically stored as `.bib` files,
and listed in the `references` section of the
[`calkit.yaml` file](calkit-yaml.md).

## Reading a reference

Opening a reference in the hub shows its PDF alongside its metadata and
notes, and a note can be anchored to a highlight in the PDF.

The PDF comes from whichever source has one: a Zotero attachment if the
collection is linked to Zotero, a file stored in the project, or arXiv when
the entry is a preprint with neither.
An arXiv entry is recognized from its `eprint` field, an arxiv.org URL, or a
DOI minted under arXiv's prefix, so it doesn't matter which tool wrote the
entry.
Nothing is downloaded into the project in that case; the paper is fetched
from arXiv when you open it.
