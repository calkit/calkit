/**
 * A PDF viewer that shows the review comments in a LaTeX document's
 * source, following the Calkit comment schema, with ways to add, reply
 * to, resolve, and delete them, modeled on the VS Code extension's.
 *
 * The page it's shown on, e.g., Overleaf's editor, does everything with
 * the source: it sends the PDF and the threads with where they are in it,
 * and makes the edits this asks for. A PDF built on this machine is read
 * from it here instead, since this page can reach it.
 */
import "pdfjs-dist/legacy/web/pdf_viewer.css";
import "./review.css";
import * as pdfjsLib from "pdfjs-dist/legacy/build/pdf.mjs";
import workerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";
import {
  findText,
  normalizeSelection,
  type PdfTextItem,
  type Synctex,
  synctexReverse,
  type TextRange,
} from "../../../../vscode-ext/src/latex/pdf";
import { getLocalPdf, getLocalSynctex } from "../../core/local";
import { type PdfBox, placePdfBoxes } from "../../core/pdf-boxes";
import type {
  FromReview,
  PdfRect,
  ReviewThread,
  ToReview,
} from "../../core/review";

type Thread = ReviewThread & { unplaced?: boolean };
type Without<T> = T extends unknown ? Omit<T, "calkit"> : never;

interface PageItem extends PdfTextItem {
  x: number;
  base: number;
  width: number;
  height: number;
  top: number;
  /** Its span in the text layer, or -1 for an empty item, which has none. */
  span: number;
}

interface Place {
  page: number;
  y: number;
  item?: number;
  offset?: number;
}

interface Occurrence {
  page: number;
  range: TextRange;
  items: PageItem[];
}

interface Box {
  left: number;
  top: number;
  width?: number;
  height?: number;
}

const params = new URLSearchParams(window.location.search);
// Only the pages it's shown on may talk to it
const parentOrigin = params.get("parent") ?? "";
if (!/^https:\/\/(www\.)?overleaf\.com$/.test(parentOrigin)) {
  throw new Error(`Not shown on a page it works with: ${parentOrigin}`);
}
const viewKey = `calkit.review.view:${params.get("key") ?? ""}`;
// Matches the page's colors, so it looks like Overleaf's own PDF pane
for (const [param, name] of [
  ["bar", "--bar-bg"],
  ["barText", "--bar-fg"],
  ["backdrop", "--backdrop"],
  ["bg", "--bg"],
  ["fg", "--fg"],
  ["muted", "--muted"],
  ["border", "--border"],
  ["raised", "--raised"],
  ["raisedHover", "--raised-hover"],
]) {
  const color = params.get(param);
  if (color && CSS.supports("color", color)) {
    document.documentElement.style.setProperty(name, color);
  }
}
const PREFS_KEY = "calkit.review.prefs";

function readStored(key: string): Record<string, unknown> {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "{}");
  } catch {
    return {};
  }
}

const state = {
  showComments: true,
  showPanel: true,
  panelWidth: 260,
  showResolved: false,
  scale: "page-width",
  scrollTop: 0,
  ...readStored(PREFS_KEY),
  ...readStored(viewKey),
};
let saveTimer: ReturnType<typeof setTimeout> | undefined;
function save(): void {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      const { scale, scrollTop, ...prefs } = state;
      localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
      localStorage.setItem(viewKey, JSON.stringify({ scale, scrollTop }));
    } catch {
      // Only a convenience
    }
  }, 300);
}

function post(message: Without<FromReview>): void {
  window.parent.postMessage({ calkit: "review", ...message }, parentOrigin);
}

// The viewer reads the library from the global, so it's set first
(globalThis as { pdfjsLib?: unknown }).pdfjsLib = pdfjsLib;
pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;
const { EventBus, PDFFindController, PDFLinkService, PDFViewer } = await import(
  "pdfjs-dist/legacy/web/pdf_viewer.mjs"
);

function byId<T extends HTMLElement = HTMLElement>(id: string): T {
  return document.getElementById(id) as T;
}

const container = byId<HTMLDivElement>("viewerContainer");
const panel = byId("panel");
const statusEl = byId("status");
const selectBtn = byId("select-actions");
const eventBus = new EventBus();
const linkService = new PDFLinkService({ eventBus });
const findController = new PDFFindController({ linkService, eventBus });
const viewer = new PDFViewer({
  container,
  eventBus,
  linkService,
  findController,
  removePageBorders: true,
});
linkService.setViewer(viewer);
let pdfDoc: pdfjsLib.PDFDocumentProxy | null = null;
let threads: Thread[] = [];
let selected: string | null = null;
let composer: {
  text: string;
  occ: number;
  file?: string;
  line?: number;
  // What's typed, kept across redraws
  draft?: string;
  // The request saving it, which holds it on screen until it's in the list
  saving?: number;
} | null = null;
// A thread waiting on a click to confirm its deletion
let deleting: string | null = null;
// Replies and posts to Overleaf on their way, by request, which hold their
// thread's buttons until they're done
const sending = new Map<number, { key: string; act: "reply" | "overleaf" }>();
const textCache = new Map<number, Promise<PageItem[]>>();
const pending = new Map<
  number,
  (msg: ToReview & { type: "located" }) => void
>();
let reqCounter = 0;

