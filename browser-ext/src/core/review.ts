/**
 * Review comments in a LaTeX document's source, as the PDF viewer on
 * Overleaf shows and edits them, following the Calkit comment schema: a
 * thread is a `% COMMENT` block above the paragraph it's about.
 *
 * The schema is parsed and written by the hub's code for it, and the
 * SyncTeX and text matching are the VS Code extension's, so all three
 * read and write threads the same way.
 */
import {
  type TexThread as SourceThread,
  commentDate,
  newCommentId,
  paragraphStart,
  parseComments,
  renderComment,
} from "../../../hub/frontend/src/lib/latexComments";
import {
  type PdfRect,
  type TexThread,
  paragraphLines,
} from "../../../vscode-ext/src/latex/core";

export type { PdfRect };

/** A thread as the viewer shows it, with where it is in the PDF. */
export interface ReviewThread extends TexThread {
  key: string;
  start?: PdfRect;
  end?: PdfRect;
}

/** Messages from the page the viewer is on to the viewer. */
export type ToReview =
  | { calkit: "review"; type: "load"; data: ArrayBuffer }
  | {
      calkit: "review";
      type: "threads";
      threads: ReviewThread[];
      synctex: boolean;
      stale: string[];
    }
  | { calkit: "review"; type: "status"; text: string }
  | { calkit: "review"; type: "reveal"; rect: PdfRect }
  | {
      calkit: "review";
      type: "located";
      reqId: number;
      file?: string;
      line?: number;
      start?: PdfRect;
      text?: string;
    };

/** A thread's file, and its ID, or a line in it for one without. */
interface ThreadRef {
  file: string;
  id?: string;
  line?: number;
}

/** Messages from the viewer to the page it's on. */
export type FromReview =
  | { calkit: "review"; type: "ready" }
  | {
      calkit: "review";
      type: "sourceAt";
      page: number;
      x: number;
      y: number;
      context: string;
      focus?: string;
    }
  | {
      calkit: "review";
      type: "locate";
      reqId: number;
      page: number;
      x: number;
      y: number;
      context: string;
    }
  | {
      calkit: "review";
      type: "add";
      file: string;
      line: number;
      text: string;
      highlight: string;
      occ: number;
    }
  | ({ calkit: "review"; type: "reply"; text: string } & ThreadRef)
  | ({ calkit: "review"; type: "resolve"; resolved: boolean } & ThreadRef)
  | ({ calkit: "review"; type: "delete" } & ThreadRef)
  | { calkit: "review"; type: "openSource"; file: string; line: number }
  | { calkit: "review"; type: "openIssue"; url: string };

/** Who's writing a comment, as the schema names them. */
export interface CommentAuthor {
  name: string;
  email: string | null;
}

/** A change to a file's lines: `count` from `line` (from 1) replaced. */
export interface LineEdit {
  line: number;
  count: number;
  insert: string[];
}

/**
 * A paragraph's text as it roughly reads in the PDF: without comments,
 * commands, or braces. Only good enough to find runs of its words.
 */
export function getPlainText(lines: string[]): string {
  return lines
    .map((line) => line.replace(/(^|[^\\])%.*$/, "$1"))
    .join(" ")
    .replace(
      /~?\\(?:cite|ref|eqref|label|cref|Cref)\*?(?:\[[^\]]*\])*\{[^}]*\}/g,
      "",
    )
    .replace(/\\[a-zA-Z]+\*?(?:\[[^\]]*\])*/g, "")
    .replace(/\\./g, "")
    .replace(/[{}$~]/g, " ")
    .replace(/\s+/g, " ")
    .replace(/ ([.,;:])/g, "$1")
    .trim();
}

