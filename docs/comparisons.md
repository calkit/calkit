# Calkit vs. other tools

Calkit is an interface on top of a project's files.
It declares how to set up and run the project
(environments and the pipeline),
what the project claims (questions answered with evidence),
and whether those are up to date
(`calkit status` and `calkit check questions`).
Without it, that structure is usually implicit,
or described in prose, e.g., in a README.

Other tools cover parts of this:
building a document from code, running a pipeline,
managing environments, tracking experiments,
versioning data and recording its provenance,
describing a project with metadata,
or sharing and collaborating on the results.
Calkit is vertically integrated:
environments, the pipeline, data versioning, provenance, publications,
and the project's claims are declared in one place and work together,
so there's no need to build a workflow from separate components.

The project's artifacts are also front and center.
The publication, figures, and results are what other people see and use
first, and they're tightly coupled to the findings,
so Calkit keeps them in the project, versioned with the code and data
that produced them.
Many tools keep them elsewhere,
e.g., on a tracking server or in an app's data folder.

This page compares Calkit with those tools,
and with AI tools that do or evaluate research,
and explores how they fit together.

## Literate programming

[Quarto](https://quarto.org/) builds documents,
e.g., articles, websites, and books,
from files that mix prose and code.
The code runs when the document is rendered,
through Jupyter, knitr, Julia, or Observable,
and its outputs are embedded in the document.
With `freeze: auto`, a document is re-rendered only when its source changes;
changes to input data aren't tracked,
and the docs say to re-render in full when they happen.
Environments are left to the user.

Calkit has the same integrative spirit, with more modularity.
A figure doesn't have to be made inside the document:
it's made by its own pipeline stage,
and the document is built by another stage that uses it,
so the two stay connected through the pipeline,
and a change to the data reruns everything that depends on it.
A Quarto document can itself be a Calkit pipeline stage.

## Workflow and pipeline tools

These run a graph of steps and skip the ones that are up to date.
Calkit's pipeline is one of these:
it's compiled to a DVC pipeline.

| Tool                                           | Unit of work            | Environments                                         | Skips unchanged work by                    |
| ---------------------------------------------- | ----------------------- | ---------------------------------------------------- | ------------------------------------------ |
| [DVC](https://doc.dvc.org/user-guide)          | Stage in `dvc.yaml`     | Not part of the tool                                 | Hashes of inputs and outputs               |
| [Snakemake](https://snakemake.readthedocs.io)  | Rule                    | Conda or a container per rule                        | Rerun triggers, optional cache             |
| [Nextflow](https://docs.seqera.io/nextflow/)   | Process                 | A container, conda, or Spack per process             | A hash of each task (`-resume`)            |
| [targets](https://books.ropensci.org/targets/) | Target in `_targets.R`  | Not part of the tool                                 | Hashes of code, data, and upstream targets |
| [Make](https://www.gnu.org/software/make/)     | Rule                    | Not part of the tool                                 | File timestamps                            |
| [Airflow](https://airflow.apache.org/docs/)    | Task in a scheduled DAG | Virtualenv, Docker, or Kubernetes operators          | Not its purpose                            |
| [explore](https://github.com/vacoa/explore)    | MATLAB function         | Not part of the tool                                 | Memoized results, rerun when code changes  |
| Calkit                                         | Stage in `calkit.yaml`  | Many kinds per stage, e.g., uv, conda, Docker, Julia | DVC, with environment locks as inputs      |

Snakemake and Nextflow run on clusters and in the cloud without changes
to the workflow, and Nextflow has a large library of community pipelines
in [nf-core](https://nf-co.re/).
targets, from rOpenSci, is for R:
targets are R objects kept in a `_targets/` store,
and `tar_quarto()`, from the companion tarchetypes package,
renders Quarto documents as part of the pipeline.
Airflow is for workflows that run on a schedule,
rather than for reproducing a result.
explore is a MATLAB class that saves each function's outputs and reruns
only what changed; it hasn't been updated since 2020.
None of these link claims in a paper to their outputs.

### Calkit and DVC

Since Calkit's pipeline runs on DVC, it's worth saying what Calkit adds:

- Named environments, whose lock files are inputs to the stages that use
  them.
  A DVC stage is just a command.
- Kinds of stage, e.g., Python scripts, notebooks, and LaTeX documents,
  and `calkit xr`, which works out a stage's kind, environment, inputs,
  and outputs from a script.
- One file, `calkit.yaml`, that ties datasets, figures, publications,
  and references to the pipeline,
  along with the questions the project answers and the evidence for them.
- Answers whose numbers are read from pipeline outputs,
  and a check that reports evidence that's stale, missing,
  or not computed by any stage.

Some things neither does yet.
Neither records who ran a stage beyond the Git commit,
or signs that record,
and neither replays a project and reports which outputs came out
differently, with tolerances for results that aren't reproducible bit
for bit, e.g., from training on a GPU.
Calkit also doesn't record who reviewed an answer;
see [issue #1606](https://github.com/calkit/calkit/issues/1606).

### showyourwork

[showyourwork](https://show-your.work/) is the closest to Calkit.
It builds a LaTeX article from a Snakemake workflow on every push with
GitHub Actions, and it uses conda for environments.
`\script` ties a figure to the script that made it,
`\variable` inserts a file's contents, e.g., a computed number,
into the text as a workflow dependency,
and the PDF gets margin icons linking figures to their scripts.
Expensive outputs can be cached on Zenodo.
The project layout is fixed,
and as of September 2026 its docs note that the last release is over two
years old.

Calkit isn't limited to one article, layout, or kind of environment,
and its questions state claims apart from any document,
with the check reporting stale or untraceable evidence.

## Environment management

Tools like conda, uv, pixi, renv, Docker, and Julia's package manager
create environments,
and some pin them in lock files.
[conda-lock](https://conda.github.io/conda-lock/), for example,
solves an `environment.yml` for each platform and writes a lock file,
so installing from it doesn't run the solver again.
Calkit doesn't replace these tools; they plug in as kinds of environment.
What Calkit adds is making sure they're used reproducibly:

- Every environment has a lock file.
  Where the tool doesn't write one, Calkit does,
  e.g., for conda, venv, and Docker environments.
  A Docker environment's lock records the image's digest for each
  architecture, and a pulled image is checked against it.
- Before a command runs in an environment,
  `calkit xenv` checks that the environment matches its specification,
  and rebuilds it if it doesn't.
- Julia runs with the global environment left off its load path,
  so code can't use packages the project doesn't declare.
- A `system` environment can lock properties of the machine,
  e.g., the Python version.
- Lock files are inputs to the stages that use them,
  so changing an environment reruns what depends on it.

## Experiment tracking

[W&B](https://docs.wandb.ai/) and
[MLflow](https://mlflow.org/docs/latest/ml/tracking/) record runs as code
executes:
each run logs its configuration, metrics, and output files,
and a web app compares runs.
W&B's Artifacts version datasets and models as the inputs and outputs of
runs, and show the lineage between them.
W&B is hosted by W&B or self-managed, and its client library is
MIT-licensed.
MLflow keeps runs in stores you configure, and is open source under the
Apache 2.0 license.
[DVC experiments](https://doc.dvc.org/user-guide/experiment-management)
run a DVC pipeline with changed parameters,
keep each run as a hidden Git reference,
and compare them with `dvc exp show`.

These are built for exploring:
runs are logged as they happen,
and comparing them is how a result is found.
With W&B and MLflow, the logged outputs live on the tracking server
rather than in the project;
DVC keeps its experiments in the project's Git repository.
Calkit's approach is more designed.
A parameter sweep is a pipeline stage with `iterate_over`,
its outputs are versioned like any other,
and a question and hypothesis say up front what the runs are meant to
show, with the answer checked against the outputs.

## Data management and provenance

[DataLad](https://www.datalad.org/) manages data in Git repositories,
using [git-annex](https://git-annex.branchable.com/) for large files.
A dataset can nest others as subdatasets,
so a project can bring in someone else's data with `datalad clone`
and fetch only the files it needs with `datalad get`.
`datalad run` records the command that produced an output in the commit,
and `datalad rerun` runs it again.
The datalad-container extension runs commands in Singularity or Docker
images, and the metalad extension extracts metadata.
There's no declared pipeline that skips steps that are up to date.

Calkit covers the same ground with DVC:
versioned data, datasets imported from other projects with
`imported_from`, and a record of how each output was made.
The difference is that each output comes from a declared pipeline stage,
with its inputs and environment, rather than from a logged command,
so Calkit can tell when an output is out of date.

## Project metadata

### RO-Crate

[RO-Crate](https://www.researchobject.org/ro-crate/) is a specification,
at version 1.3 as of June 2026, for describing research data and what it
came from.
A crate is a directory with an `ro-crate-metadata.json` file,
JSON-LD using mostly schema.org terms,
that describes its files, the people and organizations involved,
and licenses.
The Workflow Run Crate profiles record a workflow's execution:
its inputs, outputs, and code.
RO-Crate describes and packages but doesn't run anything.
It's widely adopted,
e.g., by WorkflowHub, Galaxy, and Dataverse.

`calkit.yaml` is also project metadata,
but it's the same file Calkit runs the project from,
so the description can't drift from what the project does.
Exporting a project as an RO-Crate would make it readable by the tools
that use the format.

### ASTRA

[ASTRA](https://github.com/LightconeResearch/astra-spec),
by Lightcone Research, is a YAML format, `astra.yaml`,
for describing an analysis:
its inputs, outputs, and the decisions made along the way,
each with the options that were considered.
Findings are claims with evidence,
each citing a declared output or a DOI,
the commit that produced it,
and optionally the quoted text that supports it.
ASTRA doesn't run anything itself:
each output has a recipe, a shell command for a runner of your choice.
Its companion runner, `lightcone-cli`, stores data with git-annex and
publishes an RO-Crate.
As of September 2026 it's in early alpha.

Calkit's questions were designed to be compatible in spirit with ASTRA's
findings.
Where ASTRA leaves running to other tools,
Calkit's pipeline is part of the same file as the claims,
so a claim can be checked against whether its evidence is current.

## Archiving and sharing

[Zenodo](https://about.zenodo.org/) and
[Figshare](https://info.figshare.com/about/) publish research outputs,
e.g., data, software, and papers,
with a DOI so they can be cited.
Zenodo is operated by CERN with OpenAIRE,
and its code is open source, built on InvenioRDM.
Figshare is part of Digital Science;
its DOIs can be versioned, institutions can run branded instances of it,
and its code isn't open source.

These are for sharing artifacts once they're done.
The Calkit hub is for collaborating on them while they're being made:
it stores every version of a project's data, figures, and publications,
and it's where collaborators work on them together.
The two meet at a release:
`calkit new release` uploads the project's files to Zenodo for a DOI,
and releasing again makes a new version of the same record.

## Collaboration platforms

These are where people work together, each built for one kind of work.
[GitHub](https://github.com) is built for software development,
with issues, pull requests, and CI through GitHub Actions.
The [Hugging Face Hub](https://huggingface.co/docs/hub/index)
is built for machine learning:
its repositories hold models, datasets, and Spaces,
i.e., demo apps,
with large files stored through Xet,
and model and dataset cards describing what's in them.
[Overleaf](https://www.overleaf.com/) is built for writing:
it's a web app for editing LaTeX documents together.

The Calkit hub does the same for research.
Its unit is a research project,
and it shows what the project is made of,
e.g., its figures, publications, pipeline,
and the questions it answers,
along with whether each is up to date.
It integrates with GitHub rather than replacing it,
and serves as a DVC remote,
so a project's data and outputs are stored alongside its repository.

Overleaf is only for writing, though,
so figures and tables made by scripts elsewhere have to be uploaded by
hand whenever they change.
Calkit keeps writing integrated with analysis,
since the two are tightly coupled,
and any friction between them slows iteration and lowers quality.
A Calkit publication can be [linked to an Overleaf project](overleaf.md):
edits sync both ways,
and figures made by the pipeline are sent up to Overleaf,
so collaborators can keep writing there.

## Hosted computing environments

These are places to do the work, with compute and collaboration built in.
A Calkit project lives in its repository and runs anywhere,
including in these environments' sessions and terminals.

### Renku

[Renku](https://renkulab.io/), by the Swiss Data Science Center,
is an open source platform that connects a project's data, code,
and compute.
Data connectors mount external storage, e.g., S3,
and sessions run Jupyter, VS Code, or RStudio in a Docker image.
It's hosted at renkulab.io or self-hosted on Kubernetes.
The original Renku, with its `renku` CLI, workflow capture,
and provenance graph,
[was turned off](https://blog.renkulab.io/sunsetting-legacy/) in October
2025 in favor of Renku 2.0,
whose docs don't cover workflows or provenance.

### CoCalc

[CoCalc](https://cocalc.ai/), by SageMath, Inc.,
is an online environment for real-time collaboration on Jupyter
notebooks, LaTeX documents, and SageMath,
with terminals and a per-file revision history.
Its source is available under the Microsoft Reference Source License.
As of September 2026, cocalc.com redirects to CoCalc.ai,
a rewrite built around AI.
Pipelines, data versioning, and provenance aren't part of either version.

## Agentic research tools

These run AI agents that do research.
Calkit doesn't run agents itself;
it gives them, and the people checking their work,
a declared structure to work within.

### Claude Science

[Claude Science](https://claude.com/docs/claude-science/overview)
is a desktop app in beta, launched in June 2026,
that pairs Claude with an analysis environment on the user's computer,
aimed at the life sciences first.
Claude runs Python, R, and shell code in a sandbox,
in conda environments it manages,
and connects to scientific databases and compute clusters.
It requires a paid Claude plan, and its source isn't published.

Its record of the work is per
[artifact](https://claude.com/docs/claude-science/artifacts),
i.e., a saved figure, dataset, report, or notebook.
Each version of an artifact records the conversation around it,
a reproducible script, the log of every command that ran,
and the environment's packages and versions.
[The reviewer](https://claude.com/docs/claude-science/the-reviewer)
checks Claude's claims against that record,
e.g., a value that contradicts the file it came from,
but it doesn't re-run analyses.
Artifacts live in the app's data folder, `~/.claude-science`,
not in a repository.

Checking claims against evidence is common to both tools.
Calkit keeps that record in the project repository instead,
as a declared pipeline that anyone who clones it can rerun,
and `calkit check questions` also reports evidence whose stage is out of
date.

### OpenResearch

[OpenResearch](https://github.com/alphaXiv/OpenResearch), by alphaXiv,
is a local-first workspace that turns coding agents,
e.g., Claude Code or Codex,
into research agents that review literature, form hypotheses,
and run experiments.
A project is a tree of experiments,
each on its own Git branch,
sharing one fixed run command.
Each run uses a snapshot of its branch's commit,
and the run record keeps the command, commit, and exit code.

Environments are left to the project,
with the agent told to prefer uv with committed lock files.
There's no pipeline of stages or caching of outputs.
Agents are told to cite runs and files after claims in their replies,
but nothing checks the citations.
Run logs, reports, and figures are kept in a data directory outside the
repository.

A project's run command could be `calkit run`,
which would add declared environments, stages that are skipped when
unchanged, and versioned outputs in the repository.
In the other direction, OpenResearch's experiment trees and launching on
remote compute are things Calkit doesn't do.

## Agent evaluation

[Harbor](https://github.com/harbor-framework/harbor) is a harness for
evaluating AI agents:
it runs an agent on tasks in containers and scores each attempt with a
verifier.
[Terminal-Bench-Science](https://github.com/harbor-framework/terminal-bench-science)
is a benchmark of 70 research tasks built on it.
Harbor makes the scoring of an agent's attempt reproducible,
while Calkit makes a project's results reproducible,
so they answer different questions.

Calkit could supplement them in a few places.
The scripts a task's author uses to generate its test data and calibrate
its pass thresholds could be a Calkit pipeline,
with the numbers behind the thresholds as answers to questions.
A task could require the agent to deliver a Calkit project,
so the verifier can check that the submission's claims come from its
pipeline, and a person reviewing it has a way in.
And a benchmark's own results, e.g., comparing models,
could cite Harbor's run records as evidence.
The [example](https://github.com/calkit/calkit/tree/main/examples/harbor-tb-science)
shows the first two.