function setStatus(text: string): void {
  statusEl.textContent = text;
  statusEl.title = text;
}

function esc(s: unknown): string {
  return String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ] ?? c,
  );
}

function isShown(t: Thread): boolean {
  return state.showResolved || !t.resolved;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function getPageView(n: number): any {
  return viewer.getPageView(n - 1);
}

// SyncTeX measures from the top-left of the page in points; PDF.js from the
// bottom-left
function toViewport(n: number, x: number, y: number): number[] {
  const vp = getPageView(n).viewport;
  return vp.convertToViewportPoint(x, vp.viewBox[3] - y);
}

function fromViewport(
  n: number,
  vx: number,
  vy: number,
): { x: number; y: number } {
  const vp = getPageView(n).viewport;
  const [x, y] = vp.convertToPdfPoint(vx, vy);
  return { x, y: vp.viewBox[3] - y };
}

function getPageText(n: number): Promise<PageItem[]> {
  let cached = textCache.get(n);
  if (!cached && pdfDoc) {
    cached = pdfDoc
      .getPage(n)
      .then((p) => p.getTextContent())
      .then((tc) => {
        const view = getPageView(n).viewport.viewBox;
        let span = 0;
        // The text layer has a span for each item with text, in order
        return tc.items
          .filter((it) => "str" in it)
          .map((it) => {
            const { str, transform, width, height } = it as {
              str: string;
              transform: number[];
              width: number;
              height: number;
            };
            return {
              str,
              x: transform[4],
              base: transform[5],
              width,
              height: height || Math.hypot(transform[2], transform[3]),
              top: view[3] - transform[5],
              span: str ? span++ : -1,
            };
          });
      });
    textCache.set(n, cached);
  }
  return cached ?? Promise.resolve([]);
}

// Each occurrence of some text from the top of a line to either the bottom
// of one, or a place in the text, in reading order
async function getOccurrences(
  text: string,
  from: Place,
  to: Place,
): Promise<Occurrence[]> {
  const out: Occurrence[] = [];
  if (!pdfDoc) {
    return out;
  }
  for (let n = from.page; n <= Math.min(to.page, pdfDoc.numPages); n++) {
    const items = await getPageText(n);
    for (const r of findText(items, text)) {
      const y = items[r.start.item].top;
      if (n === from.page && y < from.y - 2) {
        continue;
      }
      if (n === to.page) {
        const { item, offset } = r.start;
        if (
          to.item === undefined
            ? y > to.y + 2
            : item > to.item || (item === to.item && offset >= (to.offset ?? 0))
        ) {
          continue;
        }
      }
      out.push({ page: n, range: r, items });
    }
  }
  return out;
}

// Where a page's content starts on screen, inside its border
function getPageBox(div: HTMLElement): { left: number; top: number } {
  const r = div.getBoundingClientRect();
  return { left: r.left + div.clientLeft, top: r.top + div.clientTop };
}

// The text of the line nearest each of two heights on a page, and those
// between, as context for finding its paragraph in the source
async function getLineText(n: number, y0: number, y1 = y0): Promise<string> {
  const items = (await getPageText(n)).filter((it) => it.str.trim());
  const near = (y: number) =>
    items.reduce<PageItem | null>(
      (a, it) =>
        !a || Math.abs(it.top - y - 3) < Math.abs(a.top - y - 3) ? it : a,
      null,
    );
  const a = near(y0);
  const b = near(y1);
  if (!a || !b) {
    return "";
  }
  return items
    .filter((it) => it.top >= a.top - 1 && it.top <= b.top + 1)
    .map((it) => it.str)
    .join(" ");
}

// Where a paragraph is in the PDF from its text alone, for when there's no
// SyncTeX: runs of its words, from its start and end, that are found
const placeCache = new Map<
  string,
  Promise<{ start: PdfRect; end: PdfRect } | null>
>();
function findParagraph(
  text: string,
): Promise<{ start: PdfRect; end: PdfRect } | null> {
  let cached = placeCache.get(text);
  if (!cached) {
    cached = placeParagraph(text);
    placeCache.set(text, cached);
  }
  return cached;
}

async function placeParagraph(
  text: string,
): Promise<{ start: PdfRect; end: PdfRect } | null> {
  const words = text.split(/\s+/).filter(Boolean);
  if (!words.length || !pdfDoc) {
    return null;
  }
  // Runs of fewer words for a short paragraph, e.g., an equation
  const sizes = [8, 5].filter((s) => s <= words.length);
  if (!sizes.length) {
    sizes.push(words.length);
  }
  const pages: PageItem[][] = [];
  for (let n = 1; n <= pdfDoc.numPages; n++) {
    pages.push(await getPageText(n));
  }
  type Hit = { page: number; items: PageItem[]; r: TextRange };
  const hitsOf = (needle: string) => {
    const hits: Hit[] = [];
    pages.forEach((items, i) =>
      findText(items, needle).forEach((r) =>
        hits.push({ page: i + 1, items, r }),
      ),
    );
    return hits;
  };
  const after = (h: Hit, s: Hit) =>
    h.page > s.page || (h.page === s.page && h.r.start.item >= s.r.start.item);
  const rect = (h: Hit, item: number): PdfRect => {
    const it = h.items[item];
    const shown = h.items.filter((x) => x.str.trim());
    const left = Math.min(...shown.map((x) => x.x));
    const right = Math.max(...shown.map((x) => x.x + x.width));
    return {
      page: h.page,
      x: left,
      y: it.top - it.height,
      width: right - left,
      height: it.height * 1.25,
    };
  };
  let start: Hit | null = null;
  let fallback: Hit | null = null;
  for (const size of sizes) {
    for (let i = 0; i + size <= words.length && i < 20 && !start; i++) {
      const hits = hitsOf(words.slice(i, i + size).join(" "));
      if (hits.length === 1) {
        start = hits[0];
      } else if (hits.length && !fallback) {
        fallback = hits[0];
      }
    }
  }
  start ??= fallback;
  if (!start) {
    return null;
  }
  const first = start;
  let end: Hit | null = null;
  for (const size of sizes) {
    for (
      let i = words.length - size;
      i >= 0 && i > words.length - size - 20 && !end;
      i--
    ) {
      end =
        hitsOf(words.slice(i, i + size).join(" ")).find((h) =>
          after(h, first),
        ) ?? null;
    }
  }
  const last = end ?? first;
  return {
    start: rect(first, first.r.start.item),
    end: rect(last, last.r.end.item),
  };
}

function getSpans(n: number): HTMLElement[] {
  return [
    ...(getPageView(n)?.div?.querySelectorAll(
      ".textLayer span:not(.markedContent, .highlight)",
    ) ?? []),
  ];
}

// Rectangles around a match, from the text layer where it's rendered, since
// that has the real glyph widths, otherwise estimated from the text items
function getRangeRects(m: Occurrence): Box[] {
  const rects: Box[] = [];
  const pv = getPageView(m.page);
  const box = getPageBox(pv.div);
  const domSpans = getSpans(m.page);
  for (let i = m.range.start.item; i <= m.range.end.item; i++) {
    const it = m.items[i];
    const len = Math.max(it.str.length, 1);
    const a = i === m.range.start.item ? m.range.start.offset : 0;
    const b = i === m.range.end.item ? m.range.end.offset : it.str.length;
    if (b <= a || !it.width) {
      continue;
    }
    const node = domSpans[it.span]?.firstChild;
    if (node?.nodeType === Node.TEXT_NODE && node.textContent === it.str) {
      const range = document.createRange();
      range.setStart(node, a);
      range.setEnd(node, b);
      for (const r of range.getClientRects()) {
        rects.push({
          left: r.left - box.left,
          top: r.top - box.top,
          width: r.width,
          height: r.height,
        });
      }
      continue;
    }
    const r = [
      ...pv.viewport.convertToViewportPoint(
        it.x + (it.width * a) / len,
        it.base - it.height * 0.25,
      ),
      ...pv.viewport.convertToViewportPoint(
        it.x + (it.width * b) / len,
        it.base + it.height * 0.85,
      ),
    ];
    rects.push({
      left: Math.min(r[0], r[2]),
      top: Math.min(r[1], r[3]),
      width: Math.abs(r[2] - r[0]),
      height: Math.abs(r[3] - r[1]),
    });
  }
  return rects;
}

function getLayer(n: number): HTMLElement | null {
  const pv = getPageView(n);
  if (!pv?.div) {
    return null;
  }
  let node = pv.div.querySelector(".ck-layer") as HTMLElement | null;
  if (!node) {
    node = document.createElement("div");
    node.className = "ck-layer";
    pv.div.appendChild(node);
  }
  return node;
}

function addEl(
  parent: HTMLElement,
  cls: string,
  box: Box,
  t: Thread,
): HTMLElement {
  const node = document.createElement("div");
  node.className =
    cls +
    (t.resolved ? " resolved" : "") +
    (selected === t.key ? " selected" : "");
  Object.assign(node.style, { left: `${box.left}px`, top: `${box.top}px` });
  if (box.width !== undefined) {
    node.style.width = `${box.width}px`;
  }
  if (box.height !== undefined) {
    node.style.height = `${box.height}px`;
  }
  node.addEventListener("click", (e) => {
    e.stopPropagation();
    select(t.key, false);
  });
  parent.appendChild(node);
  return node;
}

let drawGen = 0;
async function draw(): Promise<void> {
  if (!pdfDoc) {
    return;
  }
  const gen = ++drawGen;
  for (let n = 1; n <= pdfDoc.numPages; n++) {
    getPageView(n)?.div?.querySelector(".ck-layer")?.replaceChildren();
  }
  const pins = new Map<string, number>();
  for (const t of threads) {
    if (!isShown(t)) {
      continue;
    }
    if (!t.start && t.anchor) {
      const place = await findParagraph(t.anchor.text);
      if (gen !== drawGen) {
        return;
      }
      if (place) {
        Object.assign(t, place);
      } else if (!t.unplaced) {
        t.unplaced = true;
        renderPanel();
      }
    }
    if (!t.start) {
      continue;
    }
    const startLayer = getLayer(t.start.page);
    if (!startLayer) {
      continue;
    }
    const end = t.end && t.end.page === t.start.page ? t.end : null;
    const view = getPageView(t.start.page).viewport.viewBox;
    const [x0, y0] = toViewport(
      t.start.page,
      t.start.x + t.start.width + 4,
      t.start.y,
    );
    const [, y1] = toViewport(
      t.start.page,
      0,
      end ? end.y + end.height : view[3],
    );
    addEl(
      startLayer,
      "ck-bar",
      { left: x0, top: y0, height: Math.max(y1 - y0, 8) },
      t,
    );
    // Threads on the same paragraph fan out to the right
    const key = `${t.start.page}:${Math.round(t.start.y)}`;
    const k = pins.get(key) ?? 0;
    pins.set(key, k + 1);
    const pin = addEl(
      startLayer,
      "ck-pin",
      { left: x0 + 6 + k * 22, top: y0 - 2 },
      t,
    );
    pin.textContent = String(t.messages.length);
    pin.title = `${t.messages[0]?.author}: ${t.messages[0]?.text}`;
    if (t.highlight) {
      const last = t.end ?? t.start;
      const found = await getOccurrences(
        t.highlight.text,
        { page: t.start.page, y: t.start.y },
        { page: last.page, y: last.y + last.height },
      );
      if (gen !== drawGen) {
        return;
      }
      const m = found[t.highlight.occ] ?? found[0];
      const hlLayer = m && getLayer(m.page);
      if (m && hlLayer) {
        for (const r of getRangeRects(m)) {
          addEl(hlLayer, "ck-hl", r, t);
        }
      }
    }
  }
}

function renderPanel(): void {
  const shown = threads.filter(isShown);
  const parts: string[] = [];
  const busy = new Set([...sending.values()].map((s) => s.key));
  if (composer) {
    parts.push(
      `<div class="thread composer" data-key="__new"><div class="quote">${esc(
        composer.text,
      )}</div>` +
        `<textarea id="new-text" placeholder="Add a comment"${
          composer.saving ? " disabled" : ""
        }>${esc(composer.draft)}</textarea>` +
        (composer.saving
          ? '<div class="actions"><button class="primary" disabled>Saving…</button></div></div>'
          : '<div class="actions"><button class="primary" data-act="save-new">Comment</button>' +
            '<button data-act="cancel-new">Cancel</button></div></div>'),
    );
  }
  if (!shown.length && !composer) {
    const hidden = threads.length - shown.length;
    parts.push(
      `<div class="empty">No ${hidden ? "open " : ""}comments. ` +
        "Select text in the PDF to add one." +
        (hidden ? ` ${hidden} resolved hidden.` : "") +
        "</div>",
    );
  }
  for (const t of shown) {
    const held = busy.has(t.key) ? " disabled" : "";
    const msgs = t.messages
      .map(
        (m) =>
          `<div class="msg"><span class="who">${esc(m.author)}</span>` +
          (m.date ? `<span class="when">${esc(m.date)}</span>` : "") +
          `<div class="text">${esc(m.text)}</div></div>`,
      )
      .join("");
    const actions =
      deleting === t.key
        ? "<span>Delete this thread and its replies?</span>" +
          '<button class="primary" data-act="confirm-delete">Delete</button>' +
          '<button data-act="cancel-delete">Cancel</button>'
        : '<textarea placeholder="Reply"></textarea>' +
          `<button class="primary" data-act="reply"${held}>Reply</button>` +
          `<button data-act="resolve">${
            t.resolved ? "Reopen" : "Resolve"
          }</button>` +
          '<button data-act="source">Source</button>' +
          (t.overleaf
            ? ""
            : `<button data-act="overleaf" title="Add it to Overleaf's comments, kept in step from then on"${held}>Post to Overleaf</button>`) +
          '<button data-act="delete">Delete</button>';
    parts.push(
      `<div class="thread${t.resolved ? " resolved" : ""}${
        selected === t.key ? " selected" : ""
      }" data-key="${esc(t.key)}">` +
        `<div class="meta">${
          t.resolved ? '<span class="badge">Resolved</span>' : ""
        }` +
        (t.issue
          ? `<a data-act="issue" title="${esc(t.issue)}">Issue</a>`
          : "") +
        (t.overleaf
          ? '<span title="Kept in step with a comment on Overleaf">Overleaf</span>'
          : "") +
        (t.unplaced
          ? '<span title="Its paragraph was not found in the PDF">Not placed</span>'
          : "") +
        "</div>" +
        (t.highlight
          ? `<div class="quote">${esc(t.highlight.text)}</div>`
          : "") +
        msgs +
        `<div class="actions">${actions}</div></div>`,
    );
  }
  // Keep anything typed but not yet sent
  const keyOf = (node: Element | null | undefined) =>
    (node?.closest(".thread") as HTMLElement | null)?.dataset.key;
  const typed = new Map(
    [...panel.querySelectorAll("textarea")].map((node) => [
      keyOf(node),
      node.value,
    ]),
  );
  const focused = keyOf(document.activeElement);
  panel.innerHTML = parts.join("");
  for (const node of panel.querySelectorAll("textarea")) {
    const key = keyOf(node);
    const value = typed.get(key);
    if (value) {
      node.value = value;
    }
    if (key === focused) {
      node.focus();
    }
  }
  if (composer && !focused) {
    panel.querySelector<HTMLTextAreaElement>("#new-text")?.focus();
  }
}

function select(key: string, scroll: boolean): void {
  selected = key;
  if (!state.showPanel) {
    state.showPanel = true;
    applyState();
  }
  renderPanel();
  void draw();
  const t = threads.find((x) => x.key === key);
  panel
    .querySelector(`[data-key="${CSS.escape(key)}"]`)
    ?.scrollIntoView({ block: "nearest" });
  if (scroll && t?.start) {
    reveal(t.start);
  }
  // And in the source, so the comment's in view in all three
  if (t) {
    post({ type: "openSource", file: t.path, line: t.line });
  }
}

function reveal(rect: PdfRect): void {
  const pv = getPageView(rect.page);
  if (!pv) {
    return;
  }
  const [x0, y0] = toViewport(rect.page, rect.x, rect.y);
  const [x1, y1] = toViewport(
    rect.page,
    rect.x + rect.width,
    rect.y + rect.height,
  );
  container.scrollTo({
    top: pv.div.offsetTop + y0 - container.clientHeight / 3,
  });
  const node = document.createElement("div");
  node.className = "ck-flash";
  Object.assign(node.style, {
    left: `${Math.min(x0, x1)}px`,
    top: `${Math.min(y0, y1)}px`,
    width: `${Math.max(Math.abs(x1 - x0), 20)}px`,
    height: `${Math.max(Math.abs(y1 - y0), 10)}px`,
  });
  pv.div.appendChild(node);
  setTimeout(() => node.remove(), 1700);
}

panel.addEventListener("click", (e) => {
  const target = e.target as HTMLElement;
  const card = target.closest<HTMLElement>(".thread");
  if (!card) {
    return;
  }
  const act = target.closest<HTMLElement>("[data-act]")?.dataset.act;
  if (card.dataset.key === "__new") {
    if (act === "cancel-new") {
      composer = null;
      renderPanel();
    }
    if (act === "save-new" && composer && !composer.saving) {
      const text =
        panel.querySelector<HTMLTextAreaElement>("#new-text")?.value.trim() ??
        "";
      if (!text || !composer.file || composer.line === undefined) {
        return;
      }
      composer.saving = ++reqCounter;
      composer.draft = text;
      post({
        type: "add",
        reqId: composer.saving,
        file: composer.file,
        line: composer.line,
        text,
        highlight: composer.text,
        occ: composer.occ,
      });
      setStatus("Saving comment…");
      renderPanel();
    }
    return;
  }
  const t = threads.find((x) => x.key === card.dataset.key);
  if (!t) {
    return;
  }
  const ref = t.id
    ? { file: t.path, id: t.id }
    : { file: t.path, line: t.line };
  if (!act) {
    if (selected !== t.key) {
      select(t.key, true);
    }
    return;
  }
  const held = [...sending.values()].some((s) => s.key === t.key);
  if (act === "reply") {
    const text = card.querySelector("textarea")?.value.trim();
    if (text && !held) {
      const reqId = ++reqCounter;
      sending.set(reqId, { key: t.key, act });
      post({ type: "reply", ...ref, reqId, text });
      setStatus("Saving reply…");
      renderPanel();
    }
  } else if (act === "resolve") {
    post({ type: "resolve", ...ref, resolved: !t.resolved });
  } else if (act === "delete") {
    deleting = t.key;
    renderPanel();
  } else if (act === "cancel-delete") {
    deleting = null;
    renderPanel();
  } else if (act === "confirm-delete") {
    deleting = null;
    post({ type: "delete", ...ref });
  } else if (act === "overleaf") {
    if (!held) {
      const reqId = ++reqCounter;
      sending.set(reqId, { key: t.key, act });
      post({ type: "postToOverleaf", ...ref, reqId });
      setStatus("Posting to Overleaf\u2026");
      renderPanel();
    }
  } else if (act === "source") {
    post({ type: "openSource", file: t.path, line: t.line });
  } else if (act === "issue" && t.issue) {
    post({ type: "openIssue", url: t.issue });
  }
});

panel.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
    (e.target as HTMLElement)
      .closest(".thread")
      ?.querySelector<HTMLButtonElement>("button.primary")
      ?.click();
  }
});

