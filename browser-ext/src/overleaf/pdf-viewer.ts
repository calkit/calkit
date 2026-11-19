/**
 * Overleaf's PDF pane: boxes over what came from the project, the PDF built
 * on this machine, and the review pane for commenting on the PDF.
 */
import { getShownValue } from "../core/latex";
import { isExtensionAlive, send } from "../core/messages";
import { type OverleafLinkPublic } from "../core/types";
import { el } from "../core/ui";
import {
  type CommentAuthor,
  type FromReview,
  type LineEdit,
  type OverleafComment,
  type OverleafSynced,
  type OverleafThread,
  type PdfRect,
  type ToReview,
  findParagraphByText,
  getAddEdit,
  getEditedLines,
  getOverleafSyncedLines,
  getReply,
  getReviewThreads,
  getThreadEdit,
} from "../core/review";
import { getZipTexts } from "../core/zip";
import { type PdfBox, placePdfBoxes } from "../core/pdf-boxes";
import {
  findInSource,
  lineMap,
  paragraphLines,
  parseSynctex,
  synctexForward,
  synctexInputFile,
  synctexTag,
} from "../../../vscode-ext/src/latex/pdf";
import {
  currentProjectId,
  lastCheck,
  watching,
  observePage,
  currentLink,
  citationProvenance,
  readEditor,
  getOverleafTree,
  editEditor,
  openDocument,
} from "./index";
import {
  Without,
  editorCitations,
  editorProblems,
  toEditor,
  fillTooltip,
} from "./citations";
import { RAIL_TAB_ID } from "./sidebar";

type SynctexBox = Omit<PdfBox, "message" | "options" | "textLeft" | "text">;

/** The PDF Overleaf last built, which synctex lookups have to name. */
interface PdfBuild {
  buildId: string;
  /** Overleaf's lookups fail without it once its URLs carry one. */
  editorId: string | null;
  clsiServerId: string | null;
}

let pdfBuild: PdfBuild | null = null;
let pdfBoxes: PdfBox[] = [];
const synctexCache = new Map<string, Promise<SynctexBox[]>>();

/** The open document's path in the Overleaf project, from the file tree. */
export function openDocPath(): string | null {
  const selected = document.querySelector<HTMLElement>(
    '[role="treeitem"][aria-selected="true"]',
  );
  const name = selected?.getAttribute("aria-label");
  if (!selected || !name || !/\.tex$/i.test(name)) {
    return null;
  }
  const parts = [name];
  let folder = selected.parentElement?.closest('[role="treeitem"]');
  while (folder) {
    parts.unshift(folder.getAttribute("aria-label") ?? "");
    folder = folder.parentElement?.closest('[role="treeitem"]');
  }
  return parts.join("/");
}

// Overleaf's synctex wants an editor ID, but a build in a user's own zone
// doesn't belong to one, so any will do for those
const ANY_EDITOR_ID = crypto.randomUUID();

function setBuildParams(params: URLSearchParams, build: PdfBuild): void {
  params.set("buildId", build.buildId);
  params.set("editorId", build.editorId ?? ANY_EDITOR_ID);
  if (build.clsiServerId) {
    params.set("clsiserverid", build.clsiServerId);
  }
}

/** Where in the PDF a line of the open document landed, as Overleaf says. */
function synctex(
  projectId: string,
  build: PdfBuild,
  file: string,
  line: number,
  column: number,
): Promise<SynctexBox[]> {
  const params = new URLSearchParams({
    file,
    line: String(line),
    column: String(column),
  });
  setBuildParams(params, build);
  const key = params.toString();
  let cached = synctexCache.get(key);
  if (!cached) {
    cached = fetch(`/project/${projectId}/sync/code?${params}`, {
      headers: { Accept: "application/json" },
    })
      .then((response) => (response.ok ? response.json() : { pdf: [] }))
      .then((data: { pdf?: Omit<SynctexBox, "line" | "column">[] }) =>
        (data.pdf ?? []).map((box) => ({ ...box, line, column })),
      )
      .catch(() => []);
    synctexCache.set(key, cached);
  }
  return cached;
}

// The SyncTeX of the PDF from this machine, read once for each time it's
// shown
let localSynctexText: {
  pdf: NonNullable<typeof localPdf>;
  text: Promise<string | null>;
} | null = null;

/**
 * Where lines of an Overleaf file landed in the PDF built on this machine,
 * as Overleaf says for its own, mapped from Overleaf's copy of the file to
 * this machine's, which may differ, e.g., by comments not synced here yet.
 */
async function getLocalBoxes(
  pdf: NonNullable<typeof localPdf>,
  file: string,
): Promise<(line: number, column: number) => SynctexBox[]> {
  const project = `${pdf.link.project_owner_name}/${pdf.link.project_name}`;
  if (localSynctexText?.pdf !== pdf) {
    localSynctexText = {
      pdf,
      text: send({
        type: "local.publicationSynctex",
        project,
        folder: pdf.path,
      }).catch(() => null),
    };
  }
  const [text, built, current] = await Promise.all([
    localSynctexText.text,
    send({
      type: "local.publicationSource",
      project,
      folder: pdf.path,
      path: file,
    }).catch(() => null),
    readEditor(),
  ]);
  const s = text ? parseSynctex(text) : null;
  const tag = s ? synctexTag(s, file) : undefined;
  if (!s || tag === undefined) {
    return () => [];
  }
  const map =
    built && current !== null
      ? lineMap(built.text.split("\n"), current.split("\n"))
      : null;
  return (line, column) => {
    const builtLine = map ? map.toBefore(line) : line;
    // A box made on that line, e.g., a figure's, or else where the next
    // line with text landed
    const made = s.boxes.filter((b) => b.tag === tag && b.line === builtLine);
    const rects = made.length
      ? made
      : [synctexForward(s, tag, builtLine)].filter((r) => r !== undefined);
    return rects.map((r) => ({
      page: r.page,
      h: r.x,
      v: r.y + r.height,
      width: r.width,
      height: r.height,
      line,
      column,
    }));
  };
}

