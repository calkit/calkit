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

- every evidence path exists;
- every `value` key resolves in its file, and every `{name}` placeholder in
  the prose resolves and formats;
- every publication `label` still exists in the LaTeX source;
- no evidence has changed (Git history for Git-tracked outputs, `dvc.lock`
  for DVC-tracked ones) since the commit that last edited the question;
- each evidence path is produced by a pipeline stage, or declared with
  `imported_from` or `created_by`. This one is advisory: it is reported as
  `unattributed` and does not fail the check.

Judgment, done here — the check reads paths and hashes, and cannot read a
sentence:

- **does the evidence actually support the answer**, which is the reason
  this skill exists;
- does the answer still follow from the evidence, given what changed;
- are numbers retyped into the prose that should be `{name}` placeholders;
- is the answer concise, and does it point at the publication section that
  carries the argument rather than repeating it.

## Does the evidence support the answer?

A question can pass every deterministic check and still be wrong: the
paths resolve, the numbers render, nothing has changed since — and the
sentence claims something the evidence does not show. That is the failure
this skill is for, and it is not visible to the CLI. For each answer you
review, read the evidence yourself and ask, in this order:

1. **Does the evidence say what the answer says it says?** Open each entry:
   the value at its key, the figure, the table, the publication section.
   An answer of "the closure cuts error by {improvement:.1f}x" needs the
   value behind `improvement` to be that ratio, not the two errors it was
   computed from, and not a ratio over a different pair of cases.
2. **Does it support the claim's strength?** "Reduces error" needs a
   difference; "reduces error by 40%" needs the number; "reduces error
   across the range" needs evidence across the range, not at one point.
   Weaken the sentence to what is there, or add the evidence that would
   carry it.
3. **Does it cover the claim's scope?** A claim about all cases cited
   against one case, a claim about the method cited against one dataset,
   a general statement resting on the best run: the evidence is real and
   the sentence reaches past it. Name the gap.
4. **Would the claim survive the evidence changing?** If a cited value
   moved 10%, would the sentence still be true? If yes, the number is
   decoration and the claim is vaguer than it looks. If a change of any
   size would leave it standing, the evidence is not what the answer rests
   on, and something is missing from `evidence`.
5. **Is anything load-bearing missing?** A claim resting on a comparison
   needs both sides. A claim about significance needs the test, not the
   means. If the reasoning runs through an artifact the entry does not
   name, add it or say the answer cannot be checked as written.
6. **Is the causal language earned?** "Because", "leads to", "explains"
   need more than co-movement. If the evidence is a correlation, the
   answer should say so.

Report what you found, quoting the value or naming the figure. Where the
evidence does not support the sentence, propose the sentence it does
support and let the user decide; never edit the answer to match the
evidence without showing them both.

## Procedure

1. Run `calkit check questions --json` and read the report. Questions with
   status `stale` or `error` need attention; `ok` ones pass the
   deterministic check, which says nothing about whether their evidence
   supports them, so review those too whenever the user asked for a full
   review or the answer is one the paper leans on.
2. For each **stale** question, the report names the evidence that changed
   and the commit the answer dates from. Read the rendered answer
   (`calkit list questions`) against the current evidence, and if it helps,
   the old evidence (`git show <commit>:<path>`). Decide:
   - **The claim still holds**: say so, and edit the question to record
     that you read it again. Any edit counts: the check anchors on the
     commit where the question last changed. Adding or refining `notes` is
     usually the honest edit to make, since it is where you say what you
     checked.
   - **The claim no longer holds**: draft a corrected answer, show the user
     the old and new text side by side with the values that changed, and
     only after they agree, edit `calkit.yaml`.
   - **The evidence changed because a stage is not reproducible** (same
     inputs, different output): that is a pipeline defect, not an answer
     defect. Report it as such and do not rewrite the answer to match noise.
3. For each **unattributed** evidence entry, ask where the file came
   from. If a stage should produce it, that is a pipeline gap worth
   reporting. If it was imported or made by hand, declare it under
   `figures`, `datasets`, or `publications` with `imported_from` or
   `created_by` so the project says so.
4. For each **error**, fix the reference: a missing path means the pipeline
   has not been run or pulled; a bad key or placeholder means a results
   file was restructured; a missing label means the publication was
   reorganized. Do not delete evidence to make an error go away.
5. For every question you touched, move any number in the prose that the
   evidence carries into a `{name:...}` placeholder on a `value` entry, so
   it is read from the results file rather than retyped.

6. Run the evidence-supports-the-answer review above on every question in
   scope, `ok` ones included. A question the CLI passed is where an
   unsupported claim survives, because nothing else looks at it.

Never edit a stale question just to clear the check. It is the act of
reading the answer against the evidence that the edit is meant to record,
and an edit made without doing that is a false statement about the
project, not a tidy-up.

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
