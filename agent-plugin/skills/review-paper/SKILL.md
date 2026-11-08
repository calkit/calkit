---
name: review-paper
description: Help peer review a manuscript in a Calkit project, checking its
  references, trying to reproduce its results with a pipeline, and drafting
  comments into a review file to paste into the journal's form. Use when the
  user invokes `/calkit:review-paper`, or asks for help reviewing a paper,
  refereeing a manuscript, or checking whether a submission's results
  reproduce.
---

# Review a paper

A review project holds the reviewer's work on someone else's manuscript:
the PDF they were sent, a reference check, any attempt to reproduce the
results, and the review itself, a Markdown file of numbered comments. The
authors' material comes in read-only, and everything the reviewer makes is
kept apart from it.

## Confidentiality comes first

A manuscript under review is confidential, and many journals and funders
forbid putting one into an AI tool. Before reading the manuscript, ask the
user whether the venue's reviewer guidelines allow it.

- If it isn't allowed, or the user doesn't know, don't read the manuscript
  or the reports made from it, e.g., the reference check's, which quotes its
  citations. Set up the project, then hand the user the commands below to
  run themselves.
- Either way, keep everything in this project. Nothing from the manuscript
  goes anywhere else: other projects, issues, test data, or anything public.
  The project stays private (`calkit new project` makes a private one
  unless given `--public`), and comments are written for the editor and
  authors, not posted anywhere.

## Division of labor

Deterministic, done by Calkit, never by hand:

- whether each reference is real and matches the record its identifier
  names: `calkit check refs`;
- running the authors' code, or a reimplementation, and recording its
  outputs: `calkit run`;
- where a comment goes in the review file and how it's numbered:
  `calkit new comment` on the PDF.

Judgment, done here and then confirmed with the user:

- whether a reproduced number or figure agrees with the paper, and within
  what tolerance;
- which findings are worth a comment, and how to word them;
- the summary and the recommendation, which belong to the reviewer. Draft
  them only if asked.

## Procedure

1. **Set up the project**, unless the user already has one:

   ```sh
   calkit new project reviews/<short-name> --title "Review of <title>"
   ```

   Put the manuscript at `paper/manuscript.pdf`, or wherever the user wants
   it. Its first comment lists it under `publications` in `calkit.yaml`, with
   its review file, `paper/review.md` beside it by default:

   ```yaml
   publications:
     - path: paper/manuscript.pdf
       kind: journal-article
       reviews:
         - path: paper/review.md
   ```

2. **Check the references:**

   ```sh
   calkit check refs paper/manuscript.pdf
   ```

   With no source to read, the check takes the reference list printed in
   the PDF. Each finding prints the entry as it was read, so the user can
   see it came from the PDF. What fails the check is decidable and worth a
   comment:

   - `doi-not-registered`: the DOI doesn't exist. Say so, and give the
     right one if the report found it.
   - `mismatch`: the DOI names a different work than the entry describes.

   `not-found` isn't evidence of anything on its own. Many venues aren't
   indexed, and the report says when it's one of them. Mention it to the
   user to check by hand, but don't put it in the review as a problem.

   To keep the report as an output, add a stage:

   ```yaml
   pipeline:
     stages:
       check-references:
         kind: references-check
         target_path: paper/manuscript.pdf
   ```

3. **Try to reproduce the results.** Look in the manuscript's data and code
   availability statement for a compendium: a repository, archive, or
   Calkit project.

   - **With one**, bring it in read-only under `authors/`, pinned to the
     version the manuscript describes, e.g., as a Git submodule at a commit
     or with `calkit import zenodo`. Never edit it. Anything needed to run
     it, e.g., an environment or a patched path, is a stage or a file in
     this project. Add stages that run the authors' code (see
     `create-pipeline` and `add-pipeline-stage`). Then add a stage that
     compares its outputs with the numbers and figures the paper reports,
     writing the comparison to a results file, e.g.,
     `results/reproduction.json`.
   - **Without one**, the missing code or data is itself a finding, and
     usually the first comment. If the data is public and a central result
     can be recomputed from the methods as written, a small reimplementation
     in a stage shows whether the description is enough to reproduce it.
     Say plainly that it's a reimplementation.

   Run with `calkit run`. Never run a script by hand and copy a number into
   a comment: a comment's evidence should be an output the pipeline made.
   Record what didn't reproduce as carefully as what did.

4. **Draft comments into the review file**, one per finding:

   ```sh
   calkit new comment paper/manuscript.pdf --page 4 --line 212 \
     --highlight "within 2%" \
     -m "Rerunning the authors' code gives 3.4% (results/reproduction.json)."
   calkit new comment paper/manuscript.pdf \
     -m "The data needed to reproduce the main results isn't available."
   ```

   `--page`, `--line` (the manuscript's printed line number, if it has
   them), and `--highlight` (text quoted from that spot) are written into
   the comment, so the authors can find it, and the VS Code PDF viewer
   shows it there. A comment without them is general. The user can also
   comment straight from the PDF in VS Code. Keep each comment to one
   point, written for the authors, with the evidence named.

5. **Hand it over.** Tell the user what was checked, what reproduced, what
   didn't, and what you left for them to judge. Point them to the review
   file to edit and paste into the journal's form.

## Related

- `create-pipeline` and `add-pipeline-stage` for the reproduction stages.
- `check-reproducibility` is the same idea for the user's own project.