/** Find where each error in the open document lands in the PDF. */
export async function drawPdfBoxes(): Promise<void> {
  const build = pdfBuild;
  const snapshot = editorCitations;
  const problems = editorProblems;
  const projectId = currentProjectId;
  const file = openDocPath();
  if (
    !build ||
    !snapshot ||
    !projectId ||
    !file ||
    problems?.version !== snapshot.version
  ) {
    return;
  }
  const boxes: PdfBox[] = [];
  for (const [index, item] of snapshot.items.entries()) {
    const error = problems.found[index]?.find((p) => p.severity === "error");
    // Only what the project shows, not what's typed, has errors to box
    if (!error || !item.citation) {
      continue;
    }
    const found = await synctex(projectId, build, file, item.line, item.column);
    // Overleaf repeats boxes, and puts the line's box around a figure's,
    // so only the innermost of each is kept
    const inside = (a: SynctexBox, b: SynctexBox) =>
      a.page === b.page &&
      a.h >= b.h &&
      a.h + a.width <= b.h + b.width &&
      a.v - a.height >= b.v - b.height &&
      a.v <= b.v;
    const kept: SynctexBox[] = [];
    for (const box of found) {
      if (
        !kept.some((k) => inside(k, box)) &&
        !found.some(
          (other) => other !== box && inside(other, box) && !inside(box, other),
        )
      ) {
        kept.push(box);
      }
    }
    const { citation } = item;
    // The value as shown, which is somewhere in its line's box
    const provenance =
      citation.kind === "value" && currentLink
        ? await citationProvenance(currentLink, citation).catch(() => null)
        : null;
    const text =
      provenance && !provenance.value_error && provenance.value !== undefined
        ? getShownValue(provenance.value, citation.options)
        : undefined;
    for (const box of kept) {
      const same = boxes.find(
        (b) =>
          b.page === box.page &&
          b.h === box.h &&
          b.v === box.v &&
          b.text === text,
      );
      if (same) {
        if (!same.message.includes(error.message)) {
          same.message += `; ${error.message}`;
        }
        continue;
      }
      boxes.push({
        ...box,
        message: error.message,
        options: citation.kind === "figure" ? citation.options : undefined,
        textLeft: Math.min(...found.map((b) => b.h)),
        text,
      });
    }
  }
  if (pdfBuild !== build || editorCitations !== snapshot) {
    return;
  }
  pdfBoxes = boxes;
  showPdfBoxes();
}

/**
 * Draw what's wrong on Overleaf's PDF, and on the viewer with comments
 * when it's showing Overleaf's.
 */
function showPdfBoxes(): void {
  const goTo = (box: PdfBox) =>
    toEditor({ type: "goto", line: box.line, column: box.column });
  placePdfBoxes(pdfBoxes, goTo);
  if (review?.ready && !review.local) {
    postToReview({ type: "boxes", boxes: pdfBoxes });
  }
}

// What's under the pointer on the viewer with comments, shown as on
// Overleaf's, or null once it's off the PDF
let pdfPointer: (
  point: {
    page: number;
    h: number;
    v: number;
    clientX: number;
    clientY: number;
  } | null,
) => void = () => undefined;

/** Follow Overleaf's builds and its PDF viewer, to keep the boxes on it. */
export function watchPdf(): void {
  // A new build means new positions, and a lookup that failed for
  // want of the editor ID shouldn't stay cached
  const noteBuild = (url: string, clsiServerId: string | null) => {
    // e.g., build/<editor id>-<build id>/output/output.pdf, where the
    // editor ID, a UUID, isn't always there
    const match = url.match(
      /\/build\/(?:([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})-)?([0-9a-f]+-[0-9a-f]+)\/output\/(?:cached\/)?output\.pdf/,
    );
    if (!match) {
      return;
    }
    const [, editorId = null, buildId] = match;
    const same = buildId === pdfBuild?.buildId ? pdfBuild : null;
    const next = {
      buildId,
      editorId: editorId ?? same?.editorId ?? null,
      clsiServerId: clsiServerId ?? same?.clsiServerId ?? null,
    };
    if (
      same &&
      same.editorId === next.editorId &&
      same.clsiServerId === next.clsiServerId
    ) {
      return;
    }
    pdfBuild = next;
    synctexCache.clear();
    void drawPdfBoxes();
    void sendOverleafPdf();
  };
  // Overleaf's own requests say which compile server has the build, but
  // a content script may not see them, so the PDF's download link, which
  // it always can, says which build it is
  const resources = new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) {
      noteBuild(
        entry.name,
        URL.canParse(entry.name)
          ? new URL(entry.name).searchParams.get("clsiserverid")
          : null,
      );
    }
  });
  resources.observe({ type: "resource", buffered: true });
  watching.signal.addEventListener("abort", () => resources.disconnect());
  const noteDownloadLink = () => {
    const link = document.querySelector<HTMLAnchorElement>(
      'a[href*="/build/"][href*="output.pdf"]',
    );
    if (link) {
      noteBuild(link.href, null);
    }
  };
  noteDownloadLink();
  observePage(
    () => {
      noteDownloadLink();
      showPdfBoxes();
    },
    200,
    {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["href"],
    },
  );
  // A component's provenance on hover, as in the editor. Where each one
  // lands is asked of Overleaf once per build and edit, the first time the
  // pointer rests on the PDF, so moving it around costs nothing, and the
  // PDF still gets every click
  let shown: { index: number; version: number; host: HTMLElement } | null =
    null;
  let showing: ReturnType<typeof setTimeout> | undefined;
  let hiding: ReturnType<typeof setTimeout> | undefined;
  let lookups = 0;
  let tips = 0;
  let landed: {
    build: PdfBuild | NonNullable<typeof localPdf>;
    snapshot: NonNullable<typeof editorCitations>;
    file: string;
    boxes: Promise<{ index: number; box: SynctexBox }[]>;
  } | null = null;
  const hide = () => {
    clearTimeout(hiding);
    hiding = undefined;
    shown?.host.remove();
    shown = null;
  };
  const citationAt = async (page: number, h: number, v: number) => {
    // Over the PDF from this machine, it's what that was built with
    const local = review?.local ? localPdf : null;
    const build = local ?? pdfBuild;
    const projectId = currentProjectId;
    const snapshot = editorCitations;
    const file = openDocPath();
    // Only a paper linked to a project has anything to show
    if (!currentLink || !build || !projectId || !snapshot || !file) {
      return null;
    }
    if (
      landed?.build !== build ||
      landed.snapshot !== snapshot ||
      landed.file !== file
    ) {
      // One at a time, and cached by line, so an edit only asks again
      // about what moved
      const boxes = (async () => {
        const found: { index: number; box: SynctexBox }[] = [];
        const boxesAt = local
          ? await getLocalBoxes(local, file)
          : (line: number, column: number) =>
              synctex(projectId, build as PdfBuild, file, line, column);
        for (const [index, item] of snapshot.items.entries()) {
          if (!item.citation) {
            continue;
          }
          for (const box of await boxesAt(item.line, item.column)) {
            found.push({ index, box });
          }
        }
        return found;
      })();
      landed = { build, snapshot, file, boxes };
    }
    // The smallest box under the pointer, e.g., a figure's rather than the
    // line's around it; a box's v is its bottom
    let best: { index: number; area: number } | null = null;
    for (const { index, box } of await landed.boxes) {
      const area = box.width * box.height;
      if (
        box.page === page &&
        h >= box.h &&
        h <= box.h + box.width &&
        v >= box.v - box.height &&
        v <= box.v &&
        (!best || area < best.area)
      ) {
        best = { index, area };
      }
    }
    return best ? { index: best.index, version: snapshot.version } : null;
  };
  const show = (
    found: { index: number; version: number },
    x: number,
    y: number,
  ) => {
    hide();
    const host = el("div");
    host.id = `calkit-pdf-tooltip-${++tips}`;
    const below = y < window.innerHeight / 2;
    Object.assign(host.style, {
      position: "fixed",
      left: `${Math.max(4, Math.min(x - 20, window.innerWidth - 386))}px`,
      ...(below
        ? { top: `${y + 12}px` }
        : { bottom: `${window.innerHeight - y + 12}px` }),
      zIndex: "2147483646",
      border: "1px solid rgba(0, 0, 0, 0.15)",
      borderRadius: "4px",
      boxShadow: "0 2px 8px rgba(0, 0, 0, 0.2)",
      overflow: "hidden",
    });
    document.body.append(host);
    shown = { ...found, host };
    void fillTooltip(host.id, found.version, found.index);
  };
  // Over the PDF, what's under the pointer once it rests decides, whether
  // it's Overleaf's viewer or the one with comments
  const pointAt = (point: {
    page: number;
    h: number;
    v: number;
    clientX: number;
    clientY: number;
  }) => {
    clearTimeout(showing);
    clearTimeout(hiding);
    hiding = undefined;
    showing = setTimeout(async () => {
      const lookup = ++lookups;
      const found = await citationAt(point.page, point.h, point.v);
      if (lookup !== lookups) {
        return;
      }
      if (!found) {
        hide();
      } else if (
        shown?.index !== found.index ||
        shown.version !== found.version
      ) {
        show(found, point.clientX, point.clientY);
      }
    }, 300);
  };
  pdfPointer = (point) => {
    if (point) {
      pointAt(point);
      return;
    }
    clearTimeout(showing);
    if (shown && hiding === undefined) {
      hiding = setTimeout(hide, 300);
    }
  };
  document.addEventListener(
    "mousemove",
    (event) => {
      clearTimeout(showing);
      if (shown && event.target === shown.host) {
        clearTimeout(hiding);
        hiding = undefined;
        return;
      }
      const page = (event.target as Element | null)?.closest?.<HTMLElement>(
        ".pdfViewer .page[data-page-number]",
      );
      const scale = page
        ? parseFloat(getComputedStyle(page).getPropertyValue("--scale-factor"))
        : NaN;
      if (!page || !Number.isFinite(scale)) {
        if (shown && hiding === undefined) {
          hiding = setTimeout(hide, 300);
        }
        return;
      }
      const bounds = page.getBoundingClientRect();
      pointAt({
        page: Number(page.dataset.pageNumber),
        h: (event.clientX - bounds.left - page.clientLeft) / scale,
        v: (event.clientY - bounds.top - page.clientTop) / scale,
        clientX: event.clientX,
        clientY: event.clientY,
      });
    },
    { passive: true, signal: watching.signal },
  );
  // A fixed tooltip would stay put while the PDF scrolls away under it
  document.addEventListener(
    "scroll",
    (event) => {
      if (shown && event.target !== shown.host) {
        clearTimeout(showing);
        hide();
      }
    },
    { capture: true, passive: true, signal: watching.signal },
  );
}

