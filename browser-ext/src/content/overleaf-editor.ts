/**
 * Marks problems with what an Overleaf document shows from its Calkit
 * project in the editor, the way a linter would.
 *
 * Runs in the page's own world, since only there can it reach the editor,
 * through the hook Overleaf offers browser extensions for adding CodeMirror
 * extensions. Only the extension's world can reach the hub, so the two
 * talk with window messages: this side says what the document cites and
 * where, and the other says what's wrong and fills the hover tooltips.
 */
import { type Citation, citationsIn } from "../core/latex";

/** A command showing project content, and where it is in the document. */
export interface EditorCitation {
  from: number;
  to: number;
  /** 1-based, as Overleaf numbers lines. */
  line: number;
  column: number;
  citation: Citation;
}

export type FromEditor =
  | {
      calkit: "editor";
      type: "citations";
      version: number;
      items: EditorCitation[];
    }
  | {
      calkit: "editor";
      type: "tooltip";
      id: string;
      version: number;
      index: number;
    }
  // The open document's text, or whether lines were replaced in it
  | { calkit: "editor"; type: "text"; reqId: number; text: string | null }
  | { calkit: "editor"; type: "replaced"; reqId: number; error: string | null }
  // Overleaf's file tree: its documents' IDs and its other files' Git
  // hashes, by path, or null if it can't be found
  | {
      calkit: "editor";
      type: "tree";
      reqId: number;
      tree: {
        docs: { path: string; id: string }[];
        files: { path: string; hash: string }[];
      } | null;
    };

export type ToEditor =
  | {
      calkit: "lint";
      type: "problems";
      version: number;
      items: { index: number; severity: "error" | "warning" }[];
    }
  | { calkit: "lint"; type: "goto"; line: number; column: number }
  // Text selected, e.g., to comment on it, by line (from 1) and column
  | {
      calkit: "lint";
      type: "select";
      from: { line: number; column: number };
      to: { line: number; column: number };
    }
  // From a script put in after the extension reloaded, which missed the
  // last scan
  | { calkit: "lint"; type: "rescan" }
  | { calkit: "lint"; type: "read"; reqId: number }
  | { calkit: "lint"; type: "tree"; reqId: number }
  // Lines from `line` (from 1) replaced, if they're still `expected`
  | {
      calkit: "lint";
      type: "replace";
      reqId: number;
      line: number;
      expected: string[];
      insert: string[];
    };

// CodeMirror comes from Overleaf's bundle at runtime, so it's untyped here
type View = any;

let version = 0;
let citations: EditorCitation[] = [];
let tooltips = 0;
// Whether the extension has checked the document, which it only does for
// one linked to a Calkit project, so a tooltip would have something in it
let checked = false;
// The editor last scanned, and how to mark problems in it
let active: {
  view: View;
  mark: (items: ToEditor & { type: "problems" }) => void;
} | null = null;

type Without<T> = T extends unknown ? Omit<T, "calkit"> : never;

function post(message: Without<FromEditor>): void {
  window.postMessage({ calkit: "editor", ...message }, window.location.origin);
}

function scan(view: View): void {
  const doc = view.state.doc;
  const items: EditorCitation[] = [];
  for (let n = 1; n <= doc.lines; n++) {
    const line = doc.line(n);
    if (!line.text.includes("\\")) {
      continue;
    }
    for (const match of citationsIn(line.text)) {
      items.push({
        from: line.from + match.start,
        to: line.from + match.end,
        line: n,
        column: match.start,
        citation: match.citation,
      });
    }
  }
  version++;
  citations = items;
  post({ type: "citations", version, items });
}

window.addEventListener("UNSTABLE_editor:extensions", (event) => {
  const { CodeMirror, extensions } = (event as CustomEvent).detail;
  const {
    Decoration,
    EditorView,
    StateEffect,
    StateField,
    ViewPlugin,
    hoverTooltip,
  } = CodeMirror;
  const setProblems = StateEffect.define();
  const problems = StateField.define({
    create: () => Decoration.none,
    update(value: any, tr: any) {
      let next = value.map(tr.changes);
      for (const effect of tr.effects) {
        if (effect.is(setProblems)) {
          next = effect.value;
        }
      }
      return next;
    },
    provide: (field: any) => EditorView.decorations.from(field),
  });
  const scanner = ViewPlugin.define((view: View) => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const mark = (message: ToEditor & { type: "problems" }) => {
      if (message.version !== version) {
        return;
      }
      const length = view.state.doc.length;
      const ranges = message.items.flatMap(({ index, severity }) => {
        const item = citations[index];
        return item && item.to <= length
          ? [
              Decoration.mark({
                class: `calkit-problem calkit-problem-${severity}`,
              }).range(item.from, item.to),
            ]
          : [];
      });
      view.dispatch({ effects: setProblems.of(Decoration.set(ranges, true)) });
    };
    active = { view, mark };
    timer = setTimeout(() => scan(view), 500);
    return {
      update(update: any) {
        if (update.docChanged) {
          // Kept where they are until the next scan, so marks and hovers
          // in the meantime land on the right text
          citations = citations.map((item) => ({
            ...item,
            from: update.changes.mapPos(item.from),
            to: update.changes.mapPos(item.to, 1),
          }));
          active = { view, mark };
          clearTimeout(timer);
          timer = setTimeout(() => scan(view), 500);
        }
      },
      destroy() {
        clearTimeout(timer);
        if (active?.view === view) {
          active = null;
        }
      },
    };
  });
  const tooltip = hoverTooltip(
    (_view: View, pos: number) => {
      const index = citations.findIndex(
        (item) => pos >= item.from && pos <= item.to,
      );
      if (index < 0 || !checked) {
        return null;
      }
      const item = citations[index];
      return {
        pos: item.from,
        end: item.to,
        above: true,
        create() {
          // Filled from the extension's world, which finds it by its id
          const dom = document.createElement("div");
          dom.id = `calkit-tooltip-${++tooltips}`;
          post({ type: "tooltip", id: dom.id, version, index });
          return { dom };
        },
      };
    },
    { hoverTime: 300 },
  );
  const theme = EditorView.baseTheme({
    ".calkit-problem-error": {
      textDecoration: "underline wavy #e5484d",
      textDecorationSkipInk: "none",
      textUnderlineOffset: "3px",
    },
    ".calkit-problem-warning": {
      textDecoration: "underline wavy #d69e2e",
      textDecorationSkipInk: "none",
      textUnderlineOffset: "3px",
    },
  });
  extensions.push(problems, scanner, tooltip, theme);
});

