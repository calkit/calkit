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
  type Panel,
} from "../core/ui";

const PANEL_ID = "calkit-github-panel";
const LAUNCHER_ID = "calkit-github-launcher";

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
  return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)} ${
    units[unit]
  }`;
}

function isPreviewable(path: string): boolean {
  return /\.(png|jpe?g|gif|webp|svg)$/i.test(path);
}

function artifactRow(
  project: ProjectPublic,
  item: ContentsItemBase,
): HTMLElement {
  const details = [
    item.storage === "dvc-zip" ? "DVC (zipped)" : "DVC",
    formatSize(item.size),
    item.stage ? `stage: ${item.stage}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const row = el("div", { class: "row" }, [
    el("div", { class: "grow" }, [
      el("div", { class: "name", text: item.path }),
      el("div", { class: "dim small", text: details }),
    ]),
  ]);
  if (item.url) {
    row.append(
      el("a", {
        class: "small",
        text: "Download",
        href: item.url,
        title: "Fetch this artifact from the project's DVC storage",
      }),
    );
  } else {
    row.append(
      el("a", {
        class: "small",
        text: "View",
        href:
          `${projectUrl(hubWebUrl, project.owner_account_name, project.name)}` +
          `/files?path=${encodeURIComponent(item.path)}`,
      }),
    );
  }
  if (item.url && isPreviewable(item.path)) {
    const preview = el("img", {
      style: {
        display: "block",
        maxWidth: "100%",
        marginTop: "6px",
        borderRadius: "4px",
      },
    });
    // GitHub's content security policy governs what this panel can load, and
    // it doesn't allow object storage, so the image comes back through the
    // service worker as a data URL instead
    void send({ type: "content.imageDataUrl", url: item.url })
      .then((dataUrl) => {
        preview.src = dataUrl;
      })
      .catch(() => {
        preview.remove();
      });
    const wrapper = el("div", {}, [row, preview]);
    return wrapper;
  }
  return row;
}

/** Walk the project tree collecting DVC-tracked files. */
async function collectArtifacts(
  project: ProjectPublic,
  path: string | undefined,
  depth: number,
  found: ContentsItemBase[],
): Promise<void> {
  // Deep trees would mean a request per directory, so stop a few levels in
  // and let the user open the project on the hub for the rest
  if (depth > 2 || found.length >= 50) {
    return;
  }
  const contents = await send({
    type: "project.contents",
    owner: project.owner_account_name,
    project: project.name,
    path,
  });
  const items = contents.dir_items ?? [contents];
  const directories: ContentsItemBase[] = [];
  for (const item of items) {
    if (item.type === "dir") {
      directories.push(item);
    } else if (item.storage === "dvc" || item.storage === "dvc-zip") {
      found.push(item);
    }
  }
  for (const directory of directories) {
    if (found.length >= 50) {
      break;
    }
    await collectArtifacts(project, directory.path, depth + 1, found);
  }
}

async function renderProject(
  body: HTMLElement,
  project: ProjectPublic,
  focusPath: string | null,
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
    ]),
  );
  const list = el("div");
  body.append(list);
  clear(list).append(loading("Reading DVC artifacts"));
  try {
    const found: ContentsItemBase[] = [];
    await collectArtifacts(project, undefined, 0, found);
    clear(list);
    if (!found.length) {
      list.append(
        el("div", {
          class: "dim small",
          text: "No DVC-tracked artifacts found near the top of this repo.",
        }),
      );
      return;
    }
    // When browsing a file on GitHub, put that file first if it's tracked
    found.sort((a, b) => {
      if (focusPath) {
        if (a.path === focusPath) return -1;
        if (b.path === focusPath) return 1;
      }
      return a.path.localeCompare(b.path);
    });
    list.append(
      el("div", {
        class: "small dim",
        text: `${found.length} DVC-tracked file${
          found.length === 1 ? "" : "s"
        }`,
      }),
      ...found.map((item) => artifactRow(project, item)),
    );
  } catch (e) {
    clear(list).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
  }
}

async function load(repo: string): Promise<void> {
  if (!panel) {
    return;
  }
  const body = panel.body;
  clear(body).append(loading());
  try {
    hubWebUrl = await getHubWebUrl();
    const projects = await send({
      type: "projects.byGithubRepo",
      githubRepo: repo,
    });
    if (!projects.data.length) {
      clear(body).append(
        el("div", { class: "stack" }, [
          el("div", {
            class: "dim small",
            text: `No Calkit project is linked to ${repo}.`,
          }),
          el("a", {
            class: "small",
            text: "Import this repo into Calkit",
            href: `${hubWebUrl}/?import=${encodeURIComponent(repo)}`,
          }),
        ]),
      );
      return;
    }
    await renderProject(
      body,
      projects.data[0],
      getGithubPath(window.location.href),
    );
  } catch (e) {
    clear(body);
    if (e instanceof RequestFailed && e.notSignedIn) {
      body.append(
        signInPrompt(async () => {
          clear(body).append(loading("Waiting for authorization"));
          try {
            await send({ type: "auth.signIn" });
            void load(repo);
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
 * A small button rather than an open panel: unlike Overleaf, most GitHub
 * pages have nothing to do with Calkit, so the panel opens on request.
 */
function mountLauncher(repo: string): void {
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
      background: #009688;
      border: 0;
      border-radius: 999px;
      padding: 8px 14px;
      cursor: pointer;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    }
    button:hover { background: #00766c; }
  `;
  const button = el("button", { text: "Calkit artifacts" });
  button.addEventListener("click", () => {
    panel = mountPanel({ id: PANEL_ID, title: `Calkit · ${repo}` });
    void load(repo);
  });
  root.append(style, button);
  document.body.append(host);
}

function sync(): void {
  const repo = getGithubRepo(window.location.href);
  if (!repo) {
    document.getElementById(LAUNCHER_ID)?.remove();
    panel?.remove();
    panel = null;
    currentRepo = null;
    return;
  }
  if (repo === currentRepo) {
    return;
  }
  currentRepo = repo;
  panel?.remove();
  panel = null;
  mountLauncher(repo);
}

runContentScript({
  id: "github",
  sync,
  teardown: () => {
    document.getElementById(LAUNCHER_ID)?.remove();
    panel?.remove();
    panel = null;
  },
});
