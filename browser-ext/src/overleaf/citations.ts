/**
 * What the editor shows from the project, e.g., \ckvalue and typed numbers
 * that could be linked: checking it, the cards for it, and Insert.
 */
import { renderFailure } from "../core/pickers";
import {
  type Citation,
  type CitationProblem,
  type PrintedMatch,
  type PrintedNumbers,
  type ResultValue,
  type TableFile,
  type TypedNumber,
  IGNORE_COMMENT,
  citationProblems,
  citationText,
  notebookOfValuesPath,
  printedNumberMatches,
  roundedLike,
  typedNumberCitation,
  typedNumberMatches,
  getTypedNumberLink,
  typedTableMatches,
  getTypedTableLink,
} from "../core/latex";
import { isExtensionAlive, send } from "../core/messages";
import { type OverleafLinkPublic, type Provenance } from "../core/types";
import {
  clear,
  el,
  errorMessage,
  loading,
  STYLES,
  textInput,
} from "../core/ui";
import { type EditorItem, type FromEditor, type ToEditor } from "./editor";
import {
  lastCheck,
  watching,
  currentLink,
  provenanceFor,
  projectValues,
  projectPrintedNumbers,
  startRun,
  projectTables,
  citationProvenance,
  linkKey,
  syncOverleaf,
  syncNow,
  renderRuns,
  drawRuns,
  editorReplies,
  showInPanel,
  recheckAfterEdit,
} from "./index";
import { valueText, renderProvenance } from "./origins";
import { drawPdfBoxes, scheduleReviewThreads } from "./pdf-viewer";
import { markRailTab, drawRail } from "./sidebar";

/**
 * Type into Overleaf's editor at the cursor, as if the user had.
 *
 * CodeMirror keeps its selection while the panel has focus and puts it
 * back when the editor is focused again, and it handles an insertText
 * command like typing, so the edit lands in Overleaf's history and syncs.
 * Falls back to the clipboard when there's no editor to type into, e.g.,
 * with a PDF open instead of a .tex file.
 */
async function insertIntoEditor(text: string): Promise<"inserted" | "copied"> {
  const editor = document.querySelector<HTMLElement>(".cm-content");
  if (editor) {
    editor.focus();
    if (document.execCommand("insertText", false, text)) {
      return "inserted";
    }
  }
  await navigator.clipboard.writeText(text);
  return "copied";
}

/** One problem, colored by how bad it is. */
export function problemLine(problem: CitationProblem): HTMLElement {
  return el("div", {
    class: "small",
    style: {
      color:
        problem.severity === "error"
          ? "var(--ck-danger)"
          : problem.severity === "warning"
          ? "var(--ck-warning)"
          : "var(--ck-main)",
      fontWeight: "600",
    },
    text: problem.message,
  });
}

export type Without<T> = T extends unknown ? Omit<T, "calkit"> : never;

// The editor's count of scans, which go up with each edit, so the first
// one, when it opens, isn't taken for an edit
let lastEditorVersion: number | null = null;

// What the editor last said the open document shows, and what's wrong with
// each, by its index there
export let editorCitations: { version: number; items: EditorItem[] } | null =
  null;
export let editorProblems: {
  version: number;
  found: CitationProblem[][];
} | null = null;

export function toEditor(message: Without<ToEditor>): void {
  window.postMessage({ calkit: "lint", ...message }, window.location.origin);
}

/** Find what's wrong with what the open document shows, and mark it. */
export async function checkCitations(): Promise<void> {
  const link = currentLink;
  const snapshot = editorCitations;
  if (!link || !snapshot) {
    return;
  }
  const found: CitationProblem[][] = [];
  // A few at a time, since each has the hub read the project
  let next = 0;
  const work = async () => {
    while (next < snapshot.items.length) {
      const i = next++;
      const item = snapshot.items[i];
      try {
        // What's typed is only marked where the project has something it
        // could be linked to
        if (item.typed) {
          const linkable = getTypedNumberLink(
            item.typed,
            await projectValues(link),
          );
          found[i] = linkable ? [linkable] : [];
        } else if (item.table) {
          const linkable = getTypedTableLink(
            { numbers: item.table.numbers },
            await projectTables(link),
          );
          found[i] = linkable ? [linkable] : [];
        } else {
          found[i] = citationProblems(
            item.citation,
            await citationProvenance(link, item.citation),
          );
        }
      } catch {
        found[i] = [];
      }
    }
  };
  await Promise.all([work(), work(), work(), work()]);
  if (editorCitations !== snapshot || currentLink !== link) {
    return;
  }
  editorProblems = { version: snapshot.version, found };
  drawRuns();
  drawRail();
  markRailTab();
  toEditor({
    type: "problems",
    version: snapshot.version,
    items: found.flatMap((problems, index) =>
      problems.length
        ? [
            {
              index,
              severity: problems.some((p) => p.severity === "error")
                ? "error"
                : problems.some((p) => p.severity === "warning")
                ? "warning"
                : "link",
            },
          ]
        : [],
    ),
  });
  void drawPdfBoxes();
}