// Selecting text offers to comment on it
container.addEventListener("mouseup", () => {
  setTimeout(() => {
    const sel = document.getSelection();
    const text =
      sel && !sel.isCollapsed ? normalizeSelection(sel.toString()) : "";
    if (
      !sel ||
      !text ||
      !sel.anchorNode ||
      !container.contains(sel.anchorNode)
    ) {
      selectBtn.style.display = "none";
      return;
    }
    const rects = sel.getRangeAt(0).getClientRects();
    const lastRect = rects[rects.length - 1];
    const wrapRect = byId("wrap").getBoundingClientRect();
    selectBtn.style.left = `${lastRect.right - wrapRect.left + 4}px`;
    selectBtn.style.top = `${lastRect.bottom - wrapRect.top + 4}px`;
    selectBtn.style.display = "flex";
  }, 0);
});
container.addEventListener("scroll", () => {
  selectBtn.style.display = "none";
});
selectBtn.addEventListener("mousedown", (e) => e.preventDefault());

// How far into an element's text a point in it is
function offsetIn(node: Node, inner: Node, offset: number): number {
  if (inner.nodeType !== Node.TEXT_NODE) {
    return 0;
  }
  const r = document.createRange();
  r.setStart(node, 0);
  r.setEnd(inner, offset);
  return r.toString().length;
}

