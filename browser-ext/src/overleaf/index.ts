/**
 * Content script for Overleaf project pages: the Calkit badge and its
 * panel, linking a project, syncing, and pipeline runs. The rest of what it
 * draws is in the other modules here; editor.ts runs separately, inside
 * Overleaf's own page.
 */
import { getOverleafProjectId } from "../core/detect";
import calkitLogo from "../../public/icons/calkit.svg?raw";
import {
  renderFailure,
  renderHubPicker,
  renderProjectPicker,
} from "../core/pickers";
import { getHubWebUrl, projectUrl } from "../core/hub-url";
import {
  getEditorLabel,
  getGitBlobSha,
  type CheckoutStatus,
  type LocalStatus,
} from "../core/local";
import {
  type Citation,
  type PrintedNumbers,
  type ResultValue,
  type TableFile,
  citationCandidates,
  notebookOfValuesPath,
  resultValues,
  tableFile,
} from "../core/latex";
import { runContentScript } from "../core/lifecycle";
import {
  isExtensionAlive,
  isUnsupportedByHub,
  RequestFailed,
  send,
} from "../core/messages";
import {
  type GithubRepo,
  type OverleafLinkPublic,
  type Provenance,
  type OverleafSyncResponse,
  type OverleafSyncStatus,
  type OverleafSyncStatusFile,
  type PipelineRun,
  type PipelineRuns,
  type ProjectPublic,
} from "../core/types";
import {
  clear,
  el,
  launcherPosition,
  errorMessage,
  loading,
  mountOverlay,
  mountPanel,
  type Panel,
  textInput,
} from "../core/ui";
import { type LineEdit, getEditContext } from "../core/review";
import { type EditorItem, type FromEditor } from "./editor";
import {
  editorProblems,
  toEditor,
  checkCitations,
  fillCard,
  watchEditor,
  renderInsert,
} from "./citations";
import {
  openDocPath,
  watchPdf,
  localPdf,
  showLocalPdf,
  removePdfViewer,
  watchReview,
  watchPdfSwitch,
  mountPdfSwitch,
} from "./pdf-viewer";
import {
  RAIL_TAB_ID,
  railStyle,
  railOpen,
  railPipeline,
  watchRail,
  getMissingOrigins,
  getLinkableTyped,
  ItemAt,
  setRail,
  refreshRailPipeline,
  drawRail,
} from "./sidebar";

const PANEL_ID = "calkit-overleaf-panel";
const LAUNCHER_ID = "calkit-overleaf-launcher";
const TOKEN_PANEL_ID = "calkit-overleaf-token-panel";
const OVERLEAF_TOKEN_RE = /\bolp_[A-Za-z0-9]{20,}\b/;

let panel: Panel | null = null;
export let currentProjectId: string | null = null;
export let hubWebUrl = "https://calkit.io";
// The last status found for this page, so opening the panel shows it at
// once instead of waiting for the hub to check Overleaf all over again
export let lastCheck: {
  overleafProjectId: string;
  hubWebUrl: string;
  link: OverleafLinkPublic;
  status: OverleafSyncStatus;
  // What the last sync did, kept through the check that follows it
  notice?: string;
} | null = null;
// Bumped by each load, each sync, and each sign-in change, so a check
// that finishes after any of them doesn't draw over it
let loadGeneration = 0;
let tokenWatcher: MutationObserver | null = null;
// Aborted once this script shuts down, which stops what watches the page
export const watching = new AbortController();

/**
 * Call back a moment after the page changes, until this script shuts down,
 * e.g., to put back what Overleaf redrew without it, or straight away with
 * no delay.
 */
export function observePage(
  callback: () => void,
  delay: number | null,
  options: MutationObserverInit = { childList: true, subtree: true },
): void {
  // A copy left behind by a reload can't reach the extension, and throws
  // if it tries, until it notices and shuts down
  const run = (): void => {
    if (isExtensionAlive()) {
      callback();
    }
  };
  let timer: ReturnType<typeof setTimeout> | undefined;
  const observer = new MutationObserver(() => {
    if (delay === null) {
      run();
      return;
    }
    clearTimeout(timer);
    timer = setTimeout(run, delay);
  });
  observer.observe(document.body, options);
  watching.signal.addEventListener("abort", () => {
    observer.disconnect();
    clearTimeout(timer);
  });
}
// The Calkit project this Overleaf project syncs with, once found
export let currentLink: OverleafLinkPublic | null = null;
// Overleaf links whose project changed on the hub, e.g., with an import,
// but whose sync failed, so a retry syncs even when nothing changes again
export const syncOwed = new Set<string>();
// Kept for a minute, since the project changes under it, e.g., with a sync
export const provenanceCache = new Map<
  string,
  { at: number; provenance: Promise<Provenance> }
>();

export function provenanceFor(
  link: OverleafLinkPublic,
  path: string,
  key?: string,
): Promise<Provenance> {
  const cacheKey = `${link.project_owner_name}/${link.project_name}:${path}:${
    key ?? ""
  }`;
  const cached = provenanceCache.get(cacheKey);
  if (cached && Date.now() - cached.at < 60_000) {
    return cached.provenance;
  }
  const provenance = send({
    type: "project.provenance",
    owner: link.project_owner_name,
    project: link.project_name,
    path,
    key,
  });
  // A failure is worth asking again about next time
  provenance.catch(() => provenanceCache.delete(cacheKey));
  provenanceCache.set(cacheKey, { at: Date.now(), provenance });
  return provenance;
}

// Kept for a minute too, since checking a document asks for them each time
// it changes
const valuesCache = new Map<
  string,
  { at: number; values: Promise<ResultValue[]> }
>();

/**
 * Every number in the project's results files, which a typed number may be
 * a copy of.
 */
export function projectValues(
  link: OverleafLinkPublic,
): Promise<ResultValue[]> {
  const owner = link.project_owner_name;
  const project = link.project_name;
  const cacheKey = `${owner}/${project}`;
  const cached = valuesCache.get(cacheKey);
  if (cached && Date.now() - cached.at < 60_000) {
    return cached.values;
  }
  const values = (async () => {
    const results = await send({ type: "project.results", owner, project });
    const paths = [...new Set(results.map((result) => result.path))].filter(
      (path) => /\.(json|ya?ml|toml)$/i.test(path),
    );
    const files = await Promise.all(
      paths.map((path) => provenanceFor(link, path).catch(() => null)),
    );
    return files.flatMap((file, i) =>
      file && !file.value_error
        ? resultValues(notebookOfValuesPath(paths[i]) ?? paths[i], file.value)
        : [],
    );
  })();
  values.catch(() => valuesCache.delete(cacheKey));
  valuesCache.set(cacheKey, { at: Date.now(), values });
  return values;
}

const printedCache = new Map<
  string,
  { at: number; printed: Promise<PrintedNumbers[]> }
>();

/**
 * Numbers the pipeline's notebooks printed, which a typed number may be a
 * copy of, read on this machine, or none when the project isn't here.
 */
export function projectPrintedNumbers(
  link: OverleafLinkPublic,
): Promise<PrintedNumbers[]> {
  const cacheKey = `${link.project_owner_name}/${link.project_name}`;
  const cached = printedCache.get(cacheKey);
  if (cached && Date.now() - cached.at < 60_000) {
    return cached.printed;
  }
  const printed = send({
    type: "project.printedNumbers",
    owner: link.project_owner_name,
    project: link.project_name,
  }).catch(() => [] as PrintedNumbers[]);
  printedCache.set(cacheKey, { at: Date.now(), printed });
  return printed;
}

const tablesCache = new Map<
  string,
  { at: number; tables: Promise<TableFile[]> }
>();

/** The tables stages write as TeX, which a typed table may be a copy of. */
export function projectTables(link: OverleafLinkPublic): Promise<TableFile[]> {
  const owner = link.project_owner_name;
  const project = link.project_name;
  const cacheKey = `${owner}/${project}`;
  const cached = tablesCache.get(cacheKey);
  if (cached && Date.now() - cached.at < 60_000) {
    return cached.tables;
  }
  const tables = (async () => {
    const listed = await send({ type: "project.tables", owner, project });
    const paths = [...new Set(listed.map((table) => table.path))].filter(
      (path) => /\.tex$/i.test(path),
    );
    const files = await Promise.all(
      paths.map(async (path) => {
        try {
          const item = await send({
            type: "project.contents",
            owner,
            project,
            path,
          });
          if (!item.content) {
            return null;
          }
          // Base64, as the hub sends every file
          const bytes = Uint8Array.from(atob(item.content), (c) =>
            c.charCodeAt(0),
          );
          return tableFile(path, new TextDecoder().decode(bytes));
        } catch {
          return null;
        }
      }),
    );
    return files.filter((file): file is TableFile => file !== null);
  })();
  tables.catch(() => tablesCache.delete(cacheKey));
  tablesCache.set(cacheKey, { at: Date.now(), tables });
  return tables;
}

/**
 * Sync after the hub changed the project, remembering until it works that
 * a sync is owed, since the hub won't report the change again.
 */
export async function syncAfterHubChange(
  link: OverleafLinkPublic,
): Promise<void> {
  const key = `${linkKey(link)}:${link.path}`;
  syncOwed.add(key);
  await send({
    type: "overleaf.sync",
    owner: link.project_owner_name,
    project: link.project_name,
    path: link.path,
  });
  syncOwed.delete(key);
}

/**
 * Where a file the document shows came from, finding it in the project
 * first, since TeX may find it under a name with an extension added, and
 * finds a plainly included one relative to the document.
 */
export async function citationProvenance(
  link: OverleafLinkPublic,
  citation: Citation,
): Promise<Provenance> {
  if (citation.kind === "value") {
    return provenanceFor(link, citation.path, citation.key);
  }
  const candidates = citationCandidates(link.path, citation);
  let first: Provenance | null = null;
  for (const candidate of candidates) {
    const provenance = await provenanceFor(link, candidate);
    if (provenance.exists) {
      return provenance;
    }
    first ??= provenance;
  }
  return first ?? provenanceFor(link, candidates[0]);
}

// The project's pipeline runs, checked often while one is going, so a
// finished run syncs to Overleaf even with the panel closed, and now and
// then otherwise, to see ones started elsewhere
export let pipelineRuns: {
  key: string;
  runs: PipelineRuns;
  // What the last finished run did here
  notice?: string;
} | null = null;
let runsTimer: ReturnType<typeof setTimeout> | undefined;
// The check going now, which others wait on rather than repeat
let runsRequest: { key: string; promise: Promise<void> } | null = null;
// Checks that failed in a row, which space the next ones out
let runsFailures = 0;
// A start from a run button, kept across their redraws
export let starting: { key: string; busy: boolean; error?: string } | null =
  null;
// Whether syncing from this machine runs what's out of date first, as last
// chosen
const RUN_BEFORE_SYNC_KEY = "runBeforeSync";
let runBeforeSync = true;
void chrome.storage.local.get(RUN_BEFORE_SYNC_KEY).then((stored) => {
  runBeforeSync = stored[RUN_BEFORE_SYNC_KEY] ?? true;
});
// Where the open panel shows them, redrawn as they change
const runsBoxes = new Set<{
  box: HTMLElement;
  link: OverleafLinkPublic;
  offer: boolean;
}>();

export function linkKey(link: OverleafLinkPublic): string {
  return `${link.project_owner_name}/${link.project_name}`;
}

/** Whether the user can change the project, e.g., run or sync it. */
export function canWrite(link: OverleafLinkPublic): boolean {
  return ["write", "admin", "owner"].includes(link.current_user_access ?? "");
}

/** The run going now, if there is one. */
export function activeRun(): PipelineRun | null {
  const latest = pipelineRuns?.runs.runs[0];
  return latest && ["queued", "running"].includes(latest.status)
    ? latest
    : null;
}

/** Show what's going on on the launcher, while the panel is closed. */
export function remountLauncher(): void {
  if (!panel && currentProjectId) {
    const id = currentProjectId;
    mountLauncher(() => openPanel(id), launcherTone(), true);
  }
}

