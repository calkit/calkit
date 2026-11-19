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
} from "../../../vscode-ext/src/latex/pdf";

import type { PdfBox } from "./pdf-boxes";

export type { PdfRect };

/** A thread as the viewer shows it, with where it is in the PDF. */
export interface ReviewThread extends TexThread {
  key: string;
  start?: PdfRect;
  end?: PdfRect;
  /** The Overleaf comment thread it's kept in step with, if any. */
  overleaf?: string | null;
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
  | { calkit: "review"; type: "boxes"; boxes: PdfBox[] }
  | { calkit: "review"; type: "reveal"; rect: PdfRect }
  // Whether a reply or post to Overleaf the viewer asked for went through
  | { calkit: "review"; type: "sent"; reqId: number; ok: boolean }
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
      /** Where SyncTeX says it is, for a PDF built on this machine. */
      synctex?: { input: string; line: number };
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
      reqId: number;
      file: string;
      line: number;
      text: string;
      highlight: string;
      occ: number;
    }
  | ({
      calkit: "review";
      type: "reply";
      reqId: number;
      text: string;
    } & ThreadRef)
  | ({ calkit: "review"; type: "resolve"; resolved: boolean } & ThreadRef)
  | ({ calkit: "review"; type: "delete" } & ThreadRef)
  | ({ calkit: "review"; type: "postToOverleaf"; reqId: number } & ThreadRef)
  | { calkit: "review"; type: "openSource"; file: string; line: number }
  | { calkit: "review"; type: "openIssue"; url: string }
  // What's wrong at a box, to show in the editor
  | { calkit: "review"; type: "goto"; line: number; column: number }
  // Where the pointer rests on the PDF, in points from a page's top left,
  // and on the viewer's own page, or null once it's off the PDF
  | {
      calkit: "review";
      type: "pointer";
      point: {
        page: number;
        x: number;
        y: number;
        clientX: number;
        clientY: number;
      } | null;
    };

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
        overleaf: getOverleafThreadId(t),
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

/**
 * The lines an edit replaces and those either side, null past either end,
 * so it can be checked before it's made, even when it only inserts.
 */
export interface EditContext {
  before: string | null;
  expected: string[];
  after: string | null;
}

export function getEditContext(lines: string[], edit: LineEdit): EditContext {
  return {
    before: edit.line > 1 ? lines[edit.line - 2] ?? null : null,
    expected: lines.slice(edit.line - 1, edit.line - 1 + edit.count),
    after: lines[edit.line - 1 + edit.count] ?? null,
  };
}

/** Whether a file's lines, by number from 1, are as an edit expects. */
export function isEditCurrent(
  getLine: (n: number) => string,
  nLines: number,
  edit: { line: number } & EditContext,
): boolean {
  const { line, before, expected, after } = edit;
  const next = line + expected.length;
  if (line < 1 || next - 1 > nLines) {
    return false;
  }
  if (before === null ? line !== 1 : line < 2 || getLine(line - 1) !== before) {
    return false;
  }
  if (
    after === null ? next <= nLines : next > nLines || getLine(next) !== after
  ) {
    return false;
  }
  return expected.every((text, i) => getLine(line + i) === text);
}

/** The Overleaf thread a source thread is kept in step with, if any. */
function getOverleafThreadId(t: SourceThread): string | null {
  const raw = t.attrs.find(([key]) => key === "overleaf")?.[1];
  return raw ? raw.replace(/^"|"$/g, "") : null;
}

/** A comment on Overleaf: its thread, the text it's on, and where. */
export interface OverleafComment {
  thread: string;
  text: string;
  /** Characters into the file. */
  offset: number;
}

/** A comment thread as Overleaf keeps it. */
export interface OverleafThread {
  messages?: {
    content: string;
    timestamp?: number | string;
    user?: { first_name?: string; last_name?: string; email?: string };
  }[];
  resolved?: boolean;
}

/** What to do on Overleaf to bring a thread there into step. */
export interface OverleafPush {
  thread: string;
  replies: string[];
  resolved?: boolean;
  /** Deleted from the source after being in step, so from Overleaf too. */
  deleted?: boolean;
}

/** How a thread was on both sides when they were last in step. */
export interface OverleafSynced {
  resolved: boolean;
  messages: number;
}

/**
 * A file's lines with its Overleaf comments brought into the source: a
 * thread for each new one, above its paragraph, and new replies and
 * resolving or reopening on Overleaf since they were last in step. A thread
 * deleted on Overleaf after being in step is deleted from the source too.
 * Also what to do on Overleaf for replies, resolving or reopening, and
 * deleting done in the source, with replies others wrote named, since they're posted by
 * `me`, and how each thread will be on both sides, for next time.
 */
