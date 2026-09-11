import type { CalkitInfo } from "../types";

// Mirrors STAGE_NAME_SEPARATOR in calkit/markdown.py. DVC reserves "@" for
// the names it generates from a matrix, so a stage declared in Markdown is
// addressed as "<file>/<block name>".
export const STAGE_NAME_SEPARATOR = "/";

// At least three backticks or tildes, indented no more than three spaces.
const FENCE_RE = /^([ ]{0,3})(`{3,}|~{3,})(.*)$/;
const COMMENT_OPEN_RE = /^[ ]{0,3}<!--\s*(.*)$/;

export interface MarkdownStageBlock {
  /** Name declared by the block, i.e. the part after "name=". */
  name: string;
  /** Zero-indexed line the block's annotation starts on. */
  line: number;
}

/**
 * Read the stage name out of a "calkit stage ..." annotation.
 *
 * Only the name is needed to run the stage, so this deliberately does not
 * try to be the full attribute parser that lives on the Python side.
 */
function stageNameFromAnnotation(text: string): string | undefined {
  // Whole tokens, so "calkit stages" or "calkit stagecoach" is not a stage
  // any more than the Python parser thinks it is
  const match0 = /^\s*calkit\s+stage(?:\s+|$)/.exec(text);
  if (!match0) {
    return undefined;
  }
  const attrs = text.slice(match0[0].length);
  // A name is a bare token, so it ends at the next whitespace
  const match = /(?:^|\s)name=("[^"]*"|'[^']*'|\S+)/.exec(attrs);
  if (!match) {
    return undefined;
  }
  return match[1].replace(/^["']|["']$/g, "");
}

/** Split a fence's info string into its language and Calkit annotation. */
function annotationFromFenceInfo(info: string): string | undefined {
  const trimmed = info.trim();
  if (!trimmed) {
    return undefined;
  }
  if (trimmed.startsWith("calkit")) {
    return trimmed;
  }
  // Renderers take the first token as the language and ignore the rest
  const spaceAt = trimmed.search(/\s/);
  return spaceAt === -1 ? undefined : trimmed.slice(spaceAt + 1).trim();
}

/**
 * Find the stage-declaring code blocks in a Markdown document.
 *
 * Blocks inside a longer fence are shown rather than run, which is how a
 * file documents this feature without the examples it shows becoming
 * stages, so those must not be reported here either.
 */
export function findMarkdownStageBlocks(text: string): MarkdownStageBlock[] {
  const lines = text.split(/\r?\n/);
  const blocks: MarkdownStageBlock[] = [];
  let pendingName: string | undefined;
  let pendingLine = 0;
  let i = 0;
  while (i < lines.length) {
    const fence = FENCE_RE.exec(lines[i]);
    if (fence) {
      const [, , marker, info] = fence;
      const annotation = annotationFromFenceInfo(info);
      const name = annotation ? stageNameFromAnnotation(annotation) : undefined;
      // Find the closing fence: same character, at least as long, and
      // carrying no info string of its own.
      let j = i + 1;
      while (j < lines.length) {
        const close = FENCE_RE.exec(lines[j]);
        if (
          close &&
          close[2][0] === marker[0] &&
          close[2].length >= marker.length &&
          !close[3].trim()
        ) {
          break;
        }
        j += 1;
      }
      const resolved = name ?? pendingName;
      if (resolved) {
        blocks.push({
          name: resolved,
          line: pendingName !== undefined ? pendingLine : i,
        });
      }
      pendingName = undefined;
      i = j + 1;
      continue;
    }
    // A directive comment attaches to the block directly below it. Prose
    // in between makes the file invalid to compile, so there is no stage
    // to run and a lens on a later block would be wrong.
    if (pendingName !== undefined && lines[i].trim()) {
      pendingName = undefined;
    }
    const comment = COMMENT_OPEN_RE.exec(lines[i]);
    if (comment) {
      // A directive comment may span several lines, so a long declaration
      // doesn't have to sit on one
      const parts: string[] = [];
      let j = i;
      let body = comment[1];
      let terminated = false;
      while (j < lines.length) {
        const end = body.indexOf("-->");
        if (end !== -1) {
          parts.push(body.slice(0, end));
          terminated = true;
          j += 1;
          break;
        }
        parts.push(body);
        j += 1;
        if (j >= lines.length) {
          break;
        }
        body = lines[j];
      }
      if (terminated) {
        const name = stageNameFromAnnotation(parts.join(" "));
        if (name) {
          pendingName = name;
          pendingLine = i;
        }
        i = j;
        continue;
      }
    }
    i += 1;
  }
  return blocks;
}

/**
 * Return the pipeline stage a Markdown file is declared as, if any.
 *
 * A Markdown stage stands in for the stages its blocks declare; its
 * target_path says which file that is.
 */
export function markdownStageNameForFile(
  config: CalkitInfo | undefined,
  relPath: string,
): string | undefined {
  for (const [stageName, stage] of Object.entries(
    config?.pipeline?.stages ?? {},
  )) {
    if (stage?.kind !== "markdown") {
      continue;
    }
    if (typeof stage.target_path !== "string") {
      continue;
    }
    if (stage.target_path.replace(/\\/g, "/") === relPath) {
      return stageName;
    }
  }
  return undefined;
}

/**
 * Find the project directory a file belongs to.
 *
 * A repository can hold self-contained projects in subdirectories without
 * declaring them as subprojects---the examples in this very repo are one
 * case---so the nearest calkit.yaml at or above the file wins, falling
 * back to the workspace root.
 */
export function findProjectDir(
  filePath: string,
  workspaceRoot: string,
  exists: (candidate: string) => boolean,
  pathApi: {
    dirname: (p: string) => string;
    join: (...parts: string[]) => string;
    relative: (from: string, to: string) => string;
  },
): string | undefined {
  let dir = pathApi.dirname(filePath);
  for (;;) {
    if (exists(pathApi.join(dir, "calkit.yaml"))) {
      return dir;
    }
    const rel = pathApi.relative(workspaceRoot, dir);
    // Stop at the workspace root; going above it would reach projects the
    // user has not opened
    if (rel === "" || rel.startsWith("..")) {
      return undefined;
    }
    const parent = pathApi.dirname(dir);
    if (parent === dir) {
      return undefined;
    }
    dir = parent;
  }
}

/**
 * Split a derived stage name into the Markdown stage and block it names.
 *
 * The stages a Markdown file declares exist only in dvc.yaml, so anything
 * looking one up in calkit.yaml has to come back through the file it came
 * from.
 */
export function splitMarkdownStageName(
  stageName: string,
  config: CalkitInfo | undefined,
): { markdownStageName: string; blockName: string } | undefined {
  for (const [name, stage] of Object.entries(config?.pipeline?.stages ?? {})) {
    if (stage?.kind !== "markdown") {
      continue;
    }
    const prefix = name + STAGE_NAME_SEPARATOR;
    if (stageName.startsWith(prefix)) {
      return {
        markdownStageName: name,
        blockName: stageName.slice(prefix.length),
      };
    }
  }
  return undefined;
}

/** The path of the Markdown file a markdown stage reads. */
export function markdownStagePath(
  config: CalkitInfo | undefined,
  stageName: string,
): string | undefined {
  const stage = config?.pipeline?.stages?.[stageName];
  if (stage?.kind !== "markdown" || typeof stage.target_path !== "string") {
    return undefined;
  }
  return stage.target_path.replace(/\\/g, "/");
}