const TOOLTIP_STYLES = `
.tip {
  color: var(--ck-fg);
  background: var(--ck-bg);
  padding: 8px 10px;
  max-width: 360px;
  max-height: 50vh;
  overflow-y: auto;
}
`;

/** Fill a tooltip the editor opened over something the document shows. */
export async function fillTooltip(
  id: string,
  version: number,
  index: number,
): Promise<void> {
  const link = currentLink;
  const item =
    editorCitations?.version === version
      ? editorCitations.items[index]
      : undefined;
  if (!link || !item) {
    return;
  }
  // Made as the tooltip opens, so it may not be on the page quite yet
  let host = document.getElementById(id);
  for (let i = 0; i < 20 && !host; i++) {
    await new Promise((resolve) => requestAnimationFrame(resolve));
    host = document.getElementById(id);
  }
  if (!host || host.shadowRoot) {
    return;
  }
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = STYLES + TOOLTIP_STYLES;
  const body = el("div", { class: "tip" });
  root.append(style, body);
  await fillCard(body, link, item, { version, index });
}

/**
 * Where something the document shows came from, and how to fix what's
 * wrong with it, as its hover card and the sidebar show it.
 */
export async function fillCard(
  body: HTMLElement,
  link: OverleafLinkPublic,
  item: EditorItem,
  at: { version: number; index: number },
): Promise<void> {
  clear(body).append(loading());
  try {
    if (item.typed) {
      const [values, printed] = await Promise.all([
        projectValues(link),
        projectPrintedNumbers(link),
      ]);
      clear(body);
      renderTyped(body, link, item.typed, values, printed, at);
      return;
    }
    if (item.table) {
      const tables = await projectTables(link);
      clear(body);
      renderTypedTable(body, link, item.table.numbers, tables, at);
      return;
    }
    const provenance = await citationProvenance(link, item.citation);
    clear(body);
    renderProvenance(body, link, item.citation, provenance, false);
    body.append(bringUpToDate(link, item.citation, provenance));
  } catch (e) {
    clear(body).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
  }
}

// Replacements asked of the editor, by id, until it says how they went
const replacing = new Map<string, (error: string | undefined) => void>();
let replacements = 0;

/**
 * Have the editor swap something typed for what shows it instead, then
 * sync, so it shows up. Says why if the editor couldn't.
 *
 * The edit closes the tooltip that asked for it, so a failed sync is shown
 * in the panel.
 */
async function replaceInEditor(
  link: OverleafLinkPublic,
  at: { version: number; index: number },
  text: string,
  endOfLine = false,
): Promise<string | undefined> {
  const id = `replace-${++replacements}`;
  const error = await new Promise<string | undefined>((resolve) => {
    const timer = setTimeout(() => {
      replacing.delete(id);
      resolve("The editor didn't respond; reload the page and try again");
    }, 5000);
    replacing.set(id, (error) => {
      clearTimeout(timer);
      replacing.delete(id);
      resolve(error);
    });
    toEditor({
      type: "replaceItem",
      id,
      ...at,
      text,
      usePackage: !endOfLine,
      endOfLine,
    });
  });
  if (error) {
    return error;
  }
  // Overleaf saves an edit a moment after it's made, and a sync started
  // first would miss it
  void new Promise((resolve) => setTimeout(resolve, 3000))
    .then(() =>
      send({
        type: "overleaf.sync",
        owner: link.project_owner_name,
        project: link.project_name,
        path: link.path,
      }),
    )
    .catch((e) =>
      showInPanel((body) =>
        body.append(errorMessage(e instanceof Error ? e.message : String(e))),
      ),
    );
  return undefined;
}

