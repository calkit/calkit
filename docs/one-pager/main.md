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

AI makes scientific results cheap to produce, shifting the bottleneck to
verification, yet the reproducibility crisis persists:
[only 12% of articles share code](https://doi.org/10.1371/journal.pone.0311493),
and most results reach the paper through manual, disconnected steps.
We've long taken computational methods on trust, and AI makes that
unworkable.

## Our approach

AI review overload and failures to reproduce have the same solution:
every artifact, from raw data to article,
must clearly define where it came from,
and most should come from a deterministic, automated pipeline.
Calkit includes such a pipeline,
with hashed I/O, version control, environment management,
and provenance tracking all built in,
allowing different stages to be done in different tools or programming
languages, gluing everything together for single-button reproducibility.
Every figure and number traces back to the code and data that made it,
whether a person or an AI agent did the work.

Open science or reproducibility tools
typically fall into two categories:
monolithic document-based workflows (literate programming)
or platforms to help users gain credit for sharing more of their
artifacts.

Calkit has a different take on both.
It allows different stages like writing and analysis to live in
different contexts or modules,
but keeps them tied together,
with an optional platform that makes both collaboration during
and sharing after the project is complete,
like a GitHub for science.

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

Her dissertation's pipelines ran MATLAB, Python, Julia, and LaTeX with one
button, and she submitted 3 journal articles with collaborators editing in
Overleaf instead of Git.

<!-- calkit values path=results/2027-budget.json -->

## The ask: \$<!-- calkit value key=total_rounded format="{:,.0f}" -->100,000<!-- /calkit value --> to learn what sticks

For most researchers, connecting an analysis to Overleaf is still too
much work.
In 2027 we'll take Calkit on tour, starting at Caltech with our browser
extension's Overleaf sync,
in <!-- calkit value key=workshops -->8<!-- /calkit value --> workshops that
train some <!-- calkit value key=researchers_trained -->200<!-- /calkit value -->
researchers and help
about <!-- calkit value key=projects_supported -->60<!-- /calkit value -->
of them convert active projects.
Each workshop is an experiment: who connects a figure, who still uses it six
weeks later, and why.
Opt-in analytics in our tools will measure it, what we learn will drive
development between workshops, and we'll publish an open curriculum and a
report on what worked.

![](../img/2027-budget.png)

::: footer
Calkit is led by its creator, Pete Bachant, with 25% of a Caltech Schmidt
Academy research software engineer and Google Cloud credits for hosting.
Learn more at [docs.calkit.org](https://docs.calkit.org) and
[calkit.io](https://calkit.io), or email [pete@calkit.org](mailto:pete@calkit.org).
:::
