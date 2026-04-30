# Using AI tools with Calkit

AI coding agents like Claude Code, GitHub Copilot, Cursor, OpenAI Codex, Gemini
CLI, et al.,
can help you create and maintain Calkit projects.
This page explains how to give each tool additional context to be as
effective as possible.

There are two layers of context to provide:

1. **Project instructions**: What _this project_ is doing (you write this,
   per project)
2. **Calkit skills**: How Calkit works in general (Calkit installs this
   once, globally)

## The golden rule: Agents create code, the pipeline creates outputs

An AI agent working in a Calkit project should never produce derived artifacts
directly.
It must not save a figure, an executed notebook, a compiled PDF,
or any other computed result on its own.
All derived outputs must come from the
pipeline so their _provenance_ is unambiguous.
This is important because these artifacts are used as evidence to back up
results to research questions, so the process used to create that evidence
must be fully auditable and reproducible.
An agent saving a figure directly without saving the code to do so
is similar to a human doing it, i.e.,
the process is then documented as hearsay.

The correct pattern:

1. Agent writes or modifies source code, scripts, notebooks, or `calkit.yaml`
2. Human (or a CI check) runs `calkit run`
3. The pipeline produces the derived outputs with full provenance

If an agent saves a figure by running a script and committing the result,
provenance is broken: there is no record of the environment, the exact inputs,
or the process that produced the file.
The `dvc.lock` file will not reflect it
and `calkit status` will not know it is stale.

The same applies to Jupyter notebooks: An agent should not execute a notebook
and commit the result. It should ensure the notebook is defined as a
`jupyter-notebook` pipeline stage so `calkit run` executes it in the correct
environment with tracked provenance.

## Step 1: Write project-level instructions

Create an `AGENTS.md` at your repo root that explains the project to any
agent. Keep it short and focused on what is unique to your project:

```markdown
# Agent instructions

This project studies fluid dynamics in turbine blades using CFD simulations.

The pipeline:

- Runs simulations with OpenFOAM in a Docker environment (`scripts/`)
- Post-processes results with Python notebooks in `notebooks/`
- Compiles a LaTeX paper in `paper/`

All derived outputs must be created as pipeline stages in `calkit.yaml`.
Do not run scripts manually outside of `calkit run`.
```

For Claude Code, create a `CLAUDE.md` at the repo root with the same content
(or have it point to `AGENTS.md`).

## Step 2: Install Calkit skills globally

Calkit ships agent skills covering `calkit.yaml` structure, stage
kinds, environment types, and CLI commands. Install it once after installing
Calkit:

```bash
calkit update agent-skills
```

This copies skills into `~/.agents/skills`.
Run the same command again after
upgrading Calkit to pick up any updates.

For command details, see the
[CLI reference for `calkit update agent-skills`](cli-reference.md#subcommand-update-agent-skills).

## Tool-specific notes

### Claude Code

Claude Code supports a plugin system that loads skills on demand.
Install the Calkit plugin with:

```
/plugin marketplace add calkit/calkit
/plugin install calkit@calkit
```

This gives you two action skills:

- `/calkit:create-pipeline` — converts an ad hoc repo into a reproducible
  pipeline end-to-end
- `/calkit:add-pipeline-stage` — adds a single stage to an existing pipeline

Calkit conventions are loaded automatically whenever you work in a Calkit
project.

To stay current automatically, enable auto-update for the plugin:

```
/plugin auto-update calkit@calkit enable
```

Or update manually after a Calkit release:

```
/plugin marketplace update
```

### OpenAI Codex and other skill-based agents

`calkit update agent-skills` copies skills into `~/.agents/skills`.
Check whether your agent loads skills from that directory and configure
accordingly.

## What the Calkit conventions cover

The skills installed by `calkit update agent-skills` (or loaded by the Claude
Code plugin) include:

- The `calkit.yaml` schema: All top-level sections and their purpose
- All pipeline stage kinds and their required/optional fields
- Environment types (Python, R, Julia, Docker, MATLAB, etc.) and how to
  declare them
- Output storage (Git vs. DVC) and when to use each
- How Calkit relates to DVC: Why you should usually not need ton edit `dvc.
yaml` directly
- The `calkit xr` command for auto-detecting stage type, environment, and I/O
- Key CLI commands for running, checking, and committing