/**
 * A way to say a typed number or table isn't a result, e.g., one quoted
 * from a datasheet, which marks its line with `% calkit: ignore`.
 */
function ignoreRow(
  link: OverleafLinkPublic,
  at: { version: number; index: number },
  message: HTMLElement,
  what: string,
): HTMLElement {
  return el("div", { class: "row", style: { marginTop: "6px" } }, [
    el("div", {
      class: "grow dim small",
      text: `Not ${what}, e.g., quoted from somewhere else?`,
    }),
    el("button", {
      class: "action secondary",
      text: "Ignore",
      onClick: async () => {
        const error = await replaceInEditor(
          link,
          at,
          ` ${IGNORE_COMMENT}`,
          true,
        );
        if (error) {
          clear(message).append(errorMessage(error));
        }
      },
    }),
  ]);
}

/**
 * A typed number, what's wrong with it, and the results that could show
 * it instead, which replace it with a \\ckvalue and sync.
 */
function renderTyped(
  container: HTMLElement,
  link: OverleafLinkPublic,
  number: TypedNumber,
  values: ResultValue[],
  printed: PrintedNumbers[],
  at: { version: number; index: number },
): void {
  const { exact, close } = typedNumberMatches(number, values);
  const fromNotebooks = exact.length
    ? []
    : printedNumberMatches(number, printed);
  const canWrite = link.current_user_access !== "read";
  const message = el("div", { class: "small", style: { marginTop: "6px" } });
  const use = async (value: ResultValue) => {
    const text = citationText(typedNumberCitation(number, value));
    const error = await replaceInEditor(link, at, text);
    if (error) {
      clear(message).append(errorMessage(error));
    }
  };
  const row = (value: ResultValue) => {
    const reads = roundedLike(number, value.value);
    return el("div", { class: "row" }, [
      el("div", { class: "grow" }, [
        el("div", { class: "small", text: `${value.path}: ${value.key}` }),
        el("div", {
          class: "dim small",
          text:
            reads === number.text
              ? String(value.value)
              : `${value.value}, which would read ${reads}`,
        }),
      ]),
      canWrite
        ? el("button", {
            class: "action secondary",
            text: "Link",
            onClick: () => void use(value),
          })
        : null,
    ]);
  };
  // A notebook's printed number is linked once the variable holding it is
  // added as a value and the pipeline has saved it, since the variable may
  // hold more than this number, e.g., a dict of them, whose key the saved
  // value then shows
  const printedRow = (match: PrintedMatch) => {
    const variable = el("select", { class: "grow" }) as HTMLSelectElement;
    for (const name of match.variables) {
      variable.append(el("option", { text: name, value: name }));
    }
    const other = el("input", {
      class: "grow",
      placeholder: "Variable",
    }) as HTMLInputElement;
    const choice = match.variables.length ? variable : other;
    const useIt = el("button", {
      class: "action secondary",
      text: "Use this",
    }) as HTMLButtonElement;
    useIt.addEventListener("click", async () => {
      const name = choice.value.trim();
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) {
        clear(message).append(errorMessage("Not a variable name"));
        return;
      }
      useIt.disabled = true;
      try {
        await send({
          type: "project.addCellOutput",
          owner: link.project_owner_name,
          project: link.project_name,
          notebook: match.notebook,
          stage: match.stage,
          cell_id: match.cell,
          variable_name: name,
        });
        clear(message).append(
          el("div", {
            class: "small",
            text: `Saving ${name} on each run. Once saved, link the number here.`,
          }),
          el("div", { class: "actions" }, [
            el("button", {
              class: "action",
              text: "Run and sync",
              onClick: () => void startRun(link),
            }),
          ]),
        );
      } catch (e) {
        useIt.disabled = false;
        clear(message).append(
          errorMessage(e instanceof Error ? e.message : String(e)),
        );
      }
    });
    return el("div", { class: "stack", style: { marginTop: "4px" } }, [
      el("div", {
        class: "small",
        text: `${match.notebook}, cell ${match.cell_index + 1}: ${
          match.printed
        }`,
      }),
      canWrite ? el("div", { class: "row" }, [choice, useIt]) : null,
    ]);
  };
  const linkable = getTypedNumberLink(number, values);
  container.append(
    el("div", { class: "name", text: number.text }),
    ...(linkable ? [problemLine(linkable)] : []),
  );
  if (exact.length) {
    container.append(
      el("div", {
        class: "dim small",
        text: "Linked, it updates whenever the analysis does:",
      }),
      ...exact.slice(0, 5).map(row),
    );
  } else {
    if (close.length) {
      container.append(
        el("div", {
          class: "dim small",
          text: "The nearest results, if it's a mistyped or outdated copy:",
        }),
        ...close.map(row),
      );
    }
    if (fromNotebooks.length) {
      container.append(
        el("div", {
          class: "dim small",
          style: { marginTop: "6px" },
          text: "Printed by a notebook; save the variable it's in:",
        }),
        ...fromNotebooks.slice(0, 3).map(printedRow),
      );
    } else {
      container.append(
        el("div", {
          class: "dim small",
          style: { marginTop: "6px" },
          text:
            "If a notebook computes it, use Save as Output on its cell in " +
            "VS Code. A script can save it to a results file, e.g., " +
            "results.json.",
        }),
      );
    }
  }
  if (canWrite) {
    container.append(ignoreRow(link, at, message, "a result"));
  }
  container.append(message);
}

