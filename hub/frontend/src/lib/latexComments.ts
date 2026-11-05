// The Calkit LaTeX comment schema, as in calkit/latex.py: a thread is a
// `% COMMENT` block above the paragraph it's about, so comments made in the
// editor are edits to the source like any other, saved with it.
import { RangeSetBuilder } from "@codemirror/state"
import {
  Decoration,
  type DecorationSet,
  type EditorView,
  ViewPlugin,
  type ViewUpdate,
} from "@codemirror/view"

export interface TexEntry {
  author: string
  email: string | null
  date: string | null
  text: string
}

export interface TexThread {
  entries: TexEntry[]
  highlight: string | null
  occ: number
  resolved: boolean
  id: string | null
  issue: string | null
  // Attributes this doesn't know, as written, so they survive a rewrite
  attrs: [string, string][]
  // Where the block is: its `% COMMENT` line, from 1, and its length
  lineno: number
  nlines: number
}

const AUTHOR_RE =
  /^(?<name>.*?)\s*(?:<(?<email>[^>]*)>)?\s*(?:\((?<date>[^)]*)\))?:$/
const BLOCK_START =
  /^\s*\\(begin|end|section|subsection|subsubsection|chapter|part|item|caption|maketitle|documentclass)\b/

// The key=value attributes on a COMMENT line, with each value as written: a
// bare word, a quoted string, or a flow mapping like {text: "x", occ: 0}
function parseHeader(text: string): [string, string][] {
  const out: [string, string][] = []
  const key = /\s*(\w+)=/y
  let i = 0
  for (;;) {
    key.lastIndex = i
    const m = key.exec(text)
    if (!m) return out
    i = key.lastIndex
    let j = i
    if (text[i] === "{") {
      let depth = 0
      let quoted = false
      for (; j < text.length; j++) {
        const c = text[j]
        if (c === '"' && text[j - 1] !== "\\") quoted = !quoted
        else if (!quoted && c === "{") depth++
        else if (!quoted && c === "}" && --depth === 0) break
      }
      j++
    } else if (text[i] === '"') {
      const q = /"(?:[^"\\]|\\.)*"/y
      q.lastIndex = i
      if (!q.exec(text)) return out
      j = q.lastIndex
    } else {
      while (j < text.length && !/\s/.test(text[j])) j++
    }
    out.push([m[1], text.slice(i, j)])
    i = j
  }
}

function unquote(raw: string): string {
  return raw.startsWith('"') ? JSON.parse(raw) : raw
}

// A flow mapping's entries, e.g., {text: "a, b", occ: 1}
function parseMapping(raw: string): Record<string, string | number> {
  const out: Record<string, string | number> = {}
  const inner = raw.slice(1, -1)
  const parts: string[] = []
  let quoted = false
  let start = 0
  for (let i = 0; i < inner.length; i++) {
    if (inner[i] === '"' && inner[i - 1] !== "\\") quoted = !quoted
    else if (!quoted && inner[i] === ",") {
      parts.push(inner.slice(start, i))
      start = i + 1
    }
  }
  parts.push(inner.slice(start))
  for (const part of parts) {
    const colon = part.indexOf(":")
    if (colon < 0) continue
    const value = part.slice(colon + 1).trim()
    out[part.slice(0, colon).trim()] = /^-?\d+$/.test(value)
      ? Number(value)
      : unquote(value)
  }
  return out
}

export function parseComments(lines: string[]): TexThread[] {
  const out: TexThread[] = []
  let i = 0
  while (i < lines.length) {
    if (!/^% COMMENT( |$)/.test(lines[i])) {
      i++
      continue
    }
    const start = i
    let header = lines[i].slice("% COMMENT".length)
    const entries: TexEntry[] = []
    i++
    while (i < lines.length && /^%( {3}|$)/.test(lines[i])) {
      const body = lines[i].slice(1)
      const indent = body.length - body.trimStart().length
      const author = indent === 3 ? AUTHOR_RE.exec(body.trim()) : null
      if (!entries.length && indent === 3 && /^\s*\w+=/.test(body)) {
        header += ` ${body.trim()}`
      } else if (author?.groups) {
        entries.push({
          author: author.groups.name.trim(),
          email: author.groups.email || null,
          date: author.groups.date || null,
          text: "",
        })
      } else if (indent > 3 && entries.length) {
        const e = entries[entries.length - 1]
        e.text = `${e.text} ${body.trim()}`.trim()
      }
      i++
    }
    if (!entries.length) continue
    const thread: TexThread = {
      entries,
      highlight: null,
      occ: 0,
      resolved: false,
      id: null,
      issue: null,
      attrs: [],
      lineno: start + 1,
      nlines: i - start,
    }
    for (const [key, raw] of parseHeader(header)) {
      if (key === "highlight") {
        if (raw.startsWith("{")) {
          const m = parseMapping(raw)
          thread.highlight = m.text ? String(m.text) : null
          thread.occ = Number(m.occ ?? 0)
        } else {
          thread.highlight = unquote(raw) || null
        }
      } else if (key === "resolved") {
        thread.resolved = unquote(raw).toLowerCase() === "true"
      } else if (key === "id") {
        thread.id = unquote(raw) || null
      } else if (key === "issue") {
        thread.issue = unquote(raw) || null
      } else {
        thread.attrs.push([key, raw])
      }
    }
    out.push(thread)
  }
  return out
}

