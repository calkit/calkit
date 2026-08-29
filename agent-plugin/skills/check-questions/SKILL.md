---
name: check-questions
description: Review a Calkit project's questions and answers against their
  evidence. Use when the user invokes `/calkit:check-questions`, asks whether
  the project's answers are still true, or after a pipeline run changes
  results that answers cite.
---

# Check questions against evidence

An answer in `calkit.yaml` is a claim about what the pipeline produced when
the answer was written. The pipeline keeps the evidence current; nothing
keeps the prose current. Calkit's deterministic check catches the numbers
moving. This skill covers what a check cannot: whether the sentence still
follows from the numbers.

## Division of labor

Deterministic, done by `calkit check questions` — never re-derive by hand:

- every evidence path exists and is a pipeline output;
- every result `key` resolves in its file;
- every recorded `value` still matches the file (relative tolerance 1e-6, or
  the entry's own `tolerance`);
- every publication `label` still exists in the LaTeX source.

Judgment, done here:

- does the answer still follow from the evidence, given what changed;
- do numbers or counts retyped into the prose agree with the evidence;
- is the answer concise, and does it point at the publication section that
  carries the argument rather than repeating it.

## Procedure

1. Run `calkit check questions --json` and read the report. Questions with
   status `stale`, `error`, or `unrecorded` need attention; `ok` ones do
   not, unless the user asked for a full review.
2. For each **stale** question, read the answer, the recorded and current
   values (`recorded` and `current` on each evidence entry), and the results
   file itself if the key is an aggregate. Decide:
   - **The claim still holds** (the number moved within the sentence's
     meaning): say so, then record the new value with
     `calkit update questions -q N`.
   - **The claim no longer holds**: draft a corrected answer, show the user
     the old and new text side by side with the values that changed, and
     only after they agree, edit `calkit.yaml` and record the values.
   - **The evidence changed because a stage is not reproducible** (same
     inputs, different output): that is a pipeline defect, not an answer
     defect. Report it as such and do not rewrite the answer to match noise.
3. For each **error**, fix the reference: a missing path means the pipeline
   has not been run or pulled; a bad key means a results file was
   restructured; a missing label means the publication was reorganized.
   Do not delete evidence to make an error go away.
4. For each **unrecorded** question, check the answer against the current
   values by reading it, then record them. Do not record blindly:
   recording is the act of declaring the answer current.
5. For every question you touched, check that any number in the prose
   matches an evidence value to the precision quoted. Prefer removing the
   number from the prose and letting the evidence carry it.

Never run `calkit update questions --all` as a shortcut. It declares every
answer current, which is a claim the user has to be willing to make.

## Writing answers

- One claim per question, two to four sentences. Say what was found and
  what it means; leave the reasoning to the publication.
- Point at the publication with a `publication` evidence entry carrying
  `section` (for the reader) and `label` (for the check), instead of an
  `explanation` that restates the argument.
- Each keyed result should be one the answer actually depends on. Evidence
  that would not change the answer if it changed is decoration.
- Mark open questions with `answer: OPEN` only if the user's project uses
  that convention; otherwise leave `answer` unset so the check reports them
  as unanswered rather than as claims.

## Reporting

Relay a short table: question index, status, what changed, what you did or
propose. Quote values, not adjectives. If the pipeline is stale
(`calkit status`), say so first, since the evidence may be about to change
again.