/**
 * A typed table, what's wrong with it, and the table files that could show
 * it instead, which replace it with a \\cktable and sync.
 */
function renderTypedTable(
  container: HTMLElement,
  link: OverleafLinkPublic,
  numbers: TypedNumber[],
  tables: TableFile[],
  at: { version: number; index: number },
): void {
  const matches = typedTableMatches({ numbers }, tables);
  const linkedTable = getTypedTableLink({ numbers }, tables);
  const canWrite = link.current_user_access !== "read";
  const message = el("div", { class: "small", style: { marginTop: "6px" } });
  container.append(
    el("div", {
      class: "name",
      text: `Table, ${numbers.length} number${numbers.length === 1 ? "" : "s"}`,
    }),
    ...(linkedTable ? [problemLine(linkedTable)] : []),
  );
  if (matches.length) {
    container.append(
      el("div", {
        class: "dim small",
        text: "Linked, it updates whenever the analysis does:",
      }),
      ...matches.slice(0, 3).map(({ path, matched }) =>
        el("div", { class: "row" }, [
          el("div", { class: "grow" }, [
            el("div", { class: "small", text: path }),
            el("div", {
              class: "dim small",
              text:
                matched === numbers.length
                  ? `Has all ${matched} numbers`
                  : `Has ${matched} of the ${numbers.length} numbers; ` +
                    "the rest may be outdated",
            }),
          ]),
          canWrite
            ? el("button", {
                class: "action secondary",
                text: "Link",
                onClick: async () => {
                  const error = await replaceInEditor(
                    link,
                    at,
                    citationText({ kind: "table", path, options: "" }),
                  );
                  if (error) {
                    clear(message).append(errorMessage(error));
                  }
                },
              })
            : null,
        ]),
      ),
    );
  } else {
    container.append(
      el("div", {
        class: "dim small",
        text:
          "Have the script that computes it write the table as TeX, " +
          "e.g., with pandas' to_latex, so the paper can show it from there.",
      }),
    );
  }
  if (canWrite) {
    container.append(ignoreRow(link, at, message, "results"));
  }
  container.append(message);
}

/**
 * A way to bring what the document shows up to date from its card: syncing
 * what the project already has, or running what's stale first, which syncs
 * when it's done.
 */
function bringUpToDate(
  link: OverleafLinkPublic,
  citation: Citation,
  provenance: Provenance,
): HTMLElement {
  const path = provenance.path;
  // What the next sync would bring, by where Overleaf gets its copy
  const status =
    lastCheck && linkKey(lastCheck.link) === linkKey(link)
      ? lastCheck.status
      : null;
  const waiting = (status?.files_to_push ?? []).some(
    (f) =>
      f.project_path === path ||
      f.project_path.endsWith(`/_calkit/${path}`) ||
      (citation.kind === "value" &&
        f.project_path.endsWith("/_calkit/values.tex")),
  );
  // A frozen stage won't rerun, and a manual step needs a person
  const stale =
    provenance.stale_reason === "pipeline" &&
    provenance.stage_kind !== "manual-step";
  if (stale) {
    return renderRuns(link, true);
  }
  const box = el("div", { style: { marginTop: "6px" } });
  if (waiting) {
    const { button, message } = syncNow(link, link.path);
    box.append(el("div", { class: "actions" }, [button]), message);
  }
  return box;
}

