import * as path from "node:path";
import * as vscode from "vscode";
import {
  extractLatexImageRefs,
  extractMarkdownImageRefs,
  resolveFigureRefStage,
  resolveImageRefToRepoRelative,
} from "./core";
import type { FigureEntry } from "../types";

// Open the figures gallery/carousel webview. The caller supplies the figure
// entries (for provenance metadata) and a nonce so this module stays free of
// extension-global state.
export function openFiguresCarousel(
  context: vscode.ExtensionContext,
  workspaceRoot: string,
  figurePaths: string[],
  startIndex: number,
  openCarousel: boolean,
  figList: FigureEntry[],
  nonce: string,
  outputToStage: Map<string, string>,
  onShowStage: (stageName: string) => void,
): vscode.WebviewPanel {
  const panel = vscode.window.createWebviewPanel(
    "calkit.figuresCarousel",
    "Figures",
    vscode.ViewColumn.Active,
    {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.file(workspaceRoot)],
    },
  );
  context.subscriptions.push(panel);
  // Build per-figure data: webview URI + provenance metadata
  const figures: FigureData[] = figurePaths.map((p) => {
    const absUri = vscode.Uri.file(path.join(workspaceRoot, p));
    const webviewUri = panel.webview.asWebviewUri(absUri);
    const entry = figList.find((f) => f.path === p);
    const importedFrom = entry?.imported_from
      ? typeof entry.imported_from === "object" &&
        "url" in (entry.imported_from as object)
        ? (entry.imported_from as { url: string }).url
        : JSON.stringify(entry.imported_from)
      : undefined;
    return {
      path: p,
      uriStr: webviewUri.toString(),
      ext: path.extname(p).toLowerCase(),
      // Prefer an explicitly-declared stage, otherwise auto-detect the stage
      // that produces this path from the pipeline output map.
      stage:
        typeof entry?.stage === "string" ? entry.stage : outputToStage.get(p),
      importedFrom,
      title: typeof entry?.title === "string" ? entry.title : undefined,
      description:
        typeof entry?.description === "string" ? entry.description : undefined,
    };
  });
  panel.webview.html = buildCarouselHtml(
    nonce,
    figures,
    startIndex,
    panel.webview.cspSource,
    openCarousel,
  );
  // The webview posts { type: "showStage", stage } when the stage name (in the
  // metadata footer) or the toolbar source button is clicked.
  panel.webview.onDidReceiveMessage(
    (msg: { type?: string; stage?: string }) => {
      if (msg?.type === "showStage" && typeof msg.stage === "string") {
        onShowStage(msg.stage);
      }
    },
    undefined,
    context.subscriptions,
  );
  return panel;
}

type FigureData = {
  path: string;
  uriStr: string;
  ext: string;
  stage: string | undefined;
  importedFrom: string | undefined;
  title: string | undefined;
  description: string | undefined;
};

