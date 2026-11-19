<!-- TODO: needs human review -->

# Agent plugin

One set of skills in `skills/` serves three agents:

```text
.claude-plugin/marketplace.json     # Claude Code marketplace (repo root)
.agents/plugins/marketplace.json    # Codex marketplace (repo root)
agent-plugin/
├── .claude-plugin/plugin.json      # Claude Code manifest
├── .codex-plugin/plugin.json       # Codex manifest
├── package.json, index.js          # OpenCode plugin (registers the skills)
└── skills/<skill-name>/SKILL.md
```

`calkit update agent-skills` also copies `skills/` into `~/.agents/skills`
for other agents.

When you change the skills, bump `version` in both `plugin.json` manifests
to the same value.
Claude Code and Codex only update installed plugins when it changes.

Skill frontmatter must be strict YAML, since Codex skips a skill it can't
parse, e.g., a description containing `: ` outside quotes.