/** The threads in a document's files, in path then line order. */
export function getReviewThreads(files: Map<string, string>): ReviewThread[] {
  const threads: ReviewThread[] = [];
  for (const path of [...files.keys()].sort()) {
    const lines = files.get(path)?.split("\n") ?? [];
    for (const t of parseComments(lines)) {
      const after = t.lineno + t.nlines;
      const start = paragraphStart(lines, after);
      const para = start === null ? null : paragraphLines(lines, start);
      threads.push({
        key: t.id ?? `${path}:${t.lineno}`,
        id: t.id,
        path,
        line: t.lineno,
        nlines: t.nlines,
        resolved: t.resolved,
        issue: t.issue,
        highlight: t.highlight ? { text: t.highlight, occ: t.occ } : null,
        anchor: para && {
          line: para.start,
          end_line: para.end,
          text: getPlainText(lines.slice(para.start - 1, para.end)),
        },
        messages: t.entries.map((e) => ({ ...e })),
      });
    }
  }
  return threads;
}

/**
 * The source paragraph some text from the PDF is most likely in, by the
 * words they share, for a PDF without SyncTeX.
 */
export function findParagraphByText(
  files: Map<string, string>,
  context: string,
): { file: string; line: number; text: string } | null {
  const words = (text: string) =>
    new Set(text.toLowerCase().match(/[a-z]{3,}/g) ?? []);
  const wanted = words(context);
  let best: { file: string; line: number; text: string } | null = null;
  let bestScore = 0;
  for (const [file, text] of files) {
    const lines = text.split("\n");
    for (let line = 1; line <= lines.length; ) {
      if (!lines[line - 1].trim() || lines[line - 1].trim().startsWith("%")) {
        line++;
        continue;
      }
      const para = paragraphLines(lines, line);
      const plain = getPlainText(lines.slice(para.start - 1, para.end));
      const score = [...words(plain)].filter((w) => wanted.has(w)).length;
      if (score > bestScore) {
        best = { file, line: para.start, text: plain };
        bestScore = score;
      }
      line = Math.max(para.end, line) + 1;
    }
  }
  return best;
}

/** The thread an edit is for, by its ID, or any line in it. */
function findThread(
  lines: string[],
  ref: { id?: string; line?: number },
): SourceThread {
  const found = parseComments(lines).find((t) =>
    ref.id
      ? t.id === ref.id
      : ref.line !== undefined &&
        ref.line >= t.lineno &&
        ref.line < t.lineno + t.nlines,
  );
  if (!found) {
    throw new Error("That comment thread is no longer in the source.");
  }
  return found;
}

/** A new thread above the paragraph at or after a line. */
export function getAddEdit(
  lines: string[],
  line: number,
  author: CommentAuthor,
  text: string,
  highlight: string,
  occ: number,
): LineEdit {
  const start = paragraphStart(lines, line);
  if (start === null) {
    throw new Error(`No paragraph at or after line ${line}.`);
  }
  return {
    line: start,
    count: 0,
    insert: renderComment({
      entries: [
        { author: author.name, email: author.email, date: commentDate(), text },
      ],
      highlight: highlight || null,
      occ: highlight ? occ : 0,
      resolved: false,
      id: newCommentId(),
      issue: null,
      attrs: [],
      lineno: 0,
      nlines: 0,
    }),
  };
}

/**
 * A thread replied to, resolved or reopened, or, with no change, deleted,
 * giving it an ID if it had none.
 */
export function getThreadEdit(
  lines: string[],
  ref: { id?: string; line?: number },
  change: ((t: SourceThread) => SourceThread) | null,
): LineEdit {
  const thread = findThread(lines, ref);
  if (!change) {
    return { line: thread.lineno, count: thread.nlines, insert: [] };
  }
  const changed = change(thread);
  return {
    line: thread.lineno,
    count: thread.nlines,
    insert: renderComment({ ...changed, id: changed.id ?? newCommentId() }),
  };
}

/** A reply to a thread, as a change to it. */
export function getReply(
  author: CommentAuthor,
  text: string,
): (t: SourceThread) => SourceThread {
  return (t) => ({
    ...t,
    entries: [
      ...t.entries,
      { author: author.name, email: author.email, date: commentDate(), text },
    ],
  });
}

/** Lines with an edit made to them. */
export function getEditedLines(lines: string[], edit: LineEdit): string[] {
  return [
    ...lines.slice(0, edit.line - 1),
    ...edit.insert,
    ...lines.slice(edit.line - 1 + edit.count),
  ];
}