// The selected text, where it starts on its page, and the lines it's on
async function getCommentSelection(): Promise<{
  text: string;
  page: number;
  at: { x: number; y: number };
  item: number;
  offset: number;
  context: string;
} | null> {
  const sel = document.getSelection();
  if (!sel || sel.isCollapsed) {
    return null;
  }
  const range = sel.getRangeAt(0);
  const rects = range.getClientRects();
  const startNode = range.startContainer;
  // Search matches split a text layer span, so it's the one around them
  let startEl =
    startNode.nodeType === Node.TEXT_NODE
      ? startNode.parentElement
      : (startNode as HTMLElement);
  if (startEl?.classList.contains("highlight")) {
    startEl = startEl.parentElement;
  }
  const pageDiv = startEl?.closest<HTMLElement>(".page");
  if (!startEl || !rects.length || !pageDiv) {
    return null;
  }
  const n = Number(pageDiv.dataset.pageNumber);
  // Where the selection starts in the page's text items
  const domIndex = getSpans(n).indexOf(startEl);
  const item = (await getPageText(n)).findIndex(
    (it) => it.span === domIndex && domIndex >= 0,
  );
  const box = getPageBox(pageDiv);
  const first = rects[0];
  const last = rects[rects.length - 1];
  const at = fromViewport(
    n,
    first.left - box.left + 1,
    first.top - box.top + first.height / 2,
  );
  const atEnd = fromViewport(
    n,
    last.left - box.left,
    last.top - box.top + last.height / 2,
  );
  return {
    text: normalizeSelection(sel.toString()),
    page: n,
    at,
    item,
    offset: offsetIn(startEl, startNode, range.startOffset),
    context: await getLineText(n, at.y, atEnd.y),
  };
}

