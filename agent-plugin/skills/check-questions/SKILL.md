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
whether the sentence still follows from the evidence, and whether the
question's `approach` describes what its pipeline stages actually do.

A person saying an answer holds is recorded as a review under the
question's `reviews`. A review is theirs, not yours: you read and report,
and they sign off.

## Division of labor

Deterministic, done by `calkit check questions` — never re-derive by hand:

- every evidence path exists;
- every `value` key resolves in its file, and every `{name}` placeholder in
  the prose resolves and formats;
- every clause of a conditional answer parses, names only evidence, and
  renders, including the clauses the current values don't select;
- every publication `label` still exists in the LaTeX source;
- no evidence has changed (Git history for Git-tracked outputs, `dvc.lock`
  for DVC-tracked ones) since the commit that last edited the question;
- no review is stale, i.e., neither the evidence nor the question has
  changed since the commit that added it;
- which pipeline stages are behind each question's evidence, upstream
  first, listed by `calkit check questions --verbose` and
  `calkit list questions`;
- each `value` entry reads a file a pipeline stage produces, or one
  declared with `imported_from`; anything else is an error, since a number
  nothing computes is a magic number;
- each other evidence path is produced by a pipeline stage, or declared
  with `imported_from` or `created_by`. This one is advisory: it is
  reported as `unattributed` and does not fail the check.

Judgment, done here — the check reads paths and hashes, and cannot read a
sentence:

- **does the evidence actually support the answer**, which is the reason
  this skill exists;
- **does the `approach` describe what the stages implement**;
- does the answer still follow from the evidence, given what changed;
- are numbers retyped into the prose that should be `{name}` placeholders;
- does a claim resting on a threshold use a conditional answer, with a
  threshold chosen before the value was known;
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

## Does the approach match the implementation?

`approach` is one sentence on how the question is answered. The stages it
summarizes are derived from the evidence, so they can't drift, but the
sentence can. For each question with an `approach`:

1. Get its stages from `calkit check questions --verbose --json` (the
   `stages` list) and read each one's definition in `calkit.yaml`, then the
   script, notebook, or command it runs.
2. Check that the method the sentence names is the one the code runs,
   e.g., a "discrete-event simulation" that is really a closed-form
   calculation, or "a regression on all sites" that filters half of them.
3. Check that anything the sentence states as fixed, e.g., a sample size,
   a model, a dataset, a parameter, matches the code and its inputs.
4. Check that no stage in the chain does something the sentence would lead
   a reader to rule out, e.g., an exclusion step or a different estimator.

Report mismatches with the line of code and the words they contradict, and
propose a corrected sentence. A question with an answer and no `approach`
is worth one: draft it from the stages and let the user decide.

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
   - **The claim still holds**: say so, with what you checked. Recording
     that is the user's sign-off, not yours: suggest they run
     `calkit update question <n> --review "<what they checked>"`, adding
     `--with-ai "<your model>"` if your reading informed theirs. Never add
     or refresh a review yourself unless they ask you to, and then only
     with their Git identity and that disclosure.
   - **The claim no longer holds**: draft a corrected answer, show the user
     the old and new text side by side with the values that changed, and
     only after they agree, edit `calkit.yaml`.
   - **The evidence changed because a stage is not reproducible** (same
     inputs, different output): that is a pipeline defect, not an answer
     defect. Report it as such and do not rewrite the answer to match noise.
3. For each question whose **review is stale**, the report names what
   changed since the reviewer signed off: evidence, with old and new
   values, or the question's own text. Do the reading in step 2 against
   the version they signed off on (`git show <commit>:calkit.yaml`), and
   tell the user which reviewers need to look again and at what.
4. For each **unattributed** evidence entry, ask where the file came
   from. If a stage should produce it, that is a pipeline gap worth
   reporting. If it was imported or made by hand, declare it under
   `figures`, `datasets`, or `publications` with `imported_from` or
   `created_by` so the project says so. A `value` entry with no stage is
   reported as an error rather than `unattributed`: give it a stage.
5. For each **error**, fix the reference: a missing path means the pipeline
   has not been run or pulled; a bad key or placeholder means a results
   file was restructured; a missing label means the publication was
   reorganized. Do not delete evidence to make an error go away.
6. For every question you touched, move any number in the prose that the
   evidence carries into a `{name:...}` placeholder on a `value` entry, so
   it is read from the results file rather than retyped.

7. Run the evidence-supports-the-answer and approach reviews above on every
   question in scope, `ok` ones included. A question the CLI passed is where an
   unsupported claim survives, because nothing else looks at it.

Never edit a question or add a review just to clear the check. A review
records a person having read the answer against the evidence, and one
added without that is a false statement about the project, not a tidy-up.

## Writing answers

- One claim per question, two to four sentences. Say what was found and
  what it means; leave the reasoning to the publication.
- Numbers come from `value` evidence via placeholders, formatted to the
  precision the claim needs: `{ratio:.1f}x`, `{error:.0%}`. When several
  come from one file, e.g., the outputs of one calculation, name them
  together in one `result` entry's `values`, a map of name to key.
- A `value` entry must read a file a pipeline stage writes. A placeholder
  over a results file written by hand, including one you write, is a
  retyped number with extra steps, and the check fails it. If no stage
  produces the number, add one (`/calkit:add-pipeline-stage`) instead of
  writing the file. Never declare a file `imported_from` or `created_by`
  to clear that error unless it really came from there, and never edit a
  results file to change what an answer says.
- When the claim itself depends on a value, not just the number in it,
  e.g., significant or not, which method wins, write a conditional answer
  so the wording follows the evidence on a rerun:

  ```yaml
  answer:
    if p < 0.05: "The closure cuts error by {improvement:.1f}x."
    else: "The closure does not measurably reduce error."
  evidence:
    - kind: result
      path: results/closure.json
      values:
        p: p-value
        improvement: improvement
  ```

  Conditions use the names of values, so those names must be valid Python
  identifiers. Every branch must be a
  claim the evidence would support if it held. The threshold is part of
  the claim: take it from the field's convention or the user, never pick
  it to make the current branch hold, and don't use branches to hedge a
  claim that should simply be weakened.

- Point at the publication with a `publication` evidence entry carrying
  `section` (for the reader) and `label` (for the check), instead of an
  `explanation` that restates the argument.
- Each evidence entry should be one the answer actually depends on.
  Evidence that would not change the answer if it changed is decoration.
- An open question has no `answer`; `notes` says why it is open and what
  would settle it.

## Reporting

Relay a short table: question index, status, review status, what changed,
what you did or propose. Quote values, not adjectives. If the pipeline is stale
(`calkit status`), say so first, since the evidence may be about to change
again.
