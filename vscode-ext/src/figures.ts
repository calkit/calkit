import * as path from "node:path";

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