/**
 * Check the project's runs, and keep checking: often while one is going,
 * now and then otherwise, less often after failures, and not while the tab
 * is hidden. A check already going is waited on rather than repeated.
 */
function refreshRuns(link: OverleafLinkPublic): Promise<void> {
  const key = linkKey(link);
  const schedule = () => {
    clearTimeout(runsTimer);
    const delay = runsFailures
      ? Math.min(15_000 * 2 ** runsFailures, 300_000)
      : activeRun()?.location === "local"
      ? 2_000
      : activeRun()
      ? 15_000
      : 60_000;
    runsTimer = setTimeout(() => {
      if (document.hidden) {
        schedule();
      } else {
        void refreshRuns(link);
      }
    }, delay);
  };
  const check = async () => {
    const known = pipelineRuns?.key === key ? pipelineRuns : null;
    const wasRunning = Boolean(known && activeRun());
    let runs: PipelineRuns;
    try {
      runs = await send({
        type: "project.pipelineRuns",
        owner: link.project_owner_name,
        project: link.project_name,
      });
      runsFailures = 0;
    } catch {
      runsFailures++;
      schedule();
      return;
    }
    if (currentLink && linkKey(currentLink) !== key) {
      return;
    }
    pipelineRuns = { key, runs, notice: known?.notice };
    if (!activeRun() && wasRunning) {
      if (railOpen) {
        void refreshRailPipeline(link);
      }
      if (runs.runs[0]?.status === "succeeded") {
        await bringInRun(link);
      } else {
        pipelineRuns.notice = undefined;
      }
    }
    schedule();
    drawRuns();
    drawRail();
    remountLauncher();
  };
  if (runsRequest?.key === key) {
    return runsRequest.promise;
  }
  const promise = check().finally(() => {
    if (runsRequest?.promise === promise) {
      runsRequest = null;
    }
  });
  runsRequest = { key, promise };
  return promise;
}

/** Sync the paper with its project, showing that it's going meanwhile. */
export async function syncOverleaf(
  owner: string,
  project: string,
  path: string,
): Promise<OverleafSyncResponse> {
  syncing = true;
  drawRail();
  drawStatusParts();
  remountLauncher();
  try {
    return await send({ type: "overleaf.sync", owner, project, path });
  } finally {
    syncing = false;
    drawRail();
    drawStatusParts();
    remountLauncher();
  }
}

/** Look again at what's synced and shown, now that a sync changed it. */
function afterSync(): void {
  provenanceCache.clear();
  // A run saves values, e.g., a notebook's, that typed numbers can link to
  valuesCache.clear();
  printedCache.clear();
  checkingAfterSync = true;
  drawStatusParts();
  drawRail();
  // What was just built and synced, rather than what was
  if (localPdf) {
    showLocalPdf(localPdf.link, localPdf.path);
  }
  // A run or sync changes which stages are out of date
  if (currentLink?.local_path) {
    void refreshRailPipeline(currentLink);
  }
  if (!currentProjectId) {
    return;
  }
  if (panel) {
    void load(currentProjectId);
  } else {
    void checkSyncStatus(currentProjectId);
  }
}

// Why the last sync from a Sync now button failed, kept across redraws
let syncError: string | undefined;

/** A Sync now button, for where a sync is all that's needed. */
export function syncNow(
  link: OverleafLinkPublic,
  path: string,
  secondary = false,
): { button: HTMLElement; message: HTMLElement } {
  const message = el("div", { class: "small" }, [
    syncError ? errorMessage(syncError) : null,
  ]);
  const button = el("button", {
    class: secondary ? "action secondary" : "action",
    text: "Sync now",
    disabled: !canWrite(link) || syncing,
    title: canWrite(link)
      ? "Push project files to Overleaf and pull Overleaf edits"
      : "You need write access to this project to sync",
  });
  button.addEventListener("click", async () => {
    button.disabled = true;
    syncError = undefined;
    clear(message).append(loading("Syncing"));
    try {
      await syncOverleaf(link.project_owner_name, link.project_name, path);
      clear(message).append(el("div", { class: "dim", text: "Synced." }));
      afterSync();
    } catch (e) {
      syncError = e instanceof Error ? e.message : String(e);
      button.disabled = false;
      clear(message).append(errorMessage(syncError));
    }
  });
  return { button, message };
}

/**
 * Start the pipeline on this machine, saving and syncing after if chosen,
 * or else on GitHub Actions, which syncs here when it's done.
 */
export async function startRun(link: OverleafLinkPublic): Promise<void> {
  const key = linkKey(link);
  starting = { key, busy: true };
  drawRuns();
  try {
    const run = await send({
      type: "project.startPipelineRun",
      owner: link.project_owner_name,
      project: link.project_name,
      sync: true,
    });
    starting = null;
    // Listed as soon as it's recorded, before GitHub lists it
    if (pipelineRuns?.key === key) {
      pipelineRuns.runs.runs.unshift(run);
      pipelineRuns.notice = undefined;
    }
  } catch (e) {
    starting = {
      key,
      busy: false,
      error: e instanceof Error ? e.message : String(e),
    };
  }
  drawRuns();
  drawRail();
  remountLauncher();
  if (!starting) {
    // One that was already going may not have it yet
    await runsRequest?.promise;
    await refreshRuns(link);
  }
}

/** Bring what a finished run made into this paper. */
async function bringInRun(link: OverleafLinkPublic): Promise<void> {
  if (!pipelineRuns) {
    return;
  }
  // 'calkit run --save --overleaf' synced already, unless it was only run
  if (pipelineRuns.runs.runs[0]?.location === "local") {
    pipelineRuns.notice =
      "The pipeline ran on this machine, and its results were saved " +
      "and synced here.";
  } else if (canWrite(link)) {
    try {
      await syncOverleaf(link.project_owner_name, link.project_name, link.path);
      pipelineRuns.notice =
        "The pipeline finished on GitHub Actions, and its results were " +
        "synced here.";
    } catch (e) {
      pipelineRuns.notice =
        "The pipeline finished on GitHub Actions, but syncing failed: " +
        (e instanceof Error ? e.message : String(e));
    }
  }
  afterSync();
}

/**
 * The pipeline's latest run, and a button to start one when ``offer``
 * says there's something to run.
 */
export function renderRuns(
  link: OverleafLinkPublic,
  offer: boolean,
): HTMLElement {
  const box = el("div", { style: { marginTop: "6px" } });
  runsBoxes.add({ box, link, offer });
  if (pipelineRuns?.key === linkKey(link)) {
    drawRuns();
  } else if (!runsFailures) {
    // Failed checks are retried on a timer instead
    void refreshRuns(link);
  }
  return box;
}

export function drawRuns(): void {
  drawStatusParts();
  drawPanelActions();
  for (const entry of runsBoxes) {
    const { box, link, offer } = entry;
    if (!box.isConnected && box.dataset.drawn) {
      runsBoxes.delete(entry);
      continue;
    }
    box.dataset.drawn = "1";
    clear(box);
    if (pipelineRuns?.key !== linkKey(link)) {
      continue;
    }
    const { runs, notice } = pipelineRuns;
    const run = activeRun();
    const latest = runs.runs[0];
    const view = (r: PipelineRun, text: string) =>
      r.url
        ? el("a", { text, href: r.url, attrs: { target: "_blank" } })
        : null;
    if (run) {
      const since = run.started
        ? ` since ${new Date(run.started).toLocaleTimeString([], {
            hour: "numeric",
            minute: "2-digit",
          })}`
        : "";
      box.append(
        el("div", { class: "row" }, [
          el("span", { class: "spinner" }),
          el("div", {
            class: "grow small",
            text:
              run.location === "local"
                ? getRunActivity(run)
                : run.status === "running"
                ? `Running ${getRunPlace(run)}${since}`
                : `Waiting to run ${getRunPlace(run)}`,
          }),
          run.location === "local"
            ? el("button", {
                class: "action secondary",
                text: "Show log",
                onClick: () => openRunLog(link, run),
              })
            : view(run, "View"),
        ]),
      );
      // The last of what it's printed, with the rest a click away
      if (run.location === "local" && run.output) {
        box.append(
          el("pre", {
            class: "log",
            text: run.output.split("\n").slice(-3).join("\n"),
          }),
        );
      }
      continue;
    }
    if (notice) {
      box.append(el("div", { class: "dim small", text: notice }));
    } else if (latest?.status === "failed") {
      box.append(
        el("div", { class: "row" }, [
          el("div", {
            class: "grow small",
            text:
              `The last run ${getRunPlace(latest)} failed` +
              (latest.error ? `: ${latest.error}` : "."),
            title: latest.output ?? "",
          }),
          latest.location === "local"
            ? el("button", {
                class: "action secondary",
                text: "Show log",
                onClick: () => openRunLog(link, latest),
              })
            : view(latest, "See why"),
        ]),
      );
    }
    // Something the document shows being out of date is reason to run
    // too, even when Overleaf has what the project has
    const staleShown = editorProblems?.found.some((problems) =>
      problems.some((p) => p.kind === "stale"),
    );
    // On this machine, the panel's own sync runs it, but a card, e.g., the
    // hover card, offers it for what it shows
    if (
      (link.local_path && !offer) ||
      (!offer && !staleShown && latest?.status !== "failed")
    ) {
      continue;
    }
    const mine = starting?.key === linkKey(link) ? starting : null;
    const start = el("button", {
      class: "action",
      text: "Run and sync",
      disabled: !canWrite(link) || !runs.can_start || Boolean(mine?.busy),
      title: !canWrite(link)
        ? "You need write access to this project to run it"
        : runs.cannot_start_reason ??
          (link.local_path
            ? "Run pipeline on this machine, save, and sync"
            : "Run pipeline on GitHub Actions and sync its outputs here"),
      onClick: () => void startRun(link),
    });
    box.append(
      el("div", { class: "actions" }, [start]),
      mine?.busy
        ? loading("Starting")
        : mine?.error
        ? errorMessage(mine.error)
        : el("div"),
    );
  }
}

/** What a run on this machine is doing now, as a line would say it. */
export function getRunActivity(run: PipelineRun): string {
  const progress = run.progress;
  if (run.status === "queued") {
    return "Waiting to run on this machine";
  }
  const of = progress?.n_stages ? ` of ${progress.n_stages}` : "";
  switch (progress?.phase) {
    case "syncing":
      return "Syncing with Overleaf";
    case "running":
      return progress.stage
        ? `Running stage ${progress.n_done + 1}${of}: ${progress.stage}`
        : `Checking stages (${progress.n_done}${of} done)`;
    case "finishing":
      return "Finishing up";
    case "saving":
      return "Saving project";
    default:
      return "Preparing to run";
  }
}

/**
 * Show the whole log of a run on this machine, kept up to date while it
 * runs.
 */
export function openRunLog(link: OverleafLinkPublic, run: PipelineRun): void {
  const started = run.started ?? run.created;
  const overlay = mountOverlay({
    id: "calkit-run-log",
    title: `Run on this machine, ${new Date(started).toLocaleString([], {
      dateStyle: "medium",
      timeStyle: "short",
    })}`,
  });
  const log = el("pre", { class: "log", text: "Loading…" });
  overlay.viewport.append(log);
  const refresh = async () => {
    if (!overlay.host.isConnected) {
      return;
    }
    try {
      const { log: text } = await send({
        type: "project.pipelineRunLog",
        owner: link.project_owner_name,
        project: link.project_name,
        runId: run.id,
      });
      // Kept at the end as it grows, unless scrolled back to read
      const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
      log.textContent = text || "Nothing printed yet.";
      if (atEnd) {
        log.scrollTop = log.scrollHeight;
      }
    } catch (e) {
      log.textContent = e instanceof Error ? e.message : String(e);
    }
    const latest = pipelineRuns?.runs.runs.find((r) => r.id === run.id);
    if (latest && ["queued", "running"].includes(latest.status)) {
      setTimeout(() => void refresh(), 2_000);
    }
  };
  void refresh();
}