// The page and point there under a point in the window
function pointAt(
  cx: number,
  cy: number,
): { page: number; at: { x: number; y: number } } | null {
  const pageDiv = document
    .elementFromPoint(cx, cy)
    ?.closest<HTMLElement>(".page");
  if (!pageDiv) {
    return null;
  }
  const n = Number(pageDiv.dataset.pageNumber);
  const box = getPageBox(pageDiv);
  return { page: n, at: fromViewport(n, cx - box.left, cy - box.top) };
}

// What a PDF built on this machine was built with, once it's read
let localSynctex: Synctex | null = null;

// Go to the source of the selection, or of a point on a page
async function sourceAt(
  point: { page: number; at: { x: number; y: number } } | null,
): Promise<void> {
  const sel = point ? null : await getCommentSelection();
  const getSynctex = (page: number, at: { x: number; y: number }) =>
    (localSynctex && synctexReverse(localSynctex, page, at.x, at.y)) ??
    undefined;
  if (sel) {
    post({
      type: "sourceAt",
      page: sel.page,
      x: sel.at.x,
      y: sel.at.y,
      context: sel.context,
      focus: sel.text,
      synctex: getSynctex(sel.page, sel.at),
    });
  } else if (point) {
    post({
      type: "sourceAt",
      page: point.page,
      x: point.at.x,
      y: point.at.y,
      context: await getLineText(point.page, point.at.y),
      synctex: getSynctex(point.page, point.at),
    });
  }
}