/**
 * Replace lines in the open document, as one change it can undo, unless
 * they've changed, e.g., by someone else editing them meanwhile. Says
 * what went wrong, if anything.
 */
function replaceLines(message: ToEditor & { type: "replace" }): string | null {
  if (!active) {
    return "The editor isn't open.";
  }
  const doc = active.view.state.doc;
  const { line, expected, insert } = message;
  const last = line + expected.length - 1;
  if (line < 1 || last > doc.lines || line > doc.lines + 1) {
    return "The source changed. Try again.";
  }
  for (let n = line; n <= last; n++) {
    if (doc.line(n).text !== expected[n - line]) {
      return "The source changed. Try again.";
    }
  }
  const text = insert.map((l) => `${l}\n`).join("");
  let from: number;
  let to: number;
  if (line > doc.lines) {
    // After the last line, which has no line break of its own
    from = to = doc.length;
    active.view.dispatch({
      changes: { from, to, insert: `\n${text.slice(0, -1)}` },
    });
    return null;
  }
  from = doc.line(line).from;
  to = expected.length ? Math.min(doc.line(last).to + 1, doc.length) : from;
  const atEnd = expected.length && doc.line(last).to === doc.length;
  active.view.dispatch({
    changes: { from, to, insert: atEnd ? text.slice(0, -1) : text },
    scrollIntoView: false,
  });
  return null;
}

/**
 * Overleaf's file tree, from the data its React components share, found by
 * walking up from one of them, since Overleaf doesn't expose it otherwise.
 */
function getFileTree(): Extract<FromEditor, { type: "tree" }>["tree"] {
  interface Folder {
    name: string;
    docs?: { _id: string; name: string }[];
    fileRefs?: { name: string; hash?: string }[];
    folders?: Folder[];
  }
  const start = document.querySelector(
    "[data-file-id], .cm-content, #ide-root",
  );
  const key =
    start && Object.keys(start).find((k) => k.startsWith("__reactFiber"));
  let fiber = key ? (start as any)[key] : null;
  let root: Folder | null = null;
  for (let i = 0; fiber && i < 1000 && !root; i++, fiber = fiber.return) {
    const data = fiber.memoizedProps?.value?.fileTreeData;
    if (data && Array.isArray(data.docs)) {
      root = data;
    }
  }
  if (!root) {
    return null;
  }
  const docs: { path: string; id: string }[] = [];
  const files: { path: string; hash: string }[] = [];
  const walk = (folder: Folder, prefix: string): boolean => {
    for (const doc of folder.docs ?? []) {
      docs.push({ path: prefix + doc.name, id: doc._id });
    }
    for (const file of folder.fileRefs ?? []) {
      if (!file.hash) {
        return false;
      }
      files.push({ path: prefix + file.name, hash: file.hash });
    }
    return (folder.folders ?? []).every((f) => walk(f, `${prefix}${f.name}/`));
  };
  return walk(root, "") ? { docs, files } : null;
}

window.addEventListener("message", (event) => {
  if (event.source !== window || event.data?.calkit !== "lint") {
    return;
  }
  const message = event.data as ToEditor;
  if (message.type === "problems") {
    checked = true;
    active?.mark(message);
  } else if (message.type === "rescan") {
    if (active) {
      scan(active.view);
    }
  } else if (message.type === "read") {
    post({
      type: "text",
      reqId: message.reqId,
      text: active ? active.view.state.doc.toString() : null,
    });
  } else if (message.type === "tree") {
    post({ type: "tree", reqId: message.reqId, tree: getFileTree() });
  } else if (message.type === "replace") {
    post({
      type: "replaced",
      reqId: message.reqId,
      error: replaceLines(message),
    });
  } else if (message.type === "select" && active) {
    const doc = active.view.state.doc;
    const at = ({ line, column }: { line: number; column: number }) => {
      const found = doc.line(Math.min(Math.max(line, 1), doc.lines));
      return Math.min(found.from + column, found.to);
    };
    active.view.dispatch({
      selection: { anchor: at(message.from), head: at(message.to) },
      scrollIntoView: true,
    });
    active.view.focus();
  } else if (message.type === "goto" && active) {
    const doc = active.view.state.doc;
    if (message.line < 1 || message.line > doc.lines) {
      return;
    }
    const line = doc.line(message.line);
    active.view.dispatch({
      selection: { anchor: Math.min(line.from + message.column, line.to) },
      scrollIntoView: true,
    });
    active.view.focus();
  }
});

// Asks an editor that's already open to take the extension above
window.dispatchEvent(new Event("editor:extension-loaded"));
