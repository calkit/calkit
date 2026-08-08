import {
  getGithubPath,
  getGithubPullNumber,
  getGithubRepo,
} from "../core/detect";
import { getHubWebUrl, projectUrl } from "../core/hub-url";
import { runContentScript } from "../core/lifecycle";
import { RequestFailed, send } from "../core/messages";
import { renderFailure } from "../core/pickers";
import type { ContentsItemBase, DvcOutput, ProjectPublic } from "../core/types";
import {
  clear,
  el,
  launcherPosition,
  errorMessage,
  loading,
  mountOverlay,
  mountPanel,
  signInPrompt,
  textInput,
  type Panel,
} from "../core/ui";

/** The little an overlay needs to show a file: where it is and its bytes. */
interface Viewable {
  path: string;
  name: string;
  url?: string | null;
  size?: number | null;
  storage?: string | null;
}

const PANEL_ID = "calkit-github-panel";
const OVERLAY_ID = "calkit-github-overlay";
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
  /**
   * Hub this repo is worked with through: the one it declares if it
   * declares one, otherwise the configured one. Knowing a project's hub
   * is enough to use it, so a project on another instance doesn't require
   * changing which hub the extension uses by default.
   */
  hubWebUrl: string;
  /** Whether that hub has credentials stored for it. */
  signedIn: boolean;
  /** How the hub names itself, which shows which instance was reached. */
  hubLabel: string;
}

let panel: Panel | null = null;
let currentRepo: string | null = null;
let hubWebUrl = "https://calkit.io";

/** Host of a hub URL, for prose that shouldn't carry a scheme. */
function hubHost(webUrl: string): string {
  return webUrl.replace(/^https?:\/\//, "").replace(/\/+$/, "");
}

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
  const info = await send({
    type: "github.calkitInfo",
    githubRepo: repo,
  }).catch(() => null);
  // The repo's own declaration wins, so the project is looked up on the
  // hub it says it belongs to rather than whichever one is configured
  const target = info?.hubUrl ? info.hubUrl.replace(/\/+$/, "") : hubWebUrl;
  const state: RepoState = {
    repo,
    project: null,
    declaresCalkit: Boolean(info?.present),
    hubWebUrl: target,
    signedIn: false,
    hubLabel: hubHost(target),
  };
  const auth = await send({ type: "auth.state", hubUrl: target }).catch(
    () => null,
  );
  state.signedIn = Boolean(auth?.signedIn);
  state.hubLabel = auth?.hubLabel ?? hubHost(target);
  const projects = await send({
    type: "projects.byGithubRepo",
    githubRepo: repo,
    hubUrl: target,
  }).catch(() => null);
  state.project = projects?.data[0] ?? null;
  return state;
}

/** Where a path lives on the hub, for links out of the page. */
function filesUrl(
  project: ProjectPublic,
  path: string,
  hubUrl: string,
): string {
  return (
    `${projectUrl(hubUrl, project.owner_account_name, project.name)}` +
    `/files?path=${encodeURIComponent(path)}`
  );
}

/** The extension's own page for looking at an artifact. */
function viewerUrl(
  project: ProjectPublic,
  item: ContentsItemBase,
  hubUrl: string,
): string {
  const params = new URLSearchParams({
    url: item.url ?? "",
    path: item.path,
    hubUrl: filesUrl(project, item.path, hubUrl),
  });
  return `${chrome.runtime.getURL("viewer.html")}?${params.toString()}`;
}