byId("select-source").addEventListener("click", () => {
  selectBtn.style.display = "none";
  void sourceAt(null);
});

byId("select-comment").addEventListener("click", async () => {
  selectBtn.style.display = "none";
  const sel = await getCommentSelection();
  if (!sel) {
    return;
  }
  const { text, page: n, at, item: selItem, offset: selOffset, context } = sel;
  const reqId = ++reqCounter;
  const located = new Promise<ToReview & { type: "located" }>((resolve) =>
    pending.set(reqId, resolve),
  );
  post({ type: "locate", reqId, page: n, x: at.x, y: at.y, context });
  composer = { text, occ: 0 };
  state.showComments = true;
  state.showPanel = true;
  applyState();
  renderPanel();
  const loc = await located;
  pending.delete(reqId);
  if (!composer || composer.text !== text) {
    return;
  }
  if (!loc.file || loc.line === undefined) {
    setStatus("Can't find the source of that text.");
    composer = null;
    renderPanel();
    return;
  }
  composer.file = loc.file;
  composer.line = loc.line;
  let start = loc.start;
  if (!start && loc.text) {
    start = (await findParagraph(loc.text))?.start;
  }
  // The highlight is the nth occurrence of its text in the paragraph
  if (start) {
    const to: Place =
      selItem >= 0
        ? { page: n, y: at.y, item: selItem, offset: selOffset }
        : { page: n, y: at.y - 6 };
    const found = await getOccurrences(
      text,
      { page: start.page, y: start.y },
      to,
    );
    composer.occ = found.length;
  }
});

// Double-clicking goes to the source, as in Overleaf's own viewer, and so
// does Ctrl or Cmd-clicking, as in VS Code's
container.addEventListener("click", (e) => {
  if (e.ctrlKey || e.metaKey) {
    void sourceAt(pointAt(e.clientX, e.clientY));
  }
});
container.addEventListener("dblclick", (e) => {
  const point = pointAt(e.clientX, e.clientY);
  if (point) {
    document.getSelection()?.removeAllRanges();
    selectBtn.style.display = "none";
    void sourceAt(point);
  }
});

