# _Calkit_: The cure for reproducibility anxiety in the age of AI

![Calkit system](../img/pipeline.png)

Generative AI is making it much cheaper to produce research outputs,
shifting the bottleneck to verification and validation.
Meanwhile, the reproducibility crisis remains unsolved.
For example, the open-access publisher PLOS found
[only 12% of articles sharing code openly](https://doi.org/10.1371/journal.pone.0311493),
and even fewer share code that is quick to verify,
i.e., what's shared doesn't actually run without significant reverse
engineering.
Thus, it's now more important than
ever to make it intuitive and enjoyable for both humans and AI agents
to work transparently and reproducibly.

Rather than assuming we should simply teach scientists software development
tools and platforms and leave them to assemble their own systems and workflows,
Calkit provides a vertically integrated,
research-focused experience right out of the box: reference management, version
control (including large data files), computational environments, pipeline
automation, and a (self-hostable) collaboration platform.
Everything is totally open source with the ability to interact via web app
or command line interface (CLI),
so humans are able to work alongside AI agents and quickly verify that
both of their work is reproducible.

## A success story

[Rebecca (Becca) McCabe](https://scholar.google.com/citations?user=r3eP1gIAAAAJ&hl=en)
recently finished her PhD in Mechanical Engineering at Cornell,
developing advanced computational methods for multidisciplinary
optimization of
wave energy converters in her
[MDOcean](https://github.com/symbiotic-engineering/MDOcean),
[OpenFLASH](https://github.com/symbiotic-engineering/OpenFLASH), and
[WEC-DECIDER](https://github.com/symbiotic-engineering/WEC-DECIDER)
projects.
She used Calkit to create single-button reproducible pipelines that integrated
MATLAB, Python, Julia, LaTeX, and more.
She used Calkit's Overleaf integration
to allow collaborators to contribute without the complexity of Git,
submitting three journal articles along with her dissertation.

Read how Calkit helped Becca with her research in her own words:

> In the first conference paper I wrote back in 2022,
> I had a scare where my process of manually screenshotting MATLAB figures and uploading them to Overleaf
> almost led me to publish inconsistent results when I forgot to rerun some intermediate steps.
> To ensure the integrity of my research, I resolved to better automate my workflow,
> and spent too much time creating some clunky one-off reproducibility code that only partially addressed my needs.
> Then in 2025 I stumbled upon Calkit.
> With its structured approach, cross-language capabilities, and use of software engineering best practices,
> Calkit was more comprehensive, flexible, and future-proof than my hacky custom script, and
> I relied on it heavily for the remainder of my projects.
> Using Calkit significantly **relieved my anxiety** about inadvertently contributing to the replication crisis;
> streamlined review, collaboration, and reproduction workflows that would have been otherwise infeasible;
> and improved the usability and visibility of my work for other researchers.
> Importantly, Calkit scales to more complex projects, and I can't imagine how I would have
> kept the 87 figures and 92 numerical results in my dissertation straight without this tool.
> I also received impressive technical support, including fast and helpful responses to my questions, bug reports, and feature requests.
> I would recommend Calkit to software-savvy researchers (and even tech-traditionalist collaborators)
> who care about the accuracy and transparency of their results.

## Where we're heading

Calkit is developed and operated in a very lean and efficient manner.
Current support includes 25% of a Research Software Engineer's capacity
provided by the Schmidt Academy for Software Engineering at Caltech
and academic research credits from Google Cloud to host our instance of
the web platform.

<!-- calkit values path=results/2027-budget.json -->

With an MVP serving a handful of users,
Calkit now needs more encounters
with more diverse research problems to test and enhance its value.
We're seeking
\$<!-- calkit value key=total format="{:,.0f}" -->29,000<!-- /calkit value -->
for a six-month pilot in 2027:
\$<!-- calkit value key=by_category.fellow format="{:,.0f}" -->19,500<!-- /calkit value -->
to pay experienced Calkit users like Rebecca to run workshops around Boston
and help about <!-- calkit value key=projects_supported -->20<!-- /calkit value --> researchers
convert their own active projects,
\$<!-- calkit value key=by_category.workshops format="{:,.0f}" -->4,500<!-- /calkit value -->
for <!-- calkit value key=workshops -->4<!-- /calkit value --> workshops,
including ours at Caltech, and
\$<!-- calkit value key=by_category.hosting format="{:,.0f}" -->5,000<!-- /calkit value -->
for hosting if our cloud credits aren't renewed.
We'll measure how many get a real project running,
how many still use Calkit
three months later,
and how many papers ship with a Calkit project,
to decide what to build next.

<!-- ## Learn more -->

To learn more about Calkit, check out the docs at
[docs.calkit.org](https://docs.calkit.org), the web platform at
[calkit.io](https://calkit.io), or email Pete Bachant at
[pete@calkit.org](mailto:pete@calkit.org).