export function getOverleafSyncedLines(
  lines: string[],
  comments: OverleafComment[],
  threads: Record<string, OverleafThread>,
  synced: Record<string, OverleafSynced>,
  me: string,
): {
  lines: string[];
  pushes: OverleafPush[];
  synced: Record<string, OverleafSynced>;
} {
  const toEntry = (m: NonNullable<OverleafThread["messages"]>[number]) => {
    const name = [m.user?.first_name, m.user?.last_name]
      .filter(Boolean)
      .join(" ")
      .trim();
    return {
      author: name || m.user?.email || "Someone on Overleaf",
      email: m.user?.email ?? null,
      date:
        m.timestamp === undefined ? null : commentDate(new Date(m.timestamp)),
      text: m.content.replace(/\s+/g, " ").trim(),
    };
  };
  // Every edit is to the lines as they are, then made from the bottom up
  const edits: LineEdit[] = [];
  const pushes: OverleafPush[] = [];
  const next: Record<string, OverleafSynced> = {};
  const inSource = new Set<string>();
  const text = lines.join("\n");
  // The character each line starts at
  const starts = [0];
  for (const line of lines) {
    starts.push(starts[starts.length - 1] + line.length + 1);
  }
  const getLine = (offset: number) => text.slice(0, offset).split("\n").length;
  // Threads posted to Overleaf from the source, found by their paragraph
  // and first message, are linked to it rather than brought in again
  const norm = (s: string) => s.replace(/\s+/g, " ").trim();
  const parsed = parseComments(lines);
  const linked = new Set(parsed.map(getOverleafThreadId));
  const links = new Map<number, string>();
  for (const c of comments) {
    const first = threads[c.thread]?.messages?.[0]?.content;
    if (!first || linked.has(c.thread) || synced[c.thread]) {
      continue;
    }
    const start = paragraphStart(lines, getLine(c.offset));
    const match = parsed.find(
      (t) =>
        !getOverleafThreadId(t) &&
        !links.has(t.lineno) &&
        paragraphStart(lines, t.lineno + t.nlines) === start &&
        t.entries[0] &&
        [
          norm(t.entries[0].text),
          norm(`${t.entries[0].author}: ${t.entries[0].text}`),
        ].includes(norm(first)),
    );
    if (match) {
      links.set(match.lineno, c.thread);
    }
  }
  for (const t of parsed) {
    const id = getOverleafThreadId(t) ?? links.get(t.lineno);
    if (!id) {
      continue;
    }
    inSource.add(id);
    const thread = threads[id];
    // Just posted, so in step as far as its first message
    const last = links.has(t.lineno)
      ? { resolved: Boolean(thread?.resolved), messages: 1 }
      : synced[id];
    if (!thread) {
      if (last) {
        edits.push({ line: t.lineno, count: t.nlines, insert: [] });
      }
      continue;
    }
    const messages = thread.messages ?? [];
    const resolved = Boolean(thread.resolved);
    // Replies on each side since they were in step, which, never in step
    // here before, are those past what both have
    const base = last?.messages ?? Math.min(messages.length, t.entries.length);
    const push: OverleafPush = {
      thread: id,
      replies: t.entries
        .slice(base)
        .map((e) => (e.author === me ? e.text : `${e.author}: ${e.text}`)),
    };
    let changed = links.has(t.lineno)
      ? { ...t, attrs: [...t.attrs, ["overleaf", id] as [string, string]] }
      : t;
    if (messages.length > base) {
      changed = {
        ...changed,
        entries: [...changed.entries, ...messages.slice(base).map(toEntry)],
      };
    }
    // Resolved or reopened on one side since they were in step, or, never
    // in step here, as it is on Overleaf
    if (resolved !== t.resolved) {
      if (last?.resolved === resolved) {
        push.resolved = t.resolved;
      } else {
        changed = { ...changed, resolved };
      }
    }
    if (push.replies.length || push.resolved !== undefined) {
      pushes.push(push);
    }
    if (changed !== t) {
      edits.push({
        line: t.lineno,
        count: t.nlines,
        insert: renderComment({ ...changed, id: changed.id ?? newCommentId() }),
      });
    }
    next[id] = { resolved: changed.resolved, messages: changed.entries.length };
  }
  for (const c of comments) {
    const thread = threads[c.thread];
    if (inSource.has(c.thread) || !thread?.messages?.length) {
      continue;
    }
    inSource.add(c.thread);
    if (synced[c.thread]) {
      pushes.push({ thread: c.thread, replies: [], deleted: true });
      continue;
    }
    const start = paragraphStart(lines, getLine(c.offset));
    if (start === null) {
      continue;
    }
    // Which time its text appears in the paragraph, counting from 0
    const before = text.slice(starts[start - 1], c.offset);
    const highlight = c.text.includes("\\")
      ? getPlainText([c.text])
      : c.text.replace(/\s+/g, " ").trim();
    const entries = thread.messages.map(toEntry);
    edits.push({
      line: start,
      count: 0,
      insert: renderComment({
        entries,
        highlight: highlight || null,
        occ: highlight ? before.split(c.text).length - 1 : 0,
        resolved: Boolean(thread.resolved),
        id: newCommentId(),
        issue: null,
        attrs: [["overleaf", c.thread]],
        lineno: 0,
        nlines: 0,
      }),
    });
    next[c.thread] = {
      resolved: Boolean(thread.resolved),
      messages: entries.length,
    };
  }
  let out = lines;
  for (const edit of edits.sort((a, b) => b.line - a.line)) {
    out = getEditedLines(out, edit);
  }
  return { lines: out, pushes, synced: next };
}
