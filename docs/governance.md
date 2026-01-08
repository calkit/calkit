# Governance

Calkit is a free, open-source, and openly-governed project.
All [issues and ideas](https://github.com/calkit/calkit/issues)
are discussed publicly and are open to input from anyone.
Because the project is still early-stage,
the [founder](https://github.com/petebachant)
serves as the primary maintainer and decision maker.
As the number of
[contributors](https://github.com/calkit/calkit/graphs/contributors) grows,
maintainers will be added to share review and release duties.
The contributor's guide can be found
[here](https://github.com/calkit/calkit/blob/main/CONTRIBUTING.md)
and our code of conduct can be found
[here](https://github.com/calkit/calkit/blob/main/CODE_OF_CONDUCT.md).

## Vision

We envision a future where nearly every research article is delivered as part
of a [single-button](https://petebachant.me/single-button/)
reproducible
[compendium](https://book.the-turing-way.org/reproducible-research/compendia/)
(or ["repro pack"](https://lorenabarba.com/blog/how-repro-packs-can-save-your-future-self/)).
That is, all primary artifacts like source code and raw data are available,
and all secondary artifacts like figures and article PDFs
can be produced with a single command.

We believe that this will increase the pace of collective knowledge creation
by enabling faster:

1. **Discovery of errors.**
   Computational methods will be fully described and auditable.
2. **Replication.**
   Studies can be replicated by simply replacing the raw input data and
   rerunning the pipeline.
3. **Extension.**
   Innovation in science largely occurs at the level of
   hypotheses and conceptual models,
   not in mundane pipeline construction and execution.
   There is also a network effect as more types of single-button projects are
   published,
   making it easier to find something similar to a desired workflow to start
   from and adapt to new questions.

### The status quo

The figure below from the PLOS Open Science Indicators dataset
shows how far away we are from our target.
Code sharing rates are only ~10%,
and of what is shared, it's reasonable to assume
[only ~10% of that code will even run](https://doi.org/10.1093/bib/bbad375),
never mind be included in a complete, automated pipeline.

![Code sharing rates from PLOS OSI 2024.](img/plos-osi-code-2024-03.png){ style="max-width: 500px; width: auto; height: auto;" }
/// caption
Code sharing rates from
[PLOS Open Science Indicators](https://theplosblog.plos.org/2024/03/six-years-of-open-science-indicators-data/).
///

## Strategy

We believe one major hurdle preventing researchers from working reproducibly is
the expectation that they become software engineering experts,
choose and integrate multiple tools,
and assemble a custom workflow.
We want to provide a vertically-integrated, purpose-built,
and user-friendly project format and toolset that reduces the required
expertise and decision fatigue.
That is not to say that policy, education, and support are not part of the
solution—they certainly are—but we are focused on improving
tooling and infrastructure.

- **Path of least resistance:**
  Make it faster to work in a clean,
  reproducible way than it is to work in an ad-hoc, disorganized way.
- **Intuitive tooling:**
  Simplify the "hard parts" of modern scientific computing:
  caching, version control, and environment management.
- **Bridging the gap:**
  Create a natural transition from interactive discovery (notebooks/shells)
  to automated batch pipelines.
- **Builder's pride:**
  Enable researchers to take pride in what they create so
  they will be more likely to share their projects openly.

## Objective and key results (OKRs)

### 2026-Q1

1. Objective: Empower researchers to create and share single-button
   reproducible research projects.
   1. Key result: 5 researchers (excluding direct collaborators) create and
      share single-button reproducible research projects this quarter.

## Funding and sustainability

Calkit is committed to remaining free and open source forever.
The project is sustained through a combination of:

- **Volunteer contributions** from the community.
- **Institutional support** through allocated work time.
- **Calkit Cloud** optional paid plans to help cover infrastructure costs
  for the cloud storage and compute service hosted at
  [calkit.io](https://calkit.io).

The cloud service operates on a freemium model:
a generous free tier for most users,
with paid options for those who need additional storage or compute resources.
This helps ensure the service remains available and reliable
without requiring payment for typical research projects.

All Calkit software remains MIT-licensed and can be self-hosted
and used with any compatible storage backend.
In fact, we would prefer institutions host their own instance
as part of a
[decentralized, federated network](https://github.com/calkit/calkit-cloud/issues/190).