/**
 * Hear from the editor, through the script in the page's world, what the
 * open document shows and when a tooltip opens over it.
 *
 * The page can post these too, so all they can do is have the linked
 * project's provenance looked up and shown, which the page could show
 * anyway.
 */
export function watchEditor(): void {
  const listener = (event: MessageEvent) => {
    if (event.source !== window || event.data?.calkit !== "editor") {
      return;
    }
    // Cut off by the extension reloading, so the script put in after
    // answers instead, rather than this one taking a tooltip it can't fill
    if (!isExtensionAlive()) {
      window.removeEventListener("message", listener);
      return;
    }
    const message = event.data as FromEditor;
    if (message.type === "citations") {
      editorCitations = { version: message.version, items: message.items };
      drawRail();
      void checkCitations();
      // The open file changed, and maybe its comments with it
      scheduleReviewThreads();
      // Overleaf saves edits as they're made, so they're there to sync
      if (lastEditorVersion !== null && message.version !== lastEditorVersion) {
        recheckAfterEdit(5000);
      }
      lastEditorVersion = message.version;
    } else if (message.type === "tooltip") {
      void fillTooltip(message.id, message.version, message.index);
    } else if (
      message.type === "text" ||
      message.type === "replaced" ||
      message.type === "tree"
    ) {
      editorReplies.get(message.reqId)?.(message);
      editorReplies.delete(message.reqId);
    } else if (message.type === "replacedItem") {
      replacing.get(message.id)?.(message.error);
    }
  };
  window.addEventListener("message", listener, { signal: watching.signal });
  // What the open document shows, in case this script came in after the
  // editor last said
  toEditor({ type: "rescan" });
}

/**
 * Insert a figure, table, or value from the project at the cursor.
 *
 * What's inserted is a calkit.sty command naming it by its path in the
 * project. The next sync brings what it cites into the paper's _calkit
 * folder, so there's nothing to set up: no map-paths or json-to-latex
 * stage, and no copying files by hand.
 */
