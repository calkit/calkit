import { getGithubPath, getGithubRepo } from "../core/detect";
import { getHubWebUrl, projectUrl } from "../core/hub-url";
import { runContentScript } from "../core/lifecycle";
import { RequestFailed, send } from "../core/messages";
import type { ContentsItemBase, ProjectPublic } from "../core/types";
import {
  clear,
  el,
  errorMessage,
  loading,
  mountPanel,
  signInPrompt,
  textInput,
  type Panel,
} from "../core/ui";

const PANEL_ID = "calkit-github-panel";
const LAUNCHER_ID = "calkit-github-launcher";
const ARTIFACT_ROW_ATTR = "data-calkit-artifact";

/**
 * What the extension knows about the repo currently on screen.
 *
 * The repo's own calkit.yaml is the better source, since it names the hub
 * the project belongs to: a project living on another instance is then
 * recognised rather than looking like it isn't a Calkit project at all.
 * The hub lookup fills in the project itself, and covers private repos,
 * whose calkit.yaml can't be read anonymously.
 */
interface RepoState {
  repo: string;
  project: ProjectPublic | null;
  declaresCalkit: boolean;
  /** Hub the repo declares, when that isn't the one in use. */
  foreignHubUrl: string | null;
}

let panel: Panel | null = null;
let currentRepo: string | null = null;
let hubWebUrl = "https://calkit.io";

function formatSize(size: number | null | undefined): string {
  if (!size && size !== 0) {
    return "";
  }
  const units = ["B", "kB", "MB", "GB", "TB"];
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value);
  return `${rounded} ${units[unit]}`;
}

function isPreviewable(path: string): boolean {
  return /\.(png|jpe?g|gif|webp|svg)$/i.test(path);
}