// The parts of the open panel's status that a run or sync going on makes
// out of date, set aside meanwhile rather than shown as current
const statusParts = new Set<{
  link: OverleafLinkPublic;
  hide: HTMLElement[];
  busy: HTMLElement;
}>();
// Whether what's shown is from before a run or sync that's just ended, until
// it's been checked again
export let checkingAfterSync = false;

/** What's going on that makes the status shown out of date, if anything. */
function getStatusBusyText(link: OverleafLinkPublic): string | null {
  if (syncing) {
    return "Syncing with Overleaf";
  }
  const run = pipelineRuns?.key === linkKey(link) ? activeRun() : null;
  if (run) {
    return run.progress?.phase === "syncing"
      ? "Syncing with Overleaf"
      : "Sync status updates after the run.";
  }
  return checkingAfterSync ? "Checking what's synced now" : null;
}

function drawStatusParts(): void {
  for (const entry of statusParts) {
    if (!entry.busy.isConnected && entry.busy.dataset.drawn) {
      statusParts.delete(entry);
      continue;
    }
    entry.busy.dataset.drawn = "1";
    const text = getStatusBusyText(entry.link);
    for (const part of entry.hide) {
      part.style.display = text ? "none" : "";
    }
    clear(entry.busy);
    if (text) {
      entry.busy.append(
        text.endsWith(".")
          ? el("div", {
              class: "dim small",
              style: { marginTop: "8px" },
              text,
            })
          : el("div", { style: { marginTop: "8px" } }, [loading(text)]),
      );
    }
  }
}

// Whether Calkit on this machine answers, asked once per page, since the
// browser starts it to find out
let localStatus: Promise<LocalStatus> | null = null;

/**
 * A button that opens the project in the editor on this machine, at a
 * file if given, e.g., the notebook that makes a figure, through Calkit
 * here rather than a hub, or installs the editor first if it isn't there.
 */
export function renderOpenLocally(
  project: string,
  path?: string,
  inline = false,
  // Shown as a link, e.g., the checkout's path, rather than a button
  shown?: string,
): HTMLElement {
  localStatus ??= send({ type: "local.status" }).catch(() => ({
    permitted: false,
  }));
  const open = el("button", {
    class: shown ? "link" : "action secondary",
    text: shown ?? "Open in editor",
    title: path ? `Open ${path} on this machine` : "Open it on this machine",
  });
  const message = el("div", { class: "small" });
  const label = (status: LocalStatus) => {
    const editor = getEditorLabel(status.editor);
    const text =
      status.editorInstalled === false
        ? `Install ${editor}`
        : `Open in ${editor}`;
    if (shown) {
      open.title = text;
    } else {
      open.textContent = text;
    }
  };
  void localStatus.then(label);
  open.addEventListener("click", async () => {
    const status = await (localStatus as Promise<LocalStatus>);
    if (!status.version) {
      // Asked again next time, e.g., once it's been connected
      localStatus = null;
      clear(message).append(
        el("span", {
          text: status.permitted
            ? `${status.error ?? "Calkit on this machine didn't answer"}. `
            : "Connect the extension to Calkit on this machine. ",
        }),
        el("button", {
          class: "action secondary",
          text: "Connect",
          onClick: () => void send({ type: "local.openOptions" }),
        }),
      );
      return;
    }
    open.disabled = true;
    try {
      if (status.editorInstalled === false) {
        clear(message).append(
          loading(`Installing ${getEditorLabel(status.editor)}`),
        );
        await send({ type: "local.installEditor", project });
        localStatus = send({ type: "local.status" });
        label(await localStatus);
      }
      clear(message).append(loading("Opening"));
      await send({ type: "local.openProject", project, path });
      clear(message);
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    } finally {
      open.disabled = false;
    }
  });
  if (inline) {
    message.classList.add("line-message");
    return el("div", { style: { display: "contents" } }, [open, message]);
  }
  return el("div", { style: { marginTop: "4px" } }, [open, message]);
}

/**
 * What's on this machine that Overleaf won't see until it's saved and
 * synced, e.g., a figure remade by running a notebook, or a way to connect
 * if the extension isn't connected to Calkit here. With ``localPath``, the
 * checkout the panel already works with, only what the panel doesn't show
 * otherwise, i.e., what isn't saved or pushed.
 */
function renderLocalChanges(
  project: string,
  reload: () => void,
  localPath?: string | null,
): HTMLElement {
  const container = el("div");
  localStatus ??= send({ type: "local.status" }).catch(() => ({
    permitted: false,
  }));
  void (async () => {
    const status = await (localStatus as Promise<LocalStatus>);
    if (!status.version) {
      // Asked again next time, e.g., once it's been connected
      localStatus = null;
      container.append(
        el("div", { class: "row", style: { marginTop: "8px" } }, [
          el("div", {
            class: "dim small grow",
            text: status.permitted
              ? `${status.error ?? "Calkit on this machine didn't answer"}.`
              : "Connect this machine to see what's on it that Overleaf " +
                "doesn't have yet.",
          }),
          el("button", {
            class: "action secondary",
            text: "Connect",
            onClick: () => void send({ type: "local.openOptions" }),
          }),
        ]),
      );
      return;
    }
    // Not here yet, so offered, since working on it here is the point
    const local = await send({ type: "local.checkout", project }).catch(
      () => null,
    );
    if (local && !local.path) {
      container.append(renderClone(project, reload));
      return;
    }
    // Which of several, e.g., worktrees, answers for it
    if (local && local.paths.length > 1) {
      const choice = el(
        "select",
        { class: "small", title: "The checkout this panel uses" },
        local.paths.map((p) => el("option", { text: p, value: p })),
      );
      choice.value = local.path ?? "";
      choice.addEventListener("change", async () => {
        await send({
          type: "local.chooseCheckout",
          project,
          path: choice.value,
        });
        reload();
      });
      container.append(
        el("div", { class: "row small", style: { marginTop: "8px" } }, [
          el("span", { class: "dim", text: "Using" }),
          choice,
        ]),
      );
    }
    let checkouts: CheckoutStatus[];
    try {
      ({ checkouts } = await send({ type: "local.projectStatus", project }));
    } catch (e) {
      container.append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
      return;
    }
    let pendingCount = 0;
    const plural = (n: number, word: string) =>
      `${n} ${word}${n === 1 ? "" : "s"}`;
    if (localPath) {
      checkouts = checkouts.filter((c) => c.path === localPath);
    }
    for (const checkout of checkouts) {
      const lines: HTMLElement[] = [];
      // Saved from here, so nobody has to leave Overleaf to back it up, in
      // the checkout the panel uses, which is this one if it's the only one
      if (checkout.n_unsaved_files && !(localPath || checkouts.length === 1)) {
        lines.push(
          el("div", {
            class: "small",
            text: plural(checkout.n_unsaved_files, "unsaved file"),
            title: checkout.unsaved_files.join("\n"),
          }),
        );
      } else if (checkout.n_unsaved_files) {
        const message = el("div", { class: "small" });
        const save = el("button", { class: "action secondary", text: "Save" });
        save.addEventListener("click", async () => {
          save.disabled = true;
          clear(message).append(loading("Saving"));
          try {
            await send({ type: "local.save", project });
            reload();
          } catch (e) {
            save.disabled = false;
            clear(message).append(
              errorMessage(e instanceof Error ? e.message : String(e)),
            );
          }
        });
        lines.push(
          el("div", { class: "row" }, [
            el("div", {
              class: "grow small",
              text: plural(checkout.n_unsaved_files, "unsaved file"),
              title: checkout.unsaved_files.join("\n"),
            }),
            save,
          ]),
          message,
        );
      }
      if (checkout.commits_ahead) {
        lines.push(
          el("div", {
            class: "small",
            text: plural(checkout.commits_ahead, "unpushed change"),
          }),
        );
      }
      // The panel lists what a sync would send for its own checkout
      for (const folder of localPath ? [] : checkout.overleaf) {
        const n =
          (folder.n_files_to_push ?? 0) + (folder.n_files_to_delete ?? 0);
        if (folder.syncing) {
          lines.push(el("div", { class: "small", text: "Syncing now" }));
        } else if (folder.never_synced) {
          lines.push(
            el("div", {
              class: "small",
              text: `${folder.path} hasn't been synced from here yet`,
            }),
          );
        } else if (folder.error) {
          lines.push(errorMessage(folder.error));
        } else if (n) {
          lines.push(
            el("div", {
              class: "small",
              text: `${plural(n, "file")} in ${folder.path} not synced here`,
              title: (folder.files_to_push ?? []).join("\n"),
            }),
          );
        }
      }
      if (!lines.length) {
        continue;
      }
      pendingCount++;
      if (localPath) {
        container.append(el("div", { style: { marginTop: "6px" } }, lines));
        continue;
      }
      container.append(
        el("div", { class: "muted-box", style: { marginTop: "8px" } }, [
          el("div", { class: "row" }, [
            el("div", { class: "grow" }, [
              el("div", { class: "small", text: "On this machine" }),
              el("div", { class: "dim small", text: checkout.path }),
            ]),
            el("span", { class: "badge warn", text: "not synced" }),
          ]),
          ...lines,
          el("div", {
            class: "dim small",
            style: { marginTop: "4px" },
            text: "Run and sync there to bring them here.",
          }),
        ]),
      );
    }
    // Only checkouts with something to bring here are listed, since
    // someone may have several, e.g., Git worktrees
    if (checkouts.length && !pendingCount && !localPath) {
      container.append(
        el("div", {
          class: "dim small",
          style: { marginTop: "6px" },
          text: "Everything on this machine is saved and synced.",
        }),
      );
    }
  })();
  return container;
}

/**
 * Clone a project that isn't on this machine, so this panel works with
 * it here from then on.
 */
