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
import {
  type Citation,
  type TypedNumber,
  citationsIn,
  typedNumbersInDocument,
} from "../core/latex";

/**
 * A command showing project content, or a number or table typed in that
 * looks like a result, and where it is in the document.
 */
export type EditorItem = {
  from: number;
  to: number;
  /** 1-based, as Overleaf numbers lines. */
  line: number;
  column: number;
} & (
  | { citation: Citation; typed?: undefined; table?: undefined }
  | { typed: TypedNumber; citation?: undefined; table?: undefined }
  | {
      /** The table's numbers, and where its \\begin command ends, which
       * is all that's marked, though hovering anywhere in it shows why. */
      table: { numbers: TypedNumber[]; markTo: number };
      citation?: undefined;
      typed?: undefined;
    }
);

export type FromEditor =
  | {
      calkit: "editor";
      type: "citations";
      version: number;
      items: EditorItem[];
    }
  | { calkit: "editor"; type: "replaced"; id: string; error?: string }
  | {
      calkit: "editor";
      type: "tooltip";
      id: string;
      version: number;
      index: number;
    };

export type ToEditor =
  | {
      calkit: "lint";
      type: "problems";
      version: number;
      items: { index: number; severity: "error" | "warning" }[];
    }
  | { calkit: "lint"; type: "goto"; line: number; column: number }
  | {
      calkit: "lint";
      type: "replace";
      /** Echoed in the reply. */
      id: string;
      version: number;
      index: number;
      text: string;
      /** Add \\usepackage{calkit} to the preamble if it isn't there. */
      usePackage: boolean;
      /** Add the text to the end of the item's line instead, e.g., a
       * comment saying its numbers aren't results. */
      endOfLine?: boolean;
    };

// CodeMirror comes from Overleaf's bundle at runtime, so it's untyped here
type View = any;

let version = 0;
let citations: EditorItem[] = [];
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
  const items: EditorItem[] = [];
  const lines: string[] = [];
  for (let n = 1; n <= doc.lines; n++) {
    lines.push(doc.line(n).text);
  }
  const typed = typedNumbersInDocument(lines);
  for (const table of typed.tables) {
    const from = doc.line(table.start.line + 1).from + table.start.column;
    items.push({
      from,
      to: doc.line(table.end.line + 1).from + table.end.column,
      line: table.start.line + 1,
      column: table.start.column,
      table: {
        numbers: table.numbers,
        markTo: from + `\\begin{${table.env}}`.length,
      },
    });
  }
  for (const { line: i, match } of typed.numbers) {
    const line = doc.line(i + 1);
    items.push({
      from: line.from + match.start,
      to: line.from + match.end,
      line: i + 1,
      column: match.start,
      typed: match.number,
    });
  }
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
  citations = items.sort((a, b) => a.from - b.from);
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
              }).range(item.from, item.table?.markTo ?? item.to),
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
          citations = citations.map((item): EditorItem => {
            const from = update.changes.mapPos(item.from);
            const to = update.changes.mapPos(item.to, 1);
            return item.table
              ? {
                  ...item,
                  from,
                  to,
                  table: {
                    ...item.table,
                    markTo: update.changes.mapPos(item.table.markTo, 1),
                  },
                }
              : { ...item, from, to };
          });
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
      // The innermost, e.g., a \\ckvalue in a typed table
      let index = -1;
      for (const [i, item] of citations.entries()) {
        const inner =
          index < 0 ||
          item.to - item.from < citations[index].to - citations[index].from;
        if (pos >= item.from && pos <= item.to && inner) {
          index = i;
        }
      }
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

window.addEventListener("message", (event) => {
  if (event.source !== window || event.data?.calkit !== "lint") {
    return;
  }
  const message = event.data as ToEditor;
  if (message.type === "problems") {
    checked = true;
    active?.mark(message);
  } else if (message.type === "replace") {
    replace(message);
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

/**
 * Swap a typed number or table for what the extension says shows it
 * instead, e.g., a \\ckvalue, or mark its line as not results, as one
 * edit, so it's one step in Overleaf's history.
 */
function replace(message: ToEditor & { type: "replace" }): void {
  const item = citations[message.index];
  const view = active?.view;
  const fail = (error: string) =>
    post({ type: "replaced", id: message.id, error });
  const changed = "The document changed; hover over it again";
  if (!view || message.version !== version || !(item?.typed || item?.table)) {
    return fail(changed);
  }
  const doc = view.state.doc;
  const now = doc.sliceString(item.from, item.to);
  if (item.typed ? now !== item.typed.text : !now.startsWith("\\begin")) {
    return fail(changed);
  }
  const end = doc.lineAt(item.from).to;
  const changes = message.endOfLine
    ? [{ from: end, to: end, insert: message.text }]
    : [{ from: item.from, to: item.to, insert: message.text }];
  const text = doc.toString();
  const body = text.search(/^[^%\n]*\\begin\s*\{document\}/m);
  const loaded =
    /^[^%\n]*\\usepackage\s*(?:\[[^\]]*\])?\s*\{[^}]*\bcalkit\b[^}]*\}/m.test(
      text,
    );
  if (message.usePackage && body >= 0 && !loaded) {
    changes.push({ from: body, to: body, insert: "\\usepackage{calkit}\n" });
  }
  view.dispatch({ changes, userEvent: "input" });
  post({ type: "replaced", id: message.id });
}

// Asks an editor that's already open to take the extension above
window.dispatchEvent(new Event("editor:extension-loaded"));