// The PDF from this machine shown over Overleaf's, if it is
export let localPdf: {
  host: HTMLElement;
  link: OverleafLinkPublic;
  path: string;
} | null = null;

/**
 * Show the PDF a synced folder builds to on this machine, e.g., from a
 * pipeline run, over Overleaf's, so there's no waiting on Overleaf to
 * compile, until it's turned off. Overleaf's own PDF features, e.g.,
 * double-clicking to go to the source, don't work in it.
 */
export function showLocalPdf(link: OverleafLinkPublic, path: string): void {
  hideLocalPdf();
  const pane = getPdfPane();
  if (!pane) {
    return;
  }
  const params = new URLSearchParams({
    localProject: `${link.project_owner_name}/${link.project_name}`,
    folder: path,
  });
  const frame = el("iframe", {
    title: "PDF from this machine",
    style: { flex: "1", width: "100%", border: "none", background: "#fff" },
  });
  // Always with comments, whose own toggle hides them, since without them
  // it would be the browser's plain viewer
  frame.src = getReviewUrl(params);
  // The switch in Overleaf's toolbar says which PDF this is
  const host = el("div", {}, [frame]);
  Object.assign(host.style, {
    display: "flex",
    flexDirection: "column",
    background: "#fff",
    position: "absolute",
    inset: "0",
    zIndex: "20",
  });
  if (getComputedStyle(pane).position === "static") {
    pane.style.position = "relative";
  }
  pane.append(host);
  localPdf = { host, link, path };
  hideOverleafReview();
  review = { frame, host, local: true, ready: false, buildId: null };
  mountPdfSwitch();
  mountCommentsToggle();
}

function hideLocalPdf(): void {
  localPdf?.host.remove();
  localPdf = null;
  if (review?.local) {
    review = null;
  }
  mountPdfSwitch();
  mountCommentsToggle();
  if (commentsOn) {
    showOverleafReview();
  }
}

// Whether the PDF is shown with its comments, in the viewer that has
// them, for this Overleaf project
let commentsOn = false;
/** Whether someone last showed comments on an Overleaf project, by ID. */
const COMMENTS_KEY = "pdfComments";

// The viewer with comments over Overleaf's PDF pane, if it's shown
export let review: {
  frame: HTMLIFrameElement;
  host: HTMLElement;
  /** Showing the PDF built on this machine, rather than Overleaf's. */
  local: boolean;
  ready: boolean;
  /** The build of Overleaf's PDF it has. */
  buildId: string | null;
} | null = null;

// The project's LaTeX source as the PDF was built from it, and as it is
// now, which the threads and where they are in the PDF come from
let reviewSources: {
  buildId: string | null;
  built: Map<string, string>;
  current: Map<string, string>;
} | null = null;

/** Who's commenting, as Overleaf knows them. */
function getCommentAuthor(): CommentAuthor {
  try {
    const user = JSON.parse(
      document.querySelector<HTMLMetaElement>('meta[name="ol-user"]')
        ?.content ?? "{}",
    );
    const name = [user.first_name, user.last_name]
      .filter(Boolean)
      .join(" ")
      .trim();
    return { name: name || user.email || "Someone", email: user.email ?? null };
  } catch {
    return { name: "Someone", email: null };
  }
}

/**
 * The text of the project's LaTeX files, except the ones Calkit writes:
 * each on its own where the file tree shows its ID, else all from the
 * project's download, e.g., for one in a folder that's closed.
 */
