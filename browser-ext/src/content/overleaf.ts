import { getOverleafProjectId } from "../core/detect";
import { getHubWebUrl, projectUrl } from "../core/hub-url";
import { RequestFailed, send } from "../core/messages";
import type {
  OverleafLinkPublic,
  OverleafSyncStatus,
  OverleafSyncStatusFile,
  ProjectPublic,
} from "../core/types";
import {
  clear,
  el,
  errorMessage,
  loading,
  mountPanel,
  signInPrompt,
  type Panel,
} from "../core/ui";

const PANEL_ID = "calkit-overleaf-panel";

let panel: Panel | null = null;
let currentProjectId: string | null = null;
let hubWebUrl = "https://calkit.io";

function fileRow(file: OverleafSyncStatusFile): HTMLElement {
  const stale = file.stage_status && file.stage_status.status !== "up-to-date";
  const stateLabel = {
    new: "not on Overleaf",
    modified: "changed",
    deleted: "removed",
  }[file.state];
  return el("div", { class: "row" }, [
    el("div", { class: "grow" }, [
      el("div", { class: "name", text: file.path }),
      el("div", { class: "dim small", text: stateLabel }),
    ]),
    file.figure && el("span", { class: "badge info", text: "figure" }),
    stale &&
      el("span", {
        class: "badge warn",
        text: "stale",
        title:
          `Produced by stage '${file.stage}', which is ` +
          `${file.stage_status?.status}; run the pipeline before syncing`,
      }),
  ]);
}

