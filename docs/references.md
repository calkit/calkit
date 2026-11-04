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

## Checking that the references are real

A citation can be wrong in ways a build doesn't catch.
The key can be missing from every collection, which BibTeX mentions and a
reader of the PDF sees only as a question mark.
The entry can exist and describe a work that doesn't, which is what a
language model produces when it invents a plausible citation.
Or the entry can carry a DOI that resolves to a different work than its
title and authors name, which is the same mistake wearing a real
identifier.

`calkit check references` checks all three.
It reads citation keys from the documents the pipeline builds, and from
the files they input, since that is where a key is written and where it
has to be fixed.
Each key is resolved against the project's reference collections, and each
entry is then looked up in Crossref, OpenAlex, and arXiv, by identifier
when it has one and by title when it doesn't.
A candidate is compared on title, first author, and year.

```sh
calkit check references
```

```
paper/main.tex: 71 cited (1 not-checkable, 1 not-found, 69 verified)
  not-found: daulton2023hvkg
    cited at paper/main.tex:147
    no work with this title was found in the services checked
    the venue (Proceedings of the 40th International Conference on
    Machine Learning) is indexed thinly or not at all by these services,
    so this is as likely a coverage gap as a bad entry and needs checking
    by hand
```

Each reference ends up with one status:

| Status               | Meaning                                                 |
| -------------------- | ------------------------------------------------------- |
| `verified`           | Found, and the title, first author, and year agree      |
| `missing-from-bib`   | Cited but defined in no collection, so it can't resolve |
| `doi-not-registered` | The DOI doesn't exist in the handle system              |
| `mismatch`           | Found, but the record disagrees with the entry          |
| `not-found`          | Nothing was found, which may be a coverage gap          |
| `not-checkable`      | A URL or software citation, with nothing to look up     |

The first three of those fail the check, because each is decidable.
A key in no collection is read from the project itself.
An unregistered DOI is settled by the handle system behind `doi.org`,
which every registrar uses, so a handle it doesn't have can't be a real
identifier whether or not Crossref happens to list the work.
A mismatch carries the record it disagrees with.

`not-found` is reported but doesn't fail, because a work in a venue these
services don't index looks exactly like a work that doesn't exist.
Anything in PMLR is the common case: it registers no DOIs, so Crossref has
none of its proceedings.
When an entry names such a venue the report says so, rather than implying
the reference is bad.
For the same reason a search result that doesn't resemble the title it was
found with is discarded instead of reported: a title query always returns
its nearest neighbor, and reporting that would accuse the entry of
describing an unrelated paper.

## Checking references in the pipeline

A `references-check` stage runs the check as part of the pipeline:

```yaml
pipeline:
  stages:
    check-references:
      kind: references-check
      environment: _system
```

Its inputs are `calkit.yaml`, the documents the pipeline builds, the files
they input, and the reference collections, and its outputs are one report
per document, under `.calkit/reference-checks`.
All of that is derived when the pipeline is compiled, so nothing needs
declaring in the stage, and editing a document or a `.bib` file makes only
that document's check stale.

A report records that a work was found and where to go and see it, not
what the work is.
Repeating the title, authors, and year would only copy the collection the
check just read them from, and a copy goes stale against its original, so
each reference keeps the collection it's defined in, where it's cited, how
it was found, and which fields were compared:

```json
{
  "key": "jones1998ego",
  "cited_at": ["paper/main.tex:100"],
  "in_collections": ["paper/references.bib"],
  "status": "verified",
  "evidence": {
    "matched_by": "doi",
    "source": "crossref",
    "url": "https://doi.org/10.1023/a:1008306431147",
    "agrees_on": ["title", "first-author", "year"]
  }
}
```

A field only carries a value where the record disagrees with the entry,
under `differs`, since there the record is the finding.

A report carries no timestamp, so it's a function of the sources that
produced it and can be checked for staleness like any other output.
Answers from the services are cached under `.calkit/local`, which isn't
tracked, so a rerun needs no network.
Pass `offline: true` in the stage, or `--offline` to the command, to use
only cached answers, e.g., where the pipeline runs without a network.

<!-- prettier-ignore -->
!!! note
    The check is deliberately quiet about what it can't know.
    It will not tell you a reference is good, only that nothing it can
    reach contradicts it, and a reference it reports as not found still
    needs a person to look.