function renderClone(project: string, reload: () => void): HTMLElement {
  const name = project.split("/")[1];
  const location = el("input", {
    class: "small",
    type: "text",
    value: `~/calkit/${name}`,
    title: "Where to put it",
  });
  const message = el("div", { class: "small" });
  const clone = el("button", {
    class: "action",
    text: "Clone to this machine",
  });
  clone.addEventListener("click", async () => {
    clone.disabled = true;
    clear(message).append(loading("Cloning"));
    try {
      await send({
        type: "local.clone",
        project,
        location: location.value.trim() || undefined,
      });
      reload();
    } catch (e) {
      clone.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  return el("div", { class: "muted-box", style: { marginTop: "8px" } }, [
    el("div", {
      class: "small",
      text:
        "This project isn't on this machine. Clone it to run, save, and " +
        "sync from here:",
    }),
    el("div", { class: "row", style: { marginTop: "6px" } }, [location, clone]),
    message,
  ]);
}

/**
 * Whether a failure is about the user's Overleaf Git token, missing or
 * rejected, which the hub needs to read the project, rather than their
 * Calkit credentials.
 */
function isOverleafTokenProblem(e: unknown): boolean {
  return (
    e instanceof RequestFailed &&
    e.status === 401 &&
    /overleaf/i.test(e.message)
  );
}

/**
 * Ask for an Overleaf Git token, and save it to the hub, or, without
 * Overleaf Premium, connect the browser's Overleaf login instead.
 */
function renderTokenForm(
  container: HTMLElement,
  problem: string,
  reload: () => void,
): void {
  const rejected = problem.includes("rejected");
  const sessionRejected = rejected && problem.includes("session");
  const connectMessage = el("div", { class: "small" });
  const connect = el("button", {
    class: sessionRejected ? "action" : "action secondary",
    text: "Connect with Overleaf login",
  });
  connect.addEventListener("click", async () => {
    connect.disabled = true;
    clear(connectMessage).append(loading("Connecting"));
    try {
      await send({ type: "overleaf.connectSession" });
      reload();
    } catch (e) {
      connect.disabled = false;
      clear(connectMessage).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  const connectSection = el("div", { style: { marginTop: "12px" } }, [
    el("div", {
      class: "small",
      text: sessionRejected
        ? "Overleaf no longer accepts the Overleaf login Calkit saved. " +
          "Connect it again to keep syncing."
        : "No Overleaf Premium? Calkit can sync using your Overleaf " +
          "login instead of a token.",
    }),
    el("div", { class: "actions" }, [connect]),
    connectMessage,
  ]);
  if (sessionRejected) {
    container.append(connectSection);
    return;
  }
  const input = textInput({ placeholder: "olp_..." });
  input.type = "password";
  const message = el("div", { class: "small" });
  const get = el("button", {
    class: "action",
    text: "Get a token from Overleaf",
  });
  get.addEventListener("click", async () => {
    try {
      await send({ type: "overleaf.openTokenSettings" });
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  const save = el("button", {
    class: "action secondary",
    text: "Save token",
  });
  save.addEventListener("click", async () => {
    const token = input.value.trim();
    if (!token.startsWith("olp_")) {
      clear(message).append(errorMessage("Overleaf tokens start with olp_"));
      return;
    }
    save.disabled = true;
    clear(message).append(loading("Saving"));
    try {
      await send({ type: "overleaf.setToken", token });
      reload();
    } catch (e) {
      save.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  container.append(
    el("div", {
      class: "small",
      text: rejected
        ? "Overleaf rejected your Git token. It may have expired or " +
          "been revoked."
        : "Calkit needs an Overleaf Git token to read this project.",
    }),
    el("div", { class: "dim small", style: { marginTop: "6px" } }, [
      document.createTextNode(
        "Opens your Overleaf settings, where you click Generate token. " +
          "Calkit saves it and brings you back here.",
      ),
    ]),
    el("div", { class: "actions" }, [get]),
    el("div", { class: "dim small", style: { marginTop: "12px" } }, [
      document.createTextNode("Or paste one you have:"),
    ]),
    input,
    el("div", { class: "actions" }, [
      save,
      el("button", {
        class: "action secondary",
        text: "Check again",
        onClick: reload,
      }),
    ]),
    message,
    connectSection,
  );
}

/**
 * Show a failure, offering to connect Overleaf when that's what's missing,
 * so a first link or import works without Premium too.
 */
function renderOverleafFailure(e: unknown, reload: () => void): HTMLElement {
  if (isOverleafTokenProblem(e)) {
    const container = el("div");
    renderTokenForm(
      container,
      e instanceof Error ? e.message : String(e),
      reload,
    );
    return container;
  }
  return renderFailure(e, { onSignedIn: reload });
}

/**
 * Save an Overleaf Git token to Calkit as soon as Overleaf shows one, which
 * it only does once, right after it's generated.
 *
 * In a tab the Calkit panel opened for this, the user already asked for the
 * token to be saved, so it is, and they go back to their project. Anywhere
 * else it's only offered: nothing is read or sent until they click.
 */
async function watchForNewToken(): Promise<void> {
  if (tokenWatcher) {
    return;
  }
  // Set now so a second sync doesn't start another while this one asks
  const placeholder = new MutationObserver(() => undefined);
  tokenWatcher = placeholder;
  const { requested } = await send({ type: "overleaf.tokenTab" }).catch(() => ({
    requested: false,
  }));
  if (tokenWatcher !== placeholder) {
    // Torn down meanwhile
    return;
  }
  const texts = (): string[] => [
    ...Array.from(document.querySelectorAll("input"), (input) => input.value),
    document.body.innerText,
  ];
  const message = el("div", { class: "small" });
  const save = async (tokenPanel: Panel): Promise<void> => {
    const token = texts()
      .map((text) => text.match(OVERLEAF_TOKEN_RE)?.[0])
      .find(Boolean);
    if (!token) {
      clear(message).append(errorMessage("The token is no longer on the page"));
      return;
    }
    clear(message).append(loading("Saving"));
    try {
      await send({ type: "overleaf.setToken", token });
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
      return;
    }
    clear(tokenPanel.body).append(
      el("div", {
        class: "small",
        text: "Saved. Your Overleaf projects can sync with Calkit now.",
      }),
    );
    if (requested) {
      await send({ type: "overleaf.returnFromTokenTab" }).catch(
        () => undefined,
      );
    }
  };
  // Point at the button that makes one, which Overleaf labels by whether
  // the account has a token already
  let pointed = false;
  const pointAtGenerate = (): void => {
    const button = Array.from(document.querySelectorAll("button")).find((b) =>
      /^\s*(generate token|add another token)\s*$/i.test(b.textContent ?? ""),
    );
    if (!button) {
      return;
    }
    pointed = true;
    button.scrollIntoView({ block: "center" });
    button.style.outline = "3px solid #f0ad4e";
    button.style.outlineOffset = "2px";
  };
  const guide = requested
    ? mountPanel({ id: TOKEN_PANEL_ID, title: "Calkit" })
    : null;
  if (guide) {
    guide.body.append(
      el("div", {
        class: "small",
        text:
          "Click Generate token under Git integration. Calkit saves the " +
          "token and takes you back to your project.",
      }),
      message,
    );
    pointAtGenerate();
  }
  // Only whether one is showing until it's saved, so the token itself is
  // never held before then
  let showing = false;
  tokenWatcher = new MutationObserver(() => {
    if (requested && !pointed) {
      pointAtGenerate();
    }
    const visible = texts().some((text) => OVERLEAF_TOKEN_RE.test(text));
    if (visible === showing) {
      return;
    }
    showing = visible;
    if (guide) {
      if (visible) {
        void save(guide);
      }
      return;
    }
    if (!visible) {
      document.getElementById(TOKEN_PANEL_ID)?.remove();
      return;
    }
    const tokenPanel = mountPanel({ id: TOKEN_PANEL_ID, title: "Calkit" });
    const button = el("button", { class: "action", text: "Save to Calkit" });
    button.addEventListener("click", async () => {
      button.disabled = true;
      await save(tokenPanel);
      button.disabled = false;
    });
    clear(message);
    tokenPanel.body.append(
      el("div", {
        class: "small",
        text:
          "Save this Overleaf Git token to Calkit, so it can check and " +
          "sync your Overleaf projects?",
      }),
      el("div", { class: "actions" }, [button]),
      message,
    );
  });
  tokenWatcher.observe(document.body, { childList: true, subtree: true });
}

function fileRow(file: OverleafSyncStatusFile): HTMLElement {
  const stale = file.stage_status && file.stage_status.status !== "up-to-date";
  const stateLabel = {
    new: "not on Overleaf",
    modified: "changed",
    deleted: "removed",
  }[file.state];
  return el("div", { class: "row" }, [
    el("div", { class: "grow" }, [
      el("div", { class: "name", text: file.path }),
      el("div", { class: "dim small", text: stateLabel }),
    ]),
    file.figure && el("span", { class: "badge info", text: "figure" }),
    stale &&
      el("span", {
        class: "badge warn",
        text: "stale",
        title:
          `Produced by stage '${file.stage}', which is ` +
          `${file.stage_status?.status}; run the pipeline before syncing`,
      }),
  ]);
}

// Answers from the editor's script, by request
export const editorReplies = new Map<
  number,
  (message: FromEditor & { type: "text" | "replaced" | "tree" }) => void
>();
let editorRequests = 0;

/** The open file's text in the editor, or null if there isn't one. */
export function readEditor(): Promise<string | null> {
  const reqId = ++editorRequests;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      editorReplies.delete(reqId);
      resolve(null);
    }, 3000);
    editorReplies.set(reqId, (message) => {
      clearTimeout(timer);
      resolve(message.type === "text" ? message.text : null);
    });
    toEditor({ type: "read", reqId });
  });
}

/**
 * What the Overleaf project has, from its editor: every file's Git hash
 * and the documents' text, by path, so Calkit on this machine can tell if
 * its copy is current, or bring it up to date, without downloading the
 * project. Null if Overleaf's file tree can't be read.
 */
async function getOverleafFiles(projectId: string): Promise<{
  shas: Record<string, string>;
  texts: Record<string, string>;
} | null> {
  const tree = await getOverleafTree();
  if (!tree) {
    return null;
  }
  const shas: Record<string, string> = {};
  const texts: Record<string, string> = {};
  for (const file of tree.files) {
    shas[file.path] = file.hash;
  }
  try {
    await Promise.all(
      tree.docs.map(async (doc) => {
        // Typing changes only the open one, so the rest are read again
        // only once they may have been changed by someone else
        const cached = overleafDocs.get(doc.id);
        if (
          cached &&
          doc.id !== tree.openDocId &&
          Date.now() - cached.at < DOC_CACHE_MS
        ) {
          shas[doc.path] = cached.sha;
          texts[doc.path] = cached.text;
          return;
        }
        const response = await fetch(
          `/project/${projectId}/doc/${doc.id}/download`,
        );
        if (!response.ok) {
          throw new Error(`Couldn't read ${doc.path} (${response.status})`);
        }
        const data = new Uint8Array(await response.arrayBuffer());
        shas[doc.path] = await getGitBlobSha(data);
        texts[doc.path] = new TextDecoder().decode(data);
        overleafDocs.set(doc.id, {
          at: Date.now(),
          sha: shas[doc.path],
          text: texts[doc.path],
        });
      }),
    );
  } catch {
    return null;
  }
  return { shas, texts };
}

// What each Overleaf document held when last read, by ID, and for how long
// that's trusted for those not open
const overleafDocs = new Map<
  string,
  { at: number; sha: string; text: string }
>();
const DOC_CACHE_MS = 30 * 1000;

/** Overleaf's file tree, from its editor, or null if it can't be read. */
export function getOverleafTree(): Promise<
  (FromEditor & { type: "tree" })["tree"]
> {
  const reqId = ++editorRequests;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      editorReplies.delete(reqId);
      resolve(null);
    }, 3000);
    editorReplies.set(reqId, (message) => {
      clearTimeout(timer);
      resolve(message.type === "tree" ? message.tree : null);
    });
    toEditor({ type: "tree", reqId });
  });
}

/** Make an edit to the open file in the editor, as typing would. */
export function editEditor(edit: LineEdit, lines: string[]): Promise<void> {
  const reqId = ++editorRequests;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      editorReplies.delete(reqId);
      reject(new Error("The editor didn't answer."));
    }, 3000);
    editorReplies.set(reqId, (message) => {
      clearTimeout(timer);
      if (message.type === "replaced" && message.error) {
        reject(new Error(message.error));
      } else {
        resolve();
      }
    });
    toEditor({
      type: "replace",
      reqId,
      line: edit.line,
      insert: edit.insert,
      ...getEditContext(lines, edit),
    });
  });
}

/**
 * Open a file in Overleaf's editor, as clicking it in the file tree would,
 * opening the folders it's in first, and wait for it to load. Says whether
 * it could.
 */
export async function openDocument(path: string): Promise<boolean> {
  const sleep = (ms: number) =>
    new Promise((resolve) => setTimeout(resolve, ms));
  if (openDocPath() === path) {
    return true;
  }
  const parts = path.split("/");
  let scope: ParentNode = document;
  for (const [i, name] of parts.entries()) {
    const item = [
      ...scope.querySelectorAll<HTMLElement>('[role="treeitem"]'),
    ].find((node) => node.getAttribute("aria-label") === name);
    if (!item) {
      return false;
    }
    if (i < parts.length - 1) {
      if (item.getAttribute("aria-expanded") === "false") {
        item
          .querySelector<HTMLElement>(".folder-expand-collapse-button")
          ?.click();
        await sleep(300);
      }
      scope = item;
      continue;
    }
    (
      item.querySelector<HTMLElement>(".file-tree-entity-button") ?? item
    ).click();
  }
  for (let i = 0; i < 50 && openDocPath() !== path; i++) {
    await sleep(100);
  }
  // The editor shows it a moment after the tree says it's open
  await sleep(300);
  return openDocPath() === path;
}

/**
 * Where the panel's answers come from: the checkout on this machine, or
 * the hub.
 */
export function renderWhere(link: OverleafLinkPublic): HTMLElement {
  if (link.local_path) {
    // Opens it in the editor, which is what the path is there for
    return el("div", { class: "dim small" }, [
      document.createTextNode("On this machine: "),
      renderOpenLocally(linkKey(link), undefined, true, link.local_path),
    ]);
  }
  return el("div", {
    class: "dim small",
    text: `Via ${new URL(hubWebUrl).host}`,
  });
}

