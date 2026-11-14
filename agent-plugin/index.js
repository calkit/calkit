// OpenCode plugin that registers the skills in ./skills.
//
// Claude Code and Codex read the skills directly via their plugin
// manifests. OpenCode has no manifest format, so this module adds the skills
// itself, prefixed with `calkit-` like `calkit update agent-skills` does.
// It targets the OpenCode 2 plugin API and has no dependencies, so it works
// when installed straight from Git.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SKILLS_DIR = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "skills",
);

// Parse simple `key: value` frontmatter, which is all our skills use.
// Indented lines continue the previous value.
function parseSkill(text) {
  const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!match) return { data: {}, body: text };
  const data = {};
  let key;
  for (const line of match[1].split(/\r?\n/)) {
    const field = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (field) {
      key = field[1];
      data[key] = field[2];
    } else if (key && /^\s+\S/.test(line)) {
      data[key] = `${data[key]} ${line.trim()}`.trim();
    }
  }
  for (const [k, v] of Object.entries(data)) {
    const quoted = v.match(/^(["'])(.*)\1$/);
    if (quoted) data[k] = quoted[2];
    else if (v === "true") data[k] = true;
    else if (v === "false") data[k] = false;
  }
  return { data, body: match[2] };
}

function loadSkills() {
  const skills = [];
  for (const entry of fs.readdirSync(SKILLS_DIR, { withFileTypes: true })) {
    const file = path.join(SKILLS_DIR, entry.name, "SKILL.md");
    if (!entry.isDirectory() || !fs.existsSync(file)) continue;
    const { data, body } = parseSkill(fs.readFileSync(file, "utf8"));
    const id = `calkit-${entry.name}`;
    const skill = { id, name: id, path: file, content: body };
    if (data.description) skill.description = data.description;
    if (data["disable-model-invocation"] === true) skill.autoinvoke = false;
    skills.push(skill);
  }
  return skills;
}

export default {
  id: "calkit",
  async setup(ctx) {
    const skills = loadSkills();
    await ctx.skill.transform((editor) => {
      for (const skill of skills) {
        // A user's own skill with the same ID takes precedence, e.g., one
        // copied by `calkit update agent-skills`.
        if (editor.get(skill.id)) continue;
        try {
          editor.add(skill);
        } catch (err) {
          console.error(`calkit: skipping skill ${skill.id}:`, err);
        }
      }
    });
  },
};
