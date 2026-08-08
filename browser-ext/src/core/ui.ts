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

export function clear(node: HTMLElement): HTMLElement {
  node.replaceChildren();
  return node;
}

/** Colors and spacing shared by the panels, matching the Calkit web app. */
export const STYLES = `
:host {
  all: initial;
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
.panel {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial,
    sans-serif;
  font-size: 13px;
  line-height: 1.45;
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
  close.addEventListener("click", () => host.remove());
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

/** A "sign in to Calkit" prompt shown when a panel has no session. */
export function signInPrompt(onSignIn: () => void): HTMLElement {
  return el("div", { class: "stack" }, [
    el("div", {
      class: "dim small",
      text: "Sign in to your Calkit account to use this panel.",
    }),
    el("div", { class: "actions" }, [
      el("button", {
        class: "action",
        text: "Sign in",
        onClick: onSignIn,
      }),
    ]),
  ]);
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
