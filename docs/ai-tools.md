# Using AI tools with Calkit

AI coding agents — Claude Code, GitHub Copilot, Cursor, OpenAI Codex, Gemini CLI, and others — can help you build and maintain Calkit pipelines. This page explains how to give each tool the context it needs.

There are two layers of context to provide:

1. **Project instructions** — what _this project_ is doing (you write this, per project)
2. **Calkit conventions** — how Calkit works in general (Calkit installs this once, globally)

---

## Step 1 — Write project-level instructions

Create an `AGENTS.md` at your repo root that explains the project to any agent. Keep it short and focused on what's unique to your project:

```markdown
# Agent instructions

This project studies fluid dynamics in turbine blades using CFD simulations.

The pipeline:

- Runs simulations with OpenFOAM in a Docker environment (shell scripts in `scripts/`)
- Post-processes results with Python notebooks in `notebooks/`
- Compiles a LaTeX paper in `paper/`

All derived outputs must be created as pipeline stages in `calkit.yaml`
so their provenance is fully tracked. Do not run scripts manually outside
of `calkit run`.
```

For Claude Code, create a `CLAUDE.md` at the repo root with the same content (or have it point to `AGENTS.md`).

---

## Step 2 — Install Calkit conventions globally

Calkit ships a conventions document covering `calkit.yaml` structure, stage kinds, environment types, and CLI commands. Install it once after installing Calkit:

```bash
calkit update agents
```

This downloads the latest conventions from the Calkit GitHub repo and writes them to the global instructions location for each supported tool — **in your home directory, not in the project**. Run it again after upgrading Calkit to get updated instructions.

To update instructions for one tool only:

```bash
calkit update agents --tool cursor
```

Supported `--tool` values:

| Value     | File written                        |
| --------- | ----------------------------------- |
| `codex`   | `~/AGENTS.md`                       |
| `copilot` | `~/.github/copilot-instructions.md` |
| `cursor`  | `~/.cursor/rules/calkit.mdc`        |
| `gemini`  | `~/.gemini/GEMINI.md`               |
| `all`     | All of the above (default)          |

---

## Tool-specific notes

### Claude Code

Claude Code supports a plugin system that loads skills on demand. Install the Calkit plugin once:

```
/plugin marketplace add calkit/calkit/agent-plugin
/plugin install calkit@calkit
```

This gives you two action skills:

- `/calkit:create-pipeline` — converts an ad hoc repo into a reproducible pipeline end-to-end
- `/calkit:add-pipeline-stage` — adds a single stage to an existing pipeline correctly

Calkit conventions are loaded automatically as a background reference skill whenever you work in a Calkit project.

Update after a Calkit release:

```
/plugin marketplace update
```

### GitHub Copilot

`calkit update agents --tool copilot` writes to `~/.github/copilot-instructions.md`, which Copilot loads for every repo. No per-project files needed.

### Cursor

`calkit update agents --tool cursor` writes to `~/.cursor/rules/calkit.mdc` with `alwaysApply: true`. Cursor loads this rule file in every workspace automatically.

### OpenAI Codex

`calkit update agents --tool codex` writes to `~/AGENTS.md`. Codex reads `AGENTS.md` from the project root and all parent directories up to `~`, so this covers every Calkit project on the machine.

### Gemini CLI

`calkit update agents --tool gemini` writes to `~/.gemini/GEMINI.md`. Gemini CLI loads this as global context for all projects.

### Any other agent

For agents not listed here: most support either a global instructions file or reading `AGENTS.md` from the repo. Point your tool at `~/AGENTS.md` (installed by `calkit update agents --tool codex`) or consult that tool's docs for its global instructions path.

---

## What the Calkit conventions cover

The document installed by `calkit update agents` (or loaded by the Claude Code plugin) includes:

- The `calkit.yaml` schema — all top-level sections and their purpose
- All pipeline stage kinds and their required/optional fields
- Environment types (Python, R, Julia, Docker, MATLAB, etc.) and how to declare them
- Output storage (Git vs. DVC) and when to use each
- How Calkit relates to DVC — why you should never edit `dvc.yaml` directly
- The `calkit xr` command for auto-detecting stage type, environment, and I/O
- Key CLI commands for running, checking, and committing
