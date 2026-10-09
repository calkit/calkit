import { execFile } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { promisify } from "node:util";
import * as zlib from "node:zlib";
import * as vscode from "vscode";

import {
  LIGATURES,
  findText,
  latexStageSource,
  lineMap,
  normalizeSelection,
  paragraphLines,
  parseSynctex,
  synctexForward,
  synctexInputFile,
  synctexReverse,
  synctexTag,
  type PdfRect,
  type Synctex,
  type TexThread,
} from "./core";

const execFileAsync = promisify(execFile);

export const PDF_REVIEW_VIEW_TYPE = "calkit.pdfReview";

export interface PdfReviewDeps {
  getWorkspaceRoot: () => string | undefined;
  getStages: () => Record<string, unknown>;
  getNonce: () => string;
}

// A thread with where its paragraph is in the PDF, keyed so the webview can
// refer back to it whether or not it has an ID yet.
interface ThreadView extends TexThread {
  key: string;
  start?: PdfRect;
  end?: PdfRect;
}

interface Viewer {
  panel: vscode.WebviewPanel;
  // Project-relative, as the CLI and SyncTeX see them
  pdf: string;
  tex?: string;
  synctex?: Synctex;
  // The source files as the PDF was built from them, so lines can be
  // followed after comments are added, which don't change the PDF
  built?: Record<string, string>;
  // Sources changed since the build with no snapshot, where comments can be
  // misplaced until it's rebuilt
  stale?: string[];
  ready: boolean;
  pendingReveal?: PdfRect;
}

