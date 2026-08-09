type Child = Node | string | null | undefined | false;

interface ElementOptions {
  class?: string;
  text?: string;
  html?: string;
  title?: string;
  href?: string;
  type?: string;
  value?: string;
  placeholder?: string;
  disabled?: boolean;
  onClick?: (event: MouseEvent) => void;
  style?: Partial<CSSStyleDeclaration>;
  attrs?: Record<string, string>;
}

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  options: ElementOptions = {},
  children: Child[] = [],
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (options.class) node.className = options.class;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.html !== undefined) node.innerHTML = options.html;
  if (options.title) node.title = options.title;
  if (options.href && node instanceof HTMLAnchorElement) {
    node.href = options.href;
    node.target = "_blank";
    node.rel = "noreferrer noopener";
  }
  if (
    options.type &&
    (node instanceof HTMLInputElement || node instanceof HTMLButtonElement)
  ) {
    node.type = options.type;
  }
  if (
    options.value !== undefined &&
    (node instanceof HTMLInputElement ||
      node instanceof HTMLTextAreaElement ||
      node instanceof HTMLSelectElement ||
      // An option left out here silently falls back to its own text as its
      // value, so a select reports its visible label instead of the value
      // the caller set
      node instanceof HTMLOptionElement)
  ) {
    node.value = options.value;
  }
  if (
    options.placeholder &&
    (node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement)
  ) {
    node.placeholder = options.placeholder;
  }
  if (options.disabled !== undefined && "disabled" in node) {
    (node as HTMLButtonElement).disabled = options.disabled;
  }
  if (options.onClick) {
    node.addEventListener("click", options.onClick as EventListener);
  }
  if (options.style) Object.assign(node.style, options.style);
  for (const [name, value] of Object.entries(options.attrs ?? {})) {
    node.setAttribute(name, value);
  }
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child);
  }
  return node;
}

/**
 * A file icon matching the one GitHub puts beside a filename.
 *
 * Rows injected into their listing are clones of a real row, and whatever
 * icon the cloned row carried is either the wrong one (a directory) or
 * gone. Without one, the filename starts where everyone else's icon does
 * and the column reads as ragged.
 */
export function fileIcon(): SVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute(
    "d",
    "M2 1.75C2 .784 2.784 0 3.75 0h6.586c.464 0 .909.184 1.237.513l2.914 " +
      "2.914c.329.328.513.773.513 1.237v9.586A1.75 1.75 0 0 1 13.25 16h-9.5A" +
      "1.75 1.75 0 0 1 2 14.25Zm1.75-.25a.25.25 0 0 0-.25.25v12.5c0 .138.112" +
      ".25.25.25h9.5a.25.25 0 0 0 .25-.25V6h-2.75A1.75 1.75 0 0 1 9 4.25V1.5" +
      "Zm6.75.062V4.25c0 .138.112.25.25.25h2.688l-.011-.013-2.914-2.914-.013" +
      "-.011Z",
  );
  svg.append(path);
  Object.assign(svg.style, {
    // GitHub's own icon colour and spacing, so the column lines up
    color: "var(--fgColor-muted, #59636e)",
    fill: "currentColor",
    marginRight: "8px",
    verticalAlign: "text-bottom",
    flex: "0 0 auto",
  });
  return svg;
}

export function clear(node: HTMLElement): HTMLElement {
  node.replaceChildren();
  return node;
}

