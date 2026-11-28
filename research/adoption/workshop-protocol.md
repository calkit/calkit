<!-- TODO: needs human review -->

# Workshop protocol: question-driven development

Tests the first question in `../calkit.yaml`:
what would get researchers to adopt Calkit,
with reproducibility as a side effect.

## Hypotheses

- **Question-driven development (QDD)**, the hypothesis:
  like test-driven development for research,
  a person writes a question with its hypothesis and approach,
  an agent builds the pipeline and evidence that answer it,
  and the person reviews the approach, checks the outputs, and signs off.
  When inputs change, the answer goes stale and the question is open again.
- **Self-updating figures and numbers**:
  revisions without the redo.
- **Others can use your research**:
  code and results others can install and build on.
- **Cluster from a laptop**:
  running expensive steps on a cluster without leaving one's own machine.

The last three are what the first is tested against.
The session exercises only QDD and a baseline;
the interview probes all four.

## Before the session

- Each participant brings a dataset of their own
  and something they'd normally plot or compute from it.
- Their machine has Calkit, a coding agent with the Calkit plugin,
  and the dataset in a Calkit project, set up beforehand
  so setup time isn't counted.
- Ask for consent to keep the agent transcript and the project,
  or only the notes, and record which.

## Session

About 90 min per participant, in pairs or small groups with one
facilitator, who helps only when someone is stuck and records each time.

1. **Baseline** (20 min):
   ask the agent to make a figure or number they need,
   e.g., "make a plot of X against Y", with no question written first.
2. **QDD** (45 min):
   - Write one question about their data, with a hypothesis and the
     approach they'd take, in `calkit.yaml` (`calkit new question`).
   - Ask the agent to build the pipeline and evidence that answer it,
     with the answer filled in from the results.
   - Review the approach and check the outputs, then sign off,
     or say why they won't.
   - Change an input, e.g., add rows or change a parameter,
     run `calkit check questions` to see the answer go stale,
     and rerun.
3. **Interview** (15-25 min), below.

Half the participants do QDD first, so the order doesn't decide which
they prefer.

## What to record

For each participant and task:

- Time to a first answer or figure, and time in each step
- Where they got stuck: the step, what happened, how it was resolved,
  and whether the facilitator stepped in
- Enjoyment, 1-5
- Trust in the answer, 1-5, and why
- Whether they checked the outputs, and how
- Whether they signed off
- Would keep going: yes, no, or maybe, and with what
- Which of the two ways they'd use next time

Write each session to `sessions/<n>.json`, with no names,
for a stage to summarize.

## Interview

Ask the open questions before naming any hypothesis,
and note which reasons come up unprompted.

Open:

- What would make you use this again next week? What would stop you?
- What did you like least?

Question-driven development:

- Before today, how did you write down what an analysis was for?
- The last time you handed an analysis to someone else, or to an agent,
  how did you check what came back?
- What would you need to see before signing off on an answer?

Self-updating figures and numbers:

- The last time a reviewer or coauthor asked for a change,
  what did you have to redo, and how long did it take?
- The last time an expensive step changed,
  how did you decide what to rerun?
- Have you nearly submitted a stale figure or number?
  How did you catch it?

Others can use your research:

- Has anyone else tried to use your code or results? What happened?
- Who would want to install it, and what would they do with it?

Cluster from a laptop:

- Where do your expensive steps run?
  How do you move code and results between there and your machine?
- What part of that would you most like gone?

Closing:

- Of everything we talked about, which would make you keep using Calkit?
  Which would you not miss?

## Reading the results

QDD is supported if most participants prefer it to the baseline,
rate their trust in its answer higher,
and name it unprompted as a reason to keep going.
An alternative that comes up unprompted more often than QDD
is the stronger hook, whatever the ratings say.
Where people got stuck says what to fix first,
not whether the hypothesis holds.