// A PDF viewer for LaTeX documents that shows the comment threads in their
// source, following the Calkit LaTeX comment schema, and goes between the
// PDF and source with SyncTeX.
export class PdfReviewProvider implements vscode.CustomReadonlyEditorProvider {
  private viewers = new Set<Viewer>();

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly deps: PdfReviewDeps,
  ) {
    // Comments are in the source, so any change to it can change them
    const texWatcher = vscode.workspace.createFileSystemWatcher("**/*.tex");
    let debounce: ReturnType<typeof setTimeout> | undefined;
    const refresh = (): void => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        for (const v of this.viewers) {
          void this.sendThreads(v);
        }
      }, 300);
    };
    texWatcher.onDidChange(refresh);
    texWatcher.onDidCreate(refresh);
    texWatcher.onDidDelete(refresh);
    context.subscriptions.push(texWatcher);
  }

  openCustomDocument(uri: vscode.Uri): vscode.CustomDocument {
    return { uri, dispose: () => undefined };
  }

  resolveCustomEditor(
    document: vscode.CustomDocument,
    panel: vscode.WebviewPanel,
  ): void {
    const root =
      this.deps.getWorkspaceRoot() ?? path.dirname(document.uri.fsPath);
    const pdf = rel(root, document.uri.fsPath);
    const stem = pdf.replace(/\.pdf$/i, "");
    const tex =
      latexStageSource(this.deps.getStages(), pdf) ??
      (fs.existsSync(path.join(root, `${stem}.tex`))
        ? `${stem}.tex`
        : undefined);
    const viewer: Viewer = { panel, pdf, tex, ready: false };
    this.viewers.add(viewer);
    this.setOpenContext();
    const pdfjs = vscode.Uri.joinPath(
      this.context.extensionUri,
      "node_modules",
      "pdfjs-dist",
    );
    panel.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.file(root), pdfjs],
    };
    panel.webview.html = buildHtml(
      panel.webview,
      pdfjs,
      this.deps.getNonce(),
      path.basename(pdf),
    );
    // Rebuilding the PDF rewrites its SyncTeX file too
    const watcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(
        vscode.Uri.file(path.dirname(document.uri.fsPath)),
        `${path.basename(stem)}.{pdf,synctex.gz,synctex}`,
      ),
    );
    let debounce: ReturnType<typeof setTimeout> | undefined;
    const reload = (): void => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        viewer.synctex = undefined;
        this.sendPdf(viewer);
        void this.sendThreads(viewer);
      }, 300);
    };
    watcher.onDidChange(reload);
    watcher.onDidCreate(reload);
    panel.onDidDispose(() => {
      watcher.dispose();
      this.viewers.delete(viewer);
      this.setOpenContext();
    });
    panel.webview.onDidReceiveMessage((msg) =>
      this.onMessage(viewer, msg).catch((err) =>
        vscode.window.showErrorMessage(String(err?.message ?? err)),
      ),
    );
  }

  // Show a source line in an open viewer of a PDF it's part of, returning
  // whether one was found.
  reveal(file: string, line: number): boolean {
    for (const v of this.viewers) {
      const s = this.loadSynctex(v);
      const tag = s && synctexTag(s, file);
      const rect =
        s && tag !== undefined
          ? synctexForward(s, tag, this.lines(v, file).toBefore(line))
          : undefined;
      if (rect) {
        v.panel.reveal(undefined, true);
        if (v.ready) {
          void v.panel.webview.postMessage({ type: "reveal", rect });
        } else {
          v.pendingReveal = rect;
        }
        return true;
      }
    }
    return false;
  }

  // For the keybinding that goes from source to PDF
  private setOpenContext(): void {
    void vscode.commands.executeCommand(
      "setContext",
      "calkit.pdfReviewOpen",
      this.viewers.size > 0,
    );
  }

  private root(): string {
    return this.deps.getWorkspaceRoot() ?? "";
  }

  private loadSynctex(v: Viewer): Synctex | undefined {
    if (v.synctex) {
      return v.synctex;
    }
    const root = this.root();
    const stem = path.join(root, v.pdf.replace(/\.pdf$/i, ""));
    const file = [`${stem}.synctex.gz`, `${stem}.synctex`].find((f) =>
      fs.existsSync(f),
    );
    if (!file) {
      return undefined;
    }
    try {
      const data = fs.readFileSync(file);
      v.synctex = parseSynctex(
        (file.endsWith(".gz") ? zlib.gunzipSync(data) : data).toString(),
      );
    } catch {
      // Mid-write during a build; the watcher tries again when it's done
      return undefined;
    }
    // Sources not changed since the build are as built. The snapshot is
    // kept, since comments added later change them without a rebuild.
    const mtime = fs.statSync(file).mtimeMs;
    const key = `calkit.pdfReview.built:${v.pdf}`;
    const saved = this.context.workspaceState.get<{
      mtime: number;
      files: Record<string, string>;
      stale: string[];
    }>(key);
    if (saved?.mtime === mtime) {
      v.built = saved.files;
      v.stale = saved.stale;
      return v.synctex;
    }
    v.built = {};
    v.stale = [];
    for (const input of v.synctex.inputs.values()) {
      const f = synctexInputFile(input, (f) =>
        fs.existsSync(path.join(root, f)),
      );
      const abs = f && path.join(root, f);
      if (!f || !abs || !f.endsWith(".tex")) {
        continue;
      }
      if (fs.statSync(abs).mtimeMs <= mtime + 2000) {
        v.built[f] = fs.readFileSync(abs, "utf8");
      } else {
        v.stale.push(f);
      }
    }
    void this.context.workspaceState.update(key, {
      mtime,
      files: v.built,
      stale: v.stale,
    });
    return v.synctex;
  }

  // Line numbers between the source now and as the PDF was built from it
  private lines(
    v: Viewer,
    file: string,
  ): { toAfter: (line: number) => number; toBefore: (line: number) => number } {
    const built = v.built?.[file];
    const abs = path.join(this.root(), file);
    if (built === undefined || !fs.existsSync(abs)) {
      return { toAfter: (l) => l, toBefore: (l) => l };
    }
    return lineMap(built.split("\n"), fs.readFileSync(abs, "utf8").split("\n"));
  }

  private sendPdf(v: Viewer): void {
    const uri = vscode.Uri.file(path.join(this.root(), v.pdf));
    const url = v.panel.webview.asWebviewUri(uri).toString();
    void v.panel.webview.postMessage({
      type: "load",
      url: `${url}?v=${Date.now()}`,
    });
  }

  private async sendThreads(v: Viewer): Promise<void> {
    if (!v.tex) {
      void v.panel.webview.postMessage({
        type: "status",
        text: "No LaTeX source found for this PDF, so no comments to show.",
      });
      return;
    }
    let threads: TexThread[];
    try {
      const { stdout } = await execFileAsync(
        "calkit",
        ["latex", "comments", "list", v.tex, "--json"],
        { cwd: this.root(), maxBuffer: 64 * 1024 * 1024 },
      );
      threads = JSON.parse(stdout);
    } catch (err) {
      const text = /No such command/.test(
        String((err as { stderr?: string }).stderr),
      )
        ? "Upgrade Calkit to see comments: calkit upgrade"
        : `Couldn't list comments: ${String((err as Error).message ?? err)}`;
      void v.panel.webview.postMessage({ type: "status", text });
      return;
    }
    const s = this.loadSynctex(v);
    const views: ThreadView[] = threads.map((t) => {
      const key = t.id ?? `${t.path}:${t.line}`;
      const tag = s ? synctexTag(s, t.path) : undefined;
      if (!s || tag === undefined) {
        return { ...t, key };
      }
      const { toBefore } = this.lines(v, t.path);
      const first = toBefore(t.anchor?.line ?? t.line + t.nlines);
      const last = toBefore(t.anchor?.end_line ?? t.line + t.nlines);
      return {
        ...t,
        key,
        start: synctexForward(s, tag, first),
        end: synctexForward(s, tag, last, true),
      };
    });
    void v.panel.webview.postMessage({
      type: "threads",
      threads: views,
      synctex: s !== undefined,
      stale: v.stale ?? [],
    });
  }

  // Run a comments command that edits a file, after making sure the editor
  // doesn't hold unsaved changes the edit would clash with.
  private async edit(file: string, args: string[]): Promise<string> {
    const abs = path.join(this.root(), file);
    const open = vscode.workspace.textDocuments.find(
      (d) => d.uri.fsPath === abs && d.isDirty,
    );
    if (open) {
      const choice = await vscode.window.showWarningMessage(
        `${file} has unsaved changes. Save it before changing comments?`,
        "Save",
      );
      if (choice !== "Save" || !(await open.save())) {
        throw new Error("Comment not changed, since the file isn't saved.");
      }
    }
    const { stdout } = await execFileAsync(
      "calkit",
      ["latex", "comments", ...args],
      { cwd: this.root() },
    );
    return stdout.trim();
  }

  private async openSource(file: string, line: number): Promise<void> {
    const uri = vscode.Uri.file(path.join(this.root(), file));
    const visible = vscode.window.visibleTextEditors.find(
      (e) => e.document.uri.fsPath === uri.fsPath,
    );
    const pos = new vscode.Position(Math.max(line - 1, 0), 0);
    await vscode.window.showTextDocument(uri, {
      viewColumn: visible?.viewColumn ?? vscode.ViewColumn.Beside,
      selection: new vscode.Range(pos, pos),
    });
  }

  private async onMessage(
    v: Viewer,
    msg: { type: string; [key: string]: unknown },
  ): Promise<void> {
    const root = this.root();
    // A thread's ID, or its line for one that doesn't have an ID yet
    const ref = (): string[] =>
      typeof msg.id === "string"
        ? ["--id", msg.id]
        : ["--line", String(msg.line)];
    switch (msg.type) {
      case "ready":
        v.ready = true;
        this.sendPdf(v);
        await this.sendThreads(v);
        if (v.pendingReveal) {
          void v.panel.webview.postMessage({
            type: "reveal",
            rect: v.pendingReveal,
          });
          v.pendingReveal = undefined;
        }
        return;
      case "sourceAt": {
        const s = this.loadSynctex(v);
        const at =
          s &&
          synctexReverse(s, Number(msg.page), Number(msg.x), Number(msg.y));
        const file =
          at &&
          synctexInputFile(at.input, (f) => fs.existsSync(path.join(root, f)));
        if (!at || !file) {
          void vscode.window.showInformationMessage(
            "No source found there. Is the PDF built with SyncTeX?",
          );
          return;
        }
        await this.openSource(file, this.lines(v, file).toAfter(at.line));
        return;
      }
      case "locate": {
        // Where a selection's paragraph starts, so the webview can count
        // earlier occurrences of the selected text in it
        const s = this.loadSynctex(v);
        const at =
          s &&
          synctexReverse(s, Number(msg.page), Number(msg.x), Number(msg.y));
        const file =
          at &&
          synctexInputFile(at.input, (f) => fs.existsSync(path.join(root, f)));
        let start: PdfRect | undefined;
        let line: number | undefined;
        if (s && at && file) {
          const map = this.lines(v, file);
          line = map.toAfter(at.line);
          const lines = fs
            .readFileSync(path.join(root, file), "utf8")
            .split("\n");
          const para = paragraphLines(lines, line);
          const tag = synctexTag(s, file);
          start =
            tag === undefined
              ? undefined
              : synctexForward(s, tag, map.toBefore(para.start));
        }
        void v.panel.webview.postMessage({
          type: "located",
          reqId: msg.reqId,
          file,
          line,
          start,
        });
        return;
      }
      case "add": {
        const args = [
          "add",
          String(msg.file),
          "--line",
          String(msg.line),
          "-m",
          String(msg.text),
        ];
        if (typeof msg.highlight === "string" && msg.highlight) {
          args.push(
            "--highlight",
            msg.highlight,
            "--occ",
            String(msg.occ ?? 0),
          );
        }
        await this.edit(String(msg.file), args);
        break;
      }
      case "reply":
        await this.edit(String(msg.file), [
          "reply",
          String(msg.file),
          ...ref(),
          "-m",
          String(msg.text),
        ]);
        break;
      case "resolve":
        await this.edit(String(msg.file), [
          msg.resolved ? "resolve" : "reopen",
          String(msg.file),
          ...ref(),
        ]);
        break;
      case "delete": {
        const choice = await vscode.window.showWarningMessage(
          "Delete this comment thread and its replies?",
          { modal: true },
          "Delete",
        );
        if (choice !== "Delete") {
          return;
        }
        await this.edit(String(msg.file), [
          "delete",
          String(msg.file),
          ...ref(),
        ]);
        break;
      }
      case "openSource":
        await this.openSource(String(msg.file), Number(msg.line));
        return;
      case "openIssue":
        if (typeof msg.url === "string" && /^https?:\/\//.test(msg.url)) {
          await vscode.env.openExternal(vscode.Uri.parse(msg.url));
        }
        return;
      default:
        return;
    }
    await this.sendThreads(v);
  }
}