/** Show an artifact without leaving the repo page. */
function openArtifact(
  project: ProjectPublic,
  item: ContentsItemBase,
  hubUrl: string,
  onBack?: () => void,
): void {
  panel = mountPanel({ id: PANEL_ID, title: item.name });
  const body = panel.body;
  clear(body);
  if (onBack) {
    // Opening a file replaces the panel, so without this the only way
    // back to the artifact list is closing and reopening the panel
    body.append(
      el("div", { class: "actions", style: { marginTop: "0" } }, [
        el("button", {
          class: "action secondary",
          text: "\u2190 Back",
          onClick: onBack,
        }),
      ]),
    );
  }
  body.append(
    el("div", { class: "name", text: item.path }),
    el("div", { class: "dim small", text: describe(item) }),
  );
  if (!item.url) {
    body.append(
      el("a", {
        class: "small",
        text: "Open in Calkit",
        href: filesUrl(project, item.path, hubUrl),
      }),
    );
    return;
  }
  body.append(
    el("div", { class: "actions" }, [
      // Anything that isn't a plain image needs frames or objects that
      // GitHub's content security policy forbids in this panel, so it
      // renders in a page of ours -- laid over this one, or in its own tab
      el("button", {
        class: "action secondary",
        text: "View",
        onClick: () =>
          openOverlay(project, hubUrl, [{ label: item.name, item }]),
      }),
      el("a", {
        class: "small",
        text: "Open in a tab",
        href: viewerUrl(project, item, hubUrl),
      }),
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
  hubUrl: string,
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
    // Cloning a row brings GitHub's own behaviour with it. Their hovercard
    // attributes are the visible one: left in place they pop up the
    // profile card of whoever last touched the row this was copied from.
    for (const node of [row, ...Array.from(row.querySelectorAll("*"))]) {
      for (const name of node.getAttributeNames()) {
        if (
          name.startsWith("data-hovercard") ||
          name.startsWith("data-turbo") ||
          name === "data-testid" ||
          name === "aria-describedby"
        ) {
          node.removeAttribute(name);
        }
      }
    }
    const links = Array.from(row.querySelectorAll("a"));
    if (!links.length) {
      continue;
    }
    // The first link is the filename; the rest are the latest commit and
    // other chrome that means nothing for a file Git never saw
    const nameLink = links[0];
    nameLink.textContent = item.name;
    // A real href means middle-click and copy-link do something sensible,
    // and it goes where the file actually lives
    nameLink.href = filesUrl(project, item.path, hubUrl);
    nameLink.title = `${item.path} (tracked by DVC)`;
    nameLink.addEventListener("click", (event) => {
      // Let a modified click through, so opening in a new tab still works
      if (event.metaKey || event.ctrlKey || event.shiftKey) {
        return;
      }
      event.preventDefault();
      openArtifact(project, item, hubUrl);
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
  hubUrl: string,
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
        hubUrl,
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
        `${repo} isn't a Calkit project on ${hubHost(hubUrl)} yet. ` +
        "Connecting it tracks " +
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
  hubUrl: string,
): Promise<void> {
  clear(body).append(
    el("div", { class: "row" }, [
      el("div", { class: "grow" }, [
        el("a", {
          text: `${project.owner_account_name}/${project.name}`,
          href: projectUrl(hubUrl, project.owner_account_name, project.name),
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
      hubUrl,
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
    const added = injectArtifactRows(project, items, hubUrl);
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
            onClick: () =>
              openArtifact(project, item, hubUrl, () => {
                panel = mountPanel({
                  id: PANEL_ID,
                  title: `Calkit \u00b7 ${project.owner_account_name}/${project.name}`,
                });
                void renderProject(panel.body, project, hubUrl);
              }),
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

/**
 * What a pull request does to the project's DVC-tracked outputs.
 *
 * A diff on GitHub shows the `.dvc` pointer changing, which says an
 * output changed but nothing about how. Reading the project at both refs
 * gives the actual files, so a new or regenerated figure can be looked at
 * next to the one it replaces.
 */
async function renderPullRequest(
  body: HTMLElement,
  project: ProjectPublic,
  hubUrl: string,
  number: number,
): Promise<void> {
  clear(body).append(loading("Reading the pull request"));
  let refs;
  try {
    refs = await send({
      type: "github.pullRequest",
      owner: project.owner_account_name,
      project: project.name,
      number,
      hubUrl,
    });
  } catch (e) {
    clear(body).append(renderFailure(e, { onSignedIn: () => undefined }));
    return;
  }
  clear(body).append(loading("Comparing DVC outputs"));
  // Every output at a ref in one call, each carrying that version's own
  // presigned URL. Listing the tree a directory at a time would miss
  // anything nested, which is where outputs usually live, and would have
  // no URL to view the artifact with.
  const read = async (ref: string) => {
    const outputs = await send({
      type: "project.dvcOutputs",
      owner: project.owner_account_name,
      project: project.name,
      ref,
      hubUrl,
    });
    return new Map(outputs.map((item) => [item.path, item]));
  };
  let head: Map<string, DvcOutput>;
  let base: Map<string, DvcOutput>;
  try {
    [head, base] = await Promise.all([
      read(refs.head_sha),
      read(refs.base_sha),
    ]);
  } catch (e) {
    clear(body).append(renderFailure(e, { onSignedIn: () => undefined }));
    return;
  }
  clear(body).append(
    el("div", { class: "dim small" }, [
      document.createTextNode(
        `Comparing DVC outputs in #${number}: ` +
          `${refs.head_ref} against ${refs.base_ref}.`,
      ),
    ]),
  );
  const changed = [...head.values()].filter((item) => {
    const before = base.get(item.path);
    if (!before) {
      return true;
    }
    // Equal content hashes mean the same file, whatever the pointer
    // commit says. Size only stands in where a hash is missing, and it
    // can't tell a same-size edit from no edit at all.
    return before.md5 && item.md5
      ? before.md5 !== item.md5
      : before.size !== item.size;
  });
  if (!changed.length) {
    body.append(
      el("div", {
        class: "dim small",
        style: { marginTop: "8px" },
        text: "No DVC-tracked outputs changed on this branch.",
      }),
    );
    return;
  }
  for (const item of changed) {
    const before = base.get(item.path);
    const versions = [
      { label: refs.head_ref, item },
      ...(before ? [{ label: refs.base_ref, item: before }] : []),
    ];
    body.append(
      el("div", { class: "row" }, [
        el("div", { class: "grow" }, [
          el("div", { class: "name", text: item.path }),
          el("div", {
            class: "dim small",
            text: before
              ? `changed \u00b7 ${describeOutput(item)}`
              : `new \u00b7 ${describeOutput(item)}`,
          }),
        ]),
        el("button", {
          class: "action secondary",
          text: "View",
          disabled: !item.url,
          title: item.url
            ? undefined
            : "This version hasn't been pushed to storage yet",
          onClick: () => openOverlay(project, hubUrl, versions),
        }),
      ]),
    );
  }
}

/**
 * Show an artifact over the page it was opened from.
 *
 * A pull request is read on GitHub, so the figure or paper it changes is
 * worth seeing without leaving it. The versions are the same artifact at
 * each ref, so switching between them is switching branches.
 */
function openOverlay(
  project: ProjectPublic,
  hubUrl: string,
  versions: { label: string; item: Viewable }[],
): void {
  const first = versions[0];
  const overlay = mountOverlay({ id: OVERLAY_ID, title: first.item.name });
  const show = (version: { label: string; item: Viewable }) => {
    for (const button of buttons) {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.label === version.label),
      );
    }
    clear(details).append(
      document.createTextNode(describeOutput(version.item)),
    );
    download.href = version.item.url ?? "";
    tab.href = overlayViewerUrl(project, version.item, hubUrl);
    overlay.frame.src = `${tab.href}&embedded=1`;
  };
  const buttons = versions.map((version) => {
    const button = el("button", {
      class: "chip",
      text: version.label,
      onClick: () => show(version),
    });
    button.dataset.label = version.label;
    return button;
  });
  const details = el("span", { class: "dim small" });
  const tab = el("a", { class: "small", text: "Open in a tab", href: "#" });
  const download = el("a", { class: "small", text: "Download", href: "#" });
  overlay.toolbar.append(
    el("span", { class: "name", text: first.item.path }),
    // Only worth a switch when there's another version to switch to
    ...(versions.length > 1 ? buttons : []),
    details,
    el("span", { class: "spacer" }),
    tab,
    download,
  );
  show(first);
}

function overlayViewerUrl(
  project: ProjectPublic,
  item: Viewable,
  hubUrl: string,
): string {
  const params = new URLSearchParams({
    url: item.url ?? "",
    path: item.path,
    hubUrl: filesUrl(project, item.path, hubUrl),
  });
  return `${chrome.runtime.getURL("viewer.html")}?${params.toString()}`;
}

function describeOutput(item: Viewable): string {
  return [
    item.storage === "dvc-zip" ? "DVC (zipped)" : "DVC",
    formatSize(item.size),
  ]
    .filter(Boolean)
    .join(" \u00b7 ");
}

async function openPanel(state: RepoState): Promise<void> {
  panel = mountPanel({ id: PANEL_ID, title: `Calkit · ${state.repo}` });
  const body = panel.body;
  const reload = () => void refresh(state.repo);
  clear(body).append(loading());
  try {
    if (!state.signedIn) {
      clear(body).append(
        el("div", { class: "stack" }, [
          el("div", {
            class: "dim small",
            text:
              `This project belongs to ${state.hubLabel}, and there are no ` +
              "credentials stored for it. Signing in here stays separate " +
              "from whichever hub the extension uses by default.",
          }),
        ]),
      );
      const message = el("div", { class: "small" });
      const signIn = el("button", {
        class: "action",
        text: `Sign in to ${hubHost(state.hubWebUrl)}`,
      });
      signIn.addEventListener("click", async () => {
        signIn.disabled = true;
        clear(message).append(
          loading("Approve the request in the tab that just opened"),
        );
        try {
          await send({ type: "auth.signIn", hubUrl: state.hubWebUrl });
          reload();
        } catch (e) {
          signIn.disabled = false;
          clear(message).append(
            errorMessage(e instanceof Error ? e.message : String(e)),
          );
        }
      });
      body.append(
        el("div", { class: "actions" }, [
          signIn,
          el("a", {
            class: "small",
            text: "Open the hub",
            href: state.hubWebUrl,
          }),
        ]),
        message,
      );
      return;
    }
    if (state.project) {
      const pullNumber = getGithubPullNumber(window.location.href);
      if (pullNumber !== null) {
        await renderPullRequest(
          body,
          state.project,
          state.hubWebUrl,
          pullNumber,
        );
        return;
      }
      await renderProject(body, state.project, state.hubWebUrl);
      return;
    }
    clear(body);
    renderConnect(body, state.repo, state.hubWebUrl, reload);
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
    button.title = `${state.repo} is a Calkit project on ${hubHost(
      state.hubWebUrl,
    )}`;
  } else if (state?.declaresCalkit) {
    button.className = "elsewhere";
    button.title = state.signedIn
      ? `${state.repo} declares a Calkit project on ${state.hubWebUrl}`
      : `Sign in to ${hubHost(state.hubWebUrl)} to work with this project`;
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
    state = {
      repo,
      project: null,
      declaresCalkit: false,
      hubWebUrl,
      signedIn: false,
      hubLabel: hubHost(hubWebUrl),
    };
  }
  if (currentRepo !== repo) {
    return;
  }
  mountLauncher(state, () => void openPanel(state));
  // A connected project puts its artifacts in the file listing without
  // waiting to be asked, which is the point of being on this page
  if (state.project) {
    try {
      const path = getGithubPath(window.location.href) ?? undefined;
      const contents = await send({
        type: "project.contents",
        owner: state.project.owner_account_name,
        project: state.project.name,
        path,
        hubUrl: state.hubWebUrl,
      });
      injectArtifactRows(
        state.project,
        contents.dir_items ?? [contents],
        state.hubWebUrl,
      );
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
