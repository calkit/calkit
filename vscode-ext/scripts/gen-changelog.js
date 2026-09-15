// Generate CHANGELOG.md from the vscode-ext/v* release tags.
//
// The extension's changelog is derived rather than hand-maintained, for the
// same reason its version is: both must mirror the release tags, and a copy
// kept by hand drifts. See the "Generate changelog" step in
// .github/workflows/publish-vscode-ext.yml.
//
// Commits are filtered to the vscode-ext/ directory. The GitHub-generated
// release notes can't be used as the source: they list every PR merged since
// the previous tag of any kind, which in this monorepo is mostly CLI and hub
// work that never touched the extension.
//
// A release whose commit subjects don't read well can be written by hand
// instead, in changelog-notes.md; see the comment at the top of that file.
// Anything not written there falls back to the commit subjects, so the two
// can be mixed freely and there's nothing to keep in sync.
//
// Requires the full history and tags, i.e., a checkout with fetch-depth: 0.

const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const repoRoot = path.join(__dirname, "..", "..");

function git(...args) {
  return execFileSync("git", args, {
    cwd: repoRoot,
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
  }).trim();
}

const TAG_PREFIX = "vscode-ext/v";

function parseVersion(tag) {
  const parts = tag.slice(TAG_PREFIX.length).split(".");
  return parts.map((p) => Number.parseInt(p, 10) || 0);
}

// Oldest first, so each tag can be diffed against the one before it
const tags = git("tag", "--list", `${TAG_PREFIX}*`)
  .split("\n")
  .filter(Boolean)
  .sort((a, b) => {
    const [x, y] = [parseVersion(a), parseVersion(b)];
    for (let i = 0; i < Math.max(x.length, y.length); i++) {
      if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) - (y[i] || 0);
    }
    return 0;
  });

if (tags.length === 0) {
  console.error(
    `No ${TAG_PREFIX}* tags found; is this a shallow checkout ` +
      "without tags (fetch-depth: 0)?",
  );
  process.exit(1);
}

// Subjects that only record release mechanics or repo chores, which say
// nothing to someone reading the changelog to see what changed for them
const SKIP =
  /^(increment|bump|release |merge |update changelog|add to readme)/i;

// Hand-written sections, keyed by version. Headings may carry a date
// (## 0.1.3 - 2026-06-12) so a generated section can be pasted in and edited
// as-is; the date is always re-derived from the tag, so only the body counts.
function readNotes() {
  const notesPath = path.join(__dirname, "..", "changelog-notes.md");
  if (!fs.existsSync(notesPath)) return new Map();
  const notes = new Map();
  let version = null;
  let lines = [];
  const flush = () => {
    // A heading with nothing under it is one nobody got around to writing,
    // so leave it to the commit subjects rather than emitting a blank section
    const body = lines.join("\n").trim();
    if (version && body) notes.set(version, body);
  };
  // Drop HTML comments first, so the worked example in the file's own header
  // isn't parsed as a real section
  const text = fs
    .readFileSync(notesPath, "utf8")
    .replace(/<!--[\s\S]*?-->/g, "");
  for (const line of text.split("\n")) {
    const heading = line.match(/^##\s+v?(\d+\.\d+\.\d+[^\s-]*)/);
    if (heading) {
      flush();
      version = heading[1];
      lines = [];
    } else if (version !== null) {
      lines.push(line);
    }
  }
  flush();
  return notes;
}

const notes = readNotes();

const sections = tags.map((tag, i) => {
  const version = tag.slice(TAG_PREFIX.length);
  const date = git("log", "-1", "--format=%ad", "--date=short", tag);
  const written = notes.get(version);
  if (written) return { version, date, body: written };
  // The first tag has no predecessor, so take everything leading up to it
  const range = i === 0 ? tag : `${tags[i - 1]}..${tag}`;
  const entries = git(
    "log",
    "--format=%s",
    "--no-merges",
    range,
    "--",
    "vscode-ext/",
  )
    .split("\n")
    .filter((s) => s && !SKIP.test(s));
  const unique = [...new Set(entries)];
  const body = unique.length
    ? unique.map((s) => `- ${s}`).join("\n")
    : "- Maintenance and dependency updates.";
  return { version, date, body };
});

// Catch a typo'd or not-yet-tagged heading rather than silently dropping it
const tagged = new Set(tags.map((t) => t.slice(TAG_PREFIX.length)));
const pending = [...notes.keys()].filter((v) => !tagged.has(v));
if (pending.length) {
  console.log(
    `Note: changelog-notes.md has ${pending.length} section(s) matching no ` +
      `release tag (${pending.join(", ")}); they'll be used once those ` +
      "versions are tagged.",
  );
}

// Newest first, the way a changelog is read
const body = sections
  .reverse()
  .map(({ version, date, body }) => `## ${version} - ${date}\n\n${body}\n`)
  .join("\n");

const header =
  "# Changelog\n\n" +
  "Generated from the `vscode-ext/v*` release tags and `changelog-notes.md`;\n" +
  "see `scripts/gen-changelog.js`.\n\n";

const outPath = path.join(__dirname, "..", "CHANGELOG.md");
fs.writeFileSync(outPath, header + body, "utf8");
console.log(`Wrote ${sections.length} releases to ${outPath}`);