// Fill lines up to a width, breaking at spaces, or after a hyphen within a
// word, as Python's textwrap does
function wrap(text: string, width: number, indent: string): string[] {
  const lines: string[] = []
  let line = ""
  for (const word of text.split(/\s+/).filter(Boolean)) {
    word.split(/(?<=\w-)(?=\w)/).forEach((chunk, i) => {
      const sep = line && i === 0 ? " " : ""
      if (
        line &&
        indent.length + line.length + sep.length + chunk.length > width
      ) {
        lines.push(indent + line)
        line = chunk
      } else {
        line += sep + chunk
      }
    })
  }
  if (line) lines.push(indent + line)
  return lines
}

export function renderComment(t: TexThread): string[] {
  const fmt = (v: string) => (/^[^\s"{}]+$/.test(v) ? v : JSON.stringify(v))
  const attrs: string[] = []
  if (t.id) attrs.push(`id=${fmt(t.id)}`)
  if (t.resolved) attrs.push("resolved=true")
  if (t.issue) attrs.push(`issue=${fmt(t.issue)}`)
  if (t.highlight) {
    const occ = t.occ ? `, occ: ${t.occ}` : ""
    attrs.push(`highlight={text: ${JSON.stringify(t.highlight)}${occ}}`)
  }
  attrs.push(...t.attrs.map(([k, v]) => `${k}=${v}`))
  const out = ["% COMMENT"]
  // Attributes continue onto their own lines when they don't fit
  for (const attr of attrs) {
    const last = out[out.length - 1]
    if (last === "% COMMENT" || last.length + 1 + attr.length <= 79) {
      out[out.length - 1] = `${last} ${attr}`
    } else {
      out.push(`%   ${attr}`)
    }
  }
  for (const e of t.entries) {
    const email = e.email ? ` <${e.email}>` : ""
    const date = e.date ? ` (${e.date})` : ""
    out.push(`%   ${e.author}${email}${date}:`)
    out.push(...wrap(e.text, 79, "%     "))
  }
  return out
}

export function newCommentId(): string {
  const bytes = new Uint8Array(4)
  crypto.getRandomValues(bytes)
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("")
}

// Now as the schema writes it, in UTC
export function commentDate(now = new Date()): string {
  return now.toISOString().slice(0, 16).replace("T", " ")
}

// Where the paragraph at or after a line starts, mirroring `blocks` in
// calkit/latex.py closely enough to find it: blank lines and structure
// commands start one, and a comment line before one isn't part of it.
export function paragraphStart(lines: string[], line: number): number | null {
  let i = Math.max(line, 1)
  const skip = (n: number) =>
    !lines[n - 1].trim() || lines[n - 1].trim().startsWith("%")
  while (i <= lines.length && skip(i)) i++
  if (i > lines.length) return null
  while (
    i > 1 &&
    !BLOCK_START.test(lines[i - 1]) &&
    lines[i - 2].trim() &&
    !lines[i - 2].trim().startsWith("%")
  ) {
    i--
  }
  return i
}

// A new thread above the paragraph at or after a line, below any threads
// already there
export function addComment(
  lines: string[],
  line: number,
  thread: Omit<TexThread, "lineno" | "nlines">,
): string[] {
  const start = paragraphStart(lines, line)
  if (start === null) {
    throw new Error(`No paragraph at or after line ${line}`)
  }
  const rendered = renderComment({ ...thread, lineno: 0, nlines: 0 })
  return [...lines.slice(0, start - 1), ...rendered, ...lines.slice(start - 1)]
}

// A thread changed, or removed with no change, giving it an ID if it had
// none
export function editComment(
  lines: string[],
  thread: TexThread,
  change: ((t: TexThread) => TexThread) | null,
): string[] {
  const before = lines.slice(0, thread.lineno - 1)
  const after = lines.slice(thread.lineno - 1 + thread.nlines)
  if (change === null) return [...before, ...after]
  const changed = change(thread)
  const rendered = renderComment({
    ...changed,
    id: changed.id ?? newCommentId(),
  })
  return [...before, ...rendered, ...after]
}

// Tints comment blocks in the editor, so they read apart from the text
export const commentHighlighter = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet
    constructor(view: EditorView) {
      this.decorations = this.build(view)
    }
    update(u: ViewUpdate) {
      if (u.docChanged) this.decorations = this.build(u.view)
    }
    build(view: EditorView): DecorationSet {
      const doc = view.state.doc
      const builder = new RangeSetBuilder<Decoration>()
      const lines = doc.toString().split("\n")
      for (const t of parseComments(lines)) {
        for (let n = t.lineno; n < t.lineno + t.nlines; n++) {
          const from = doc.line(n).from
          builder.add(
            from,
            from,
            Decoration.line({
              class: t.resolved ? "cm-texComment cm-resolved" : "cm-texComment",
            }),
          )
        }
      }
      return builder.finish()
    }
  },
  { decorations: (v) => v.decorations },
)