function applyState(): void {
  document.body.classList.toggle("no-comments", !state.showComments);
  document.body.classList.toggle("no-panel", !state.showPanel);
  document.documentElement.style.setProperty(
    "--panel-width",
    `${state.panelWidth}px`,
  );
  byId("toggle-comments").setAttribute(
    "aria-pressed",
    String(state.showComments),
  );
  byId<HTMLInputElement>("show-resolved").checked = state.showResolved;
  save();
}

byId("toggle-comments").addEventListener("click", () => {
  state.showComments = !state.showComments;
  // Showing them again brings back the threads too
  if (state.showComments) {
    state.showPanel = true;
  }
  applyState();
});
byId("close-panel").addEventListener("click", () => {
  state.showPanel = false;
  applyState();
});

// Dragging the sidebar's edge resizes it
const resizer = byId("resizer");
resizer.addEventListener("pointerdown", (e) => {
  resizer.setPointerCapture(e.pointerId);
  resizer.classList.add("dragging");
  const move = (ev: PointerEvent) => {
    state.panelWidth = Math.round(
      Math.min(
        Math.max(window.innerWidth - ev.clientX, 160),
        window.innerWidth * 0.6,
      ),
    );
    document.documentElement.style.setProperty(
      "--panel-width",
      `${state.panelWidth}px`,
    );
  };
  const up = () => {
    resizer.classList.remove("dragging");
    resizer.removeEventListener("pointermove", move);
    save();
  };
  resizer.addEventListener("pointermove", move);
  resizer.addEventListener("pointerup", up, { once: true });
});

byId<HTMLInputElement>("show-resolved").addEventListener("change", (e) => {
  state.showResolved = (e.target as HTMLInputElement).checked;
  applyState();
  renderPanel();
  void draw();
});

function setScale(value: number | string): void {
  viewer.currentScaleValue = String(value);
  state.scale = String(value);
  save();
}
byId("zoom-in").addEventListener("click", () =>
  setScale(Math.min(viewer.currentScale * 1.1, 5)),
);
byId("zoom-out").addEventListener("click", () =>
  setScale(Math.max(viewer.currentScale / 1.1, 0.25)),
);
byId("fit").addEventListener("click", () => setScale("page-width"));

// Kept across a rebuild, which loads the new PDF where the old one was
let keepScroll: number | null = null;
eventBus.on("pagesinit", () => {
  viewer.currentScaleValue = state.scale;
  const top = keepScroll ?? state.scrollTop;
  if (top) {
    container.scrollTop = top;
  }
  keepScroll = null;
});
eventBus.on("pagechanging", (e: { pageNumber: number }) => {
  byId("page").textContent = `${e.pageNumber} / ${pdfDoc?.numPages ?? ""}`;
});
container.addEventListener("scroll", () => {
  state.scrollTop = container.scrollTop;
  save();
});
// What's wrong with what the document shows, from the page it's on
let boxes: PdfBox[] = [];
function drawBoxes(): void {
  placePdfBoxes(boxes, (box) =>
    post({ type: "goto", line: box.line, column: box.column }),
  );
}
eventBus.on("textlayerrendered", () => {
  void draw();
  drawBoxes();
});
eventBus.on("scalechanging", () => setTimeout(drawBoxes, 0));
// Where the pointer rests, so the page can say what's there, as it does on
// its own viewer; a few times a second at most
let pointerTimer: ReturnType<typeof setTimeout> | undefined;
let lastPointer: MouseEvent | null = null;
container.addEventListener("mousemove", (e) => {
  lastPointer = e;
  pointerTimer ??= setTimeout(() => {
    pointerTimer = undefined;
    const event = lastPointer;
    const point = event && pointAt(event.clientX, event.clientY);
    post({
      type: "pointer",
      point: point && {
        page: point.page,
        x: point.at.x,
        y: point.at.y,
        clientX: event.clientX,
        clientY: event.clientY,
      },
    });
  }, 100);
});
for (const type of ["mouseleave", "scroll"]) {
  container.addEventListener(type, () => {
    clearTimeout(pointerTimer);
    pointerTimer = undefined;
    lastPointer = null;
    post({ type: "pointer", point: null });
  });
}
new ResizeObserver(() => {
  if (pdfDoc && state.scale === "page-width") {
    viewer.currentScaleValue = "page-width";
  }
}).observe(container);

async function load(data: Uint8Array): Promise<void> {
  try {
    const doc = await pdfjsLib.getDocument({ data }).promise;
    const old = pdfDoc;
    if (old) {
      keepScroll = container.scrollTop;
    }
    pdfDoc = doc;
    textCache.clear();
    placeCache.clear();
    for (const t of threads) {
      t.unplaced = false;
    }
    viewer.setDocument(doc);
    linkService.setDocument(doc);
    byId("page").textContent = `1 / ${doc.numPages}`;
    // pdf.js 6 destroys a document through its loading task
    void old?.loadingTask.destroy();
  } catch (err) {
    setStatus(
      `Couldn't open the PDF: ${err instanceof Error ? err.message : err}`,
    );
  }
}

