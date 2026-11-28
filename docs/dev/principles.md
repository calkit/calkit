# Design principles

<!-- prettier-ignore -->
!!! note
    This document was drafted by Anthropic's Claude Code from Pete's notes.

<!-- TODO: needs human review -->

## For people, with agents as helpers

A project is a place where people do research together,
and agents are helpers in it, not its audience.
Anyone involved should be able to tap in:

- **To contribute,**
  from the tools they already use,
  e.g., a PI commenting in the browser,
  a coauthor editing in Word or Overleaf,
  or a student running a stage on a cluster,
  without needing to learn Git.
- **To get value out,**
  by following a result back until they understand it,
  reusing it with its context,
  or picking the project up for the next question.

Being able to see how results were made is there so people can understand,
steer, and judge the work.
Agents can take over drudgery and help people understand,
but judgment stays with people.
Research made by agents only for other agents would leave people out of
their own work.

## Everything travels with the project

A project's parts are coupled:
data, environments, the pipeline, outputs, the writing,
and the conversations about them.
A change to one ripples through the rest,
so they belong in the project, versioned together.

The status quo spreads them across systems that don't keep them:
environments set up by hand on one machine,
outputs left as artifacts on a CI service,
reviews in GitHub or Overleaf comments,
and analysis treated as a product separate from the writing it supports.
Each split is a place where the chain from data to paper breaks,
and each hop between systems slows iteration.

So:

- **Config lives in the project**
  and says what a machine must provide,
  rather than relying on how a machine happens to be set up.
  Only what truly differs per machine,
  e.g., where its external storage is,
  is set per machine,
  and the project says what it needs.
- **Outputs are versioned with the project**
  and pushed to durable storage,
  not left in a cache, a CI run, or someone's downloads folder.
  A cache on an external drive is fine.
  An output that only exists there isn't.
- **CI is a place to run the pipeline, not to keep its outputs.**
  Code is what makes the outputs,
  so they're parts of the same system and viewed together.
  CI services like Buildkite or GitHub Actions can run stages,
  but their outputs go back into the project,
  rather than staying as artifacts on the service,
  where they expire and are cut off from the code that made them.
- **Conversations about the work**,
  e.g., comments and issues,
  sync into the project rather than living only in a service.
- **Analysis and writing are one project**,
  so a figure in a paper leads back to the code and data that made it.

## Cohesion and modularity without fragmentation

Keeping parts together doesn't mean one tool or one service.
Parts stay modular:
they can be stored in different places, run on different machines,
and use whatever tools fit,
e.g., Git, DVC, Overleaf, or an HPC cluster.
What Calkit avoids is fragmentation,
meaning parts that can't find each other,
or that live somewhere that won't last.
Every part is reached from the project,
e.g., a file by its path in the project wherever it's stored,
and stays usable without Calkit,
e.g., as a plain DVC remote.

Separating coupled parts reduces what people see at once,
not what they have to keep in sync.
The coupling moves into people's heads and manual transfers,
which is where outputs go stale.
So focus comes from views, not distance.
Subprojects are the main way to get it:
a paper, a study, or a set of decisions can be its own subproject,
e.g., a paper as a subproject of the software it reports on,
worked on, run, and reviewed on its own,
with views and CI that only show that part,
so neither people nor agents need the whole project in mind at once.
Subprojects have to be cheap to create and use,
or people will reach for separate repos instead.

Some separations are real, though,
and those parts live in separate projects that stay connected:

- **Visibility:**
  a paper often stays private until submission while its software is public.
- **Access:**
  coauthors may edit the paper but shouldn't push to the software.
- **Lifecycle:**
  paper drafts shouldn't mix with the software's release history.

A connected project pins the other at exact commits
and imports its outputs with where they came from,
so staleness shows across projects as it does within one.

## Integration by default

People do the best they can with the tools they have.
They pick the best place for code, the best writing tool,
and the best pipeline runner,
and connecting them comes last,
so it's done by hand, if at all.
Calkit has to make integration so painless that it happens by default:

- **People keep their tools.**
  Calkit connects the code host, writing tool, and runner people already
  use, from inside them,
  e.g., the browser extension on Overleaf or the GitHub Action,
  rather than asking anyone to switch.
- **Integration is a side effect of what people already do.**
  Saving, pushing, and running record what was made and where it came
  from, with no separate step to import or promote it.
  Capturing is cheap by default,
  and what's cited, e.g., by an answer or an accepted change,
  is what's kept.
- **Extra steps are counted.**
  A feature should add no steps over working by hand,
  after a one-time setup.
  When something has to be asked,
  it's asked once, when the answer pays off.