function buildCarouselHtml(
  nonce: string,
  figures: FigureData[],
  startIndex: number,
  cspSource: string,
  openCarousel: boolean,
): string {
  const RENDERABLE = new Set([
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".pdf",
    ".html",
    ".htm",
    ".json",
  ]);
  const figuresJson = JSON.stringify(figures);
  // Plotly figures are stored as JSON; only pull in the (large) Plotly library
  // when at least one figure needs it.
  const hasPlotly = figures.some((f) => f.ext === ".json");
  const plotlyScript = hasPlotly
    ? `<script nonce="${nonce}" src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2/plotly.min.js"></script>`
    : "";
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${
    figures.length > 0 ? cspSource : "'none'"
  } data:; frame-src ${cspSource}; object-src ${cspSource}; script-src 'nonce-${nonce}'${
    hasPlotly ? " https://cdn.jsdelivr.net" : ""
  }; style-src 'unsafe-inline'; connect-src ${cspSource};">
<title>Figures</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; overflow: hidden; font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground); background: var(--vscode-editor-background); }
  .hidden { display: none !important; }
  /* Gallery grid */
  #gallery-view { display: flex; flex-direction: column; height: 100vh; }
  #gallery-header { display: flex; align-items: baseline; gap: 10px; padding: 12px 16px; border-bottom: 1px solid var(--vscode-panel-border, #444); flex-shrink: 0; }
  #gallery-title { font-size: 1.1em; font-weight: 600; }
  #gallery-count { color: var(--vscode-descriptionForeground); font-size: 0.85em; }
  #gallery { flex: 1; overflow: auto; padding: 16px; display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 14px; align-content: start; }
  #gallery-empty { color: var(--vscode-descriptionForeground); padding: 24px; font-style: italic; }
  .thumb { display: flex; flex-direction: column; border: 1px solid var(--vscode-panel-border, #444); border-radius: 6px; overflow: hidden; cursor: pointer; background: var(--vscode-editorWidget-background, rgba(128,128,128,0.06)); }
  .thumb:hover { border-color: var(--vscode-focusBorder, #007fd4); }
  .thumb-media { height: 120px; display: flex; align-items: center; justify-content: center; overflow: hidden; background: var(--vscode-editor-background); }
  .thumb-media img { width: 100%; height: 100%; object-fit: contain; }
  .thumb-placeholder { color: var(--vscode-descriptionForeground); font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.05em; }
  .thumb-caption { padding: 6px 8px; font-size: 0.78em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-top: 1px solid var(--vscode-panel-border, #444); }
  /* Carousel modal */
  #modal { position: fixed; inset: 0; z-index: 10; background: var(--vscode-editor-background); }
  #root { display: flex; flex-direction: column; height: 100vh; }
  #toolbar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--vscode-panel-border, #444); flex-shrink: 0; }
  #counter { color: var(--vscode-descriptionForeground); font-size: 0.85em; white-space: nowrap; }
  #path-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.9em; opacity: 0.8; }
  #viewer { flex: 1; position: relative; display: flex; align-items: center; justify-content: center; overflow: hidden; }
  #fig-content { max-width: 100%; max-height: 100%; display: flex; align-items: center; justify-content: center; }
  #fig-content img { max-width: 100%; max-height: calc(100vh - 140px); object-fit: contain; display: block; }
  #fig-content embed, #fig-content iframe { width: 100%; height: calc(100vh - 140px); border: none; background: white; }
  .no-render { color: var(--vscode-descriptionForeground); font-size: 0.9em; padding: 20px; text-align: center; }
  .nav-btn { background: var(--vscode-button-secondaryBackground, rgba(128,128,128,0.2)); color: var(--vscode-button-secondaryForeground, inherit); border: none; border-radius: 4px; padding: 6px 14px; cursor: pointer; font-size: 1.1em; flex-shrink: 0; }
  .nav-btn:hover:not(:disabled) { background: var(--vscode-button-secondaryHoverBackground, rgba(128,128,128,0.35)); }
  .nav-btn:disabled { opacity: 0.35; cursor: default; }
  #btn-back { font-size: 0.85em; }
  .icon-btn { padding: 5px 8px; display: inline-flex; align-items: center; justify-content: center; }
  #metadata { flex-shrink: 0; padding: 8px 12px; border-top: 1px solid var(--vscode-panel-border, #444); font-size: 0.82em; display: flex; gap: 16px; flex-wrap: wrap; }
  .meta-item { display: flex; gap: 4px; }
  .meta-label { color: var(--vscode-descriptionForeground); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.85em; }
  .meta-value { color: var(--vscode-foreground); opacity: 0.85; }
  .meta-link { cursor: pointer; color: var(--vscode-textLink-foreground); text-decoration: underline; opacity: 1; }
  .meta-link:hover { color: var(--vscode-textLink-activeForeground); }
  #dots { display: flex; gap: 5px; align-items: center; overflow-x: auto; max-width: 300px; }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--vscode-descriptionForeground); opacity: 0.35; cursor: pointer; flex-shrink: 0; }
  .dot.active { opacity: 1; background: var(--vscode-focusBorder, #007fd4); }
</style>
</head>
<body>
<div id="gallery-view">
  <div id="gallery-header">
    <span id="gallery-title">Figures</span>
    <span id="gallery-count"></span>
  </div>
  <div id="gallery"></div>
</div>
<div id="modal" class="hidden">
  <div id="root">
    <div id="toolbar">
      <button class="nav-btn" id="btn-back" title="Back to gallery">&#8592; Gallery</button>
      <button class="nav-btn" id="btn-prev">&#8592;</button>
      <div id="dots"></div>
      <button class="nav-btn" id="btn-next">&#8594;</button>
      <span id="counter"></span>
      <span id="path-label"></span>
      <button class="nav-btn icon-btn hidden" id="btn-source" title="View producing stage"><svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M2 3.5C2 3.22386 2.22386 3 2.5 3H13.5C13.7761 3 14 3.22386 14 3.5C14 3.77614 13.7761 4 13.5 4H6V6H13.5C13.7761 6 14 6.22386 14 6.5C14 6.77614 13.7761 7 13.5 7H6V9H13.5C13.7761 9 14 9.22386 14 9.5C14 9.77614 13.7761 10 13.5 10H6V12H13.5C13.7761 12 14 12.2239 14 12.5C14 12.7761 13.7761 13 13.5 13H5.5C5.22386 13 5 12.7761 5 12.5V4H2.5C2.22386 4 2 3.77614 2 3.5Z"/></svg></button>
    </div>
    <div id="viewer">
      <div id="fig-content"></div>
    </div>
    <div id="metadata"></div>
  </div>
</div>
${plotlyScript}
<script nonce="${nonce}">
  const RENDERABLE = ${JSON.stringify([...RENDERABLE])};
  const figures = ${figuresJson};
  let idx = ${Math.max(0, Math.min(startIndex, figures.length - 1))};

  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');
  const btnBack = document.getElementById('btn-back');
  const counter = document.getElementById('counter');
  const pathLabel = document.getElementById('path-label');
  const figContent = document.getElementById('fig-content');
  const metadata = document.getElementById('metadata');
  const dotsEl = document.getElementById('dots');
  const modal = document.getElementById('modal');
  const galleryEl = document.getElementById('gallery');
  const galleryCount = document.getElementById('gallery-count');
  const btnSource = document.getElementById('btn-source');

  const vscodeApi = acquireVsCodeApi();
  // Ask the extension to reveal the producing stage in the Calkit sidebar.
  function showStage(stage) {
    if (stage) vscodeApi.postMessage({ type: 'showStage', stage: stage });
  }
  btnSource.addEventListener('click', function() { showStage(figures[idx].stage); });

  const IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.gif', '.svg'];

  // Build the gallery grid of thumbnails
  galleryCount.textContent =
    figures.length + (figures.length === 1 ? ' figure' : ' figures');
  if (figures.length === 0) {
    const empty = document.createElement('div');
    empty.id = 'gallery-empty';
    empty.textContent = 'No figures found.';
    galleryEl.appendChild(empty);
  }
  figures.forEach(function(fig, i) {
    const thumb = document.createElement('div');
    thumb.className = 'thumb';
    thumb.title = fig.path;
    const media = document.createElement('div');
    media.className = 'thumb-media';
    if (IMAGE_EXTS.indexOf(fig.ext) !== -1) {
      const img = document.createElement('img');
      img.src = fig.uriStr;
      img.alt = fig.path;
      media.appendChild(img);
    } else {
      const ph = document.createElement('div');
      ph.className = 'thumb-placeholder';
      ph.textContent = fig.ext === '.json' ? 'plotly' : (fig.ext.replace('.', '') || 'file');
      media.appendChild(ph);
    }
    const caption = document.createElement('div');
    caption.className = 'thumb-caption';
    caption.textContent = fig.title || fig.path.split('/').pop();
    thumb.appendChild(media);
    thumb.appendChild(caption);
    thumb.addEventListener('click', function() { openModal(i); });
    galleryEl.appendChild(thumb);
  });

  // Build dots
  figures.forEach(function(_, i) {
    const dot = document.createElement('div');
    dot.className = 'dot';
    dot.addEventListener('click', function() { navigate(i); });
    dotsEl.appendChild(dot);
  });

  function openModal(newIdx) {
    idx = newIdx;
    modal.classList.remove('hidden');
    render();
  }

  function closeModal() {
    modal.classList.add('hidden');
  }

  function modalOpen() {
    return !modal.classList.contains('hidden');
  }

  function navigate(newIdx) {
    idx = newIdx;
    render();
  }

  function render() {
    const fig = figures[idx];
    // Update toolbar
    counter.textContent = (idx + 1) + ' / ' + figures.length;
    pathLabel.textContent = fig.path;
    pathLabel.title = fig.path;
    btnPrev.disabled = idx === 0;
    btnNext.disabled = idx === figures.length - 1;
    // Toolbar "Show Source" button: only for figures with a producing stage
    if (fig.stage) {
      btnSource.classList.remove('hidden');
      btnSource.title = 'View stage: ' + fig.stage;
    } else {
      btnSource.classList.add('hidden');
    }
    // Update dots
    Array.from(dotsEl.querySelectorAll('.dot')).forEach(function(d, i) {
      d.classList.toggle('active', i === idx);
    });
    // Render figure
    figContent.innerHTML = '';
    const ext = fig.ext;
    if (ext === '.png' || ext === '.jpg' || ext === '.jpeg' || ext === '.gif' || ext === '.svg') {
      const img = document.createElement('img');
      img.src = fig.uriStr;
      img.alt = fig.path;
      figContent.appendChild(img);
    } else if (ext === '.pdf') {
      const embed = document.createElement('embed');
      embed.src = fig.uriStr;
      embed.type = 'application/pdf';
      embed.style.width = '100%';
      embed.style.height = 'calc(100vh - 140px)';
      figContent.appendChild(embed);
    } else if (ext === '.html' || ext === '.htm') {
      const frame = document.createElement('iframe');
      frame.src = fig.uriStr;
      frame.style.width = '100%';
      frame.style.height = 'calc(100vh - 140px)';
      frame.style.border = 'none';
      figContent.appendChild(frame);
    } else if (ext === '.json') {
      // Plotly figure: fetch the JSON spec and render it interactively.
      const plotDiv = document.createElement('div');
      plotDiv.style.width = '100%';
      figContent.appendChild(plotDiv);
      const target = fig.uriStr;
      fetch(target)
        .then(function(r) { return r.json(); })
        .then(function(spec) {
          if (figures[idx].uriStr !== target) return; // navigated away
          if (typeof Plotly === 'undefined') {
            throw new Error('Plotly failed to load.');
          }
          const layout = Object.assign({}, spec.layout || {});
          // Keep the figure's own height (or Plotly's ~450px default), but
          // shrink it to fit the viewport if it would otherwise overflow.
          const avail = window.innerHeight - 140;
          const desired = layout.height || 450;
          if (desired > avail) {
            layout.height = avail;
          }
          Plotly.newPlot(plotDiv, spec.data || [], layout, {responsive: true});
        })
        .catch(function(err) {
          plotDiv.className = 'no-render';
          plotDiv.textContent = 'Could not render Plotly figure: ' + err.message;
        });
    } else {
      const msg = document.createElement('div');
      msg.className = 'no-render';
      msg.textContent = 'Preview not available for ' + ext + ' files.';
      figContent.appendChild(msg);
    }
    // Update metadata
    metadata.innerHTML = '';
    function metaItem(label, value, clickable) {
      if (!value) return;
      const div = document.createElement('div');
      div.className = 'meta-item';
      const lbl = document.createElement('span');
      lbl.className = 'meta-label';
      lbl.textContent = label + ':';
      const val = document.createElement('span');
      val.className = clickable ? 'meta-value meta-link' : 'meta-value';
      val.textContent = value;
      if (clickable) {
        val.setAttribute('role', 'button');
        val.title = 'View stage in Calkit sidebar';
        val.addEventListener('click', function() { showStage(value); });
      }
      div.appendChild(lbl);
      div.appendChild(val);
      metadata.appendChild(div);
    }
    metaItem('Title', fig.title);
    // The stage name is clickable: reveal the producing stage in the sidebar.
    metaItem('Stage', fig.stage, true);
    metaItem('Imported from', fig.importedFrom);
    metaItem('Description', fig.description);
  }

  btnPrev.addEventListener('click', function() { if (idx > 0) navigate(idx - 1); });
  btnNext.addEventListener('click', function() { if (idx < figures.length - 1) navigate(idx + 1); });
  btnBack.addEventListener('click', closeModal);

  document.addEventListener('keydown', function(e) {
    if (!modalOpen()) return;
    if (e.key === 'Escape') closeModal();
    if (e.key === 'ArrowLeft' && idx > 0) navigate(idx - 1);
    if (e.key === 'ArrowRight' && idx < figures.length - 1) navigate(idx + 1);
  });

  // Open straight into the carousel when launched from a specific figure;
  // otherwise show the gallery grid.
  if (${openCarousel ? "true" : "false"} && figures.length > 0) {
    openModal(idx);
  }
</script>
</body>
</html>`;
}

// Dependencies the CodeLens provider needs from the extension host, injected so
// this module stays decoupled from extension-global state.
export interface FigureSourceCodeLensDeps {
  getWorkspaceRoot: () => string | undefined;
  buildOutputToStageMap: (
    workspaceRoot: string,
  ) => Promise<Map<string, string>>;
  goToFigureSourceCommand: string;
}

// Shows a "Source: <stage>" CodeLens above each figure reference in a Quarto/
// Markdown document whose target is produced by a pipeline stage, linking to
// the producing stage's source via the goToFigureSource command.
export class FigureSourceCodeLensProvider implements vscode.CodeLensProvider {
  private readonly _onDidChangeCodeLenses = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this._onDidChangeCodeLenses.event;

  constructor(private readonly deps: FigureSourceCodeLensDeps) {}

  refresh(): void {
    this._onDidChangeCodeLenses.fire();
  }

  async provideCodeLenses(
    document: vscode.TextDocument,
  ): Promise<vscode.CodeLens[]> {
    const workspaceRoot = this.deps.getWorkspaceRoot();
    if (!workspaceRoot) {
      return [];
    }
    // LaTeX docs use \includegraphics; Markdown/Quarto use ![](...).
    const isLatex =
      document.languageId === "latex" ||
      document.uri.fsPath.toLowerCase().endsWith(".tex");
    const text = document.getText();
    const refs = isLatex
      ? extractLatexImageRefs(text)
      : extractMarkdownImageRefs(text);
    if (refs.length === 0) {
      return [];
    }
    const outputToStage = await this.deps.buildOutputToStageMap(workspaceRoot);
    const lenses: vscode.CodeLens[] = [];
    for (const ref of refs) {
      const relPath = resolveImageRefToRepoRelative(
        document.uri.fsPath,
        ref.target,
        workspaceRoot,
      );
      if (!relPath) {
        continue;
      }
      const stageName = resolveFigureRefStage(relPath, outputToStage);
      if (!stageName) {
        continue;
      }
      lenses.push(
        new vscode.CodeLens(new vscode.Range(ref.line, 0, ref.line, 0), {
          title: `$(go-to-file) Source: ${stageName}`,
          command: this.deps.goToFigureSourceCommand,
          arguments: [relPath],
        }),
      );
    }
    return lenses;
  }
}
