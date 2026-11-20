<!-- TODO: needs human review -->

# Peer reviewing a paper

A review is a small research project of its own.
You check the paper's references,
try to reproduce its results,
and write comments for the editor and authors.
Keeping that work in a Calkit project means
the checks and reproduction attempts behind each comment are saved with it,
and the comments end up in one Markdown file,
ready to paste into the journal's review form.

The project is yours, separate from the authors' work.
Their manuscript and any code or data they provide come in as inputs,
and everything you write stays in your project.

<!-- prettier-ignore -->
!!! warning
    A manuscript under review is confidential.
    Keep the project private,
    and check the journal's reviewer guidelines before using an AI
    assistant on it: many don't allow it.

Where the guidelines allow one,
an AI assistant is useful for understanding the paper and for drudgery,
but it can't stand in for your critical reading,
which is what the editor asked you for.
Read the paper yourself first, so your first impressions are your own.
Then the assistant can explain an unfamiliar method,
find where the paper describes something,
set up and run the reproduction,
and file your comments.
Whether the methods are sound,
the conclusions follow,
and the paper should be published
is yours to decide.
The `/calkit:review-paper` skill in the
[Calkit agent plugin](../ai-tools.md) works this way.

## Creating the project

```sh
calkit new project reviews/smith-2026 --title "Review of Smith et al."
cd reviews/smith-2026
```

The project is private unless you create it with `--public`.
Save the manuscript PDF you were sent at `paper/manuscript.pdf`.

## Checking the references

```sh
calkit check refs paper/manuscript.pdf
```

Since you don't have the authors' LaTeX or Word source,
Calkit reads the reference list printed at the end of the PDF.
Each entry is looked up in Crossref, DataCite, OpenAlex, and arXiv,
by its DOI when it has one.
The report lists anything that needs attention,
along with each entry as it was read from the PDF:

- **DOI isn't registered**: the DOI doesn't exist, so it can't be right.
  If a work matching the entry was found, the report gives its DOI.
- **Mismatch**: the DOI points to a different work than the entry
  describes.
- **Not found**: no matching work was found.
  This doesn't mean the reference is wrong:
  some venues, e.g., many conference proceedings, aren't indexed.
  Check these by hand.

The first two are worth a comment in your review.

To keep the report with the project and update it when the PDF changes,
e.g., when a revised version arrives, add a stage to `calkit.yaml`:

```yaml
pipeline:
  stages:
    check-references:
      kind: references-check
      target_path: paper/manuscript.pdf
```

## Reproducing the results

Look for the paper's data and code availability statement.

If the authors provide code and data,
put them under `authors/`, at the version the paper describes,
and don't edit them.
Then add pipeline stages that run their code,
and a stage that compares its outputs with the numbers and figures
in the paper, writing the comparison to a file like
`results/reproduction.json`.
`calkit run` runs it all,
and running it again after a revision shows what changed.
See [Creating your first project](first-project.md)
for how stages and environments work.

If they don't provide code or data,
that is usually your first comment.
Where the data is public and a key result can be recomputed from the
methods as written,
a short script in a stage shows whether the description is enough to
reproduce it.

## Writing comments

In VS Code, open the PDF with **Open With... > Calkit PDF Review**.
Select text and click **Comment** to add a comment about it,
or click **General comment** for one that isn't about a particular spot.
Choose whether it's a major or minor comment as you add it.
Comments go in `paper/review.md`,
which is created beside the PDF the first time you add one,
and listed with it in `calkit.yaml`:

```yaml
publications:
  - path: paper/manuscript.pdf
    reviews:
      - path: paper/review.md
```

Each comment is a numbered item saying where it's about,
so the authors can find it:

```markdown
The paper presents ...

## Major comments

1. Page 4, line 212 ("within 2%"): Rerunning the authors' code gives 3.4%.
2. The data needed to reproduce Figure 5 isn't available.

## Minor comments

1. Page 2, line 48 ("principle"): Typo.
```

The page and quoted text come from your selection,
and the line number from the margin if the manuscript has line numbers.
Clicking a comment in the viewer shows where it is in the PDF,
and **Edit** opens it in the review file, beside the PDF.

You can also add comments from the command line:

```sh
calkit new comment paper/manuscript.pdf --section major --page 4 \
    --line 212 --highlight "within 2%" \
    -m "Rerunning the authors' code gives 3.4%."
```

Write your summary and assessment of the paper at the top,
above the comments.
Clicking the review file's name in the viewer opens it there,
beside the PDF.
Any section whose heading contains "comments" holds numbered comments,
so you can add others,
e.g., `## Comments on the figures`.

## Submitting the review

Copy the review file's text into the journal's review form.
If a revised manuscript comes back,
save it in place of the old one and run `calkit run`:
the reference check and reproduction run again on the new version.
