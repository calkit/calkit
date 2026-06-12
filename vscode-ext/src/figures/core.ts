import * as path from "node:path";

// Pure helpers (no vscode imports) for parsing figure references, so they can be
// unit-tested under plain `node --test` (where the `vscode` module is absent).
// The vscode-dependent figure UI lives in view.ts.

// Extract Markdown/Quarto image references (`![alt](target)`) from document
// text, returning the 0-based line and the raw link target for each. The target
// stops at whitespace so an optional "title" or `<url>` wrapper is ignored.
export function extractMarkdownImageRefs(
  text: string,
): { line: number; target: string }[] {
  const refs: { line: number; target: string }[] = [];
  // Either an angle-bracket form `<...>` (may contain spaces) or a bare target
  // that stops at whitespace or `)` (so a trailing "title" is excluded).
  const re = /!\[[^\]]*\]\(\s*(?:<([^>]+)>|([^)\s]+))/g;
  text.split(/\r?\n/).forEach((lineText, lineIndex) => {
    re.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = re.exec(lineText)) !== null) {
      refs.push({ line: lineIndex, target: match[1] ?? match[2] });
    }
  });
  return refs;
}

// Extract LaTeX `\includegraphics[opts]{target}` references from document text,
// returning the 0-based line and the raw target for each. The optional `[...]`
// options block and a trailing `*` are skipped.
export function extractLatexImageRefs(
  text: string,
): { line: number; target: string }[] {
  const refs: { line: number; target: string }[] = [];
  const re = /\\includegraphics\*?\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}/g;
  text.split(/\r?\n/).forEach((lineText, lineIndex) => {
    re.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = re.exec(lineText)) !== null) {
      refs.push({ line: lineIndex, target: match[1].trim() });
    }
  });
  return refs;
}

// Resolve an image link target (relative to the referencing document) to a
// repo-relative POSIX path, or undefined for remote URLs, data URIs, or paths
// that escape the workspace.
export function resolveImageRefToRepoRelative(
  documentFsPath: string,
  target: string,
  workspaceRoot: string,
): string | undefined {
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(target) || target.startsWith("data:")) {
    return undefined;
  }
  const absPath = path.resolve(path.dirname(documentFsPath), target);
  const relPath = path.relative(workspaceRoot, absPath).replace(/\\/g, "/");
  if (relPath.startsWith("..") || path.isAbsolute(relPath)) {
    return undefined;
  }
  return relPath;
}

// Find the pipeline stage that produces the figure referenced at `relPath`.
// Matches the output paths directly; if `relPath` has no extension (common for
// LaTeX `\includegraphics`, which lets LaTeX pick the file), it also tries the
// usual graphics extensions so e.g. `figures/plot` finds `figures/plot.pdf`.
export function resolveFigureRefStage(
  relPath: string,
  outputToStage: Map<string, string>,
): string | undefined {
  const direct = outputToStage.get(relPath);
  if (direct) {
    return direct;
  }
  if (path.extname(relPath) === "") {
    for (const ext of [
      ".pdf",
      ".png",
      ".jpg",
      ".jpeg",
      ".eps",
      ".svg",
      ".gif",
    ]) {
      const stage = outputToStage.get(relPath + ext);
      if (stage) {
        return stage;
      }
    }
  }
  return undefined;
}