function rel(root: string, fsPath: string): string {
  return path.relative(root, fsPath).replace(/\\/g, "/");
}

function buildHtml(
  webview: vscode.Webview,
  pdfjs: vscode.Uri,
  nonce: string,
  title: string,
): string {
  const uri = (...p: string[]): string =>
    webview.asWebviewUri(vscode.Uri.joinPath(pdfjs, ...p)).toString();
  const csp = webview.cspSource;
  const config = {
    lib: uri("legacy", "build", "pdf.min.mjs"),
    worker: uri("legacy", "build", "pdf.worker.min.mjs"),
    viewer: uri("legacy", "web", "pdf_viewer.mjs"),
    cMapUrl: `${uri("cmaps")}/`,
    standardFontDataUrl: `${uri("standard_fonts")}/`,
    wasmUrl: `${uri("wasm")}/`,
    iccUrl: `${uri("iccs")}/`,
  };
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}' 'wasm-unsafe-eval' ${csp}; style-src 'unsafe-inline' ${csp}; img-src ${csp} data: blob:; font-src ${csp} data: blob:; connect-src ${csp}; worker-src blob:;">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escapeHtml(title)}</title>
<link rel="stylesheet" href="${uri("legacy", "web", "pdf_viewer.css")}">
<style>
  :root { --open: #e8a317; --resolved: #8a8a8a; --panel-width: 320px; }
  html, body { margin: 0; padding: 0; height: 100%; overflow: hidden;
    font-family: var(--vscode-font-family); font-size: var(--vscode-font-size);
    color: var(--vscode-foreground); background: var(--vscode-editor-background); }
  #toolbar { display: flex; align-items: center; gap: 6px; padding: 4px 8px;
    border-bottom: 1px solid var(--vscode-panel-border); height: 28px; box-sizing: content-box; }
  #toolbar .spacer { flex: 1; }
  #toolbar #status { opacity: 0.8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  button { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground);
    border: none; padding: 3px 8px; border-radius: 2px; cursor: pointer; font: inherit; }
  button:hover { background: var(--vscode-button-secondaryHoverBackground); }
  button.primary { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
  button.primary:hover { background: var(--vscode-button-hoverBackground); }
  button[aria-pressed="true"] { outline: 1px solid var(--vscode-focusBorder); }
  label { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
  #main { position: absolute; top: 37px; left: 0; right: 0; bottom: 0; display: flex; }
  #wrap { position: relative; flex: 1; }
  #viewerContainer { position: absolute; inset: 0; overflow: auto; background: var(--vscode-editorWidget-background, #525659); }
  #panel { width: var(--panel-width); overflow-y: auto; border-left: 1px solid var(--vscode-panel-border);
    padding: 8px; box-sizing: border-box; }
  body.no-comments #panel { display: none; }
  body.no-comments .ck-layer { display: none; }
  .ck-layer { position: absolute; inset: 0; pointer-events: none; z-index: 5; }
  .ck-hl { position: absolute; background: rgba(255, 200, 0, 0.35); pointer-events: auto; cursor: pointer;
    mix-blend-mode: multiply; }
  .ck-hl.resolved { background: rgba(140, 140, 140, 0.25); }
  .ck-hl.selected { background: rgba(255, 160, 0, 0.6); }
  .ck-bar { position: absolute; width: 3px; background: var(--open); pointer-events: auto; cursor: pointer; }
  .ck-bar.resolved { background: var(--resolved); }
  .ck-pin { position: absolute; min-width: 18px; height: 18px; border-radius: 9px 9px 9px 2px; background: var(--open);
    color: #000; font: bold 11px sans-serif; display: flex; align-items: center; justify-content: center;
    pointer-events: auto; cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.4); padding: 0 4px; box-sizing: border-box; }
  .ck-pin.resolved { background: var(--resolved); }
  .ck-pin.selected { outline: 2px solid var(--vscode-focusBorder); }
  .ck-flash { position: absolute; background: rgba(0, 120, 255, 0.25); border-radius: 2px; pointer-events: none;
    animation: ck-fade 1.6s ease-out forwards; }
  @keyframes ck-fade { 0%, 50% { opacity: 1; } 100% { opacity: 0; } }
  .thread { border: 1px solid var(--vscode-panel-border); border-left: 3px solid var(--open); border-radius: 3px;
    padding: 6px 8px; margin-bottom: 8px; cursor: pointer; }
  .thread.resolved { border-left-color: var(--resolved); opacity: 0.8; }
  .thread.selected { outline: 1px solid var(--vscode-focusBorder); }
  .thread .quote { border-left: 2px solid var(--vscode-textBlockQuote-border, #888); padding-left: 6px; margin: 2px 0 6px;
    font-style: italic; opacity: 0.85; }
  .msg { margin: 4px 0; }
  .msg .who { font-weight: 600; }
  .msg .when { opacity: 0.6; font-size: 0.9em; margin-left: 4px; }
  .msg .text { white-space: pre-wrap; word-wrap: break-word; }
  .thread .meta { display: flex; gap: 6px; align-items: center; font-size: 0.9em; opacity: 0.8; margin-bottom: 2px; }
  .thread .actions { display: none; gap: 4px; flex-wrap: wrap; margin-top: 6px; }
  .thread.selected .actions, .thread.composer .actions { display: flex; }
  textarea { width: 100%; box-sizing: border-box; min-height: 48px; resize: vertical; font: inherit;
    color: var(--vscode-input-foreground); background: var(--vscode-input-background);
    border: 1px solid var(--vscode-input-border, transparent); padding: 4px; }
  .badge { font-size: 0.85em; padding: 0 4px; border-radius: 2px; background: var(--vscode-badge-background);
    color: var(--vscode-badge-foreground); }
  a { color: var(--vscode-textLink-foreground); cursor: pointer; }
  #select-btn { position: absolute; display: none; z-index: 20; }
  .empty { opacity: 0.7; padding: 4px; }
</style>
</head>
<body>
<div id="toolbar">
  <button id="zoom-out" title="Zoom out">&minus;</button>
  <button id="zoom-in" title="Zoom in">+</button>
  <button id="fit" title="Fit width">Fit</button>
  <span id="page"></span>
  <span class="spacer"></span>
  <span id="status"></span>
  <label title="Show resolved threads"><input type="checkbox" id="show-resolved"> Resolved</label>
  <button id="toggle-comments" aria-pressed="true" title="Show or hide comments">Comments</button>
</div>
<div id="main">
  <div id="wrap">
    <div id="viewerContainer"><div id="viewer" class="pdfViewer"></div></div>
    <button id="select-btn" class="primary">Comment</button>
  </div>
  <aside id="panel"></aside>
</div>
<script nonce="${nonce}" type="module">
const config = ${JSON.stringify(config)};
const LIGATURES = ${JSON.stringify(LIGATURES)};
${findText.toString()}
${normalizeSelection.toString()}
const vscode = acquireVsCodeApi();
const state = Object.assign({ showComments: true, showResolved: false, scale: "page-width" }, vscode.getState() || {});
const save = () => vscode.setState(state);
const pdfjsLib = await import(config.lib);
const { EventBus, PDFLinkService, PDFViewer } = await import(config.viewer);
// A worker from another origin is refused, so it's loaded from a blob
const workerCode = await (await fetch(config.worker)).text();
pdfjsLib.GlobalWorkerOptions.workerPort = new Worker(
  URL.createObjectURL(new Blob([workerCode], { type: "text/javascript" })),
  { type: "module" },
);
const container = document.getElementById("viewerContainer");
const panel = document.getElementById("panel");
const statusEl = document.getElementById("status");
const selectBtn = document.getElementById("select-btn");
const eventBus = new EventBus();
const linkService = new PDFLinkService({ eventBus });
const viewer = new PDFViewer({ container, eventBus, linkService, removePageBorders: false });
linkService.setViewer(viewer);
let pdfDoc = null;
let threads = [];
let selected = null;
let composer = null;
const textCache = new Map();
const pending = new Map();
let reqCounter = 0;

function setStatus(text) { statusEl.textContent = text || ""; statusEl.title = text || ""; }
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
function visible(t) { return state.showResolved || !t.resolved; }
function pageView(n) { return viewer.getPageView(n - 1); }
// SyncTeX measures from the top-left of the page in points; PDF.js from the
// bottom-left
function toViewport(n, x, y) {
  const vp = pageView(n).viewport;
  return vp.convertToViewportPoint(x, vp.viewBox[3] - y);
}
function fromViewport(n, vx, vy) {
  const vp = pageView(n).viewport;
  const [x, y] = vp.convertToPdfPoint(vx, vy);
  return { x, y: vp.viewBox[3] - y };
}
async function pageText(n) {
  if (!textCache.has(n)) {
    textCache.set(n, pdfDoc.getPage(n).then((p) => p.getTextContent()).then((tc) => {
      const view = pageView(n).viewport.viewBox;
      let span = 0;
      // The text layer has a span for each item with text, in order
      return tc.items.filter((it) => "str" in it).map((it) => ({
        str: it.str, x: it.transform[4], base: it.transform[5], width: it.width,
        height: it.height || Math.hypot(it.transform[2], it.transform[3]),
        top: view[3] - it.transform[5], span: it.str ? span++ : -1,
      }));
    }));
  }
  return textCache.get(n);
}
// Each occurrence of some text from the top of a line to either the bottom
// of one, or a place in the text, in reading order
async function occurrences(text, from, to) {
  const out = [];
  for (let n = from.page; n <= Math.min(to.page, pdfDoc.numPages); n++) {
    const items = await pageText(n);
    for (const r of findText(items, text)) {
      const y = items[r.start.item].top;
      if (n === from.page && y < from.y - 2) continue;
      if (n === to.page) {
        const { item, offset } = r.start;
        if (to.item === undefined ? y > to.y + 2 : item > to.item || (item === to.item && offset >= to.offset)) continue;
      }
      out.push({ page: n, range: r, items });
    }
  }
  return out;
}
// Where a page's content starts on screen, inside its border
function pageBox(div) {
  const r = div.getBoundingClientRect();
  return { left: r.left + div.clientLeft, top: r.top + div.clientTop };
}
function spans(n) {
  return pageView(n)?.div?.querySelectorAll(".textLayer span:not(.markedContent)") ?? [];
}
// Rectangles around a match, from the text layer where it's rendered, since
// that has the real glyph widths, otherwise estimated from the text items
function rangeRects(m) {
  const rects = [];
  const pv = pageView(m.page);
  const box = pageBox(pv.div);
  const domSpans = spans(m.page);
  for (let i = m.range.start.item; i <= m.range.end.item; i++) {
    const it = m.items[i];
    const len = Math.max(it.str.length, 1);
    const a = i === m.range.start.item ? m.range.start.offset : 0;
    const b = i === m.range.end.item ? m.range.end.offset : it.str.length;
    if (b <= a || !it.width) continue;
    const node = domSpans[it.span]?.firstChild;
    if (node?.nodeType === 3 && node.textContent === it.str) {
      const range = document.createRange();
      range.setStart(node, a);
      range.setEnd(node, b);
      for (const r of range.getClientRects()) {
        rects.push({ left: r.left - box.left, top: r.top - box.top, width: r.width, height: r.height });
      }
      continue;
    }
    const r = [
      ...pv.viewport.convertToViewportPoint(it.x + (it.width * a) / len, it.base - it.height * 0.25),
      ...pv.viewport.convertToViewportPoint(it.x + (it.width * b) / len, it.base + it.height * 0.85),
    ];
    rects.push({ left: Math.min(r[0], r[2]), top: Math.min(r[1], r[3]), width: Math.abs(r[2] - r[0]), height: Math.abs(r[3] - r[1]) });
  }
  return rects;
}
function layer(n) {
  const pv = pageView(n);
  if (!pv || !pv.div) return null;
  let el = pv.div.querySelector(".ck-layer");
  if (!el) {
    el = document.createElement("div");
    el.className = "ck-layer";
    pv.div.appendChild(el);
  }
  return el;
}
function addEl(parent, cls, box, t) {
  const el = document.createElement("div");
  el.className = cls + (t.resolved ? " resolved" : "") + (selected === t.key ? " selected" : "");
  Object.assign(el.style, { left: box.left + "px", top: box.top + "px" });
  if (box.width !== undefined) el.style.width = box.width + "px";
  if (box.height !== undefined) el.style.height = box.height + "px";
  el.addEventListener("click", (e) => { e.stopPropagation(); select(t.key, false); });
  parent.appendChild(el);
  return el;
}
let drawGen = 0;
async function draw() {
  if (!pdfDoc) return;
  const gen = ++drawGen;
  const drawn = new Map();
  for (let n = 1; n <= pdfDoc.numPages; n++) {
    const pv = pageView(n);
    pv?.div?.querySelector(".ck-layer")?.replaceChildren();
  }
  const pins = new Map();
  for (const t of threads) {
    if (!visible(t) || !t.start) continue;
    const startLayer = layer(t.start.page);
    if (!startLayer) continue;
    const end = t.end && t.end.page === t.start.page ? t.end : null;
    const view = pageView(t.start.page).viewport.viewBox;
    const [x0, y0] = toViewport(t.start.page, t.start.x + t.start.width + 4, t.start.y);
    const [, y1] = toViewport(t.start.page, 0, end ? end.y + end.height : view[3]);
    addEl(startLayer, "ck-bar", { left: x0, top: y0, height: Math.max(y1 - y0, 8) }, t);
    // Threads on the same paragraph fan out to the right
    const key = t.start.page + ":" + Math.round(t.start.y);
    const k = pins.get(key) ?? 0;
    pins.set(key, k + 1);
    const pin = addEl(startLayer, "ck-pin", { left: x0 + 6 + k * 22, top: y0 - 2 }, t);
    pin.textContent = String(t.messages.length);
    pin.title = t.messages[0]?.author + ": " + t.messages[0]?.text;
    if (t.highlight) {
      const last = t.end ?? t.start;
      const found = await occurrences(t.highlight.text, t.start, {
        page: last.page, y: last.y + last.height,
      });
      if (gen !== drawGen) return;
      const m = found[t.highlight.occ] ?? found[0];
      if (m) {
        const hlLayer = layer(m.page);
        for (const r of rangeRects(m)) addEl(hlLayer, "ck-hl", r, t);
      }
    }
  }
}
function renderPanel() {
  const shown = threads.filter(visible);
  const parts = [];
  if (composer) {
    parts.push('<div class="thread composer" data-key="__new"><div class="quote">' + esc(composer.text) + '</div>' +
      '<textarea id="new-text" placeholder="Add a comment"></textarea>' +
      '<div class="actions"><button class="primary" data-act="save-new">Comment</button><button data-act="cancel-new">Cancel</button></div></div>');
  }
  if (!shown.length && !composer) {
    const hidden = threads.length - shown.length;
    parts.push('<div class="empty">No ' + (hidden ? "open " : "") + "comments. Select text in the PDF to add one." +
      (hidden ? " " + hidden + " resolved hidden." : "") + "</div>");
  }
  for (const t of shown) {
    const msgs = t.messages.map((m) => '<div class="msg"><span class="who">' + esc(m.author) + '</span>' +
      (m.date ? '<span class="when">' + esc(m.date) + '</span>' : "") + '<div class="text">' + esc(m.text) + "</div></div>").join("");
    parts.push('<div class="thread' + (t.resolved ? " resolved" : "") + (selected === t.key ? " selected" : "") + '" data-key="' + esc(t.key) + '">' +
      '<div class="meta">' + (t.resolved ? '<span class="badge">Resolved</span>' : "") +
      (t.issue ? '<a data-act="issue" title="' + esc(t.issue) + '">Issue</a>' : "") +
      (t.start ? "" : '<span title="Not found in the PDF; is it built with SyncTeX?">Not placed</span>') + "</div>" +
      (t.highlight ? '<div class="quote">' + esc(t.highlight.text) + "</div>" : "") + msgs +
      '<div class="actions"><textarea placeholder="Reply"></textarea>' +
      '<button class="primary" data-act="reply">Reply</button>' +
      '<button data-act="resolve">' + (t.resolved ? "Reopen" : "Resolve") + "</button>" +
      '<button data-act="source">Source</button><button data-act="delete">Delete</button></div></div>');
  }
  panel.innerHTML = parts.join("");
  if (composer) panel.querySelector("#new-text")?.focus();
}
function select(key, scroll) {
  selected = key;
  renderPanel();
  void draw();
  const t = threads.find((x) => x.key === key);
  panel.querySelector('[data-key="' + CSS.escape(key) + '"]')?.scrollIntoView({ block: "nearest" });
  if (scroll && t?.start) reveal(t.start);
}
function reveal(rect) {
  const pv = pageView(rect.page);
  if (!pv) return;
  const [x0, y0] = toViewport(rect.page, rect.x, rect.y);
  const [x1, y1] = toViewport(rect.page, rect.x + rect.width, rect.y + rect.height);
  container.scrollTo({ top: pv.div.offsetTop + y0 - container.clientHeight / 3 });
  const el = document.createElement("div");
  el.className = "ck-flash";
  Object.assign(el.style, { left: Math.min(x0, x1) + "px", top: Math.min(y0, y1) + "px",
    width: Math.max(Math.abs(x1 - x0), 20) + "px", height: Math.max(Math.abs(y1 - y0), 10) + "px" });
  pv.div.appendChild(el);
  setTimeout(() => el.remove(), 1700);
}
panel.addEventListener("click", (e) => {
  const card = e.target.closest(".thread");
  if (!card) return;
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (card.dataset.key === "__new") {
    if (act === "cancel-new") { composer = null; renderPanel(); }
    if (act === "save-new") {
      const text = panel.querySelector("#new-text").value.trim();
      if (!text || !composer.file) return;
      vscode.postMessage({ type: "add", file: composer.file, line: composer.line, text, highlight: composer.text, occ: composer.occ });
      composer = null;
      setStatus("Saving comment\\u2026");
      renderPanel();
    }
    return;
  }
  const t = threads.find((x) => x.key === card.dataset.key);
  if (!t) return;
  const target = { file: t.path, id: t.id ?? undefined, line: t.id ? undefined : t.line };
  if (!act) { if (selected !== t.key) select(t.key, true); return; }
  if (act === "reply") {
    const text = card.querySelector("textarea").value.trim();
    if (text) vscode.postMessage({ type: "reply", ...target, text });
  } else if (act === "resolve") {
    vscode.postMessage({ type: "resolve", ...target, resolved: !t.resolved });
  } else if (act === "delete") {
    vscode.postMessage({ type: "delete", ...target });
  } else if (act === "source") {
    vscode.postMessage({ type: "openSource", file: t.path, line: t.line });
  } else if (act === "issue") {
    vscode.postMessage({ type: "openIssue", url: t.issue });
  }
});
panel.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
    e.target.closest(".thread")?.querySelector("button.primary")?.click();
  }
});
// Selecting text offers to comment on it
container.addEventListener("mouseup", () => {
  setTimeout(() => {
    const sel = document.getSelection();
    const text = sel && !sel.isCollapsed ? normalizeSelection(sel.toString()) : "";
    if (!text || !sel.anchorNode || !container.contains(sel.anchorNode)) { selectBtn.style.display = "none"; return; }
    const rects = sel.getRangeAt(0).getClientRects();
    const lastRect = rects[rects.length - 1];
    const wrapRect = document.getElementById("wrap").getBoundingClientRect();
    selectBtn.style.left = (lastRect.right - wrapRect.left + 4) + "px";
    selectBtn.style.top = (lastRect.bottom - wrapRect.top + 4) + "px";
    selectBtn.style.display = "block";
  }, 0);
});
container.addEventListener("scroll", () => { selectBtn.style.display = "none"; });
selectBtn.addEventListener("mousedown", (e) => e.preventDefault());
selectBtn.addEventListener("click", async () => {
  selectBtn.style.display = "none";
  const sel = document.getSelection();
  if (!sel || sel.isCollapsed) return;
  const text = normalizeSelection(sel.toString());
  const range = sel.getRangeAt(0);
  const first = range.getClientRects()[0];
  const startNode = range.startContainer;
  const startEl = startNode.nodeType === 3 ? startNode.parentElement : startNode;
  const pageDiv = startEl.closest(".page");
  if (!first || !pageDiv) return;
  const n = Number(pageDiv.dataset.pageNumber);
  // Where the selection starts in the page's text items
  const domIndex = [...spans(n)].indexOf(startEl);
  const selItem = (await pageText(n)).findIndex((it) => it.span === domIndex && domIndex >= 0);
  const selOffset = startNode.nodeType === 3 ? range.startOffset : 0;
  const box = pageBox(pageDiv);
  const at = fromViewport(n, first.left - box.left + 1, first.top - box.top + first.height / 2);
  const reqId = ++reqCounter;
  const located = new Promise((resolve) => pending.set(reqId, resolve));
  vscode.postMessage({ type: "locate", reqId, page: n, x: at.x, y: at.y });
  composer = { text, occ: 0 };
  state.showComments = true;
  applyState();
  renderPanel();
  const loc = await located;
  if (!composer || composer.text !== text) return;
  if (!loc.file) {
    setStatus("Can't find the source of that text. Is the PDF built with SyncTeX?");
    composer = null;
    renderPanel();
    return;
  }
  composer.file = loc.file;
  composer.line = loc.line;
  // The highlight is the nth occurrence of its text in the paragraph
  if (loc.start) {
    const to = selItem >= 0 ? { page: n, item: selItem, offset: selOffset } : { page: n, y: at.y - 6 };
    const found = await occurrences(text, loc.start, to);
    composer.occ = found.length;
  }
});
// Ctrl or Cmd-click goes to the source
container.addEventListener("click", (e) => {
  if (!(e.ctrlKey || e.metaKey)) return;
  const pageDiv = e.target.closest(".page");
  if (!pageDiv) return;
  const n = Number(pageDiv.dataset.pageNumber);
  const box = pageBox(pageDiv);
  const at = fromViewport(n, e.clientX - box.left, e.clientY - box.top);
  vscode.postMessage({ type: "sourceAt", page: n, x: at.x, y: at.y });
});
function applyState() {
  document.body.classList.toggle("no-comments", !state.showComments);
  document.getElementById("toggle-comments").setAttribute("aria-pressed", String(state.showComments));
  document.getElementById("show-resolved").checked = state.showResolved;
  save();
}
document.getElementById("toggle-comments").addEventListener("click", () => {
  state.showComments = !state.showComments;
  applyState();
});
document.getElementById("show-resolved").addEventListener("change", (e) => {
  state.showResolved = e.target.checked;
  applyState();
  renderPanel();
  void draw();
});
const setScale = (v) => { viewer.currentScaleValue = v; state.scale = String(v); save(); };
document.getElementById("zoom-in").addEventListener("click", () => setScale(Math.min(viewer.currentScale * 1.1, 5)));
document.getElementById("zoom-out").addEventListener("click", () => setScale(Math.max(viewer.currentScale / 1.1, 0.25)));
document.getElementById("fit").addEventListener("click", () => setScale("page-width"));
eventBus.on("pagesinit", () => {
  viewer.currentScaleValue = state.scale;
  if (state.scrollTop) container.scrollTop = state.scrollTop;
});
eventBus.on("pagechanging", (e) => {
  document.getElementById("page").textContent = e.pageNumber + " / " + (pdfDoc?.numPages ?? "");
});
container.addEventListener("scroll", () => { state.scrollTop = container.scrollTop; save(); });
eventBus.on("textlayerrendered", () => void draw());
new ResizeObserver(() => { if (pdfDoc && state.scale === "page-width") viewer.currentScaleValue = "page-width"; }).observe(container);
async function load(url) {
  try {
    const doc = await pdfjsLib.getDocument({
      url, cMapUrl: config.cMapUrl, cMapPacked: true, standardFontDataUrl: config.standardFontDataUrl,
      wasmUrl: config.wasmUrl, iccUrl: config.iccUrl, useWorkerFetch: false, isEvalSupported: false,
    }).promise;
    const old = pdfDoc;
    pdfDoc = doc;
    textCache.clear();
    viewer.setDocument(doc);
    linkService.setDocument(doc);
    document.getElementById("page").textContent = "1 / " + doc.numPages;
    old?.destroy();
  } catch (err) {
    setStatus("Couldn't open the PDF: " + (err?.message ?? err));
  }
}
window.addEventListener("message", (e) => {
  const msg = e.data;
  if (msg.type === "load") void load(msg.url);
  else if (msg.type === "threads") {
    threads = msg.threads;
    const open = threads.filter((t) => !t.resolved).length;
    setStatus(!msg.synctex ? "No SyncTeX file, so comments can't be placed in the PDF"
      : msg.stale.length ? msg.stale.join(", ") + " changed since this PDF was built; rebuild it to place comments exactly"
      : open + " open of " + threads.length);
    renderPanel();
    void draw();
  } else if (msg.type === "status") setStatus(msg.text);
  else if (msg.type === "reveal") reveal(msg.rect);
  else if (msg.type === "located") pending.get(msg.reqId)?.(msg);
});
applyState();
vscode.postMessage({ type: "ready" });
</script>
</body>
</html>`;
}

function escapeHtml(s: string): string {
  return s.replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ] ?? c,
  );
}
