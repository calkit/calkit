# Using AI tools with Calkit

AI coding agents —
Claude Code, GitHub Copilot, Cursor, OpenAI Codex, Gemini CLI, and others —
can help you build and maintain Calkit pipelines.
This page explains how to give each tool the context it needs.

There are two layers of context to provide:

1. **Project instructions**—what _this project_ is doing (you write this, per project)
2. **Calkit conventions**—how Calkit works in general (Calkit installs this once, globally)

## The golden rule: agents create code, the pipeline creates outputs

An AI agent working in a Calkit project
**must never produce derived artifacts directly** —
it must not save a figure, an executed notebook, a compiled PDF,
or any other computed result on its own.
All derived outputs must come from the pipeline.

The correct pattern:

1. Agent writes or modifies source code, scripts, notebooks, or `calkit.yaml`
2. Human (or a CI check) runs `calkit run`
3. The pipeline produces the derived outputs with full provenance

If an agent saves a figure by running a script in its own session and committing the result,
provenance is broken:
there is no record of the environment, the exact inputs, or the process that produced the file.
The `dvc.lock` file will not reflect it,
and `calkit status` will not know it is stale.

This mirrors the principle that applies to humans:
you do not run scripts manually and commit their outputs.
You define the stage, declare the inputs and outputs,
and let `calkit run` do the work.

The same applies to Jupyter notebooks:
an agent should not execute a notebook and commit the executed `.ipynb`.
It should ensure the notebook is defined as a `jupyter-notebook` pipeline stage
so `calkit run` executes it in the correct environment with tracked provenance.

## Step 1—Write project-level instructions

Create an `AGENTS.md` at your repo root that explains the project to any agent.
Keep it short and focused on what's unique to your project:

```markdown
# Agent instructions

This project studies fluid dynamics in turbine blades using CFD simulations.

The pipeline:

- Runs simulations with OpenFOAM in a Docker environment (shell scripts in `scripts/`)
- Post-processes results with Python notebooks in `notebooks/`
- Compiles a LaTeX paper in `paper/`

All derived outputs must be created as pipeline stages in `calkit.yaml`
so their provenance is fully tracked.
Do not run scripts manually outside of `calkit run`.
```

For Claude Code,
create a `CLAUDE.md` at the repo root with the same content
(or have it point to `AGENTS.md`).

## Step 2—Install Calkit conventions globally

Calkit ships a conventions document covering
`calkit.yaml` structure, stage kinds, environment types, and CLI commands.
Install it once after installing Calkit:

```bash
calkit update agent-skills
```

This copies bundled Calkit skills from your local Calkit installation
into a universal skills directory in your home folder:
`~/.agents/skills`.
For regular refreshes after upgrading Calkit, run:

```bash
calkit update agent-skills
```

For command details, see the
[CLI reference for `calkit update agent-skills`](cli-reference.md#subcommand-update-agent-skills).

## Tool-specific notes

### Claude Code

Claude Code supports a plugin system that loads skills on demand.
Install the Calkit plugin once:

```
/plugin marketplace add calkit/calkit/agent-plugin
/plugin install calkit@calkit
```

This gives you two action skills:

- `/calkit:create-pipeline`—converts an ad hoc repo into a reproducible pipeline end-to-end
- `/calkit:add-pipeline-stage`—adds a single stage to an existing pipeline correctly

Calkit conventions are loaded automatically as a background reference skill
whenever you work in a Calkit project.

Update after a Calkit release:

```
/plugin marketplace update
```

### OpenAI Codex (and compatible skill-based agents)

`calkit update agent-skills` copies bundled Calkit skills into
`~/.agents/skills`.

For other agents, check whether they can load skills from
`~/.agents/skills` and configure them accordingly.

## What the Calkit conventions cover

The skills installed by `calkit update agent-skills`
(or loaded by the Claude Code plugin) includes:

- The `calkit.yaml` schema—all top-level sections and their purpose
- All pipeline stage kinds and their required/optional fields
- Environment types (Python, R, Julia, Docker, MATLAB, etc.) and how to declare them
- Output storage (Git vs. DVC) and when to use each
- How Calkit relates to DVC—why you should never edit `dvc.yaml` directly
- The `calkit xr` command for auto-detecting stage type, environment, and I/O
- Key CLI commands for running, checking, and committing
