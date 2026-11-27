# Design principles

<!-- prettier-ignore -->
!!! note
    This document was drafted by Anthropic's Claude Code from Pete's notes.

<!-- TODO: needs human review -->

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
