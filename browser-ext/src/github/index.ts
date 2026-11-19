/**
 * Content script for GitHub: the Calkit badge and panel for a repo, and the
 * viewer overlay for its artifacts.
 */
import {
  getGithubPath,
  getGithubPullNumber,
  getGithubRepo,
} from "../core/detect";
import { getHubWebUrl, projectUrl } from "../core/hub-url";
import { runContentScript } from "../core/lifecycle";
import { send } from "../core/messages";
import { renderFailure } from "../core/pickers";
import { type ContentsItemBase, type ProjectPublic } from "../core/types";
import {
  clear,
  el,
  launcherPosition,
  errorMessage,
  loading,
  mountOverlay,
  mountPanel,
  textInput,
  type Panel,
} from "../core/ui";
import {
  removePullRequestCard,
  readPullRequest,
  renderPullRequest,
  injectPullRequestCard,
} from "./pr";
import { ARTIFACT_ROW_ATTR, injectArtifactRows } from "./repo-home";

interface Viewable {
  path: string;
  name: string;
  url?: string | null;
  size?: number | null;
  storage?: string | null;
}

const PANEL_ID = "calkit-github-panel";
const OVERLAY_ID = "calkit-github-overlay";
const SIDE_BY_SIDE = "Side by side";
const TEXT_DIFF = "Text diff";
const LATEX_DIFF = "LaTeX diff";
// Marked-up documents are outputs too; they belong beside the document
// they describe rather than in the list of things that changed
export const LATEX_DIFF_DIR = ".calkit/latex-diffs/";
const LAUNCHER_ID = "calkit-github-launcher";
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

