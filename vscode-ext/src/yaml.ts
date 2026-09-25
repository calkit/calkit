import {
  isMap,
  isScalar,
  LineCounter,
  parseDocument,
  visit,
  YAMLParseError,
} from "yaml";

export interface YamlSyntaxError {
  /** Parser message, with its trailing position and source snippet removed. */
  message: string;
  /** One-based line the parser flagged, if it reported one. */
  line?: number;
  /** One-based column the parser flagged, if it reported one. */
  column?: number;
}

// The `yaml` package appends " at line L, column C:" plus a snippet of the
// offending source to every parse error message. That reads poorly in a
// notification, and we render the position ourselves.
const POSITION_SUFFIX = / at line \d+, column \d+:?[\s\S]*$/;

/**
 * Describe a YAML parse failure, or return undefined for other errors.
 *
 * Errors from reading the file (missing, unreadable) are not syntax errors,
 * so callers can keep handling those separately.
 */
export function yamlSyntaxError(error: unknown): YamlSyntaxError | undefined {
  if (!(error instanceof YAMLParseError)) {
    return undefined;
  }
  const pos = error.linePos?.[0];
  return {
    message: error.message.replace(POSITION_SUFFIX, "").trim(),
    line: pos?.line,
    column: pos?.col,
  };
}

/** Render a syntax error as a single line naming the file and position. */
export function formatYamlSyntaxError(
  fileName: string,
  error: YamlSyntaxError,
): string {
  const where =
    error.line === undefined
      ? ""
      : error.column === undefined
      ? ` at line ${error.line}`
      : ` at line ${error.line}, column ${error.column}`;
  return `${fileName} has a YAML syntax error${where}: ${error.message}`;
}

/**
 * Zero-based line where a pipeline stage is defined in calkit.yaml.
 *
 * Located through the parsed document rather than by searching for the
 * name, so a stage called `plot` is not found in a comment, in another
 * collection, or in a value that happens to say it.
 */
export function stageDefinitionLine(
  text: string,
  stageName: string,
): number | undefined {
  const counter = new LineCounter();
  const doc = parseDocument(text, { lineCounter: counter });
  const stages = doc.getIn(["pipeline", "stages"], true);
  if (!isMap(stages)) {
    return undefined;
  }
  for (const pair of stages.items) {
    const key = pair.key;
    if (!isScalar(key) || String(key.value) !== stageName || !key.range) {
      continue;
    }
    return counter.linePos(key.range[0]).line - 1;
  }
  return undefined;
}

/** A scalar value in a YAML document, with where its text sits. */
export interface YamlValueSpan {
  value: string;
  /** Character offset of the value's text, quotes excluded. */
  offset: number;
  length: number;
}

/**
 * Every scalar value in a document that could name a file.
 *
 * Values only: a mapping key is the name of a field, not a path, and
 * `path: figures/plot.png` would otherwise offer "path" as one. Nothing
 * here decides whether a file exists, which is the caller's to check
 * against a directory this does not know.
 *
 * Deliberately not restricted to a list of known keys. Any string that
 * turns out to name a file in the project is worth opening, and the keys
 * that hold one grow with every stage kind.
 */
export function pathLikeScalars(text: string): YamlValueSpan[] {
  const found: YamlValueSpan[] = [];
  const doc = parseDocument(text);
  visit(doc, {
    Scalar(key, node) {
      if (key === "key" || typeof node.value !== "string" || !node.range) {
        return;
      }
      const value = node.value;
      // A path has no line breaks, is not a URL, and is not prose. The
      // length cap keeps a long description from being stat'd.
      if (
        !value ||
        value.length > 250 ||
        /[\n\r]/.test(value) ||
        /^[a-z][a-z0-9+.-]*:\/\//i.test(value)
      ) {
        return;
      }
      let [offset, end] = [node.range[0], node.range[1]];
      // A quoted scalar's range covers its quotes, which are not the path
      const raw = text.slice(offset, end);
      const quote = raw[0];
      if ((quote === '"' || quote === "'") && raw.endsWith(quote)) {
        offset += 1;
        end -= 1;
      }
      // A value written as a block or with escapes is not the same string
      // as its source, so linking a span of it would highlight the wrong
      // characters
      if (text.slice(offset, end) !== value) {
        return;
      }
      found.push({ value, offset, length: end - offset });
    },
  });
  return found;
}