export function renderInsert(
  link: OverleafLinkPublic,
  path: string,
  reload: () => void,
): HTMLElement {
  const owner = link.project_owner_name;
  const project = link.project_name;
  const list = el("div", { class: "stack", style: { marginTop: "6px" } });
  const message = el("div", { class: "small" });
  const format = textInput({ placeholder: "Format, e.g., .2f (optional)" });
  const insert = async (citation: Citation) => {
    try {
      const how = await insertIntoEditor(citationText(citation));
      const sync = async () => {
        clear(message).append(loading("Syncing"));
        // Overleaf saves an edit a moment after it's made, and a sync
        // started first would miss it
        await new Promise((resolve) => setTimeout(resolve, 3000));
        try {
          await syncOverleaf(owner, project, path);
          reload();
        } catch (e) {
          clear(message).append(
            errorMessage(e instanceof Error ? e.message : String(e)),
          );
        }
      };
      // Synced right away so it shows up, unless it still has to be pasted
      if (how === "inserted") {
        await sync();
        return;
      }
      clear(message).append(
        el("div", {
          class: "dim small",
          text:
            "Copied; paste it where it should go, then sync to bring it " +
            "into the paper. The document needs \\usepackage{calkit} in " +
            "its preamble.",
        }),
        el("div", { class: "actions" }, [
          el("button", {
            class: "action secondary",
            text: "Sync now",
            onClick: (e: Event) => {
              (e.currentTarget as HTMLButtonElement).disabled = true;
              void sync();
            },
          }),
        ]),
      );
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  };
  const row = (title: string, detail: string, onClick: () => void) =>
    el("div", { class: "row" }, [
      el("div", { class: "grow" }, [
        el("div", { class: "small", text: title }),
        el("div", { class: "dim small", text: detail }),
      ]),
      el("button", {
        class: "action secondary",
        text: "Insert",
        onClick,
      }),
    ]);
  const showFigures = async () => {
    clear(list).append(loading());
    try {
      const page = await send({ type: "project.figures", owner, project });
      clear(list);
      for (const figure of page.items) {
        list.append(
          row(figure.title, figure.path, () =>
            insert({
              kind: "figure",
              path: figure.path,
              options: "width=\\linewidth",
            }),
          ),
        );
      }
      if (!page.items.length) {
        list.append(el("div", { class: "dim small", text: "No figures" }));
      }
    } catch (e) {
      clear(list).append(renderFailure(e, { onSignedIn: reload }));
    }
  };
  const showTables = async () => {
    clear(list).append(loading());
    try {
      // \cktable inputs TeX, so a CSV would need a stage to typeset it
      const tables = (
        await send({ type: "project.tables", owner, project })
      ).filter((table) => table.path.endsWith(".tex"));
      clear(list);
      for (const table of tables) {
        list.append(
          row(table.title, table.path, () =>
            insert({ kind: "table", path: table.path, options: "" }),
          ),
        );
      }
      if (!tables.length) {
        list.append(
          el("div", {
            class: "dim small",
            text: "No tables written as TeX",
          }),
        );
      }
    } catch (e) {
      clear(list).append(renderFailure(e, { onSignedIn: reload }));
    }
  };
  // A value is picked from inside a results file, so a file opens to its
  // keys rather than inserting anything
  const showValues = async () => {
    clear(list).append(loading());
    try {
      const results = await send({ type: "project.results", owner, project });
      const paths = [...new Set(results.map((result) => result.path))].filter(
        (resultPath) => /\.(json|ya?ml|toml)$/i.test(resultPath),
      );
      clear(list).append(format);
      for (const resultPath of paths) {
        // Values a notebook's cells make are cited by the notebook
        const citedAs = notebookOfValuesPath(resultPath) ?? resultPath;
        const keys = el("div", { style: { paddingLeft: "10px" } });
        const open = el("button", {
          class: "action secondary",
          text: "Open",
        });
        open.addEventListener("click", async () => {
          open.disabled = true;
          clear(keys).append(loading());
          try {
            const file = await provenanceFor(link, resultPath);
            clear(keys);
            if (file.value_error) {
              keys.append(errorMessage(file.value_error));
              return;
            }
            // Every leaf, by its dotted key, which is what \ckvalue takes
            const walk = (value: unknown, prefix: string) => {
              if (value === null || typeof value !== "object") {
                keys.append(
                  row(prefix, valueText(value), () =>
                    insert({
                      kind: "value",
                      path: citedAs,
                      key: prefix,
                      options: format.value.trim(),
                    }),
                  ),
                );
                return;
              }
              const entries = Array.isArray(value)
                ? value.map((item, i) => [String(i), item] as const)
                : Object.entries(value as Record<string, unknown>);
              for (const [name, item] of entries) {
                walk(item, prefix ? `${prefix}.${name}` : name);
              }
            };
            walk(file.value, "");
          } catch (e) {
            open.disabled = false;
            clear(keys).append(
              errorMessage(e instanceof Error ? e.message : String(e)),
            );
          }
        });
        list.append(
          el("div", { class: "row" }, [
            el("div", { class: "grow small", text: citedAs }),
            open,
          ]),
          keys,
        );
      }
      if (!paths.length) {
        list.append(
          el("div", {
            class: "dim small",
            text: "No JSON, YAML, or TOML results",
          }),
        );
      }
    } catch (e) {
      clear(list).append(renderFailure(e, { onSignedIn: reload }));
    }
  };
  return el("div", { style: { marginTop: "10px" } }, [
    el("div", {
      class: "small",
      style: { fontWeight: "600" },
      text: "Insert from project",
    }),
    el("div", { class: "actions" }, [
      el("button", {
        class: "action secondary",
        text: "Figure",
        onClick: () => void showFigures(),
      }),
      el("button", {
        class: "action secondary",
        text: "Table",
        onClick: () => void showTables(),
      }),
      el("button", {
        class: "action secondary",
        text: "Value",
        onClick: () => void showValues(),
      }),
    ]),
    list,
    message,
  ]);
}
