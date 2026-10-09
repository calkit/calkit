import * as path from "node:path";

// Pure helpers (no vscode imports) for diffing LaTeX documents, so they can be
// unit-tested under plain `node --test`.

// Turn a Git ref into one path component, mirroring `_ref_dirname` in
// calkit/latex.py.
function refDirname(ref: string): string {
  const name = ref.replace(/^_+/, "").replace(/_/g, "-").replace(/\//g, "-");
  return name.replace(/[^A-Za-z0-9.-]+/g, "-").replace(/^-+|-+$/g, "");
}

// Where `calkit latex diff` keeps a comparison against the working tree,
// mirroring `get_diff_path` in calkit/latex.py. An undefined `fromRef` means
// the CLI's default, the merge base with the default branch.
export function latexWorkingDiffPath(
  texFile: string,
  fromRef?: string,
): string {
  const name = refDirname(fromRef ?? "default-branch");
  return path.posix.join(
    ".calkit/local/latex-diffs",
    `${name}..working`,
    path.posix.dirname(texFile),
    `${path.posix.basename(texFile, path.posix.extname(texFile))}.pdf`,
  );
}

// A diff a latex stage keeps, mirroring `get_pipeline_diffs` in
// calkit/latex.py. `toRef` is undefined for a bare revision, which is
// compared with the working tree.
export interface PipelineLatexDiff {
  path: string;
  document: string;
  latexStage: string;
  stage: string;
  fromRef: string;
  toRef?: string;
}

export function pipelineLatexDiffs(
  stages: Record<string, unknown>,
): PipelineLatexDiff[] {
  const diffs: PipelineLatexDiff[] = [];
  for (const [name, raw] of Object.entries(stages)) {
    const stage = raw as {
      kind?: string;
      wdir?: string;
      target_path?: string;
      diffs?: (string | string[])[];
    };
    if (stage?.kind !== "latex" || !stage.target_path) {
      continue;
    }
    const wdir = stage.wdir ?? "";
    const target = stage.target_path;
    for (const entry of stage.diffs ?? []) {
      const [fromRef, toRef] =
        typeof entry === "string" ? [entry, "HEAD"] : [entry[0], entry[1]];
      let dir = refDirname(fromRef);
      let suffix = refDirname(fromRef);
      if (toRef !== "HEAD") {
        dir += `..${refDirname(toRef)}`;
        suffix += `-${refDirname(toRef)}`;
      }
      diffs.push({
        path: path.posix.join(
          wdir,
          ".calkit/latex-diffs",
          dir,
          path.posix.dirname(target),
          `${path.posix.basename(target, path.posix.extname(target))}.pdf`,
        ),
        document: path.posix.join(wdir, target),
        latexStage: name,
        stage: `${name}-diff-${suffix}`,
        fromRef,
        toRef: typeof entry === "string" ? undefined : toRef,
      });
    }
  }
  return diffs;
}

interface LatexStageFields {
  kind?: string;
  wdir?: string;
  target_path?: string;
}

// The PDF a latex stage builds from `texFile`, if one does.
export function latexStagePdf(
  stages: Record<string, unknown>,
  texFile: string,
): string | undefined {
  for (const raw of Object.values(stages)) {
    const stage = raw as LatexStageFields;
    if (stage?.kind !== "latex" || typeof stage.target_path !== "string") {
      continue;
    }
    const target = path.posix.join(stage.wdir ?? "", stage.target_path);
    if (target === texFile) {
      return target.replace(/\.tex$/, ".pdf");
    }
  }
  return undefined;
}

// The document a latex stage builds `pdfFile` from, if one does.
export function latexStageSource(
  stages: Record<string, unknown>,
  pdfFile: string,
): string | undefined {
  for (const raw of Object.values(stages)) {
    const stage = raw as LatexStageFields;
    if (stage?.kind !== "latex" || typeof stage.target_path !== "string") {
      continue;
    }
    const target = path.posix.join(stage.wdir ?? "", stage.target_path);
    if (target.replace(/\.tex$/, ".pdf") === pdfFile) {
      return target;
    }
  }
  return undefined;
}

// A comment thread as `calkit latex comments list --json` reports it.
export interface TexThread {
  id: string | null;
  path: string;
  line: number;
  nlines: number;
  resolved: boolean;
  issue: string | null;
  highlight: { text: string; occ: number } | null;
  anchor: { line: number; end_line: number; text: string } | null;
  messages: {
    author: string;
    email: string | null;
    date: string | null;
    text: string;
  }[];
}

// A region of a PDF page in points from its top-left corner, as SyncTeX
// measures it.
export interface PdfRect {
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

interface SynctexBox extends PdfRect {
  tag: number;
  line: number;
}

interface SynctexNode {
  page: number;
  tag: number;
  line: number;
  x: number;
  y: number;
  // The innermost horizontal box around it, e.g., its line of text
  box?: SynctexBox;
}

export interface Synctex {
  inputs: Map<number, string>;
  boxes: SynctexBox[];
  nodes: SynctexNode[];
}

// Parse an uncompressed .synctex file. Only what's needed to go between
// source lines and places on the page is kept.
export function parseSynctex(text: string): Synctex {
  const inputs = new Map<number, string>();
  const boxes: SynctexBox[] = [];
  const nodes: SynctexNode[] = [];
  const header: Record<string, number> = {
    Unit: 1,
    Magnification: 1000,
    "X Offset": 0,
    "Y Offset": 0,
  };
  // Scaled points to PDF points: 65536 sp per TeX point, 72.27 per inch
  const pt = (n: string): number =>
    (Number(n) * header.Unit * header.Magnification) / 1000 / 65781.76;
  const record =
    /^([[(vhxkg$])(\d+),(\d+):(-?\d+),(-?\d+)(?::(-?\d+)(?:,(-?\d+),(-?\d+))?)?/;
  let page = 0;
  // Enclosing boxes, with undefined for vertical ones
  const stack: (SynctexBox | undefined)[] = [];
  for (const line of text.split(/\r?\n/)) {
    const input = /^Input:(\d+):(.*)$/.exec(line);
    if (input) {
      inputs.set(Number(input[1]), input[2]);
      continue;
    }
    const field = /^(Unit|Magnification|X Offset|Y Offset):(-?[\d.]+)$/.exec(
      line,
    );
    if (field) {
      header[field[1]] = Number(field[2]);
      continue;
    }
    if (line.startsWith("{")) {
      page = Number(line.slice(1));
      stack.length = 0;
      continue;
    }
    if (line === ")" || line === "]") {
      stack.pop();
      continue;
    }
    const m = record.exec(line);
    if (!m || !page) {
      continue;
    }
    const [, kind, tag, ln, h, v, w, ht, dp] = m;
    const x = pt(h) + pt(String(header["X Offset"]));
    const y = pt(v) + pt(String(header["Y Offset"]));
    if ("[(vh".includes(kind)) {
      const height = ht ? pt(ht) : 0;
      const box: SynctexBox = {
        page,
        tag: Number(tag),
        line: Number(ln),
        x,
        y: y - height,
        width: w ? pt(w) : 0,
        height: height + (dp ? pt(dp) : 0),
      };
      if (kind === "(" || kind === "h") {
        boxes.push(box);
      }
      if (kind === "(" || kind === "[") {
        stack.push(kind === "(" ? box : undefined);
      }
      continue;
    }
    const box = [...stack].reverse().find((b) => b !== undefined);
    nodes.push({ page, tag: Number(tag), line: Number(ln), x, y, box });
  }
  return { inputs, boxes, nodes };
}

function normalizeInput(input: string): string {
  return input.replace(/\\/g, "/").replace(/\/(\.\/)+/g, "/");
}

// The SyncTeX input for a project file. Its paths can be absolute and from
// another machine or a container, so they're matched by suffix.
export function synctexTag(s: Synctex, file: string): number | undefined {
  for (const [tag, input] of s.inputs) {
    const norm = normalizeInput(input);
    if (norm === file || norm.endsWith(`/${file}`)) {
      return tag;
    }
  }
  return undefined;
}

// The project file a SyncTeX input is, as the longest of its trailing paths
// that exists.
export function synctexInputFile(
  input: string,
  exists: (file: string) => boolean,
): string | undefined {
  const parts = normalizeInput(input).split("/");
  for (let i = 0; i < parts.length; i++) {
    const file = parts.slice(i).join("/");
    if (file && exists(file)) {
      return file;
    }
  }
  return undefined;
}

// Where a source line ends up in the PDF: the line of text it starts, or its
// last one. A line producing nothing, e.g., a comment, goes to the next one
// that does.
export function synctexForward(
  s: Synctex,
  tag: number,
  line: number,
  last = false,
): PdfRect | undefined {
  const nodes = s.nodes.filter((n) => n.tag === tag);
  const lines = [...new Set(nodes.map((n) => n.line))];
  const after = lines.filter((l) => l >= line);
  const target = after.length ? Math.min(...after) : Math.max(...lines);
  const found = nodes.filter((n) => n.line === target);
  const node = last ? found[found.length - 1] : found[0];
  if (!node) {
    return undefined;
  }
  if (node.box) {
    const { page, x, y, width, height } = node.box;
    return { page, x, y, width, height };
  }
  return { page: node.page, x: node.x, y: node.y - 10, width: 0, height: 12 };
}

// The source line at a point on a page: the closest thing to its left on
// the line of text there.
export function synctexReverse(
  s: Synctex,
  page: number,
  x: number,
  y: number,
): { input: string; line: number } | undefined {
  const onPage = s.boxes.filter((b) => b.page === page);
  const containing = onPage.filter(
    (b) => b.x <= x && x <= b.x + b.width && b.y <= y && y <= b.y + b.height,
  );
  const area = (b: SynctexBox): number => b.width * b.height;
  const distance = (b: SynctexBox): number =>
    Math.max(b.y - y, y - (b.y + b.height), 0);
  const box = containing.length
    ? containing.reduce((a, b) => (area(b) < area(a) ? b : a))
    : onPage.reduce<SynctexBox | undefined>(
        (a, b) => (!a || distance(b) < distance(a) ? b : a),
        undefined,
      );
  if (!box) {
    return undefined;
  }
  const inBox = s.nodes.filter((n) => n.box === box);
  const left = inBox.filter((n) => n.x <= x);
  const node = left.length ? left[left.length - 1] : inBox[0];
  const tag = node ? node.tag : box.tag;
  const input = s.inputs.get(tag);
  return input === undefined
    ? undefined
    : { input, line: node ? node.line : box.line };
}

const BLOCK_START =
  /^\s*\\(begin|end|section|subsection|subsubsection|chapter|part|item|caption|maketitle|documentclass)\b/;

// The lines of the paragraph a line is in, mirroring `blocks` in
// calkit/latex.py closely enough to find where it starts and ends.
export function paragraphLines(
  lines: string[],
  line: number,
): { start: number; end: number } {
  const blank = (i: number): boolean =>
    i < 1 || i > lines.length || !lines[i - 1].trim();
  let start = line;
  while (
    !blank(start - 1) &&
    !lines[start - 2].trim().startsWith("%") &&
    !BLOCK_START.test(lines[start - 1])
  ) {
    start--;
  }
  let end = line;
  while (!blank(end + 1) && !BLOCK_START.test(lines[end])) {
    end++;
  }
  return { start, end };
}

export interface PdfTextItem {
  str: string;
}

export interface TextRange {
  start: { item: number; offset: number };
  end: { item: number; offset: number };
}

// Not exported where it's declared, so the functions using it can run in a
// webview, where there's no `exports`
const LIGATURES: Record<string, string> = {
  ﬀ: "ff",
  ﬁ: "fi",
  ﬂ: "fl",
  ﬃ: "ffi",
  ﬄ: "ffl",
  "‘": "'",
  "’": "'",
  "“": '"',
  "”": '"',
};

export { LIGATURES };

// Every place some text appears in a page's text items. Spacing and dashes
// are ignored, since a PDF's line breaks and hyphenation rarely match the
// text being looked for.
export function findText(items: PdfTextItem[], text: string): TextRange[] {
  const skip = /[\s\-­‐-―]/;
  const norm = (s: string): string =>
    [...s]
      .map((c) => LIGATURES[c] ?? c)
      .join("")
      .split("")
      .filter((c) => !skip.test(c))
      .join("");
  const needle = norm(text);
  if (!needle) {
    return [];
  }
  let hay = "";
  const at: { item: number; offset: number }[] = [];
  items.forEach((it, item) => {
    [...it.str].forEach((c, offset) => {
      for (const ch of LIGATURES[c] ?? c) {
        if (!skip.test(ch)) {
          hay += ch;
          at.push({ item, offset });
        }
      }
    });
  });
  const out: TextRange[] = [];
  for (let i = hay.indexOf(needle); i >= 0; i = hay.indexOf(needle, i + 1)) {
    const last = at[i + needle.length - 1];
    out.push({
      start: at[i],
      end: { item: last.item, offset: last.offset + 1 },
    });
  }
  return out;
}

// Text selected in a PDF as it would read in the source's paragraph, without
// the hyphenation and line breaks of its layout.
export function normalizeSelection(text: string): string {
  return [...text]
    .map((c) => LIGATURES[c] ?? c)
    .join("")
    .replace(/(\w)[-\u00ad]\s*\n\s*(\w)/g, "$1$2")
    .replace(/\s+/g, " ")
    .trim();
}

// Line numbers between two versions of a file, e.g., the source a PDF was
// built from and the source now, which differ by the comments added since.
// A line that's only in one goes to the next line in both.
export function lineMap(
  before: string[],
  after: string[],
): { toAfter: (line: number) => number; toBefore: (line: number) => number } {
  const n = before.length;
  const m = after.length;
  const fwd = new Array<number>(n).fill(-1);
  const back = new Array<number>(m).fill(-1);
  let lo = 0;
  while (lo < n && lo < m && before[lo] === after[lo]) {
    fwd[lo] = back[lo] = lo;
    lo++;
  }
  let hi = 0;
  while (
    hi < n - lo &&
    hi < m - lo &&
    before[n - 1 - hi] === after[m - 1 - hi]
  ) {
    fwd[n - 1 - hi] = m - 1 - hi;
    back[m - 1 - hi] = n - 1 - hi;
    hi++;
  }
  // The longest common subsequence of what's left, if that's small enough
  const a = before.slice(lo, n - hi);
  const b = after.slice(lo, m - hi);
  if (a.length && b.length && a.length * b.length <= 4e6) {
    const w = b.length + 1;
    const len = new Uint32Array((a.length + 1) * w);
    for (let i = a.length - 1; i >= 0; i--) {
      for (let j = b.length - 1; j >= 0; j--) {
        len[i * w + j] =
          a[i] === b[j]
            ? len[(i + 1) * w + j + 1] + 1
            : Math.max(len[(i + 1) * w + j], len[i * w + j + 1]);
      }
    }
    for (let i = 0, j = 0; i < a.length && j < b.length; ) {
      if (a[i] === b[j]) {
        fwd[lo + i] = lo + j;
        back[lo + j] = lo + i;
        i++;
        j++;
      } else if (len[(i + 1) * w + j] >= len[i * w + j + 1]) {
        i++;
      } else {
        j++;
      }
    }
  }
  const lookup =
    (map: number[], size: number) =>
    (line: number): number => {
      for (let i = Math.max(line - 1, 0); i < map.length; i++) {
        if (map[i] >= 0) {
          return map[i] + 1;
        }
      }
      return Math.min(line, size);
    };
  return { toAfter: lookup(fwd, m), toBefore: lookup(back, n) };
}

// Where rendered text is in the source near a line: all of it if it's
// there as is, else as many of its first words as are, since macros and
// line breaks can come between them.
export function findInSource(
  lines: string[],
  line: number,
  text: string,
): { line: number; start: number; end: number } | undefined {
  const words = text.split(/\s+/).filter(Boolean);
  const near = [line, line + 1, line - 1, line + 2, line - 2].filter(
    (l) => l >= 1 && l <= lines.length,
  );
  for (let n = words.length; n >= 1; n--) {
    const needle = words.slice(0, n).join(" ");
    if (n === 1 && needle.replace(/[^A-Za-z]/g, "").length < 3) {
      break;
    }
    for (const l of near) {
      const start = lines[l - 1].indexOf(needle);
      if (start >= 0) {
        return { line: l, start, end: start + needle.length };
      }
    }
  }
  return undefined;
}
