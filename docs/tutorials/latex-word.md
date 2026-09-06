# Collaborating on a LaTeX document using Microsoft Word for feedback

Teams have a variety of tolerance for markup languages and complex
system setup.
Thus, despite its limitations for technical writing,
Microsoft Word remains an important tool.
In some projects, the lead may want to use LaTeX or some other
text-first typesetting system like Quarto,
but the rest of the team does not want to engage in that way.
They prefer a WYSIWYG experience without needing to sign up for a web
app like Overleaf (or Calkit for that matter).

However, converting from LaTeX to Word with something like Pandoc produces
a Word document that doesn't look like the final output,
and migrating the contributions back into LaTeX is a tedious manual process.
For these situations, Calkit supports a workflow where the source of
truth is LaTeX, but Word Documents can be sent out for review,
and the project lead can merge the comments and edits from the `.docx` files
back into the main project as to-do items and LaTeX changes,
respectively.

Assuming we have a LaTeX document in our Calkit project at `paper/main.tex`,
we can start a review session for it with.

```sh
calkit new review-session paper/main.tex --to docx
```

This document will need to already be set up to build in the project
pipeline.
Calkit will build the document and convert it to `.docx` format
in such a way that it looks nearly identical to the PDF
and contains special metadata markers for the eventual merge back
into LaTeX.

You'll see a `.docx` in TODO that can be emailed to your collaborators.
When they email it back marked up,
start importing them back into the LaTeX source with:

```sh
calkit latex merge-docx path/to/collaborator/file.docx
```

This will compare all of the Word document changes to the original
version sent out to the collaborators when the review session was started,
creating a patch to be applied in chunks.
Calkit will walk you through each chunk asking if you'd like to apply,
reject, comment back.
All of these decisions are recorded in `.calkit/reviews`,
which serves as somewhat of a distributed database for the process.

The marked up `.docx` files are similarly stored in the review session
for posterity and revisiting later.

This process can be done on the web as well instead of the CLI,
and all of the data is the same, so it works equally well from either
location.

## TODO

These are some design decisions we need to make:

- [ ] Fully distributed or brokered by the hub? Do we want these interactions to actually live in the repo?
- [ ] How important is it that the Word doc look like the LaTeX PDF?
- [ ] Is Word a requirement?
- [ ] Integrate git-bug now for conversations around comments?
- [ ] Can it be more stateless, i.e., do we need review sessions, or can we simply try to merge a docx back into tex source idempotently?
