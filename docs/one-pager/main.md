# _Calkit_: Agile, verifiable, reproducible science in the age of AI

![Calkit system](../img/pipeline.png)

Generative AI is making it much cheaper to produce research outputs,
while the reproducibility crisis remains unsolved.
For example, the open-access publisher PLOS found
[only 12% of articles sharing code openly](https://doi.org/10.1371/journal.pone.0311493),
and even fewer share code that is quick to verify.
As the bottleneck is shifting from producing outputs
to checking that those outputs are trustworthy, it's now more important than
ever to make it intuitive and enjoyable to work transparently and reproducibly,
both for humans and AI agents.

Rather than assuming we should simply teach scientists software development
tools and platforms and leave them to assemble their own systems and workflows,
Calkit provides a turnkey, vertically integrated,
research-focused experience right out of the box: reference management, version
control (including large data files), computational environments, pipeline
automation, and a (self-hostable) collaboration platform.
The extra discipline of working this way, much like a software engineer,
speeds research up rather than slowing it down, and with the learning curve
kept short, it's almost always worth switching from manual, ad hoc workflows.

Calkit is designed to help individuals work more efficiently by allowing all
stages of research—from asking questions, to data collection and analysis, to
publication—to live together in the same project, breaking down silos that slow
down iteration
(inspired by the Agile, Lean, and DevOps movements)
while allowing more inclusive collaboration, e.g., from those
who don't want to learn complex tools like Git.

A Calkit project
_includes_ the research article, not only supplements it, and is intended to be
shipped whole, providing full context and fast verifiability, by
linking all evidence for answers to research questions back to reproducible
calculations.
See
[this published article](https://doi.org/10.1088/1538-3873/ae6fef)
for an example.

<!-- calkit values path=results/research-flow.json -->

## By the numbers

- **<!-- calkit value key=goals.steps.1.correct_gain format="{:.0%}" -->20%<!-- /calkit value -->**
  more error-free findings published per year with agents alone
- **<!-- calkit value key=goals.correct_gain format="{:.0%}" -->149%<!-- /calkit value -->**
  more with agents and Calkit together

From a simulation
in Calkit's own pipeline
([view source](https://calkit.io/calkit/calkit/pipeline?stage=research-flow)).

## A success story

[Rebecca McCabe](https://scholar.google.com/citations?user=r3eP1gIAAAAJ&hl=en)
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
to allow collaborators to contribute without learning Git,
producing
TODO
journal articles and
TODO
conference papers.

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