function renderStatus(
  body: HTMLElement,
  link: OverleafLinkPublic,
  status: OverleafSyncStatus,
  reload: () => void,
): void {
  clear(body);
  const figures = status.files_to_push.filter((f) => f.figure);
  const others = status.files_to_push.filter((f) => !f.figure);
  const canWrite = ["write", "admin", "owner"].includes(
    link.current_user_access ?? "",
  );
  body.append(
    el("div", { class: "row" }, [
      el("div", { class: "grow" }, [
        el("a", {
          text: `${link.project_owner_name}/${link.project_name}`,
          href: projectUrl(
            hubWebUrl,
            link.project_owner_name,
            link.project_name,
          ),
        }),
        el("div", {
          class: "dim small",
          text: `Synced folder: ${status.path}`,
        }),
      ]),
      status.in_sync
        ? el("span", { class: "badge ok", text: "in sync" })
        : el("span", {
            class: figures.length ? "badge danger" : "badge warn",
            text: figures.length
              ? `${figures.length} figure${
                  figures.length === 1 ? "" : "s"
                } to sync`
              : "out of sync",
          }),
    ]),
  );
  if (status.in_sync) {
    body.append(
      el("div", {
        class: "dim small",
        style: { paddingTop: "6px" },
        text: "Everything here matches the Calkit project.",
      }),
    );
  }
  if (figures.length) {
    body.append(
      el("div", {
        class: "small",
        style: { marginTop: "8px", fontWeight: "600" },
        text: "Figures to sync",
      }),
      ...figures.map(fileRow),
    );
  }
  if (others.length) {
    body.append(
      el("div", {
        class: "small",
        style: { marginTop: "8px", fontWeight: "600" },
        text: "Other files to sync",
      }),
      ...others.map(fileRow),
    );
  }
  if (status.files_to_delete.length) {
    body.append(
      el("div", {
        class: "small",
        style: { marginTop: "8px", fontWeight: "600" },
        text: "Removed from the project",
      }),
      ...status.files_to_delete.map(fileRow),
    );
  }
  if (status.commits_from_overleaf > 0) {
    const count = status.commits_from_overleaf;
    body.append(
      el("div", {
        class: "dim small",
        style: { marginTop: "8px" },
        text:
          `${count} Overleaf ${count === 1 ? "change" : "changes"} ` +
          "will come back into the project on the next sync.",
      }),
    );
  }
  const syncButton = el("button", {
    class: "action",
    text: "Sync now",
    disabled: !canWrite || status.in_sync,
    title: canWrite
      ? "Push project files to Overleaf and pull Overleaf edits back"
      : "You need write access to this project to sync",
  });
  const message = el("div", { class: "small" });
  syncButton.addEventListener("click", async () => {
    syncButton.disabled = true;
    clear(message).append(loading("Syncing"));
    try {
      const result = await send({
        type: "overleaf.sync",
        owner: link.project_owner_name,
        project: link.project_name,
        path: status.path,
      });
      clear(message).append(
        el("span", {
          class: "dim",
          text:
            `Synced. ${result.commits_from_overleaf} change` +
            `${
              result.commits_from_overleaf === 1 ? "" : "s"
            } came from Overleaf.`,
        }),
      );
      reload();
    } catch (e) {
      syncButton.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  body.append(
    el("div", { class: "actions" }, [
      syncButton,
      el("button", {
        class: "action secondary",
        text: "Refresh",
        onClick: reload,
      }),
    ]),
    message,
  );
}

/** Let the user point this Overleaf project at one of their Calkit projects. */
async function renderPicker(
  body: HTMLElement,
  overleafProjectId: string,
  reload: () => void,
): Promise<void> {
  clear(body);
  body.append(
    el("div", {
      class: "dim small",
      text:
        "This Overleaf project isn't linked to a Calkit project yet, or the " +
        "link hasn't been seen by the hub. Pick a project to check or link.",
    }),
  );
  const search = el("input", {
    type: "text",
    placeholder: "Search your projects",
    attrs: {
      autocomplete: "off",
      "data-form-type": "other",
      "data-lpignore": "true",
    },
  });
  const results = el("div", { class: "stack", style: { marginTop: "6px" } });
  const message = el("div", { class: "small" });
  const checkProject = async (project: ProjectPublic) => {
    clear(message).append(loading("Checking"));
    try {
      const statuses = await send({
        type: "overleaf.status",
        owner: project.owner_account_name,
        project: project.name,
        overleafProjectId,
      });
      if (statuses.length) {
        // Reading the status indexes the link server side, so a plain
        // reload now finds it
        reload();
        return;
      }
      clear(message).append(
        el("div", { class: "stack" }, [
          el("div", {
            class: "dim small",
            text:
              `${project.name} doesn't sync with this Overleaf project. ` +
              "Import it as a new publication?",
          }),
          ...renderImportForm(project, overleafProjectId, reload),
        ]),
      );
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  };
  const runSearch = async () => {
    clear(results).append(loading());
    try {
      const projects = await send({
        type: "projects.list",
        searchFor: search.value.trim() || undefined,
        limit: 10,
      });
      clear(results);
      if (!projects.data.length) {
        results.append(el("div", { class: "dim small", text: "No projects" }));
        return;
      }
      for (const project of projects.data) {
        results.append(
          el("div", { class: "row" }, [
            el("div", { class: "grow" }, [
              el("div", {
                text: `${project.owner_account_name}/${project.name}`,
              }),
              el("div", { class: "dim small", text: project.title }),
            ]),
            el("button", {
              class: "action secondary",
              text: "Check",
              onClick: () => void checkProject(project),
            }),
          ]),
        );
      }
    } catch (e) {
      clear(results).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  };
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => void runSearch(), 300);
  });
  body.append(search, results, message);
  await runSearch();
}

function renderImportForm(
  project: ProjectPublic,
  overleafProjectId: string,
  reload: () => void,
): HTMLElement[] {
  const path = el("input", {
    type: "text",
    value: "paper",
    attrs: { autocomplete: "off", "data-lpignore": "true" },
  });
  const kind = el("select");
  for (const [value, label] of [
    ["journal-article", "Journal article"],
    ["conference-paper", "Conference paper"],
    ["report", "Report"],
    ["book", "Book"],
    ["masters-thesis", "Master's thesis"],
    ["phd-thesis", "PhD thesis"],
    ["other", "Other"],
  ]) {
    kind.append(el("option", { value, text: label }));
  }
  const importButton = el("button", {
    class: "action",
    text: "Import and link",
  });
  const message = el("div", { class: "small" });
  importButton.addEventListener("click", async () => {
    importButton.disabled = true;
    clear(message).append(loading("Importing"));
    try {
      await send({
        type: "overleaf.import",
        owner: project.owner_account_name,
        project: project.name,
        overleafProjectUrl: `https://www.overleaf.com/project/${overleafProjectId}`,
        path: path.value.trim(),
        kind: kind.value,
      });
      reload();
    } catch (e) {
      importButton.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  return [
    el("label", { text: "Folder in the project" }),
    path,
    el("label", { text: "Type" }),
    kind,
    el("div", { class: "actions" }, [importButton]),
    message,
  ];
}

async function load(overleafProjectId: string): Promise<void> {
  if (!panel) {
    return;
  }
  const body = panel.body;
  clear(body).append(loading());
  const reload = () => void load(overleafProjectId);
  try {
    hubWebUrl = await getHubWebUrl();
    const links = await send({
      type: "overleaf.links",
      overleafProjectId,
    });
    if (!links.length) {
      await renderPicker(body, overleafProjectId, reload);
      return;
    }
    // A folder in more than one project is rare, so the first link is the
    // one shown, with the rest offered as alternatives underneath
    const link = links[0];
    const statuses = await send({
      type: "overleaf.status",
      owner: link.project_owner_name,
      project: link.project_name,
      overleafProjectId,
      path: link.path,
    });
    if (!statuses.length) {
      clear(body).append(
        el("div", {
          class: "dim small",
          text:
            "The project no longer syncs a folder with this Overleaf " +
            "project. Reload to pick a different project.",
        }),
      );
      return;
    }
    renderStatus(body, link, statuses[0], reload);
    if (links.length > 1) {
      body.append(
        el("div", {
          class: "dim small",
          style: { marginTop: "8px" },
          text: `Also linked from ${links.length - 1} other project(s).`,
        }),
      );
    }
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
    const message = e instanceof Error ? e.message : String(e);
    body.append(errorMessage(message));
    if (message.includes("Overleaf token")) {
      body.append(
        el("div", { class: "dim small", style: { marginTop: "6px" } }, [
          document.createTextNode("Connect Overleaf in your "),
          el("a", {
            text: "Calkit account settings",
            href: `${hubWebUrl}/settings?tab=connected-accounts`,
          }),
          document.createTextNode(" to check sync status."),
        ]),
      );
    }
  }
}

function sync(): void {
  const overleafProjectId = getOverleafProjectId(window.location.href);
  if (!overleafProjectId) {
    panel?.remove();
    panel = null;
    currentProjectId = null;
    return;
  }
  if (panel && overleafProjectId === currentProjectId) {
    return;
  }
  currentProjectId = overleafProjectId;
  panel = mountPanel({ id: PANEL_ID, title: "Calkit" });
  void load(overleafProjectId);
}

// Overleaf is a single-page app, so the project ID can change without a
// navigation the extension would otherwise hear about
let lastUrl = window.location.href;
setInterval(() => {
  if (window.location.href !== lastUrl) {
    lastUrl = window.location.href;
    sync();
  }
}, 1000);

sync();
