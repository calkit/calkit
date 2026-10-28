# _Calkit_: The cure for [_reproducibility anxiety_]{.highlight} in the age of AI

![Calkit system](../img/pipeline.png)

**Calkit is an open-source research project framework, toolset, and
collaboration platform that
keeps figures, tables, and values in articles connected to the code and data
that produced them, for fast iteration and full transparency.**

<!-- calkit values path=results/traction.json -->

## By the numbers

- **<!-- calkit value key=hub_project_owners -->37<!-- /calkit value -->**
  researchers and groups with projects on [calkit.io](https://calkit.io)
- **<!-- calkit value key=papers_shipped -->5<!-- /calkit value -->**
  reproducible publications shipped
- **<!-- calkit value key=releases_per_week_last_90_days -->8.0<!-- /calkit value -->**
  releases per week

as of <!-- calkit value key=date -->2026-10-27<!-- /calkit value -->

## The problem

AI is making scientific output cheaper than ever to produce,
shifting the bottleneck to verification and deepening
the still-unsolved reproducibility crisis.
LLMs will happily
generate---and possibly hallucinate---artifacts to back up conclusions
without showing all their work (code, data, environments, etc.).
It's now essential to make it easy and intuitive
to deliver research artifacts with their entire digital paper trail,
so evidence for claims can be traced all the way back to its origin.

## Our approach

Many open science or reproducibility
solutions focus on embedding code in documents (literate programming)
or helping researchers share and obtain credit for
outputs like code and data after a project is done.
Calkit takes a more integrated, modular approach.
Stages like analysis and writing can remain separate but connected,
with information flowing freely between them for fast iteration.
Version control (including large data files),
environment management, pipelines with hashed I/O,
and provenance definition are all included,
so researchers don't need to assemble bespoke systems.
An optional, self-hostable web app
facilitates collaboration during the project
and sharing once it's done, like a GitHub for science.
With the whole project "single-button reproducible,"
it becomes much easier to review work done by AI agents or humans.

## A success story {.box}

> In the first conference paper I wrote back in 2022,
> I had a scare where my process of manually screenshotting MATLAB figures and uploading them to Overleaf
> almost led me to publish inconsistent results when I forgot to rerun some intermediate steps.
>
> [\[…\]](https://docs.calkit.org/testimonials/#becca-mccabe) Using Calkit significantly **relieved my anxiety** about inadvertently contributing to the replication crisis;
> streamlined review, collaboration, and reproduction workflows that would have been otherwise infeasible;
> and improved the usability and visibility of my work for other researchers.
> Importantly, Calkit scales to more complex projects, and I can't imagine how I would have
> kept the 87 figures and 92 numerical results in my dissertation straight without this tool.
> I also received impressive technical support, including fast and helpful responses to my questions, bug reports, and feature requests.

---[Rebecca (Becca) McCabe](https://scholar.google.com/citations?user=r3eP1gIAAAAJ&hl=en), PhD, Cornell (2026)

<!-- calkit values path=results/2027-budget.json -->

## The ask: \$<!-- calkit value key=total_rounded_thousands format="{:.0f}" -->100<!-- /calkit value -->k to bring Calkit to researchers

So far we've seen the most interest from researchers
who like Overleaf's ease of use but want to connect it to their analyses
to eliminate error-prone and tedious manual uploads.
In 2027 we'll take Calkit on tour, starting at Caltech and several
universities in Boston.
In <!-- calkit value key=workshops -->8<!-- /calkit value --> workshops,
roughly <!-- calkit value key=researchers_trained -->200<!-- /calkit value -->
researchers will connect their analyses to Overleaf with our new
[browser extension](https://chromewebstore.google.com/detail/calkit/idhdomgapfolnpffanajdckdaojencal),
and we expect to provide follow-up support
for about <!-- calkit value key=projects_supported -->60<!-- /calkit value -->
of them.
What we learn will be published openly and will drive Calkit's development.

![](../img/2027-budget.png)

::: footer
Calkit is led by [Pete Bachant](https://petebachant.me),
a Senior Research Software Engineer
and instructor at Caltech's
[Schmidt Academy for Software Engineering](https://sase.caltech.edu),
which funds 25% of his time on Calkit.
Google Cloud has supported [calkit.io](https://calkit.io) with research credits.

To learn more, visit [docs.calkit.org](https://docs.calkit.org) or email [pete@calkit.org](mailto:pete@calkit.org).
:::