async function getOverleafTexts(
  projectId: string,
): Promise<Map<string, string>> {
  const response = await fetch(`/project/${projectId}/entities`);
  if (!response.ok) {
    throw new Error(`Couldn't list the project's files (${response.status})`);
  }
  const { entities } = (await response.json()) as {
    entities: { path: string; type: string }[];
  };
  const wanted = (path: string) =>
    /\.tex$/i.test(path) && !path.startsWith("_calkit/");
  const paths = entities
    .filter((e) => e.type === "doc")
    .map((e) => e.path.replace(/^\//, ""))
    .filter(wanted);
  const ids = await getDocIds();
  if (paths.every((p) => ids.get(p))) {
    const texts = await Promise.all(
      paths.map(async (p) => {
        const doc = await fetch(
          `/project/${projectId}/doc/${ids.get(p)}/download`,
        );
        if (!doc.ok) {
          throw new Error(`Couldn't read ${p} (${doc.status})`);
        }
        return [p, await doc.text()] as const;
      }),
    );
    return new Map(texts);
  }
  const zip = await fetch(`/project/${projectId}/download/zip`);
  if (!zip.ok) {
    throw new Error(`Couldn't download the project (${zip.status})`);
  }
  return getZipTexts(await zip.arrayBuffer(), wanted);
}

/**
 * The IDs of the project's documents, by their paths, from Overleaf's file
 * tree, or else those the tree shows, which leaves out closed folders.
 */
async function getDocIds(): Promise<Map<string, string>> {
  const tree = await getOverleafTree();
  if (tree) {
    return new Map(tree.docs.map((doc) => [doc.path, doc.id]));
  }
  const ids = new Map<string, string>();
  for (const node of document.querySelectorAll<HTMLElement>(
    '[data-file-type="doc"][data-file-id]',
  )) {
    const parts: string[] = [];
    let item = node.closest('[role="treeitem"]');
    while (item) {
      parts.unshift(item.getAttribute("aria-label") ?? "");
      item = item.parentElement?.closest('[role="treeitem"]') ?? null;
    }
    ids.set(parts.join("/"), node.dataset.fileId ?? "");
  }
  return ids;
}

/**
 * The comments made on Overleaf, by the file each is in, and their
 * threads. A file the tree doesn't show is found by the comments' text
 * being where they say.
 */
async function getOverleafComments(
  projectId: string,
  texts: Map<string, string>,
): Promise<{
  byFile: Map<string, OverleafComment[]>;
  threads: Record<string, OverleafThread>;
}> {
  const read = async <T>(path: string): Promise<T> => {
    const response = await fetch(`/project/${projectId}/${path}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`Couldn't read Overleaf's comments (${response.status})`);
    }
    return response.json();
  };
  const [ranges, threads] = await Promise.all([
    read<
      {
        id: string;
        ranges?: { comments?: { op: { c: string; p: number; t: string } }[] };
      }[]
    >("ranges"),
    read<Record<string, OverleafThread>>("threads"),
  ]);
  const paths = new Map(
    [...(await getDocIds())].map(([path, id]) => [id, path]),
  );
  const byFile = new Map<string, OverleafComment[]>();
  for (const doc of ranges) {
    const comments = (doc.ranges?.comments ?? []).map(({ op }) => ({
      thread: op.t,
      text: op.c,
      offset: op.p,
    }));
    if (!comments.length) {
      continue;
    }
    const path =
      paths.get(doc.id) ??
      [...texts].find(([, text]) =>
        comments.every(
          (c) => text.slice(c.offset, c.offset + c.text.length) === c.text,
        ),
      )?.[0];
    if (path) {
      byFile.set(path, comments);
    }
  }
  return { byFile, threads };
}

/** Delete a comment thread on Overleaf, as its review panel does. */
async function deleteOverleafThread(
  projectId: string,
  docId: string,
  thread: string,
): Promise<void> {
  const response = await fetch(
    `/project/${projectId}/doc/${docId}/thread/${thread}`,
    {
      method: "DELETE",
      headers: {
        Accept: "application/json",
        "X-Csrf-Token":
          document.querySelector<HTMLMetaElement>('meta[name="ol-csrfToken"]')
            ?.content ?? "",
      },
    },
  );
  // Already gone is as good as deleted
  if (!response.ok && response.status !== 404) {
    throw new Error(
      `Overleaf didn't delete the comment thread (${response.status})`,
    );
  }
}

/** How each Overleaf thread was when last in step, by Overleaf project. */
const OVERLEAF_SYNCED_KEY = "overleafCommentsSynced";

/**
 * Bring the open file's Overleaf comments into its source, through the
 * editor, and remember how each thread now is. Only the open one, so
 * someone's file isn't switched under them; each catches up when opened.
 * Says whether the source changed.
 */
async function syncOverleafComments(
  projectId: string,
  file: string,
  sources: { current: Map<string, string> },
): Promise<boolean> {
  const { byFile, threads } = await getOverleafComments(
    projectId,
    sources.current,
  );
  const lines = (sources.current.get(file) ?? "").split("\n");
  const comments = byFile.get(file) ?? [];
  if (!comments.length && !lines.some((l) => /overleaf=/.test(l))) {
    return false;
  }
  const getStored = async () =>
    ((await chrome.storage.local.get(OVERLEAF_SYNCED_KEY))[
      OVERLEAF_SYNCED_KEY
    ] ?? {}) as Record<string, Record<string, OverleafSynced>>;
  const known = (await getStored())[projectId] ?? {};
  const {
    lines: next,
    pushes,
    synced,
  } = getOverleafSyncedLines(
    lines,
    comments,
    threads,
    known,
    getCommentAuthor().name,
  );
  const docId = (await getDocIds()).get(file);
  const csrf =
    document.querySelector<HTMLMetaElement>('meta[name="ol-csrfToken"]')
      ?.content ?? "";
  const post = async (path: string, body?: object) => {
    const response = await fetch(`/project/${projectId}/${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-Csrf-Token": csrf,
      },
      body: JSON.stringify(body ?? {}),
    });
    if (!response.ok) {
      throw new Error(
        `Overleaf didn't take a change to a comment (${response.status})`,
      );
    }
  };
  // The source first, which fails if it was edited meanwhile, before
  // Overleaf is told anything, so nothing's sent twice
  const changed = next.join("\n") !== lines.join("\n");
  if (changed) {
    // Read again after the waits above, in case a thread went in meanwhile
    if (openDocPath() !== file || (await readEditor()) !== lines.join("\n")) {
      throw new Error("The source changed. Try again.");
    }
    // Only what changed, so the rest of the file is left as it is
    let prefix = 0;
    while (
      prefix < lines.length &&
      prefix < next.length &&
      lines[prefix] === next[prefix]
    ) {
      prefix++;
    }
    let suffix = 0;
    while (
      suffix < lines.length - prefix &&
      suffix < next.length - prefix &&
      lines[lines.length - 1 - suffix] === next[next.length - 1 - suffix]
    ) {
      suffix++;
    }
    await editEditor(
      {
        line: prefix + 1,
        count: lines.length - prefix - suffix,
        insert: next.slice(prefix, next.length - suffix),
      },
      lines,
    );
    sources.current.set(file, next.join("\n"));
  }
  // This file's threads replace what was known of them, those Overleaf
  // has yet to hear about from here aside, so they're sent again next time
  const here = new Set([
    ...comments.map((c) => c.thread),
    ...getReviewThreads(new Map([[file, lines.join("\n")]])).flatMap((t) =>
      t.overleaf ? [t.overleaf] : [],
    ),
  ]);
  // Read again each time, so what another tab saved meanwhile is kept
  const save = async (state: Record<string, OverleafSynced>) => {
    const stored = await getStored();
    const kept = Object.fromEntries(
      Object.entries(stored[projectId] ?? {}).filter(([id]) => !here.has(id)),
    );
    await chrome.storage.local.set({
      [OVERLEAF_SYNCED_KEY]: { ...stored, [projectId]: { ...kept, ...state } },
    });
  };
  const unsent = new Set(pushes.map((p) => p.thread));
  const done = Object.fromEntries(
    Object.entries(synced).filter(([id]) => !unsent.has(id)),
  );
  const pending = Object.fromEntries(
    [...unsent].filter((id) => known[id]).map((id) => [id, known[id]]),
  );
  await save({ ...pending, ...done });
  for (const push of pushes) {
    // Without its document's ID, Overleaf can't be told, so it's left to
    // be sent next time
    if ((push.deleted || push.resolved !== undefined) && !docId) {
      continue;
    }
    if (push.deleted) {
      await deleteOverleafThread(projectId, docId as string, push.thread);
    } else {
      for (const content of push.replies) {
        await post(`thread/${push.thread}/messages`, { content });
      }
      if (push.resolved !== undefined) {
        await post(
          `doc/${docId}/thread/${push.thread}/${
            push.resolved ? "resolve" : "reopen"
          }`,
        );
      }
    }
    delete pending[push.thread];
    if (synced[push.thread]) {
      done[push.thread] = synced[push.thread];
    }
    await save({ ...pending, ...done });
  }
  return changed;
}

// The file whose Overleaf comments were last brought into its source
let overleafSyncedFile: string | null = null;
// The refresh of the viewer's threads under way, which the next waits for
let reviewRefresh: Promise<void> = Promise.resolve();

/** The address of the viewer with comments, for this page. */
function getReviewUrl(params: URLSearchParams): string {
  const all = new URLSearchParams(params);
  all.set("parent", window.location.origin);
  // Overleaf's own PDF toolbar and backdrop, whichever theme is on
  const toolbar = document.querySelector(".toolbar-pdf");
  const pane = toolbar?.closest(".pdf");
  if (toolbar) {
    all.set("bar", getComputedStyle(toolbar).backgroundColor);
    all.set("barText", getComputedStyle(toolbar).color);
  }
  if (pane) {
    all.set("backdrop", getComputedStyle(pane).backgroundColor);
  }
  // The panel's, from the variables Overleaf's own themed panels use
  const theme = getComputedStyle(document.body);
  for (const [param, name] of [
    ["bg", "--bg-primary-themed"],
    ["fg", "--content-primary-themed"],
    ["muted", "--content-placeholder-themed"],
    ["border", "--bg-tertiary-themed"],
    ["raised", "--bg-secondary-themed"],
    ["raisedHover", "--bg-tertiary-themed"],
  ]) {
    const color = theme.getPropertyValue(name).trim();
    if (color) {
      all.set(param, color);
    }
  }
  all.set(
    "key",
    `${currentProjectId}:${all.has("localProject") ? "local" : "overleaf"}`,
  );
  return `${chrome.runtime.getURL("review.html")}?${all}`;
}

function postToReview(
  message: Without<ToReview>,
  transfer: Transferable[] = [],
): void {
  if (!review || !isExtensionAlive()) {
    return;
  }
  review.frame.contentWindow?.postMessage(
    { calkit: "review", ...message },
    new URL(chrome.runtime.getURL("")).origin,
    transfer,
  );
}

/** Show Overleaf's PDF in the viewer with comments, over its own. */
function showOverleafReview(): void {
  if (review && !review.local && review.host.isConnected) {
    return;
  }
  hideOverleafReview();
  const pane = getPdfPane();
  if (!pane || localPdf) {
    return;
  }
  const frame = el("iframe", {
    title: "PDF with comments",
    style: { flex: "1", width: "100%", border: "none", background: "#fff" },
  });
  frame.src = getReviewUrl(new URLSearchParams());
  const host = el("div", {}, [frame]);
  Object.assign(host.style, {
    display: "flex",
    flexDirection: "column",
    background: "#fff",
    position: "absolute",
    inset: "0",
    zIndex: "20",
  });
  if (getComputedStyle(pane).position === "static") {
    pane.style.position = "relative";
  }
  pane.append(host);
  review = { frame, host, local: false, ready: false, buildId: null };
}

function hideOverleafReview(): void {
  if (review && !review.local) {
    review.host.remove();
    review = null;
  }
}

/** Send the viewer Overleaf's latest PDF, if it hasn't got it. */
async function sendOverleafPdf(): Promise<void> {
  const r = review;
  const build = pdfBuild;
  if (!r?.ready || r.local || !build || r.buildId === build.buildId) {
    return;
  }
  const link = document.querySelector<HTMLAnchorElement>(
    'a[href*="/build/"][href*="output.pdf"]',
  );
  if (!link) {
    return;
  }
  r.buildId = build.buildId;
  try {
    const response = await fetch(link.href);
    if (!response.ok) {
      throw new Error(`Couldn't get the PDF (${response.status})`);
    }
    const data = await response.arrayBuffer();
    if (review !== r) {
      return;
    }
    postToReview({ type: "load", data }, [data]);
    postToReview({ type: "boxes", boxes: pdfBoxes });
    await refreshReviewThreads(true);
  } catch (e) {
    r.buildId = null;
    postToReview({
      type: "status",
      text: e instanceof Error ? e.message : String(e),
    });
  }
}

/** Where a box Overleaf's SyncTeX gives is, as the viewer measures. */
function toPdfRect(box: SynctexBox): PdfRect {
  return {
    page: box.page,
    x: box.h,
    y: box.v - box.height,
    width: box.width,
    height: box.height,
  };
}

/**
 * Send the viewer the threads in the source, with where each is in
 * Overleaf's PDF. The project's files are read again for a new build, and
 * otherwise only the open one, from the editor.
 */
async function refreshReviewThreads(full: boolean): Promise<void> {
  // One at a time, so two can't bring the same comment into the source
  const previous = reviewRefresh;
  let finish: () => void = () => undefined;
  reviewRefresh = new Promise<void>((resolve) => (finish = resolve));
  await previous;
  const r = review;
  const projectId = currentProjectId;
  if (!r?.ready || !projectId) {
    finish();
    return;
  }
  try {
    let sources = reviewSources;
    const buildId = r.local ? null : pdfBuild?.buildId ?? null;
    if (full || !sources) {
      const texts = await getOverleafTexts(projectId);
      sources = {
        buildId,
        // What a build was made from is read once, when it's new
        built:
          sources && sources.buildId === buildId
            ? sources.built
            : new Map(texts),
        current: texts,
      };
      reviewSources = sources;
    }
    const file = openDocPath();
    const live = file && sources.current.has(file) ? await readEditor() : null;
    if (file && live !== null) {
      sources.current.set(file, live);
      // Overleaf's comments are asked for with a new build, or a file just
      // opened, not on every edit
      if (full || overleafSyncedFile !== file) {
        overleafSyncedFile = file;
        try {
          await syncOverleafComments(projectId, file, sources);
        } catch (e) {
          // Tried again with the next refresh
          overleafSyncedFile = null;
          postToReview({
            type: "status",
            text: e instanceof Error ? e.message : String(e),
          });
        }
      }
    }
    const threads = getReviewThreads(sources.current);
    const build = pdfBuild;
    const synctexUsed = !r.local && Boolean(build);
    if (build && !r.local) {
      const { built, current } = sources;
      await Promise.all(
        threads.map(async (t) => {
          if (!t.anchor) {
            return;
          }
          const map = lineMap(
            (built.get(t.path) ?? "").split("\n"),
            (current.get(t.path) ?? "").split("\n"),
          );
          const [start] = await synctex(
            projectId,
            build,
            t.path,
            map.toBefore(t.anchor.line),
            0,
          );
          const ends = await synctex(
            projectId,
            build,
            t.path,
            map.toBefore(t.anchor.end_line),
            0,
          );
          if (start) {
            t.start = toPdfRect(start);
          }
          if (ends.length) {
            t.end = toPdfRect(ends[ends.length - 1]);
          }
        }),
      );
    }
    if (review === r) {
      postToReview({
        type: "threads",
        threads,
        synctex: synctexUsed,
        stale: [],
      });
    }
  } catch (e) {
    postToReview({
      type: "status",
      text: `Couldn't read the comments: ${e instanceof Error ? e.message : e}`,
    });
  } finally {
    finish();
  }
}

let reviewTimer: ReturnType<typeof setTimeout> | undefined;
export function scheduleReviewThreads(): void {
  if (!review?.ready) {
    return;
  }
  clearTimeout(reviewTimer);
  reviewTimer = setTimeout(() => void refreshReviewThreads(false), 800);
}

/**
 * The source file and line at a place in the PDF: by SyncTeX for
 * Overleaf's, else the paragraph sharing the most words with the text
 * there, as a line in the source now. With ``withStart``, also where its
 * paragraph starts in the PDF, which takes Overleaf another lookup.
 */
async function getSourceAt(
  page: number,
  x: number,
  y: number,
  context: string,
  withStart = false,
  localSynctex?: { input: string; line: number },
): Promise<{
  file: string;
  line: number;
  start?: PdfRect;
  text?: string;
} | null> {
  const projectId = currentProjectId;
  const sources = reviewSources;
  const build = pdfBuild;
  if (!projectId || !sources) {
    return null;
  }
  if (review && !review.local && build) {
    const params = new URLSearchParams({
      page: String(page),
      h: String(x),
      v: String(y),
    });
    setBuildParams(params, build);
    const response = await fetch(`/project/${projectId}/sync/pdf?${params}`, {
      headers: { Accept: "application/json" },
    });
    const data = response.ok
      ? ((await response.json()) as { code?: { file: string; line: number }[] })
      : {};
    // Named as the build found it, e.g., "./sections/intro.tex"
    const found = data.code
      ?.map((c) => ({ ...c, file: c.file.replace(/^(\.\/)+/, "") }))
      .find((c) => sources.current.has(c.file));
    if (found) {
      const map = lineMap(
        (sources.built.get(found.file) ?? "").split("\n"),
        (sources.current.get(found.file) ?? "").split("\n"),
      );
      const line = map.toAfter(found.line);
      if (!withStart) {
        return { file: found.file, line };
      }
      const lines = (sources.current.get(found.file) ?? "").split("\n");
      const para = paragraphLines(lines, line);
      const [box] = await synctex(
        projectId,
        build,
        found.file,
        map.toBefore(para.start),
        0,
      );
      return { file: found.file, line, start: box && toPdfRect(box) };
    }
  }
  // A PDF built on this machine was made from the project's copy of the
  // files Overleaf has, so they're matched by their trailing paths
  if (review?.local && localSynctex) {
    const file = synctexInputFile(localSynctex.input, (f) =>
      sources.current.has(f),
    );
    if (file && localPdf) {
      // Mapped from this machine's copy to Overleaf's, which may have
      // more, e.g., comments not synced here yet
      const link = localPdf.link;
      const built = await send({
        type: "local.publicationSource",
        project: `${link.project_owner_name}/${link.project_name}`,
        folder: localPdf.path,
        path: file,
      }).catch(() => null);
      const line = built
        ? lineMap(
            built.text.split("\n"),
            (sources.current.get(file) ?? "").split("\n"),
          ).toAfter(localSynctex.line)
        : localSynctex.line;
      return { file, line };
    }
  }
  const para = findParagraphByText(sources.current, context);
  return para && { file: para.file, line: para.line, text: para.text };
}

/**
 * Edit a file through Overleaf's editor, opening it first, so the change
 * is saved and shared like any other.
 */
async function editSource(
  file: string,
  getEdit: (lines: string[]) => LineEdit,
): Promise<LineEdit> {
  if (!(await openDocument(file))) {
    throw new Error(`Couldn't open ${file} in the editor.`);
  }
  const text = await readEditor();
  if (text === null) {
    throw new Error(`Couldn't read ${file} from the editor.`);
  }
  const lines = text.split("\n");
  const edit = getEdit(lines);
  await editEditor(edit, lines);
  reviewSources?.current.set(file, getEditedLines(lines, edit).join("\n"));
  return edit;
}

/**
 * Add a thread from the source to Overleaf's comments through Overleaf's
 * own comment form, since a comment's place in the text can only be set by
 * its editor: its text is selected, the form opened, and its first message
 * put in and sent. The next sync links the two.
 */
async function postToOverleaf(
  file: string,
  ref: { id?: string; line?: number },
  me: string,
): Promise<void> {
  const sleep = (ms: number) =>
    new Promise((resolve) => setTimeout(resolve, ms));
  if (!(await openDocument(file))) {
    throw new Error(`Couldn't open ${file} in the editor.`);
  }
  const text = (await readEditor()) ?? "";
  const lines = text.split("\n");
  const thread = getReviewThreads(new Map([[file, text]])).find((t) =>
    ref.id
      ? t.id === ref.id
      : ref.line !== undefined &&
        ref.line >= t.line &&
        ref.line < t.line + t.nlines,
  );
  if (!thread?.anchor || !thread.messages.length) {
    throw new Error("That comment thread is no longer in the source.");
  }
  if (thread.overleaf) {
    return;
  }
  // Its highlight where it is in the paragraph, else the paragraph's start
  const { anchor, highlight } = thread;
  let found: { line: number; start: number; end: number } | undefined;
  for (let n = anchor.line; highlight && !found && n <= anchor.end_line; n++) {
    found = findInSource(lines, n, highlight.text);
  }
  toEditor({
    type: "select",
    from: found
      ? { line: found.line, column: found.start }
      : { line: anchor.line, column: 0 },
    to: found
      ? { line: found.line, column: found.end }
      : { line: anchor.line, column: lines[anchor.line - 1]?.length ?? 0 },
  });
  await sleep(300);
  // Overleaf opens its review panel for the form, which the viewer with
  // comments already shows, so it's put back as it was after
  const getRailTab = () =>
    document.querySelector<HTMLElement>(".ide-rail-tab-link.active");
  const railBefore = getRailTab();
  const railWasClosed =
    (document.querySelector(".ide-rail-tab-content")?.getBoundingClientRect()
      .width ?? 0) < 20;
  try {
    window.dispatchEvent(new Event("add-new-review-comment"));
    // Overleaf's comment box is a small editor of its own, out of sight
    let box: HTMLElement | null = null;
    for (let i = 0; i < 30 && !box; i++) {
      await sleep(100);
      box =
        document
          .querySelector(".review-panel-add-comment-editor")
          ?.shadowRoot?.querySelector<HTMLElement>(".cm-content") ?? null;
    }
    if (!box) {
      throw new Error("Overleaf's comment form didn't open.");
    }
    const [first] = thread.messages;
    // Pasted into that box, since typing commands go to whatever editor the
    // page thinks has focus, which can be the document's
    const data = new DataTransfer();
    data.setData(
      "text/plain",
      first.author === me ? first.text : `${first.author}: ${first.text}`,
    );
    box.focus();
    box.dispatchEvent(
      new ClipboardEvent("paste", {
        clipboardData: data,
        bubbles: true,
        cancelable: true,
      }),
    );
    const root = box.getRootNode() as ShadowRoot;
    const button = root.host
      ?.closest("form")
      ?.querySelector<HTMLButtonElement>('button[type="submit"]');
    for (let i = 0; i < 20 && button?.disabled; i++) {
      await sleep(100);
    }
    if (!button || button.disabled) {
      throw new Error("Couldn't fill in Overleaf's comment form.");
    }
    button.click();
    // Time for Overleaf to save it before it's linked
    await sleep(1500);
  } finally {
    const railAfter = getRailTab();
    if (railAfter && railAfter.id !== RAIL_TAB_ID) {
      if (railWasClosed || !railBefore) {
        // Clicking the open tab closes the panel
        railAfter.click();
      } else if (railBefore !== railAfter) {
        railBefore.click();
      }
    }
  }
}

// Which go to source is the latest
let sourceAtSeq = 0;

/** Do what the viewer with comments asks. */
async function onReviewMessage(message: FromReview): Promise<void> {
  const r = review;
  if (!r) {
    return;
  }
  const author = getCommentAuthor();
  const ref = (m: { id?: string; line?: number }) =>
    m.id ? { id: m.id } : { line: m.line };
  try {
    switch (message.type) {
      case "ready":
        r.ready = true;
        r.buildId = null;
        if (r.local) {
          await refreshReviewThreads(true);
        } else {
          await sendOverleafPdf();
        }
        return;
      case "locate": {
        // Always answered, without a source if it can't be found, since
        // the viewer waits on it
        const found = await getSourceAt(
          message.page,
          message.x,
          message.y,
          message.context,
          true,
        ).catch(() => null);
        postToReview({ type: "located", reqId: message.reqId, ...found });
        return;
      }
      case "sourceAt":
      case "openSource": {
        // Overleaf takes a second or more to say, so only the last asked
        // for is gone to, not whichever's answered last
        const seq = ++sourceAtSeq;
        const found =
          message.type === "openSource"
            ? { file: message.file, line: message.line }
            : await getSourceAt(
                message.page,
                message.x,
                message.y,
                message.context,
                false,
                message.synctex,
              );
        if (seq !== sourceAtSeq) {
          return;
        }
        if (!found || !(await openDocument(found.file))) {
          postToReview({ type: "status", text: "No source found there." });
          return;
        }
        if (seq !== sourceAtSeq) {
          return;
        }
        toEditor({ type: "goto", line: found.line, column: 0 });
        return;
      }
      case "add": {
        const edit = await editSource(message.file, (lines) =>
          getAddEdit(
            lines,
            message.line,
            author,
            message.text,
            message.highlight,
            message.occ,
          ),
        );
        // In the list now, rather than once it's on Overleaf too
        await refreshReviewThreads(false);
        postToReview({ type: "sent", reqId: message.reqId, ok: true });
        // On Overleaf too, so it's in its review panel, kept in step
        const id = /\bid=([0-9a-f]{8})\b/.exec(edit.insert[0])?.[1];
        if (id) {
          try {
            await postToOverleaf(message.file, { id }, author.name);
          } catch (e) {
            postToReview({
              type: "status",
              text: `Saved in the source, but not on Overleaf: ${
                e instanceof Error ? e.message : e
              }`,
            });
            overleafSyncedFile = null;
            await refreshReviewThreads(false);
            return;
          }
        }
        break;
      }
      case "reply":
        await editSource(message.file, (lines) =>
          getThreadEdit(lines, ref(message), getReply(author, message.text)),
        );
        break;
      case "resolve":
        await editSource(message.file, (lines) =>
          getThreadEdit(lines, ref(message), (t) => ({
            ...t,
            resolved: message.resolved,
          })),
        );
        break;
      case "delete": {
        // One kept in step with Overleaf goes there too, first, or the
        // next sync would bring it back
        const thread = getReviewThreads(
          new Map([
            [message.file, reviewSources?.current.get(message.file) ?? ""],
          ]),
        ).find((t) =>
          message.id
            ? t.id === message.id
            : message.line !== undefined &&
              message.line >= t.line &&
              message.line < t.line + t.nlines,
        );
        const docId = (await getDocIds()).get(message.file);
        if (thread?.overleaf && currentProjectId) {
          if (!docId) {
            throw new Error(
              `Open ${message.file} in Overleaf to delete its comment there.`,
            );
          }
          await deleteOverleafThread(currentProjectId, docId, thread.overleaf);
        }
        await editSource(message.file, (lines) =>
          getThreadEdit(lines, ref(message), null),
        );
        break;
      }
      case "goto":
        toEditor({ type: "goto", line: message.line, column: message.column });
        return;
      case "pointer": {
        // Its place on this page, over the viewer
        const frame = r.frame.getBoundingClientRect();
        const point = message.point;
        pdfPointer(
          point
            ? {
                page: point.page,
                h: point.x,
                v: point.y,
                clientX: frame.left + point.clientX,
                clientY: frame.top + point.clientY,
              }
            : null,
        );
        return;
      }
      case "postToOverleaf":
        await postToOverleaf(message.file, ref(message), author.name);
        break;
      case "openIssue":
        if (/^https?:\/\//.test(message.url)) {
          window.open(message.url, "_blank", "noopener");
        }
        return;
    }
    postToReview({ type: "status", text: "" });
    // So a change to a thread kept in step with Overleaf goes there now
    overleafSyncedFile = null;
    await refreshReviewThreads(false);
    // Only now, once a posted thread's link to Overleaf is in the source
    if (message.type === "reply" || message.type === "postToOverleaf") {
      postToReview({ type: "sent", reqId: message.reqId, ok: true });
    }
  } catch (e) {
    postToReview({
      type: "status",
      text: e instanceof Error ? e.message : String(e),
    });
    if (
      message.type === "add" ||
      message.type === "reply" ||
      message.type === "postToOverleaf"
    ) {
      postToReview({ type: "sent", reqId: message.reqId, ok: false });
    }
  }
}

/** Hear from the viewer with comments, and only from it. */
export function watchReview(): void {
  const origin = new URL(chrome.runtime.getURL("")).origin;
  window.addEventListener(
    "message",
    (event) => {
      if (
        !review ||
        event.source !== review.frame.contentWindow ||
        event.origin !== origin ||
        event.data?.calkit !== "review"
      ) {
        return;
      }
      void onReviewMessage(event.data as FromReview);
    },
    { signal: watching.signal },
  );
}

/**
 * A button in Overleaf's PDF toolbar that shows the PDF with the comments
 * in its source, remembered per Overleaf project. Mounted again whenever
 * Overleaf redraws the toolbar.
 */
function mountCommentsToggle(): void {
  // Cut off, the button with its ID may be the next copy's
  if (watching.signal.aborted || !isExtensionAlive()) {
    return;
  }
  const toolbar = document.querySelector<HTMLElement>(".toolbar-pdf-left");
  const existing = document.getElementById("calkit-comments-toggle");
  const projectId = currentProjectId;
  // This machine's PDF always has them, so it's only for Overleaf's
  if (!toolbar || !projectId || localPdf) {
    existing?.remove();
    return;
  }
  // Redrawn by Overleaf, so shown again where it now is
  if (commentsOn && !review?.host.isConnected) {
    review = null;
    showOverleafReview();
  }
  if (
    existing?.parentElement === toolbar &&
    existing.dataset.on === `${commentsOn}` &&
    existing.dataset.project === projectId
  ) {
    return;
  }
  const first = !existing || existing.dataset.project !== projectId;
  existing?.remove();
  const set = (on: boolean) => {
    commentsOn = on;
    void chrome.storage.local.get(COMMENTS_KEY).then((stored) => {
      const all: Record<string, boolean> = stored[COMMENTS_KEY] ?? {};
      all[projectId] = on;
      void chrome.storage.local.set({ [COMMENTS_KEY]: all });
    });
    if (on) {
      showOverleafReview();
    } else {
      hideOverleafReview();
    }
    mountCommentsToggle();
  };
  const button = el("button", {
    text: "Comments",
    title: commentsOn ? "Hide comments" : "Show PDF with comments",
    attrs: {
      id: "calkit-comments-toggle",
      "aria-pressed": String(commentsOn),
    },
    style: {
      marginLeft: "8px",
      border: "none",
      padding: "2px 10px",
      borderRadius: "999px",
      cursor: "pointer",
      font: "inherit",
      fontSize: "12px",
      whiteSpace: "nowrap",
      background: commentsOn ? "#009688" : "rgba(127, 127, 127, 0.18)",
      color: commentsOn ? "#fff" : "inherit",
    },
    onClick: () => set(!commentsOn),
  });
  button.dataset.on = `${commentsOn}`;
  button.dataset.project = projectId;
  toolbar.append(button);
  // The last choice for this project applies when it's opened
  if (first) {
    void chrome.storage.local.get(COMMENTS_KEY).then((stored) => {
      if ((stored[COMMENTS_KEY] ?? {})[projectId] && !commentsOn) {
        set(true);
      }
    });
  }
}

/** The pane Overleaf shows its PDF in, around pdf.js's pages. */
function getPdfPane(): HTMLElement | null {
  const viewer = document.querySelector<HTMLElement>(".pdfViewer");
  return (
    viewer?.closest<HTMLElement>(".pdf-viewer, .pdfjs-viewer, .pdf") ??
    viewer?.parentElement ??
    null
  );
}

/** Keep the PDF switch in the toolbar as Overleaf redraws it. */
export function watchPdfSwitch(): void {
  observePage(() => {
    mountPdfSwitch();
    mountCommentsToggle();
  }, 200);
}

/** Which PDF someone last chose for an Overleaf project, by its ID. */
const PDF_SOURCE_KEY = "pdfSources";

/**
 * A switch in Overleaf's PDF toolbar between its PDF and the one built on
 * this machine, for a project checked out here, remembered per Overleaf
 * project. Mounted again whenever Overleaf redraws the toolbar.
 */
export function mountPdfSwitch(): void {
  const check = lastCheck;
  // Beside Recompile, the logs, and download
  const toolbar = document.querySelector<HTMLElement>(".toolbar-pdf-left");
  const existing = document.getElementById("calkit-pdf-switch");
  // Cut off, the switch with its ID may be the next copy's
  if (watching.signal.aborted || !isExtensionAlive()) {
    return;
  }
  if (!check?.link.local_path || !toolbar) {
    existing?.remove();
    return;
  }
  // Redrawn by Overleaf, so shown again where it now is
  if (localPdf && !localPdf.host.isConnected) {
    showLocalPdf(localPdf.link, localPdf.path);
    return;
  }
  const local = Boolean(localPdf);
  const edits = check.status.commits_from_overleaf;
  if (
    existing?.parentElement === toolbar &&
    existing.dataset.local === `${local}` &&
    existing.dataset.edits === `${edits}`
  ) {
    return;
  }
  existing?.remove();
  const choose = (useLocal: boolean) => {
    void chrome.storage.local.get(PDF_SOURCE_KEY).then((stored) => {
      const sources: Record<string, string> = stored[PDF_SOURCE_KEY] ?? {};
      sources[check.overleafProjectId] = useLocal ? "local" : "overleaf";
      void chrome.storage.local.set({ [PDF_SOURCE_KEY]: sources });
    });
    if (useLocal) {
      showLocalPdf(check.link, check.status.path);
    } else {
      hideLocalPdf();
    }
  };
  const option = (text: string, useLocal: boolean) =>
    el("button", {
      text,
      title: useLocal
        ? "The PDF the pipeline built on this machine, without waiting " +
          "on Overleaf to compile" +
          (edits
            ? `, without ${edits} edit${
                edits === 1 ? "" : "s"
              } made on Overleaf since the last sync`
            : "")
        : "Overleaf's own PDF",
      style: {
        border: "none",
        padding: "2px 8px",
        borderRadius: "999px",
        cursor: "pointer",
        font: "inherit",
        fontSize: "12px",
        whiteSpace: "nowrap",
        background: useLocal === local ? "#009688" : "transparent",
        color: useLocal === local ? "#fff" : "inherit",
      },
      onClick: () => {
        if (useLocal !== local) {
          choose(useLocal);
        }
      },
    });
  const toggle = el(
    "div",
    {
      attrs: { id: "calkit-pdf-switch", title: "Which PDF to show" },
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: "2px",
        marginLeft: "8px",
        padding: "2px",
        borderRadius: "999px",
        background: "rgba(127, 127, 127, 0.18)",
      },
    },
    [option("Overleaf", false), option("This machine", true)],
  );
  toggle.dataset.local = `${local}`;
  toggle.dataset.edits = `${edits}`;
  // Before Comments, whichever was put back last
  const comments = document.getElementById("calkit-comments-toggle");
  if (comments?.parentElement === toolbar) {
    toolbar.insertBefore(toggle, comments);
  } else {
    toolbar.append(toggle);
  }
  // The first time it's shown for this project, the last choice applies
  if (!existing) {
    void chrome.storage.local.get(PDF_SOURCE_KEY).then((stored) => {
      const source = (stored[PDF_SOURCE_KEY] ?? {})[check.overleafProjectId];
      if (source === "local" && !localPdf && lastCheck === check) {
        showLocalPdf(check.link, check.status.path);
      }
    });
  }
}

/** Remove the local PDF and review pane, and stop refreshing review. */
export function removePdfViewer(): void {
  clearTimeout(reviewTimer);
  localPdf?.host.remove();
  localPdf = null;
  review?.host.remove();
  review = null;
}
