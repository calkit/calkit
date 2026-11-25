/**
 * The Calkit tab in Overleaf's left rail: the document's components and the
 * stages that make them.
 */
import calkitLogo from "../../public/icons/calkit.svg?raw";
import { projectUrl } from "../core/hub-url";
import { type Citation, citationText } from "../core/latex";
import { send } from "../core/messages";
import {
  type OverleafLinkPublic,
  type PipelineRun,
  type ProjectPipeline,
} from "../core/types";
import { clear, el, errorMessage, loading, STYLES } from "../core/ui";
import { type EditorItem } from "./editor";
import {
  currentProjectId,
  hubWebUrl,
  lastCheck,
  watching,
  observePage,
  currentLink,
  pipelineRuns,
  starting,
  linkKey,
  canWrite,
  activeRun,
  remountLauncher,
  syncNow,
  startRun,
  renderRuns,
  getRunActivity,
  openRunLog,
  checkingAfterSync,
  renderOpenLocally,
  renderWhere,
  getRunPlace,
  syncing,
  openPanel,
  drawPanelActions,
  drawPanelOrigins,
} from "./index";
import {
  editorCitations,
  editorProblems,
  toEditor,
  fillCard,
} from "./citations";

export const RAIL_TAB_ID = "calkit-rail-tab";
// What styles the tab and its pane, removed on shutting down
export let railStyle: HTMLStyleElement | null = null;
const RAIL_PANE_ID = "calkit-rail-pane";
// Whether Calkit's tab is the one showing in Overleaf's sidebar
export let railOpen = false;
let railPane: { host: HTMLElement; body: HTMLElement } | null = null;
// The component opened in the sidebar, kept through redraws, which come
// with every edit
let railCard: { key: string; element: HTMLElement } | null = null;
// The stage whose details are open in the sidebar
let railStage: string | null = null;
/**
 * A stage's details in the sidebar: why it's out of date, what it runs,
 * reads, and makes, with ways to open it in the editor on this machine
 * or on the hub.
 */