/** Colors and spacing shared by the panels, matching the Calkit web app. */
export const STYLES = `
:host {
  /* Isolates from the host page, and takes the page's typography with it:
     what's left is the initial font, which is a serif. Everything in this
     shadow root inherits from here, so it's set once rather than on the
     one container that happened to need it. */
  all: initial;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial,
    sans-serif;
  font-size: 13px;
  line-height: 1.45;
  --ck-main: #009688;
  --ck-main-hover: #00766c;
  --ck-danger: #e53e3e;
  --ck-warning: #d69e2e;
  --ck-success: #48bb78;
  --ck-dim: #718096;
  --ck-border: #e2e8f0;
  --ck-bg: #ffffff;
  --ck-fg: #1a202c;
  --ck-subtle-bg: #f7fafc;
}
@media (prefers-color-scheme: dark) {
  :host {
    --ck-border: #2d3748;
    --ck-bg: #1a202c;
    --ck-fg: #f7fafc;
    --ck-dim: #a0aec0;
    --ck-subtle-bg: #252d3d;
  }
}
* { box-sizing: border-box; }
/* A button doesn't inherit type by default; without this they'd each fall
   back to the browser's own form font */
button { font-family: inherit; font-size: inherit; }
.panel {
  color: var(--ck-fg);
  background: var(--ck-bg);
  border: 1px solid var(--ck-border);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  overflow: hidden;
}
.header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--ck-main);
  color: #ffffff;
  font-weight: 600;
  cursor: move;
  user-select: none;
}
.header .spacer { flex: 1; }
.header button {
  background: transparent;
  border: 0;
  color: #ffffff;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 2px 4px;
  border-radius: 4px;
}
.header button:hover { background: rgba(255, 255, 255, 0.2); }
.body { padding: 10px; max-height: 60vh; overflow-y: auto; }
.row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 0;
  border-bottom: 1px solid var(--ck-border);
}
.row:last-child { border-bottom: 0; }
.row .grow { flex: 1; min-width: 0; }
.name {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.dim { color: var(--ck-dim); }
.small { font-size: 12px; }
.muted-box {
  background: var(--ck-subtle-bg);
  border-radius: 6px;
  padding: 8px;
}
.badge {
  display: inline-block;
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.badge.ok { background: rgba(72, 187, 120, 0.18); color: var(--ck-success); }
.badge.warn { background: rgba(214, 158, 46, 0.18); color: var(--ck-warning); }
.badge.danger { background: rgba(229, 62, 62, 0.18); color: var(--ck-danger); }
.badge.info { background: rgba(0, 150, 136, 0.18); color: var(--ck-main); }
button.action {
  background: var(--ck-main);
  color: #ffffff;
  border: 0;
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
button.action:hover:not(:disabled) { background: var(--ck-main-hover); }
button.action:disabled { opacity: 0.6; cursor: default; }
button.secondary {
  background: transparent;
  color: var(--ck-main);
  border: 1px solid var(--ck-main);
}
button.secondary:hover:not(:disabled) {
  background: rgba(0, 150, 136, 0.12);
}
a { color: var(--ck-main); }
input, select, textarea {
  width: 100%;
  padding: 5px 7px;
  border: 1px solid var(--ck-border);
  border-radius: 6px;
  background: var(--ck-bg);
  color: var(--ck-fg);
  font-size: 12px;
  font-family: inherit;
}
textarea { min-height: 70px; resize: vertical; }
label { display: block; font-size: 11px; font-weight: 600; margin: 6px 0 2px; }
.error { color: var(--ck-danger); }
.stack { display: flex; flex-direction: column; gap: 6px; }
.actions { display: flex; gap: 6px; margin-top: 8px; }
.spinner {
  width: 12px;
  height: 12px;
  border: 2px solid var(--ck-border);
  border-top-color: var(--ck-main);
  border-radius: 50%;
  display: inline-block;
  animation: ck-spin 0.7s linear infinite;
}
@keyframes ck-spin { to { transform: rotate(360deg); } }
.backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.overlay {
  display: flex;
  flex-direction: column;
  width: min(1100px, 100%);
  height: 100%;
  background: var(--ck-bg);
  border-radius: 8px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
  overflow: hidden;
}
.overlay .header { cursor: default; }
.overlay .toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--ck-border);
  background: var(--ck-subtle-bg);
  font-size: 12px;
  color: var(--ck-fg);
  flex-wrap: wrap;
}
.overlay .toolbar .spacer { flex: 1; }
.overlay .viewport {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 1px;
  background: var(--ck-border);
}
.overlay .pane {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--ck-bg);
}
.overlay .pane-label {
  padding: 4px 8px;
  font-size: 11px;
  font-weight: 600;
  color: var(--ck-dim);
  border-bottom: 1px solid var(--ck-border);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.overlay .frame {
  flex: 1;
  min-height: 0;
  border: 0;
  width: 100%;
  background: var(--ck-bg);
}
.diff {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 14px;
  background: var(--ck-bg);
  color: var(--ck-fg);
  font-size: 13px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.diff .equal { color: var(--ck-dim); }
.diff .insert {
  background: rgba(72, 187, 120, 0.22);
  color: var(--ck-fg);
  border-radius: 3px;
  padding: 0 2px;
}
.diff .delete {
  background: rgba(229, 62, 62, 0.2);
  color: var(--ck-fg);
  border-radius: 3px;
  padding: 0 2px;
  text-decoration: line-through;
}
.diff .elided {
  display: block;
  margin: 10px 0;
  border-top: 1px dashed var(--ck-border);
}
button.chip {
  background: var(--ck-bg);
  color: var(--ck-fg);
  border: 1px solid var(--ck-border);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
}
button.chip[aria-pressed="true"] {
  background: var(--ck-main);
  border-color: var(--ck-main);
  color: #ffffff;
  font-weight: 600;
}
`;

