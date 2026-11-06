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

`calkit check references`, or `calkit check refs`, checks all three for
one document.
It reads citation keys from the document and the files it inputs, since
that is where a key is written and where it has to be fixed, so a PDF is
checked through the `.tex` or Markdown file a stage builds it from.
Each key is resolved against the bibliographies the document names, with
`\bibliography` or `\addbibresource`, or in a Markdown document's front
matter, or against the collections in `calkit.yaml` if it names none.
Each entry is then looked up in Crossref, DataCite, OpenAlex, and arXiv,
by identifier when it has one and by title when it doesn't.
A candidate is compared on title, first author, and year.
An identifier is trusted over a title search, so an entry whose DOI
resolves to another work is a mismatch even when a search for its title
finds the right one, which the report then points to.

```sh
calkit check refs paper/main.tex
```

```
paper/main.tex: 71 references (1 not-checkable, 1 not-found, 69 verified)
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
| `mismatch`           | Its DOI or arXiv ID names a work that disagrees         |
| `not-found`          | No matching work found, which may be a coverage gap     |
| `unchecked`          | Not looked up, since a service couldn't be reached      |
| `not-checkable`      | A URL or software citation, with nothing to look up     |

`missing-from-bib`, `doi-not-registered`, and `mismatch` fail the check,
because each is decidable.
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
For the same reason a search result only counts as the work if its
title, first author, and year all agree with the entry: a title query
always returns its nearest neighbor, and a book's other editions,
reprints, and reviews share its title, so reporting either would accuse
the entry of describing a work it doesn't.
A close title, or the same title with another year or author, is named in
the notes instead.
Only a record found by the entry's own DOI or arXiv ID can contradict it.
`unchecked` doesn't fail either, and a lookup that got no answer, e.g.,
without a network, isn't cached, so the next run asks again.

Given a `.bib` file instead, the command checks every entry in it,
whether anything cites it or not.
It only prints its report, unless given `--output` to write it to a file,
as a pipeline stage does.

### What the check can and can't catch

Studies of citations generated by language models find three kinds of
failure: works that don't exist, real works described with wrong details,
e.g., the wrong authors, year, or DOI, and real works that don't support
the claim they're cited for.

Without search, the first two dominate.
GPT-3.5 fabricated 55% of the citations it was asked for and GPT-4 18%,
and of the real works 43% and 24% had substantive errors
([Walters and Wilder, 2023](https://doi.org/10.1038/s41598-023-41032-5)).
In medical content, GPT-3.5 fabricated 47% of references and got another
46% wrong
([Bhattacharyya et al., 2023](https://doi.org/10.7759/cureus.39238)).
GPT-4o still fabricated 20% of citations for mental health reviews in
2025, a wrong DOI was the most common error among real ones, and most DOIs
attached to fabricated citations resolved to real, unrelated articles
([Linardon et al., 2025](https://doi.org/10.2196/80371)).
Of 100 fabricated citations found in papers accepted at NeurIPS 2025, 66
were invented outright and 27 mixed real details, e.g., real authors, into
an invented reference
([Ansari, 2026](https://doi.org/10.48550/arXiv.2602.05930)).
Even with search, GPT-5, Claude Sonnet 4.6, and Gemini 3 Flash produced a
fully correct BibTeX entry for only about half of the papers they were
given
([Rao and Callison-Burch, 2026](https://doi.org/10.48550/arXiv.2604.03159)).

With search or retrieval, invented sources mostly disappear and the third
kind takes over.
About a quarter of the citations generative search engines gave didn't
support the sentence they were attached to
([Liu et al., 2023](https://doi.org/10.18653/v1/2023.findings-emnlp.467)),
and 50–90% of models' answers to medical questions weren't fully
supported by the sources they cited
([Wu et al., 2025](https://doi.org/10.1038/s41467-025-58551-6)).

`calkit check references` catches the first two kinds.
It can't catch the third: a real, correctly described work that doesn't
say what it's cited for is `verified`, so whether each source supports
its claim still takes a person reading it.

## Checking references in the pipeline

A `references-check` stage runs the check as part of the pipeline,
naming the document to check:

```yaml
pipeline:
  stages:
    check-references:
      kind: references-check
      target_path: paper/main.tex
```

The target can also be a PDF, whose source is read, or a `.bib` file,
whose every entry is checked.
Its inputs are that document, the `.tex` files it inputs, and the
bibliographies it names, or `calkit.yaml` and its collections if it names
none, and its output is that document's report, by default under
`.calkit/reference-checks`, or wherever the stage's `outputs` says.
All of that is derived when the pipeline is compiled, so nothing else
needs declaring: editing `paper/main.tex`, a `.tex` file it inputs, or a
`.bib` file rechecks that document, and nothing else.
A `.tex` file another stage generates is an input even before it's first
made, so the check runs after that stage.
A project with two papers gives each one a stage, and each goes out of
date on its own.
No `environment` is needed, since the check runs where the Calkit running
the pipeline already is.

A report records that a work was found and where to go and see it, not
what the work is.
Repeating the title, authors, and year would only copy the collection the
check just read them from, and a copy goes stale against its original, so
each reference keeps the collection it's defined in, where it's cited, how
it was found, and which fields were compared:

```json
"references": {
  "jones1998ego": {
    "cited_at": ["paper/main.tex:100"],
    "collection": "paper/references.bib",
    "status": "verified",
    "evidence": {
      "matched_by": "doi",
      "source": "crossref",
      "url": "https://doi.org/10.1023/a:1008306431147",
      "agrees_on": ["title", "first-author", "year"]
    }
  }
}
```

A field only carries a value where the record disagrees with the entry,
under `differs`, since there the record is the finding.

A key defined in more than one bibliography also gets an `also_in`, since
which entry BibTeX uses then depends on the order the document names them
in.

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