/** Where a run of the pipeline happens, as a sentence would say it. */
export function getRunPlace(run: PipelineRun | undefined): string {
  return run?.location === "local" ? "on this machine" : "on GitHub Actions";
}

function renderStatus(
  body: HTMLElement,
  link: OverleafLinkPublic,
  status: OverleafSyncStatus,
  reload: () => void,
): void {
  clear(body);
  const figures = status.files_to_push.filter((f) => f.figure);
  const others = status.files_to_push.filter((f) => !f.figure);
  const project = `${link.project_owner_name}/${link.project_name}`;
  // Worked on here, so the hub's parts stay out of the way
  const local = Boolean(link.local_path);
  const syncBadge = status.in_sync
    ? el("span", { class: "badge ok", text: "in sync" })
    : el("span", {
        class: figures.length ? "badge danger" : "badge warn",
        text: figures.length
          ? `${figures.length} figure${figures.length === 1 ? "" : "s"} to sync`
          : "out of sync",
      });
  // Components with no origin outrank being in sync, and are listed, each
  // opening its card
  const badge = el("span");
  let openOrigin: { key: string; element: HTMLElement } | null = null;
  const origins = el("div");
  drawPanelOrigins = () => {
    const missing = getMissingOrigins();
    const n = missing.length;
    clear(badge).append(
      n
        ? el("span", {
            class: "badge danger",
            text: `${n} missing origin`,
          })
        : syncBadge,
    );
    clear(origins);
    // Each row opens its card, as in the sidebar, e.g., with the ways to
    // define an origin, or the result to link a typed number to
    const rows = (
      heading: string,
      color: string,
      list: { item: EditorItem; label: string; at: ItemAt }[],
    ) => {
      if (!list.length) {
        return;
      }
      origins.append(
        el("div", {
          class: "small",
          style: { marginTop: "8px", fontWeight: "600" },
          text: heading,
        }),
        ...list.flatMap(({ item, label, at }) => {
          const key = `${heading}:${at.index}:${label}`;
          const open = openOrigin?.key === key;
          const row = el("div", { class: "small" }, [
            el("a", {
              text: `${open ? "\u25be" : "\u25b8"} ${label}`,
              style: { color },
              onClick: (event) => {
                event.preventDefault();
                if (open) {
                  openOrigin = null;
                } else {
                  const element = el("div", {
                    class: "muted-box",
                    style: { marginTop: "4px" },
                  });
                  openOrigin = { key, element };
                  void fillCard(element, link, item, at);
                }
                drawPanelOrigins?.();
              },
            }),
          ]);
          return open && openOrigin ? [row, openOrigin.element] : [row];
        }),
      );
    };
    rows(
      "Missing origin",
      "var(--ck-danger)",
      missing.map(({ path, uses, item, at }) => ({
        item,
        at,
        // What's missing one, and what it makes when that's something else
        label: uses.some((use) => path.endsWith(use))
          ? path
          : `${path}, for ${uses.join(", ")}`,
      })),
    );
    // Typed numbers and tables the project has results for, which are
    // worth linking but nothing's wrong with
    rows("Can link", "var(--ck-main)", getLinkableTyped());
  };
  drawPanelOrigins();
  // What a sync would do, set aside while a run or sync makes it out of
  // date, with what's going on said instead
  const details = el("div");
  const busy = el("div");
  body.append(
    el("div", { class: "row" }, [
      el("div", { class: "grow" }, [
        local
          ? el("div", { text: project })
          : el("a", {
              text: project,
              href: projectUrl(
                hubWebUrl,
                link.project_owner_name,
                link.project_name,
              ),
            }),
        el("div", {
          class: "dim small",
          text: `Synced folder: ${status.path}`,
        }),
        renderWhere(link),
      ]),
      badge,
    ]),
  );
  body.append(renderLocalChanges(project, reload, link.local_path));
  body.append(origins, busy, details);
  // On this machine, the badge says it
  if (status.in_sync && !local) {
    details.append(
      el("div", {
        class: "dim small",
        style: { paddingTop: "6px" },
        text: "Everything here matches the Calkit project.",
      }),
    );
  }
  if (figures.length) {
    details.append(
      el("div", {
        class: "small",
        style: { marginTop: "8px", fontWeight: "600" },
        text: "Figures to sync",
      }),
      ...figures.map(fileRow),
    );
  }
  if (others.length) {
    details.append(
      el("div", {
        class: "small",
        style: { marginTop: "8px", fontWeight: "600" },
        text: "Other files to sync",
      }),
      ...others.map(fileRow),
    );
  }
  if (status.files_to_delete.length) {
    details.append(
      el("div", {
        class: "small",
        style: { marginTop: "8px", fontWeight: "600" },
        text: "Removed from the project",
      }),
      ...status.files_to_delete.map(fileRow),
    );
  }
  if (status.commits_from_overleaf > 0) {
    const count = status.commits_from_overleaf;
    details.append(
      el("div", {
        class: "dim small",
        style: { marginTop: "8px" },
        text:
          `${count} Overleaf ${count === 1 ? "change" : "changes"} ` +
          "will come back into the project on the next sync.",
      }),
    );
  }
  // Something stale is what a run would fix
  const stale = [...status.files_to_push, ...status.files_to_delete].some(
    (f) => f.stage_status && f.stage_status.status !== "up-to-date",
  );
  // On this machine, the panel's actions below have it
  body.append(renderRuns(link, stale && !link.local_path));
  const syncButton = el("button", {
    class: "action",
    text: "Sync now",
    disabled: !canWrite(link) || status.in_sync,
    title: canWrite(link)
      ? "Push project files to Overleaf and pull Overleaf edits"
      : "You need write access to this project to sync",
  });
  const message = el("div", { class: "small" });
  syncButton.addEventListener("click", async () => {
    // Running saves and syncs when it's done, so that's the sync
    if (runFirst.isConnected && runFirst.checked) {
      void startRun(link);
      return;
    }
    loadGeneration++;
    syncButton.disabled = true;
    // The status above says it's syncing
    clear(message);
    try {
      const result = await syncOverleaf(
        link.project_owner_name,
        link.project_name,
        status.path,
      );
      // Shown as in sync straight away, since that's what a sync leaves,
      // while the hub confirms it
      lastSyncNeeded = false;
      lastCheck = {
        overleafProjectId: link.overleaf_project_id,
        hubWebUrl,
        link,
        status: {
          ...status,
          in_sync: true,
          files_to_push: [],
          files_to_delete: [],
          commits_from_overleaf: 0,
        },
        notice:
          `Synced. ${result.commits_from_overleaf} change` +
          (result.commits_from_overleaf === 1
            ? " from Overleaf was"
            : "s from Overleaf were") +
          " synced to the main project.",
      };
      reload();
    } catch (e) {
      syncButton.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  // Syncing, and on this machine running what's out of date first, or,
  // with nothing to sync, running and syncing after. Redrawn once it's
  // known what's out of date, which takes a moment.
  const actions = el("div", { class: "actions" });
  const openLocally = local
    ? renderOpenLocally(project, undefined, true)
    : null;
  const refresh = el("button", {
    class: "action secondary",
    text: "Refresh",
    onClick: reload,
  });
  const runFirst = el("input", { type: "checkbox" }) as HTMLInputElement;
  runFirst.addEventListener("change", () => {
    runBeforeSync = runFirst.checked;
    void chrome.storage.local.set({ [RUN_BEFORE_SYNC_KEY]: runBeforeSync });
  });
  const drawActions = () => {
    const pipeline =
      local && railPipeline?.key === linkKey(link)
        ? railPipeline.pipeline
        : undefined;
    const staleStages = (pipeline?.ck_stages ?? []).filter((name) =>
      ["stale", "not-run"].includes(
        pipeline?.stage_statuses[name]?.status ?? "",
      ),
    );
    const running = Boolean(activeRun()) || Boolean(starting?.busy);
    runFirst.checked = runBeforeSync;
    const stagesText = `Out of date: ${staleStages.join(", ")}`;
    clear(actions).append(
      ...[
        status.in_sync ? null : syncButton,
        !status.in_sync && staleStages.length
          ? el("label", { class: "check", title: stagesText }, [
              runFirst,
              document.createTextNode("Run pipeline"),
            ])
          : null,
        status.in_sync && staleStages.length
          ? el("button", {
              class: "action",
              text: "Run and sync",
              title: `Run pipeline, save, and sync. ${stagesText}`,
              disabled: !canWrite(link) || running,
              onClick: () => void startRun(link),
            })
          : null,
        // Its button in this row, and anything it says below it
        openLocally,
        refresh,
      ].filter((node): node is HTMLElement => Boolean(node)),
    );
    syncButton.disabled = !canWrite(link) || status.in_sync || running;
    syncButton.title = staleStages.length
      ? `Push project files to Overleaf and pull Overleaf edits. ${stagesText}`
      : syncButton.title;
  };
  drawPanelActions = () => {
    if (actions.isConnected) {
      drawActions();
    }
  };
  drawActions();
  if (local) {
    void refreshRailPipeline(link);
  }
  body.append(actions, message);
  statusParts.add({ link, hide: [badge, details, actions], busy });
  drawStatusParts();
}

/**
 * Let the user make a new Calkit project for this Overleaf project, or
 * pick one they already have.
 *
 * Starting down either path hides the other, so a half-filled form never
 * sits next to a list of unrelated projects.
 */
async function renderPicker(
  body: HTMLElement,
  overleafProjectId: string,
  reload: () => void,
): Promise<void> {
  clear(body);
  const back = (text: string) =>
    el("div", { class: "actions" }, [
      el("button", {
        class: "action secondary",
        text,
        onClick: () => void renderPicker(body, overleafProjectId, reload),
      }),
    ]);
  const attachContainer = el("div");
  const start = el("div", {}, [
    el("div", {
      class: "dim small",
      text: "This paper isn't part of a Calkit project yet.",
    }),
    el("div", { class: "actions" }, [
      el("button", {
        class: "action",
        text: "Make this paper reproducible",
        onClick: () => {
          start.remove();
          existing.remove();
          const form = el("div");
          clear(attachContainer).append(
            form,
            back("Use a project I already have"),
          );
          void renderAttachForm(form, overleafProjectId, reload);
        },
      }),
    ]),
  ]);
  const search = textInput({
    placeholder: "Search your projects",
  });
  const results = el("div", { class: "stack", style: { marginTop: "6px" } });
  const existing = el("div", {}, [
    el("div", {
      class: "dim small",
      style: { marginTop: "12px" },
      text: "Or add it to a project you already have:",
    }),
    search,
    results,
  ]);
  const chosen = el("div", { class: "stack" });
  const chooseProject = async (project: ProjectPublic) => {
    start.remove();
    existing.remove();
    const message = el("div", { class: "small" }, [loading("Checking")]);
    clear(chosen).append(
      el(
        "div",
        {
          class: "muted-box",
          style: { borderLeft: "3px solid var(--ck-main)" },
        },
        [
          el("div", { class: "dim small", text: "Adding this paper to" }),
          el("div", {
            text: `${project.owner_account_name}/${project.name}`,
          }),
          el("div", { class: "dim small", text: project.title }),
        ],
      ),
      message,
      back("Select a different project"),
    );
    try {
      const statuses = await send({
        type: "overleaf.status",
        owner: project.owner_account_name,
        project: project.name,
        overleafProjectId,
      });
      if (statuses.length) {
        // Reading the status indexes the link server side, so a plain
        // reload now finds it
        reload();
        return;
      }
      clear(message).append(
        el("div", { class: "stack" }, [
          el("div", {
            class: "dim small",
            text:
              "Calkit will copy this paper's files into the project and " +
              "keep them in sync with Overleaf.",
          }),
          ...renderImportForm(project, overleafProjectId, reload),
        ]),
      );
    } catch (e) {
      clear(message).append(
        renderOverleafFailure(e, () => void chooseProject(project)),
      );
    }
  };
  const runSearch = async () => {
    clear(results).append(loading());
    try {
      const projects = await send({
        type: "projects.list",
        searchFor: search.value.trim() || undefined,
        limit: 10,
      });
      clear(results);
      if (!projects.data.length) {
        results.append(el("div", { class: "dim small", text: "No projects" }));
        return;
      }
      for (const project of projects.data) {
        results.append(
          el("div", { class: "row" }, [
            el("div", { class: "grow" }, [
              el("div", {
                text: `${project.owner_account_name}/${project.name}`,
              }),
              el("div", { class: "dim small", text: project.title }),
            ]),
            el("button", {
              class: "action secondary",
              text: "Choose",
              onClick: () => void chooseProject(project),
            }),
          ]),
        );
      }
    } catch (e) {
      clear(results).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  };
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => void runSearch(), 300);
  });
  body.append(start, attachContainer, existing, chosen);
  await runSearch();
}

/** The name Overleaf shows for this project. */
function overleafProjectTitle(): string {
  const meta = document.querySelector<HTMLMetaElement>(
    'meta[name="ol-projectName"]',
  );
  if (meta?.content.trim()) {
    return meta.content.trim();
  }
  // The tab reads, e.g., "My paper - Online LaTeX Editor Overleaf"
  return document.title.replace(/\s+-\s+[^-]*Overleaf[^-]*$/i, "").trim();
}

/** A project name from a title, the way the hub makes one. */
function projectSlug(title: string): string {
  return title
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^\w-]+/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
}