export interface Panel {
  host: HTMLElement;
  body: HTMLElement;
  setTitle: (title: string) => void;
  remove: () => void;
}

/**
 * Mount a floating panel in a shadow root, so nothing the host page styles
 * can reach inside it and nothing here leaks out.
 */
export function mountPanel(options: {
  id: string;
  title: string;
  position?: "bottom-right" | "top-right";
  /**
   * Called when the user closes the panel. A surface that has no other
   * way back uses this to put its launcher button up, so closing means
   * "get out of my way", not "never again on this page".
   */
  onClose?: () => void;
}): Panel {
  document.getElementById(options.id)?.remove();
  const host = el("div", { attrs: { id: options.id } });
  Object.assign(host.style, {
    position: "fixed",
    right: "16px",
    [options.position === "top-right" ? "top" : "bottom"]: "16px",
    width: "340px",
    zIndex: "2147483000",
  });
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = STYLES;
  const title = el("span", { text: options.title });
  const body = el("div", { class: "body" });
  const collapse = el("button", { text: "−", title: "Collapse" });
  const close = el("button", { text: "×", title: "Close" });
  const header = el("div", { class: "header" }, [
    title,
    el("span", { class: "spacer" }),
    collapse,
    close,
  ]);
  collapse.addEventListener("click", () => {
    const collapsed = body.style.display === "none";
    body.style.display = collapsed ? "" : "none";
    collapse.textContent = collapsed ? "−" : "+";
  });
  close.addEventListener("click", () => {
    host.remove();
    options.onClose?.();
  });
  makeDraggable(host, header);
  root.append(style, el("div", { class: "panel" }, [header, body]));
  document.body.append(host);
  return {
    host,
    body,
    setTitle: (value: string) => {
      title.textContent = value;
    },
    remove: () => host.remove(),
  };
}

export interface Overlay {
  host: HTMLElement;
  /** A row above the content, for the caller's own controls. */
  toolbar: HTMLElement;
  /** Fills the rest of the card; the caller puts its frames here. */
  viewport: HTMLElement;
  remove: () => void;
}

/**
 * Mount a full-page overlay showing one of the extension's own pages.
 *
 * A big artifact is worth looking at without leaving what you were
 * reading, but a PDF or a notebook can't be rendered into the host page:
 * its content security policy governs any frame a content script injects.
 * An extension page is exempt from that policy, since Chrome treats a
 * web-accessible resource as ours rather than the page's, so the artifact
 * renders in a frame of ours laid over the page.
 */