export function formatSize(size: number | null | undefined): string {
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
export function filesUrl(
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
export function openArtifact(
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
      el("div", { class: "grow small", text: "Make project public" }),
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

export function openOverlay(
  project: ProjectPublic,
  hubUrl: string,
  versions: { label: string; item: Viewable }[],
  options: {
    /** The refs being compared, which the text diff is asked for by. */
    refs?: { base: string; head: string };
    /** The project's own marked-up version, if its pipeline built one. */
    latexDiff?: Viewable;
  } = {},
): void {
  const refs = options.refs ?? null;
  const latexDiff = options.latexDiff ?? null;
  const first = versions[0];
  const overlay = mountOverlay({ id: OVERLAY_ID, title: first.item.name });
  const pane = (
    version: { label: string; item: Viewable },
    labelled: boolean,
  ) =>
    el("div", { class: "pane" }, [
      labelled ? el("div", { class: "pane-label", text: version.label }) : null,
      (() => {
        const frame = el("iframe", { class: "frame" });
        frame.src = `${overlayViewerUrl(
          project,
          version.item,
          hubUrl,
        )}&embedded=1`;
        return frame;
      })(),
    ]);
  const show = (label: string) => {
    for (const button of buttons) {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.mode === label),
      );
    }
    if (label === TEXT_DIFF) {
      showTextDiff();
      return;
    }
    if (label === LATEX_DIFF && latexDiff) {
      clear(overlay.viewport).append(
        pane({ label: LATEX_DIFF, item: latexDiff }, false),
      );
      clear(details).append(document.createTextNode(describeOutput(latexDiff)));
      download.href = latexDiff.url ?? "";
      tab.href = overlayViewerUrl(project, latexDiff, hubUrl);
      return;
    }
    // Side by side is how you see what actually changed; one at a time is
    // how you read it, since half a page of PDF is no use
    const showing =
      label === SIDE_BY_SIDE
        ? versions
        : versions.filter((version) => version.label === label);
    clear(overlay.viewport).append(
      ...showing.map((version) => pane(version, showing.length > 1)),
    );
    const current = showing[0];
    clear(details).append(
      document.createTextNode(
        showing.length > 1
          ? versions.map((v) => describeOutput(v.item)).join("  vs  ")
          : describeOutput(current.item),
      ),
    );
    download.href = current.item.url ?? "";
    tab.href = overlayViewerUrl(project, current.item, hubUrl);
  };
  // A document the project marked up itself is the best answer: latexdiff
  // shows insertions and deletions in place, in the typeset document.
  // Reading the words out of both PDFs is the fallback for a project that
  // hasn't declared the comparison.
  const comparable =
    latexDiff === null &&
    versions.length > 1 &&
    /\.pdf$/i.test(first.item.path) &&
    refs !== null;
  const showTextDiff = async () => {
    clear(details);
    download.href = versions[0].item.url ?? "";
    const pane = el("div", { class: "diff" });
    clear(overlay.viewport).append(pane);
    pane.append(loading("Reading both documents"));
    let result;
    try {
      result = await send({
        type: "project.textDiff",
        owner: project.owner_account_name,
        project: project.name,
        path: first.item.path,
        base: refs!.base,
        head: refs!.head,
        hubUrl,
      });
    } catch (e) {
      clear(pane).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
      return;
    }
    clear(pane);
    if (result.identical) {
      pane.append(
        el("div", {
          class: "dim small",
          text:
            "The words are the same in both versions. Whatever changed is " +
            "in the layout, the figures, or the numbers inside them.",
        }),
      );
      return;
    }
    if (result.truncated) {
      pane.append(
        el("div", {
          class: "dim small",
          text: "Long document: only the first pages were compared.",
        }),
      );
    }
    for (const segment of result.segments) {
      if (segment.elided) {
        pane.append(el("span", { class: "elided" }));
        continue;
      }
      pane.append(
        el("span", { class: segment.kind, text: `${segment.text} ` }),
      );
    }
  };
  const modes = [
    ...versions.map((version) => version.label),
    ...(versions.length > 1 ? [SIDE_BY_SIDE] : []),
    ...(latexDiff ? [LATEX_DIFF] : []),
    ...(comparable ? [TEXT_DIFF] : []),
  ];
  const buttons = modes.map((mode) => {
    const button = el("button", {
      class: "chip",
      text: mode,
      onClick: () => show(mode),
    });
    button.dataset.mode = mode;
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
  // Open on the most useful thing there is, and leave the rest a chip
  // away: the project's own LaTeX diff, else both versions side by side,
  // else just the file
  show(
    latexDiff ? LATEX_DIFF : versions.length > 1 ? SIDE_BY_SIDE : first.label,
  );
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

export function describeOutput(item: Viewable): string {
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
        clear(message).append(loading("Approve the request in the new tab"));
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
            text: "Open hub",
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
    // renderFailure offers a way to sign in, and a hub picker with it:
    // credentials are per hub, so a signed-out panel needs a way back to
    // whichever hub the user meant
    clear(body).append(renderFailure(e, { onSignedIn: reload }));
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
  // A panel still on screen was showing the old state, e.g., a sign-in
  // prompt whose spinner would otherwise run until the page is reloaded
  if (panel?.host.isConnected) {
    void openPanel(state);
  }
  if (!state.project) {
    return;
  }
  // A connected project puts its artifacts on the page without waiting to
  // be asked, which is the point of being here: in the file listing, or
  // in the conversation on a pull request
  const pullNumber = getGithubPullNumber(window.location.href);
  if (pullNumber !== null) {
    try {
      const { refs, changed } = await readPullRequest(
        state.project,
        state.hubWebUrl,
        pullNumber,
      );
      injectPullRequestCard(state.project, state.hubWebUrl, refs, changed);
    } catch {
      // The panel reports why; the conversation stays as GitHub had it
    }
    return;
  }
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

function teardown(): void {
  document.getElementById(LAUNCHER_ID)?.remove();
  removePullRequestCard();
  document.getElementById(OVERLAY_ID)?.remove();
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
  // Anything read for the last page is stale now, including a pull
  // request whose branch may have been pushed to since
  removePullRequestCard();
  void refresh(repo);
}

runContentScript({
  id: "github",
  sync,
  teardown,
  authChanged: () => {
    if (!currentRepo) {
      return;
    }
    // Read under the old session, including a lookup that failed for want
    // of signing in, which would otherwise be served from the cache
    removePullRequestCard();
    document.getElementById(OVERLAY_ID)?.remove();
    for (const row of document.querySelectorAll(`[${ARTIFACT_ROW_ATTR}]`)) {
      row.remove();
    }
    void refresh(currentRepo);
  },
});