/**
 * Make a Calkit project for this Overleaf project, so the paper becomes a
 * pipeline stage whose figures and values can be traced and kept current.
 *
 * The project is a GitHub repo with the paper in a folder inside it,
 * either a new repo or one that already holds the analysis behind the
 * paper. Either way the hub needs a GitHub account to own it and the
 * Calkit app installed to write to it, so those come first, rather than
 * as an error after the form is filled in.
 */
async function renderAttachForm(
  container: HTMLElement,
  overleafProjectId: string,
  reload: () => void,
): Promise<void> {
  // Where the hub connects GitHub and installs its app, whose name differs
  // between hubs, and which sends a user with no installation to GitHub
  const accountsUrl = `${hubWebUrl}/settings?tab=connected-accounts`;
  const openAccounts = () => window.open(accountsUrl, "_blank", "noopener");
  const retry = () =>
    void renderAttachForm(container, overleafProjectId, reload);
  const blocked = (text: string, action: string) =>
    clear(container).append(
      el("div", { class: "small", text }),
      el("div", { class: "actions" }, [
        el("button", { class: "action", text: action, onClick: openAccounts }),
        el("button", {
          class: "action secondary",
          text: "Check again",
          onClick: retry,
        }),
      ]),
    );
  clear(container).append(loading("Checking your GitHub connection"));
  let githubName: string;
  try {
    const auth = await send({ type: "auth.state" });
    if (!auth.user?.github_username) {
      blocked(
        "Calkit keeps a project's files in a GitHub repo, so connect a " +
          "GitHub account first.",
        "Connect GitHub",
      );
      return;
    }
    githubName = auth.user.github_username;
    const installations = await send({ type: "github.installations" });
    if (!installations.total_count) {
      blocked(
        "Install the Calkit app on GitHub, so Calkit can create and update " +
          "the project's repo.",
        "Install the Calkit app",
      );
      return;
    }
  } catch (e) {
    // The hub's GitHub token can be expired or revoked even with a GitHub
    // username on the account, which reconnecting fixes
    if (
      e instanceof RequestFailed &&
      e.status === 401 &&
      /github/i.test(e.message)
    ) {
      blocked(
        "Calkit's connection to GitHub has expired. Reconnect it to " +
          "continue.",
        "Reconnect GitHub",
      );
      return;
    }
    clear(container).append(renderOverleafFailure(e, retry));
    return;
  }
  clear(container);
  const existsOnGithub = el("input", { type: "checkbox" });
  existsOnGithub.style.width = "auto";
  // Only for a new repo, since the hub matches an existing one's visibility
  const isPublic = el("input", { type: "checkbox" });
  isPublic.style.width = "auto";
  isPublic.addEventListener("change", () => describe());
  const publicField = el(
    "label",
    { class: "row", style: { fontWeight: "400" } },
    [isPublic, el("div", { class: "grow small", text: "Make public" })],
  );
  const repoInput = textInput({
    placeholder: "Start typing your GitHub repo name",
  });
  const repoResults = el("div", { class: "stack" });
  const repoFields = el("div", { class: "stack" }, [
    el("label", { text: "GitHub repo" }),
    repoInput,
    repoResults,
    el("div", { class: "dim small" }, [
      document.createTextNode("Only repos the Calkit app can access show. "),
      el("a", { text: "Give access to more", href: accountsUrl }),
    ]),
  ]);
  const titleInput = textInput({
    value: overleafProjectTitle(),
    placeholder: "My project",
  });
  const nameInput = textInput({
    value: projectSlug(titleInput.value),
    placeholder: "my-project",
  });
  // The name follows the title until it's edited itself
  let nameEdited = false;
  nameInput.addEventListener("input", () => {
    nameEdited = true;
    describe();
  });
  titleInput.addEventListener("input", () => {
    if (!nameEdited) {
      nameInput.value = projectSlug(titleInput.value);
    }
    describe();
  });
  const doc = documentFields(() => describe());
  // Where the document's files will go, since committing into an existing
  // repo is the part worth knowing before clicking
  const where = el("div", { class: "dim small" });
  const message = el("div", { class: "small" });
  let repos: GithubRepo[] | null = null;
  let chosenRepo: GithubRepo | null = null;
  // A folder on this machine with the analysis in it, which becomes the
  // project, as 'calkit new project' makes one, rather than a new repo
  let analysisFolder: string | null = null;
  const describe = () => {
    const folder = doc.folder();
    if (analysisFolder) {
      where.textContent =
        `Calkit will make ${analysisFolder} a project and save everything ` +
        `in it to a ${isPublic.checked ? "public" : "private"} repo, ` +
        `${githubName}/${nameInput.value.trim() || "..."}, with this ` +
        `document's files in ${folder}/, kept in sync with Overleaf.`;
      return;
    }
    where.textContent = existsOnGithub.checked
      ? chosenRepo
        ? `Calkit will commit this document's files to ${folder}/ in ` +
          `${chosenRepo.full_name}, and keep them in sync with Overleaf.`
        : ""
      : `Calkit will create a ${isPublic.checked ? "public" : "private"} ` +
        `repo, ${githubName}/` +
        `${nameInput.value.trim() || "..."}, with this document's files in ` +
        `${folder}/, and keep them in sync with Overleaf.`;
  };
  const renderRepoResults = () => {
    const query = repoInput.value.trim().toLowerCase();
    clear(repoResults);
    if (!repos) {
      return;
    }
    const matching = repos
      .filter((repo) => repo.full_name.toLowerCase().includes(query))
      .slice(0, 8);
    for (const repo of matching) {
      repoResults.append(
        el("div", { class: "row" }, [
          el("div", { class: "grow" }, [
            el("div", { class: "small", text: repo.full_name }),
            repo.description
              ? el("div", { class: "dim small", text: repo.description })
              : null,
          ]),
          el("button", {
            class: "action secondary",
            text: chosenRepo?.full_name === repo.full_name ? "Chosen" : "Use",
            disabled: chosenRepo?.full_name === repo.full_name,
            onClick: () => {
              chosenRepo = repo;
              repoInput.value = repo.full_name;
              // The project takes the repo's name unless renamed, since
              // that's the pairing everything else assumes
              if (!nameEdited) {
                nameInput.value = repo.name;
              }
              renderRepoResults();
              describe();
            },
          }),
        ]),
      );
    }
    if (!matching.length) {
      repoResults.append(
        el("div", { class: "dim small", text: "No matching repos" }),
      );
    }
  };
  const loadRepos = async () => {
    clear(repoResults).append(loading("Reading your GitHub repos"));
    try {
      repos = await send({ type: "github.repos" });
      renderRepoResults();
    } catch (e) {
      clear(repoResults).append(renderFailure(e, { onSignedIn: reload }));
    }
  };
  repoInput.addEventListener("input", renderRepoResults);
  const syncGithubFields = () => {
    repoFields.style.display = existsOnGithub.checked ? "" : "none";
    publicField.style.display = existsOnGithub.checked ? "none" : "";
    // A repo picked before switching to a new one would otherwise still be
    // where the paper goes
    if (!existsOnGithub.checked && chosenRepo) {
      chosenRepo = null;
      repoInput.value = "";
      if (!nameEdited) {
        nameInput.value = projectSlug(titleInput.value);
      }
      renderRepoResults();
    }
    if (existsOnGithub.checked && repos === null) {
      void loadRepos();
    }
    describe();
  };
  existsOnGithub.addEventListener("change", syncGithubFields);
  syncGithubFields();
  // Kept once made, so retrying after the import fails doesn't try to
  // create the same project again
  let created: ProjectPublic | null = null;
  const attach = el("button", { class: "action", text: "Create project" });
  attach.addEventListener("click", async () => {
    attach.disabled = true;
    try {
      const name = nameInput.value.trim();
      if (!name) {
        throw new Error("A project name is required");
      }
      if (existsOnGithub.checked && !chosenRepo) {
        throw new Error("Select a GitHub repo");
      }
      // Made on this machine, which signs in to the hub if it needs to
      if (analysisFolder) {
        clear(message).append(loading("Creating project"));
        const made = await send({
          type: "local.createProject",
          owner: githubName,
          name,
          title: titleInput.value.trim() || name,
          isPublic: isPublic.checked,
          folder: analysisFolder,
          overleafProjectUrl: `https://www.overleaf.com/project/${overleafProjectId}`,
          path: doc.folder(),
          kind: doc.kind.value,
          hubUrl: hubWebUrl,
        });
        await send({
          type: "settings.set",
          update: { activeProject: made.project },
        });
        reload();
        return;
      }
      if (!created) {
        clear(message).append(loading("Creating project"));
        try {
          created = await send({
            type: "projects.create",
            name,
            title: titleInput.value.trim() || name,
            gitRepoUrl: chosenRepo
              ? `https://github.com/${chosenRepo.full_name}`
              : undefined,
            isPublic: !chosenRepo && isPublic.checked,
          });
        } catch (e) {
          // An earlier try that stopped partway, e.g., when the panel was
          // reloaded, already made the project, so carry on with that one
          if (!(e instanceof RequestFailed && e.status === 409)) {
            throw e;
          }
          const existing = await send({
            type: "projects.list",
            githubRepo: chosenRepo?.full_name ?? `${githubName}/${name}`,
            limit: 1,
          });
          if (!existing.data.length) {
            throw e;
          }
          created = existing.data[0];
        }
        // Nothing above can change what was made
        for (const input of [existsOnGithub, isPublic, repoInput, nameInput]) {
          input.disabled = true;
        }
        titleInput.disabled = true;
        clear(repoResults);
        // The project this paper now belongs to is the one to work in
        await send({
          type: "settings.set",
          update: {
            activeProject: `${created.owner_account_name}/${created.name}`,
          },
        });
      }
      clear(message).append(loading("Importing from Overleaf"));
      await send({
        type: "overleaf.import",
        owner: created.owner_account_name,
        project: created.name,
        overleafProjectUrl: `https://www.overleaf.com/project/${overleafProjectId}`,
        path: doc.folder(),
        kind: doc.kind.value,
      });
      reload();
    } catch (e) {
      attach.disabled = false;
      // Retried in place, so connecting Overleaf here doesn't start over
      clear(message).append(renderOverleafFailure(e, () => attach.click()));
      // What the hub says when the app can't reach the account or repo
      if (String(e instanceof Error ? e.message : e).includes("App not")) {
        message.append(
          el("div", { class: "actions" }, [
            el("button", {
              class: "action secondary",
              text: "Give Calkit app access",
              onClick: openAccounts,
            }),
          ]),
        );
      }
    }
  });
  const existsField = el(
    "label",
    { class: "row", style: { fontWeight: "400" } },
    [
      existsOnGithub,
      el("div", {
        class: "grow small",
        text: "This project already has a GitHub repo",
      }),
    ],
  );
  const folderName = el("div", { class: "grow small dim" });
  const selectFolder = el("button", {
    class: "action secondary",
    text: "Select analysis folder",
  });
  selectFolder.addEventListener("click", async () => {
    clear(message);
    try {
      const chosen = await send({
        type: "local.chooseFolder",
        prompt: "Select analysis folder",
      });
      if (!chosen.path) {
        return;
      }
      analysisFolder = chosen.path;
      folderName.textContent = chosen.path;
      // Its own repo is made from it
      existsOnGithub.checked = false;
      syncGithubFields();
      existsField.style.display = "none";
      describe();
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  container.append(
    el("label", { text: "Project title" }),
    titleInput,
    el("label", { text: "Project name" }),
    nameInput,
    el("div", { class: "row" }, [folderName, selectFolder]),
    existsField,
    repoFields,
    publicField,
    ...doc.fields,
    where,
    el("div", { class: "actions" }, [attach]),
    message,
  );
}

/**
 * Type and folder fields for an Overleaf document going into a project,
 * the folder following the type until it's edited.
 */
function documentFields(onChange: () => void = () => {}): {
  kind: HTMLSelectElement;
  folder: () => string;
  fields: HTMLElement[];
} {
  const types: [string, string, string][] = [
    ["journal-article", "Journal article", "paper"],
    ["conference-paper", "Conference paper", "paper"],
    ["report", "Report", "report"],
    ["book", "Book", "book"],
    ["masters-thesis", "Master's thesis", "thesis"],
    ["phd-thesis", "PhD thesis", "thesis"],
    ["other", "Other", "document"],
  ];
  const kind = el("select");
  for (const [value, label] of types) {
    kind.append(el("option", { value, text: label }));
  }
  const defaultFolder = () =>
    types.find(([value]) => value === kind.value)?.[2] ?? "document";
  const path = textInput({ value: defaultFolder() });
  let pathEdited = false;
  path.addEventListener("input", () => {
    pathEdited = true;
    onChange();
  });
  kind.addEventListener("change", () => {
    if (!pathEdited) {
      path.value = defaultFolder();
    }
    onChange();
  });
  return {
    kind,
    folder: () => path.value.trim() || defaultFolder(),
    fields: [
      el("label", { text: "Type" }),
      kind,
      el("label", { text: "Folder for this document" }),
      path,
    ],
  };
}

function renderImportForm(
  project: ProjectPublic,
  overleafProjectId: string,
  reload: () => void,
): HTMLElement[] {
  const doc = documentFields();
  const importButton = el("button", {
    class: "action",
    text: `Add to ${project.name}`,
  });
  const message = el("div", { class: "small" });
  importButton.addEventListener("click", async () => {
    importButton.disabled = true;
    clear(message).append(loading("Importing from Overleaf"));
    try {
      await send({
        type: "overleaf.import",
        owner: project.owner_account_name,
        project: project.name,
        overleafProjectUrl: `https://www.overleaf.com/project/${overleafProjectId}`,
        path: doc.folder(),
        kind: doc.kind.value,
      });
      await send({
        type: "settings.set",
        update: {
          activeProject: `${project.owner_account_name}/${project.name}`,
        },
      });
      reload();
    } catch (e) {
      importButton.disabled = false;
      clear(message).append(
        renderOverleafFailure(e, () => importButton.click()),
      );
    }
  });
  return [
    ...doc.fields,
    el("div", { class: "actions" }, [importButton]),
    message,
  ];
}

async function load(overleafProjectId: string): Promise<void> {
  if (!panel) {
    return;
  }
  const body = panel.body;
  const generation = ++loadGeneration;
  const current = () => generation === loadGeneration;
  clear(body).append(loading());
  const reload = () => void load(overleafProjectId);
  try {
    hubWebUrl = await getHubWebUrl();
    const settings = await send({ type: "settings.get" });
    // Filled in as the hub answers, without holding up the rest, which
    // for a project on this machine doesn't need the hub at all
    const pickers = el("div", {
      class: "muted-box stack",
      style: { marginBottom: "8px" },
    });
    void Promise.all([
      renderHubPicker(reload),
      renderProjectPicker({
        activeProject: settings.activeProject,
        onChange: reload,
      }),
    ]).then((parts) => pickers.append(...parts));
    const cached =
      lastCheck?.overleafProjectId === overleafProjectId &&
      lastCheck.hubWebUrl === hubWebUrl
        ? lastCheck
        : null;
    const content = el("div");
    // The hub's pickers are beside the point for a project worked on here
    clear(body).append(...(cached?.link.local_path ? [] : [pickers]), content);
    const showNotice = () => {
      if (cached?.notice) {
        content.append(
          el("div", {
            class: "dim small",
            style: { marginTop: "6px" },
            text: cached.notice,
          }),
        );
      }
    };
    if (cached) {
      renderStatus(content, cached.link, cached.status, reload);
      showNotice();
      content.append(loading("Checking for changes"));
    } else {
      content.append(loading("Finding linked project"));
    }
    // The index answers at once when this Overleaf project has been seen
    // before; otherwise the hub reads through the user's projects, active
    // one first, and remembers what it finds
    const lookup = await send({
      type: "overleaf.lookup",
      overleafProjectId,
      activeProject: settings.activeProject ?? undefined,
    });
    if (!current()) {
      return;
    }
    const links = lookup.links;
    lastUnlinked = !links.length && lookup.projects_remaining === 0;
    if (!links.length) {
      clear(body).append(pickers);
      if (lookup.projects_remaining > 0) {
        body.append(
          el("div", { class: "dim small" }, [
            document.createTextNode(
              `Checked ${lookup.projects_scanned} project(s); ` +
                `${lookup.projects_remaining} left to look through.`,
            ),
          ]),
          el("div", { class: "actions" }, [
            el("button", {
              class: "action secondary",
              text: "Keep looking",
              onClick: reload,
            }),
          ]),
        );
      }
      const chooser = el("div");
      body.append(chooser);
      await renderPicker(chooser, overleafProjectId, reload);
      return;
    }
    // A folder in more than one project is rare, so the first link is the
    // one shown, with the rest offered as alternatives underneath
    const link = links[0];
    if (link.local_path) {
      pickers.remove();
    } else if (!pickers.isConnected) {
      body.prepend(pickers);
    }
    if (!cached) {
      clear(content).append(
        loading(`Checking ${link.project_owner_name}/${link.project_name}`),
      );
    }
    const statusRequest = {
      type: "overleaf.status",
      owner: link.project_owner_name,
      project: link.project_name,
      overleafProjectId,
      path: link.path,
    } as const;
    // On this machine, what's known from the last pull comes at once,
    // and is shown while Overleaf is asked for anything newer
    if (link.local_path) {
      const known = await send({ ...statusRequest, pull: false }).catch(
        () => [],
      );
      if (!current()) {
        return;
      }
      if (known.length && !known[0].pulled) {
        // As of the last sync, e.g., by a run that just ended
        checkingAfterSync = false;
        renderStatus(content, link, known[0], reload);
        content.append(loading("Checking Overleaf for new edits"));
      }
    }
    const files = link.local_path
      ? await getOverleafFiles(overleafProjectId)
      : null;
    const statuses = await send({
      ...statusRequest,
      overleafFiles: files?.shas,
      overleafTexts: files?.texts,
    });
    if (!current()) {
      return;
    }
    if (!statuses.length) {
      clear(content).append(
        el("div", {
          class: "dim small",
          text:
            "The project no longer syncs a folder with this Overleaf " +
            "project. Reload to select a different project.",
        }),
      );
      return;
    }
    lastTokenProblem = false;
    lastSyncNeeded = !statuses[0].in_sync;
    currentLink = link;
    void checkCitations();
    lastCheck = { overleafProjectId, hubWebUrl, link, status: statuses[0] };
    // Checked since the last run or sync, so it's current again
    checkingAfterSync = false;
    drawRail();
    renderStatus(content, link, statuses[0], reload);
    showNotice();
    content.append(renderInsert(link, statuses[0].path, reload));
    if (links.length > 1) {
      content.append(
        el("div", {
          class: "dim small",
          style: { marginTop: "8px" },
          text: `Also linked from ${links.length - 1} other project(s).`,
        }),
      );
    }
  } catch (e) {
    if (!current()) {
      return;
    }
    checkingAfterSync = false;
    drawRail();
    clear(body);
    if (e instanceof RequestFailed && e.notSignedIn) {
      // With a hub picker alongside, since credentials are per hub and a
      // signed-out panel otherwise has no way back to the right one
      body.append(renderFailure(e, { onSignedIn: reload }));
      return;
    }
    if (isUnsupportedByHub(e)) {
      // Hubs deploy separately from the extension, so this is a version
      // gap rather than anything the user did wrong. Saying "Not Found",
      // which is all the hub sends back for a route it doesn't have,
      // would send them looking for a missing project instead
      body.append(
        errorMessage(
          `${hubWebUrl.replace(/^https?:\/\//, "")} doesn't support ` +
            "Overleaf sync yet.",
        ),
        el("div", {
          class: "dim small",
          style: { marginTop: "6px" },
          text: "Switch to a hub running a newer version to sync from here.",
        }),
        el("div", { style: { marginTop: "8px" } }, [
          await renderHubPicker(reload),
        ]),
      );
      return;
    }
    // The picker stays, since the problem may be with this hub, e.g., an
    // Overleaf token only another hub has, and switching is the way out
    const hubPicker = el("div", { style: { marginBottom: "8px" } }, [
      await renderHubPicker(reload),
    ]);
    if (isOverleafTokenProblem(e)) {
      body.append(hubPicker);
      renderTokenForm(body, e instanceof Error ? e.message : String(e), reload);
      return;
    }
    body.append(
      hubPicker,
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
  }
}

/**
 * The button that opens the panel, and what it collapses back to.
 *
 * Its tone carries the one thing worth interrupting for: amber means a
 * sync would do something, which is how a stale figure gets noticed
 * without the panel opening on top of the document uninvited. A paper
 * not in any project gets it too, since linking it is the first step.
 */
type LauncherTone =
  | "idle"
  | "attention"
  | "reconnect"
  | "unlinked"
  | "running"
  | "syncing"
  | "origins";

function mountLauncher(
  onClick: () => void,
  tone: LauncherTone = "idle",
  keep = false,
): void {
  const missing = getMissingOrigins().length;
  const state = `${currentProjectId}|${tone}|${missing}`;
  // Redrawn only for a change, since one under a click would swallow it
  const existing = document.getElementById(LAUNCHER_ID);
  if (keep && existing?.dataset.state === state) {
    return;
  }
  existing?.remove();
  const host = el("div", { attrs: { id: LAUNCHER_ID } });
  host.dataset.state = state;
  Object.assign(host.style, {
    position: "fixed",
    ...launcherPosition(),
    zIndex: "2147482999",
  });
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = `
    button {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica,
        Arial, sans-serif;
      font-size: 12px;
      font-weight: 600;
      color: #ffffff;
      background: #009688;
      border: 0;
      border-radius: 999px;
      padding: 8px 14px;
      cursor: pointer;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    }
    button:hover { filter: brightness(1.1); }
    button.attention { background: #d69e2e; }
    button.danger { background: #e5484d; }
  `;
  const button = el("button", {
    text: {
      idle: "Calkit",
      attention: "Calkit: sync needed",
      reconnect: "Calkit: reconnect Overleaf",
      unlinked: "Calkit: not linked",
      running: "Calkit: running",
      syncing: "Calkit: syncing",
      origins: `Calkit: ${missing} missing origin`,
    }[tone],
    class:
      tone === "origins"
        ? "danger"
        : ["idle", "running", "syncing"].includes(tone)
        ? ""
        : "attention",
  });
  button.addEventListener("click", onClick);
  root.append(style, button);
  document.body.append(host);
}

// Remembered so a closed panel can still show that something is waiting
let lastSyncNeeded = false;
// A sync from here is going, which the sidebar and launcher show
export let syncing = false;
let lastTokenProblem = false;
let lastUnlinked = false;

function launcherTone(): LauncherTone {
  if (lastTokenProblem) {
    return "reconnect";
  }
  if (lastUnlinked) {
    return "unlinked";
  }
  if (syncing) {
    return "syncing";
  }
  if (activeRun()) {
    return "running";
  }
  if (getMissingOrigins().length) {
    return "origins";
  }
  return lastSyncNeeded ? "attention" : "idle";
}

export function openPanel(
  overleafProjectId: string,
  fill?: (body: HTMLElement) => void,
): void {
  document.getElementById(LAUNCHER_ID)?.remove();
  panel = mountPanel({
    id: PANEL_ID,
    title: "Calkit",
    onClose: () => {
      panel = null;
      mountLauncher(() => openPanel(overleafProjectId), launcherTone());
    },
  });
  if (fill) {
    fill(panel.body);
  } else {
    void load(overleafProjectId);
  }
}

/** Open the panel on something to do, e.g., a fix from a tooltip. */
export function showInPanel(
  fill: (body: HTMLElement) => void | Promise<void>,
): void {
  const overleafProjectId = currentProjectId;
  if (!overleafProjectId) {
    return;
  }
  openPanel(overleafProjectId, (body) => {
    // Its own element, so what clears it keeps the way back
    const content = el("div");
    body.append(
      el("button", {
        class: "action secondary",
        text: "\u2190 Back",
        onClick: () => openPanel(overleafProjectId),
      }),
      content,
    );
    void fill(content);
  });
}

function teardown(): void {
  tokenWatcher?.disconnect();
  tokenWatcher = null;
  document.getElementById(TOKEN_PANEL_ID)?.remove();
  document.getElementById(LAUNCHER_ID)?.remove();
  panel?.remove();
  panel = null;
  currentProjectId = null;
  currentLink = null;
}

/**
 * Stop watching the page and remove all this script put in it, when the
 * extension's reloaded or a newer copy of this script takes over.
 */
function shutdown(): void {
  watching.abort();
  setRail(false);
  removePdfViewer();
  for (const id of [
    "calkit-pdf-switch",
    "calkit-comments-toggle",
    "calkit-integration",
    "calkit-insert-divider",
    RAIL_TAB_ID,
  ]) {
    document.getElementById(id)?.remove();
  }
  document.getElementById("calkit-insert")?.parentElement?.remove();
  railStyle?.remove();
  teardown();
}

export function sync(): void {
  if (new URL(window.location.href).pathname.startsWith("/user/settings")) {
    void watchForNewToken();
    return;
  }
  const overleafProjectId = getOverleafProjectId(window.location.href);
  if (!overleafProjectId) {
    teardown();
    return;
  }
  if (overleafProjectId === currentProjectId) {
    return;
  }
  currentProjectId = overleafProjectId;
  // A button, not an open panel: this sits on top of someone's document,
  // and opening uninvited is the extension deciding it matters more than
  // what they were doing. The check below is what earns the click.
  mountLauncher(() => openPanel(overleafProjectId));
  void checkSyncStatus(overleafProjectId);
}

/**
 * Ask whether this Overleaf project has anything waiting, and say so on
 * the button.
 *
 * The whole point of the panel is catching a figure that was regenerated
 * and never made it to Overleaf, which nobody would think to open a panel
 * to find out. So the question is asked quietly and only the answer
 * shows: an amber button when a sync would do something.
 */
async function checkSyncStatus(overleafProjectId: string): Promise<void> {
  // An answer from a hub or sign-in that has since changed describes
  // something else, so it's dropped rather than cached
  const generation = loadGeneration;
  const hub = await getHubWebUrl();
  const current = async () =>
    generation === loadGeneration && (await getHubWebUrl()) === hub;
  try {
    const settings = await send({ type: "settings.get" });
    const lookup = await send({
      type: "overleaf.lookup",
      overleafProjectId,
      activeProject: settings.activeProject ?? undefined,
    });
    const link = lookup.links[0];
    if (!link) {
      if (!(await current())) {
        return;
      }
      // Only when every project was checked, since the rest might link it
      lastUnlinked = lookup.projects_remaining === 0;
      if (lastUnlinked && !panel && currentProjectId === overleafProjectId) {
        mountLauncher(() => openPanel(overleafProjectId), "unlinked");
      }
      return;
    }
    // Cards link to the hub the project was found on, and can show before
    // the panel, which also sets it, is opened
    hubWebUrl = hub;
    currentLink = link;
    void checkCitations();
    drawRail();
    if (railOpen && railPipeline?.key !== linkKey(link)) {
      void refreshRailPipeline(link);
    }
    if (pipelineRuns?.key !== linkKey(link)) {
      void refreshRuns(link);
    }
    const files = link.local_path
      ? await getOverleafFiles(overleafProjectId)
      : null;
    const statuses = await send({
      type: "overleaf.status",
      owner: link.project_owner_name,
      project: link.project_name,
      overleafProjectId,
      path: link.path,
      overleafFiles: files?.shas,
      overleafTexts: files?.texts,
    });
    if (!(await current())) {
      return;
    }
    lastTokenProblem = false;
    lastUnlinked = false;
    lastSyncNeeded = Boolean(statuses.length) && !statuses[0].in_sync;
    lastCheck = statuses.length
      ? { overleafProjectId, hubWebUrl: hub, link, status: statuses[0] }
      : null;
    checkingAfterSync = false;
    drawStatusParts();
    drawRail();
    mountPdfSwitch();
    // Nothing to say if the panel was opened in the meantime, or if the
    // page moved on to another project
    if (panel || currentProjectId !== overleafProjectId) {
      return;
    }
    mountLauncher(() => openPanel(overleafProjectId), launcherTone());
  } catch (e) {
    if (!(await current())) {
      return;
    }
    checkingAfterSync = false;
    drawStatusParts();
    drawRail();
    // A token problem is worth a nudge, since nothing works until it's
    // fixed; anything else the panel explains when opened
    lastTokenProblem = isOverleafTokenProblem(e);
    if (lastTokenProblem && !panel && currentProjectId === overleafProjectId) {
      mountLauncher(() => openPanel(overleafProjectId), "reconnect");
    }
  }
}

/**
 * Re-check after a save, since that is exactly when the answer changes.
 *
 * Overleaf saves continuously, so this listens for the explicit save
 * people still press rather than trying to observe every keystroke, and
 * waits a moment for Overleaf to have written it before asking.
 */
let recheckTimer: ReturnType<typeof setTimeout> | undefined;

/**
 * Check again what there is to sync, a while after the last change, e.g.,
 * a save, or an edit Overleaf saves by itself, like a comment added from
 * the PDF, which the sync has to bring to this machine.
 */
export function recheckAfterEdit(delay: number): void {
  clearTimeout(recheckTimer);
  recheckTimer = setTimeout(() => {
    if (!currentProjectId) {
      return;
    }
    // The button has to notice it too, not just an already-open panel
    if (panel) {
      void load(currentProjectId);
    } else {
      void checkSyncStatus(currentProjectId);
    }
  }, delay);
}

function watchForSaves(): void {
  document.addEventListener(
    "keydown",
    (event) => {
      const isSave =
        (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s";
      if (isSave && currentProjectId) {
        recheckAfterEdit(2000);
      }
    },
    { capture: true, signal: watching.signal },
  );
}

// Redraws the open panel's sync and run buttons, e.g., once it's known
// what's out of date
export let drawPanelActions: () => void = () => undefined;

// Redraws what the panel says of origins, while it's showing a status
export let drawPanelOrigins: (() => void) | null = null;

/**
 * List Calkit among Overleaf's own integrations, beside GitHub and
 * Dropbox, as another way to open the panel.
 */
function watchIntegrations(): void {
  // An image has no text color to inherit, so the logo gets its own
  const icon = `data:image/svg+xml,${encodeURIComponent(
    calkitLogo.replace(/currentColor/g, "#009688"),
  )}`;
  const addCard = () => {
    const list = document.querySelector(".integrations-panel");
    if (!list || !currentProjectId) {
      return;
    }
    const description = currentLink
      ? `Synced with ${currentLink.project_owner_name}/${currentLink.project_name}.`
      : "Make this paper reproducible.";
    const existing = list.querySelector<HTMLElement>("#calkit-integration");
    if (existing) {
      const text = existing.querySelector(
        ".integrations-panel-card-description",
      );
      if (text && text.textContent !== description) {
        text.textContent = description;
      }
      return;
    }
    const card = el(
      "button",
      {
        class: "integrations-panel-card-button",
        attrs: { id: "calkit-integration", type: "button" },
      },
      [
        el("div", { class: "integrations-panel-card-contents" }, [
          el("div", { class: "integrations-panel-card-icon" }, [
            el("img", {
              attrs: { src: icon, alt: "", width: "32", height: "32" },
            }),
          ]),
          el("div", { class: "integrations-panel-card-inner" }, [
            el("div", { class: "integrations-panel-card-header" }, [
              el("div", {
                class: "integrations-panel-card-title",
                text: "Calkit",
                attrs: { translate: "no" },
              }),
            ]),
            el("p", {
              class: "integrations-panel-card-description",
              text: description,
            }),
          ]),
        ]),
      ],
    );
    card.addEventListener("click", () => {
      if (currentProjectId && !panel) {
        openPanel(currentProjectId);
      }
    });
    // First after the header, being the one that brings the rest together
    const header = list.querySelector(".rail-panel-header");
    if (header) {
      header.after(card);
    } else {
      list.prepend(card);
    }
  };
  observePage(addCard, 100);
}

/**
 * Add inserting from the project to the editor's right-click menu, which
 * Overleaf draws itself rather than leaving to the browser. Right-clicking
 * moves the cursor there, so that's where it's inserted.
 */
function watchContextMenu(): void {
  const addItem = () => {
    const menu = document.querySelector<HTMLElement>(
      ".editor-context-menu-container ul[role=menu]",
    );
    const check = lastCheck;
    const ours = menu?.querySelector("#calkit-insert")?.parentElement;
    if (ours) {
      // Kept last, since Overleaf adds some of its own items after opening
      if (ours !== menu?.lastElementChild) {
        menu?.append(menu.querySelector("#calkit-insert-divider") ?? "", ours);
      }
      return;
    }
    if (
      !menu ||
      !check ||
      check.link !== currentLink ||
      check.link.current_user_access === "read"
    ) {
      return;
    }
    const item = el("button", {
      class: "dropdown-item",
      text: "Insert from Calkit\u2026",
      attrs: { id: "calkit-insert", role: "menuitem", type: "button" },
    });
    item.addEventListener("click", () => {
      // Closes Overleaf's menu, as choosing one of its own items would
      menu.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
      showInPanel((body) =>
        body.append(
          renderInsert(check.link, check.status.path, () =>
            openPanel(check.overleafProjectId),
          ),
        ),
      );
    });
    menu.append(
      el("li", {
        class: "dropdown-divider",
        attrs: { id: "calkit-insert-divider", role: "separator" },
      }),
      el("li", { attrs: { role: "none" } }, [item]),
    );
  };
  observePage(addItem, null);
}

runContentScript({
  id: "overleaf",
  watch: () => {
    watchForSaves();
    watchEditor();
    watchPdf();
    watchIntegrations();
    watchRail();
    watchContextMenu();
    watchPdfSwitch();
    watchReview();
  },
  sync,
  teardown: shutdown,
  authChanged: () => {
    if (!currentProjectId) {
      return;
    }
    const overleafProjectId = currentProjectId;
    // What the last session found says nothing about this one
    loadGeneration++;
    lastSyncNeeded = false;
    lastTokenProblem = false;
    lastUnlinked = false;
    currentLink = null;
    provenanceCache.clear();
    lastCheck = null;
    if (panel) {
      void load(overleafProjectId);
    } else {
      mountLauncher(() => openPanel(overleafProjectId));
      void checkSyncStatus(overleafProjectId);
    }
  },
});