export function mountOverlay(options: {
  id: string;
  title: string;
  onClose?: () => void;
}): Overlay {
  document.getElementById(options.id)?.remove();
  const host = el("div", { attrs: { id: options.id } });
  Object.assign(host.style, {
    position: "fixed",
    inset: "0",
    zIndex: "2147483001",
  });
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = STYLES;
  const close = el("button", { text: "×", title: "Close" });
  const toolbar = el("div", { class: "toolbar" });
  const viewport = el("div", { class: "viewport" });
  const card = el("div", { class: "overlay" }, [
    el("div", { class: "header" }, [
      el("span", { text: options.title }),
      el("span", { class: "spacer" }),
      close,
    ]),
    toolbar,
    viewport,
  ]);
  const backdrop = el("div", { class: "backdrop" }, [card]);
  const remove = () => {
    host.remove();
    document.removeEventListener("keydown", onKeyDown, true);
  };
  const dismiss = () => {
    remove();
    options.onClose?.();
  };
  function onKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      dismiss();
    }
  }
  close.addEventListener("click", dismiss);
  backdrop.addEventListener("click", (event) => {
    // Only the backdrop itself, so a click inside the card -- or a drag
    // that happens to end on it -- doesn't close what you're reading
    if (event.target === backdrop) {
      dismiss();
    }
  });
  // Captured, since the host page may well stop keydown before it bubbles
  document.addEventListener("keydown", onKeyDown, true);
  root.append(style, backdrop);
  document.body.append(host);
  return { host, toolbar, viewport, remove };
}

function makeDraggable(host: HTMLElement, handle: HTMLElement): void {
  let startX = 0;
  let startY = 0;
  let originLeft = 0;
  let originTop = 0;
  const onMove = (event: MouseEvent) => {
    host.style.left = `${originLeft + event.clientX - startX}px`;
    host.style.top = `${originTop + event.clientY - startY}px`;
  };
  const onUp = () => {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
  };
  handle.addEventListener("mousedown", (event) => {
    // Dragging is anchored from the panel's current spot, so switch from the
    // right/bottom placement it was mounted with to explicit coordinates
    const rect = host.getBoundingClientRect();
    originLeft = rect.left;
    originTop = rect.top;
    startX = event.clientX;
    startY = event.clientY;
    host.style.left = `${originLeft}px`;
    host.style.top = `${originTop}px`;
    host.style.right = "auto";
    host.style.bottom = "auto";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    event.preventDefault();
  });
}

export function loading(text = "Loading"): HTMLElement {
  return el("div", { class: "row" }, [
    el("span", { class: "spinner" }),
    el("span", { class: "dim small", text }),
  ]);
}

export function errorMessage(message: string): HTMLElement {
  return el("div", { class: "error small", text: message });
}

/**
 * A text input that password managers leave alone.
 *
 * None of the fields in these panels hold credentials, so autofill on them
 * is never right. Each manager reads its own opt-out: Dashlane and others
 * follow `data-form-type`, with per-manager attributes for the rest.
 */
export function textInput(options: {
  value?: string;
  placeholder?: string;
}): HTMLInputElement {
  return el("input", {
    type: "text",
    value: options.value,
    placeholder: options.placeholder,
    attrs: {
      autocomplete: "off",
      "data-form-type": "other",
      "data-lpignore": "true",
      "data-1p-ignore": "",
      "data-bwignore": "true",
    },
  });
}

/**
 * Where a floating launcher sits, kept clear of what the site already
 * puts in that corner.
 *
 * The bottom right is prime real estate for feedback widgets and chat
 * bubbles, and landing on top of one hides both. There's no reliable way
 * to detect that, so the sites known to collide are listed instead, which
 * is easy to extend the next time one turns up.
 */
const CORNER_OFFSETS: Record<string, { right: string; bottom: string }> = {
  // Cambridge Core's feedback tab occupies the corner
  "www.cambridge.org": { right: "16px", bottom: "96px" },
};

export function launcherPosition(): { right: string; bottom: string } {
  return (
    CORNER_OFFSETS[window.location.hostname] ?? {
      right: "16px",
      bottom: "16px",
    }
  );
}
