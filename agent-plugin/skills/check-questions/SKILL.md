---
name: check-questions
description: Review a Calkit project's questions and answers against their
  evidence. Use when the user invokes `/calkit:check-questions`, asks whether
  the project's answers are still true, or after a pipeline run changes
  results that answers cite.
---

# Check questions against evidence

An answer in `calkit.yaml` is a claim about the evidence as it was when the
answer was last edited. The pipeline keeps the evidence current; nothing
keeps the prose current. Calkit's deterministic check catches evidence
changing underneath an answer. This skill covers what a check cannot:
whether the sentence still follows from the evidence.

## Division of labor

Deterministic, done by `calkit check questions` — never re-derive by hand:

- every evidence path exists and is a pipeline output;
- every `value` key resolves in its file, and every `{name}` placeholder in
  the prose resolves and formats;
- every publication `label` still exists in the LaTeX source;
- no evidence has changed (Git history for Git-tracked outputs, `dvc.lock`
  for DVC-tracked ones) since the commit that last edited the question.

Judgment, done here:

- does the answer still follow from the evidence, given what changed;
- are numbers retyped into the prose that should be `{name}` placeholders;
- is the answer concise, and does it point at the publication section that
  carries the argument rather than repeating it.

## Procedure

1. Run `calkit check questions --json` and read the report. Questions with
   status `stale` or `error` need attention; `ok` ones do not, unless the
   user asked for a full review.
2. For each **stale** question, the report names the evidence that changed
   and the commit the answer dates from. Read the rendered answer
   (`calkit list questions`) against the current evidence, and if it helps,
   the old evidence (`git show <commit>:<path>`). Decide:
   - **The claim still holds**: say so, and set `reviewed` on the question
     to today's date. That edit is what marks it current.
   - **The claim no longer holds**: draft a corrected answer, show the user
     the old and new text side by side with the values that changed, and
     only after they agree, edit `calkit.yaml`.
   - **The evidence changed because a stage is not reproducible** (same
     inputs, different output): that is a pipeline defect, not an answer
     defect. Report it as such and do not rewrite the answer to match noise.
3. For each **error**, fix the reference: a missing path means the pipeline
   has not been run or pulled; a bad key or placeholder means a results
   file was restructured; a missing label means the publication was
   reorganized. Do not delete evidence to make an error go away.
4. For every question you touched, move any number in the prose that the
   evidence carries into a `{name:...}` placeholder on a `value` entry, so
   it is read from the results file rather than retyped.

Never set `reviewed` on a stale question without reading it. It is the act
of declaring the answer current, which is a claim the user has to be
willing to make.

## Writing answers

- One claim per question, two to four sentences. Say what was found and
  what it means; leave the reasoning to the publication.
- Numbers come from `value` evidence via placeholders, formatted to the
  precision the claim needs: `{ratio:.1f}x`, `{error:.0%}`.
- Point at the publication with a `publication` evidence entry carrying
  `section` (for the reader) and `label` (for the check), instead of an
  `explanation` that restates the argument.
- Each evidence entry should be one the answer actually depends on.
  Evidence that would not change the answer if it changed is decoration.
- An open question has no `answer`; `notes` says why it is open and what
  would settle it.

## Reporting

Relay a short table: question index, status, what changed, what you did or
propose. Quote values, not adjectives. If the pipeline is stale
(`calkit status`), say so first, since the evidence may be about to change
again.