function renderStageCard(
  link: OverleafLinkPublic,
  pipeline: ProjectPipeline,
  name: string,
): HTMLElement {
  const base = projectUrl(
    hubWebUrl,
    link.project_owner_name,
    link.project_name,
  );
  const stage = pipeline.dvc_stages?.[name];
  const status = pipeline.stage_statuses[name];
  const cmd = [stage?.cmd ?? ""].flat().join(" ");
  // Environment locks and the like are inputs, but not anyone's concern
  const deps = (stage?.deps ?? []).filter(
    (d) => !d.startsWith(".calkit/") && !/(^|\/)(uv|pixi)\.lock$/.test(d),
  );
  // A manual step names its file in what it says to do, not to run it
  const manual = /calkit manual-step --message '((?:[^']|'\\'')*)'/.exec(cmd);
  const source = manual ? undefined : deps.find((d) => cmd.includes(d));
  const outs = (stage?.outs ?? []).map((o) =>
    typeof o === "string" ? o : Object.keys(o)[0],
  );
  const list = (label: string, paths: string[]) =>
    paths.length
      ? el("div", { class: "small" }, [
          el("span", { class: "dim", text: `${label} ` }),
          document.createTextNode(
            paths.length > 4
              ? `${paths.slice(0, 4).join(", ")}, and ${paths.length - 4} more`
              : paths.join(", "),
          ),
        ])
      : null;
  const changed = [
    ...(status?.modified_command ? ["its command"] : []),
    ...(status?.modified_inputs ?? []),
  ];
  const project = `${link.project_owner_name}/${link.project_name}`;
  return el("div", { class: "card" }, [
    changed.length
      ? el("div", {
          class: "small",
          style: { color: "var(--ck-warning)" },
          text: `Modified: ${changed.join(", ")}`,
        })
      : status?.missing_outputs.length
      ? el("div", {
          class: "small",
          style: { color: "var(--ck-warning)" },
          text: `Missing: ${status.missing_outputs.join(", ")}`,
        })
      : null,
    manual
      ? el("div", { class: "small" }, [
          el("span", { class: "dim", text: "Manual step: " }),
          document.createTextNode(manual[1].replace(/'\\''/g, "'")),
        ])
      : null,
    source
      ? el("div", { class: "small" }, [
          el("span", { class: "dim", text: "Runs " }),
          document.createTextNode(source),
        ])
      : null,
    list(
      "Reads",
      deps.filter((d) => d !== source),
    ),
    list("Makes", outs),
    el("div", { class: "actions", style: { alignItems: "center" } }, [
      link.local_path ? renderOpenLocally(project, source, true) : null,
      el("a", {
        class: "small",
        text: "Open in Calkit",
        href: `${base}/pipeline?stage=${encodeURIComponent(name)}`,
        attrs: { target: "_blank" },
      }),
    ]),
  ]);
}

export let railPipeline: {
  key: string;
  pipeline?: ProjectPipeline;
  error?: string;
} | null = null;

/**
 * A Calkit tab in Overleaf's sidebar, listing what the open document shows
 * from the project and the pipeline's stages, with a button to run it.
 *
 * Overleaf renders only its active tab's pane, so this one is put in the
 * sidebar's content area while it's open, with Overleaf's pane hidden,
 * rather than being a tab Overleaf knows about.
 */
export function watchRail(): void {
  const style = document.createElement("style");
  railStyle = style;
  style.textContent = `
    .ide-rail-tab-content.calkit-open > :not(#${RAIL_PANE_ID}) {
      display: none !important;
    }
    #${RAIL_PANE_ID} { height: 100%; overflow-y: auto; }
    body.calkit-rail-open .ide-rail-tab-link.active:not(#${RAIL_TAB_ID}) {
      background-color: transparent !important;
      color: inherit !important;
    }
    body.calkit-rail-open
      .ide-rail-tab-link.active:not(#${RAIL_TAB_ID})::after {
      display: none !important;
    }
    #${RAIL_TAB_ID} svg {
      width: 20px;
      height: 20px;
      display: block;
      margin: 0 auto;
      color: #009688;
    }
    #${RAIL_TAB_ID}.active svg { color: #fff; }
    #${RAIL_TAB_ID} { position: relative; }
    #${RAIL_TAB_ID} .calkit-rail-dot {
      position: absolute; bottom: 4px; right: 6px; width: 8px; height: 8px;
      border-radius: 50%; background: #e5484d;
      box-shadow: 0 0 0 2px var(--bg-primary-themed, #fff);
    }
    #${RAIL_TAB_ID} .calkit-rail-dot.busy {
      box-sizing: border-box; background: var(--bg-primary-themed, #fff);
      border: 2px solid #009688; border-top-color: transparent;
      animation: calkit-rail-spin 0.8s linear infinite;
    }
    @keyframes calkit-rail-spin { to { transform: rotate(360deg); } }
  `;
  document.head.append(style);
  // One of Overleaf's own tabs brings its pane back. The one it thinks is
  // showing would otherwise close the sidebar instead.
  document.addEventListener(
    "click",
    (event) => {
      const target = (event.target as Element | null)?.closest?.(
        ".ide-rail-tab-link",
      );
      if (!railOpen || !target || target.id === RAIL_TAB_ID) {
        return;
      }
      if (target.classList.contains("active")) {
        event.preventDefault();
        event.stopPropagation();
      }
      setRail(false);
    },
    { capture: true, signal: watching.signal },
  );
  const ensure = () => {
    const first = document.getElementById("ide-rail-tabs-tab-file-tree");
    const tabs = first?.parentElement;
    if (!tabs || !currentProjectId) {
      return;
    }
    let tab = document.getElementById(RAIL_TAB_ID);
    if (!tab) {
      tab = el("button", {
        class: "ide-rail-tab-link nav-link",
        attrs: {
          id: RAIL_TAB_ID,
          type: "button",
          role: "tab",
          title: "Calkit",
          "aria-label": "Calkit",
        },
      });
      // Inline, so it takes the tab's color: white while ours is open
      tab.innerHTML = calkitLogo;
      tab.addEventListener("click", () => setRail(!railOpen));
      const separated = tabs.querySelector(".separated-rail-tab");
      if (separated) {
        separated.before(tab);
      } else {
        tabs.append(tab);
      }
    }
    markRailTab();
    // Overleaf underlines the tab whose pane is open by open-rail
    tab.classList.toggle("active", railOpen);
    tab.classList.toggle("open-rail", railOpen);
    tab.setAttribute("aria-selected", String(railOpen));
    if (railOpen) {
      placeRailPane();
    }
  };
  observePage(ensure, 100);
}

/**
 * What the open document's components are made from that has no origin
 * defined, with a component made from each and what they all show.
 */
function getOriginGaps(): Map<string, { citation: Citation; uses: string[] }> {
  const gaps = new Map<string, { citation: Citation; uses: string[] }>();
  const items = editorCitations?.items ?? [];
  if (editorProblems?.version !== editorCitations?.version) {
    return gaps;
  }
  editorProblems?.found.forEach((problems, index) => {
    const citation = items[index]?.citation;
    for (const problem of problems) {
      if (problem.kind !== "origin" || !citation) {
        continue;
      }
      const gap = gaps.get(problem.path) ?? { citation, uses: [] };
      const use = citation.key
        ? `${citation.path} \u00b7 ${citation.key}`
        : citation.path;
      if (!gap.uses.includes(use)) {
        gap.uses.push(use);
      }
      gaps.set(problem.path, gap);
    }
  });
  return gaps;
}

/**
 * What the open document is made from that has no origin defined, e.g., a
 * figure, or the data a figure's script reads, each with the components it
 * makes and the first one's place in the editor's scan, which its card
 * needs.
 */
export function getMissingOrigins(): {
  path: string;
  uses: string[];
  item: EditorItem;
  citation: Citation;
  at: { version: number; index: number };
}[] {
  const items = editorCitations?.items ?? [];
  const version = editorCitations?.version ?? 0;
  if (!currentLink || editorProblems?.version !== editorCitations?.version) {
    return [];
  }
  const missing = new Map<string, ReturnType<typeof getMissingOrigins>[0]>();
  items.forEach((item, index) => {
    const citation = item.citation;
    if (!citation) {
      return;
    }
    for (const problem of editorProblems?.found[index] ?? []) {
      if (problem.kind !== "origin") {
        continue;
      }
      const entry = missing.get(problem.path) ?? {
        path: problem.path,
        uses: [],
        item,
        citation,
        at: { version, index },
      };
      if (!entry.uses.includes(citation.path)) {
        entry.uses.push(citation.path);
      }
      missing.set(problem.path, entry);
    }
  });
  return [...missing.values()];
}

/**
 * Typed numbers and tables the project has results for, which linking
 * keeps current, with what each is labeled and where it is in the scan.
 */
export function getLinkableTyped(): {
  item: EditorItem;
  label: string;
  at: ItemAt;
}[] {
  const items = editorCitations?.items ?? [];
  const version = editorCitations?.version ?? 0;
  if (!currentLink || editorProblems?.version !== editorCitations?.version) {
    return [];
  }
  return items.flatMap((item, index) =>
    (item.typed || item.table) && editorProblems?.found[index]?.length
      ? [
          {
            item,
            label: item.typed
              ? `${item.typed.text} (line ${item.line})`
              : `Table (line ${item.line})`,
            at: { version, index },
          },
        ]
      : [],
  );
}

/** Where an item is in one of the editor's scans. */
export type ItemAt = { version: number; index: number };

/** A dot on the Calkit tab while something here needs an origin defined. */
export function markRailTab(): void {
  drawPanelOrigins?.();
  remountLauncher();
  drawRailDot();
}

/**
 * The Calkit tab's dot: spinning while the pipeline runs or the paper
 * syncs, otherwise there while something here needs an origin defined.
 */
function drawRailDot(): void {
  const tab = document.getElementById(RAIL_TAB_ID);
  if (!tab) {
    return;
  }
  const busy = currentLink
    ? activeRun()
      ? "running"
      : syncing
      ? "syncing"
      : null
    : null;
  const n = currentLink ? getOriginGaps().size : 0;
  let dot = tab.querySelector<HTMLElement>(".calkit-rail-dot");
  if (!busy && !n) {
    dot?.remove();
    tab.title = "Calkit";
    return;
  }
  if (!dot) {
    dot = el("span", { class: "calkit-rail-dot" });
    tab.append(dot);
  }
  dot.classList.toggle("busy", Boolean(busy));
  tab.title = busy
    ? `Calkit: ${busy}`
    : `Calkit: ${n} file${n === 1 ? "" : "s"} this document is made from ` +
      `need${n === 1 ? "s" : ""} an origin defined`;
}

export function setRail(open: boolean): void {
  railOpen = open;
  document.body.classList.toggle("calkit-rail-open", open);
  const tab = document.getElementById(RAIL_TAB_ID);
  tab?.classList.toggle("active", open);
  tab?.classList.toggle("open-rail", open);
  tab?.setAttribute("aria-selected", String(open));
  if (!open) {
    document
      .querySelector(".ide-rail-tab-content")
      ?.classList.remove("calkit-open");
    railPane?.host.remove();
    return;
  }
  // A closed sidebar has no content area to show it in, so open it on the
  // file tree first
  const content = document.querySelector(".ide-rail-tab-content");
  if (!content || content.getBoundingClientRect().width < 20) {
    // Its pane is put there once it's drawn, as Overleaf redraws
    document.getElementById("ide-rail-tabs-tab-file-tree")?.click();
  } else {
    placeRailPane();
  }
  drawRail();
  if (currentLink) {
    void refreshRailPipeline(currentLink);
  }
}

// The Calkit pane in Overleaf's sidebar, which brings its own background,
// since its colors follow the system's theme rather than Overleaf's
const RAIL_STYLES = `
  .rail {
    padding: 10px 12px; min-height: 100%; box-sizing: border-box;
    color: var(--ck-fg); background: var(--ck-bg);
  }
  .rail .project {
    flex-direction: column; align-items: flex-start; gap: 2px;
    overflow-wrap: anywhere;
  }
  .rail h3 {
    font-size: 12px; font-weight: 600; margin: 14px 0 4px;
    text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--ck-dim);
  }
  .item {
    display: flex; align-items: center; gap: 6px; width: 100%;
    padding: 3px 4px; border: 0; border-radius: 4px; text-align: left;
    background: none; color: inherit; cursor: pointer;
  }
  .item:hover { background: var(--ck-subtle-bg); }
  .item .grow { min-width: 0; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex: none;
    background: var(--ck-success); }
  .dot.warning { background: var(--ck-warning); }
  .dot.error { background: var(--ck-danger); }
  .dot.unknown { background: var(--ck-dim); }
  /* A row that expands, colored for its state, pointing down when open */
  .twistie { width: 0; height: 0; flex: none; margin: 0 1px 0 2px;
    border-top: 4px solid transparent; border-bottom: 4px solid transparent;
    border-left: 6px solid var(--ck-success);
    transition: transform 0.1s; }
  .twistie.open { transform: rotate(90deg); }
  .twistie.warning { border-left-color: var(--ck-warning); }
  .twistie.error { border-left-color: var(--ck-danger); }
  .twistie.unknown { border-left-color: var(--ck-dim); }
  .twistie.link { border-left-color: var(--ck-main); }
  .item .spinner { width: 8px; height: 8px; border-width: 1.5px;
    flex: none; }
  .card {
    margin: 2px 0 8px 14px; padding: 6px 8px; font-size: 12px;
    border-left: 2px solid var(--ck-border);
  }
  .card > * + * { margin-top: 3px; }
  .card button.action { padding: 1px 6px; font-size: 11px; }
`;

/** Put the pane in the sidebar, where Overleaf may have redrawn it away. */
function placeRailPane(): void {
  const content = document.querySelector(".ide-rail-tab-content");
  if (!content) {
    return;
  }
  if (!railPane) {
    const host = el("div", { attrs: { id: RAIL_PANE_ID } });
    const root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = STYLES + RAIL_STYLES;
    const body = el("div", { class: "rail" });
    root.append(style, body);
    railPane = { host, body };
    drawRail();
  }
  if (railPane.host.parentElement !== content) {
    content.append(railPane.host);
  }
  content.classList.add("calkit-open");
}

/** Ask the hub for the pipeline's stages, then show them. */
export async function refreshRailPipeline(
  link: OverleafLinkPublic,
): Promise<void> {
  try {
    const pipeline = await send({
      type: "project.pipeline",
      owner: link.project_owner_name,
      project: link.project_name,
    });
    railPipeline = { key: linkKey(link), pipeline };
    drawPanelActions();
  } catch (e) {
    railPipeline = {
      key: linkKey(link),
      error: e instanceof Error ? e.message : String(e),
    };
  }
  drawRail();
}

/** Open the sidebar on a component's card, as clicking its row does. */
export function showInRail(citation: Citation): void {
  const link = currentLink;
  const items = editorCitations?.items ?? [];
  const text = citationText(citation);
  const index = items.findIndex(
    (i) => i.citation && citationText(i.citation) === text,
  );
  if (!link || index < 0) {
    return;
  }
  const element = el("div", { class: "card" });
  railCard = { key: `${text}#1`, element };
  void fillCard(element, link, items[index], {
    version: editorCitations?.version ?? 0,
    index,
  });
  if (!railOpen) {
    setRail(true);
  }
  drawRail();
  element.scrollIntoView({ block: "center", behavior: "smooth" });
}

export function drawRail(): void {
  // One of the pipeline's runs, opening its log, or GitHub's page for it
  const renderRunItem = (link: OverleafLinkPublic, run: PipelineRun) => {
    const when = new Date(run.started ?? run.created).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
    const active = ["queued", "running"].includes(run.status);
    const parts = [
      active
        ? el("span", { class: "spinner" })
        : el("span", {
            class: `dot ${
              run.status === "succeeded"
                ? ""
                : run.status === "failed"
                ? "error"
                : "unknown"
            }`,
          }),
      // All here, or all on GitHub, as the panel says above
      el("span", { class: "grow small", text: when }),
      el("span", { class: "dim small", text: run.status }),
    ];
    if (run.location === "local") {
      return el(
        "button",
        {
          class: "item",
          title: run.error ?? "Show its log",
          onClick: () => openRunLog(link, run),
        },
        parts,
      );
    }
    return run.url
      ? el(
          "a",
          { class: "item", href: run.url, attrs: { target: "_blank" } },
          parts,
        )
      : el("div", { class: "item" }, parts);
  };
  drawRailDot();
  if (!railPane) {
    return;
  }
  const body = clear(railPane.body);
  const link = currentLink;
  if (!link) {
    body.append(
      el("div", {
        class: "small",
        text: "This paper isn't linked to a Calkit project yet.",
      }),
      el("div", { class: "actions" }, [
        el("button", {
          class: "action",
          text: "Link",
          onClick: () => currentProjectId && openPanel(currentProjectId),
        }),
      ]),
    );
    return;
  }
  const base = projectUrl(
    hubWebUrl,
    link.project_owner_name,
    link.project_name,
  );
  body.append(
    el("div", { class: "row project" }, [
      el("a", {
        class: "small",
        text: "Open in Calkit",
        href: base,
        title: linkKey(link),
        attrs: { target: "_blank" },
      }),
      renderWhere(link),
    ]),
  );
  // What's going on between the paper and its project
  const running = activeRun();
  const status =
    lastCheck && linkKey(lastCheck.link) === linkKey(link)
      ? lastCheck.status
      : null;
  if (syncing) {
    body.append(loading("Syncing with project"));
  } else if (checkingAfterSync && !running) {
    body.append(loading("Checking what's synced now"));
  } else if (running) {
    body.append(
      loading(
        running.location === "local"
          ? getRunActivity(running)
          : running.status === "running"
          ? `Running ${getRunPlace(running)}`
          : `Waiting to run ${getRunPlace(running)}`,
      ),
    );
  } else if (status?.in_sync) {
    body.append(
      el("div", { class: "row small" }, [
        el("span", { class: "dot" }),
        el("span", { text: "In sync with project" }),
      ]),
    );
  } else if (status) {
    const { button, message } = syncNow(link, status.path, true);
    body.append(
      el("div", { class: "row small" }, [
        el("span", { class: "dot warning" }),
        el("span", { class: "grow", text: "Changes to sync" }),
        button,
      ]),
      message,
    );
  }
  // Components the open document shows, each with what's wrong with it
  body.append(el("h3", { text: "Components" }));
  const items = editorCitations?.items ?? [];
  const version = editorCitations?.version ?? 0;
  const checked =
    editorProblems && editorProblems.version === editorCitations?.version
      ? editorProblems.found
      : null;
  if (!items.length) {
    body.append(
      el("div", {
        class: "dim small",
        text: "Nothing from the project here yet.",
      }),
    );
  }
  const seen = new Map<string, number>();
  items.forEach((item, index) => {
    const problems = checked?.[index];
    // Something typed is only listed where it could be linked
    if ((item.typed || item.table) && !problems?.length) {
      return;
    }
    // What it shows, and which time, since its line moves with edits
    const text = item.citation
      ? citationText(item.citation)
      : item.typed
      ? item.typed.text
      : "table";
    const nth = (seen.get(text) ?? 0) + 1;
    seen.set(text, nth);
    const key = `${text}#${nth}`;
    const label = item.citation
      ? item.citation.key
        ? `${item.citation.path} · ${item.citation.key}`
        : item.citation.path
      : item.typed
      ? `Typed number ${item.typed.text}`
      : "Typed table";
    const failing = problems?.some((p) => p.severity === "error");
    body.append(
      el(
        "button",
        {
          class: "item",
          title: problems?.length
            ? problems.map((p) => p.message).join("\n")
            : `Line ${item.line}`,
          attrs: { "aria-expanded": String(railCard?.key === key) },
          onClick: () => {
            toEditor({ type: "goto", line: item.line, column: item.column });
            if (railCard?.key === key) {
              railCard = null;
            } else {
              const element = el("div", { class: "card" });
              railCard = { key, element };
              void fillCard(element, link, item, {
                version,
                index,
              });
            }
            drawRail();
          },
        },
        [
          el("span", {
            class: `twistie ${
              problems === undefined
                ? "unknown"
                : problems.some((p) => p.severity === "error")
                ? "error"
                : problems.some((p) => p.severity === "warning")
                ? "warning"
                : problems.length
                ? "link"
                : ""
            }${railCard?.key === key ? " open" : ""}`,
          }),
          el("span", {
            class: "grow small",
            text: label,
            style: failing ? { color: "var(--ck-danger)" } : {},
          }),
          el("span", { class: "dim small", text: `${item.line}` }),
        ],
      ),
    );
    if (railCard?.key === key) {
      body.append(railCard.element);
    }
  });
  // The pipeline's stages, and running it
  body.append(el("h3", { text: "Pipeline" }));
  const known = railPipeline?.key === linkKey(link) ? railPipeline : null;
  const pipeline = known?.pipeline;
  if (known?.error) {
    body.append(errorMessage(known.error));
  } else if (!pipeline) {
    body.append(loading());
  } else if (!pipeline.ck_stages.length) {
    body.append(el("div", { class: "dim small", text: "No stages yet." }));
  }
  for (const name of pipeline?.ck_stages ?? []) {
    const status = pipeline?.stage_statuses[name]?.status ?? "unknown";
    const due = ["stale", "not-run"].includes(status);
    // What a run going now will run
    const toRun = Boolean(running) && due;
    body.append(
      el(
        "button",
        {
          class: "item",
          title: status,
          attrs: { "aria-expanded": String(railStage === name) },
          onClick: () => {
            railStage = railStage === name ? null : name;
            drawRail();
          },
        },
        [
          toRun
            ? el("span", { class: "spinner" })
            : el("span", {
                class: `twistie ${
                  status === "up-to-date" ? "" : due ? "warning" : "unknown"
                }${railStage === name ? " open" : ""}`,
              }),
          el("span", { class: "grow small", text: name }),
          status !== "up-to-date"
            ? el("span", {
                class: "dim small",
                text: toRun ? "running" : status,
              })
            : null,
        ],
      ),
    );
    if (railStage === name && pipeline) {
      body.append(renderStageCard(link, pipeline, name));
    }
  }
  body.append(renderRuns(link, true));
  // On this machine, a run is offered only when something's out of date
  const staleStages = (pipeline?.ck_stages ?? []).filter((name) =>
    ["stale", "not-run"].includes(pipeline?.stage_statuses[name]?.status ?? ""),
  );
  if (link.local_path && staleStages.length && !running) {
    body.append(
      el("div", { class: "actions" }, [
        el("button", {
          class: "action",
          text: "Run and sync",
          title:
            "Run pipeline, save, and sync. " +
            `Out of date: ${staleStages.join(", ")}`,
          disabled: !canWrite(link) || Boolean(starting?.busy),
          onClick: () => void startRun(link),
        }),
      ]),
    );
  }
  // The latest runs, each with its log
  const runs =
    pipelineRuns?.key === linkKey(link) ? pipelineRuns.runs.runs : [];
  if (runs.length) {
    body.append(el("h3", { text: "Runs" }));
    for (const run of runs.slice(0, 5)) {
      body.append(renderRunItem(link, run));
    }
  }
}