function describe(item: ContentsItemBase): string {
  return [
    item.storage === "dvc-zip" ? "DVC (zipped)" : "DVC",
    formatSize(item.size),
    item.stage ? `stage: ${item.stage}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

async function resolveRepo(repo: string): Promise<RepoState> {
  const [info, projects] = await Promise.all([
    send({ type: "github.calkitInfo", githubRepo: repo }).catch(() => null),
    send({ type: "projects.byGithubRepo", githubRepo: repo }).catch(() => null),
  ]);
  const state: RepoState = {
    repo,
    project: projects?.data[0] ?? null,
    declaresCalkit: Boolean(info?.present),
    foreignHubUrl: null,
  };
  if (info?.present && info.hubUrl) {
    const declared = info.hubUrl.replace(/\/+$/, "");
    if (declared !== hubWebUrl.replace(/\/+$/, "")) {
      state.foreignHubUrl = declared;
    }
  }
  return state;
}

/** Show an artifact without leaving the repo page. */
function openArtifact(project: ProjectPublic, item: ContentsItemBase): void {
  panel = mountPanel({ id: PANEL_ID, title: item.name });
  const body = panel.body;
  clear(body).append(
    el("div", { class: "name", text: item.path }),
    el("div", { class: "dim small", text: describe(item) }),
  );
  if (!item.url) {
    body.append(
      el("a", {
        class: "small",
        text: "Open in Calkit",
        href:
          `${projectUrl(hubWebUrl, project.owner_account_name, project.name)}` +
          `/files?path=${encodeURIComponent(item.path)}`,
      }),
    );
    return;
  }
  body.append(
    el("div", { class: "actions" }, [
      el("a", { class: "small", text: "Download", href: item.url }),
    ]),
  );
  if (!isPreviewable(item.path)) {
    return;
  }
  const preview = el("img", {
    style: { display: "block", maxWidth: "100%", marginTop: "8px" },
  });
  const status = el("div", { class: "small" });
  body.append(status, preview);
  clear(status).append(loading("Loading preview"));
  // GitHub's content security policy governs what this panel may load and
  // doesn't allow object storage, so the bytes come back through the
  // service worker as a data URL instead
  void send({ type: "content.imageDataUrl", url: item.url })
    .then((dataUrl) => {
      preview.src = dataUrl;
      status.remove();
    })
    .catch((e: unknown) => {
      preview.remove();
      clear(status).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    });
}

/**
 * Add rows for DVC-tracked files to GitHub's own file listing.
 *
 * GitHub can only show the `.dvc` pointer files, since the artifacts
 * themselves were never committed to Git. These rows put the real files
 * back where they belong, so a figure is something you can open from the
 * repo you're already looking at.
 */
function injectArtifactRows(
  project: ProjectPublic,
  items: ContentsItemBase[],
): number {
  const table =
    document.querySelector('table[aria-labelledby="folders-and-files"]') ??
    document.querySelector('[role="grid"]');
  const body = table?.querySelector("tbody") ?? table;
  if (!body) {
    return 0;
  }
  for (const stale of body.querySelectorAll(`[${ARTIFACT_ROW_ATTR}]`)) {
    stale.remove();
  }
  // Cloning one of GitHub's own rows inherits whatever classes and layout
  // it currently uses, which survives their markup changing far better
  // than rebuilding their row here would.
  const template = body.querySelector("tr");
  if (!template) {
    return 0;
  }
  const shown = new Set(
    Array.from(body.querySelectorAll("tr a[href]")).map(
      (link) => link.textContent?.trim() ?? "",
    ),
  );
  let added = 0;
  for (const item of items) {
    if (item.storage !== "dvc" && item.storage !== "dvc-zip") {
      continue;
    }
    if (shown.has(item.name)) {
      continue;
    }
    const row = template.cloneNode(true) as HTMLElement;
    row.setAttribute(ARTIFACT_ROW_ATTR, item.path);
    row.removeAttribute("id");
    const links = Array.from(row.querySelectorAll("a"));
    if (!links.length) {
      continue;
    }
    // The first link is the filename; the rest are the latest commit and
    // other chrome that means nothing for a file Git never saw
    const nameLink = links[0];
    nameLink.textContent = item.name;
    nameLink.removeAttribute("href");
    nameLink.style.cursor = "pointer";
    nameLink.title = `${item.path} (tracked by DVC)`;
    nameLink.addEventListener("click", (event) => {
      event.preventDefault();
      openArtifact(project, item);
    });
    for (const other of links.slice(1)) {
      other.remove();
    }
    for (const cell of Array.from(row.querySelectorAll("td")).slice(1)) {
      cell.textContent = "";
    }
    const badge = el("span", {
      text: formatSize(item.size) ? `DVC · ${formatSize(item.size)}` : "DVC",
    });
    Object.assign(badge.style, {
      marginLeft: "8px",
      padding: "0 6px",
      borderRadius: "999px",
      fontSize: "11px",
      fontWeight: "600",
      color: "#009688",
      border: "1px solid #009688",
      whiteSpace: "nowrap",
    });
    nameLink.after(badge);
    body.append(row);
    added += 1;
  }
  return added;
}

/** Offer to connect the repo to the hub. */
function renderConnect(
  body: HTMLElement,
  repo: string,
  reload: () => void,
): void {
  const [, repoName] = repo.split("/");
  const title = textInput({ value: repoName });
  const isPublic = el("input", { type: "checkbox" });
  isPublic.style.width = "auto";
  const message = el("div", { class: "small" });
  const connect = el("button", {
    class: "action",
    text: "Make this a Calkit project",
  });
  connect.addEventListener("click", async () => {
    connect.disabled = true;
    clear(message).append(loading("Connecting"));
    try {
      await send({
        type: "projects.create",
        name: repoName,
        title: title.value.trim() || repoName,
        gitRepoUrl: `https://github.com/${repo}`,
        isPublic: isPublic.checked,
      });
      reload();
    } catch (e) {
      connect.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  body.append(
    el("div", {
      class: "dim small",
      text:
        `${repo} isn't a Calkit project on ` +
        `${hubWebUrl.replace(/^https?:\/\//, "")} yet. Connecting it tracks ` +
        "the repo as a project, so its pipeline, figures, and DVC artifacts " +
        "show up here and on the hub. You need write access to the repo.",
    }),
    el("label", { text: "Title" }),
    title,
    el("label", { class: "row", style: { fontWeight: "400" } }, [
      isPublic,
      el("div", { class: "grow small", text: "Make the project public" }),
    ]),
    el("div", { class: "actions" }, [connect]),
    message,
  );
}

async function renderProject(
  body: HTMLElement,
  project: ProjectPublic,
): Promise<void> {
  clear(body).append(
    el("div", { class: "row" }, [
      el("div", { class: "grow" }, [
        el("a", {
          text: `${project.owner_account_name}/${project.name}`,
          href: projectUrl(hubWebUrl, project.owner_account_name, project.name),
        }),
        el("div", { class: "dim small", text: project.title }),
      ]),
      el("span", { class: "badge ok", text: "connected" }),
    ]),
  );
  const list = el("div");
  body.append(list);
  clear(list).append(loading("Reading DVC artifacts"));
  try {
    const path = getGithubPath(window.location.href) ?? undefined;
    const contents = await send({
      type: "project.contents",
      owner: project.owner_account_name,
      project: project.name,
      path,
    });
    const items = (contents.dir_items ?? [contents]).filter(
      (item) => item.storage === "dvc" || item.storage === "dvc-zip",
    );
    clear(list);
    if (!items.length) {
      list.append(
        el("div", {
          class: "dim small",
          text: "No DVC-tracked files in this directory.",
        }),
      );
      return;
    }
    const added = injectArtifactRows(project, items);
    list.append(
      el("div", {
        class: "small dim",
        text: added
          ? `${added} added to the file list on this page.`
          : `${items.length} DVC-tracked file${
              items.length === 1 ? "" : "s"
            } here.`,
      }),
      ...items.map((item) =>
        el("div", { class: "row" }, [
          el("div", { class: "grow" }, [
            el("div", { class: "name", text: item.name }),
            el("div", { class: "dim small", text: describe(item) }),
          ]),
          el("button", {
            class: "action secondary",
            text: "View",
            onClick: () => openArtifact(project, item),
          }),
        ]),
      ),
    );
  } catch (e) {
    clear(list).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
  }
}

