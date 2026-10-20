# _Calkit_: The cure for [_reproducibility anxiety_]{.highlight} in the age of AI

![Calkit system](../img/pipeline.png)

**Calkit is an open-source research project framework and platform that
keeps figures, tables, and values in articles connected to the code and data
that produced them, for fast iteration and full transparency.**

<!-- calkit values path=results/traction.json -->

## By the numbers

- **<!-- calkit value key=hub_project_owners -->37<!-- /calkit value -->**
  researchers and groups with projects on calkit.io
- **<!-- calkit value key=papers_shipped -->5<!-- /calkit value -->**
  reproducible publications shipped
- **<!-- calkit value key=releases_per_week_last_90_days -->7.3<!-- /calkit value -->**
  releases/week on average

As of <!-- calkit value key=date -->2026-10-20<!-- /calkit value -->.

## The problem

AI is making scientific output cheaper than ever to produce,
shifting the bottleneck to verification and potentially deepening
the previously unsolved reproducibility crisis,
as agents will happily generate---and maybe hallucinate---artifacts
without showing all their work.
Thus, it's now more important than ever to make it easy and intuitive
to deliver research artifacts with their entire digital paper trail,
such that evidence can be traced all the way back to its origin.

## Our approach

Many open science or reproducibility
solutions focus on embedding code in documents (literate programming)
or helping researchers share and obtain credit for
outputs like code and data after a project is done.
Calkit takes a more holistic approach,
bundling version control (including large data files),
environment management, pipelines with hashed I/O,
and provenance definition, where different stages like analysis and writing
are allowed to remain as separate contexts or modules while
information flows freely between them for fast iteration.
An optional, self-hostable web app
facilitates collaboration during the project
and sharing once it's done, like a GitHub for science.
Since everything is integrated,
every figure and number can be traced back to its origin,
making it much easier to review work done by AI agents or humans.

## A success story {.box}

> In the first conference paper I wrote back in 2022,
> I had a scare where my process of manually screenshotting MATLAB figures and uploading them to Overleaf
> almost led me to publish inconsistent results when I forgot to rerun some intermediate steps.
>
> […] Using Calkit significantly **relieved my anxiety** about inadvertently contributing to the replication crisis;
> streamlined review, collaboration, and reproduction workflows that would have been otherwise infeasible;
> and improved the usability and visibility of my work for other researchers.
> Importantly, Calkit scales to more complex projects, and I can't imagine how I would have
> kept the 87 figures and 92 numerical results in my dissertation straight without this tool.
> I also received impressive technical support, including fast and helpful responses to my questions, bug reports, and feature requests.

---[Rebecca (Becca) McCabe](https://scholar.google.com/citations?user=r3eP1gIAAAAJ&hl=en), PhD, Cornell (2026)

<!-- calkit values path=results/2027-budget.json -->

## The ask: \$<!-- calkit value key=total_rounded format="{:,.0f}" -->100,000<!-- /calkit value --> to learn what sticks

Thus far we've seen the most traction from Overleaf users
who appreciate its user friendliness but want to connect it to their analyses
to eliminate error-prone and tedious manual uploads.
In 2027 we'll take Calkit on tour, starting at Caltech and various
universities in Boston,
teaching researchers how to integrate their workflows with our
new browser extension,
hosting

<!-- calkit value key=workshops -->8<!-- /calkit value -->

workshops with

<!-- calkit value key=researchers_trained -->200<!-- /calkit value -->

researchers and help
about <!-- calkit value key=projects_supported -->60<!-- /calkit value -->
of them convert active projects.
Learnings from the workshops will be published openly and fed back
into improving Calkit.

![](../img/2027-budget.png)

::: footer
Calkit is led by its creator, Pete Bachant, with 25% of a Caltech Schmidt
Academy research software engineer and Google Cloud credits for hosting.
Learn more at [docs.calkit.org](https://docs.calkit.org) and
[calkit.io](https://calkit.io), or email [pete@calkit.org](mailto:pete@calkit.org).
:::