// Searching the PDF's text, with Cmd/Ctrl+F, as in an editor
const findBar = byId("find");
const findInput = byId<HTMLInputElement>("find-input");
const findCount = byId("find-count");
function find(type: string, previous = false): void {
  eventBus.dispatch("find", {
    source: findBar,
    type,
    query: findInput.value,
    caseSensitive: false,
    entireWord: false,
    highlightAll: true,
    findPrevious: previous,
    matchDiacritics: false,
  });
}
function openFind(): void {
  const text = document.getSelection()?.toString().trim();
  if (text && !text.includes("\n")) {
    findInput.value = normalizeSelection(text);
  }
  findBar.hidden = false;
  findInput.focus();
  findInput.select();
  if (findInput.value) {
    find("");
  }
}
function closeFind(): void {
  findBar.hidden = true;
  eventBus.dispatch("findbarclose", { source: findBar });
  container.focus();
}
function showCount({ current, total }: { current: number; total: number }) {
  findCount.textContent = !findInput.value
    ? ""
    : total
    ? `${current} of ${total}`
    : "No results";
  findBar.classList.toggle("missing", !!findInput.value && !total);
}
eventBus.on(
  "updatefindmatchescount",
  (e: { matchesCount: { current: number; total: number } }) =>
    showCount(e.matchesCount),
);
eventBus.on(
  "updatefindcontrolstate",
  (e: { matchesCount: { current: number; total: number } }) =>
    showCount(e.matchesCount),
);
findInput.addEventListener("input", () => find(""));
panel.addEventListener("input", (e) => {
  const target = e.target as HTMLElement;
  if (composer && target.id === "new-text") {
    composer.draft = (target as HTMLTextAreaElement).value;
  }
});
findInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    find("again", e.shiftKey);
  } else if (e.key === "Escape") {
    e.preventDefault();
    closeFind();
  }
});
byId("find-prev").addEventListener("click", () => find("again", true));
byId("find-next").addEventListener("click", () => find("again"));
byId("find-close").addEventListener("click", closeFind);
window.addEventListener("keydown", (e) => {
  const mod = e.metaKey || e.ctrlKey;
  if (mod && !e.altKey && e.key.toLowerCase() === "f") {
    e.preventDefault();
    openFind();
  } else if (
    ((mod && e.key.toLowerCase() === "g") || e.key === "F3") &&
    !findBar.hidden &&
    findInput.value
  ) {
    e.preventDefault();
    find("again", e.shiftKey);
  } else if (
    e.key === "Escape" &&
    !findBar.hidden &&
    !(e.target as HTMLElement).closest?.("textarea")
  ) {
    closeFind();
  }
});

window.addEventListener("message", (e) => {
  if (
    e.source !== window.parent ||
    e.origin !== parentOrigin ||
    e.data?.calkit !== "review"
  ) {
    return;
  }
  const msg = e.data as ToReview;
  if (msg.type === "load") {
    void load(new Uint8Array(msg.data));
  } else if (msg.type === "threads") {
    // Placed by their text again, since the PDF may have changed
    threads = msg.threads;
    const open = threads.filter((t) => !t.resolved).length;
    const count = byId("comment-count");
    count.textContent = String(open);
    count.hidden = !open;
    byId("toggle-comments").title = `Show or hide comments (${open} open, ${
      threads.length - open
    } resolved)`;
    setStatus(
      msg.synctex && msg.stale.length
        ? "Recompile to place comments exactly"
        : "",
    );
    if (msg.synctex && msg.stale.length) {
      statusEl.title = `Changed since this PDF was built: ${msg.stale.join(
        ", ",
      )}`;
    }
    renderPanel();
    void draw();
  } else if (msg.type === "status") {
    setStatus(msg.text);
  } else if (msg.type === "sent") {
    // A new comment goes once it's in the list, or stays to try again
    if (composer?.saving === msg.reqId) {
      composer = msg.ok ? null : { ...composer, saving: undefined };
    }
    const sent = sending.get(msg.reqId);
    sending.delete(msg.reqId);
    // A reply that went through isn't kept, to be sent again
    if (sent?.act === "reply" && msg.ok) {
      const node = panel.querySelector<HTMLTextAreaElement>(
        `[data-key="${CSS.escape(sent.key)}"] textarea`,
      );
      if (node) {
        node.value = "";
      }
    }
    renderPanel();
  } else if (msg.type === "boxes") {
    boxes = msg.boxes;
    drawBoxes();
  } else if (msg.type === "reveal") {
    reveal(msg.rect);
  } else if (msg.type === "located") {
    pending.get(msg.reqId)?.(msg);
  }
});

applyState();
// A PDF built on this machine is read from it here
const localProject = params.get("localProject");
if (localProject) {
  setStatus("Reading PDF from this machine…");
  getLocalPdf(localProject, params.get("folder") ?? "")
    .then(async ({ parts, first }) => {
      const data = new Uint8Array(first.size);
      let offset = 0;
      for (const part of parts) {
        data.set(part, offset);
        offset += part.length;
      }
      await load(data);
      // Where each place in it came from, for going to its source
      void getLocalSynctex(localProject, params.get("folder") ?? "").then(
        (s) => (localSynctex = s),
      );
      setStatus(
        first.edited_since_built
          ? `${params.get("folder")} has changed since this PDF was built`
          : "",
      );
    })
    .catch((err) =>
      setStatus(
        `Couldn't read the PDF: ${err instanceof Error ? err.message : err}`,
      ),
    );
}
post({ type: "ready" });