async function openPanel(state: RepoState): Promise<void> {
  panel = mountPanel({ id: PANEL_ID, title: `Calkit · ${state.repo}` });
  const body = panel.body;
  const reload = () => void refresh(state.repo);
  clear(body).append(loading());
  try {
    if (state.foreignHubUrl) {
      clear(body).append(
        el("div", { class: "stack" }, [
          el("div", {
            class: "dim small",
            text:
              `This project belongs to ${state.foreignHubUrl}, not the hub ` +
              "you're using. Switch hubs in the extension options to work " +
              "with it here.",
          }),
          el("a", {
            class: "small",
            text: "Open the project's hub",
            href: state.foreignHubUrl,
          }),
        ]),
      );
      return;
    }
    if (state.project) {
      await renderProject(body, state.project);
      return;
    }
    clear(body);
    renderConnect(body, state.repo, reload);
  } catch (e) {
    clear(body);
    if (e instanceof RequestFailed && e.notSignedIn) {
      body.append(
        signInPrompt(async () => {
          clear(body).append(loading("Waiting for authorization"));
          try {
            await send({ type: "auth.signIn" });
            reload();
          } catch (signInError) {
            clear(body).append(
              errorMessage(
                signInError instanceof Error
                  ? signInError.message
                  : String(signInError),
              ),
            );
          }
        }),
      );
      return;
    }
    body.append(errorMessage(e instanceof Error ? e.message : String(e)));
  }
}

/**
 * The button says whether this repo is a Calkit project before it's
 * clicked, so the state is visible at a glance rather than on demand.
 */
function mountLauncher(state: RepoState | null, onClick: () => void): void {
  document.getElementById(LAUNCHER_ID)?.remove();
  const host = el("div", { attrs: { id: LAUNCHER_ID } });
  Object.assign(host.style, {
    position: "fixed",
    right: "16px",
    bottom: "16px",
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
      background: #718096;
      border: 0;
      border-radius: 999px;
      padding: 8px 14px;
      cursor: pointer;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
      display: flex;
      align-items: center;
      gap: 6px;
    }
    button.connected { background: #009688; }
    button.elsewhere { background: #d69e2e; }
    button:hover { filter: brightness(1.1); }
    .dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.9);
    }
  `;
  const button = el("button", {}, [
    state?.project || state?.declaresCalkit
      ? el("span", { class: "dot" })
      : null,
    el("span", { text: "Calkit" }),
  ]);
  if (state?.project) {
    button.className = "connected";
    button.title = `${state.repo} is a Calkit project on ${hubWebUrl}`;
  } else if (state?.foreignHubUrl) {
    button.className = "elsewhere";
    button.title = `This project belongs to ${state.foreignHubUrl}`;
  } else if (state) {
    button.title = `${state.repo} isn't a Calkit project yet`;
  } else {
    button.title = "Checking with Calkit";
  }
  button.addEventListener("click", onClick);
  root.append(style, button);
  document.body.append(host);
}

async function refresh(repo: string): Promise<void> {
  mountLauncher(null, () => undefined);
  try {
    hubWebUrl = await getHubWebUrl();
  } catch {
    // Keep the default; the state below reports the real problem
  }
  let state: RepoState;
  try {
    state = await resolveRepo(repo);
  } catch {
    state = { repo, project: null, declaresCalkit: false, foreignHubUrl: null };
  }
  if (currentRepo !== repo) {
    return;
  }
  mountLauncher(state, () => void openPanel(state));
  // A connected project puts its artifacts in the file listing without
  // waiting to be asked, which is the point of being on this page
  if (state.project && !state.foreignHubUrl) {
    try {
      const path = getGithubPath(window.location.href) ?? undefined;
      const contents = await send({
        type: "project.contents",
        owner: state.project.owner_account_name,
        project: state.project.name,
        path,
      });
      injectArtifactRows(state.project, contents.dir_items ?? [contents]);
    } catch {
      // The panel reports why; the listing stays as GitHub had it
    }
  }
}

function teardown(): void {
  document.getElementById(LAUNCHER_ID)?.remove();
  for (const row of document.querySelectorAll(`[${ARTIFACT_ROW_ATTR}]`)) {
    row.remove();
  }
  panel?.remove();
  panel = null;
  currentRepo = null;
}

function sync(): void {
  const repo = getGithubRepo(window.location.href);
  if (!repo) {
    teardown();
    return;
  }
  // Moving between directories keeps the repo but changes which artifacts
  // belong in the listing, so a same-repo move still refreshes
  currentRepo = repo;
  panel?.remove();
  panel = null;
  void refresh(repo);
}

runContentScript({ id: "github", sync, teardown });
