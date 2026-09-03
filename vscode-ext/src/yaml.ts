import {
  isMap,
  isScalar,
  LineCounter,
  parseDocument,
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
